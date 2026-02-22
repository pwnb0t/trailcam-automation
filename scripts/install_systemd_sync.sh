#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="/home/pwnb0t/trailcam-automation"
UNIT_DIR="/etc/systemd/system"

sudo install -m 0644 "$ROOT_DIR/systemd/trailcam-sync.service" "$UNIT_DIR/trailcam-sync.service"
sudo install -m 0644 "$ROOT_DIR/systemd/trailcam-sync.timer" "$UNIT_DIR/trailcam-sync.timer"
sudo systemctl daemon-reload
sudo systemctl enable --now trailcam-sync.timer
sudo systemctl restart trailcam-sync.timer
sudo systemctl status trailcam-sync.timer --no-pager -l
sudo systemctl list-timers trailcam-sync.timer --all --no-pager

