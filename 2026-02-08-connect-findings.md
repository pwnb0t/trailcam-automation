# Connect Phase Findings (2026-02-08)

This note summarizes the **first connection phase** after the phone joins the camera AP, based on:

- `pcap/trailcam_2-1-connect.pcap`

It compares directly with the **refresh gallery** analysis to confirm which assumptions hold and what new details appear **before** the refresh step.

---

## 1. High-Level Sequence Observed

Right after the phone connects to the camera AP, the app does the following:

1. **Discovery beacons**
   - Phone sends `f1 30 00 00` to broadcast (`192.168.43.255:32108` and `255.255.255.255:32108`).

2. **Handshake / status messages from camera**
   - Camera sends:
     - `f1 41 00 14 ...`
     - `f1 42 00 14 ...` (new; not seen in refresh)
     - `f1 43 00 2c ...` (status frames)
   - Payloads contain ASCII `LBCS....CCCJJ....`.

3. **Keepalive traffic**
   - `f1 e0 00 00` and `f1 e1 00 00` are exchanged early.

4. **Large `D0` data stream** (gallery page)
   - Camera sends a **large chunked `D0` stream** using a **16-bit sequence**.
   - This is the **same gallery format** identified in the refresh analysis.

5. **Cloud probe (optional)**
   - Phone sends `f1 f9 ...` to public IPs on UDP port `32100`.
   - Not required for local operation.

---

## 2. Confirmed: Gallery Stream Appears During Connect

The large `D0` stream observed during refresh is **already present during connect**.

- Chunk header: `d1 04 <seq_hi> <seq_lo>`
- Seq16 range in connect capture: **0 .. 1617**
- Reassembly yields **45 ARTEMIS records**, identical structure to refresh

This means:

- The gallery response is **not exclusive to the refresh action**.
- A correct connect prelude can trigger the same gallery stream.

---

## 3. `ARTEMIS` Records (Same as Refresh)

Reassembled connect stream contains:

- `ARTEMIS\x00`
- `ver = 8`
- `type = 1..N`
- `length = payload length`

Each payload includes:

- 72-byte header
- JPEG thumbnail starting at offset `72` (`FF D8 FF`)

Header fields are consistent with refresh:

Offset | Size | Meaning (inferred)
---|---:|---
0x00 | 17 | Camera MAC (ASCII)
0x20 | 2 | Constant `0x0066`
0x22 | 2 | Record ID (monotonic decreasing)
0x24 | 2 | JPEG length

---

## 4. New Opcode Presence (`0x42`)

During connect, the camera sends:

```
f1 42 00 14 4c 42 43 53 ... 43 43 43 4a 4a ...
```

This opcode was **not observed in refresh captures**.
Its role is unknown but likely part of initial session setup.

---

## 5. Additional Phone `D0` Requests During Connect

The phone sends a **larger variety of `D0` request bodies** during connect.
Unique request `ARTEMIS` records identified:

- `ver=2, typ=65537..65541` (decoded payload length 16)
- `ver=2, typ=33..37` (decoded payload length 32 / 64 / 128 / 753)

These request types **do not match** the refresh-only set (which uses types 65544..65547 and 38..39).

This implies the phone performs **extra setup/auth steps** immediately after connecting,
*before* or *while* the gallery stream is triggered.

---

## 6. Seq16 Behavior Difference vs Refresh

Connect capture seq16 range:

- **0 .. 1617**

Refresh capture seq16 range:

- **1618 .. 3239**

This suggests the camera uses a **running seq16 counter** across transfers.
Our client must **not assume seq starts at 0**, only that it is strictly increasing within a transfer.

---

## 7. Open Questions from Connect Phase

1. Which specific `D0` request(s) trigger the large gallery stream?
2. What is the meaning of `0x42`?
3. Are the connect-phase `ver=2 typ=33..37` requests required for any later operations?
4. Do any of the connect `D0` request payloads depend on BLE wake output?

---

## 8. Practical Implication for Client Design

A minimal future client should:

- Reproduce **connect-phase request set** (not just refresh packets)
- Be prepared for the gallery stream **during connect**
- Parse `D0` large stream by seq16, regardless of starting value

