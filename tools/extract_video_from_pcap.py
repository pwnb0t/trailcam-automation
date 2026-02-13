#!/usr/bin/env python3
"""Extract video payloads from TrailCam PCAPs and (optionally) mux to MP4.

The TrailCam app "video view/download" flows are not a simple MP4 transfer.
In observed captures, the camera streams video-like payloads over D0 subtype
streams (notably subtype=0x02 and subtype=0x03). The phone app appears to mux
or transcode into an MP4 on-device.

This tool:
- Extracts camera->client `F1 D0` packets for a chosen subtype
- Reassembles in 16-bit sequence order (seq16 = body[2:4], big-endian)
- Writes assembled binary stream(s)
- Attempts to carve an Annex-B H.264 elementary stream and mux to MP4 via ffmpeg

It is intentionally heuristic. The output is meant for iterative reverse
engineering: you can compare carved streams against the known-good MP4 from
Android and improve extraction logic.
"""

from __future__ import annotations

import argparse
import binascii
import json
import os
import shutil
import struct
import subprocess
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple


F1_MAGIC = 0xF1
ARTEMIS_MAGIC = b"ARTEMIS\x00"
AES_V4_KEY_DEFAULT = "xs38nul7cqf7m1va"
V4_PAGE_SIZE = 0x1000
V4_CBC_CRYPT_LEN = 0x60


def _tshark_rows(pcap: str, src: str, dst: str) -> Iterable[Tuple[int, bytes]]:
    cmd = [
        "tshark",
        "-r",
        pcap,
        "-Y",
        f"ip.src=={src} && ip.dst=={dst} && udp && data",
        "-T",
        "fields",
        "-e",
        "frame.number",
        "-e",
        "data",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "tshark failed")
    for line in proc.stdout.splitlines():
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        try:
            frame = int(parts[0])
            payload = binascii.unhexlify(parts[1])
        except Exception:
            continue
        yield frame, payload


def _guess_client_ip(pcap: str, camera_ip: str) -> Optional[str]:
    cmd = [
        "tshark",
        "-r",
        pcap,
        "-Y",
        "udp && data && data[0]==f1",
        "-T",
        "fields",
        "-e",
        "ip.src",
        "-e",
        "ip.dst",
    ]
    try:
        out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL).decode("utf-8", errors="replace")
    except Exception:
        return None
    c: Counter[str] = Counter()
    for line in out.splitlines():
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        s, d = parts[0], parts[1]
        if s and s != camera_ip:
            c[s] += 1
        if d and d != camera_ip:
            c[d] += 1
    if not c:
        return None
    return c.most_common(1)[0][0]


@dataclass
class ChunkStats:
    total_pkts: int
    unique_seqs: int
    dup_pkts: int
    min_seq: int
    max_seq: int
    missing_seq_count: int


def extract_d0_subtype_chunks_seq16(
    pcap: str,
    src: str,
    dst: str,
    subtype: int,
) -> Tuple[Dict[int, bytes], ChunkStats]:
    chunks: Dict[int, bytes] = {}
    seen: Counter[int] = Counter()
    total = 0
    for _frame, pkt in _tshark_rows(pcap, src, dst):
        if len(pkt) < 8 or pkt[0] != F1_MAGIC or pkt[1] != 0xD0:
            continue
        body_len = struct.unpack("!H", pkt[2:4])[0]
        if len(pkt) < 4 + body_len:
            continue
        body = pkt[4 : 4 + body_len]
        if len(body) < 4 or body[0] != 0xD1 or body[1] != subtype:
            continue
        seq16 = (body[2] << 8) | body[3]
        total += 1
        seen[seq16] += 1
        # Keep first seen chunk for a given seq; retransmits are common.
        if seq16 not in chunks:
            chunks[seq16] = body[4:]

    if not chunks:
        raise RuntimeError(f"No camera->client D0 subtype=0x{subtype:02x} packets found for {src}->{dst}")

    min_seq = min(chunks)
    max_seq = max(chunks)
    missing = 0
    for s in range(min_seq, max_seq + 1):
        if s not in chunks:
            missing += 1

    stats = ChunkStats(
        total_pkts=total,
        unique_seqs=len(chunks),
        dup_pkts=total - len(chunks),
        min_seq=min_seq,
        max_seq=max_seq,
        missing_seq_count=missing,
    )
    return chunks, stats


def parse_artemis_records_strict(blob: bytes) -> List[Tuple[int, int, int, bytes]]:
    out: List[Tuple[int, int, int, bytes]] = []
    pos = 0
    while True:
        i = blob.find(ARTEMIS_MAGIC, pos)
        if i == -1 or i + 20 > len(blob):
            break
        ver = int.from_bytes(blob[i + 8 : i + 12], "little")
        typ = int.from_bytes(blob[i + 12 : i + 16], "little")
        ln = int.from_bytes(blob[i + 16 : i + 20], "little")
        j = i + 20 + ln
        if ln <= 0 or j > len(blob):
            pos = i + 1
            continue
        out.append((i, ver, typ, blob[i + 20 : j]))
        pos = j
    return out


@dataclass
class ArtemisV4Header:
    # These are empirical offsets from captures; the camera appears to prepend
    # a fixed header to the "real" media bytes. We treat this as a black box
    # but extract a few fields that are consistent across records.
    header_len: int
    pts_ms: int
    data_len: int
    width: int
    height: int
    data_len_off: int
    session_no: int
    seed_u32_0: int
    seed_u32_1: int


def _u32le(b: bytes) -> int:
    return int.from_bytes(b, "little", signed=False)


def parse_artemis_v4_header(payload: bytes) -> Optional[ArtemisV4Header]:
    """Parse the empirical ver=4 payload header.

    Observed invariant for most ver=4 video payloads:
    - header is 108 bytes
    - data_len at offset 16 is little-endian u32
    - data_len == len(payload) - 108
    - width/height at offsets 28/32
    - a pts-like value at offset 8 (ms)
    """
    if len(payload) < 108:
        return None
    header_len = 108
    # In capture t8_3 video subtype=0x02, we observed two record families:
    # - video-like: data_len stored at offset 16, bigger blobs (KBs..hundreds of KB)
    # - audio-like?: data_len stored at offset 20, tiny blobs (~150..600B)
    data_len = _u32le(payload[16:20])
    data_len_off = 16
    if not (data_len > 0 and data_len == (len(payload) - header_len)):
        data_len = _u32le(payload[20:24])
        data_len_off = 20
        if not (data_len > 0 and data_len == (len(payload) - header_len)):
            return None
    pts_ms = _u32le(payload[8:12])
    width = _u32le(payload[28:32])
    height = _u32le(payload[32:36])
    session_no = _u32le(payload[48:52]) if len(payload) >= 56 else 0
    seed_u32_0 = _u32le(payload[64:68]) if len(payload) >= 72 else 0
    seed_u32_1 = _u32le(payload[68:72]) if len(payload) >= 72 else 0
    return ArtemisV4Header(
        header_len=header_len,
        pts_ms=pts_ms,
        data_len=data_len,
        width=width,
        height=height,
        data_len_off=data_len_off,
        session_no=session_no,
        seed_u32_0=seed_u32_0,
        seed_u32_1=seed_u32_1,
    )


def _aes_128_cbc_decrypt(key16: bytes, iv16: bytes, data: bytes) -> bytes:
    # Selectively decrypting ver=4 record data requires AES-CBC. We use cryptography if available.
    try:
        from cryptography.hazmat.backends import default_backend
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    except Exception as e:  # pragma: no cover
        raise RuntimeError(
            "AES decrypt requires python 'cryptography' package (pip install cryptography)."
        ) from e

    if len(key16) != 16 or len(iv16) != 16:
        raise ValueError("AES-128-CBC requires 16-byte key and 16-byte IV")
    if len(data) % 16 != 0:
        raise ValueError("AES-CBC decrypt input must be a multiple of 16 bytes")

    cipher = Cipher(algorithms.AES(key16), modes.CBC(iv16), backend=default_backend())
    dec = cipher.decryptor()
    return dec.update(data) + dec.finalize()


def decrypt_v4_data_in_pages(
    data: bytes,
    *,
    key16: bytes,
    iv16: bytes,
    page_size: int = V4_PAGE_SIZE,
    crypt_len: int = V4_CBC_CRYPT_LEN,
) -> bytes:
    """Decrypt ver=4 record data as observed in trailcam_8-3 view/download-video.

    Empirical:
    - Data is mostly plaintext.
    - At the start of each 0x1000 page, the first 0x60 bytes are AES-128-CBC encrypted.
    - The remaining bytes in the page are plaintext.

    We decrypt only full `crypt_len` chunks; if the tail is shorter, we decrypt the
    largest multiple-of-16 prefix and leave the remainder untouched.
    """
    if page_size <= 0 or crypt_len <= 0:
        return data
    if crypt_len % 16 != 0:
        raise ValueError("crypt_len must be a multiple of 16 bytes for AES-CBC")

    out = bytearray(data)
    for off in range(0, len(out), page_size):
        chunk = bytes(out[off : off + crypt_len])
        if not chunk:
            continue
        if len(chunk) < 16:
            continue
        if len(chunk) % 16 != 0:
            chunk = chunk[: (len(chunk) // 16) * 16]
        if len(chunk) <= 0:
            continue
        dec = _aes_128_cbc_decrypt(key16, iv16, chunk)
        out[off : off + len(dec)] = dec
    return bytes(out)


def _looks_like_annexb_h264(data: bytes) -> bool:
    return b"\x00\x00\x00\x01" in data or b"\x00\x00\x01" in data


def _looks_like_adts(data: bytes) -> bool:
    # ADTS syncword: 0xFFF (12 bits). Common first two bytes: FF F1/FF F9.
    if len(data) < 2:
        return False
    return data[0] == 0xFF and (data[1] & 0xF0) == 0xF0


def _looks_like_h264_nal_hdr(b0: int) -> bool:
    if b0 & 0x80:
        return False
    nal_type = b0 & 0x1F
    return nal_type in {1, 5, 6, 7, 8, 9, 10, 11, 12}


def len16_be_nals_to_annexb_best_effort(
    data: bytes,
    start_scan_max: int = 32,
    min_coverage_ratio: float = 0.20,
) -> Tuple[bytes, Counter[int], int, int]:
    """Decode a per-record bytestream of (len16be + nal) to Annex-B.

    Empirical: t8_3 subtype=0x02 ver=4 records appear to carry H.264-like NALs with a 2-byte
    big-endian length prefix (not 4-byte AVCC, and not Annex-B).

    Returns: (annexb_bytes, nal_type_counts, units, start_offset). If decoding fails, annexb_bytes is empty.
    """

    def decode_from(start: int) -> Tuple[bytes, Counter[int], int, int]:
        i = start
        out = bytearray()
        c: Counter[int] = Counter()
        units = 0
        consumed = 0
        while i + 3 <= len(data):
            ln = int.from_bytes(data[i : i + 2], "big")
            if ln <= 0 or i + 2 + ln > len(data):
                break
            b0 = data[i + 2]
            if not _looks_like_h264_nal_hdr(b0):
                break
            out += b"\x00\x00\x00\x01"
            out += data[i + 2 : i + 2 + ln]
            c[b0 & 0x1F] += 1
            units += 1
            i += 2 + ln
            consumed = i - start
        return bytes(out), c, units, consumed

    best: Optional[Tuple[int, bytes, Counter[int], int, int]] = None
    for start in range(0, min(start_scan_max, len(data)) + 1):
        out, c, units, consumed = decode_from(start)
        if units <= 0:
            continue
        if consumed < int(len(data) * min_coverage_ratio):
            continue
        score = consumed
        if best is None or score > best[0]:
            best = (score, out, c, units, start)

    if best is None:
        return b"", Counter(), 0, -1
    return best[1], best[2], best[3], best[4]


def _find_first_h264_start(blob: bytes) -> int:
    # Prefer 00 00 00 01, else accept 00 00 01.
    i = blob.find(b"\x00\x00\x00\x01")
    if i != -1:
        return i
    j = blob.find(b"\x00\x00\x01")
    return j


def carve_h264_annexb(blob: bytes) -> Optional[bytes]:
    i = _find_first_h264_start(blob)
    if i == -1:
        return None
    # Heuristic: return everything from first start code onwards.
    return blob[i:]


def avcc_like_to_annexb(payload: bytes) -> Tuple[bytes, Counter[int]]:
    """Convert length-prefixed H.264 NAL units within a payload to Annex-B.

    The video record payloads we see are not plain Annex-B. They commonly contain:
    - A record-specific header (we usually skip the first 72 bytes)
    - A small additional prefix (often ~33 bytes)
    - A sequence of NAL units prefixed by a 4-byte big-endian length

    This function heuristically finds the first valid (len + nal_hdr) and then
    parses sequentially, emitting 00 00 00 01 + nal for each unit.
    """
    # Heuristic: skip the common 72-byte header when present.
    data = payload[72:] if len(payload) > 72 else payload

    def looks_like_nal(hdr: int) -> bool:
        # H.264: forbidden_zero_bit must be 0, nal_type in 1..12ish.
        if hdr & 0x80:
            return False
        nal_type = hdr & 0x1F
        return nal_type in {1, 5, 6, 7, 8, 9, 10, 11, 12}

    start = None
    for i in range(0, max(0, len(data) - 5)):
        ln = int.from_bytes(data[i : i + 4], "big")
        if ln <= 0 or ln > 500_000:
            continue
        if i + 4 + ln > len(data):
            continue
        hdr = data[i + 4]
        if looks_like_nal(hdr):
            start = i
            break

    if start is None:
        return b"", Counter()

    out = bytearray()
    nal_counts: Counter[int] = Counter()
    i = start
    while i + 5 <= len(data):
        ln = int.from_bytes(data[i : i + 4], "big")
        if ln <= 0 or ln > 500_000 or i + 4 + ln > len(data):
            break
        hdr = data[i + 4]
        if not looks_like_nal(hdr):
            break
        nal_type = hdr & 0x1F
        nal_counts[nal_type] += 1
        out += b"\x00\x00\x00\x01"
        out += data[i + 4 : i + 4 + ln]
        i += 4 + ln

    return bytes(out), nal_counts


def scan_avcc_stream_to_annexb(
    stream: bytes,
    max_len: int = 200_000,
    allowed_nal_types: set[int] | None = None,
) -> Tuple[bytes, Counter[int], int]:
    """Scan a bytestream for (len32be + nal) patterns and convert to Annex-B.

    This is a resynchronizing heuristic intended for streams where NAL units can
    be split or surrounded by other bytes. It prefers recall over precision.

    Returns: (annexb_bytes, nal_type_counts, hit_count)
    """
    if allowed_nal_types is None:
        allowed_nal_types = {1, 5, 6, 7, 8, 9}

    def looks_like_nal(hdr: int) -> bool:
        if hdr & 0x80:
            return False
        return (hdr & 0x1F) in allowed_nal_types

    out = bytearray()
    c: Counter[int] = Counter()
    hits = 0
    i = 0
    while i + 5 <= len(stream):
        ln = int.from_bytes(stream[i : i + 4], "big")
        if 0 < ln <= max_len and i + 4 + ln <= len(stream):
            hdr = stream[i + 4]
            if looks_like_nal(hdr):
                hits += 1
                c[hdr & 0x1F] += 1
                out += b"\x00\x00\x00\x01"
                out += stream[i + 4 : i + 4 + ln]
                i += 4 + ln
                continue
        i += 1
    return bytes(out), c, hits


def try_ffmpeg_mux(h264_path: Path, mp4_path: Path, fps: int) -> bool:
    if shutil.which("ffmpeg") is None:
        return False
    cmd = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-r",
        str(fps),
        "-i",
        str(h264_path),
        "-c",
        "copy",
        str(mp4_path),
    ]
    p = subprocess.run(cmd, capture_output=True, text=True)
    return p.returncode == 0 and mp4_path.exists() and mp4_path.stat().st_size > 0


def try_ffmpeg_mux_h264_aac(
    h264_path: Path,
    aac_adts_path: Path,
    mp4_path: Path,
    fps: int,
) -> bool:
    if shutil.which("ffmpeg") is None:
        return False
    cmd = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-r",
        str(fps),
        "-i",
        str(h264_path),
        "-i",
        str(aac_adts_path),
        "-c",
        "copy",
        "-bsf:a",
        "aac_adtstoasc",
        str(mp4_path),
    ]
    p = subprocess.run(cmd, capture_output=True, text=True)
    return p.returncode == 0 and mp4_path.exists() and mp4_path.stat().st_size > 0


def _parse_annexb_nals(stream: bytes) -> List[bytes]:
    """Split an Annex-B bytestream into NAL units (without start codes)."""
    nals: List[bytes] = []
    i = 0
    starts: List[int] = []
    while True:
        j = stream.find(b"\x00\x00\x00\x01", i)
        if j == -1:
            break
        starts.append(j)
        i = j + 1
    for idx, s in enumerate(starts):
        start = s + 4
        end = starts[idx + 1] if idx + 1 < len(starts) else len(stream)
        if end > start:
            nals.append(stream[start:end])
    return nals


def extract_h264_annexb_from_payload(payload: bytes) -> Tuple[bytes, Counter[int]]:
    """Heuristically extract H.264 Annex-B from a single ARTEMIS payload.

    Strategy:
    1. If payload contains Annex-B start codes, return them directly.
    2. Else treat it as AVCC-like: find a plausible (len32be + nal) start and parse sequentially.
       We require at least 1 slice NAL and at least 2 NAL units to reduce false positives.
    """
    # Skip the common per-record header when present. For video records, the first NAL often starts at
    # offset 33 within payload[72:].
    bases: List[bytes] = []
    if len(payload) > 105:
        bases.append(payload[105:])
    if len(payload) > 72:
        bases.append(payload[72:])
    bases.append(payload)

    for base in bases:
        # 1) direct Annex-B
        if b"\x00\x00\x00\x01" in base:
            # Basic sanity: ensure we have at least one slice NAL.
            nals = _parse_annexb_nals(base)
            if not nals:
                continue
            c: Counter[int] = Counter((n[0] & 0x1F) for n in nals if n)
            if any(t in c for t in (1, 5)):
                return base, c

        # 2) AVCC-like
        seg, c = avcc_like_to_annexb(base)
        if not seg:
            continue
        # Validate: at least 2 NALs and at least one slice.
        if sum(c.values()) >= 2 and any(t in c for t in (1, 5)):
            return seg, c

    return b"", Counter()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("pcap", help="Input PCAP")
    ap.add_argument("--camera-ip", default="192.168.43.1", help="Camera IP (default: %(default)s)")
    ap.add_argument("--client-ip", default="", help="Client IP (default: auto-detect)")
    ap.add_argument(
        "--subtypes",
        default="0x02,0x03",
        help="Comma-separated D0 subtypes to extract (default: %(default)s)",
    )
    ap.add_argument("--out-dir", default="out/video_extract", help="Output directory root")
    ap.add_argument("--fps", type=int, default=30, help="FPS hint for ffmpeg mux (default: %(default)s)")
    ap.add_argument("--mux", action="store_true", help="Attempt ffmpeg mux of carved H264 into MP4")
    ap.add_argument(
        "--v4-header",
        action="store_true",
        help="For ver=4 ARTEMIS records, parse and strip the 108-byte header and use header data_len",
    )
    ap.add_argument(
        "--v4-decrypt",
        action="store_true",
        help=f"Decrypt ver=4 record data (AES-128-CBC, key={AES_V4_KEY_DEFAULT!r}, per-0x1000-page first-0x60 bytes). Requires --v4-header.",
    )
    ap.add_argument(
        "--v4-aes-key",
        default=AES_V4_KEY_DEFAULT,
        help="AES key for --v4-decrypt (default: %(default)s)",
    )
    args = ap.parse_args()

    if args.v4_decrypt and not args.v4_header:
        print("--v4-decrypt requires --v4-header (so we can locate ver=4 record data accurately).")
        return 2

    pcap = args.pcap
    if not os.path.exists(pcap):
        print(f"pcap not found: {pcap}")
        return 2

    camera_ip = args.camera_ip
    client_ip = args.client_ip.strip() or _guess_client_ip(pcap, camera_ip=camera_ip)
    if not client_ip:
        print("Failed to auto-detect --client-ip; please pass it explicitly.")
        return 2

    try:
        subtypes = [int(x.strip(), 0) for x in args.subtypes.split(",") if x.strip()]
    except Exception:
        print(f"Invalid --subtypes: {args.subtypes}")
        return 2

    out_root = Path(args.out_dir) / Path(pcap).stem
    out_root.mkdir(parents=True, exist_ok=True)

    summary: Dict[str, object] = {
        "pcap": pcap,
        "camera_ip": camera_ip,
        "client_ip": client_ip,
        "subtypes": [f"0x{s:02x}" for s in subtypes],
    }

    all_records: Dict[str, List[Dict[str, int]]] = {}
    carved_h264_paths: List[Path] = []

    for st in subtypes:
        chunks, stats = extract_d0_subtype_chunks_seq16(pcap, src=camera_ip, dst=client_ip, subtype=st)
        assembled = b"".join(chunks[k] for k in sorted(chunks))
        asm_path = out_root / f"subtype_{st:02x}_assembled.bin"
        asm_path.write_bytes(assembled)

        st_key = f"0x{st:02x}"
        summary[f"subtype_{st:02x}_stats"] = stats.__dict__
        summary[f"subtype_{st:02x}_assembled_bytes"] = len(assembled)
        summary[f"subtype_{st:02x}_assembled_path"] = str(asm_path)

        recs = parse_artemis_records_strict(assembled)
        all_records[st_key] = [{"ver": v, "typ": t, "len": len(p)} for _off, v, t, p in recs]

        rec_dir = out_root / f"subtype_{st:02x}_records"
        rec_dir.mkdir(parents=True, exist_ok=True)
        for idx, (_off, ver, typ, payload) in enumerate(recs, 1):
            (rec_dir / f"record_{idx:04d}_ver{ver}_typ{typ}_{len(payload)}.bin").write_bytes(payload)

        # Concatenate "data portion" across records.
        # For subtype=0x02 in video flows, payload ver=4 appears to use a fixed
        # 108-byte header; the actual media bytes are payload[108:].
        concat_data_v4 = bytearray()
        concat_guess72 = bytearray()
        concat_guess105 = bytearray()
        v4_meta_lines: List[str] = []
        v4_hdr_ok = 0
        v4_hdr_fail = 0
        v4_video_annexb = bytearray()
        v4_audio_adts = bytearray()
        for idx, (_off, ver, typ, payload) in enumerate(recs, 1):
            if len(payload) > 72:
                concat_guess72 += payload[72:]
            if len(payload) > 105:
                concat_guess105 += payload[105:]

            if not args.v4_header or ver != 4:
                continue
            hdr = parse_artemis_v4_header(payload)
            if hdr is None:
                v4_hdr_fail += 1
                continue
            v4_hdr_ok += 1
            data = payload[hdr.header_len : hdr.header_len + hdr.data_len]

            # Optional decrypt of the page-prefix bytes. For t8_3 video playback/download, this
            # transforms the data into something ffmpeg can consume (video becomes Annex-B H.264,
            # audio becomes ADTS AAC).
            if args.v4_decrypt:
                key16 = args.v4_aes_key.encode("ascii", errors="strict")
                iv16 = b"\x00" * 16
                data = decrypt_v4_data_in_pages(data, key16=key16, iv16=iv16)

            concat_data_v4 += data
            kind = "unknown"
            if hdr.data_len_off == 16:
                kind = "v16_video_like"
            elif hdr.data_len_off == 20:
                kind = "v20_small_like"

            # For subtype=0x02, t8_3 ver=4 records appear to alternate between:
            # - video-like records (width/height set, data_len_off=16) containing Annex-B H.264
            # - audio-like records (width/height 0, data_len_off=20) containing ADTS AAC frames
            if args.v4_decrypt and ver == 4:
                if kind == "v16_video_like":
                    v4_video_annexb += data
                elif kind == "v20_small_like":
                    v4_audio_adts += data

            v4_meta_lines.append(
                ",".join(
                    [
                        str(idx),
                        str(typ),
                        str(len(payload)),
                        str(hdr.pts_ms),
                        str(hdr.data_len),
                        str(hdr.width),
                        str(hdr.height),
                        str(hdr.session_no),
                        str(hdr.seed_u32_0),
                        str(hdr.seed_u32_1),
                        str(hdr.data_len_off),
                        kind,
                    ]
                )
            )

        concat72 = bytes(concat_guess72)
        concat105 = bytes(concat_guess105)
        (out_root / f"subtype_{st:02x}_concat_payload72.bin").write_bytes(concat72)
        (out_root / f"subtype_{st:02x}_concat_payload105.bin").write_bytes(concat105)
        summary[f"subtype_{st:02x}_concat_payload72_bytes"] = len(concat72)
        summary[f"subtype_{st:02x}_concat_payload105_bytes"] = len(concat105)

        if args.v4_header and concat_data_v4:
            v4_path = out_root / f"subtype_{st:02x}_concat_v4_data.bin"
            v4_path.write_bytes(bytes(concat_data_v4))
            summary[f"subtype_{st:02x}_concat_v4_data_bytes"] = len(concat_data_v4)
            summary[f"subtype_{st:02x}_concat_v4_data_path"] = str(v4_path)
            summary[f"subtype_{st:02x}_v4_header_ok"] = v4_hdr_ok
            summary[f"subtype_{st:02x}_v4_header_fail"] = v4_hdr_fail
            meta_path = out_root / f"subtype_{st:02x}_v4_records.csv"
            meta_path.write_text(
                "record_idx,typ,payload_len,pts_ms,data_len,width,height,session_no,seed_u32_0,seed_u32_1,data_len_off,kind\n"
                + "\n".join(v4_meta_lines)
                + ("\n" if v4_meta_lines else "")
            )
            summary[f"subtype_{st:02x}_v4_records_csv"] = str(meta_path)

            # Attempt to reconstruct H.264 Annex-B from the "video-like" ver=4 records by decoding
            # (len16be + nal) units per record and concatenating. This has been sufficient to get
            # ffprobe to recognize the stream for t8_3 captures.
            if st == 0x02:
                video_out = bytearray()
                video_counts: Counter[int] = Counter()
                video_records_used = 0
                video_units_total = 0
                for _idx, (_off, ver, _typ, payload) in enumerate(recs, 1):
                    if ver != 4:
                        continue
                    hdr = parse_artemis_v4_header(payload)
                    if hdr is None or hdr.data_len_off != 16:
                        continue
                    data = payload[hdr.header_len : hdr.header_len + hdr.data_len]
                    annexb, c, units, _start = len16_be_nals_to_annexb_best_effort(
                        data,
                        start_scan_max=32,
                        min_coverage_ratio=0.20,
                    )
                    if not annexb:
                        continue
                    video_records_used += 1
                    video_units_total += units
                    video_counts.update(c)
                    video_out += annexb

                if video_out:
                    h264_path = out_root / "subtype_02_v4_len16.h264"
                    h264_path.write_bytes(bytes(video_out))
                    carved_h264_paths.append(h264_path)
                    summary["subtype_02_v4_len16_h264_bytes"] = len(video_out)
                    summary["subtype_02_v4_len16_h264_path"] = str(h264_path)
                    summary["subtype_02_v4_len16_records_used"] = video_records_used
                    summary["subtype_02_v4_len16_units_total"] = video_units_total
                    summary["subtype_02_v4_len16_nal_counts"] = {str(k): int(v) for k, v in sorted(video_counts.items())}

        # Heuristic "AVCC-like" extraction: convert length-prefixed NALs to Annex-B.
        # Most useful for subtype=0x02 in video flows.
        annexb_segs: List[bytes] = []
        annexb_counts: Counter[int] = Counter()
        for _off, _ver, _typ, payload in recs:
            seg, c = avcc_like_to_annexb(payload)
            if seg:
                annexb_segs.append(seg)
                annexb_counts.update(c)
        if annexb_segs:
            cat = b"".join(annexb_segs)
            h264p = out_root / f"subtype_{st:02x}_annexb_avcc.h264"
            h264p.write_bytes(cat)
            carved_h264_paths.append(h264p)
            summary[f"subtype_{st:02x}_annexb_avcc_h264_bytes"] = len(cat)
            summary[f"subtype_{st:02x}_annexb_avcc_h264_path"] = str(h264p)
            summary[f"subtype_{st:02x}_annexb_avcc_nal_counts"] = {str(k): int(v) for k, v in sorted(annexb_counts.items())}

        # Record-by-record H.264 extraction (preferred).
        # This avoids relying on resynchronizing scans across mixed record payloads.
        sps: Optional[bytes] = None
        pps: Optional[bytes] = None
        out_annexb = bytearray()
        out_counts: Counter[int] = Counter()
        record_hits = 0
        for _off, _ver, _typ, payload in recs:
            seg, c = extract_h264_annexb_from_payload(payload)
            if not seg:
                continue
            record_hits += 1
            # Track parameter sets.
            for nal in _parse_annexb_nals(seg):
                if not nal:
                    continue
                nt = nal[0] & 0x1F
                if nt == 7 and sps is None:
                    sps = nal
                elif nt == 8 and pps is None:
                    pps = nal

            # If this access unit contains an IDR but lacks SPS/PPS, prepend the known sets.
            has_idr = (5 in c)
            has_sps = (7 in c)
            has_pps = (8 in c)
            if has_idr and sps and pps and not (has_sps and has_pps):
                out_annexb += b"\x00\x00\x00\x01" + sps
                out_annexb += b"\x00\x00\x00\x01" + pps

            out_annexb += seg
            out_counts.update(c)

        if out_annexb:
            h264p = out_root / f"subtype_{st:02x}_annexb_records.h264"
            h264p.write_bytes(bytes(out_annexb))
            carved_h264_paths.append(h264p)
            summary[f"subtype_{st:02x}_annexb_records_h264_bytes"] = len(out_annexb)
            summary[f"subtype_{st:02x}_annexb_records_record_hits"] = record_hits
            summary[f"subtype_{st:02x}_annexb_records_nal_counts"] = {str(k): int(v) for k, v in sorted(out_counts.items())}

        # Heuristic scan across concatenated payload fragments.
        scan_out, scan_counts, scan_hits = scan_avcc_stream_to_annexb(concat105, max_len=200_000)
        if scan_out:
            h264p = out_root / f"subtype_{st:02x}_annexb_scan_payload105.h264"
            h264p.write_bytes(scan_out)
            carved_h264_paths.append(h264p)
            summary[f"subtype_{st:02x}_annexb_scan_payload105_bytes"] = len(scan_out)
            summary[f"subtype_{st:02x}_annexb_scan_payload105_hits"] = scan_hits
            summary[f"subtype_{st:02x}_annexb_scan_payload105_nal_counts"] = {str(k): int(v) for k, v in sorted(scan_counts.items())}

        # Carve H264 from assembled stream and from record payloads.
        h264_raw = carve_h264_annexb(assembled)
        if h264_raw:
            h264_path = out_root / f"subtype_{st:02x}_carved_raw.h264"
            h264_path.write_bytes(h264_raw)
            carved_h264_paths.append(h264_path)
            summary[f"subtype_{st:02x}_carved_raw_h264_bytes"] = len(h264_raw)
            summary[f"subtype_{st:02x}_carved_raw_h264_path"] = str(h264_path)

        # Record-level carving (concat only segments that have startcodes).
        segs: List[bytes] = []
        for _off, _ver, _typ, payload in recs:
            seg = carve_h264_annexb(payload)
            if seg:
                segs.append(seg)
        if segs:
            cat = b"".join(segs)
            h264p = out_root / f"subtype_{st:02x}_carved_records.h264"
            h264p.write_bytes(cat)
            carved_h264_paths.append(h264p)
            summary[f"subtype_{st:02x}_carved_records_h264_bytes"] = len(cat)
            summary[f"subtype_{st:02x}_carved_records_h264_path"] = str(h264p)

        if args.mux and carved_h264_paths:
            # Try mux the most recent carved stream.
            src_h264 = carved_h264_paths[-1]
            mp4_path = out_root / f"{src_h264.stem}_fps{args.fps}.mp4"
            ok = try_ffmpeg_mux(src_h264, mp4_path, fps=args.fps)
            summary[f"mux_{src_h264.name}"] = {"ok": ok, "mp4": str(mp4_path)}

        # If we decrypted ver=4 records, write the derived elementary streams and optionally mux.
        if args.v4_decrypt and v4_video_annexb:
            h264p = out_root / f"subtype_{st:02x}_v4_decrypted.h264"
            h264p.write_bytes(bytes(v4_video_annexb))
            summary[f"subtype_{st:02x}_v4_decrypted_h264_bytes"] = len(v4_video_annexb)
            summary[f"subtype_{st:02x}_v4_decrypted_h264_path"] = str(h264p)

            if v4_audio_adts:
                aacp = out_root / f"subtype_{st:02x}_v4_decrypted.aac"
                aacp.write_bytes(bytes(v4_audio_adts))
                summary[f"subtype_{st:02x}_v4_decrypted_aac_bytes"] = len(v4_audio_adts)
                summary[f"subtype_{st:02x}_v4_decrypted_aac_path"] = str(aacp)

                if args.mux:
                    mp4p = out_root / f"subtype_{st:02x}_v4_decrypted_fps{args.fps}.mp4"
                    ok = try_ffmpeg_mux_h264_aac(h264p, aacp, mp4p, fps=args.fps)
                    summary[f"mux_{mp4p.name}"] = {"ok": ok, "mp4": str(mp4p)}

    summary_path = out_root / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True))

    recs_path = out_root / "artemis_records.json"
    recs_path.write_text(json.dumps(all_records, indent=2, sort_keys=True))

    print(f"wrote: {summary_path}")
    print(f"wrote: {recs_path}")
    print(f"out: {out_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
