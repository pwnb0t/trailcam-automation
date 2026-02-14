from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

from constants import DEFAULT_BLE_ADDRESS, WIFI_IFNAME, LOCAL_PORT


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
