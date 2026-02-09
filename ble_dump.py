#!/usr/bin/env python3
import argparse
import asyncio
import binascii
import json
import time
from pathlib import Path

from bleak import BleakClient

DEFAULT_ADDRESS = "C6:1E:0D:E0:0C:FB"
CHAR_WRITE = "00000002-0000-1000-8000-00805f9b34fb"
CHAR_NOTIFY = "00000003-0000-1000-8000-00805f9b34fb"
WAKE_PAYLOAD = bytes.fromhex(
    "13 57 01 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00"
)


def hexdump(b: bytes) -> str:
    return binascii.hexlify(b).decode("ascii")


def ascii_clean(b: bytes) -> str:
    return "".join(chr(c) if 32 <= c < 127 else "." for c in b)


async def main():
    parser = argparse.ArgumentParser(description="Dump BLE notify data from TrailCam")
    parser.add_argument("--address", default=DEFAULT_ADDRESS)
    parser.add_argument("--outfile", default="out/ble_notify_dump.txt")
    parser.add_argument("--timeout", type=float, default=12.0, help="seconds to listen after wake")
    parser.add_argument("--no-wake", action="store_true", help="do not send wake payload")
    args = parser.parse_args()

    out_path = Path(args.outfile)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with out_path.open("w", encoding="ascii") as f:
        f.write(f"# BLE notify dump {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"# address={args.address}\n")

    buf = bytearray()
    creds = {"ssid": None, "pwd": None}

    async with BleakClient(args.address) as client:
        print("BLE connected:", client.is_connected)

        def on_notify(_, data: bytearray):
            nonlocal buf
            ts = time.time()
            buf.extend(data)
            line = f"{ts:.6f}\tlen={len(data)}\thex={hexdump(data)}\tascii={ascii_clean(data)}\n"
            with out_path.open("a", encoding="ascii") as f:
                f.write(line)
            # attempt JSON extraction (same as older script)
            try:
                s = buf.decode("ascii", errors="ignore")
                start = s.find("{")
                end = s.rfind("}")
                if start != -1 and end != -1 and end > start:
                    payload = s[start : end + 1]
                    obj = json.loads(payload)
                    if "ssid" in obj and "pwd" in obj:
                        creds["ssid"] = obj["ssid"]
                        creds["pwd"] = obj["pwd"]
            except Exception:
                pass

        await client.start_notify(CHAR_NOTIFY, on_notify)

        if not args.no_wake:
            print("Sending wake payload...")
            await client.write_gatt_char(CHAR_WRITE, WAKE_PAYLOAD, response=True)

        # wait for notifications
        end = time.time() + args.timeout
        while time.time() < end:
            await asyncio.sleep(0.2)

        try:
            await client.stop_notify(CHAR_NOTIFY)
        except Exception:
            pass

    print("BLE dump saved to", out_path)
    if creds["ssid"] and creds["pwd"]:
        print(f"Parsed SSID={creds['ssid']} PWD={creds['pwd']}")
    else:
        print("No SSID/PWD parsed from notify buffer.")


if __name__ == "__main__":
    asyncio.run(main())
