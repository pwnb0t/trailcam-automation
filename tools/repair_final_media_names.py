#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime
from pathlib import Path

# Allow running as `python3 tools/...` from repo root.
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.config import OrganizeConfig, load_config
from src.sync.organize import _week_bucket_label


NAME_RE = re.compile(
    r"^(?P<alias>[^_]+)_(?P<ts>\d{8}_\d{6})_(?P<dir>\d+)-(?P<media>\d+)\.(?P<ext>jpg|mp4)$",
    flags=re.IGNORECASE,
)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Repair final media filenames: left-pad media numbers and optionally "
            "convert legacy mediaTime timestamp (UTC-interpreted) to local-epoch form."
        )
    )
    p.add_argument("--config", default="config.yaml", help="Path to config.yaml (default: %(default)s)")
    p.add_argument("--root", default=None, help="Final media root override (default: config paths.final_media_dir)")
    p.add_argument(
        "--no-shift-timestamp",
        action="store_true",
        help="Do not apply legacy timestamp correction (still pads media number and bucket path)",
    )
    p.add_argument("--apply", action="store_true", help="Perform renames (default is dry-run)")
    return p.parse_args()


def _legacy_shift_local_epoch(dt_old_local_naive: datetime) -> datetime:
    # Old code treated camera mediaTime as UTC epoch then converted to local.
    # New mode treats it as local-epoch. To convert old -> new, subtract local UTC offset.
    local_tz = datetime.now().astimezone().tzinfo
    assert local_tz is not None
    aware = dt_old_local_naive.replace(tzinfo=local_tz)
    offset = aware.utcoffset()
    if offset is None:
        return dt_old_local_naive
    return dt_old_local_naive - offset


def _build_target_name(
    *,
    alias: str,
    dt_local: datetime,
    dir_num: int,
    media_num: int,
    ext: str,
) -> str:
    ts = dt_local.strftime("%Y%m%d_%H%M%S")
    return f"{alias}_{ts}_{dir_num}-{media_num:04d}.{ext.lower()}"


def main() -> int:
    args = _parse_args()
    cfg = load_config(args.config)
    root = Path(args.root or cfg.paths.final_media_dir or "out/final-media")
    org: OrganizeConfig = cfg.organize

    if not root.exists():
        print(f"Final media root does not exist: {root}")
        return 1

    rename_count = 0
    same_count = 0
    conflict_count = 0
    scanned = 0

    files = sorted(p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in (".jpg", ".mp4"))
    for src in files:
        scanned += 1
        m = NAME_RE.match(src.name)
        if not m:
            continue

        alias = m.group("alias")
        dt_old = datetime.strptime(m.group("ts"), "%Y%m%d_%H%M%S")
        dt_new = dt_old if args.no_shift_timestamp else _legacy_shift_local_epoch(dt_old)
        dir_num = int(m.group("dir"))
        media_num = int(m.group("media"))
        ext = m.group("ext").lower()

        bucket = _week_bucket_label(
            dt_new,
            boundary_weekday=int(org.week_boundary_weekday),
            boundary_hour_local=int(org.week_boundary_hour_local),
        )
        dst_dir = root / bucket
        dst_name = _build_target_name(
            alias=alias,
            dt_local=dt_new,
            dir_num=dir_num,
            media_num=media_num,
            ext=ext,
        )
        dst = dst_dir / dst_name

        if src == dst:
            same_count += 1
            continue

        if dst.exists():
            conflict_count += 1
            print(f"CONFLICT: {src} -> {dst} (target exists)")
            continue

        rename_count += 1
        if args.apply:
            dst_dir.mkdir(parents=True, exist_ok=True)
            src.rename(dst)
            # Clean now-empty week dir
            try:
                if src.parent != root:
                    src.parent.rmdir()
            except Exception:
                pass
            print(f"RENAMED: {src} -> {dst}")
        else:
            print(f"DRYRUN: {src} -> {dst}")

    mode = "APPLY" if args.apply else "DRY-RUN"
    print("")
    print(
        f"[{mode}] scanned={scanned} rename_needed={rename_count} "
        f"unchanged={same_count} conflicts={conflict_count}"
    )
    if not args.apply:
        print("Re-run with --apply to execute renames.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
