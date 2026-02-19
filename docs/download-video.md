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
- Session number correlation:
  - `u32le(payload[48:52]) == sessionNo` from the `cmdId=769` start-play request (for this capture: `37946`)
  - `u32le(payload[52:56])` is consistently `1` in observed records
- Per-record varying fields:
  - `u32le(payload[64:68])` and `u32le(payload[68:72])` vary per record and are a strong candidate for a per-record nonce/counter seed

The (304, 157) split matches the known-good MP4's rough video/audio frame counts for this test video (304 video frames, 157 audio frames).

## Ground Truth From Camera SD Card (DSCF0935.MP4)

You added the camera's on-SD file:

- `pcap/DSCF0935.MP4`

`ffprobe` summary:

- Track 0: H.264 (avc1) 1920x1080, ~30 fps, `nb_frames=304`, duration `10.333s`
- Track 1: H.264 (avc1) 320x176, `nb_frames=155`, duration `10.366s`
- Track 2: AAC-LC audio, 16 kHz mono, `nb_frames=157`, duration `10.048s`

This matches the control-plane response in the PCAP for start playback:

- `cmdId=769` response includes `totalFrame=304`, `totalTime=10333`, `videoWidth=1920`, `videoHeight=1080`

It also matches the *sizes* we see in `subtype=0x02` ver=4 payloads:

- v16 family (data_len at offset 16): 304 records, total bytes ~6.52 MB
- v20 family (data_len at offset 20): 157 records, total bytes ~80 KB

For audio, we see a consistent per-record 7-byte overhead in the PCAP `v20` family, but the payload does **not** look like plain ADTS on the wire (it does not start with the ADTS syncword `0xFFF...`).

Using `tools/compare_video_pcap_to_sd_mp4.py` to compare the PCAP record bytes to the SD MP4 sample bytes:

- Audio: all 157 records satisfy `len(pcap_data[7:]) == len(mp4_sample)`, but `pcap_data[7:] != mp4_sample` for all frames.
- Video: 298/304 frames match by size, but `pcap_data != mp4_sample` for all frames.

Conclusion: the ver=4 `data` region is not a direct copy of MP4 sample bytes. The payload requires a partial AES-CBC decrypt step before it becomes standard H.264/AAC.

## Decryption: What Makes PCAP Bytes Turn Into H.264/AAC

We can now reconstruct a playable MP4 from the PCAP, without the app, by replicating the app's native decrypt step.

Key observations:

- Each `ver=4` record has a 108-byte header, then `data_len` bytes of "data".
- That `data` is **mostly plaintext**, except:
  - For each 0x1000 "page" of `data`, the first 0x60 bytes are AES-128-CBC encrypted.
- Decrypt parameters (empirically verified against `pcap/DSCF0935.MP4`):
  - AES key: ASCII string `"xs38nul7cqf7m1va"` (16 bytes)
  - IV: 16 bytes of `0x00`
  - Ciphertext length per page: 0x60 bytes (96 bytes), a multiple of 16.

What the decrypted output looks like:

- Video-like records (`data_len_off=16`, width/height set):
  - Decrypting the page-prefix bytes yields an Annex-B H.264 bytestream (`00 00 00 01` / `00 00 01` start codes).
  - This is why raw byte comparisons against MP4 `avc1` samples do not match: MP4 stores H.264 in length-prefixed (AVCC) form, while the camera stream is Annex-B.
- Audio-like records (`data_len_off=20`, width/height 0):
  - Decrypting the page-prefix bytes yields ADTS AAC frames (starts with `0xFF F9 ...`).
  - MP4 samples store raw AAC without ADTS headers, so the camera stream appears to add a 7-byte ADTS header.

### Critical Edge Condition (Fixed)

There is one non-obvious requirement for correctness:

- For each `0x1000` page, decrypt the first `0x60` bytes **only when remaining bytes are > `0x5f`**.
- Do **not** partially decrypt short tail pages.

This was previously wrong in our implementation and caused subtle video corruption (jumps/repeats) while still producing playable MP4 files.

Detailed note: `docs/video-v4-decrypt-notes.md`.

## Current State: Reconstructing A Valid MP4 From PCAP (Main Video + Audio)

From `pcap/trailcam_8-3-view-and-download-video.pcap`, we can reconstruct:

- 1920x1080 H.264 track (304 frames)
- AAC-LC audio track 16 kHz mono (157 frames)

This matches the MP4's track 0 and track 2.

What we are not reconstructing yet (for full parity with the SD-card MP4):

- The additional low-res H.264 track (320x176, 155 frames) present as track 1 in `pcap/DSCF0935.MP4`.
  - Hypothesis: this comes from a different D0 subtype stream (likely `subtype=0x03`) and needs similar extraction/decrypt logic.

## Tooling

The current extractor is:

- `tools/extract_video_from_pcap.py`
- `tools/compare_video_pcap_to_sd_mp4.py` (byte/size comparison against an SD-card MP4 oracle)

Example:

```bash
python3 tools/extract_video_from_pcap.py \
  pcap/trailcam_8-3-view-and-download-video.pcap \
  --out-dir out/video_extract8 \
  --subtypes 0x02 \
  --v4-header \
  --v4-decrypt \
  --mux \
  --fps 30
```

It will write:

- `out/video_extract8/trailcam_8-3-view-and-download-video/subtype_02_v4_records.csv`
- `out/video_extract8/trailcam_8-3-view-and-download-video/subtype_02_v4_decrypted.h264`
- `out/video_extract8/trailcam_8-3-view-and-download-video/subtype_02_v4_decrypted.aac`
- `out/video_extract8/trailcam_8-3-view-and-download-video/subtype_02_v4_decrypted_fps30.mp4`
- `out/video_extract8/trailcam_8-3-view-and-download-video/subtype_02_records/record_*.bin`

Comparison CSV (example):

```bash
python3 tools/compare_video_pcap_to_sd_mp4.py \
  --records-csv out/video_extract8/trailcam_8-3-view-and-download-video/subtype_02_v4_records.csv \
  --records-dir out/video_extract8/trailcam_8-3-view-and-download-video/subtype_02_records \
  --mp4 pcap/DSCF0935.MP4 \
  --out-csv out/video_compare/dscf0935_sub02_compare.csv
```

## Next Steps For Video (Likely Required)

If we want full parity with the SD-card MP4, we likely need:

1. Extract and decrypt the low-res 320x176 H.264 track (track 1 in `pcap/DSCF0935.MP4`) from the capture, likely from `D0 subtype=0x03`.
2. Expand live tooling to handle more subtypes/captures robustly (timeouts, retransmits, and clean stop conditions).
