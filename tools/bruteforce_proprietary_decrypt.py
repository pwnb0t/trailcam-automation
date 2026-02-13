#!/usr/bin/env python3
"""
Bruteforce the parameters for libArLink.so proprietary stream cipher against an MP4 oracle.

We have a capture where:
- PCAP D0 subtype streams contain ver=4 "records" whose `data` lengths match MP4 sample sizes
- Those bytes are NOT identical to MP4 sample bytes

Given the SD-card MP4 for the same video, we can treat MP4 samples as plaintext and
attempt to find the correct decrypt parameters that make:

  proprietary_decrypt(ciphertext_sample) == mp4_sample_bytes

This script is intentionally small and deterministic. It tries a handful of key4
derivations from the per-record ver=4 header fields (seed_u32_0/seed_u32_1/session_no).
"""

from __future__ import annotations

import argparse
import csv
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Tuple

import sys

# Allow importing sibling tool modules when executed as a script.
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from tools.compare_video_pcap_to_sd_mp4 import (  # type: ignore[import-not-found]
    ARTEMIS_V4_HDR_LEN,
    Mp4Track,
    PcapRecord,
    load_mp4_tracks,
    load_pcap_records,
)


def load_g__NDT_PE_Table(lib_path: Path) -> bytes:
    """
    Extract g__NDT_PE_Table from libArLink.so.

    For TrailCam Go 2.5.6 libArLink.so, `nm -D` reports:
      g__NDT_PE_Table at vaddr 0x00019cfa, size 256

    This binary is built as PIC; for this file the vaddr matches file offset.
    If that stops being true, switch to a real ELF parser (pyelftools) or use readelf.
    """

    off = 0x00019CFA
    ln = 256
    b = lib_path.read_bytes()
    if off + ln > len(b):
        raise RuntimeError(f"lib too small for table extraction: need {off+ln}, have {len(b)}")
    tbl = b[off : off + ln]
    if len(tbl) != 256:
        raise RuntimeError("table length mismatch")
    return tbl


def proprietary_decrypt(table256: bytes, src: bytes, key4: bytes) -> bytes:
    """
    Re-implementation of libArLink.so `_NDT_Proprietary_Decrypt`:

      dst[0] = src[0] XOR table[key4[0]]
      for i>=1:
        idx = (key4[src[i-1] & 3] + src[i-1]) & 0xFF
        dst[i] = src[i] XOR table[idx]
    """

    if len(key4) != 4:
        raise ValueError("key4 must be 4 bytes")
    if not src:
        return b""
    out = bytearray(len(src))
    out[0] = src[0] ^ table256[key4[0]]
    prev = src[0]
    for i in range(1, len(src)):
        idx = (key4[prev & 3] + prev) & 0xFF
        out[i] = src[i] ^ table256[idx]
        prev = src[i]
    return bytes(out)


def _u32le(n: int) -> bytes:
    return struct.pack("<I", n & 0xFFFFFFFF)


def _u32be(n: int) -> bytes:
    return struct.pack(">I", n & 0xFFFFFFFF)


@dataclass(frozen=True)
class RecordHdr:
    session_no: int
    seed_u32_0: int
    seed_u32_1: int


KeyDeriver = Callable[[RecordHdr], bytes]


def key_derivers() -> List[Tuple[str, KeyDeriver]]:
    return [
        ("seed0_le", lambda h: _u32le(h.seed_u32_0)),
        ("seed0_be", lambda h: _u32be(h.seed_u32_0)),
        ("seed1_le", lambda h: _u32le(h.seed_u32_1)),
        ("seed1_be", lambda h: _u32be(h.seed_u32_1)),
        ("seed0_xor_seed1_le", lambda h: _u32le(h.seed_u32_0 ^ h.seed_u32_1)),
        ("seed0_xor_seed1_be", lambda h: _u32be(h.seed_u32_0 ^ h.seed_u32_1)),
        ("sessionno_le", lambda h: _u32le(h.session_no)),
        ("sessionno_be", lambda h: _u32be(h.session_no)),
        ("seed0_plus_seed1_le", lambda h: _u32le((h.seed_u32_0 + h.seed_u32_1) & 0xFFFFFFFF)),
        ("seed0_plus_seed1_be", lambda h: _u32be((h.seed_u32_0 + h.seed_u32_1) & 0xFFFFFFFF)),
    ]


def best_track(tracks: List[Mp4Track], handler: str, want_count: int) -> Mp4Track:
    candidates = [t for t in tracks if t.handler == handler]
    if not candidates:
        raise RuntimeError(f"mp4 missing {handler} track")
    return sorted(candidates, key=lambda t: abs(len(t.sample_sizes) - want_count))[0]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--records-csv", required=True)
    ap.add_argument("--records-dir", required=True)
    ap.add_argument("--mp4", required=True)
    ap.add_argument("--lib", required=True, help="Path to libArLink.so (for g__NDT_PE_Table)")
    ap.add_argument("--max-samples", type=int, default=50)
    args = ap.parse_args()

    table = load_g__NDT_PE_Table(Path(args.lib))

    records_csv_path = Path(args.records_csv)
    pcap_records = load_pcap_records(records_csv_path, Path(args.records_dir))
    hdr_by_idx: dict[int, RecordHdr] = {}
    with records_csv_path.open(newline="") as f:
        r = csv.DictReader(f)
        for row in r:
            idx = int(row["record_idx"])
            hdr_by_idx[idx] = RecordHdr(
                session_no=int(row.get("session_no", "0") or "0"),
                seed_u32_0=int(row.get("seed_u32_0", "0") or "0"),
                seed_u32_1=int(row.get("seed_u32_1", "0") or "0"),
            )
    v16 = [r for r in pcap_records if r.kind.startswith("v16")]
    v20 = [r for r in pcap_records if r.kind.startswith("v20")]
    v16_sorted = sorted(v16, key=lambda r: (r.pts_ms, r.record_idx))
    v20_sorted = sorted(v20, key=lambda r: (r.pts_ms, r.record_idx))

    tracks = load_mp4_tracks(Path(args.mp4))
    vide = best_track(tracks, "vide", want_count=len(v16_sorted))
    soun = best_track(tracks, "soun", want_count=len(v20_sorted))

    # Prepare oracle plaintext samples for the first N items for speed.
    with Path(args.mp4).open("rb") as f:
        pv = [vide.sample(f, i) for i in range(min(args.max_samples, len(vide.sample_sizes)))]
        pa = [soun.sample(f, i) for i in range(min(args.max_samples, len(soun.sample_sizes)))]

    def eval_kind(kind: str, recs: List[PcapRecord], plains: List[bytes]) -> None:
        n = min(len(recs), len(plains), args.max_samples)
        if n <= 0:
            return
        print(f"{kind}: evaluating {n} samples")
        for name, derive in key_derivers():
            ok = 0
            for i in range(n):
                rec = recs[i]
                hdr = hdr_by_idx.get(rec.record_idx)
                if not hdr:
                    continue
                key4 = derive(hdr)
                c = rec.payload[ARTEMIS_V4_HDR_LEN:]
                p = plains[i]
                if len(c) != len(p):
                    continue
                d = proprietary_decrypt(table, c, key4)
                if d == p:
                    ok += 1
            print(f"  {name}: {ok}/{n} exact matches")

    eval_kind("video(v16)", v16_sorted, pv)
    eval_kind("audio(v20)", v20_sorted, pa)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
