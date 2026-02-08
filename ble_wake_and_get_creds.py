import asyncio
import json
import subprocess
from bleak import BleakClient

ADDRESS = "C6:1E:0D:E0:0C:FB"
CHAR_WRITE  = "00000002-0000-1000-8000-00805f9b34fb"
CHAR_NOTIFY = "00000003-0000-1000-8000-00805f9b34fb"

WAKE_PAYLOAD = bytes.fromhex(
    "13 57 01 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00"
)

WIFI_IFNAME = "wlan0"


def nmcli_rescan():
    subprocess.run(["sudo", "nmcli", "dev", "wifi", "rescan"], check=False)


def nmcli_list_ssids():
    p = subprocess.run(
        ["sudo", "nmcli", "-t", "-f", "SSID", "dev", "wifi", "list"],
        text=True,
        capture_output=True,
    )
    return [l.strip() for l in p.stdout.splitlines() if l.strip()]


def nmcli_connect(ssid: str, pwd: str, ifname: str = WIFI_IFNAME) -> bool:
    """
    Connect using NM. This may require sudo/polkit depending on your system.
    """
    # Disconnect any existing connection on that interface (helps avoid “already active” weirdness)
    subprocess.run(["sudo", "nmcli", "dev", "disconnect", ifname], capture_output=True, check=False)

    # Delete existing connection profile for this SSID if it exists to avoid conflicts
    subprocess.run(["sudo", "nmcli", "connection", "delete", ssid], capture_output=True, check=False)

    p = subprocess.run(
        ["sudo", "nmcli", "dev", "wifi", "connect", ssid, "password", pwd, "ifname", ifname],
        text=True,
        capture_output=True,
    )
    if p.returncode != 0:
        print("❌ nmcli connect failed:")
        if p.stdout:
            print(p.stdout.strip())
        if p.stderr:
            print(p.stderr.strip())
        return False

    print("✅ nmcli connect succeeded")
    return True


def wifi_has_camera_ip(ifname: str = WIFI_IFNAME) -> bool:
    """
    Return True if ifname has a 192.168.43.x address.
    """
    p = subprocess.run(["ip", "-br", "addr", "show", ifname], text=True, capture_output=True)
    out = p.stdout.strip()
    return "192.168.43." in out


async def main():
    creds = {"ssid": None, "pwd": None}

    try:
        async with BleakClient(ADDRESS) as client:
            print("BLE connected:", client.is_connected)

            buf = bytearray()

            def on_notify(_, data: bytearray):
                nonlocal buf
                print("NOTIFY:", data.hex())
                buf.extend(data)

                try:
                    s = buf.decode("ascii", errors="ignore")
                    start = s.find("{")
                    end = s.rfind("}")
                    if start != -1 and end != -1 and end > start:
                        payload = s[start:end+1]
                        print(f"DEBUG: attempting to parse: {payload}")
                        obj = json.loads(payload)
                        if "ssid" in obj and "pwd" in obj:
                            creds["ssid"] = obj["ssid"]
                            creds["pwd"] = obj["pwd"]
                except Exception as e:
                    print(f"DEBUG: parsing error: {e}")
                    pass

            await client.start_notify(CHAR_NOTIFY, on_notify)

            print("Sending wake payload...")
            await client.write_gatt_char(CHAR_WRITE, WAKE_PAYLOAD, response=True)

            for _ in range(50):  # up to ~10s
                if creds["ssid"] and creds["pwd"]:
                    break
                await asyncio.sleep(0.2)

            if creds["ssid"] and creds["pwd"]:
                print(f"✅ Camera reported SSID={creds['ssid']} PWD={creds['pwd']}")
            else:
                print("❌ Did not parse SSID/PWD from notify; cannot auto-connect.")
                print(f"DEBUG: final buffer content (hex): {buf.hex()}")
                print(f"DEBUG: final buffer content (ascii): {buf.decode('ascii', errors='ignore')}")
                return

            try:
                await client.stop_notify(CHAR_NOTIFY)
            except Exception as e:
                print(f"IGNORING error from client.stop_notify: {e}")

    except EOFError as e:
        print(f"ℹ️ BLE disconnected or error occurred (likely device switching to WiFi): {e}")

    print("Waiting for SSID to appear in scans...")
    for t in range(1, 61):
        nmcli_rescan()
        ssids = nmcli_list_ssids()
        if creds["ssid"] in ssids:
            print(f"✅ SSID is visible after {t}s")
            break
        await asyncio.sleep(1)
    else:
        print("❌ SSID still not visible after 60s")
        return

    print("Connecting to camera Wi-Fi...")
    if not nmcli_connect(creds["ssid"], creds["pwd"], WIFI_IFNAME):
        return

    # Wait for DHCP / address assignment
    for _ in range(30):  # up to ~6s
        if wifi_has_camera_ip(WIFI_IFNAME):
            break
        await asyncio.sleep(0.2)

    if not wifi_has_camera_ip(WIFI_IFNAME):
        print("❌ Connected but did not get 192.168.43.x address on wlan0.")
        subprocess.run(["ip", "-br", "addr", "show", WIFI_IFNAME])
        return

    subprocess.run(["ip", "-br", "addr", "show", WIFI_IFNAME])
    print("✅ Ready for UDP gallery refresh step (run your refresh script now).")


asyncio.run(main())
