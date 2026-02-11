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
  - Need a capture that includes the **actual file transfer** after `cmdId=1285` ACK.

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
- What transport carries **full photo/video data** after `cmdId=1285` (seq16 stream? another opcode/port)?

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

## Targeted PCAP Findings (2026-02-10)
### trailcam_2-3-view-photo.pcap
- Commands seen:
  - `cmdId=768` media list request (`pageNo=1`, `itemCntPerPage=45`)
  - `cmdId=772` thumbs ACKs (responses)
  - `cmdId=525` heartbeats
- Data stream:
  - seq16 stream carries **ARTEMIS ver=8** records (JPEGs with 72‑byte header).
  - Extracted 45 items: `mediaNum` **347–391** (one full page).
  - `typ 1..45` maps directly to `mediaNum` (slot index).

### trailcam_2-3-view-photo2.pcap
- Commands seen:
  - `cmdId=1285` download request (`fileType=0`, `dirNum=102`, `mediaNum=406`)
  - `cmdId=525` heartbeats
- No seq16 stream captured (no file payload observed).

### trailcam_2-3-download-photo.pcap
- Commands seen:
  - `cmdId=1285` download request (`fileType=0`, `dirNum=102`, `mediaNum=406`)
  - `cmdId=525` heartbeats
- No seq16 stream captured (no file payload observed).

### trailcam_1.pcap (re‑checked)
- `cmdId=769` and `cmdId=770` present (start/stop playback), and `cmdId=1285` download requests present.
- Large data stream observed is **only ver=8 thumbnails**; no obvious full photo/video data in this capture.

### trailcam_8-3-view-and-download-photo.pcap
- `cmdId=1285` download request present:
  - `fileType=0`, `dirNum=102`, `mediaNum=936`
- Data stream **does not** contain a full 7.5MB JPEG (pcap is ~3MB total).
- `D1 03` stream exists and reassembles into **ARTEMIS ver=5 typ=11/12** payloads.
  - Payloads contain **JPEG data with 72‑byte header** (MAC + dirNum + mediaNum + size, same header as thumbs).
  - Extracted JPEG size is ~1.4MB (preview / view‑photo size), not full download.

### trailcam_8-3-view-and-download-video.pcap
- `cmdId=1285` download request for `mediaNum=934` (fileType=0).
- `cmdId=769/770` start/stop playback for `mediaNum=935` (fileType=1), sessionNo=37946.
- Two data streams observed:
  - **D1 03** → ARTEMIS ver=5 typ=13/14 (JPEGs with 72‑byte header). Likely poster/preview frames.
  - **D1 02** → ARTEMIS ver=4 typ=1..?? (468 records). This stream is the **video payload**.
    - Payloads have per‑typ headers (varying length).
    - After stripping per‑typ headers (most common offsets: typ=3/4/5 → 37 bytes, typ=2/6 → 21 bytes, typ=1 → 67 bytes),
      concatenation yields a **~6.61MB raw H.264 stream** (matches MP4 size order).
    - No MP4 container atoms (`ftyp/moov/mdat`) found in stream; likely raw H.264 that the app muxes into MP4.
    - New finding: ver=4 payloads include a **108‑byte fixed header**; `payload_len` is stored in u32[4] (or u32[5] if u32[4]=0).
    - For 304 records (matching frame count), the **actual video bytes begin at payload offset 96**.
    - However, the resulting byte stream still does **not** contain Annex B SPS/PPS start codes.
      It partially matches the MP4’s AVCC/H.264 data but appears to include extra framing bytes.
    - Next step: decode the per‑frame payload framing to recover a clean AVCC or Annex‑B stream
      (so that ffmpeg can mux to MP4).


------

• Here’s what’s in pcap/trailcam_1.pcap, and which commands look new/un‑analyzed compared to what we’ve already documented.

  Decoded command IDs found in trailcam_1.pcap:

  - cmdId=0 (login)
    ver=2 typ=19, ver=3 typ=19
  - cmdId=512 (dev info)
    ver=2 typ=20/21
  - cmdId=768 (media list)
    ver=2 typ=22/24
  - cmdId=769 (NEW)
    ver=2 typ=31, ver=3 typ=31
  - cmdId=770 (NEW)
    ver=2 typ=32, ver=3 typ=32
  - cmdId=772 (thumbs)
    ver=3 typ=23/25
  - cmdId=1285 (NEW – file download start)
    ver=3 typ=26/27/28/29/30
  - cmdId=525 (heartbeat/status)
    ver=2 typ=65537..65554 (many variants)

  Commands we haven’t analyzed yet:

  1. cmdId=769
     Appears frequently. Not documented. Likely a query or paging‑related command.
  2. cmdId=770
     Appears with cmdId=769. Also not documented.
  3. cmdId=1285 (file download start)
     We haven’t decoded its request/response format yet.
  4. Undecoded ARTEMIS records
      - ver=2 typ=23/25 (1004‑byte payloads) — likely related to cmdId=772 responses.
      - ver=4 typ=1..9 (various sizes) — not decoded at all. These might be binary responses or a different channel.

  If you want, I can drill into any of these (e.g., decode cmdId=769/770 or start mapping cmdId=1285), or produce a full listing of the undecoded ARTEMIS records with payload samples.
