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

## libArLink.so Analysis (native)

File: `apk/apk_unzip_v2_armeabi/lib/armeabi-v7a/libArLink.so`

### High-level observations

- ELF 32-bit ARM shared object, stripped (no symbols).
- Contains AES and CRC routines, plus PPPP/P2P-style function names.
- Contains log strings indicating **login**, **command send**, **cmdId parsing**, **thumbnail recv**, **file download**, and **token**.

### Notable strings found

These indicate the native login/transport layer and likely the source of the 32-byte session token:

- `EC_Login, uid:%s, usrName:%s, password:%s, handle:%d`
- `sendCommand:%s, seq:%d`
- `get cmdId fail`
- `cmdId`
- `Parse cmd, lwlaes_decrypt fail`
- `sendCommand lwlaes_encrypt fail`
- `token`
- `ARTEMIS`

Transport / P2P indicators (PPP/PPPP style):

- `PPCS_LoginStatus_Check`
- `cs2p2p_PPPP_Proto_Send_DevLgn...`
- `cs2p2p_PPPP_Proto_Send_DevLgnAck...`
- `cs2p2p_PPPP_Proto_Send_SDevLgn...`
- `cs2p2p_PPPP_thread_recv_Proto...`
- `Start p2p connect to:%s, connectType:%d, bEnableLanSearch:%8x`

Crypto indicators:

- `AES_set_encrypt_key`, `AES_cbc_encrypt`, `AES_encrypt`
- `_NDT_AES128_Encrypt`, `_NDT_AES128_Decrypt`
- `_NDT_gAES128Key`, `_NDT_gAES128KeyArray`

### Implications

- The **token is not in Java**. The presence of `token` in the native library plus the AES routines strongly suggests that the 32-byte token and/or handshake derivation is computed inside `libArLink.so` during `ArLinkApi.logIn(...)`.
- The JSON commands (`cmdId`, media list, thumbnails) are created in Java and passed to native; the native layer encrypts/encapsulates them (see `lwlaes_encrypt`/`lwlaes_decrypt` logs).
- The P2P stack appears to be PPPP/CS2P2P with LAN/Relay/P2P modes and CRC validation; login uses `DevLgn`/`SDevLgn` protocol messages.

### What we can’t see yet

- The exact token derivation or handshake payload layout, because the library is stripped and we don’t have a disassembler/decompiler (binutils/ghidra/r2).

### Next steps for deeper analysis

If you want to go deeper, the best options are:

1. **Use Ghidra** on `libArLink.so` to locate `EC_Login` and trace token generation.
2. Install **binutils** (for `readelf`, `objdump`, `nm`) and attempt a basic control-flow trace.
3. Dynamic tracing (on Android, with Frida) of `ArLinkApi.logIn(...)` and surrounding native calls.

Even without those, we now know:

- The token is almost certainly **native-generated** during login.
- The command protocol is JSON with `cmdId` (Java-side) and is encrypted/packed in native code.

## Native: sendCommand Injects Token Into JSON

By decompiling `Java_com_xlink_arlink_ArLinkApi_sendCommand` and its helper (`fcn.00022f58`), we found the command flow:

1. `sendCommand(...)` allocates a buffer for the JSON string from Java.
2. It calls `fcn.00022f58` which:
   - Logs: `EC_SendCommand enter, handle:%d, command:%s, seq:%d`
   - Looks up the active session object
   - **Reads a per-session token**
   - Builds a new JSON string containing the original command plus a `"token"` field
   - Logs: `pCmdWithTokenStr:%s`
   - Calls `fcn.00021130` to actually send the command

### Token usage (from decompile)

Inside `fcn.00022f58` we see:

- It calls `0x21de4` which reads a pointer at `[session + 0x18c]` (likely the token string).
- It then calls `fcn.0001e65c` with `"token"` to inject the token into the JSON object.
- It uses `fcn.0001de00` / `fcn.0001ec70` to build and escape the final JSON string (`pCmdWithTokenStr`).

This means **the token is required for all commands**; it is not part of the Java command JSON and is injected natively just before sending.

### Implications

- Our script must obtain this token (or replicate its derivation) before we can send `cmdId` commands successfully.
- The token appears to be stored on a session object created during login; it is probably returned by the camera during the connect/login exchange.

## Ghidra: Token Storage and Injection

Using Ghidra headless, we decompiled the functions that reference `"token"` and command send:

### `FUN_00032f58` — Send command (injects token)

This function is called by the JNI `sendCommand(...)` path and:

- Looks up the session by handle (`FUN_00032f34`).
- Retrieves a token via `FUN_00031de4(session->0x0c)`.
- Injects it into the outgoing JSON using `FUN_0002e65c(..., "token", token)` (inferred from string/xref).
- Builds the final JSON string (`FUN_0002de00` + `FUN_0002ec70`).
- Sends it via `FUN_00031130(...)`.

### `FUN_00032020` — Parse login response and store token

This function parses a JSON response and writes:

```
*(session + 0x18c) = <token_string_pointer>
```

It uses JSON helpers (`FUN_0002ddf8`, `FUN_0002e382`) and specifically extracts the `"token"` key, storing it in the session structure at offset `0x18c`.

This is the missing link: **the token is parsed from a login response and stored**, then later injected into every command.

### `FUN_00032a1c` — Login handler

This appears to initialize a session object and trigger the login flow. It logs:

```
EC_Login, uid:%s, usrName:%s, password:%s, handle:%d
```

### `FUN_00032c04` — Login result callback

This logs:

```
EC_OnLoginResult, handle:%d, errorCode:%d, seq:%d
```

and dispatches callbacks based on login result codes.

## Practical Impact

To replicate the app’s behavior:

1. We must perform the login/handshake sequence that returns a JSON containing `"token"`.
2. We must store and inject that token into all subsequent JSON commands before sending.

Without the token, the camera will ignore or reject `cmdId` commands.

## Command Encryption Details (native)

We now have the actual AES details used by the native command channel (from Ghidra decompile + callsite analysis in `libArLink.so`).

### AES key

The AES key used for command encryption/decryption is a static 16-byte ASCII string stored in the binary:

```
xs38nul7cqf7m1va
```

This was found by analyzing the `FUN_00031130` callsite:

- The call to `FUN_00034cf0(...)` loads a literal at `0x31460`, then `add r0, pc` to get the key pointer.
- Resolving that PC-relative literal points to address `0x00026ada`, whose bytes are:

```
78 73 33 38 6e 75 6c 37 63 71 66 37 6d 31 76 61
```

Which is ASCII for `xs38nul7cqf7m1va`.

### Encryption/Decryption functions

The command payload uses AES-128-CBC with **zero IV** and **zero padding**.

#### Encrypt + Base64 (`FUN_00034cf0`)

- `AES_set_encrypt_key(key, 0x80, ...)`
- `AES_cbc_encrypt(plaintext, out, len, key, iv=0, enc=1)`
- `FUN_00034a94(...)` then base64-encodes the ciphertext into ASCII.

Caller (`FUN_00031130`) pads the JSON plaintext up to a 16-byte boundary with zero bytes before calling this.

#### Base64 Decode + Decrypt (`FUN_00034e08`)

- `FUN_00034b74(...)` base64-decodes into a temporary buffer.
- `AES_set_decrypt_key(key, 0x80, ...)`
- `AES_cbc_encrypt(ciphertext, out, len, key, iv=0, enc=0)`

The decrypted plaintext is zero-padded JSON.

### Frame format (command payload)

`FUN_00031130` builds an outgoing packet as:

- 20-byte header (starts with the 7-byte string `EVC_...`)
- `payload_len` (length of base64 string + NUL)
- base64-encoded ciphertext (NUL-terminated)

We still need to map the full header fields precisely (the function writes:
`strncpy(..., <7-byte header>)`, sets `byte[8]=0x02`, zeros, then writes `param_3` at offset `0x0c` and `payload_len` at `0x10`).

### Implications

- The AES key is **static** and does **not** depend on the 32-byte token.
- Token still must be inserted into JSON before encrypting.
- If we can extract the raw command payload from PCAP (after PPCS), we should be able to decrypt it offline using:

```
AES-128-CBC, key=xs38nul7cqf7m1va, IV=0x00..00, zero-padded, then base64
```

Next step: locate the `EVC_...` frames inside the PPCS channel data in the PCAPs and apply the decrypt pipeline above.

## Offline Decrypt Results (PCAP) - 2026-02-09

Using `tools/extract_cmd_frames.py --scan-base64`, we can recover encrypted JSON from the PPCS payloads even without locating `EVC_` headers. This confirms the AES details and shows the actual login + gallery requests.

Example (from `pcap/trailcam_7-1-connect.pcap`):

### Login request (phone -> camera)

```
{"cmdId":0,"usrName":"admin","password":"admin","needVideo":0,"needAudio":0,"utcTime":1770582417,"supportHeartBeat":true}
```

### Login response (camera -> phone)

```
{"cmdId":0,"result":0,"token":78205281,"bat_percent":100,"errorMsg":"Success"}
```

**Important:** The token is an integer (e.g. `78205281`) in the decrypted JSON, not a 32-byte string. The 32-byte value we saw in other captures is likely a separate transport/session value, but the JSON command token used here is a 32-bit integer.

### Subsequent commands (phone -> camera)

- `{"cmdId":512,"token":78205281}` (repeated)
- `{"cmdId":768,"itemCntPerPage":45,"pageNo":0,"token":78205281}` (gallery list)
- `{"cmdId":525}` (repeated, likely heartbeat or status poll)

### Command responses (camera -> phone)

- `{"cmdRet":0,"result":0,"cmdId":772}` (thumbnail command ack)

### Notes

- We did **not** find `EVC_` headers directly, but scanning for base64-like substrings inside PPCS payloads reliably extracts encrypted JSON.
- This validates that the AES key/IV are correct and usable for offline decoding.
- The login response includes the command token, which the app injects into all subsequent command JSON.

Next step is to run the extractor across other `pcap/trailcam_*-1-connect.pcap` files and compare tokens and sequences, then turn this into a reusable offline decoder and eventually a live client.
