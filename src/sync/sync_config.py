from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from src.config import AppConfig, load_config


@dataclass(frozen=True)
class SyncConfig:
    config_path: Optional[Path]
    app_cfg: Optional[AppConfig]
    state_file: Path
    final_media_dir: Path
    dupes_dir: Path
    dry_run: bool
    stage_only: bool
    debug: bool
    status: bool


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


def _build_parser() -> argparse.ArgumentParser:
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
    p.add_argument(
        "--stage-only",
        action="store_true",
        help="Download/verify into staging only; skip delete-media-all and organize",
    )
    p.add_argument("--debug", action="store_true", help="Verbose protocol logging while connected")
    p.add_argument(
        "--status",
        action="store_true",
        help="Print sync state status and next action, then exit",
    )
    return p


def create_sync_config(argv: Optional[list[str]] = None) -> SyncConfig:
    argv_in = argv if argv is not None else sys.argv[1:]
    args = _build_parser().parse_args(argv_in)

    cfg_path = _resolve_config_path(args.config)
    if args.config and cfg_path is not None and not cfg_path.exists():
        raise SystemExit(f"--config path does not exist: {cfg_path}")

    app_cfg: Optional[AppConfig] = None
    if not args.status:
        if cfg_path is None:
            raise SystemExit(
                "No config file found. Create config.yaml (see config.example.yaml), "
                "or pass --config /path/to/config.yaml"
            )
        app_cfg = load_config(cfg_path)

    final_media_dir = (
        Path(args.final_media_dir)
        if args.final_media_dir
        else Path(app_cfg.paths.final_media_dir or _default_final_media_dir()) if app_cfg is not None else _default_final_media_dir()
    )
    dupes_dir = Path(args.dupes_dir) if args.dupes_dir else _default_dupes_dir()

    return SyncConfig(
        config_path=cfg_path,
        app_cfg=app_cfg,
        state_file=Path(args.state_file),
        final_media_dir=final_media_dir,
        dupes_dir=dupes_dir,
        dry_run=bool(args.dry_run),
        stage_only=bool(args.stage_only),
        debug=bool(args.debug),
        status=bool(args.status),
    )
