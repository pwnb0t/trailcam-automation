#!/usr/bin/env python3
from __future__ import annotations

import asyncio

from src.sync.sync_config import create_sync_config
from src.sync.status import SyncStatus
from src.sync.sync_runner import SyncRunner
from src.sync.sync_state import SyncStateStore


def _next_step_for_status(status: str, dry_run: bool) -> str:
    s = str(status or "").strip().lower()
    if s in ("", SyncStatus.PENDING.value):
        return "connect/login, then download missing media"
    if s == SyncStatus.DOWNLOAD.value:
        return "continue download pass (list media, download missing items)"
    if s == SyncStatus.VERIFY.value:
        return "verify manifests; if missing items are found, go back to download"
    if s == SyncStatus.CLEAR.value:
        if dry_run:
            return "skip clear (dry-run), then organize"
        return "delete all media on camera, then organize"
    if s == SyncStatus.ORGANIZE.value:
        return "organize staged files into final media layout"
    if s == SyncStatus.STAGED.value:
        return "staging complete; inspect staged files or rerun without --stage-only"
    if s == SyncStatus.DONE.value:
        return "skip this camera (already done in state)"
    if s == SyncStatus.ERROR.value:
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


async def main() -> None:
    cfg = create_sync_config()
    state_store = SyncStateStore(cfg.state_file)
    if cfg.status:
        _print_status(state_store, cfg.dry_run)
        return

    runner = SyncRunner(cfg=cfg, state_store=state_store)
    all_ok = await runner.run_all()
    if all_ok and not cfg.stage_only:
        state = state_store.load()
        run_id = str(state.get("run_id_last") or "").strip() or None
        rotated = state_store.rotate_if_exists(suffix=run_id)
        if rotated is not None:
            print(f"Run successful. Rotated state file to: {rotated}")


if __name__ == "__main__":
    asyncio.run(main())
