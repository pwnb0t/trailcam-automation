from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

from src.constants import DEFAULT_BLE_ADDRESS, WIFI_IFNAME, LOCAL_PORT


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
    defaults: DefaultsConfig
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
class DefaultsConfig:
    wifi_ifname: str = WIFI_IFNAME
    udp_local_port: int = LOCAL_PORT

    page_no: int = 0
    page_item_cnt: int = 45
    list_max_pages: int = 200

    download_listen_s: float = 45.0
    download_idle_s: float = 4.0

    video_fps: int = 30


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
    - constants defaults (via DefaultsConfig/PathsConfig dataclass defaults)
    - config.yaml overrides (AppConfig)
    - CLI overrides
    """

    camera: CameraConfig
    defaults: DefaultsConfig
    paths: PathsConfig

    op: str
    dir_num: Optional[int] = None
    media_num: Optional[int] = None
    video_out: str = ""
    debug: bool = False


def load_config(path: str | Path) -> AppConfig:
    """Load config YAML from disk.

    If the file does not exist, returns a default config with a single implicit camera.
    """
    p = Path(path)
    if not p.exists():
        # Backward-compatible defaults: one unnamed camera.
        cam = CameraConfig(alias="default", ble_address=DEFAULT_BLE_ADDRESS, ssid="")
        return AppConfig(
            version=1,
            cameras={"default": cam},
            defaults=DefaultsConfig(),
            paths=PathsConfig(),
        )

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

    defaults_raw = raw.get("defaults") or {}
    if defaults_raw and not isinstance(defaults_raw, dict):
        raise ValueError("defaults must be a mapping")
    d = DefaultsConfig(
        wifi_ifname=str(defaults_raw.get("wifi_ifname", WIFI_IFNAME)),
        udp_local_port=_must_int(defaults_raw.get("udp_local_port", LOCAL_PORT), "defaults.udp_local_port"),
        page_no=_must_int(defaults_raw.get("page_no", 0), "defaults.page_no"),
        page_item_cnt=_must_int(defaults_raw.get("page_item_cnt", 45), "defaults.page_item_cnt"),
        list_max_pages=_must_int(defaults_raw.get("list_max_pages", 200), "defaults.list_max_pages"),
        download_listen_s=_must_float(defaults_raw.get("download_listen_s", 45.0), "defaults.download_listen_s"),
        download_idle_s=_must_float(defaults_raw.get("download_idle_s", 4.0), "defaults.download_idle_s"),
        video_fps=_must_int(defaults_raw.get("video_fps", 30), "defaults.video_fps"),
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

    return AppConfig(version=ver, cameras=cams, defaults=d, paths=paths)


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


def _build_parser(
    *,
    defaults: DefaultsConfig,
    paths: PathsConfig,
    camera: Optional[CameraConfig],
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
        default=(camera.alias if camera else None),
        help="Camera alias from config.yaml (if omitted and config has 1 camera, that one is used)",
    )
    parser.add_argument(
        "--ble-address",
        default=(camera.ble_address if camera else DEFAULT_BLE_ADDRESS),
        help="BLE MAC address of the camera (default: %(default)s)",
    )
    parser.add_argument(
        "--ssid",
        default=(camera.ssid if camera else None),
        required=(camera is None or not camera.ssid),
        help="Camera AP SSID to connect to (required unless provided by config.yaml)",
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
        default=int(defaults.list_max_pages),
        help="Maximum pages to request when using --list-media-all (default: %(default)s)",
    )
    parser.add_argument(
        "--page-no",
        type=int,
        default=int(defaults.page_no),
        help="Media list page number for --download-page/--list-media-page (default: %(default)s)",
    )
    parser.add_argument(
        "--page-item-cnt",
        type=int,
        default=int(defaults.page_item_cnt),
        help="Items per media-list page request (default: %(default)s)",
    )

    parser.add_argument(
        "--media-out-dir",
        default=str(paths.media_out_dir),
        help="Output directory root for downloads (default: %(default)s)",
    )
    parser.add_argument("--tmp-dir", default=str(paths.tmp_dir), help="Temp directory root (default: %(default)s)")

    parser.add_argument("--dir-num", type=int, default=None, help="Media directory number (e.g. 102)")
    parser.add_argument("--media-num", type=int, default=None, help="Media number (e.g. 940)")
    parser.add_argument("--video-out", default="", help="Explicit output MP4 path for --download-video")

    return parser


def parse_config_and_args(argv: Optional[list[str]] = None) -> RunnerConfig:
    """Parse config.yaml + CLI args and return a resolved runner config object.

    Precedence:
    - constants defaults
    - config.yaml overrides
    - CLI overrides
    """
    pre = _build_pre_parser()
    pre_args, _ = pre.parse_known_args(argv)
    cfg_path = _resolve_config_path(pre_args.config)
    if cfg_path is not None and pre_args.config and not cfg_path.exists():
        raise SystemExit(f"--config path does not exist: {cfg_path}")

    # load_config() returns a default config object if the file doesn't exist.
    app_cfg = load_config(cfg_path or Path("config.yaml"))

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
    camera: Optional[CameraConfig] = None
    cam_alias = pre_args.camera
    if cam_alias:
        camera = app_cfg.get_camera(str(cam_alias))
    elif len(app_cfg.cameras) == 1:
        camera = next(iter(app_cfg.cameras.values()))

    parser = _build_parser(defaults=app_cfg.defaults, paths=paths, camera=camera, config_path=cfg_path)
    args = parser.parse_args(argv)

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

    # Camera identity: config-derived defaults, CLI can override.
    cam_alias_final = str(args.camera or (camera.alias if camera else "cli"))
    cam = CameraConfig(alias=cam_alias_final, ble_address=str(args.ble_address), ssid=str(args.ssid).strip())

    # Config-only: values are taken from app_cfg.defaults (constants -> yaml). No CLI flags.
    defaults = DefaultsConfig(
        wifi_ifname=str(app_cfg.defaults.wifi_ifname),
        udp_local_port=int(app_cfg.defaults.udp_local_port),
        page_no=int(args.page_no),
        page_item_cnt=int(page_item_cnt),
        list_max_pages=int(args.list_max_pages),
        download_listen_s=float(app_cfg.defaults.download_listen_s),
        download_idle_s=float(app_cfg.defaults.download_idle_s),
        video_fps=int(app_cfg.defaults.video_fps),
    )

    # Paths: allow CLI override of media/tmp dirs.
    run_paths = PathsConfig(media_out_dir=str(args.media_out_dir), tmp_dir=str(args.tmp_dir))

    # Ensure output dirs exist for local runs.
    Path(run_paths.media_out_dir).mkdir(parents=True, exist_ok=True)
    Path(run_paths.tmp_dir).mkdir(parents=True, exist_ok=True)

    return RunnerConfig(
        camera=cam,
        defaults=defaults,
        paths=run_paths,
        op=op,
        dir_num=(int(args.dir_num) if args.dir_num is not None else None),
        media_num=(int(args.media_num) if args.media_num is not None else None),
        video_out=str(args.video_out or ""),
        debug=bool(args.debug),
    )
