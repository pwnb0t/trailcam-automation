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
