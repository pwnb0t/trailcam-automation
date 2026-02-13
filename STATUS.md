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
