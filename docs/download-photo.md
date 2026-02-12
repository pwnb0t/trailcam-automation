# Download Photo

This documents the working photo download path implemented by the Python client.

## Control Plane

1. Login to obtain `login_token_u32` (`cmdId=0`).
2. Send download request:
```json
{
  "cmdId": 1285,
  "downloadReqs": [{"fileType": 0, "dirNum": 102, "mediaNum": 940}],
  "token": 12345678
}
```
3. Camera responds with JSON ACK:
```json
{"cmdRet":0,"result":0,"cmdId":1285}
```

## Data Plane (Bulk Transfer)

The actual photo bytes are delivered on `F1 opcode=0xD0` packets with:
- `D1 subtype=0x03` (bulk data)

Critical detail:
- The bulk sequence number is 16-bit: `seq16 = (body[2] << 8) | body[3]`.
- Reassembly must be done in `seq16` order.

## ARTEMIS-Wrapped Payloads

The reassembled `subtype=0x03` byte stream contains strict ARTEMIS records:
- `"ARTEMIS\0" + ver + typ + len + payload`

The payload includes a 72-byte header followed by JPEG bytes:
- `jpeg_bytes = payload[72:]`

The header includes fields that match the requested media:
- `dirNum` at `payload[0x20:0x22]` (little-endian)
- `mediaNum` at `payload[0x22:0x24]` (little-endian)
- `mediaId` at `payload[0x30:0x34]` (little-endian)

## Output

The client writes:
- `download.jpg`: the best extracted JPEG for the requested `(dirNum, mediaNum)`.

## Reference Implementation

Relevant code:
- `flows.send_photo_download_flow()`
- `protocol.parse_artemis_records_strict()`

