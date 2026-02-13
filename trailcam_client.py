#!/usr/bin/env python3
import argparse
import asyncio
import threading
import time
from pathlib import Path

from client import TrailCamClient
from constants import DEFAULT_BLE_ADDRESS, WIFI_IFNAME
from ble import ble_wake_and_get_creds
from flows import (
    download_photo_page,
    download_media_page,
    download_photo_to_out,
    fetch_media_list_all,
    fetch_media_list_page,
    handshake_prelude,
    login_and_get_token,
    nmcli_connect,
    nmcli_list_ssids,
    nmcli_rescan,
    send_video_download_flow,
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
    action = parser.add_mutually_exclusive_group()
    action.add_argument(
        "--login-only",
        action="store_true",
        help="Perform JSON login only and exit",
    )
    action.add_argument(
        "--download-photo",
        action="store_true",
        help="After login, request a single photo download via cmdId=1285",
    )
    action.add_argument(
        "--download-video",
        action="store_true",
        help="After login, request a single video playback/download via cmdId=769 and save an MP4",
    )
    action.add_argument(
        "--download-page",
        action="store_true",
        help="After login, fetch one media-list page and download all media entries returned in that page",
    )
    action.add_argument(
        "--list-media-page",
        action="store_true",
        help="After login, fetch one media-list page and print entries",
    )
    action.add_argument(
        "--list-media-all",
        action="store_true",
        help="After login, page through media list and print entries until stop condition",
    )
    parser.add_argument(
        "--list-max-pages",
        type=int,
        default=200,
        help="Maximum pages to request when using --list-media-all (default: %(default)s)",
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
        help="Items per media-list page request (default: %(default)s). This effectively controls how many items --download-page will download.",
    )
    parser.add_argument(
        "--media-out-dir",
        default="out/media",
        help="Output directory root for downloads (default: %(default)s)",
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
        "--video-fps",
        type=int,
        default=30,
        help="FPS hint for ffmpeg mux when using --download-video (default: %(default)s)",
    )
    parser.add_argument(
        "--video-out",
        default="",
        help="Explicit output MP4 path for --download-video (default: out/media/<dirNum>/media####.mp4)",
    )
    args = parser.parse_args()

    if (args.dir_num is not None or args.media_num is not None) and not (
        args.download_photo or args.download_video
    ):
        raise SystemExit("--dir-num/--media-num are only valid with --download-photo or --download-video")

    # Camera returns an error if itemCntPerPage >= 50 ("need less than 50").
    if (args.download_page or args.list_media_page or args.list_media_all) and args.page_item_cnt >= 50:
        print(f"Warning: camera rejects --page-item-cnt >= 50; clamping {args.page_item_cnt} -> 45")
        args.page_item_cnt = 45

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
        if token is None and (
            args.download_photo
            or args.download_video
            or args.download_page
            or args.list_media_page
            or args.list_media_all
        ):
            raise SystemExit("Login token missing; cannot continue with requested action")
        if args.download_photo:
            if args.dir_num is None or args.media_num is None:
                raise SystemExit("--download-photo requires --dir-num and --media-num")
            out_path = download_photo_to_out(
                client,
                token,
                dir_num=args.dir_num,
                media_num=args.media_num,
                out_root=args.media_out_dir,
                listen_s=args.download_listen_s,
                idle_break_s=args.download_idle_s,
                debug=args.debug,
            )
            print(f"Wrote photo: {out_path or 'none'}")
            return

        if args.download_video:
            if args.dir_num is None or args.media_num is None:
                raise SystemExit("--download-video requires --dir-num and --media-num")
            if args.video_out:
                out_mp4 = args.video_out
            else:
                out_mp4 = str(Path(args.media_out_dir) / str(args.dir_num) / f"media{int(args.media_num):04d}.mp4")
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
            return

        if args.download_page:
            results = download_media_page(
                client,
                token,
                page_no=args.page_no,
                item_cnt_per_page=args.page_item_cnt,
                out_root=args.media_out_dir,
                listen_s=args.download_listen_s,
                idle_break_s=args.download_idle_s,
                video_fps=args.video_fps,
                debug=args.debug,
            )
            print(f"Downloaded page results: {len(results)} item(s)")
            for r in results:
                kind = r.get("kind", "media")
                path = r.get("path")
                print(f"  {kind} dir={r.get('dirNum')} media={r.get('mediaNum')} path={path or 'none'}")
            return

        if args.list_media_page:
            page = fetch_media_list_page(
                client,
                token,
                page_no=args.page_no,
                item_cnt_per_page=args.page_item_cnt,
                debug=args.debug,
            )
            print(f"Media entries (page {args.page_no}): {len(page)}")
            for e in page:
                print(
                    f"  dir={e.get('dirNum')} media={e.get('mediaNum')} fileType={e.get('fileType')} "
                    f"name={e.get('fileName') or ''} time={e.get('mediaTime') or ''} durMs={e.get('durationMs') or ''}"
                )
            return

        if args.list_media_all:
            all_entries = fetch_media_list_all(
                client,
                token,
                item_cnt_per_page=args.page_item_cnt,
                max_pages=args.list_max_pages,
                debug=args.debug,
            )
            print(f"Media entries (all): {len(all_entries)}")
            for e in all_entries:
                print(
                    f"  dir={e.get('dirNum')} media={e.get('mediaNum')} fileType={e.get('fileType')} "
                    f"name={e.get('fileName') or ''} time={e.get('mediaTime') or ''} durMs={e.get('durationMs') or ''}"
                )
            return

    finally:
        client.close()


if __name__ == "__main__":
    asyncio.run(main())
