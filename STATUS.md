# TrailCam Automation Status

## Current State
- BLE wake + AP credential retrieval works (`ssid`/`pwd`).
- Wi-Fi join + UDP handshake + login works (`login_token_u32`).
- Media listing works (`cmdId=768`) for page and all-pages modes.
- Photo download works (`cmdId=1285`, `D0 subtype=0x03`).
- Video download works (`cmdId=769/770`, `D0 subtype=0x02`, ver=4 decrypt).
- Delete/format operations are reverse engineered (`cmdId=773`, `cmdId=518`).
- `client_runner.py` and `trailcam_sync.py` are both functional entrypoints.

## Recently Fixed
- Video corruption/jump/repeat issue root cause identified and fixed.
- Fix: ver=4 media decrypt now matches native behavior exactly:
  - decrypt `0x60` bytes per `0x1000` page only when remaining bytes `> 0x5f`
  - no partial tail-page decrypt
- Regression tests added for this behavior and sequence/ACK helpers.

## Next Steps
1. Redesign and re-implement scheduling/service orchestration (single-service model) for automatic retries after failures.
2. Add fixture-based tests for `_parse_artemis_v4_payload_header()` (offset-16 and offset-20 cases, invalid cases).
3. Add offline pcap regression fixtures for one photo and one video parsing path.
4. Add CLI/config precedence tests (defaults < config.yaml < CLI).
5. Harden sync-run observability:
   - progress lines during long list/download phases
   - clearer failure summaries for retries/timeouts.

## Operational Goal
- Daily or periodic sync from all configured trailcams.
- Download media to staging, organize onto NAS, then clear camera media after successful verification.
