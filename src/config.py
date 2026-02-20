from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from src.constants import (
    WIFI_IFNAME,
    LOCAL_PORT,
    DEFAULT_PAGE_NO,
    DEFAULT_PAGE_ITEM_CNT,
    DEFAULT_LIST_MAX_PAGES,
    DEFAULT_DOWNLOAD_LISTEN_S,
    DEFAULT_DOWNLOAD_IDLE_S,
    DEFAULT_PHOTO_DOWNLOAD_RETRIES,
    DEFAULT_VIDEO_FPS,
    DEFAULT_STRICT_VIDEO,
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


def _must_bool(v: Any, field: str) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        s = v.strip().lower()
        if s in ("1", "true", "yes", "on"):
            return True
        if s in ("0", "false", "no", "off"):
            return False
    raise ValueError(f"{field} must be a bool, got {v!r}")


_ENV_REF_RE = re.compile(r"^\$\{([A-Za-z_][A-Za-z0-9_]*)\}$")


def _expand_env_ref(v: Any, field: str) -> str:
    s = str(v)
    m = _ENV_REF_RE.match(s.strip())
    if not m:
        return s
    env_name = m.group(1)
    env_val = os.getenv(env_name)
    if env_val is None:
        raise ValueError(f"{field} references env var {env_name!r}, but it is not set")
    return env_val


@dataclass(frozen=True)
class EmailAlertsConfig:
    enabled: bool = False
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_app_password: str = ""
    from_email: str = ""
    to_emails: List[str] = field(default_factory=list)
    subject_prefix: str = "[TrailCam Sync]"
    starttls: bool = True
    notify_on: List[str] = field(default_factory=lambda: ["failure"])


@dataclass(frozen=True)
class AlertsConfig:
    email: EmailAlertsConfig = field(default_factory=EmailAlertsConfig)


@dataclass(frozen=True)
class AppConfig:
    version: int
    cameras: Dict[str, CameraConfig]
    client: ClientConfig
    paths: PathsConfig
    alerts: AlertsConfig = field(default_factory=AlertsConfig)

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
    # Optional BLE controller selector for BlueZ:
    # - adapter name: hci0, hci1, ...
    # - controller MAC: AA:BB:CC:DD:EE:FF
    bluetooth_adapter: Optional[str] = None
    udp_local_port: int = LOCAL_PORT

    page_no: int = DEFAULT_PAGE_NO
    page_item_cnt: int = DEFAULT_PAGE_ITEM_CNT
    list_max_pages: int = DEFAULT_LIST_MAX_PAGES

    download_listen_s: float = DEFAULT_DOWNLOAD_LISTEN_S
    download_idle_s: float = DEFAULT_DOWNLOAD_IDLE_S
    photo_download_retries: int = DEFAULT_PHOTO_DOWNLOAD_RETRIES

    video_fps: int = DEFAULT_VIDEO_FPS
    strict_video: bool = DEFAULT_STRICT_VIDEO


@dataclass(frozen=True)
class PathsConfig:
    staging_dir: str = "out/media"
    tmp_dir: str = "out/tmp"
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
    bt_adapter_raw = client_raw.get("bluetooth_adapter", None)
    bt_adapter: Optional[str]
    if bt_adapter_raw is None:
        bt_adapter = None
    else:
        bt_s = str(bt_adapter_raw).strip()
        if not bt_s:
            bt_adapter = None
        else:
            if not re.fullmatch(r"hci\d+", bt_s, flags=re.IGNORECASE) and not re.fullmatch(
                r"[0-9A-Fa-f]{2}(:[0-9A-Fa-f]{2}){5}", bt_s
            ):
                raise ValueError(
                    "client.bluetooth_adapter must be adapter hciX or controller MAC "
                    "(example: hci0 or 8C:68:8B:83:07:DC)"
                )
            bt_adapter = bt_s
    c = ClientConfig(
        wifi_ifname=str(client_raw.get("wifi_ifname", WIFI_IFNAME)),
        bluetooth_adapter=bt_adapter,
        udp_local_port=_must_int(client_raw.get("udp_local_port", LOCAL_PORT), "client.udp_local_port"),
        page_no=DEFAULT_PAGE_NO,
        page_item_cnt=_must_int(client_raw.get("page_item_cnt", DEFAULT_PAGE_ITEM_CNT), "client.page_item_cnt"),
        list_max_pages=_must_int(client_raw.get("list_max_pages", DEFAULT_LIST_MAX_PAGES), "client.list_max_pages"),
        download_listen_s=_must_float(
            client_raw.get("download_listen_s", DEFAULT_DOWNLOAD_LISTEN_S), "client.download_listen_s"
        ),
        download_idle_s=_must_float(client_raw.get("download_idle_s", DEFAULT_DOWNLOAD_IDLE_S), "client.download_idle_s"),
        photo_download_retries=_must_int(
            client_raw.get("photo_download_retries", DEFAULT_PHOTO_DOWNLOAD_RETRIES),
            "client.photo_download_retries",
        ),
        video_fps=_must_int(client_raw.get("video_fps", DEFAULT_VIDEO_FPS), "client.video_fps"),
        strict_video=_must_bool(client_raw.get("strict_video", DEFAULT_STRICT_VIDEO), "client.strict_video"),
    )

    paths_raw = raw.get("paths") or {}
    if paths_raw and not isinstance(paths_raw, dict):
        raise ValueError("paths must be a mapping")
    paths = PathsConfig(
        # prefer staging_dir; accept media_out_dir as legacy alias
        staging_dir=str(paths_raw.get("staging_dir", paths_raw.get("media_out_dir", "out/media"))),
        tmp_dir=str(paths_raw.get("tmp_dir", "out/tmp")),
        final_media_dir=(str(paths_raw["final_media_dir"]) if "final_media_dir" in paths_raw else None),
    )

    alerts_raw = raw.get("alerts") or {}
    if alerts_raw and not isinstance(alerts_raw, dict):
        raise ValueError("alerts must be a mapping")
    email_raw = alerts_raw.get("email") or {}
    if email_raw and not isinstance(email_raw, dict):
        raise ValueError("alerts.email must be a mapping")

    to_emails_raw = email_raw.get("to_emails", [])
    if isinstance(to_emails_raw, str):
        to_emails = [x.strip() for x in to_emails_raw.split(",") if x.strip()]
    elif isinstance(to_emails_raw, list):
        to_emails = [str(x).strip() for x in to_emails_raw if str(x).strip()]
    else:
        raise ValueError("alerts.email.to_emails must be a list or comma-separated string")

    email_cfg = EmailAlertsConfig(
        enabled=_must_bool(email_raw.get("enabled", False), "alerts.email.enabled"),
        smtp_host=str(email_raw.get("smtp_host", "smtp.gmail.com")),
        smtp_port=_must_int(email_raw.get("smtp_port", 587), "alerts.email.smtp_port"),
        smtp_user=str(email_raw.get("smtp_user", "")),
        smtp_app_password=_expand_env_ref(email_raw.get("smtp_app_password", ""), "alerts.email.smtp_app_password"),
        from_email=str(email_raw.get("from_email", "")),
        to_emails=to_emails,
        subject_prefix=str(email_raw.get("subject_prefix", "[TrailCam Sync]")),
        starttls=_must_bool(email_raw.get("starttls", True), "alerts.email.starttls"),
        notify_on=[str(x).strip().lower() for x in email_raw.get("notify_on", ["failure"]) if str(x).strip()],
    )
    alerts_cfg = AlertsConfig(email=email_cfg)

    return AppConfig(version=ver, cameras=cams, client=c, paths=paths, alerts=alerts_cfg)


def _default_staging_dir() -> str:
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
    action.add_argument(
        "--delete-media-all",
        action="store_true",
        help="Delete all media from camera (currently implemented as SD format, cmdId=518)",
    )
    action.add_argument("--download-page", action="store_true", help="Download all media items in one media-list page")
    action.add_argument("--list-media-page", action="store_true", help="List one media-list page")
    action.add_argument("--list-media-all", action="store_true", help="List all pages until stop condition")

    parser.add_argument("--list-max-pages", type=int, default=DEFAULT_LIST_MAX_PAGES)
    parser.add_argument("--page-no", type=int, default=DEFAULT_PAGE_NO)
    parser.add_argument("--page-item-cnt", type=int, default=DEFAULT_PAGE_ITEM_CNT)

    parser.add_argument("--staging-dir", default="out/media")
    parser.add_argument("--tmp-dir", default="out/tmp")
    parser.add_argument("--dir-num", type=int, default=DEFAULT_DIR_NUM)
    parser.add_argument("--video-out", default="")
    parser.add_argument("--strict-video", action="store_true", default=DEFAULT_STRICT_VIDEO)
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
    action.add_argument(
        "--delete-media-all",
        action="store_true",
        help="Delete all media from camera (currently implemented as SD format, cmdId=518)",
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
        "--staging-dir",
        default=str(paths.staging_dir),
        help="Output directory root for downloads (default: %(default)s)",
    )
    parser.add_argument("--tmp-dir", default=str(paths.tmp_dir), help="Temp directory root (default: %(default)s)")

    parser.add_argument("--dir-num", type=int, default=DEFAULT_DIR_NUM, help="Media directory number (default: %(default)s)")
    parser.add_argument("--video-out", default="", help="Explicit output MP4 path for --download-single (when item is a video)")
    parser.add_argument(
        "--strict-video",
        action="store_true",
        default=bool(client_cfg.strict_video),
        help="Enable strict video transport checks (missing sequence or changed duplicate sequence => fail)",
    )

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
    if paths.staging_dir == "out/media":
        paths = PathsConfig(
            staging_dir=_default_staging_dir(),
            tmp_dir=paths.tmp_dir,
            final_media_dir=paths.final_media_dir,
        )

    # Choose camera: explicit --camera wins; else if config has one camera, use it.
    camera_aliases = sorted(app_cfg.cameras.keys())
    if pre_args.camera:
        camera0 = app_cfg.get_camera(str(pre_args.camera))
    elif len(app_cfg.cameras) == 1:
        camera0 = next(iter(app_cfg.cameras.values()))
    elif ("-h" in argv_in or "--help" in argv_in):
        # Allow help output without forcing --camera when multiple cameras exist.
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
        "delete_media_all",
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
            "Choose an action: --login-only, --download-single, --delete-media-all, --download-page, "
            "--list-media-page, --list-media-all"
        )

    cam = app_cfg.get_camera(str(args.camera))

    # Config-only: values are taken from app_cfg.client (constants -> yaml). No CLI flags.
    client_cfg = ClientConfig(
        wifi_ifname=str(app_cfg.client.wifi_ifname),
        bluetooth_adapter=(str(app_cfg.client.bluetooth_adapter) if app_cfg.client.bluetooth_adapter else None),
        udp_local_port=int(app_cfg.client.udp_local_port),
        page_no=int(args.page_no),
        page_item_cnt=int(page_item_cnt),
        list_max_pages=int(args.list_max_pages),
        download_listen_s=float(app_cfg.client.download_listen_s),
        download_idle_s=float(app_cfg.client.download_idle_s),
        photo_download_retries=int(app_cfg.client.photo_download_retries),
        video_fps=int(app_cfg.client.video_fps),
        strict_video=bool(args.strict_video),
    )

    # Paths: allow CLI override of staging/tmp dirs.
    run_paths = PathsConfig(staging_dir=str(args.staging_dir), tmp_dir=str(args.tmp_dir))

    # Ensure output dirs exist for local runs.
    Path(run_paths.staging_dir).mkdir(parents=True, exist_ok=True)
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
