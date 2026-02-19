# Test Priority Plan

This plan lists the highest-value automated tests to add first, ordered by risk and impact.

## P0 (Write First)

1. `decrypt_v4_media_data_pages()` tail-page behavior
- Why: this is the root cause of prior video corruption.
- Must verify:
  - decrypt `0x60` prefix per `0x1000` page when remaining bytes `> 0x5f`
  - do not decrypt short tail pages (`<= 0x5f`)
  - boundary case `remaining == 0x60` is decrypted
- File: `src/protocol.py`

2. Sequence ACK body builders
- Why: sequence ACK correctness is core to transfer integrity.
- Must verify:
  - `make_ack_body_seq_list16()` sorts + deduplicates, emits correct binary format
  - `make_ack_body_seq_window16()` keeps last-seen unique sequence IDs in stable order
- File: `src/protocol.py`

3. ARTEMIS strict parser
- Why: non-strict scanning can create overlap false positives in bulk streams.
- Must verify:
  - `parse_artemis_records_strict()` advances record-by-record (`pos = end_of_record`)
  - embedded marker bytes inside payload do not create extra records
- File: `src/protocol.py`

## P1 (Next)

1. v4 video payload normalization
- Verify `normalize_v4_video_payload_to_annexb_with_mode()` behavior for:
  - already-annexb payloads
  - len16-be NAL payloads
  - raw fallback

2. v4 record header parsing assumptions
- Add fixture-based tests for `_parse_artemis_v4_payload_header()` for both observed `data_len` offsets (16 and 20).

3. Photo extraction robustness
- Validate JPEG extraction from representative ARTEMIS ver=5 payloads and stream-carve fallback.

## P2 (Integration / Regression)

1. Offline PCAP regression tests (no live camera)
- Small fixture captures to validate:
  - gallery listing parse
  - one known-good photo extraction
  - one known-good video reconstruction path metadata (record counts, sessions)

2. CLI command wiring
- Smoke tests for `client_runner.py` argument modes and config resolution.

3. Config precedence
- Verify defaults < config.yaml < CLI for allowed override fields.

## Suggested Immediate Implementation

Write these now:
- `tests/test_protocol_video_v4_decrypt.py`
- `tests/test_protocol_sequencing.py`

These directly cover the two highest-risk areas: sequencing and the v4 video decrypt fix.

