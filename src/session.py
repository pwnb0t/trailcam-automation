from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from src.client import TrailCamClient
from src.config import RunnerConfig


@dataclass
class TrailCamSession:
    """Runtime session state (not config).

    This is what becomes available only after the connect/login flow succeeds.
    """

    # Resolved config for this run (config.yaml + CLI overrides).
    cfg: RunnerConfig

    client: TrailCamClient
    login_token_u32: int
    wifi_ssid: str
    battery_percent: Optional[int] = None
    wifi_pwd: Optional[str] = None
