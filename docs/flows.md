# Flows

This describes the high-level operation sequences the client performs.

## Connect (BLE -> Wi-Fi -> UDP -> Login)
- BLE wake + creds: retrieve `ssid`/`pwd`.
- Scan and connect to AP via `nmcli`.
- UDP session bootstrap:
  - Send beacons, learn camera UDP port.
  - Respond to handshake opcodes (`0x41/0x42/0x43`) by echoing.
  - Respond to keepalive (`0xE0`) with `0xE1`.
- JSON login (`cmdId=0`) to obtain `login_token_u32`.

## List Media (Dev Info + Media List + Thumbs)
- Send dev info (`cmdId=512`).
- Send media list (`cmdId=768`) for `pageNo`.
- Optionally request thumbnails (`cmdId=772`).
- Parse `mediaFiles` entries and thumbnail records.

## Download Photo (cmdId=1285 + bulk transfer)
- Send `cmdId=1285` download request for `(dirNum, mediaNum, fileType=0)`.
- Maintain heartbeat (`cmdId=525`) during transfer.
- Receive bulk data on `D0 subtype=0x03`:
  - ACK with subtype-aware ACKs.
  - Reassemble using 16-bit sequence ordering.
- Parse strict ARTEMIS records inside the reassembled stream.
- For matching `dirNum/mediaNum`, extract JPEG from record payload:
  - Record payload includes a 72-byte header; the JPEG bytes begin at `payload[72:]`.
- Write `download.jpg` to the output directory.

