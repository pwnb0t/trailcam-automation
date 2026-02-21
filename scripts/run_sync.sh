#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="/home/pwnb0t/trailcam-automation"
CONFIG_PATH="${TRAILCAM_CONFIG:-$ROOT_DIR/config.yaml}"
LOCK_PATH="$ROOT_DIR/out/state/trailcam-sync.lock"
LOG_DIR="$ROOT_DIR/out/logs"

mkdir -p "$(dirname "$LOCK_PATH")" "$LOG_DIR"

cd "$ROOT_DIR"

exec /usr/bin/flock -n "$LOCK_PATH" \
  /usr/bin/env python3 trailcam_sync.py --config "$CONFIG_PATH"

