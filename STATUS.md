# TrailCam Automation Status (2026-02-11)

## Current State
Core local control works end-to-end without the phone app:

1. Wake camera over BLE and get AP credentials.
2. Join camera AP with `nmcli`.
3. Complete UDP handshake/login.
4. Send encrypted JSON commands (`cmdId=512`, `768`, `772`, `525`).
5. Decode media list page 0 and extract thumbnails.

This is enough to connect reliably and list newest gallery items.

## Main Blocker
Full media download parity with the app is not complete yet.

- `cmdId=1285` request/ACK path is confirmed.
- Large binary payloads after `1285` are confirmed.
- Exact reconstruction of the app-saved full photo/video files is still incomplete.

## Next Steps (Priority)
1. **Collect one clean non-truncated photo-download capture**
   - Minimal action sequence only: connect -> open target photo once -> download once -> stop.
2. **Map `1285` data payload structure**
   - Identify exact framing/check bytes needed to reconstruct the final app-equivalent file.
3. **Implement photo download in client**
   - Build request from `mediaDirNum/mediaNum/fileType`.
   - Reassemble and write decoded file output.
4. **Implement paging for media list**
   - Iterate `pageNo=0..N` with deterministic stop condition.
5. **Add offline verification mode/tests**
   - Replay pcap to validate parsers/reassembly before live runs.

## Active Questions
1. Is the final app-saved media file formed directly from one payload stream, or composed/filtered across multiple streams?
2. Are there additional transfer control steps around `cmdId=1285` not yet reproduced by our client?
3. Does full video retrieval share the same transfer framing as photo retrieval, or only partial overlap?

## Working Command
```bash
python3 trailcam_client.py --ssid TrailCam_5DBD --json-flow --debug
```

## Detail Docs
- `2026-02-06-protocol-summary.md`
- `2026-02-08-connect-findings.md`
- `2026-02-08-gallery-refresh-findings.md`
- `2026-02-09-apk-findings.md`
- `2026-02-11-photo-download-findings.md`
- `pcap/details.md`
