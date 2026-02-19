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

Implemented:
- `tests/test_protocol_video_v4_decrypt.py`
- `tests/test_protocol_sequencing.py`

These cover the two highest-risk areas: sequencing and the v4 video decrypt fix.

## Current Highest Remaining Priorities

1. Offline pcap regression coverage
- Goal: catch regressions without requiring a live camera session.

Status:
- Added `tests/test_pcap_regression.py` with:
  - photo path regression (`trailcam_10-connect-thru-download-photo.pcap`, subtype `0x03`, ARTEMIS JPEG extraction sanity)
  - video metadata regression (`trailcam_8-3-view-and-download-video.pcap`, subtype `0x02`, expected ver=4 record profile `304` video / `157` audio)
- Note: these tests require `tshark`; they are skipped when `tshark` is unavailable.

2. CLI/config precedence tests
- Validate defaults < `config.yaml` < CLI for allowed override fields.

Status:
- Added `tests/test_flows_v4_header.py` for `_parse_artemis_v4_payload_header()` offset-16/offset-20 and invalid cases.
- Added `tests/test_config_precedence.py` for camera selection requirement, page item count clamp behavior, and config-vs-CLI precedence checks.
- Added `tests/test_protocol_video_normalize.py` for Annex-B/len16/raw normalization behavior.
- Expanded `tests/test_protocol_sequencing.py` with invalid-record skip/recovery coverage for strict ARTEMIS parsing.
