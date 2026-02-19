#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import subprocess
import tempfile
from collections import Counter
from pathlib import Path
import sys
from typing import Dict, List, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.flows import _parse_artemis_v4_payload_header
from src.protocol import decrypt_v4_media_data_pages, normalize_v4_video_payload_to_annexb_with_mode, parse_artemis_records_strict


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def extract_ref_h264(mp4_path: Path) -> bytes:
    with tempfile.TemporaryDirectory(prefix="ref_h264_") as td:
        out = Path(td) / "ref.h264"
        cmd = [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(mp4_path),
            "-an",
            "-c:v",
            "copy",
            "-bsf:v",
            "h264_mp4toannexb",
            str(out),
        ]
        p = subprocess.run(cmd, capture_output=True, text=True)
        if p.returncode != 0:
            raise RuntimeError(f"ffmpeg failed extracting ref h264: {(p.stderr or '').strip()}")
        return out.read_bytes()


def frame_hashes_from_h264(h264: bytes) -> List[str]:
    with tempfile.TemporaryDirectory(prefix="framemd5_") as td:
        h = Path(td) / "in.h264"
        m = Path(td) / "frames.md5"
        h.write_bytes(h264)
        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(h),
            "-an",
            "-f",
            "framemd5",
            str(m),
        ]
        p = subprocess.run(cmd, capture_output=True, text=True)
        if p.returncode != 0:
            raise RuntimeError(f"ffmpeg framemd5 failed: {(p.stderr or '').strip()}")
        out: List[str] = []
        for line in m.read_text().splitlines():
            if not line or line.startswith("#"):
                continue
            parts = [x.strip() for x in line.split(",")]
            if len(parts) < 6:
                continue
            out.append(parts[5])
        return out


def first_mismatch(a: List[str], b: List[str]) -> int:
    n = min(len(a), len(b))
    for i in range(n):
        if a[i] != b[i]:
            return i
    return -1 if len(a) == len(b) else n


def build_video_items(assembled: bytes) -> Tuple[List[Tuple[int, int, int, bytes]], Counter[int], Dict[str, int]]:
    # returns [(rec_idx, pts_ms, session_no, annexb_payload)], session histogram, mode counts
    recs = parse_artemis_records_strict(assembled)
    out: List[Tuple[int, int, int, bytes]] = []
    sessions: Counter[int] = Counter()
    mode_counts: Dict[str, int] = {"annexb": 0, "len16": 0, "raw": 0}
    for rec_idx, (ver, _typ, payload) in enumerate(recs):
        if ver != 4:
            continue
        hdr = _parse_artemis_v4_payload_header(payload)
        if not hdr:
            continue
        raw = payload[hdr["header_len"] : hdr["header_len"] + hdr["data_len"]]
        dec = decrypt_v4_media_data_pages(raw)
        if hdr["data_len_off"] == 16 and hdr["width"] and hdr["height"]:
            v, mode = normalize_v4_video_payload_to_annexb_with_mode(dec)
            mode_counts[mode] = mode_counts.get(mode, 0) + 1
            sess = int(hdr["session_no"])
            sessions[sess] += 1
            out.append((rec_idx, int(hdr["pts_ms"]), sess, v))
    return out, sessions, mode_counts


def mode_current(items: List[Tuple[int, int, int, bytes]], selected_session: int) -> bytes:
    v_items = [x for x in items if x[2] == selected_session]
    v_items.sort(key=lambda x: x[0])  # record order
    by_pts: Dict[int, Tuple[int, int, int, bytes]] = {}
    for it in v_items:
        pts = it[1]
        if pts not in by_pts:
            by_pts[pts] = it
    v_items = sorted(by_pts.values(), key=lambda x: x[0])
    return b"".join(x[3] for x in v_items)


def mode_callback(items: List[Tuple[int, int, int, bytes]], selected_session: int) -> bytes:
    v_items = [x for x in items if x[2] == selected_session]
    v_items.sort(key=lambda x: x[0])  # callback/record order, no dedup
    return b"".join(x[3] for x in v_items)


def mode_all_sessions(items: List[Tuple[int, int, int, bytes]]) -> bytes:
    v_items = sorted(items, key=lambda x: x[0])
    return b"".join(x[3] for x in v_items)

def mode_pts(items: List[Tuple[int, int, int, bytes]], selected_session: int) -> bytes:
    v_items = [x for x in items if x[2] == selected_session]
    v_items.sort(key=lambda x: (x[1], x[0]))  # PTS first, record idx as tie-breaker
    return b"".join(x[3] for x in v_items)


def main() -> int:
    ap = argparse.ArgumentParser(description="Compare video assembly modes against a reference SD mp4")
    ap.add_argument("--assembled", required=True, help="path to subtype_02_assembled.bin")
    ap.add_argument("--reference-mp4", required=True, help="path to original SD mp4")
    args = ap.parse_args()

    assembled = Path(args.assembled).read_bytes()
    ref_h264 = extract_ref_h264(Path(args.reference_mp4))
    ref_fh = frame_hashes_from_h264(ref_h264)

    items, sessions, mode_counts = build_video_items(assembled)
    if not items:
        raise RuntimeError("no video records found")
    selected_session = sessions.most_common(1)[0][0]

    modes = {
        "current": mode_current(items, selected_session),
        "callback": mode_callback(items, selected_session),
        "pts": mode_pts(items, selected_session),
        "all_sessions": mode_all_sessions(items),
    }

    print(f"records={len(items)} sessions={dict(sessions)} selected_session={selected_session} modes={mode_counts}")
    print(f"reference: bytes={len(ref_h264)} sha256={sha256_bytes(ref_h264)} frames={len(ref_fh)}")

    for name, h264 in modes.items():
        fh = frame_hashes_from_h264(h264)
        mm = sum(1 for i in range(min(len(ref_fh), len(fh))) if ref_fh[i] == fh[i])
        fm = first_mismatch(ref_fh, fh)
        print(
            f"{name}: bytes={len(h264)} sha256={sha256_bytes(h264)} frames={len(fh)} "
            f"match_positions={mm}/{min(len(ref_fh), len(fh))} first_mismatch={fm}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
