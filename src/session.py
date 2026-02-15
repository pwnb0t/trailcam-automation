from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from src.client import TrailCamClient
from src.config import CameraConfig, ClientConfig, PathsConfig


@dataclass
class TrailCamSession:
    """Runtime session state (not config).

    This is what becomes available only after the connect/login flow succeeds.
    """

    camera: CameraConfig
    client_cfg: ClientConfig
    paths: PathsConfig

    client: TrailCamClient
    login_token_u32: int
    wifi_ssid: str
    wifi_pwd: Optional[str] = None
    debug: bool = False

    # Operation inputs. These come from CLI/env config (RunnerConfig), but are convenient
    # to keep on the session so Command objects can be constructed as Command(session).
    target_dir_num: Optional[int] = None
    target_media_num: Optional[int] = None
    target_video_out: str = ""
