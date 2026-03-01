# TrailCam Automation Status

## Current Snapshot
- Daily systemd timer runs around **11:03 local** on both hosts: `petepad` and `piiter`.
- Sync pipeline is generally healthy and media lands on NAS in organized structure.
- Main-session noon check is active as a temporary operational safety net.

## Known Operational Behavior
- Sync can fail intermittently on individual photo/video downloads.
- Most intermittent failures clear on retry (same run or subsequent run).
- Current failure alerting is too noisy for normal transient failures.

## Intent
- Keep this file high-signal and operational only.
- Track implementation work in `TODO.md`.
