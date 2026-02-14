from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from src.client import TrailCamClient
from src.config import CameraConfig, DefaultsConfig, PathsConfig


@dataclass
class TrailCamSession:
    """Runtime session state (not config).

    This is what becomes available only after the connect/login flow succeeds.
    """

    camera: CameraConfig
    defaults: DefaultsConfig
    paths: PathsConfig

    client: TrailCamClient
    login_token_u32: int
    wifi_ssid: str
    wifi_pwd: Optional[str] = None
    debug: bool = False
