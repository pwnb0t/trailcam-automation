#!/usr/bin/env python3
"""
Compare TrailCam "start play record" PCAP payload records against an SD-card MP4.

Why this exists
---------------
For video playback/download, the app does not appear to simply download an MP4.
Instead, the camera streams ver=4 ARTEMIS records inside D0 subtype streams.

We now have a ground-truth SD-card MP4 (`pcap/DSCF0935.MP4`) for the same item
downloaded in `pcap/trailcam_8-3-view-and-download-video.pcap`. This tool treats
the MP4 as an oracle and answers:
- Do record payload sizes match MP4 sample sizes (video/audio)?
- Are record bytes identical to MP4 sample bytes (possibly after stripping a small header)?
- If not identical, is there a constant prefix/offset or other simple transform?

Input expectations
------------------
Run `tools/extract_video_from_pcap.py --v4-header` first so you have:
- `out/video_extract6/<name>/subtype_02_v4_records.csv`
- `out/video_extract6/<name>/subtype_02_records/record_XXXX_ver4_typY_LEN.bin`

This tool is intentionally "boring" and deterministic: it does not guess muxing,
it only compares bytes/sizes and emits CSV to drive the next reverse-engineering step.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import os
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple


ARTEMIS_V4_HDR_LEN = 108


def _u32be(b: bytes) -> int:
    return int.from_bytes(b, "big", signed=False)


def _u32le(b: bytes) -> int:
    return int.from_bytes(b, "little", signed=False)


def _read_exact(f, n: int) -> bytes:
    b = f.read(n)
    if len(b) != n:
        raise EOFError(f"expected {n} bytes, got {len(b)}")
    return b


def _sha1(b: bytes) -> str:
    return hashlib.sha1(b).hexdigest()


def _looks_like_adts(frame: bytes) -> bool:
    # ADTS syncword: 0xFFF (12 bits). Common first two bytes: FF F1/FF F9.
    return len(frame) >= 2 and frame[0] == 0xFF and (frame[1] & 0xF0) == 0xF0


@dataclass
class PcapRecord:
    record_idx: int
    kind: str
    typ: int
    payload_len: int
    pts_ms: int
    data_len: int
    width: int
    height: int
    payload: bytes

    @property
    def data(self) -> bytes:
        # For ver=4 records extracted by tools/extract_video_from_pcap.py, each record bin
        # is the ver=4 payload only (no "ARTEMIS\\0" wrapper). The empirical header is 108 bytes.
        if len(self.payload) < ARTEMIS_V4_HDR_LEN:
            return b""
        return self.payload[ARTEMIS_V4_HDR_LEN:]


def load_pcap_records(records_csv: Path, records_dir: Path) -> List[PcapRecord]:
    out: List[PcapRecord] = []
    with records_csv.open(newline="") as f:
        r = csv.DictReader(f)
        for row in r:
            idx = int(row["record_idx"])
            typ = int(row["typ"])
            payload_len = int(row["payload_len"])
            pts_ms = int(row["pts_ms"])
            data_len = int(row["data_len"])
            width = int(row["width"])
            height = int(row["height"])
            kind = row["kind"]

            # Filename convention: record_0006_ver4_typ6_42105.bin
            # We match by idx only.
            rec_glob = f"record_{idx:04d}_ver4_typ{typ}_*.bin"
            matches = sorted(records_dir.glob(rec_glob))
            if not matches:
                # Some indices/typs may vary due to re-extraction; fall back to idx-only match.
                matches = sorted(records_dir.glob(f"record_{idx:04d}_ver4_typ*_*.bin"))
            if not matches:
                raise FileNotFoundError(f"missing record bin for idx={idx} (looked for {rec_glob})")
            payload = matches[0].read_bytes()
            if len(payload) != payload_len:
                # Keep going, but record it; the CSV is derived from the same payloads so
                # mismatch suggests a stale folder.
                raise RuntimeError(
                    f"payload_len mismatch for idx={idx}: csv={payload_len} file={len(payload)} ({matches[0]})"
                )

            out.append(
                PcapRecord(
                    record_idx=idx,
                    kind=kind,
                    typ=typ,
                    payload_len=payload_len,
                    pts_ms=pts_ms,
                    data_len=data_len,
                    width=width,
                    height=height,
                    payload=payload,
                )
            )
    return out


# -----------------------
# Minimal MP4 sample read
# -----------------------


@dataclass
class Mp4Box:
    typ: str
    start: int
    size: int
    header_size: int

    @property
    def end(self) -> int:
        return self.start + self.size


def _iter_boxes(f, start: int, end: int) -> Iterable[Mp4Box]:
    pos = start
    while pos + 8 <= end:
        f.seek(pos)
        hdr = f.read(8)
        if len(hdr) < 8:
            return
        size = _u32be(hdr[0:4])
        typ = hdr[4:8].decode("ascii", errors="replace")
        header_size = 8
        if size == 1:
            largesize = _u64be(_read_exact(f, 8))
            size = largesize
            header_size = 16
        elif size == 0:
            size = end - pos
        if size < header_size or pos + size > end:
            return
        yield Mp4Box(typ=typ, start=pos, size=size, header_size=header_size)
        pos += size


def _u64be(b: bytes) -> int:
    return int.from_bytes(b, "big", signed=False)


def _find_child(f, parent: Mp4Box, typ: str) -> Optional[Mp4Box]:
    for b in _iter_boxes(f, parent.start + parent.header_size, parent.end):
        if b.typ == typ:
            return b
    return None


def _find_children(f, parent: Mp4Box, typ: str) -> List[Mp4Box]:
    out = []
    for b in _iter_boxes(f, parent.start + parent.header_size, parent.end):
        if b.typ == typ:
            out.append(b)
    return out


@dataclass
class Mp4Track:
    track_id: int
    handler: str  # "vide" or "soun"
    codec: str  # "avc1" or "mp4a"
    timescale: int
    sample_sizes: List[int]
    sample_offsets: List[int]
    sample_pts_ms: List[int]

    def sample(self, f, i: int) -> bytes:
        off = self.sample_offsets[i]
        ln = self.sample_sizes[i]
        f.seek(off)
        return _read_exact(f, ln)


def _read_full_box_version_and_flags(f, box: Mp4Box) -> Tuple[int, int]:
    f.seek(box.start + box.header_size)
    b = _read_exact(f, 4)
    version = b[0]
    flags = int.from_bytes(b[1:4], "big", signed=False)
    return version, flags


def _parse_mdhd_timescale(f, mdhd: Mp4Box) -> int:
    version, _flags = _read_full_box_version_and_flags(f, mdhd)
    f.seek(mdhd.start + mdhd.header_size + 4)
    if version == 0:
        _read_exact(f, 4)  # creation
        _read_exact(f, 4)  # modification
        timescale = _u32be(_read_exact(f, 4))
        return timescale
    if version == 1:
        _read_exact(f, 8)
        _read_exact(f, 8)
        timescale = _u32be(_read_exact(f, 4))
        return timescale
    raise ValueError(f"mdhd unsupported version {version}")


def _parse_tkhd_track_id(f, tkhd: Mp4Box) -> int:
    version, _flags = _read_full_box_version_and_flags(f, tkhd)
    f.seek(tkhd.start + tkhd.header_size + 4)
    if version == 0:
        _read_exact(f, 4)
        _read_exact(f, 4)
        track_id = _u32be(_read_exact(f, 4))
        return track_id
    if version == 1:
        _read_exact(f, 8)
        _read_exact(f, 8)
        track_id = _u32be(_read_exact(f, 4))
        return track_id
    raise ValueError(f"tkhd unsupported version {version}")


def _parse_hdlr_handler_type(f, hdlr: Mp4Box) -> str:
    _version, _flags = _read_full_box_version_and_flags(f, hdlr)
    f.seek(hdlr.start + hdlr.header_size + 4)
    _read_exact(f, 4)  # pre_defined
    handler = _read_exact(f, 4).decode("ascii", errors="replace")
    return handler


def _parse_stsd_codec(f, stsd: Mp4Box) -> str:
    _version, _flags = _read_full_box_version_and_flags(f, stsd)
    f.seek(stsd.start + stsd.header_size + 4)
    entry_count = _u32be(_read_exact(f, 4))
    if entry_count < 1:
        return ""
    # First sample entry:
    entry_size = _u32be(_read_exact(f, 4))
    codec = _read_exact(f, 4).decode("ascii", errors="replace")
    if entry_size < 8:
        return codec
    return codec


def _parse_stsz_sizes(f, stsz: Mp4Box) -> List[int]:
    _version, _flags = _read_full_box_version_and_flags(f, stsz)
    f.seek(stsz.start + stsz.header_size + 4)
    sample_size = _u32be(_read_exact(f, 4))
    sample_count = _u32be(_read_exact(f, 4))
    if sample_count == 0:
        return []
    if sample_size != 0:
        return [sample_size] * sample_count
    sizes = []
    for _ in range(sample_count):
        sizes.append(_u32be(_read_exact(f, 4)))
    return sizes


def _parse_stco_offsets(f, stco: Mp4Box) -> List[int]:
    _version, _flags = _read_full_box_version_and_flags(f, stco)
    f.seek(stco.start + stco.header_size + 4)
    n = _u32be(_read_exact(f, 4))
    out = []
    for _ in range(n):
        out.append(_u32be(_read_exact(f, 4)))
    return out


def _parse_co64_offsets(f, co64: Mp4Box) -> List[int]:
    _version, _flags = _read_full_box_version_and_flags(f, co64)
    f.seek(co64.start + co64.header_size + 4)
    n = _u32be(_read_exact(f, 4))
    out = []
    for _ in range(n):
        out.append(_u64be(_read_exact(f, 8)))
    return out


def _parse_stsc(f, stsc: Mp4Box) -> List[Tuple[int, int, int]]:
    _version, _flags = _read_full_box_version_and_flags(f, stsc)
    f.seek(stsc.start + stsc.header_size + 4)
    n = _u32be(_read_exact(f, 4))
    out = []
    for _ in range(n):
        first_chunk = _u32be(_read_exact(f, 4))
        samples_per_chunk = _u32be(_read_exact(f, 4))
        sample_desc_index = _u32be(_read_exact(f, 4))
        out.append((first_chunk, samples_per_chunk, sample_desc_index))
    return out


def _parse_stts(f, stts: Mp4Box) -> List[Tuple[int, int]]:
    _version, _flags = _read_full_box_version_and_flags(f, stts)
    f.seek(stts.start + stts.header_size + 4)
    n = _u32be(_read_exact(f, 4))
    out = []
    for _ in range(n):
        sample_count = _u32be(_read_exact(f, 4))
        sample_delta = _u32be(_read_exact(f, 4))
        out.append((sample_count, sample_delta))
    return out


def _build_sample_offsets(sample_sizes: List[int], chunk_offsets: List[int], stsc: List[Tuple[int, int, int]]) -> List[int]:
    if not sample_sizes:
        return []
    if not chunk_offsets:
        return []
    if not stsc:
        return []

    # Expand stsc to per-chunk samples_per_chunk.
    # stsc entries apply from first_chunk to (next_first_chunk-1) inclusive.
    per_chunk_spc: List[int] = [0] * len(chunk_offsets)
    for i, (first_chunk, spc, _sdi) in enumerate(stsc):
        start = first_chunk - 1
        end = (stsc[i + 1][0] - 1) if i + 1 < len(stsc) else len(chunk_offsets)
        for c in range(start, end):
            if 0 <= c < len(per_chunk_spc):
                per_chunk_spc[c] = spc

    out: List[int] = []
    sample_i = 0
    for chunk_i, chunk_off in enumerate(chunk_offsets):
        spc = per_chunk_spc[chunk_i]
        if spc <= 0:
            raise RuntimeError(f"invalid stsc expansion at chunk {chunk_i+1}")
        off = chunk_off
        for _ in range(spc):
            if sample_i >= len(sample_sizes):
                break
            out.append(off)
            off += sample_sizes[sample_i]
            sample_i += 1
        if sample_i >= len(sample_sizes):
            break
    if len(out) != len(sample_sizes):
        # Some MP4s can use composition offsets or edit lists; for our use we still
        # want deterministic failure if we can't account for all samples.
        raise RuntimeError(f"sample offset build mismatch: sizes={len(sample_sizes)} offsets={len(out)}")
    return out


def _build_pts_ms(sample_sizes: List[int], stts: List[Tuple[int, int]], timescale: int) -> List[int]:
    # DTS/PTS are identical for no-B-frame content. Compute monotonically increasing timestamps.
    pts_ms: List[int] = []
    t = 0
    produced = 0
    for count, delta in stts:
        for _ in range(count):
            pts_ms.append(int(round((t * 1000) / timescale)))
            t += delta
            produced += 1
            if produced >= len(sample_sizes):
                break
        if produced >= len(sample_sizes):
            break
    if len(pts_ms) != len(sample_sizes):
        # Still usable for size-only comparisons, but for alignment we prefer correctness.
        raise RuntimeError(f"stts mismatch: expected {len(sample_sizes)} pts entries, got {len(pts_ms)}")
    return pts_ms


def load_mp4_tracks(mp4_path: Path) -> List[Mp4Track]:
    with mp4_path.open("rb") as f:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        f.seek(0)
        root = Mp4Box(typ="root", start=0, size=size, header_size=0)
        moov = _find_child(f, root, "moov")
        if not moov:
            raise RuntimeError("mp4 missing moov box")

        tracks: List[Mp4Track] = []
        for trak in _find_children(f, moov, "trak"):
            tkhd = _find_child(f, trak, "tkhd")
            mdia = _find_child(f, trak, "mdia")
            if not tkhd or not mdia:
                continue
            track_id = _parse_tkhd_track_id(f, tkhd)
            mdhd = _find_child(f, mdia, "mdhd")
            hdlr = _find_child(f, mdia, "hdlr")
            minf = _find_child(f, mdia, "minf")
            if not mdhd or not hdlr or not minf:
                continue
            timescale = _parse_mdhd_timescale(f, mdhd)
            handler = _parse_hdlr_handler_type(f, hdlr)
            stbl = _find_child(f, minf, "stbl")
            if not stbl:
                continue

            stsd = _find_child(f, stbl, "stsd")
            stsz = _find_child(f, stbl, "stsz")
            stsc = _find_child(f, stbl, "stsc")
            stts = _find_child(f, stbl, "stts")
            stco = _find_child(f, stbl, "stco")
            co64 = _find_child(f, stbl, "co64")
            if not stsd or not stsz or not stsc or not stts or (not stco and not co64):
                continue

            codec = _parse_stsd_codec(f, stsd)
            sample_sizes = _parse_stsz_sizes(f, stsz)
            stsc_entries = _parse_stsc(f, stsc)
            stts_entries = _parse_stts(f, stts)
            chunk_offsets = _parse_stco_offsets(f, stco) if stco else _parse_co64_offsets(f, co64)  # type: ignore[arg-type]
            sample_offsets = _build_sample_offsets(sample_sizes, chunk_offsets, stsc_entries)
            sample_pts_ms = _build_pts_ms(sample_sizes, stts_entries, timescale)

            tracks.append(
                Mp4Track(
                    track_id=track_id,
                    handler=handler,
                    codec=codec,
                    timescale=timescale,
                    sample_sizes=sample_sizes,
                    sample_offsets=sample_offsets,
                    sample_pts_ms=sample_pts_ms,
                )
            )
        return tracks


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--records-csv", required=True, help="Path to subtype_02_v4_records.csv")
    ap.add_argument("--records-dir", required=True, help="Path to subtype_02_records/")
    ap.add_argument("--mp4", required=True, help="SD-card MP4 path (oracle)")
    ap.add_argument("--out-csv", default="out/video_compare/compare.csv", help="Output CSV path")
    ap.add_argument("--max-prefix-scan", type=int, default=256, help="Scan this many bytes for a match offset")
    args = ap.parse_args()

    records_csv = Path(args.records_csv)
    records_dir = Path(args.records_dir)
    mp4_path = Path(args.mp4)
    out_csv = Path(args.out_csv)
    out_csv.parent.mkdir(parents=True, exist_ok=True)

    pcap_records = load_pcap_records(records_csv, records_dir)
    v16 = [r for r in pcap_records if r.kind.startswith("v16")]
    v20 = [r for r in pcap_records if r.kind.startswith("v20")]

    tracks = load_mp4_tracks(mp4_path)
    video_tracks = [t for t in tracks if t.handler == "vide"]
    audio_tracks = [t for t in tracks if t.handler == "soun"]
    if not video_tracks or not audio_tracks:
        raise RuntimeError(f"expected at least 1 vide and 1 soun track, got vide={len(video_tracks)} soun={len(audio_tracks)}")

    # Pick the "best" tracks by sample count matching what we see in PCAP.
    # For DSCF0935.MP4, we empirically expect ~304 video samples and ~157 audio samples.
    video_track = sorted(video_tracks, key=lambda t: abs(len(t.sample_sizes) - len(v16)))[0]
    audio_track = sorted(audio_tracks, key=lambda t: abs(len(t.sample_sizes) - len(v20)))[0]

    # Align by order: sort PCAP records by pts then idx; MP4 samples are already decode-order.
    v16_sorted = sorted(v16, key=lambda r: (r.pts_ms, r.record_idx))
    v20_sorted = sorted(v20, key=lambda r: (r.pts_ms, r.record_idx))

    def safe_get_track_sample(track: Mp4Track, i: int) -> bytes:
        with mp4_path.open("rb") as f:
            return track.sample(f, i)

    with out_csv.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "kind",
                "pcap_record_idx",
                "pcap_pts_ms",
                "pcap_data_len",
                "pcap_data_sha1",
                "mp4_sample_idx",
                "mp4_pts_ms",
                "mp4_size",
                "mp4_sha1",
                "size_match",
                "exact_match",
                "match_offset",
                "note",
            ]
        )

        # Video compare
        for i, rec in enumerate(v16_sorted):
            if i >= len(video_track.sample_sizes):
                break
            mp4_sample = safe_get_track_sample(video_track, i)
            pdat = rec.data
            size_match = len(pdat) == len(mp4_sample)
            exact = pdat == mp4_sample
            off = ""
            note = ""
            if not exact:
                # Try to find an offset within the first N bytes where the MP4 sample prefix appears.
                scan = pdat[: args.max_prefix_scan]
                prefix = mp4_sample[:16] if len(mp4_sample) >= 16 else mp4_sample
                j = scan.find(prefix) if prefix else -1
                if j != -1:
                    off = str(j)
                    note = "mp4_prefix_found_in_pcap"
            w.writerow(
                [
                    "v16_video",
                    rec.record_idx,
                    rec.pts_ms,
                    len(pdat),
                    _sha1(pdat),
                    i,
                    video_track.sample_pts_ms[i],
                    len(mp4_sample),
                    _sha1(mp4_sample),
                    int(size_match),
                    int(exact),
                    off,
                    note,
                ]
            )

        # Audio compare
        for i, rec in enumerate(v20_sorted):
            if i >= len(audio_track.sample_sizes):
                break
            mp4_sample = safe_get_track_sample(audio_track, i)
            pdat = rec.data
            note = ""

            # Common hypothesis from our earlier size correlations: PCAP audio frames have a 7-byte header.
            pdat0 = pdat
            pdat7 = pdat[7:] if len(pdat) >= 7 else b""
            if _looks_like_adts(pdat0):
                note = "pcap_audio_looks_like_adts"
            size_match = len(pdat7) == len(mp4_sample)
            exact = pdat7 == mp4_sample
            w.writerow(
                [
                    "v20_audio",
                    rec.record_idx,
                    rec.pts_ms,
                    len(pdat),
                    _sha1(pdat),
                    i,
                    audio_track.sample_pts_ms[i],
                    len(mp4_sample),
                    _sha1(mp4_sample),
                    int(size_match),
                    int(exact),
                    "",
                    note,
                ]
            )

    print(f"Wrote {out_csv}")
    print(f"PCAP: v16={len(v16_sorted)} v20={len(v20_sorted)}; MP4: vide={len(video_track.sample_sizes)} soun={len(audio_track.sample_sizes)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

