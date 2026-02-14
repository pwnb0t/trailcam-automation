from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from constants import DEFAULT_BLE_ADDRESS, WIFI_IFNAME
from config import CameraConfig, DefaultsConfig, PathsConfig


def _default_media_out_dir() -> str:
    p = Path("/mnt/trailcam/staging")
    try:
        if p.exists() and p.is_dir():
            return str(p)
    except Exception:
        pass
    return "out/media"


def _env(name: str) -> Optional[str]:
    v = os.environ.get(name)
    if v is None:
        return None
    v = v.strip()
    return v if v else None


def _env_int(name: str) -> Optional[int]:
    v = _env(name)
    if v is None:
        return None
    return int(v)


def _env_float(name: str) -> Optional[float]:
    v = _env(name)
    if v is None:
        return None
    return float(v)


@dataclass(frozen=True)
class EnvDefaults:
    """Environment-provided defaults for the runner.

    These are optional. CLI flags still take precedence.
    """

    ssid: Optional[str] = None
    ble_address: str = DEFAULT_BLE_ADDRESS
    ifname: str = WIFI_IFNAME
    port: int = 16734

    media_out_dir: str = "out/media"
    tmp_dir: str = "out/tmp"

    page_no: int = 0
    page_item_cnt: int = 48
    list_max_pages: int = 200

    download_listen_s: float = 45.0
    download_idle_s: float = 4.0

    video_fps: int = 30
    video_out: str = ""

    @staticmethod
    def from_env() -> "EnvDefaults":
        # Conservative: only a small set of env vars, all optional.
        return EnvDefaults(
            ssid=_env("TRAILCAM_SSID"),
            ble_address=_env("TRAILCAM_BLE_ADDRESS") or DEFAULT_BLE_ADDRESS,
            ifname=_env("TRAILCAM_IFNAME") or WIFI_IFNAME,
            port=_env_int("TRAILCAM_PORT") or 16734,
            media_out_dir=_env("TRAILCAM_MEDIA_OUT_DIR") or _default_media_out_dir(),
            tmp_dir=_env("TRAILCAM_TMP_DIR") or "out/tmp",
            page_no=_env_int("TRAILCAM_PAGE_NO") or 0,
            page_item_cnt=_env_int("TRAILCAM_PAGE_ITEM_CNT") or 48,
            list_max_pages=_env_int("TRAILCAM_LIST_MAX_PAGES") or 200,
            download_listen_s=_env_float("TRAILCAM_DOWNLOAD_LISTEN_S") or 45.0,
            download_idle_s=_env_float("TRAILCAM_DOWNLOAD_IDLE_S") or 4.0,
            video_fps=_env_int("TRAILCAM_VIDEO_FPS") or 30,
            video_out=_env("TRAILCAM_VIDEO_OUT") or "",
        )


def build_parser(env: EnvDefaults) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="TrailCam client runner.")
    parser.add_argument(
        "--ble-address",
        default=env.ble_address,
        help="BLE MAC address of the camera (default: %(default)s)",
    )
    parser.add_argument(
        "--ssid",
        default=env.ssid,
        required=(env.ssid is None),
        help="Camera AP SSID to connect to (required unless TRAILCAM_SSID is set)",
    )
    parser.add_argument("--debug", action="store_true", help="Enable verbose logging of incoming packets")

    action = parser.add_mutually_exclusive_group()
    action.add_argument("--login-only", action="store_true", help="Perform JSON login only and exit")
    action.add_argument("--download-photo", action="store_true", help="Download one photo (requires --dir-num/--media-num)")
    action.add_argument("--download-video", action="store_true", help="Download one video (requires --dir-num/--media-num)")
    action.add_argument("--download-page", action="store_true", help="Download all media items in one media-list page")
    action.add_argument("--list-media-page", action="store_true", help="List one media-list page")
    action.add_argument("--list-media-all", action="store_true", help="List all pages until stop condition")

    parser.add_argument(
        "--list-max-pages",
        type=int,
        default=env.list_max_pages,
        help="Maximum pages to request when using --list-media-all (default: %(default)s)",
    )
    parser.add_argument(
        "--page-no",
        type=int,
        default=env.page_no,
        help="Media list page number for --download-page/--list-media-page (default: %(default)s)",
    )
    parser.add_argument(
        "--page-item-cnt",
        type=int,
        default=env.page_item_cnt,
        help="Items per media-list page request (default: %(default)s)",
    )

    parser.add_argument(
        "--media-out-dir",
        default=env.media_out_dir,
        help="Output directory root for downloads (default: %(default)s)",
    )
    parser.add_argument("--tmp-dir", default=env.tmp_dir, help="Temp directory root (default: %(default)s)")

    parser.add_argument("--dir-num", type=int, default=None, help="Media directory number (e.g. 102)")
    parser.add_argument("--media-num", type=int, default=None, help="Media number (e.g. 940)")

    parser.add_argument("--video-out", default=env.video_out, help="Explicit output MP4 path for --download-video")

    return parser


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    env = EnvDefaults.from_env()
    parser = build_parser(env)
    args = parser.parse_args(argv)

    # Config-only settings (env defaults for now).
    # We still attach them to args so downstream config-building code can be simple.
    args.ifname = env.ifname
    args.port = env.port
    args.download_listen_s = env.download_listen_s
    args.download_idle_s = env.download_idle_s
    args.video_fps = env.video_fps

    # Normalize: allow "config.yml" naming for humans without changing code.
    if args.ssid:
        args.ssid = str(args.ssid).strip()

    # Ensure output dirs exist for local runs.
    Path(args.media_out_dir).mkdir(parents=True, exist_ok=True)
    Path(args.tmp_dir).mkdir(parents=True, exist_ok=True)

    return args


@dataclass(frozen=True)
class RunnerConfig:
    camera: CameraConfig
    defaults: DefaultsConfig
    paths: PathsConfig
    op: str
    dir_num: Optional[int] = None
    media_num: Optional[int] = None
    video_out: str = ""
    debug: bool = False


def parse_env_and_args_to_config(argv: Optional[list[str]] = None) -> RunnerConfig:
    """Parse env + CLI args and return a runner config object."""
    args = parse_args(argv)

    if (args.dir_num is not None or args.media_num is not None) and not (args.download_photo or args.download_video):
        raise SystemExit("--dir-num/--media-num are only valid with --download-photo or --download-video")
    if args.download_photo and (args.dir_num is None or args.media_num is None):
        raise SystemExit("--download-photo requires --dir-num and --media-num")
    if args.download_video and (args.dir_num is None or args.media_num is None):
        raise SystemExit("--download-video requires --dir-num and --media-num")

    page_item_cnt = int(args.page_item_cnt)
    if (args.download_page or args.list_media_page or args.list_media_all) and page_item_cnt >= 50:
        print(f"Warning: camera rejects --page-item-cnt >= 50; clamping {page_item_cnt} -> 45")
        page_item_cnt = 45

    op = ""
    for name in (
        "login_only",
        "download_photo",
        "download_video",
        "download_page",
        "list_media_page",
        "list_media_all",
    ):
        if getattr(args, name):
            op = name
            break
    if not op:
        raise SystemExit(
            "Choose an action: --login-only, --download-photo, --download-video, --download-page, "
            "--list-media-page, --list-media-all"
        )

    camera = CameraConfig(alias="cli", ble_address=str(args.ble_address), ssid=str(args.ssid))
    defaults = DefaultsConfig(
        wifi_ifname=str(args.ifname),
        udp_local_port=int(args.port),
        page_no=int(args.page_no),
        page_item_cnt=int(page_item_cnt),
        list_max_pages=int(args.list_max_pages),
        download_listen_s=float(args.download_listen_s),
        download_idle_s=float(args.download_idle_s),
        video_fps=int(args.video_fps),
    )
    paths = PathsConfig(media_out_dir=str(args.media_out_dir), tmp_dir=str(args.tmp_dir))

    return RunnerConfig(
        camera=camera,
        defaults=defaults,
        paths=paths,
        op=op,
        dir_num=(int(args.dir_num) if args.dir_num is not None else None),
        media_num=(int(args.media_num) if args.media_num is not None else None),
        video_out=str(args.video_out or ""),
        debug=bool(args.debug),
    )
