import base64
import json
import struct
from collections import Counter
from typing import Dict, List, Optional, Tuple

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from src.constants import AES_CMD_IV, AES_CMD_KEY

V4_PAGE_SIZE = 0x1000
V4_PAGE_AES_CBC_PREFIX_LEN = 0x60


def unpack_f1(pkt: bytes) -> Optional[Tuple[int, bytes, int]]:
    if len(pkt) < 4 or pkt[0] != 0xF1:
        return None
    opcode = pkt[1]
    blen = struct.unpack("!H", pkt[2:4])[0]
    if len(pkt) < 4 + blen:
        return None
    body = pkt[4 : 4 + blen]
    return opcode, body, blen


def make_ack_body_seq_list16(subtype: int, seqs16: List[int]) -> bytes:
    """Build an ACK body (inner D1 frame) containing a list of 16-bit sequence values."""
    seqs = sorted(set(seqs16))
    count = len(seqs) & 0xFF
    seq16 = b"".join(struct.pack(">H", s & 0xFFFF) for s in seqs)
    return bytes([0xD1, subtype & 0xFF, 0x00, count]) + seq16


def make_ack_body_seq_window16(subtype: int, seqs16_ordered: List[int]) -> bytes:
    # Keep last-seen unique sequence numbers while preserving order.
    uniq_rev: List[int] = []
    seen = set()
    for s in reversed(seqs16_ordered):
        s16 = int(s) & 0xFFFF
        if s16 in seen:
            continue
        seen.add(s16)
        uniq_rev.append(s16)
    seqs = list(reversed(uniq_rev))
    count = min(len(seqs), 0xFF)
    seq16 = b"".join(struct.pack(">H", s & 0xFFFF) for s in seqs[-count:])
    return bytes([0xD1, subtype & 0xFF, 0x00, count]) + seq16


def make_ack_body_seq16(seqs16: List[int]) -> bytes:
    # Historical helper for subtype 0x04. Prefer make_ack_body_seq_list16(subtype, seqs16).
    return make_ack_body_seq_list16(0x04, seqs16)


def parse_artemis_records(assembled: bytes):
    out = []
    pos = 0
    while True:
        i = assembled.find(b"ARTEMIS\x00", pos)
        if i == -1:
            break
        if i + 20 > len(assembled):
            break
        ver = int.from_bytes(assembled[i + 8 : i + 12], "little")
        typ = int.from_bytes(assembled[i + 12 : i + 16], "little")
        ln = int.from_bytes(assembled[i + 16 : i + 20], "little")
        payload = assembled[i + 20 : i + 20 + ln]
        out.append((ver, typ, payload))
        pos = i + 1
    return out


def parse_artemis_records_strict(assembled: bytes):
    """Parse ARTEMIS records by advancing to the end of each record.

    The download data channels can contain repeated/multiple ARTEMIS records back-to-back.
    Using an overlapping scan (pos=i+1) can create false matches and corrupt extraction.
    """
    out = []
    pos = 0
    while True:
        i = assembled.find(b"ARTEMIS\x00", pos)
        if i == -1:
            break
        if i + 20 > len(assembled):
            break
        ver = int.from_bytes(assembled[i + 8 : i + 12], "little")
        typ = int.from_bytes(assembled[i + 12 : i + 16], "little")
        ln = int.from_bytes(assembled[i + 16 : i + 20], "little")
        j = i + 20 + ln
        if ln <= 0 or j > len(assembled):
            pos = i + 1
            continue
        payload = assembled[i + 20 : j]
        out.append((ver, typ, payload))
        pos = j
    return out


def _pad16(b: bytes) -> bytes:
    pad = (-len(b)) % 16
    if pad:
        b += b"\x00" * pad
    return b


def encrypt_cmd_json(obj: Dict) -> bytes:
    js = json.dumps(obj, separators=(",", ":")).encode("utf-8")
    pt = _pad16(js)
    cipher = Cipher(algorithms.AES(AES_CMD_KEY), modes.CBC(AES_CMD_IV), backend=default_backend())
    enc = cipher.encryptor()
    ct = enc.update(pt) + enc.finalize()
    return base64.b64encode(ct)


def decrypt_cmd_b64(b64: bytes) -> Optional[Dict]:
    def try_decode(candidate: bytes) -> Optional[Dict]:
        try:
            ct = base64.b64decode(candidate)
        except Exception:
            return None
        if len(ct) % 16 != 0:
            ct = ct[: len(ct) - (len(ct) % 16)]
            if not ct:
                return None
        cipher = Cipher(algorithms.AES(AES_CMD_KEY), modes.CBC(AES_CMD_IV), backend=default_backend())
        dec = cipher.decryptor()
        pt = dec.update(ct) + dec.finalize()
        pt = pt.rstrip(b"\x00")
        start = pt.find(b"{")
        end = pt.rfind(b"}")
        if start == -1 or end == -1 or end <= start:
            return None
        try:
            return json.loads(pt[start : end + 1].decode("utf-8", errors="replace"))
        except Exception:
            return None

    try:
        allowed = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/="
        cleaned = bytearray()
        for ch in b64:
            if ch in allowed:
                cleaned.append(ch)
            elif cleaned:
                break
        b64 = bytes(cleaned).strip()
        if not b64:
            return None
    except Exception:
        return None

    candidates = [b64]
    if b"=" in b64:
        candidates.append(b64[: b64.rfind(b"=") + 1])
    if len(b64) % 4 != 0:
        candidates.append(b64[: len(b64) - (len(b64) % 4)])

    for cand in candidates:
        obj = try_decode(cand)
        if obj:
            return obj

    try:
        import re

        for m in re.findall(rb"[A-Za-z0-9+/=]{32,}", b64):
            extra = [m]
            if b"=" in m:
                extra.append(m[: m.rfind(b"=") + 1])
            for cand in extra:
                obj = try_decode(cand)
                if obj:
                    return obj
    except Exception:
        pass
    return None


def decrypt_payload_b64_bytes(payload: bytes) -> Optional[Dict]:
    # Similar to decrypt_cmd_b64 but works on raw ARTEMIS payload bytes
    try:
        if b"\x00" in payload:
            payload = payload.split(b"\x00", 1)[0]
        allowed = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/="
        cleaned = bytearray()
        for ch in payload:
            if ch in allowed:
                cleaned.append(ch)
            elif cleaned:
                break
        if not cleaned:
            return None
        b64 = bytes(cleaned)
        pad = (-len(b64)) % 4
        b64 += b"=" * pad
        ct = base64.b64decode(b64)
    except Exception:
        return None
    if len(ct) % 16 != 0:
        ct = ct[: len(ct) - (len(ct) % 16)]
        if not ct:
            return None
    cipher = Cipher(algorithms.AES(AES_CMD_KEY), modes.CBC(AES_CMD_IV), backend=default_backend())
    dec = cipher.decryptor()
    pt = dec.update(ct) + dec.finalize()
    pt = pt.rstrip(b"\x00")
    start = pt.find(b"{")
    end = pt.rfind(b"}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        return json.loads(pt[start : end + 1].decode("utf-8", errors="replace"))
    except Exception:
        return None


def build_artemis_record(payload_b64: bytes, ver: int, typ: int) -> bytes:
    header = b"ARTEMIS\x00"
    header += struct.pack("<I", ver)
    header += struct.pack("<I", typ)
    header += struct.pack("<I", len(payload_b64))
    return header + payload_b64


def decrypt_artemis_json(body: bytes) -> List[Dict]:
    out: List[Dict] = []
    if len(body) >= 4 and body[0] == 0xD1:
        body = body[4:]
    records = parse_artemis_records(body)
    for _ver, _typ, payload in records:
        obj = decrypt_cmd_b64(payload)
        if obj:
            out.append(obj)
    return out


def decrypt_v4_media_data_pages(data: bytes) -> bytes:
    """Decrypt ver=4 media record data (video/audio) as seen in video playback/download.

    Empirical: for each 0x1000-byte page of `data`, the first 0x60 bytes are AES-128-CBC
    encrypted using the same 16-byte key as the command channel and a zero IV. The
    remainder of each page is plaintext.
    """
    if not data:
        return data
    if V4_PAGE_AES_CBC_PREFIX_LEN % 16 != 0:
        raise ValueError("V4 AES prefix length must be multiple of 16")

    out = bytearray(data)
    for off in range(0, len(out), V4_PAGE_SIZE):
        # Native behavior (libArLink.so, case 0/4): decrypt a fixed 0x60-byte
        # prefix per 0x1000 page only when remaining bytes > 0x5f.
        # Do not partially decrypt short tail pages.
        if (len(out) - off) <= 0x5F:
            continue
        ct = bytes(out[off : off + V4_PAGE_AES_CBC_PREFIX_LEN])
        cipher = Cipher(algorithms.AES(AES_CMD_KEY), modes.CBC(AES_CMD_IV), backend=default_backend())
        dec = cipher.decryptor()
        pt = dec.update(ct) + dec.finalize()
        out[off : off + len(pt)] = pt
    return bytes(out)


def _looks_like_h264_nal_hdr(b0: int) -> bool:
    if b0 & 0x80:
        return False
    nal_type = b0 & 0x1F
    return nal_type in {1, 5, 6, 7, 8, 9, 10, 11, 12}


def _find_first_h264_start(blob: bytes) -> int:
    i = blob.find(b"\x00\x00\x00\x01")
    if i != -1:
        return i
    return blob.find(b"\x00\x00\x01")


def len16_be_nals_to_annexb_best_effort(
    data: bytes,
    start_scan_max: int = 32,
    min_coverage_ratio: float = 0.20,
) -> Tuple[bytes, Counter[int], int, int]:
    """Decode a bytestream of (len16be + nal) units into Annex-B.

    Returns: (annexb_bytes, nal_type_counts, units, start_offset). If decoding fails,
    annexb_bytes is empty and start_offset is -1.
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


def normalize_v4_video_payload_to_annexb_with_mode(data: bytes) -> Tuple[bytes, str]:
    """Normalize decrypted ver=4 video payload bytes into Annex-B H264 bytes.

    Returns (normalized_bytes, mode) where mode is one of:
    - 'annexb' (already had start codes)
    - 'len16'  (decoded from len16-be + nal framing)
    - 'raw'    (fallback, unchanged)
    """
    if not data:
        return data, "raw"
    i = _find_first_h264_start(data)
    if i != -1:
        # For live video streams, record payloads can include continuation bytes before the
        # next start code. Trimming to first start code can discard needed tail bytes from the
        # previous access unit and cause decode artifacts. Only trim tiny alignment prefixes.
        if i <= 4:
            return data[i:], "annexb"
        return data, "annexb"
    annexb, _counts, units, _start = len16_be_nals_to_annexb_best_effort(data, start_scan_max=64, min_coverage_ratio=0.30)
    if units > 0 and annexb:
        return annexb, "len16"
    return data, "raw"


def normalize_v4_video_payload_to_annexb(data: bytes) -> bytes:
    out, _mode = normalize_v4_video_payload_to_annexb_with_mode(data)
    return out
