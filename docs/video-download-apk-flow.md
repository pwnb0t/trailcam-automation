# APK Video Download Flow (Decompiled Outline)

This document summarizes the **actual app-side flow** used for video download in TrailCam Go (`com.xlink.trailcamgo`), based on decompiled Java and the ArLink SDK wrapper classes.

## Scope
- Focus: downloading a gallery video from camera to phone storage.
- Sources: `apk/jadx_full_v2/sources/com/xlink/trailcamgo/...` and `apk/jadx_full_v2/sources/com/xlink/arlink/...`.
- Note: low-level UDP packetization/encryption and stream framing are inside native `ArLinkApi`/`libArLink.so`, not in Java.

## High-level flow
1. UI selects current video item and calls `CameraVideoPlayer.startDownloadVideo(...)`.
2. App allocates local MP4 writer (`MP4Codec`) and per-stream byte buffers.
3. App registers a playback-stream callback keyed by a random `sessionNo`.
4. App sends `StartPlayRecord` command (`cmdId=769`) with `fileType/dirNum/mediaNum/sessionNo`.
5. Native layer delivers PB video/audio frames to callback.
6. Java callback writes frames into `MP4Codec` (`writeVideoFrame`, `writeAudioFrame`).
7. Native emits `playRecordEnd`; app closes MP4, scans/saves to album, and reports completion.
8. If user stops early, app sends `StopPlayRecord` (`cmdId=770`), finalizes, then removes temp file.

## Entry points
- `CameraMediaViewActivity.PhotoViewAdapter.startDownloadCurrentVideo(...)` calls:
  - `cameraVideoPlayer.startDownloadVideo(dirNum, mediaNum, mediaId, mediaType.ordinal(), listener)`
  - File: `apk/jadx_full_v2/sources/com/xlink/trailcamgo/activity/album/CameraMediaViewActivity.java`.
- Similar call path exists from album fragment:
  - File: `apk/jadx_full_v2/sources/com/xlink/trailcamgo/activity/album/CameraAlbumFragment.java`.

## Command mapping used by app
From `ArCommandId`:
- `769` = `EC_CMD_ID_START_PLAY_RECORD`
- `770` = `EC_CMD_ID_STOP_PLAY_RECORD`
- `1285` = `EC_CMD_ID_START_FILE_DOWNLOAD` (used by photo/file download command path)

File: `apk/jadx_full_v2/sources/com/xlink/arlink/ArCommandId.java`.

### Start play command payload
Built by `ArStartPlayRecordCommand.getMessage()`:
```json
{
  "cmdId": 769,
  "fileType": <mediaType ordinal>,
  "dirNum": <dir>,
  "mediaNum": <media>,
  "sessionNo": <random>
}
```
It parses response fields:
- `startPbRet`
- `videoWidth`, `videoHeight`
- `totalFrame`, `totalTime`

File: `apk/jadx_full_v2/sources/com/xlink/arlink/ArStartPlayRecordCommand.java`.

### Stop play command payload
Built by `ArStopPlayRecordCommand.getMessage()`:
```json
{ "cmdId": 770 }
```
File: `apk/jadx_full_v2/sources/com/xlink/arlink/ArStopPlayRecordCommand.java`.

## Download implementation details in `CameraVideoPlayer`
File: `apk/jadx_full_v2/sources/com/xlink/trailcamgo/widgets/CameraVideoPlayer.java`.

### Setup
- Creates temp file in recording directory via `Paths.getRecordingDirectory(...)` + `Paths.getCacheFormattedName(..., mediaId)`.
- Allocates:
  - video buffer: `ByteBuffer.allocateDirect(2097152)`
  - audio buffer: `ByteBuffer.allocateDirect(4096)`
- Initializes `MP4Codec` and creates output MP4 file.

### Stream callback registration
- Generates random playback session number (`iRandom`).
- Registers callback with `ArLinkApi.addPBAVStreamCallback(callback, iRandom)`.
- Fills `mStartPlayRecordParam` and sends `ArtemisStartPlayRecordCmd` (cmd 769).

### Per-frame handling
Inside playback callback:
- `receiveVideoStream(...)`:
  - Copies incoming bytes into `mVideoFrameByteBuffer`.
  - Drops a special sentinel frame prefix `00 00 00 01 01`.
  - Clamps width/height by model rules (e.g. 1920x1080 for Wi‑Fi TrailCam/T680W; 2560x1440 for PR8xxx/SVH model IDs).
  - Writes frame: `mMP4Codec.writeVideoFrame(buffer, len, isIFrame, width, height, pts)`.
  - Updates progress using `receivedFrames / totalFrames`.
- `receiveAudioStream(...)`:
  - Copies into `mAudioFrameByteBuffer` and calls `mMP4Codec.writeAudioFrame(buffer, len, pts)`.

### End-of-stream handling
On `playRecordEnd(...)`:
- Closes/deinitializes `MP4Codec`.
- Clears buffers.
- Media scan + save to album (API >= 29 uses MediaStore copy).
- Sends progress `100` and completion callback.

## Storage behavior
- Temp file naming includes timestamp + mediaId hex.
- Final gallery-visible save path is handled by `AlbumFileUtils.saveRecordToAlbum(...)` under:
  - `DCIM/<AppName>/<AppName>-Videos/`
- On manual stop (`stopDownloadVideo`), it can save then delete temp file.

Files:
- `apk/jadx_full_v2/sources/com/xlink/trailcamgo/utils/Paths.java`
- `apk/jadx_full_v2/sources/com/xlink/trailcamgo/utils/AlbumFileUtils.java`

## Native boundary (important)
`ArLinkApi` methods are native for transport/codec boundary:
- `sendCommand(...)`, `logIn(...)`, and stream callbacks dispatch (`OnPBVideo_RecvData`, `OnPBAudio_RecvData`, `OnPBEnd`).
- Java code does not expose packet-level ACK/window logic; that behavior is in native layer (`libArLink.so`).

File: `apk/jadx_full_v2/sources/com/xlink/arlink/ArLinkApi.java`.

## Practical takeaway for our client
- The app’s **video download path is playback-stream-based** (`769/770`), not the photo file-download path (`1285`).
- App writes a new MP4 from received PB frames using `MP4Codec`; it is not a direct file blob save.
- Matching app behavior requires reproducing:
  - start/stop playback control,
  - session-scoped PB stream selection,
  - frame typing/PTS handling,
  - model-specific dimension handling,
  - MP4 mux/write semantics.
