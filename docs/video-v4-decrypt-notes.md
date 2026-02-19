# Video v4 Decrypt Notes (Critical Edge Case)

This note documents the exact issue that caused "jumpy/repeated" video output and the fix now used by runtime and offline tools.

## Scope
- Applies to playback/download video stream records (`ARTEMIS ver=4`) from `D0 subtype=0x02`.
- Relevant code:
  - `src/protocol.py` -> `decrypt_v4_media_data_pages()`
  - `tools/extract_video_from_pcap.py` -> `decrypt_v4_data_in_pages()`

## Correct Native Behavior

From native `libArLink.so` decompile (`FUN_000320b0`, stream case):
- Process payload in `0x1000` byte pages.
- Per page, decrypt exactly the first `0x60` bytes with AES-128-CBC (`key=xs38nul7cqf7m1va`, `iv=0x00*16`).
- Decrypt loop condition is effectively: only run while remaining bytes are `> 0x5f`.

Practical implication:
- Full/normal pages: decrypt prefix `0x60`.
- Short tail page with fewer than `0x60` remaining bytes: **do not decrypt partial tail**.

## Previous Incorrect Behavior

Previous implementation decrypted the largest multiple-of-16 on short tails.

Example of incorrect old logic:
- if 48 bytes remained on a final page, decrypt those 48 bytes.

Why this is wrong:
- Native code does not decrypt those tail bytes.
- Tail bytes are plaintext in this case.
- Decrypting them corrupts payload data at record/page boundaries.

## Symptoms
- MP4 is produced and usually playable.
- Visual corruption appears as segment repeats/jumps or broken motion continuity.
- Frame comparison versus app/original diverges early.

## Fix Applied

Both runtime and extractor now use:
- `for off in range(0, len(data), 0x1000):`
- `if (len(data) - off) <= 0x5f: continue`
- decrypt exactly `data[off : off+0x60]` (AES-128-CBC, zero IV)

No partial decrypt for short final tails.

## Verification Results

After fix:
- `media0105` (runtime output) matches SD original frame-for-frame (`305/305` position matches).
- `trailcam_8-3-view-and-download-video.pcap` reconstructed output matches app-saved mp4 frame-for-frame (`304/304`).

## Regression Guidance

If video artifacts reappear, verify these first:
1. Tail-page condition still enforces `remaining > 0x5f`.
2. Prefix decrypt size is fixed `0x60` (not dynamic).
3. Page size remains `0x1000`.
4. AES key and IV unchanged for this stream path.

