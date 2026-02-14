import asyncio
import json
from typing import Dict

from bleak import BleakClient

from src.constants import CHAR_NOTIFY, CHAR_WRITE, WAKE_PAYLOAD


async def ble_wake_and_get_creds(address: str) -> Dict[str, str]:
    creds = {"ssid": None, "pwd": None}

    # Bleak/BlueZ on some systems intermittently throws DBus EOFError during
    # disconnect/__aexit__. Treat it as non-fatal once we already got creds.
    client = BleakClient(address)
    try:
        await client.connect()
        buf = bytearray()

        def on_notify(_, data: bytearray):
            nonlocal buf
            buf.extend(data)
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
        await client.write_gatt_char(CHAR_WRITE, WAKE_PAYLOAD, response=True)

        for _ in range(50):
            if creds["ssid"] and creds["pwd"]:
                break
            await asyncio.sleep(0.2)

        try:
            await client.stop_notify(CHAR_NOTIFY)
        except Exception:
            pass
    finally:
        try:
            await client.disconnect()
        except EOFError:
            # Common failure mode observed on Pi; ignore.
            pass
        except Exception:
            # Don't let cleanup prevent the caller from proceeding.
            pass

    if not creds["ssid"] or not creds["pwd"]:
        raise RuntimeError("Did not parse SSID/PWD from BLE notifications")
    return creds  # type: ignore
