#!/usr/bin/env bash
set -uo pipefail

ROOT_DIR="/home/pwnb0t/g/trailcam-automation"
CONFIG_PATH="${TRAILCAM_CONFIG:-$ROOT_DIR/config.yaml}"
LOCK_PATH="$ROOT_DIR/out/state/trailcam-sync.lock"
LOG_DIR="$ROOT_DIR/out/logs"
SYNC_OVERRIDE="$ROOT_DIR/scripts/sync.sh"
SYNC_FALLBACK="$ROOT_DIR/scripts/sync.example.sh"

# Retry policy for one scheduled run.
MAX_ATTEMPTS="${TRAILCAM_SYNC_MAX_ATTEMPTS:-3}"
RETRY_DELAY_S="${TRAILCAM_SYNC_RETRY_DELAY_S:-300}"

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

  if [ -f "$SYNC_OVERRIDE" ]; then
    SYNC_SCRIPT="$SYNC_OVERRIDE"
  else
    SYNC_SCRIPT="$SYNC_FALLBACK"
  fi
  if [ ! -f "$SYNC_SCRIPT" ]; then
    echo "sync launcher not found: $SYNC_SCRIPT" >&2
    exit 2
  fi

  TRAILCAM_CONFIG="$CONFIG_PATH" /usr/bin/env bash "$SYNC_SCRIPT"
  rc=$?
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
