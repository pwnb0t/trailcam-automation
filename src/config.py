from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

from src.constants import (
    WIFI_IFNAME,
    LOCAL_PORT,
    DEFAULT_PAGE_NO,
    DEFAULT_PAGE_ITEM_CNT,
    DEFAULT_LIST_MAX_PAGES,
    DEFAULT_DOWNLOAD_LISTEN_S,
    DEFAULT_DOWNLOAD_IDLE_S,
    DEFAULT_VIDEO_FPS,
    DEFAULT_DIR_NUM,
    MAX_PAGE_ITEM_CNT_EXCLUSIVE,
)


def _must_int(v: Any, field: str) -> int:
    try:
        return int(v)
    except Exception as e:
        raise ValueError(f"{field} must be an int, got {v!r}") from e


def _must_float(v: Any, field: str) -> float:
    try:
        return float(v)
    except Exception as e:
        raise ValueError(f"{field} must be a float, got {v!r}") from e


@dataclass(frozen=True)
class AppConfig:
    version: int
    cameras: Dict[str, CameraConfig]
    client: ClientConfig
    paths: PathsConfig

    def get_camera(self, alias: str) -> CameraConfig:
        try:
            return self.cameras[alias]
        except KeyError as e:
            raise KeyError(f"Unknown camera alias {alias!r}. Known: {sorted(self.cameras)}") from e


@dataclass(frozen=True)
class CameraConfig:
    alias: str
    ble_address: str
    ssid: str


@dataclass(frozen=True)
class ClientConfig:
    wifi_ifname: str = WIFI_IFNAME
    udp_local_port: int = LOCAL_PORT

    page_no: int = DEFAULT_PAGE_NO
    page_item_cnt: int = DEFAULT_PAGE_ITEM_CNT
    list_max_pages: int = DEFAULT_LIST_MAX_PAGES

    download_listen_s: float = DEFAULT_DOWNLOAD_LISTEN_S
    download_idle_s: float = DEFAULT_DOWNLOAD_IDLE_S

    video_fps: int = DEFAULT_VIDEO_FPS


@dataclass(frozen=True)
class PathsConfig:
    media_out_dir: str = "out/media"
    tmp_dir: str = "out/tmp"

    staging_dir: Optional[str] = None
    final_media_dir: Optional[str] = None


@dataclass(frozen=True)
class RunnerConfig:
    """Resolved config for a single run.

    This is derived from:
    - constants defaults (via ClientConfig/PathsConfig dataclass defaults)
    - config.yaml overrides (AppConfig)
    - CLI overrides
    """

    camera: CameraConfig
    client: ClientConfig
    paths: PathsConfig

    op: str
    dir_num: Optional[int] = None
    media_num: Optional[int] = None
    video_out: str = ""
    debug: bool = False


def load_config(path: str | Path) -> AppConfig:
    """Load config YAML from disk."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Config file not found: {p}")

    raw = yaml.safe_load(p.read_text("utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError("Config must be a YAML mapping at the top level")

    ver = _must_int(raw.get("version", 1), "version")
    if ver != 1:
        raise ValueError(f"Unsupported config version: {ver}")

    cams_raw = raw.get("cameras") or {}
    if not isinstance(cams_raw, dict) or not cams_raw:
        raise ValueError("Config must define at least one camera under 'cameras:'")

    cams: Dict[str, CameraConfig] = {}
    for alias, node in cams_raw.items():
        if not isinstance(node, dict):
            raise ValueError(f"cameras.{alias} must be a mapping")
        ble = str(node.get("ble_address") or node.get("ble_mac") or "").strip()
        ssid = str(node.get("ssid") or "").strip()
        if not ble:
            raise ValueError(f"cameras.{alias}.ble_address is required")
        if not ssid:
            raise ValueError(f"cameras.{alias}.ssid is required")
        cams[str(alias)] = CameraConfig(alias=str(alias), ble_address=ble, ssid=ssid)

    client_raw = raw.get("client") or {}
    if client_raw and not isinstance(client_raw, dict):
        raise ValueError("client must be a mapping")
    if "page_no" in client_raw:
        raise ValueError("client.page_no is CLI-only; remove it from config.yaml")
    c = ClientConfig(
        wifi_ifname=str(client_raw.get("wifi_ifname", WIFI_IFNAME)),
        udp_local_port=_must_int(client_raw.get("udp_local_port", LOCAL_PORT), "client.udp_local_port"),
        page_no=DEFAULT_PAGE_NO,
        page_item_cnt=_must_int(client_raw.get("page_item_cnt", DEFAULT_PAGE_ITEM_CNT), "client.page_item_cnt"),
        list_max_pages=_must_int(client_raw.get("list_max_pages", DEFAULT_LIST_MAX_PAGES), "client.list_max_pages"),
        download_listen_s=_must_float(
            client_raw.get("download_listen_s", DEFAULT_DOWNLOAD_LISTEN_S), "client.download_listen_s"
        ),
        download_idle_s=_must_float(client_raw.get("download_idle_s", DEFAULT_DOWNLOAD_IDLE_S), "client.download_idle_s"),
        video_fps=_must_int(client_raw.get("video_fps", DEFAULT_VIDEO_FPS), "client.video_fps"),
    )

    paths_raw = raw.get("paths") or {}
    if paths_raw and not isinstance(paths_raw, dict):
        raise ValueError("paths must be a mapping")
    paths = PathsConfig(
        media_out_dir=str(paths_raw.get("media_out_dir", "out/media")),
        tmp_dir=str(paths_raw.get("tmp_dir", "out/tmp")),
        staging_dir=(str(paths_raw["staging_dir"]) if "staging_dir" in paths_raw else None),
        final_media_dir=(str(paths_raw["final_media_dir"]) if "final_media_dir" in paths_raw else None),
    )

    return AppConfig(version=ver, cameras=cams, client=c, paths=paths)


def _default_media_out_dir() -> str:
    p = Path("/mnt/trailcam/staging")
    try:
        if p.exists() and p.is_dir():
            return str(p)
    except Exception:
        pass
    return "out/media"


def _resolve_config_path(explicit: Optional[str]) -> Optional[Path]:
    if explicit:
        return Path(explicit)
    for name in ("config.yaml", "config.yml"):
        p = Path(name)
        if p.exists():
            return p
    return None


def _build_pre_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument("--config", default=None, help="Path to config.yaml/config.yml (default: auto-detect)")
    p.add_argument("--camera", default=None, help="Camera alias from config.yaml (required if multiple cameras)")
    return p


def _build_help_only_parser() -> argparse.ArgumentParser:
    # This is used when the user requests --help but no config.yaml is present.
    # It deliberately omits dynamic defaults and camera choices.
    parser = argparse.ArgumentParser(description="TrailCam client runner.")
    parser.add_argument("--config", default=None, help="Path to config.yaml/config.yml (default: auto-detect)")
    parser.add_argument("--camera", default=None, help="Camera alias from config.yaml")
    parser.add_argument("--debug", action="store_true", help="Enable verbose logging of incoming packets")

    action = parser.add_mutually_exclusive_group()
    action.add_argument("--login-only", action="store_true", help="Perform JSON login only and exit")
    action.add_argument(
        "--download-single",
        type=int,
        default=None,
        metavar="MEDIA_NUM",
        help="Download one media item by media number (uses media list to pick photo vs video)",
    )
    action.add_argument("--download-page", action="store_true", help="Download all media items in one media-list page")
    action.add_argument("--list-media-page", action="store_true", help="List one media-list page")
    action.add_argument("--list-media-all", action="store_true", help="List all pages until stop condition")

    parser.add_argument("--list-max-pages", type=int, default=DEFAULT_LIST_MAX_PAGES)
    parser.add_argument("--page-no", type=int, default=DEFAULT_PAGE_NO)
    parser.add_argument("--page-item-cnt", type=int, default=DEFAULT_PAGE_ITEM_CNT)

    parser.add_argument("--media-out-dir", default="out/media")
    parser.add_argument("--tmp-dir", default="out/tmp")
    parser.add_argument("--dir-num", type=int, default=DEFAULT_DIR_NUM)
    parser.add_argument("--video-out", default="")
    return parser


def _build_parser(
    *,
    client_cfg: ClientConfig,
    paths: PathsConfig,
    camera: CameraConfig,
    camera_aliases: list[str],
    config_path: Optional[Path],
) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="TrailCam client runner.")
    parser.add_argument(
        "--config",
        default=str(config_path) if config_path else None,
        help="Path to config.yaml/config.yml (default: auto-detect config.yaml/config.yml in cwd)",
    )
    parser.add_argument(
        "--camera",
        default=camera.alias,
        choices=camera_aliases,
        help="Camera alias from config.yaml",
    )
    parser.add_argument("--debug", action="store_true", help="Enable verbose logging of incoming packets")

    action = parser.add_mutually_exclusive_group()
    action.add_argument("--login-only", action="store_true", help="Perform JSON login only and exit")
    action.add_argument(
        "--download-single",
        type=int,
        default=None,
        metavar="MEDIA_NUM",
        help="Download one media item by media number (uses media list to pick photo vs video)",
    )
    action.add_argument("--download-page", action="store_true", help="Download all media items in one media-list page")
    action.add_argument("--list-media-page", action="store_true", help="List one media-list page")
    action.add_argument("--list-media-all", action="store_true", help="List all pages until stop condition")

    parser.add_argument(
        "--list-max-pages",
        type=int,
        default=int(client_cfg.list_max_pages),
        help="Maximum pages to request when using --list-media-all (default: %(default)s)",
    )
    parser.add_argument(
        "--page-no",
        type=int,
        default=int(client_cfg.page_no),
        help="Media list page number for --download-page/--list-media-page (default: %(default)s)",
    )
    parser.add_argument(
        "--page-item-cnt",
        type=int,
        default=int(client_cfg.page_item_cnt),
        help="Items per media-list page request (default: %(default)s)",
    )

    parser.add_argument(
        "--media-out-dir",
        default=str(paths.media_out_dir),
        help="Output directory root for downloads (default: %(default)s)",
    )
    parser.add_argument("--tmp-dir", default=str(paths.tmp_dir), help="Temp directory root (default: %(default)s)")

    parser.add_argument("--dir-num", type=int, default=DEFAULT_DIR_NUM, help="Media directory number (default: %(default)s)")
    parser.add_argument("--video-out", default="", help="Explicit output MP4 path for --download-single (when item is a video)")

    return parser


def parse_config_and_args(argv: Optional[list[str]] = None) -> RunnerConfig:
    """Parse config.yaml + CLI args and return a resolved runner config object.

    Precedence:
    - constants defaults
    - config.yaml overrides
    - CLI overrides
    """
    argv_in = argv if argv is not None else sys.argv[1:]
    pre = _build_pre_parser()
    pre_args, _ = pre.parse_known_args(argv_in)
    cfg_path = _resolve_config_path(pre_args.config)
    if ("-h" in argv_in or "--help" in argv_in) and cfg_path is None:
        _build_help_only_parser().parse_args(argv_in)
        raise SystemExit(0)
    if cfg_path is None:
        raise SystemExit(
            "No config file found. Create config.yaml (see config.example.yaml), "
            "or pass --config /path/to/config.yaml"
        )
    if pre_args.config and not cfg_path.exists():
        raise SystemExit(f"--config path does not exist: {cfg_path}")

    try:
        app_cfg = load_config(cfg_path)
    except FileNotFoundError as e:
        raise SystemExit(str(e))

    # If config didn't specify output dir, prefer /mnt/trailcam/staging when present.
    paths = app_cfg.paths
    if paths.media_out_dir == "out/media":
        paths = PathsConfig(
            media_out_dir=_default_media_out_dir(),
            tmp_dir=paths.tmp_dir,
            staging_dir=paths.staging_dir,
            final_media_dir=paths.final_media_dir,
        )

    # Choose camera: explicit --camera wins; else if config has one camera, use it.
    camera_aliases = sorted(app_cfg.cameras.keys())
    if pre_args.camera:
        camera0 = app_cfg.get_camera(str(pre_args.camera))
    elif len(app_cfg.cameras) == 1:
        camera0 = next(iter(app_cfg.cameras.values()))
    else:
        raise SystemExit(f"--camera is required (known: {camera_aliases})")

    parser = _build_parser(
        client_cfg=app_cfg.client,
        paths=paths,
        camera=camera0,
        camera_aliases=camera_aliases,
        config_path=cfg_path,
    )
    args = parser.parse_args(argv_in)

    if args.download_single is not None and args.download_single <= 0:
        raise SystemExit("--download-single MEDIA_NUM must be a positive integer")

    page_item_cnt = int(args.page_item_cnt)
    if (args.download_page or args.list_media_page or args.list_media_all) and page_item_cnt >= MAX_PAGE_ITEM_CNT_EXCLUSIVE:
        print(
            f"Warning: camera rejects --page-item-cnt >= {MAX_PAGE_ITEM_CNT_EXCLUSIVE}; clamping {page_item_cnt} -> {DEFAULT_PAGE_ITEM_CNT}"
        )
        page_item_cnt = DEFAULT_PAGE_ITEM_CNT

    op = ""
    for name in (
        "login_only",
        "download_single",
        "download_page",
        "list_media_page",
        "list_media_all",
    ):
        v = getattr(args, name)
        if isinstance(v, bool) and v:
            op = name
            break
        if name == "download_single" and v is not None:
            op = name
            break
    if not op:
        raise SystemExit(
            "Choose an action: --login-only, --download-single, --download-page, "
            "--list-media-page, --list-media-all"
        )

    cam = app_cfg.get_camera(str(args.camera))

    # Config-only: values are taken from app_cfg.client (constants -> yaml). No CLI flags.
    client_cfg = ClientConfig(
        wifi_ifname=str(app_cfg.client.wifi_ifname),
        udp_local_port=int(app_cfg.client.udp_local_port),
        page_no=int(args.page_no),
        page_item_cnt=int(page_item_cnt),
        list_max_pages=int(args.list_max_pages),
        download_listen_s=float(app_cfg.client.download_listen_s),
        download_idle_s=float(app_cfg.client.download_idle_s),
        video_fps=int(app_cfg.client.video_fps),
    )

    # Paths: allow CLI override of media/tmp dirs.
    run_paths = PathsConfig(media_out_dir=str(args.media_out_dir), tmp_dir=str(args.tmp_dir))

    # Ensure output dirs exist for local runs.
    Path(run_paths.media_out_dir).mkdir(parents=True, exist_ok=True)
    Path(run_paths.tmp_dir).mkdir(parents=True, exist_ok=True)

    return RunnerConfig(
        camera=cam,
        client=client_cfg,
        paths=run_paths,
        op=op,
        dir_num=int(args.dir_num),
        media_num=(int(args.download_single) if args.download_single is not None else None),
        video_out=str(args.video_out or ""),
        debug=bool(args.debug),
    )
