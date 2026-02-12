# Packet Format

This documents the byte-level formats used by the camera protocol we currently implement.

## F1 Envelope (UDP payload)

All packets begin with:
```text
0x00:  0xF1
0x01:  opcode (u8)
0x02:  body_len (u16, big-endian)
0x04:  body (body_len bytes)
```

The client code that parses this is `protocol.unpack_f1()`.

## D0 Data Packet (opcode 0xD0)

`F1 opcode=0xD0` carries a chunk framed as:
```text
0x00:  0xD1
0x01:  subtype (u8)
0x02:  seq_hi (u8)
0x03:  seq_lo (u8)
0x04:  payload bytes...
```

Sequence interpretation:
- subtype `0x00`: treat `seq_lo` as an 8-bit sequence (wraps at 255).
- subtype `0x03`/`0x04`: treat `(seq_hi<<8)|seq_lo` as a 16-bit sequence for ordering.

## D1 ACK Packet (opcode 0xD1)

The client sends `F1 opcode=0xD1` with body shaped like:
```text
0x00:  0xD1
0x01:  subtype (u8)
0x02:  0x00
0x03:  count (u8)
0x04:  seq list (count * u16, big-endian)
```

We currently send:
- subtype `0x00`: `seq` values are the seq8 values we are ACKing.
- subtype `0x03`/`0x04`: `seq` values are the seq16 values we are ACKing.

## ARTEMIS Record (inside D0 payload streams)

The bulk streams and control streams embed records that look like:
```text
0x00:  "ARTEMIS\\0" (8 bytes)
0x08:  ver (u32, little-endian)
0x0C:  typ (u32, little-endian)
0x10:  len (u32, little-endian)
0x14:  payload bytes (len bytes)
```

Parsing note:
- When extracting from a continuous bulk stream, you must advance by `0x14 + len` for each record.
- A naive scan that advances by `+1` can produce overlapping false positives on high-volume streams.

