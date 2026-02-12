# 2026-02-11 Photo Download Findings (trailcam_9)

## Scope
- Capture: `pcap/trailcam_9-connect-thru-download-photo.pcap`
- Notes: `pcap/details.md`
- Expected app-saved file: `pcap/2026-02-11_11.51.29.646_4B5805A2.jpg`

`tshark` reports the pcap is truncated at the end, but almost all packets are still readable and useful.

## Verified Command Sequence
From the phone-to-camera direction (`192.168.43.20:49239 -> 192.168.43.1:40611`):

1. `cmdId=0` login
2. `cmdId=512` dev info
3. `cmdId=768` media list (`pageNo=0`, `itemCntPerPage=45`)
4. `cmdId=772` thumbnail request
5. `cmdId=1285` file download request (retries observed)
6. `cmdId=525` heartbeat/status repeated throughout session

## Exact Download Request Seen
Decoded request payload for the photo download:

```json
{"cmdId":1285,"downloadReqs":[{"fileType":0,"dirNum":102,"mediaNum":938}],"token":144264967}
```

Observed at frames `1430`, `1431`, `1432` (and again at `2607`, `2608`).

Camera ACK:

```json
{"cmdRet":0,"result":0,"cmdId":1285}
```

Observed at frames `1433`, `2610`, `2612`.

## Thumbnail Request Near Download
The `cmdId=772` request immediately before download includes media numbers descending from `938` through at least `923` in `dirNum=102`, alternating `fileType` photo/video entries.

## File Transfer Observations
After `cmdId=1285` ACK, camera sends large binary ARTEMIS payloads:

- `ver=5 type=6 len=1048449` (starts around frame `1437`)
- `ver=5 type=7 len=1048449` (starts around frame `2613`)

From reassembly:
- `type=6` contains a valid JPEG payload (SOI/EOI present) that decodes as `7680x4320`.
- This payload is not byte-identical to the app-saved file.
- App-saved file is `5120x2880`, `5726201` bytes.

Interpretation:
- We have confirmed protocol-level `1285` request/ACK and associated large binary transfer.
- This specific pcap does not provide a clean path to reconstruct the exact final saved `5120x2880` file content.
- Truncation and/or additional app-side processing/selection likely affects final output.

## Decompiled Code Naming: cmdId vs ver/type
What is explicitly documented in decompiled Java:

- `cmdId` map: `apk/jadx_full_v2/sources/com/xlink/arlink/ArCommandId.java`
- Per-command JSON fields in command classes, e.g.:
  - `ArMediaListGetCommand` (`cmdId=768`, `pageNo`, `itemCntPerPage`)
  - `ArMediaFileDownloadCommand` (`cmdId=1285`, `downloadReqs`)

What is not explicitly documented in Java:

- ARTEMIS header semantic names for `ver` and `type`.
- Those appear to be native protocol internals in `libArLink.so`.

Native hints (strings in `libArLink.so`) include:
- `ARTEMIS`
- `cmdId`
- `Recved unknown msgId:%d`
- `OnFileDownload_RecvData`
- `OnThumbnail_RecvData`
- `Media file check failed ... tailData ...`
- `File download data ... checkData ...`

## Next Capture Requirements (to close photo-download gap)
1. Start capture before launching app.
2. Perform only: connect -> open target photo once -> tap download once -> wait 10s -> stop.
3. Avoid any extra swipes or repeated taps.
4. Ensure capture is not truncated.
5. Keep exported downloaded file for exact hash/size comparison.

## Update: trailcam_10 (cleaner capture)

Capture: `pcap/trailcam_10-connect-thru-download-photo.pcap`  
Saved file: `pcap/2026-02-11_12.51.46.448_CC164BCE.jpg` (`5120x2880`, `5391464` bytes)

This capture is not truncated and confirms:

1. Thumbnail request includes newest item:
   - `cmdId=772` with `mediaNum=940` (dir `102`) down through older items.
2. File download request is explicit:
   - `{"cmdId":1285,"downloadReqs":[{"fileType":0,"dirNum":102,"mediaNum":940}],"token":...}`
3. Camera returns `cmdId=1285` ACK (`cmdRet=0`), then large binary transfers:
   - `ver=5 type=6 len=988233`
   - `ver=5 type=7 len=988233`

Observed payload characteristics:

- `ver=5 type=7` contains a valid JPEG (`7680x4320`).
- `ver=5 type=6` in this run appears partially corrupted/non-decodable as a standalone image.
- Neither extracted stream image is byte-identical to the app-saved `5120x2880` file.

Conclusion from `trailcam_10`:

- The non-truncated run strengthens confidence in the `1285` control path and binary transfer framing.
- Remaining gap is now narrower: determine how app derives final `5120x2880` output from these transfer payload(s).
