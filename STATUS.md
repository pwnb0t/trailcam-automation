# TrailCam Automation Status

## Works Now
- BLE wake and retrieve AP credentials (`ssid`/`pwd`).
- Join camera AP via `nmcli`.
- UDP handshake + login to obtain `login_token_u32`.
- Media list (`cmdId=768`) and thumbnails (`cmdId=772`).
- Photo download (`cmdId=1285`) and reconstruction of full-resolution JPEG (saved as `download.jpg`).
- Video download/playback (`cmdId=769` start, `D0 subtype=0x02` decrypt, `cmdId=770` stop) and reconstruction of MP4 (H.264 + AAC).

## Next Steps
1. Make paging deterministic for media list (`pageNo=0..N`) with a clean stop condition and a maximum page limit (`--list-max-pages`).
2. Add offline “replay from pcap” tests for parsers and reassembly to prevent regressions.
3. Turn the current CLI flows into a stable library API for automation (cron, downloads, sync to NAS, etc.).

## Docs
- `docs/overview.md`
- `docs/flows.md`
- `docs/opcodes.md`
- `docs/packet-format.md`
- `docs/json-commands.md`
- `docs/download-photo.md`
- `docs/download-video.md`
- `pcap/details.md`


---------

# Some things I want to do:

* Add a .env or env.yml file to store the various settings of the client
  * Add trailcams to env. Have "front" "back" aliases and then MAC in the env.
  * I think I want most "default" options to be configurable from this env. The "single download" and others like that should still be script options.
* Create a Config class to hold env or anything else. Ideally it would be immutable but probably would have to be after
* Maybe remove SSID option and only use MAC address option. Should get SSID from MAC from the trailcam. Could still just do both in the env with SSID as a verification step?
* /mnt/trailcam is hooked up. 
  * Need to send files to /mnt/trailcam/staging then the final output to /mnt/trailcam/media
* Need an orchestration script (trailcam_sync.py)
  * Needs to have env.
  * Resumable state file (perhaps a manifest of items to download and what is downloaded)
* File structure and naming/renaming
  * Download files to staging. Move files from staging to media and rename
  * front_YYYYMMDD_HHMMSS.jpg, back_20260213_132127.mp4, ...
  * Split by week: /mnt/trailcam/media/YYYY-WW/front_YYYYMMDD_HHMMSS.jpg
  * Week cutoff should be Sundays at 8am. (I'll be running the script daily at 10am)

* Connection logic
  * Currently does BLE wake -> AP join -> UDP handshake -> login.
  * If already on AP, then it skips BLE wake and AP join. But it is possible the trailcam has gone to sleep and we receive "TimeoutError: Did not see any inbound UDP from camera"
  * In this case, it should instead go back to BLE wake.
  * I would like it if all of this was contained in its own class/step before moving forward.

* Code reorg
  * Rename trailcam_client.py to trailcam_client_runner.py
  * Add trailcam_sync.py (orchestrator)
  * All the trailcam_client related files go in src/client/
  * All the trailcam_sync related files go in src/sync/
  * Could also have src/common/ or just better named dirs as we go.

---------

# last query sent to Codex:

› I'm running a test for `python3 trailcam_client.py --ssid TrailCam_5DBD --download-page --page-no 0 --page-item-cnt 48` and it appears to be working. The ultimate goal is to automate downloading all the items off of the device and then either deleting them or running the format operation. For now I still want to focus on downloading all the items from the trailcam. What's going to be the best way to handle this? Is it to continue to extend the current trailcam_client? Or should there be a separate orchestration script? What do you think?


• Separate orchestration script, keep trailcam_client.py as the “one-camera, one action” tool.

  Reasoning:

  - trailcam_client.py is already doing a lot (BLE, Wi-Fi, UDP, login, list, download). Turning it into a long-running “sync daemon” will make it harder to test and harder to recover from partial failures.
  - A sync loop wants retry logic, progress tracking, idempotency (skip already-downloaded), and eventually delete/format. That’s cleaner as an orchestrator calling library functions.

  Concrete shape I’d do next:

  1. Promote a small stable API in flows.py for sync to use:

  - fetch_media_list_all(...) to enumerate all items (paged).
  - download_media_item(...) that takes {dirNum, mediaNum, fileType} and writes to out/media/..., returning success + path(s).
  - Optional: ensure_connected_and_logged_in(...) wrapper (BLE + Wi-Fi + handshake + login) returning a ready client, token.

  2. New script trailcam_sync.py (or tools/sync_all_media.py):

  - Inputs: --ssid, --out-root, --max-pages, --resume/--state-file, --concurrency 1 (keep 1), --video-fps, timeouts.
  - Behavior:
      - Connect/login once.
      - List all media.
      - For each item, download if missing locally (existence check by stable filename).
      - Write a small state file (JSON) of completed keys (dirNum, mediaNum, fileType) so reruns resume cleanly.
      - Print a compact summary at end: total listed, downloaded, skipped, failed.

  3. Keep trailcam_client.py for debugging primitives:

  - --list-media-all
  - --download-photo/--download-video
  - --download-page

  If you want, I can implement trailcam_sync.py next with a resumable state file and a “download everything” loop using the existing working download paths.
