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
- Put output paths under `paths:`.
  - On `piiter`, `/mnt/trailcam/staging` is the intended `media_out_dir`.

## Notes

- The login token returned by the camera is runtime state and is not stored in config.
