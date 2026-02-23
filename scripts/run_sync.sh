#!/usr/bin/env bash
set -uo pipefail

ROOT_DIR="/home/pwnb0t/trailcam-automation"
CONFIG_PATH="${TRAILCAM_CONFIG:-$ROOT_DIR/config.yaml}"
LOCK_PATH="$ROOT_DIR/out/state/trailcam-sync.lock"
LOG_DIR="$ROOT_DIR/out/logs"
OP_ENV_FILE="${TRAILCAM_OP_ENV_FILE:-$HOME/.config/openclaw/op.env}"

# Retry policy for one scheduled run.
MAX_ATTEMPTS="${TRAILCAM_SYNC_MAX_ATTEMPTS:-3}"
RETRY_DELAY_S="${TRAILCAM_SYNC_RETRY_DELAY_S:-900}"

mkdir -p "$(dirname "$LOCK_PATH")" "$LOG_DIR"
cd "$ROOT_DIR"

if ! [[ "$MAX_ATTEMPTS" =~ ^[0-9]+$ ]] || [ "$MAX_ATTEMPTS" -lt 1 ]; then
  echo "invalid TRAILCAM_SYNC_MAX_ATTEMPTS=$MAX_ATTEMPTS (must be >=1 integer)" >&2
  exit 2
fi
if ! [[ "$RETRY_DELAY_S" =~ ^[0-9]+$ ]]; then
  echo "invalid TRAILCAM_SYNC_RETRY_DELAY_S=$RETRY_DELAY_S (must be integer seconds)" >&2
  exit 2
fi

exec 9>"$LOCK_PATH"
if ! /usr/bin/flock -n 9; then
  echo "trailcam sync already running; skipping this scheduled invocation"
  exit 0
fi

attempt=1
while [ "$attempt" -le "$MAX_ATTEMPTS" ]; do
  ts="$(date -Is)"
  echo "[$ts] trailcam sync attempt $attempt/$MAX_ATTEMPTS"

  if [ -f "$OP_ENV_FILE" ] && command -v op >/dev/null 2>&1; then
    # Some environments require OP_SERVICE_ACCOUNT_TOKEN to be exported before `op run`.
    if [ -z "${OP_SERVICE_ACCOUNT_TOKEN:-}" ]; then
      token_line="$(grep -m1 '^OP_SERVICE_ACCOUNT_TOKEN=' "$OP_ENV_FILE" || true)"
      if [ -n "$token_line" ]; then
        export OP_SERVICE_ACCOUNT_TOKEN="${token_line#*=}"
      fi
    fi
    op run --env-file "$OP_ENV_FILE" -- /usr/bin/env python3 trailcam_sync.py --config "$CONFIG_PATH"
    rc=$?
  else
    /usr/bin/env python3 trailcam_sync.py --config "$CONFIG_PATH"
    rc=$?
  fi
  if [ "$rc" -eq 0 ]; then
    ts="$(date -Is)"
    echo "[$ts] trailcam sync succeeded on attempt $attempt/$MAX_ATTEMPTS"
    exit 0
  fi

  ts="$(date -Is)"
  echo "[$ts] trailcam sync failed on attempt $attempt/$MAX_ATTEMPTS (exit=$rc)"
  if [ "$attempt" -lt "$MAX_ATTEMPTS" ]; then
    echo "[$ts] retrying in ${RETRY_DELAY_S}s"
    sleep "$RETRY_DELAY_S"
  fi
  attempt=$((attempt + 1))
done

echo "trailcam sync failed after $MAX_ATTEMPTS attempts"
exit "$rc"
