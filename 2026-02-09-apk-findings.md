# APK Findings (TrailCam Go 2.5.6) - 2026-02-09

This document summarizes what we learned from a full `jadx` decompile of the app on the laptop.

## Extraction

- XAPK: `apk/TrailCam_Go_2.5.6_apkcombo.com.xapk`
- Extracted to: `apk/extracted_v2/`
- Decompiled with: `jadx -d apk/jadx_full_v2 apk/extracted_v2/com.xlink.trailcamgo.apk`
- Output:
  - Sources: `apk/jadx_full_v2/sources/`
  - Resources: `apk/jadx_full_v2/resources/`

`jadx` finished with a small number of errors, but the `com.xlink.arlink` package decompiled cleanly.

## Key Packages / Files

- Core protocol Java layer: `apk/jadx_full_v2/sources/com/xlink/arlink/`
  - `ArLinkApi.java` (native calls for login/sendCommand)
  - `ArPeerConnector.java` (login flow wrapper)
  - `ArCommander.java` / `ArCommandTask.java` (command dispatch)
  - `ArCommandId.java` (command IDs)
  - `ArMediaListGetCommand.java` (gallery list)
  - `ArThumbnailGetCommand.java` (thumbnail requests)

- Native library (actual transport / token handling):
  - `apk/apk_unzip_v2_armeabi/lib/armeabi-v7a/libArLink.so`

## Transport / Login Flow (Java Layer)

**Important:** `ArLinkApi.logIn(...)` and `ArLinkApi.sendCommand(...)` are native methods. The token generation/transport is likely in `libArLink.so`.

From `ArPeerConnector.start(...)`:

```
logIn(uid, password, seq, connectType, unixTime, timeoutSec, param1, param2)
```

Where:
- `uid` is a string (e.g., default UID is `LBCS-000000-CCCJJ` in `DevConnectDialog`)
- `password` is the device access password
- `connectType` appears to be `1` for LAN (see usage in `DevConnectDialog`)
- `timeoutSec` is typically `15`

The app calls `ArLinkApi.logIn(...)` and receives a **session handle** (integer). This handle is used for all subsequent commands.

## Command IDs

Defined in `ArCommandId.java`:

- `EC_CMD_ID_GET_MEDIA_LIST = 768`
- `EC_CMD_ID_GET_THUMBNAILS = 772`
- `EC_CMD_ID_GET_DEV_INFO = 512`
- `EC_CMD_ID_START_AV = 258`
- `EC_CMD_ID_STOP_AV = 259`
- `EC_CMD_ID_TRIGGER_SNAP = 641`
- `EC_CMD_ID_TRIGGER_RECORD = 643`
- `EC_CMD_ID_START_FILE_DOWNLOAD = 1285`
- `EC_CMD_ID_STOP_FILE_DOWNLOAD = 1286`

(Full list is in `apk/jadx_full_v2/sources/com/xlink/arlink/ArCommandId.java`.)

## Media List Command (Gallery Listing)

`ArMediaListGetCommand.getMessage()` builds JSON:

```
{
  "cmdId": 768,
  "itemCntPerPage": <int>,
  "pageNo": <int>
}
```

**Response parsing** in `ArMediaListGetCommand.onCommandResult(...)` expects JSON with:

- `getMediaListRet` (0 = success)
- `mediaFiles` array, where each entry includes:
  - `fileType` (maps to enum `MEDIA_TYPE`: 0 photo, 1 video mp4, 2 video avi)
  - `mediaDirNum`
  - `mediaNum`
  - `durationMs`
  - optional: `mediaId`
  - optional: `mediaTime`

This matches the gallery listing concept we observed in the PCAPs.

## Thumbnail Request Command

`ArThumbnailGetCommand.getMessage()` builds JSON:

```
{
  "cmdId": 772,
  "thumbnailReqs": [
    {"fileType": <int>, "dirNum": <int>, "mediaNum": <int>},
    ...
  ]
}
```

The response handling for thumbnail *data* is not in this Java class, implying that the binary data is probably received via the native layer and handed to the app via callbacks.

## Native Library Notes (`libArLink.so`)

- Contains strings `ARTEMIS` and `token`.
- Contains several `LBCS-00000X-XXXX` UIDs, likely defaults or test targets.
- UDP references exist, but no explicit `16734` string found in Java or native strings.

This strongly suggests:
- The **token** is generated or handled inside `libArLink.so`.
- The Java layer is **not** constructing the token.

## Implications for Our Script

- The commands we want (gallery list and thumbnails) are JSON (`cmdId`, etc.).
- We still need to replicate the **native login/handshake** in order to obtain a session handle and send commands that the device will accept.
- The 32-byte token seen in PCAPs is likely derived inside the native login/handshake (not BLE).

Next step should be to correlate the native login flow with the PCAP connect handshake and see where the token is computed or transmitted.
