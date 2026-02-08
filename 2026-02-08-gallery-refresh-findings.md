# Gallery Refresh Findings (2026-02-08)

This note captures **new protocol findings** from analyzing the refresh PCAPs with `tshark` on the Pi. It focuses on the *gallery listing / first page* behavior so we can later implement a clean, minimal client from scratch.

These findings are based on:
- `pcap/trailcam_2-2-refresh.pcap`
- `pcap/trailcam_3-2-refresh.pcap`

The main correction is that the **real gallery content is not delivered via the small `D0` stream**. The gallery page arrives as a **large `D0` stream with a different chunk header** and must be reassembled by a **16-bit sequence number**.

---

## 1. Key Correction: Which `D0` Stream Contains the Gallery

Two distinct `D0` response patterns are present in refresh captures:

1. **Small `D0` stream** (chunk header `d1 00 00 <seq8>`)
   - Only ~8 unique seq values (0x10..0x17), repeated.
   - Payload is ASCII-ish but **does not decode cleanly into gallery data**.
   - Contains `ARTEMIS` records with `ver=3 typ=38/39`, but payloads look opaque / binary.
   - Likely a *control/handshake response*.

2. **Large `D0` stream** (chunk header `d1 04 <seq_hi> <seq_lo>`)
   - Thousands of chunks; `seq16` runs contiguously (example: 1618..3239).
   - Reassembled payload contains multiple **`ARTEMIS` records** that each embed a JPEG thumbnail.
   - This is the **actual gallery response** (first-page content).

So for gallery listing, we must parse the **large `D0` stream** and ignore the small one.

---

## 2. Large `D0` Stream Reassembly

**Packet structure (camera → client):**
- Outer framing: `f1 d0 <len>`
- Body begins with: `d1 04 <seq_hi> <seq_lo>`
- Remainder of body is chunk payload.

**Reassembly rule:**
- Extract `seq16 = (body[2] << 8) | body[3]`
- Store `payload = body[4:]`
- Reassemble by **ascending `seq16`**

In the refresh capture, this yields a reassembled blob of ~1.6 MB.

---

## 3. `ARTEMIS` Records in the Large Stream

The reassembled blob contains repeated records:

```
ARTEMIS\x00
uint32_le  version   (observed: 8)
uint32_le  type      (observed: 1..N)
uint32_le  length    (payload length)
payload    (length bytes)
```

Example record sequence:
- `(ver=8, type=1, length=17347)`
- `(ver=8, type=2, length=15449)`
- `(ver=8, type=3, length=40414)`
- ...

In the analyzed refresh capture, **45 records** were found.

---

## 4. Record Payload Layout (Gallery Thumbnails)

Each record payload starts with a **72-byte header**, then a JPEG image:

```
payload[0:72]   = header
payload[72:]    = JPEG thumbnail (starts with FF D8 FF)
```

### Header fields (observed)

Offset | Size | Meaning (inferred)
---|---:|---
0x00 | 17 | ASCII MAC string (e.g. `C6:1E:0D:E0:0C:FB`)
0x11..0x1F | 15 | Zero padding
0x20 | 2 | Constant `0x0066` (decimal 102)
0x22 | 2 | **Record ID** (monotonic *decreasing* across records)
0x24 | 2 | **JPEG length** (exact match to `len(payload) - 72`)
0x26 | 2 | Unknown / constant `0x0000`
0x28 | 4 | Unknown (varies per record)
0x2C..0x47 | 28 | Zero padding

Notes:
- `record_id` decreases by 1 across the record list (e.g. 436..392).
- `jpeg_len` matches actual JPEG length for *every* record in the capture.
- The 4-byte field at offset `0x28` varies and is **not** a clean Unix timestamp.

---

## 5. Implications for Gallery Listing

To print a usable gallery list (first page):

1. Reassemble the large stream by `seq16`.
2. Iterate `ARTEMIS` records.
3. For each record, parse:
   - `record_id`
   - `jpeg_len`
   - optionally write thumbnail JPEG (payload[72:]).

Even without filenames, this yields a stable **record index** and a **thumbnail preview**.

---

## 6. Remaining Unknowns / Next Details to Learn

Before full automation, we still need:

1. **Mapping from record ID → actual filename / file handle**
   - Likely in a different `D0` response or a separate command.

2. **Download request body format**
   - The download PCAP shows different `D0` requests (`len=0x31`, `len=0x99`), but we need to correlate those with a specific record ID.

3. **Delete request body format**

4. **Whether any of the request fields are derived from BLE wake or session state**

---

## 7. Suggested Next Step (Once We Start Fresh)

Implement a new minimal script that:
- binds to the selected local UDP port
- sends the refresh requests
- collects **only** the large `D0` stream (`d1 04 seq16`)
- prints `record_id, jpeg_len`
- optionally writes thumbnails to `out/`

This isolates the core gallery listing logic and avoids older experimental scripts.
