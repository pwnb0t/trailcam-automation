#!/usr/bin/env python3
import argparse
import asyncio
import threading
import time

from client import TrailCamClient
from config import DEFAULT_BLE_ADDRESS, WIFI_IFNAME
from ble import ble_wake_and_get_creds
from flows import (
    handshake_prelude,
    login_and_get_token,
    nmcli_connect,
    nmcli_list_ssids,
    nmcli_rescan,
    send_full_json_flow,
    wifi_has_camera_ip,
)


async def main():
    parser = argparse.ArgumentParser(
        description="TrailCam client: BLE wake, connect, JSON login, and media list."
    )
    parser.add_argument(
        "--ble-address",
        default=DEFAULT_BLE_ADDRESS,
        help="BLE MAC address of the camera (default: %(default)s)",
    )
    parser.add_argument(
        "--skip-ble",
        action="store_true",
        help="Skip BLE wake/credentials. Assumes you are already connected to the camera AP.",
    )
    parser.add_argument(
        "--ifname",
        default=WIFI_IFNAME,
        help="Wi-Fi interface to use (default: %(default)s)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=16734,
        help="Local UDP port to bind (default: %(default)s)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable verbose logging of incoming packets",
    )
    parser.add_argument(
        "--login-only",
        action="store_true",
        help="Perform JSON login only and exit",
    )
    parser.add_argument(
        "--json-flow",
        action="store_true",
        help="After login, send dev info (cmdId=512) and media list (cmdId=768)",
    )
    parser.add_argument(
        "--dump-thumbs",
        action="store_true",
        help="Write gallery thumbnails from large D0 stream to out/",
    )
    parser.add_argument(
        "--thumb-offset",
        type=int,
        default=0,
        help="Offset mediaNum for thumbnailReqs (use to align with current files)",
    )
    parser.add_argument(
        "--thumb-dir",
        type=int,
        default=None,
        help="Override dirNum for thumbnailReqs (e.g. 100/101/102)",
    )
    args = parser.parse_args()

    if not args.skip_ble:
        creds = await ble_wake_and_get_creds(args.ble_address)
        ssid = creds["ssid"]
        pwd = creds["pwd"]
        if isinstance(pwd, str):
            pwd = pwd.strip("\x00").strip()

        if not ssid or not pwd:
            print(f"BLE creds: ssid={ssid} pwd={'<set>' if pwd else None}")
            raise SystemExit("SSID/PWD not returned from BLE wake")

        print(f"BLE creds: ssid={ssid} pwd_len={len(pwd)}")

        print(f"SSID={ssid}")
        print("Waiting for SSID to appear in scans...")
        for t in range(1, 61):
            nmcli_rescan()
            ssids = nmcli_list_ssids()
            if ssid in ssids:
                print(f"SSID visible after {t}s")
                break
            await asyncio.sleep(1)
        else:
            raise SystemExit("SSID not visible after 60s")

        print("Connecting to camera Wi-Fi...")
        if not nmcli_connect(ssid, pwd, args.ifname):
            raise SystemExit("nmcli connect failed")
    else:
        print("Camera AP already visible; skipping BLE wake")

    for _ in range(30):
        if wifi_has_camera_ip(args.ifname):
            break
        await asyncio.sleep(0.2)
    if not wifi_has_camera_ip(args.ifname):
        raise SystemExit("Connected but did not get 192.168.43.x address")

    await asyncio.sleep(1.0)

    print("Connected to camera AP. Starting UDP session...")
    client = TrailCamClient(local_port=args.port)
    try:
        client.send_beacons(count=4)
        client.learn_camera_port()
        print(f"Camera addr: {client.camera_addr}")

        def beacon_loop():
            end = time.time() + 8.0
            while time.time() < end:
                try:
                    client.send_beacons(count=1)
                except Exception:
                    pass
                time.sleep(0.5)

        t_beacon = threading.Thread(target=beacon_loop, daemon=True)
        t_beacon.start()

        client.start_keepalive(interval_s=1.0)
        handshake_prelude(client, debug=args.debug, duration_s=3.0)

        token = login_and_get_token(client, "admin", "admin")
        if token is None:
            print("Login token not found yet.")
        else:
            client.token_int = token
            print(f"Login token: {token}")
            if args.login_only:
                return
            if args.json_flow:
                send_full_json_flow(
                    client,
                    token,
                    dump_thumbs=args.dump_thumbs,
                    thumb_offset=args.thumb_offset,
                    thumb_dir=args.thumb_dir,
                )

    finally:
        client.close()


if __name__ == "__main__":
    asyncio.run(main())
