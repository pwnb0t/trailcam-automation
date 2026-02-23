#!/usr/bin/env bash
set -euo pipefail

# Default sync launcher used by scripts/run_sync.sh when no local override (scripts/sync.sh) exists.
#
# Why you might override with scripts/sync.sh:
# - Inject secrets from 1Password (or another secret manager).
# - Add machine-specific environment setup that should not be committed.
#
# To override, create scripts/sync.sh. run_sync.sh will prefer that file
# automatically and fall back to this example when it is missing.
#
# Example override (commented out) using 1Password `op run --env-file`:
#
# #!/usr/bin/env bash
# set -euo pipefail
# ROOT_DIR="/path/to/trailcam-automation"
# CONFIG_PATH="${TRAILCAM_CONFIG:-$ROOT_DIR/config.yaml}"
# OP_ENV_FILE="${TRAILCAM_OP_ENV_FILE:-$HOME/.config/your-app/op.env}"
# cd "$ROOT_DIR"
# if [ ! -f "$OP_ENV_FILE" ]; then
#   echo "missing 1Password env file: $OP_ENV_FILE" >&2
#   exit 2
# fi
# if ! command -v op >/dev/null 2>&1; then
#   echo "1Password CLI not found in PATH" >&2
#   exit 2
# fi
# if [ -z "${OP_SERVICE_ACCOUNT_TOKEN:-}" ]; then
#   token_line="$(grep -m1 '^OP_SERVICE_ACCOUNT_TOKEN=' "$OP_ENV_FILE" || true)"
#   if [ -n "$token_line" ]; then
#     export OP_SERVICE_ACCOUNT_TOKEN="${token_line#*=}"
#   fi
# fi
# op run --env-file "$OP_ENV_FILE" -- /usr/bin/env python3 trailcam_sync.py --config "$CONFIG_PATH"


# Default run:

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
CONFIG_PATH="${TRAILCAM_CONFIG:-$ROOT_DIR/config.yaml}"

if [ ! -d "$ROOT_DIR" ]; then
  echo "invalid repo root: $ROOT_DIR" >&2
  exit 2
fi
if [ ! -f "$ROOT_DIR/trailcam_sync.py" ]; then
  echo "trailcam_sync.py not found under: $ROOT_DIR" >&2
  exit 2
fi

cd "$ROOT_DIR"
/usr/bin/env python3 trailcam_sync.py --config "$CONFIG_PATH"
