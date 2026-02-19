# Config

The project uses a YAML config file to define cameras and default runtime settings.

## Example

See `config.example.yaml` (you can name your real file `config.yaml` or `config.yml`).

## Intended Usage

- Define one or more cameras under `cameras:` with:
  - `ble_address`: BLE MAC address used for wake/credentials
  - `ssid`: expected camera AP SSID (used as a verification step)
- Select which camera to talk to via `--camera <alias>` (no `--ssid` / `--ble-address` CLI overrides).
- Put default knobs under `client:` (wifi interface, UDP bind port, page sizes, timeouts).
  - Note: `client.page_no` is intentionally CLI-only; do not put it in config.yaml.
  - `photo_download_retries` controls per-item retry count used by sync for flaky photo transfers.
  - `strict_video` enables stricter video transport validation.
    - Fails video download on: missing sequence numbers, changed duplicate sequence payloads, out-of-session records, backward PTS, or `startPbRet.totalFrame` mismatch.
- Put output paths under `paths:`.
  - `staging_dir`: raw downloaded files (`/mnt/trailcam/staging` on `piiter`).
  - `final_media_dir`: final organized media root (for sync flow, e.g. `/mnt/trailcam/media`).
  - `tmp_dir`: temporary working files (`out/tmp` by default).
- Optional failure email alerts under `alerts.email`:
  - Set `enabled: true`
  - Configure SMTP fields (`smtp_host`, `smtp_port`, `smtp_user`, `from_email`, `to_emails`)
  - For Gmail app password, use env var reference:
    - `smtp_app_password: "${TRAILCAM_GMAIL_APP_PASSWORD}"`
  - Current behavior: sends on sync camera failures when `notify_on` includes `failure`.

## Notes

- The login token returned by the camera is runtime state and is not stored in config.
