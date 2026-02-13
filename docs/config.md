# Config

The project uses a YAML config file to define cameras and default runtime settings.

## Example

See `config.example.yaml`.

## Intended Usage

- Define one or more cameras under `cameras:` with:
  - `ble_address`: BLE MAC address used for wake/credentials
  - `ssid`: expected camera AP SSID (used as a verification step)
- Put default knobs under `defaults:` (wifi interface, UDP bind port, page sizes, timeouts).
- Put output paths under `paths:`.

## Notes

- The login token returned by the camera is runtime state and is not stored in config.

