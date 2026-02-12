# Opcodes

This protocol is carried over UDP between the client (phone/Pi) and camera AP (`192.168.43.1` in captures).

All packets begin with an `F1` header:
- `0xF1` magic
- `opcode` (1 byte)
- `body_len` (2 bytes, big-endian)
- `body` (`body_len` bytes)

See `docs/packet-format.md` for byte layouts.

## Handshake/Keepalive

### `opcode=0x41` (cam->client, client->cam)
- Observed during UDP handshake.
- Client echoes back the same opcode and body (we do a double-send in the client because the app appears to do so).

### `opcode=0x42` (cam->client, client->cam)
- Observed during UDP handshake.
- Client echoes back the same opcode and body (double-send).

### `opcode=0x43` (cam->client, client->cam)
- Observed during UDP handshake.
- Client echoes back the same opcode and body.

### `opcode=0xE0` (cam->client)
- Keepalive trigger.

### `opcode=0xE1` (client->cam)
- Keepalive response to `0xE0`.
- Client sends `F1 E1` with empty body.

## Data and ACK

### `opcode=0xD0` (cam->client)
Carries a `D1`-framed chunk inside its body:
- `body[0] == 0xD1`
- `body[1] == subtype`

Subtypes we actively handle:
- `subtype=0x00`: control plane (ARTEMIS-wrapped encrypted JSON, small chunks)
- `subtype=0x03`: download bulk stream (ARTEMIS-wrapped binary payloads, 16-bit sequence)
- `subtype=0x04`: secondary bulk stream (thumbnails and other large payloads depending on flow)

### `opcode=0xD1` (client->cam)
ACK frame for `opcode=0xD0` chunks.

Important details:
- For `subtype=0x00`, we ACK using the 8-bit sequence in `body[3]`.
- For `subtype=0x03` and `subtype=0x04`, the sequence is effectively 16-bit (`body[2:4]`).
  - The low byte is `body[3]`.
  - The high byte is `body[2]`.
  - Reassembly must be done by seq16 ordering, not seq8.

The current client uses a small sliding-window ACK list (similar shape to the app) for `0x03`/`0x04`.

