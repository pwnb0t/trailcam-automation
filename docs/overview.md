# Docs Overview

This folder describes the on-wire protocol we have reverse engineered for the TrailCam Wi-Fi/BLE camera and the current state of the Python client in this repo.

## What Works Today
- BLE wake + credentials: retrieve camera AP `ssid`/`pwd` over BLE.
- Wi-Fi join: connect to the camera AP.
- UDP handshake + login: establish the UDP session and obtain `login_token_u32` (from `cmdId=0` response).
- Gallery: fetch media list (`cmdId=768`).
- Photo download: request and reconstruct a full-resolution JPEG via `cmdId=1285` and `D0 subtype 0x03` bulk transfer.
- Video download/playback: request and reconstruct an MP4 via `cmdId=769`/`cmdId=770` and `D0 subtype 0x02` bulk transfer.

## Outputs
- Photos: `<staging_dir>/<camera_alias>/<dirNum>/media####.jpg`.
- Videos: `<staging_dir>/<camera_alias>/<dirNum>/media####.mp4`.
- `staging_dir` is `cfg.paths.staging_dir` (commonly `/mnt/trailcam/staging` on Pi setups).
- Temporary artifacts: `cfg.paths.tmp_dir` (commonly `out/tmp/`, expected to be auto-cleaned after successful downloads).

## Document Index
- `docs/flows.md`
- `docs/opcodes.md`
- `docs/packet-format.md`
- `docs/json-commands.md`
- `docs/download-photo.md`
- `docs/download-video.md`
- `docs/video-v4-decrypt-notes.md`
- `docs/operations-from-apk.md`
- `docs/config.md`
- `docs/test-priority-plan.md`

## Historical Notes
Older notes and intermediate findings were moved to `docs/historical/`.
