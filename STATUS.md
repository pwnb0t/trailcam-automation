# TrailCam Automation Status (2026-02-10)

## Summary
We can now wake the camera, join its AP, authenticate, send JSON commands, receive the gallery thumbnail stream, and parse the **media list JSON** (page 0 / newest items). This means the core local control path works end‑to‑end without the phone app.

## What Works Now
- **BLE wake + credentials**
  - BLE wake command succeeds and returns SSID + password.
  - BLE handling is isolated in `ble.py`.

- **Wi‑Fi connect**
  - `nmcli` connects to the camera AP using BLE credentials.
  - Stale connection profile cleanup is in place.

- **UDP session**
  - Discovery beacons and UDP handshake (0x41/0x42/0x43, keepalive) work.
  - Login succeeds and returns `login_token_u32`.

- **Command flow**
  - JSON commands sent with AES‑CBC + base64 and ARTEMIS framing.
  - Large requests (e.g. media list / thumbs) are **chunked to 1024 bytes** with seq8.
  - Base64 payloads are **NUL‑terminated** (matches app).

- **Gallery / thumbnails**
  - Large `D1 04` stream reassembled by seq16.
  - ARTEMIS v8 records parsed; thumbnails extracted to `out/`.
  - `record_id` values align with filenames (e.g. `930` matches `DSCF0930.JPG`).

- **Media list JSON**
  - `cmdId=768` response decoded from the **assembled seq8 stream**.
  - JSON includes `mediaFiles` entries with `mediaNum`, `mediaDirNum`, `fileType`, `durationMs`, etc.
  - First page (newest items) matches what the app shows.

## Current Flow (Simplified)
1. BLE wake → SSID + password.
2. Connect to AP (`nmcli`).
3. UDP beacons + handshake (0x41/0x42/0x43, keepalive).
4. Login (`cmdId=0`), receive `login_token_u32`.
5. Send:
   - Dev info (`cmdId=512`, types 2/3/34/35)
   - Media list (`cmdId=768`, types 4/36)
   - Thumbs (`cmdId=772`, type 37)
   - Heartbeat (`cmdId=525`, types 0x00010001..)
6. Reassemble seq16 stream → thumbnails.
7. Reassemble seq8 stream → media list JSON.

## What’s Missing / Remaining Work
### 1) Stable **paging** of media list
- We can read page 0, but we need to:
  - Request `pageNo=1,2,...` and merge results.
  - Determine the stop condition (empty page or fewer than `itemCntPerPage`).

### 2) Map media list → thumbnails / downloads
- We can extract thumbnails from the large stream, but we need:
  - Mapping between `mediaFiles` entries and the thumbnail stream records.
  - Confirm if thumbnail stream is keyed off `cmdId=772` request list or only page state.

### 3) File download
- APK shows `cmdId=1285/1286` for file download, but we haven’t implemented:
  - Request body format
  - Response/stream handling

### 4) Multi‑camera support
- We now require `--ssid`. For multiple cameras we need:
  - CLI options or config mapping `SSID -> BLE MAC -> password`.
  - Convenience commands for listing known cameras.

### 5) Cleanup + reliability
- BLE can still be flaky (DBus EOF). Add retry/backoff.
- `nmcli` sometimes fails with `key-mgmt missing`. Might need explicit profile handling.
- Reduce verbose debug logging (toggle more cleanly).

### 6) Tests / tooling
- Add offline tests for:
  - ARTEMIS parse
  - AES decrypt
  - seq8/seq16 reassembly
- Add a `--pcap` mode for offline parsing and verification.

## Open Questions
- Does the camera ever return a **total count** or a “last item” indicator in `cmdId=768` JSON?
- Is `cmdId=772` required for the `D1 04` thumbnail stream, or is it triggered by `cmdId=768` alone?
- Any additional auth/handshake steps needed to guarantee deterministic behavior?

## Files of Interest
- `trailcam_client.py` (CLI orchestrator)
- `ble.py` (BLE wake)
- `flows.py` (handshake, login, JSON flow, stream parsing)
- `client.py` (UDP transport)
- `protocol.py` (F1 + ARTEMIS + AES)
- `seed.py` (thumbnail request seed extraction)
- `config.py` (constants + captured packets)

## Quick Command (current working)
```
python3 trailcam_client.py --ssid TrailCam_5DBD --json-flow --debug --thumb-offset 494 --thumb-dir 102
```

This retrieves the newest media list and thumbnails for the current camera.
