# TrailCam Automation Status

## Works Now
- BLE wake and retrieve AP credentials (`ssid`/`pwd`).
- Join camera AP via `nmcli`.
- UDP handshake + login to obtain `login_token_u32`.
- Media list (`cmdId=768`) and thumbnails (`cmdId=772`).
- Photo download (`cmdId=1285`) and reconstruction of full-resolution JPEG (saved as `download.jpg`).

## Main Gap
- Video download parity is not implemented yet.

## Next Steps
1. Implement video playback/download (`cmdId=769` start play, stream decode, `cmdId=770` stop) and reconstruct an MP4 offline.
2. Make paging deterministic for media list (`pageNo=0..N`) with a clean stop condition.
3. Add offline “replay from pcap” tests for parsers and reassembly to prevent regressions.

## Docs
- `docs/overview.md`
- `docs/flows.md`
- `docs/opcodes.md`
- `docs/packet-format.md`
- `docs/json-commands.md`
- `docs/download-photo.md`
- `docs/download-video.md`
- `pcap/details.md`
