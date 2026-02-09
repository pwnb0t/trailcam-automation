2026-02-06

# TrailCam Go Wi-Fi Protocol Notes (Draft)

This document describes the UDP protocol observed between the TrailCam Go app (phone) and the trail camera over the camera’s Wi-Fi AP, based on packet captures from an offline phone connected only to the camera network.
It is written to support implementing a Python client (Raspberry Pi) that:

  1. wakes camera via BLE (out of scope here; separate module),

  2. connects to camera Wi-Fi,

  3. obtains gallery listing,

  4. downloads all media,

  5. deletes media after verification.


 


## 1. Network roles, addressing, and ports


### Roles


  - **Camera**: `192.168.43.1` (observed)

  - **Client (phone / Pi)**: `192.168.43.20` (phone example; Pi will vary)


### UDP ports (observed)


  - **Discovery/broadcast**: destination port **32108**

  - **Cloud probe** (optional, fails offline): destination port **32100**

  - **Primary session / bulk transfer**:

    - Camera source port: **40611** (observed; may vary per boot/session)

    - Client port: **3111** (common in idle capture) and/or an ephemeral port (e.g. **16734** during refresh capture)


Practical implication: your client should be prepared for:

  - camera choosing a dynamic high port for the “session”

  - client using a fixed port (3111) or ephemeral, depending on how you implement sockets

Recommendation for the Pi client: bind a known local UDP port (e.g. 3111) to mimic the app, unless testing indicates otherwise.

 


## 2. Message framing (confirmed)

All protocol messages share this outer framing:

Examples:

  - `f1 30 00 00` → opcode `0x30`, body length 0

  - `f1 43 00 2c` → opcode `0x43`, body length 0x002c (44)

  - `f1 d0 04 04` → opcode `0xD0`, body length 0x0404 (1028)

This is not TLS/DTLS; payloads are visible.

 


## 3. Observed opcodes and likely meanings

These meanings are inferred from behavior across captures.

| Opcode | Direction                      | Typical size                     | Meaning (inferred)                                  |
|-------:|--------------------------------|----------------------------------|-----------------------------------------------------|
|   0x30 | client → broadcast             | 4 bytes payload total            | Discovery / announce / keepalive beacon (stateless) |
|   0x41 | client ↔ camera                | 24 bytes payload total           | Session init / handshake / ack-like exchange        |
|   0x43 | camera → client                | 48 bytes payload total           | Camera heartbeat / status advertisement             |
|   0xD0 | client ↔ camera                | variable (small req, large resp) | Data transfer (request + chunked response)          |
|   0xD1 | client → camera                | small                            | ACK / selective-ack for `D0` chunk transfer         |
|   0xE0 | client → (broadcast or camera) | 4 bytes payload total            | Keepalive ping (seen as `f1 e0 00 00`)              |
|   0xE1 | camera → client                | 4 bytes payload total            | Keepalive pong/response (seen as `f1 e1 00 00`)     |

Notes:

  - `0x30` is distinct from session traffic. In captures, it is broadcast to `192.168.43.255:32108` and `255.255.255.255:32108`.

  - `0x43` repeats during “idle” at a steady cadence.

  - Gallery refresh uses `0xD0` and `0xD1`.


 


## 4. Discovery / keepalive (UDP/32108)


### `F1 30 00 00` beacon

Observed as 4-byte UDP payload (only header; no body) sent by client to broadcast:

  - `192.168.43.255:32108`

  - `255.255.255.255:32108`

Purpose (inferred): discovery / presence / keepalive on the local AP.
Client implementation note:

  - This may not be strictly required once a session is established, but matching the app’s behavior is low effort.


 


## 5. Idle session behavior

When the app is open and connected but not actively refreshing/downloading/streaming:

  - Camera sends repeated **status frames**:

    - `f1 43 00 2c` (48 bytes payload total)


  - Client and camera exchange minimal **keepalives**:

    - `f1 e0 00 00` and `f1 e1 00 00`


This indicates the camera maintains state and may time out if not kept alive.
Client implementation note:

  - Your Python client should run an “idle maintenance loop” while connected:

    - respond/participate in keepalives

    - optionally log/parse `0x43` heartbeat contents later



 


## 6. Gallery refresh / file listing transaction (confirmed)

Gallery refresh is a request/response transaction over UDP that implements reliability at the application layer.

### 6.1 Client request (`0xD0`, small)

Client sends one or more `0xD0` packets with small bodies, observed:

  - `f1 d0 00 31 ...` (body length 0x0031)

  - `f1 d0 00 71 ...` (body length 0x0071)

These contained:

  - ASCII string `ARTEMIS`

  - Base64 blobs that decoded to binary (observed 16 bytes and 64 bytes)

Interpretation (inferred):

  - Session identifier / device family string

  - Auth/token or capability blob

Open questions:

  - Exact field layout and whether these are constant per device, per session, or derived from BLE wake step.


### 6.2 Camera response (`0xD0`, chunked, large)

Camera responds with many large packets, typically:

  - Outer header: `f1 d0 04 04` (1028-byte body)

  - UDP payload: 1032 bytes total (4 header + 1028 body)

At the start of the `0xD0` body, camera includes an inner chunk header:

Where `<seq>` increments (e.g. `0x10, 0x11, 0x12, ...`).
After this inner chunk header, the remainder of the chunk body appears to be ASCII base64 text.
Interpretation (confirmed/inferred):

  - `0xD0` is used for bulk transfer

  - `d1 00 00 <seq>` inside the body marks the chunk sequence number

  - The actual payload is a base64-encoded larger object (likely JSON or gzip+JSON)


### 6.3 Client ACK (`0xD1`, selective ACK)

Client periodically sends `0xD1` messages that list which chunk IDs were received.
Example pattern (from dissection):

  - `f1 d1 00 10 ...` plus a list of chunk IDs in the body

Interpretation:

  - selective acknowledgment / windowing

  - camera likely retransmits missing chunks (not yet validated by inducing loss)


### 6.4 End of transfer

Camera ends with a final shorter `0xD0` packet (body length smaller than 0x0404), e.g. `f1 d0 02 45 ...` in earlier notes.
Interpretation:

  - final “tail chunk” carrying the end of the base64 text

  - once decoded/assembled, yields the full gallery listing


 


## 7. Large UDP packets (1032 payload / UDP length 1040)

The repeated packets with:

  - UDP length ≈ 1040

  - frame length ≈ 1074

are consistent with the `0xD0` chunked transfer described above (gallery refresh) and potentially other bulk operations.

Do not assume they are video; in the refresh case they are base64 text chunks.

 


## 8. Cloud probe packets (optional)

During connection, the client may emit one-off UDP packets to public IPs on port **32100**. These fail when offline and are not required for local Wi-Fi operations.
Client implementation note:

  - Ignore; do not implement unless later required for some auth/token generation (currently no evidence it is required for local downloads).


 


## 9. State machine (client perspective)


### State A — BLE wake (separate module)


  - Use BLE to wake/enable Wi-Fi (details from prior script)


### State B — Connect to camera AP


  - Associate to SSID and obtain DHCP lease

  - Expect camera at `192.168.43.1`


### State C — Establish / maintain session


  - Send broadcast `0x30` beacons (optional)

  - Observe camera `0x43` heartbeats

  - Participate in `0xE0/0xE1` keepalive loop


### State D — Request gallery listing


  - Send one or more `0xD0` small request packets (format TBD)

  - Receive `0xD0` chunk stream with inner seq header

  - Send `0xD1` ACKs listing received seq IDs

  - Reassemble payload → base64-decode → parse (likely JSON)


### State E — Download file(s)

Not yet documented. Expected to reuse:

  - `0xD0` for requests and chunked responses

  - `0xD1` for ACKs

Likely different command bodies and possibly different content (binary vs base64).


### State F — Delete file(s)

Not yet documented. Expected to be a small command/response opcode (possibly within `0xD0` or a new opcode).

 


## 10. Implementation notes for the Python client


### Socket strategy


  - Use a UDP socket bound to a stable port (suggest 3111) and interface on the Pi’s Wi-Fi

  - Log all inbound/outbound datagrams with timestamps and hex dumps


### Reliable transfer handler (needed)

Implement a generic handler for “chunked `0xD0` transfer with `0xD1` ACK”:

  - parse outer header

  - for `0xD0` large responses:

    - read inner seq (`body[3]` if it is `d1 00 00 seq`)

    - buffer chunk payload by seq


  - periodically send `0xD1` containing received seq IDs

  - detect end-of-transfer by tail packet size / terminator marker (TBD)

  - assemble in seq order


### Payload decoding

For gallery listing:

  - concatenate chunk payloads (after removing inner chunk header)

  - base64-decode

  - then attempt:

    - UTF-8 JSON parse

    - gzip header check (`1f 8b`)

    - zlib header check



 


## 11. What remains unknown (to be captured next)

To complete automation, we still need captures for:

  1. **Download a single photo** (full file transfer)

  2. **Download a single video** (full file transfer; may be larger / streaming-like)

  3. **Delete a file** (post-download command)

  4. Whether any fields in the `0xD0` request are derived from BLE wake step (token/session key)

Recommended capture method:

  - one action per capture

  - keep PCAP + dissection CSV

  - note the exact UI action and which file was chosen


 


## 12. Suggested repo layout for the Pi script



 

If you paste the BLE wake script when you find it, the next step is to draft the Python skeleton with:

  - BLE wake hook (call-out)

  - Wi-Fi connection instructions (Pi-specific)

  - UDP framing + logging

  - a `refresh_gallery()` implementation built around the `D0/D1` transfer engine.



