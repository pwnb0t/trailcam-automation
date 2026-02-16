#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
from typing import Optional

from src.config import load_config
from src.sync.sync_runner import SyncRunner
from src.sync.sync_state import SyncStateStore


def _resolve_config_path(explicit: Optional[str]) -> Optional[Path]:
    if explicit:
        return Path(explicit)
    for name in ("config.yaml", "config.yml"):
        p = Path(name)
        if p.exists():
            return p
    return None


def _default_final_media_dir() -> Path:
    p = Path("/mnt/trailcam/media")
    if p.exists():
        return p
    return Path("out/final-media")


def _default_dupes_dir() -> Path:
    p = Path("/mnt/trailcam/dupes")
    if p.exists():
        return p
    return Path("out/dupes")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="TrailCam sync runner (all configured cameras).")
    p.add_argument("--config", default=None, help="Path to config.yaml/config.yml (default: auto-detect)")
    p.add_argument(
        "--state-file",
        default="out/state/trailcam_sync_state.json",
        help="Sync state JSON path (default: %(default)s)",
    )
    p.add_argument("--final-media-dir", default=None, help="Final organized media root")
    p.add_argument("--dupes-dir", default=None, help="Destination for filename/content collisions")
    p.add_argument("--dry-run", action="store_true", help="Do not clear camera or move files; print actions")
    p.add_argument("--debug", action="store_true", help="Verbose protocol logging while connected")
    return p


async def main() -> None:
    args = build_parser().parse_args()
    cfg_path = _resolve_config_path(args.config)
    if cfg_path is None:
        raise SystemExit(
            "No config file found. Create config.yaml (see config.example.yaml), "
            "or pass --config /path/to/config.yaml"
        )
    app_cfg = load_config(cfg_path)

    final_media_dir = Path(args.final_media_dir) if args.final_media_dir else Path(app_cfg.paths.final_media_dir or _default_final_media_dir())
    dupes_dir = Path(args.dupes_dir) if args.dupes_dir else _default_dupes_dir()
    state_store = SyncStateStore(Path(args.state_file))

    runner = SyncRunner(
        app_cfg=app_cfg,
        state_store=state_store,
        final_media_dir=final_media_dir,
        dupes_dir=dupes_dir,
        debug=bool(args.debug),
        dry_run=bool(args.dry_run),
    )
    await runner.run_all()


if __name__ == "__main__":
    asyncio.run(main())

