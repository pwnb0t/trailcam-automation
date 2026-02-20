import asyncio
import json
import re
import subprocess
from typing import Dict, Optional

from bleak import BleakClient

from src.constants import CHAR_NOTIFY, CHAR_WRITE, WAKE_PAYLOAD


def _is_bluez_in_progress_error(exc: Exception) -> bool:
    msg = str(exc)
    return ("org.bluez.Error.InProgress" in msg) or ("Operation already in progress" in msg)


_HCI_RE = re.compile(r"^hci\d+$", re.IGNORECASE)
_MAC_RE = re.compile(r"^[0-9A-Fa-f]{2}(:[0-9A-Fa-f]{2}){5}$")


def _resolve_bluez_adapter_name(adapter_or_mac: Optional[str]) -> Optional[str]:
    """Resolve configured adapter selector to BlueZ adapter name (hciX).

    Accepts:
    - hciX
    - controller MAC address
    """
    if not adapter_or_mac:
        return None
    raw = str(adapter_or_mac).strip()
    if not raw:
        return None
    if _HCI_RE.fullmatch(raw):
        return raw.lower()
    if not _MAC_RE.fullmatch(raw):
        raise ValueError(
            "bluetooth_adapter must be adapter hciX or controller MAC "
            "(example: hci0 or 8C:68:8B:83:07:DC)"
        )

    want_mac = raw.upper()
    # Parse `hciconfig -a` blocks and map MAC -> hciX.
    proc = subprocess.run(["hciconfig", "-a"], text=True, capture_output=True)
    out = proc.stdout or ""
    current_hci: Optional[str] = None
    for line in out.splitlines():
        if not line.strip():
            continue
        if line.startswith("hci") and ":" in line:
            current_hci = line.split(":", 1)[0].strip().lower()
            continue
        if current_hci and "BD Address:" in line:
            m = re.search(r"BD Address:\s*([0-9A-Fa-f:]{17})", line)
            if m and m.group(1).upper() == want_mac:
                return current_hci
    raise RuntimeError(f"Configured bluetooth_adapter MAC not found among local controllers: {want_mac}")


async def _ble_wake_and_get_creds_once_with_adapter(address: str, adapter: Optional[str]) -> Dict[str, str]:
    creds = {"ssid": None, "pwd": None}

    kwargs = {}
    if adapter:
        kwargs["adapter"] = adapter

    # Bleak/BlueZ on some systems intermittently throws DBus EOFError during
    # disconnect/__aexit__. Treat it as non-fatal once we already got creds.
    client = BleakClient(address, **kwargs)
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
            pass
        except Exception:
            pass

    if not creds["ssid"] or not creds["pwd"]:
        raise RuntimeError("Did not parse SSID/PWD from BLE notifications")
    return creds  # type: ignore


async def ble_wake_and_get_creds(
    address: str,
    *,
    retries: int = 5,
    retry_delay_s: float = 1.0,
    adapter: Optional[str] = None,
) -> Dict[str, str]:
    last_err: Exception | None = None
    adapter_name = _resolve_bluez_adapter_name(adapter)
    for attempt in range(1, retries + 1):
        try:
            return await _ble_wake_and_get_creds_once_with_adapter(address, adapter_name)
        except Exception as e:
            last_err = e
            if _is_bluez_in_progress_error(e) and attempt < retries:
                print(
                    f"BLE busy (InProgress), retrying {attempt}/{retries} after {retry_delay_s:.1f}s ..."
                )
                await asyncio.sleep(retry_delay_s)
                continue
            raise
    if last_err is not None:
        raise last_err
    raise RuntimeError("ble_wake_and_get_creds failed unexpectedly")
