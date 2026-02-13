# Video Download Notes (Playback / Gallery Video)

This document captures what we currently know about the TrailCam Go app's "tap a video in the gallery" and "download video" behavior, based on PCAPs and APK decompile.

## Command IDs (From Decompiled APK)

These are defined in `apk/jadx_full_v2/sources/com/xlink/arlink/ArCommandId.java` and used by command classes in `apk/jadx_full_v2/sources/com/xlink/arlink/`.

- `cmdId=768` `EC_CMD_ID_GET_MEDIA_LIST` (gallery listing)
- `cmdId=769` `EC_CMD_ID_START_PLAY_RECORD`
  - JSON fields: `fileType`, `dirNum`, `mediaNum`, `sessionNo`
  - Response fields: `startPbRet`, `videoWidth`, `videoHeight`, `totalFrame`, `totalTime`
  - See: `apk/jadx_full_v2/sources/com/xlink/arlink/ArStartPlayRecordCommand.java`
- `cmdId=770` `EC_CMD_ID_STOP_PLAY_RECORD`
  - See: `apk/jadx_full_v2/sources/com/xlink/arlink/ArStopPlayRecordCommand.java`

## Payload Type Constants (From Decompiled APK)

`apk/jadx_full_v2/sources/com/xlink/arlink/ArLinkApi.java` contains codec identifiers the native layer reports to Java callbacks:

- `PAYLOAD_TYPE_VIDEO_H264 = 0`
- `PAYLOAD_TYPE_VIDEO_H265 = 1`
- `PAYLOAD_TYPE_VIDEO_MJPEG = 2`
- `PAYLOAD_TYPE_AUDIO_PCM = 16`
- `PAYLOAD_TYPE_AUDIO_ADPCM = 17`
- `PAYLOAD_TYPE_AUDIO_G711 = 18`
- `PAYLOAD_TYPE_AUDIO_AAC = 20`
- `PAYLOAD_TYPE_AUDIO_G726 = 21`

This is a strong hint that the stream is decoded/deframed by native code before the Java layer consumes it.

## What We See In PCAPs

The most useful capture for this is:

- `pcap/trailcam_8-3-view-and-download-video.pcap`

High-level:

- Control-plane JSON includes `cmdId=769` (start playback) and later `cmdId=770` (stop).
- Bulk data is carried via `F1 D0` subtype streams.

Observed subtype usage (camera -> client):

- `D0 subtype=0x02`: primary stream (many packets, long continuous seq16 range)
- `D0 subtype=0x03`: secondary stream (contains at least one large preview JPEG in this capture)

## ARTEMIS Record Structure (Subtype 0x02)

After reassembly by `seq16`, `subtype=0x02` contains strict `ARTEMIS\\0` records.

For the video capture, these are primarily `ver=4` with a payload that appears to start with a fixed header.

Empirical ver=4 payload header:

- Header length: 108 bytes
- `pts_ms`: `u32le(payload[8:12])` (monotonic ms-like timestamps)
- `data_len` has 2 observed placements:
  - `u32le(payload[16:20]) == len(payload) - 108` for 304 records (video-like sizes: KBs..hundreds of KB)
  - `u32le(payload[20:24]) == len(payload) - 108` for 157 records (small sizes: ~150..600 bytes)
- Width/height in header:
  - `u32le(payload[28:32]) == 1920`
  - `u32le(payload[32:36]) == 1080`

The (304, 157) split matches the known-good MP4's rough video/audio frame counts for this test video (304 video frames, 157 audio frames).

## Ground Truth From Camera SD Card (DSCF0935.MP4)

You added the camera's on-SD file:

- `pcap/DSCF0935.MP4`

`ffprobe` summary:

- Track 0: H.264 (avc1) 1920x1080, ~30 fps, `nb_frames=304`, duration `10.333s`
- Track 1: H.264 (avc1) 320x176, `nb_frames=155`, duration ~`10.366s`
- Track 2: AAC-LC audio, 16 kHz mono, `nb_frames=157`, duration `10.048s`

This matches the control-plane response in the PCAP for start playback:

- `cmdId=769` response includes `totalFrame=304`, `totalTime=10333`, `videoWidth=1920`, `videoHeight=1080`

It also matches the *sizes* we see in `subtype=0x02` ver=4 payloads:

- v16 family (data_len at offset 16): 304 records, total bytes ~6.52 MB
- v20 family (data_len at offset 20): 157 records, total bytes ~80 KB

For audio, the sizes line up exactly with ADTS overhead:

- PCAP v20 total bytes: 80516
- MP4 audio total bytes (raw AAC samples): 79417
- 80516 - 79417 == 7 * 157 (one 7-byte ADTS header per AAC frame)

This strongly suggests the playback stream is transporting per-sample audio/video frame payloads that are then converted and muxed into an MP4 by the native layer (see `libArLink.so`, `libMP4Codec.so`).

## Current State: Not Yet Reconstructing A Valid MP4 From PCAP Alone

We can reliably:

- Extract and reassemble `subtype=0x02` and `subtype=0x03` streams by `seq16`
- Parse strict ARTEMIS records
- Split ver=4 records into the two families above

We cannot yet:

- Convert the extracted video-like payload data into a clean H.264 Annex-B stream that decodes as 1920x1080
- Mux a correct MP4 offline from PCAP data alone

What this implies:

- Either the video payload is not a direct H.264 elementary stream, or it is H.264 but requires an additional native deframing/decryption step that we have not replicated yet.

## Tooling

The current extractor is:

- `tools/extract_video_from_pcap.py`

Example:

```bash
python3 tools/extract_video_from_pcap.py \
  pcap/trailcam_8-3-view-and-download-video.pcap \
  --out-dir out/video_extract6 \
  --v4-header
```

It will write:

- `out/video_extract6/trailcam_8-3-view-and-download-video/subtype_02_v4_records.csv`
- `out/video_extract6/trailcam_8-3-view-and-download-video/subtype_02_concat_v4_data.bin`
- `out/video_extract6/trailcam_8-3-view-and-download-video/subtype_02_records/record_*.bin`

## Next Steps For Video (Likely Required)

If we want video parity without relying on the phone app, we likely need one of:

1. Reverse the native stream path in `apk/apk_unzip_v2_armeabi/lib/armeabi-v7a/libArLink.so` to replicate the deframing/decryption into H.264/AAC.
2. Instrument the Android app (Frida / debug build) to dump the post-processed bytes handed to `ArLinkApi.ArLinkPlaybackStreamCallback.receiveVideoStream()` and `receiveAudioStream()`, then derive the transformation back to PCAP bytes.
