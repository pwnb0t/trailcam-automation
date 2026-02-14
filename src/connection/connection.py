from __future__ import annotations

import asyncio
from typing import Optional

from src.connection.ble import ble_wake_and_get_creds
from src.client import TrailCamClient
from src.flows import (
    handshake_prelude,
    login_and_get_token,
    nmcli_connect,
    nmcli_list_ssids,
    nmcli_rescan,
    wifi_has_camera_ip,
)
from src.runner_inputs import RunnerConfig
from src.session import TrailCamSession


async def connect_and_login(cfg: RunnerConfig) -> TrailCamSession:
    """Full connect flow: BLE wake -> Wi-Fi join -> UDP handshake -> login.

    Returns a TrailCamSession containing the TrailCamClient and login token.
    """
    camera = cfg.camera
    ssid_expected = camera.ssid

    nmcli_rescan()
    ssids_now = nmcli_list_ssids()
    already_connected = ssid_expected in ssids_now and wifi_has_camera_ip(cfg.defaults.wifi_ifname)

    wifi_pwd: Optional[str] = None
    if not already_connected:
        creds = await ble_wake_and_get_creds(camera.ble_address)
        ssid = str(creds.get("ssid") or "").strip()
        pwd = creds.get("pwd")
        if isinstance(pwd, str):
            pwd = pwd.strip("\x00").strip()
        wifi_pwd = str(pwd or "")

        if not ssid or not wifi_pwd:
            raise RuntimeError("SSID/PWD not returned from BLE wake")
        if ssid != ssid_expected:
            raise RuntimeError(f"BLE returned SSID {ssid}, expected {ssid_expected}")

        # Wait for it to appear in scans.
        for _ in range(60):
            nmcli_rescan()
            if ssid in nmcli_list_ssids():
                break
            await asyncio.sleep(1)
        else:
            raise RuntimeError("SSID not visible after 60s")

        if not nmcli_connect(ssid, wifi_pwd, cfg.defaults.wifi_ifname):
            raise RuntimeError("nmcli connect failed")

    for _ in range(30):
        if wifi_has_camera_ip(cfg.defaults.wifi_ifname):
            break
        await asyncio.sleep(0.2)
    if not wifi_has_camera_ip(cfg.defaults.wifi_ifname):
        raise RuntimeError("Connected but did not get 192.168.43.x address")

    await asyncio.sleep(1.0)

    client = TrailCamClient(local_port=cfg.defaults.udp_local_port)
    try:
        client.send_beacons(count=4)
        client.learn_camera_port()
        client.start_keepalive(interval_s=1.0)
        handshake_prelude(client, debug=cfg.debug, duration_s=3.0)
        token = login_and_get_token(client)
        if token is None:
            raise RuntimeError("Login token not found")
        client.token_int = token
        return TrailCamSession(
            camera=camera,
            defaults=cfg.defaults,
            paths=cfg.paths,
            client=client,
            login_token_u32=token,
            wifi_ssid=ssid_expected,
            wifi_pwd=wifi_pwd,
            debug=cfg.debug,
            target_dir_num=cfg.dir_num,
            target_media_num=cfg.media_num,
            target_video_out=str(cfg.video_out or ""),
        )
    except Exception:
        client.close()
        raise
