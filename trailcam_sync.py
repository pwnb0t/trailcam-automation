#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional

from src.sync.sync_config import create_sync_config
from src.sync.hardware_check import check_required_hardware
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


def _run_cmd(argv: list[str], timeout_s: float = 8.0) -> tuple[int, str]:
    try:
        p = subprocess.run(argv, text=True, capture_output=True, timeout=timeout_s)
    except Exception as e:
        return 1, f"{' '.join(argv)} failed: {e}"
    out = (p.stdout or "").strip()
    err = (p.stderr or "").strip()
    txt = out if out else err
    return p.returncode, txt


def _print_systemd_sync_status() -> None:
    print("Systemd units:")
    rc, _ = _run_cmd(["systemctl", "--version"])
    if rc != 0:
        print("- systemctl not available on this host")
        return

    for unit in ("trailcam-sync.service", "trailcam-sync.timer"):
        rc, out = _run_cmd(["systemctl", "status", unit, "--no-pager", "-l"], timeout_s=10.0)
        print("")
        print(f"[{unit}]")
        if rc != 0 and ("could not be found" in out.lower() or "not-found" in out.lower()):
            print("not installed")
            continue
        print(out or "(no output)")


def _latest_sync_from_rotated_state(state_path: Path) -> tuple[Optional[datetime], Optional[Path]]:
    parent = state_path.parent
    stem = state_path.stem
    suffix = state_path.suffix
    pat = re.compile(rf"^{re.escape(stem)}\.(\d{{8}}_\d{{6}})(?:\.\d+)?{re.escape(suffix)}$")

    best_dt: Optional[datetime] = None
    best_path: Optional[Path] = None
    for p in parent.glob(f"{stem}.*{suffix}"):
        m = pat.match(p.name)
        if not m:
            continue
        try:
            dt = datetime.strptime(m.group(1), "%Y%m%d_%H%M%S")
        except Exception:
            continue
        if best_dt is None or dt > best_dt:
            best_dt = dt
            best_path = p
    return best_dt, best_path


def _print_status(state_store: SyncStateStore, dry_run: bool) -> None:
    _print_systemd_sync_status()
    print("")

    state_path = state_store.path
    if not state_path.exists():
        print(f"No state file found at: {state_path}")
        last_dt, last_path = _latest_sync_from_rotated_state(state_path)
        if last_dt is not None and last_path is not None:
            print(f"Latest completed sync: {last_dt.strftime('%Y-%m-%d %H:%M:%S')} ({last_path})")
        print("Current state: not started")
        print("Next step: run trailcam_sync.py to start a new sync run.")
        return

    try:
        state = state_store.load()
    except Exception as e:
        print(f"State file is invalid: {state_path}")
        print(f"Error: {e}")
        last_dt, last_path = _latest_sync_from_rotated_state(state_path)
        if last_dt is not None and last_path is not None:
            print(f"Latest completed sync: {last_dt.strftime('%Y-%m-%d %H:%M:%S')} ({last_path})")
        else:
            print("Latest completed sync: (none found)")
        return

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
    check_required_hardware(cfg)

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
