#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
from typing import Optional

from src.config import load_config
from src.notify.email_notifier import EmailNotifier
from src.sync.sync_runner import SyncRunner
from src.sync.sync_state import SyncStateStore


def _next_step_for_status(status: str, dry_run: bool) -> str:
    s = str(status or "").strip().lower()
    if s in ("", "pending"):
        return "connect/login, then download missing media"
    if s == "download":
        return "continue download pass (list media, download missing items)"
    if s == "verify":
        return "verify manifests; if missing items are found, go back to download"
    if s == "clear":
        if dry_run:
            return "skip clear (dry-run), then organize"
        return "delete all media on camera, then organize"
    if s == "organize":
        return "organize staged files into final media layout"
    if s == "done":
        return "skip this camera (already done in state)"
    if s == "error":
        return "inspect error list and rerun sync (camera will retry)"
    return "unknown status; inspect state file and rerun sync"


def _print_status(state_store: SyncStateStore, dry_run: bool) -> None:
    state_path = state_store.path
    if not state_path.exists():
        print(f"No state file found at: {state_path}")
        print("Current state: not started")
        print("Next step: run trailcam_sync.py to start a new sync run.")
        return

    state = state_store.load()
    print(f"State file: {state_path}")
    print(f"Version: {state.get('version', 'unknown')}")
    print(f"Last run id: {state.get('run_id_last') or '(none)'}")
    cameras = state.get("cameras", {}) or {}
    if not cameras:
        print("No camera state entries recorded yet.")
        print("Next step: run trailcam_sync.py to initialize per-camera state.")
        return

    print("")
    print("Per-camera status:")
    for alias in sorted(cameras.keys()):
        cam = cameras.get(alias) or {}
        status = str(cam.get("status", "pending"))
        downloaded_cnt = len((cam.get("downloaded") or {}).keys())
        organized_cnt = len((cam.get("organized") or {}).keys())
        errors = cam.get("errors") or []
        print(f"- {alias}: status={status}")
        print(f"  downloaded={downloaded_cnt} organized={organized_cnt} errors={len(errors)}")
        if errors:
            print(f"  last_error={errors[-1]}")
        print(f"  next={_next_step_for_status(status, dry_run)}")


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
    p.add_argument(
        "--status",
        action="store_true",
        help="Print sync state status and next action, then exit",
    )
    return p


async def main() -> None:
    args = build_parser().parse_args()
    state_store = SyncStateStore(Path(args.state_file))
    if args.status:
        _print_status(state_store, bool(args.dry_run))
        return

    cfg_path = _resolve_config_path(args.config)
    if cfg_path is None:
        raise SystemExit(
            "No config file found. Create config.yaml (see config.example.yaml), "
            "or pass --config /path/to/config.yaml"
        )
    app_cfg = load_config(cfg_path)

    final_media_dir = Path(args.final_media_dir) if args.final_media_dir else Path(app_cfg.paths.final_media_dir or _default_final_media_dir())
    dupes_dir = Path(args.dupes_dir) if args.dupes_dir else _default_dupes_dir()
    notifier = EmailNotifier(app_cfg.alerts.email)

    runner = SyncRunner(
        app_cfg=app_cfg,
        state_store=state_store,
        final_media_dir=final_media_dir,
        dupes_dir=dupes_dir,
        notifier=notifier,
        debug=bool(args.debug),
        dry_run=bool(args.dry_run),
    )
    all_ok = await runner.run_all()
    if all_ok:
        state = state_store.load()
        run_id = str(state.get("run_id_last") or "").strip() or None
        rotated = state_store.rotate_if_exists(suffix=run_id)
        if rotated is not None:
            print(f"Run successful. Rotated state file to: {rotated}")


if __name__ == "__main__":
    asyncio.run(main())
