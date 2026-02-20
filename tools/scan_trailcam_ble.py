#!/usr/bin/env python3
import argparse
import asyncio
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, Optional

from bleak import BleakScanner

# Allow running as `python3 tools/scan_trailcam_ble.py` by adding repo root.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.connection.ble import ble_wake_and_get_creds


@dataclass
class ScanHit:
    address: str
    name: str
    rssi: int
    service_uuids: list[str]
    manufacturer_data_keys: list[str]
    seen_count: int = 1


def _looks_like_trailcam(name: str, service_uuids: list[str]) -> bool:
    n = (name or "").strip().lower()
    if "trailcam" in n or n.startswith("tc100_"):
        return True
    # Current camera advertises these custom services/chars.
    # Keeping this as a fallback for empty/odd local names.
    for u in service_uuids:
        if u.lower().startswith("0000000"):
            return True
    return False


async def run_scan(
    duration_s: float,
    rounds: int,
    show_all: bool,
    adapter: Optional[str] = None,
) -> tuple[Dict[str, ScanHit], Dict[str, ScanHit]]:
    found: Dict[str, ScanHit] = {}
    all_seen: Dict[str, ScanHit] = {}
    for i in range(1, rounds + 1):
        discover_kwargs = {"timeout": duration_s, "return_adv": True}
        if adapter:
            discover_kwargs["adapter"] = adapter
        devices = await BleakScanner.discover(**discover_kwargs)
        for _key, (device, adv) in devices.items():
            address = str(device.address or "").strip()
            if not address:
                continue
            name = str((adv.local_name or device.name or "")).strip()
            service_uuids = list(adv.service_uuids or [])
            manuf = adv.manufacturer_data or {}
            manuf_keys = [f"0x{k:04x}" for k in sorted(manuf.keys())]
            rssi_src = adv.rssi if getattr(adv, "rssi", None) is not None else device.rssi
            rssi = int(rssi_src if rssi_src is not None else -999)

            prev_all: Optional[ScanHit] = all_seen.get(address)
            if prev_all is None:
                all_seen[address] = ScanHit(
                    address=address,
                    name=name,
                    rssi=rssi,
                    service_uuids=service_uuids,
                    manufacturer_data_keys=manuf_keys,
                )
            else:
                prev_all.seen_count += 1
                if rssi > prev_all.rssi:
                    prev_all.rssi = rssi
                if name:
                    prev_all.name = name
                prev_all.service_uuids = sorted(set(prev_all.service_uuids).union(service_uuids))
                prev_all.manufacturer_data_keys = sorted(set(prev_all.manufacturer_data_keys).union(manuf_keys))

            if not show_all and not _looks_like_trailcam(name, service_uuids):
                continue

            prev: Optional[ScanHit] = found.get(address)
            if prev is None:
                found[address] = ScanHit(
                    address=address,
                    name=name,
                    rssi=rssi,
                    service_uuids=service_uuids,
                    manufacturer_data_keys=manuf_keys,
                )
            else:
                prev.seen_count += 1
                # Keep strongest RSSI seen.
                if rssi > prev.rssi:
                    prev.rssi = rssi
                # Keep latest non-empty name.
                if name:
                    prev.name = name
                # Merge seen UUIDs/keys.
                prev.service_uuids = sorted(set(prev.service_uuids).union(service_uuids))
                prev.manufacturer_data_keys = sorted(set(prev.manufacturer_data_keys).union(manuf_keys))
        print(f"round {i}/{rounds}: {len(found)} matching device(s), {len(all_seen)} total device(s)")
    return found, all_seen


def _print_table(found: Dict[str, ScanHit]) -> None:
    if not found:
        print("No matching BLE devices found.")
        return
    rows = sorted(found.values(), key=lambda x: (-x.rssi, x.address))
    print("\nDiscovered cameras:")
    print("address              rssi  seen  name")
    print("-------------------  ----  ----  ----------------")
    for h in rows:
        print(f"{h.address:19}  {h.rssi:4d}  {h.seen_count:4d}  {h.name or '-'}")


async def _fetch_ssids_for_hits(found: Dict[str, ScanHit]) -> dict[str, str]:
    ssids: dict[str, str] = {}
    rows = sorted(found.values(), key=lambda x: (-x.rssi, x.address))
    for h in rows:
        try:
            creds = await ble_wake_and_get_creds(h.address)
            ssid = str(creds.get("ssid") or "").strip()
            if ssid:
                ssids[h.address] = ssid
                print(f"ssid fetched: {h.address} -> {ssid}")
            else:
                print(f"ssid fetch failed (empty): {h.address}")
        except Exception as e:
            print(f"ssid fetch failed: {h.address} ({e})")
    return ssids


def _print_config_snippet(found: Dict[str, ScanHit], ssids: Optional[dict[str, str]] = None) -> None:
    rows = sorted(found.values(), key=lambda x: (-x.rssi, x.address))
    if not rows:
        print("\ncameras:\n  # no matching cameras found")
        return
    print("\ncameras:")
    for i, h in enumerate(rows, start=1):
        alias = f"camera{i}"
        ssid = ""
        if ssids:
            ssid = ssids.get(h.address, "")
        print(f"  {alias}:")
        print(f"    ble_address: \"{h.address}\"")
        print(f"    ssid: \"{ssid}\"")


async def main() -> int:
    p = argparse.ArgumentParser(
        description="Scan BLE and print TrailCam-like devices (MAC addresses).",
    )
    p.add_argument("--duration", type=float, default=6.0, help="seconds per scan round (default: %(default)s)")
    p.add_argument("--rounds", type=int, default=2, help="number of rounds (default: %(default)s)")
    p.add_argument("--all", action="store_true", help="show all BLE devices, not just TrailCam-like ones")
    p.add_argument(
        "--adapter",
        type=str,
        default=None,
        help="Bluetooth adapter to use on Linux BlueZ, e.g. hci0 or hci1",
    )
    p.add_argument("--json", action="store_true", help="print machine-readable JSON instead of table")
    p.add_argument("--config-snippet", action="store_true", help="print cameras: YAML snippet")
    p.add_argument(
        "--fetch-ssid",
        action="store_true",
        help="for each matched camera, BLE wake and fetch real SSID for config snippet",
    )
    args = p.parse_args()

    if args.duration <= 0:
        print("--duration must be > 0", file=sys.stderr)
        return 2
    if args.rounds <= 0:
        print("--rounds must be > 0", file=sys.stderr)
        return 2
    if args.adapter and not re.fullmatch(r"hci\d+", args.adapter.strip()):
        print("--adapter must look like hciX (example: hci0)", file=sys.stderr)
        return 2

    found, all_seen = await run_scan(
        duration_s=float(args.duration),
        rounds=int(args.rounds),
        show_all=bool(args.all),
        adapter=(args.adapter.strip() if args.adapter else None),
    )
    if args.json:
        print(json.dumps([asdict(x) for x in sorted(found.values(), key=lambda v: v.address)], indent=2))
    else:
        _print_table(found)
        if not found and not args.all:
            print("\nNo TrailCam-like matches were found.")
            if all_seen:
                sample = sorted(all_seen.values(), key=lambda x: (-x.rssi, x.address))[:10]
                print(f"BLE scanner did see {len(all_seen)} device(s). Top {len(sample)} by RSSI:")
                print("address              rssi  name")
                print("-------------------  ----  ----------------")
                for h in sample:
                    print(f"{h.address:19}  {h.rssi:4d}  {h.name or '-'}")
            print("\nTry:")
            print("  python3 tools/scan_trailcam_ble.py --all --duration 10 --rounds 3")
            print("  python3 tools/scan_trailcam_ble.py --duration 12 --rounds 4")

    ssids: Optional[dict[str, str]] = None
    if args.fetch_ssid and found:
        ssids = await _fetch_ssids_for_hits(found)
    if args.config_snippet:
        _print_config_snippet(found, ssids=ssids)
    return 0 if found else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
