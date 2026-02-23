#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="/home/pwnb0t/trailcam-automation"
CONFIG_PATH="${TRAILCAM_CONFIG:-$ROOT_DIR/config.yaml}"

cd "$ROOT_DIR"
/usr/bin/env python3 trailcam_sync.py --config "$CONFIG_PATH"
