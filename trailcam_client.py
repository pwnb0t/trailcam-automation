#!/usr/bin/env python3
import argparse
import asyncio
import threading
import time

from client import TrailCamClient
from constants import DEFAULT_BLE_ADDRESS, WIFI_IFNAME
from ble import ble_wake_and_get_creds
from flows import (
    download_photo_page,
    handshake_prelude,
    login_and_get_token,
    nmcli_connect,
    nmcli_list_ssids,
    nmcli_rescan,
    send_video_download_flow,
    send_photo_download_flow,
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
        "--ssid",
        required=True,
        help="Camera AP SSID to connect to (required; e.g. TrailCam_5DBD)",
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
        "--download-photo",
        action="store_true",
        help="After login, request a single photo download via cmdId=1285",
    )
    parser.add_argument(
        "--download-video",
        action="store_true",
        help="After login, request a single video playback/download via cmdId=769 and save an MP4",
    )
    parser.add_argument(
        "--download-page",
        action="store_true",
        help="After login, fetch one media-list page and download the newest photo entries",
    )
    parser.add_argument(
        "--page-no",
        type=int,
        default=0,
        help="Media list page number for --download-page (default: %(default)s)",
    )
    parser.add_argument(
        "--page-item-cnt",
        type=int,
        default=45,
        help="Items per media-list page request (default: %(default)s)",
    )
    parser.add_argument(
        "--page-download-limit",
        type=int,
        default=12,
        help="Maximum photos to download from fetched page (default: %(default)s)",
    )
    parser.add_argument(
        "--media-out-dir",
        default="out/media",
        help="Output directory root for --download-page results (default: %(default)s)",
    )
    parser.add_argument(
        "--dir-num",
        type=int,
        default=None,
        help="Media directory number for --download-photo (e.g. 102)",
    )
    parser.add_argument(
        "--media-num",
        type=int,
        default=None,
        help="Media number for --download-photo (e.g. 940)",
    )
    parser.add_argument(
        "--download-listen-s",
        type=float,
        default=45.0,
        help="Seconds to listen for bulk download/playback data after sending a download/start-play request (default: %(default)s)",
    )
    parser.add_argument(
        "--download-idle-s",
        type=float,
        default=4.0,
        help="Stop download/playback capture after this many seconds of data-channel idle time (default: %(default)s)",
    )
    parser.add_argument(
        "--download-art-typ",
        type=int,
        default=7,
        help="ARTEMIS type to use for cmdId=1285 photo download request (default: %(default)s; app often uses 7)",
    )
    parser.add_argument(
        "--video-fps",
        type=int,
        default=30,
        help="FPS hint for ffmpeg mux when using --download-video (default: %(default)s)",
    )
    parser.add_argument(
        "--video-out",
        default="",
        help="Explicit output MP4 path for --download-video (default: out/media/dir<dirNum>/media<mediaNum>.mp4)",
    )
    parser.add_argument(
        "--dump-thumbs",
        action="store_true",
        help="Write gallery thumbnails from large D0 stream to out/",
    )
    parser.add_argument(
        "--dump-artemis",
        action="store_true",
        help="Write raw ARTEMIS payloads (media list responses) to out/artemis/",
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

    # If already connected to the camera AP, skip BLE wake/connect work.
    already_connected = False
    nmcli_rescan()
    ssids_now = nmcli_list_ssids()
    if args.ssid in ssids_now and wifi_has_camera_ip(args.ifname):
        already_connected = True
        print(f"Already connected to camera AP {args.ssid}; skipping BLE wake")

    if not already_connected:
        creds = await ble_wake_and_get_creds(args.ble_address)
        ssid = creds["ssid"]
        pwd = creds["pwd"]
        if isinstance(pwd, str):
            pwd = pwd.strip("\x00").strip()

        if not ssid or not pwd:
            print(f"BLE creds: ssid={ssid} pwd={'<set>' if pwd else None}")
            raise SystemExit("SSID/PWD not returned from BLE wake")

        if ssid != args.ssid:
            raise SystemExit(f"BLE returned SSID {ssid}, but --ssid is {args.ssid}")

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

        token = login_and_get_token(client)
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
                    dump_artemis=args.dump_artemis,
                    debug=args.debug,
                )
            if args.download_photo:
                if args.dir_num is None or args.media_num is None:
                    raise SystemExit("--download-photo requires --dir-num and --media-num")
                send_photo_download_flow(
                    client,
                    token,
                    dir_num=args.dir_num,
                    media_num=args.media_num,
                    file_type=0,
                    art_typ=args.download_art_typ,
                    listen_s=args.download_listen_s,
                    idle_break_s=args.download_idle_s,
                    debug=args.debug,
                )
            if args.download_video:
                if args.dir_num is None or args.media_num is None:
                    raise SystemExit("--download-video requires --dir-num and --media-num")
                if args.video_out:
                    out_mp4 = args.video_out
                else:
                    out_mp4 = str(
                        Path(args.media_out_dir) / f"dir{args.dir_num}" / f"media{args.media_num}.mp4"
                    )
                send_video_download_flow(
                    client,
                    token,
                    dir_num=args.dir_num,
                    media_num=args.media_num,
                    file_type=1,
                    fps=args.video_fps,
                    listen_s=args.download_listen_s,
                    idle_break_s=args.download_idle_s,
                    out_mp4_path=out_mp4,
                    debug=args.debug,
                )
            if args.download_page:
                results = download_photo_page(
                    client,
                    token,
                    page_no=args.page_no,
                    item_cnt_per_page=args.page_item_cnt,
                    limit=args.page_download_limit,
                    out_root=args.media_out_dir,
                    art_typ=args.download_art_typ,
                    listen_s=args.download_listen_s,
                    idle_break_s=args.download_idle_s,
                    debug=args.debug,
                )
                print(f"Downloaded page results: {len(results)} item(s)")
                for r in results:
                    print(
                        f"  dir={r['dirNum']} media={r['mediaNum']} "
                        f"jpeg={r['best_jpeg'] or 'none'} out={r['dump_dir']}"
                    )

    finally:
        client.close()


if __name__ == "__main__":
    asyncio.run(main())
