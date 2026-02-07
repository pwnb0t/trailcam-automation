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

def nmcli_rescan():
    """Updated sudoers (sudo visudo) to allow this command"""
    subprocess.run(["sudo", "nmcli", "dev", "wifi", "rescan"], check=False)

def nmcli_list_ssids():
    """Updated sudoers (sudo visudo) to allow this command"""
    p = subprocess.run(
        ["sudo", "nmcli", "-t", "-f", "SSID", "dev", "wifi", "list"],
        text=True,
        capture_output=True,
    )
    ssids = [l.strip() for l in p.stdout.splitlines() if l.strip()]
    return ssids

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

                # Try to find JSON in the buffer
                try:
                    s = buf.decode("ascii", errors="ignore")
                    start = s.find("{")
                    end = s.rfind("}")
                    if start != -1 and end != -1 and end > start:
                        js = s[start:end+1]
                        obj = json.loads(js)
                        if "ssid" in obj and "pwd" in obj:
                            creds["ssid"] = obj["ssid"]
                            creds["pwd"] = obj["pwd"]
                except Exception:
                    pass

            await client.start_notify(CHAR_NOTIFY, on_notify)

            print("Sending wake payload...")
            await client.write_gatt_char(CHAR_WRITE, WAKE_PAYLOAD, response=True)

            # Wait for creds from notify
            for _ in range(50):  # up to ~10s
                if creds["ssid"] and creds["pwd"]:
                    break
                await asyncio.sleep(0.2)

            if creds["ssid"]:
                print(f"✅ Camera reported SSID={creds['ssid']} PWD={creds['pwd']}")
            else:
                print("⚠️ Did not parse SSID/PWD from notify (but may still work)")

            try:
                await client.stop_notify(CHAR_NOTIFY)
            except Exception as e:
                print(f"IGNORING error from client.stop_notify: {e}")
    except EOFError as e:
        print(f"ℹ️ BLE disconnected or error occurred (likely device switching to WiFi): {e}")

    print("Waiting for SSID to appear in scans...")
    for t in range(1, 61):  # up to 60s
        nmcli_rescan()
        ssids = nmcli_list_ssids()
        if creds["ssid"] and creds["ssid"] in ssids:
            print(f"✅ SSID is visible after {t}s")
            break
        await asyncio.sleep(1)
    else:
        print("❌ SSID still not visible after 60s")

asyncio.run(main())