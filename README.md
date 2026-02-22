# trailcam-automation

Reverse engineering a bluetooth Trail Cam.

Protocol documentation lives in `docs/overview.md` (historical notes are in `docs/historical/`).

I'm using this camera:
https://www.amazon.com/MAXDONE-Bluetooth-5200mAh-Rechargeable-Activated/dp/B0DHRYCZKF
"MAXDONE Solar Trail Camera WiFi Bluetooth - 48MP 30fps Game Camera with 5200mAh Rechargeable Battery, 0.1s Trigger Speed Motion Activated Trail Cam IP66 with 32GB TF Card for Wildlife Monitoring"

Used some of the info of the previous dude's article around hacking his BLE trail cam:
https://geekitguide.com/wifi-ble-trailcam-investigation-part-1/

This got me part of the way there, but the way the info on my cam worked was not quite the same.
I needed to use a rooted android device to get the BT wakeup command. I also had to use tcpdump on a rooted android device to capture the wifi UDP traffic. I was not able to sniff the traffic.


Anyway, not done yet, unless I am and I didn't update this file. But that totally wouldn't happen.
I've probably left some passwords and stuff in here so uhh, don't come to my house and hack my camera lol. (though if you actually understand all that's in this repo then you'll know that pw doesn't matter)

-----

# Docs
- `docs/overview.md`
- `docs/flows.md`
- `docs/opcodes.md`
- `docs/packet-format.md`
- `docs/json-commands.md`
- `docs/download-photo.md`
- `docs/download-video.md`
- `pcap/details.md`

-----

# Requirements

Python packages:
- `bleak`
- `cryptography`
- `PyYAML`
- `pytest` (for tests)

Install example:
```bash
python3 -m pip install bleak cryptography PyYAML pytest
```

System tools used by parts of this repo:
- `nmcli` (Wi-Fi connect flow)
- `tshark` (pcap analysis tools)
- `ffmpeg` (video extraction/mux and comparisons)

# Config

1. Copy `config.example.yaml` to `config.yaml`.
2. Set camera aliases/values in `config.yaml` (`cameras`, `client`, `paths`, etc).

# Run Tests

`unittest` suite:
```bash
python3 -m unittest discover -s tests -p "test_*.py" -v
```

`pytest`:
```bash
pytest -q
```

# Run `client_runner.py` (examples)

Login/connect test only:
```bash
python3 client_runner.py --camera back --login-only
```

Download first page:
```bash
python3 client_runner.py --camera back --download-page --page-no 0 --page-item-cnt 12
```

Download single media item:
```bash
python3 client_runner.py --camera back --download-single 105 --dir-num 100
# Optional: strict transport checks for video downloads.
python3 client_runner.py --camera back --download-single 105 --dir-num 100 --strict-video
```

List media:
```bash
python3 client_runner.py --camera back --list-media-page --page-no 0 --page-item-cnt 48
python3 client_runner.py --camera back --list-media-all --list-max-pages 200
```

Delete all media on camera (high impact):
```bash
python3 client_runner.py --camera back --delete-media-all
```

# Run `trailcam_sync.py` (examples)

Default sync run:
```bash
python3 trailcam_sync.py
```

Explicit config path:
```bash
python3 trailcam_sync.py --config /path/to/config.yaml
```

Stage-only run (download+verify to staging, no clear/organize):
```bash
python3 trailcam_sync.py --stage-only
```

Show current sync state and next action:
```bash
python3 trailcam_sync.py --status
```

# Automated Daily Sync (single service/timer)

Install the unit files from this repo:
```bash
./scripts/install_systemd_sync.sh
```

Scheduling model:
- One timer: `trailcam-sync.timer` at `11:00` local time (`RandomizedDelaySec=5m`).
- One service: `trailcam-sync.service`.
- Retries happen inside `scripts/run_sync.sh` (same invocation, no second timer/service).

Default in-process retry policy (set in service environment):
- `TRAILCAM_SYNC_MAX_ATTEMPTS=3`
- `TRAILCAM_SYNC_RETRY_DELAY_S=900` (15 minutes)

Check status:
```bash
systemctl status trailcam-sync.timer
systemctl status trailcam-sync.service
systemctl list-timers trailcam-sync.timer --all
```
