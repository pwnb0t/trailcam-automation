# trailcam_sync Plan

This document is a concrete plan for building `trailcam_sync.py`, which will orchestrate downloading all media from all configured cameras and organizing it on the NAS.

## Goals
- Sync **all cameras** in `config.yaml` by default.
- Download all media items (photos + videos) from each camera to a **staging** area.
- Organize staged files into a stable **final** layout.
- Be **resumable**: safe to re-run after crashes/network failures without re-downloading everything.
- Do **not** delete/format the SD card yet; defer destructive operations until sync is reliable.

## Assumptions / Conventions
- `config.yaml` defines camera aliases under `cameras:` (eg `back`, `front`).
- Staging will be per-camera:
  - `cfg.paths.media_out_dir/<alias>/...` (eg `/mnt/trailcam/staging/back/...`)
- Final layout will preserve `(dirNum, mediaNum)` in filename for traceability:
  - `/mnt/trailcam/media/YYYY-WW/<alias>_<YYYYMMDD>_<HHMMSS>_<dirNum>-<mediaNum>.<jpg|mp4>`
- Week cutoff logic: Sunday 08:00 local time (as noted in `STATUS.md`).

## Non-Goals (First Iteration)
- Deleting individual files on the camera.
- Formatting the SD card.
- Multi-host coordination (Pi vs laptop) beyond “run on Pi where BLE/Wi-Fi works”.

## High-Level Flow (Per Camera)
State machine (persisted per camera):
1. `pending`
2. `download`
3. `verify`
4. `clear` (placeholder: TODO; no destructive actions yet)
5. `organize`
6. `done`

### State: `download`
- Build `staging_manifest` by scanning staged files on disk for this camera alias.
- Build `trailcam_manifest` by listing camera media pages until stop condition.
- Compute missing items = `trailcam_manifest - staging_manifest`.
- Download missing items to staging using the existing packet-level implementations:
  - Photos via `download_photo_to_out_item(session, dirNum, mediaNum)`
  - Videos via `send_video_download_flow_item(session, dirNum, mediaNum, out_mp4_path=...)`
- Write staged outputs into `.../<alias>/<dirNum>/media####.{jpg|mp4}` to match the existing stable layout, but under the alias prefix directory.
- Update sync state after each successful item (atomic state save).
- Transition to `verify`.

### State: `verify`
Purpose: confirm the staging set matches the camera set without requiring a full expensive relist every time.
- Rebuild `staging_manifest` from disk (cheap).
- Re-list a bounded number of newest pages from the camera:
  - If any items in these pages are missing from staging, transition back to `download`.
- If verify passes, transition to `clear`.

Fallback:
- If “bounded verify” repeatedly detects gaps, do a full camera manifest rebuild and re-compute missing.

### State: `clear`
- Placeholder in v1.
- Print `TODO - format cam: <alias>` (or noop).
- Transition to `organize`.

### State: `organize`
- Ensure `staging_manifest` exists (or rebuild it).
- For each staged item:
  - Determine final filename based on `(alias, mediaTime if present else fallback, dirNum, mediaNum, ext)`.
  - Compute destination directory based on `YYYY-WW` week bucket (with Sunday 08:00 cutoff).
  - Move into final location (or copy then delete if crossing filesystems).
  - Collision policy:
    - If destination file exists and bytes are identical: treat as already organized.
    - If destination file exists and differs: move incoming to `/mnt/trailcam/dupes/<run_id>/...` and record collision in state.
- Transition to `done`.

## Stop Conditions For Listing
When building `trailcam_manifest`, stop paging when one of these holds:
- Empty page response.
- Page keys repeat (same `(dirNum, mediaNum, fileType)` set as previous page) more than N times.
- “No new items” for N pages in a row (state-aware).
- Hard cap at `cfg.client.list_max_pages`.

## Sync State File
Prefer JSON for state (safe machine writes); YAML stays for config.

Proposed file:
- `out/state/trailcam_sync_state.json` for local runs, or `/mnt/trailcam/state/trailcam_sync_state.json` on Pi.

Suggested schema:
```json
{
  "version": 1,
  "run_id_last": "20260215_101500",
  "cameras": {
    "back": {
      "status": "download",
      "downloaded": {
        "102:940:0": {"staged_path": "/mnt/trailcam/staging/back/102/media0940.jpg", "size": 5821934},
        "102:941:1": {"staged_path": "/mnt/trailcam/staging/back/102/media0941.mp4", "size": 12345678}
      },
      "organized": {
        "102:940:0": {"final_path": "/mnt/trailcam/media/2026-07/back_20260211_115129_102-940.jpg"}
      },
      "last_seen_head": {"102": 940}
    }
  }
}
```

Key choice:
- Use `(dirNum, mediaNum, fileType)` as the primary key. This matches the protocol’s stable identifiers and is sufficient for “resume and skip”.

## Proposed Code Layout
Create a new `src/sync/` package and keep protocol logic out of it.

Files:
- `trailcam_sync.py`: CLI entrypoint, very thin.
- `src/sync/sync_runner.py`: orchestration loop, state machine.
- `src/sync/sync_state.py`: load/save JSON state atomically.
- `src/sync/manifest.py`: staging manifest scan + trailcam manifest collection (via existing flows).
- `src/sync/organize.py`: final naming + week bucketing + collision handling.

## Class Outlines

### `SyncRunner`
```python
class SyncRunner:
    def __init__(self, base_cfg: RunnerConfig, app_cfg: AppConfig): ...
    async def run_all(self) -> None: ...
    async def run_camera(self, alias: str) -> None: ...
```

Notes:
- `SyncRunner` should load `AppConfig` so it can iterate all camera aliases.
- For each camera alias, it will build a `RunnerConfig` for that camera and call `connect_and_login()` to get a `TrailCamSession`.

### `SyncStateStore`
```python
class SyncStateStore:
    def __init__(self, path: Path): ...
    def load(self) -> SyncState: ...
    def save(self, state: SyncState) -> None: ...  # atomic write
```

### `StagingManifest` / `TrailcamManifest`
```python
@dataclass(frozen=True)
class MediaKey:
    dir_num: int
    media_num: int
    file_type: int  # 0 photo, 1 video

class StagingManifest:
    def __init__(self, root: Path): ...
    def keys(self) -> set[MediaKey]: ...
    def path_for(self, key: MediaKey) -> Path: ...

class TrailcamManifest:
    def __init__(self, keys: set[MediaKey], meta: dict[MediaKey, dict]): ...
    @classmethod
    def collect(cls, session: TrailCamSession, *, max_pages: int) -> "TrailcamManifest": ...
```

### `Organizer`
```python
class Organizer:
    def __init__(self, *, final_root: Path, dupes_root: Path, week_cutoff: str): ...
    def dest_for(self, alias: str, entry_meta: dict, key: MediaKey) -> Path: ...
    def move_one(self, src: Path, dst: Path, *, run_id: str) -> str: ...  # "moved|skipped|dupe"
```

## Open Items To Decide Before Implementation
- Where does sync state live on Pi? `out/state/` vs `/mnt/trailcam/state/`.
- Whether staging and final are always on the same filesystem (affects move vs copy+delete).
- Whether to keep the “raw stable layout” permanently, or only keep organized outputs.

