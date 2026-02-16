#!/usr/bin/env python3
import argparse
import asyncio
import json
import sys
from dataclasses import dataclass, asdict
from typing import Dict, Optional

from bleak import BleakScanner


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
    if "trailcam" in n:
        return True
    # Current camera advertises these custom services/chars.
    # Keeping this as a fallback for empty/odd local names.
    for u in service_uuids:
        if u.lower().startswith("0000000"):
            return True
    return False


async def run_scan(duration_s: float, rounds: int, show_all: bool) -> Dict[str, ScanHit]:
    found: Dict[str, ScanHit] = {}
    for i in range(1, rounds + 1):
        devices = await BleakScanner.discover(timeout=duration_s, return_adv=True)
        for _key, (device, adv) in devices.items():
            address = str(device.address or "").strip()
            if not address:
                continue
            name = str((adv.local_name or device.name or "")).strip()
            service_uuids = list(adv.service_uuids or [])
            if not show_all and not _looks_like_trailcam(name, service_uuids):
                continue

            manuf = adv.manufacturer_data or {}
            manuf_keys = [f"0x{k:04x}" for k in sorted(manuf.keys())]
            rssi = int(device.rssi if device.rssi is not None else -999)

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
        print(f"round {i}/{rounds}: {len(found)} matching device(s)")
    return found


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


async def main() -> int:
    p = argparse.ArgumentParser(
        description="Scan BLE and print TrailCam-like devices (MAC addresses).",
    )
    p.add_argument("--duration", type=float, default=6.0, help="seconds per scan round (default: %(default)s)")
    p.add_argument("--rounds", type=int, default=2, help="number of rounds (default: %(default)s)")
    p.add_argument("--all", action="store_true", help="show all BLE devices, not just TrailCam-like ones")
    p.add_argument("--json", action="store_true", help="print machine-readable JSON instead of table")
    args = p.parse_args()

    if args.duration <= 0:
        print("--duration must be > 0", file=sys.stderr)
        return 2
    if args.rounds <= 0:
        print("--rounds must be > 0", file=sys.stderr)
        return 2

    found = await run_scan(duration_s=float(args.duration), rounds=int(args.rounds), show_all=bool(args.all))
    if args.json:
        print(json.dumps([asdict(x) for x in sorted(found.values(), key=lambda v: v.address)], indent=2))
    else:
        _print_table(found)
    return 0 if found else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

