from __future__ import annotations

import asyncio
import subprocess
import time
from typing import List, Optional

from src.connection.ble import ble_wake_and_get_creds
from src.client import TrailCamClient
from src.constants import CAMERA_IP, CAMERA_PASSWORD, CAMERA_USERNAME
from src.protocol import make_ack_body_seq_list16, unpack_f1
from src.runner_inputs import RunnerConfig
from src.session import TrailCamSession


def nmcli_rescan() -> None:
    subprocess.run(["sudo", "nmcli", "dev", "wifi", "rescan"], capture_output=True)


def nmcli_list_ssids() -> List[str]:
    p = subprocess.run(["sudo", "nmcli", "-t", "-f", "SSID", "dev", "wifi"], text=True, capture_output=True)
    if p.returncode != 0:
        return []
    return [line.strip() for line in p.stdout.splitlines() if line.strip()]


def nmcli_connect(ssid: str, pwd: str, ifname: str) -> bool:
    # remove stale profile first
    subprocess.run(["sudo", "nmcli", "con", "delete", "id", ssid], text=True, capture_output=True)
    cmd = ["sudo", "nmcli", "dev", "wifi", "connect", ssid, "password", pwd, "ifname", ifname]
    p = subprocess.run(cmd, text=True, capture_output=True)
    if p.returncode != 0:
        err = (p.stderr or "").strip()
        out = (p.stdout or "").strip()
        print("nmcli connect failed:")
        if out:
            print(out)
        if err:
            print(err)
        return False
    return True


def wifi_has_camera_ip(ifname: str) -> bool:
    p = subprocess.run(["sudo", "ip", "-br", "addr", "show", ifname], text=True, capture_output=True)
    out = p.stdout.strip()
    return "192.168.43." in out


def handshake_prelude(client: TrailCamClient, debug: bool = False, duration_s: float = 3.0) -> None:
    seen_ops = {}
    start = time.time()
    while time.time() - start < duration_s:
        got = client.recv()
        if not got:
            continue
        addr, data = got
        if addr[0] != CAMERA_IP:
            continue
        parsed = unpack_f1(data)
        if not parsed:
            continue
        opcode, body, _ = parsed
        seen_ops[opcode] = seen_ops.get(opcode, 0) + 1
        if debug:
            print(f"RX opcode=0x{opcode:02x} len={len(body)}")
        if opcode in (0x41, 0x42):
            client.send_f1(opcode, body)
            time.sleep(0.02)
            client.send_f1(opcode, body)
        elif opcode == 0xE0:
            client.send_f1(0xE1, b"")
        elif opcode == 0xD0 and len(body) >= 4 and body[0] == 0xD1 and body[1] == 0x00:
            seq0 = (body[2] << 8) | body[3]
            ack = make_ack_body_seq_list16(0x00, [seq0])
            client.send_f1(0xD1, ack)
    if debug:
        print("Handshake opcodes seen:", {hex(k): v for k, v in seen_ops.items()})


def login_and_get_token(client: TrailCamClient, timeout_s: float = 5.0, retries: int = 3) -> Optional[int]:
    login_obj = {
        "cmdId": 0,
        "usrName": CAMERA_USERNAME,
        "password": CAMERA_PASSWORD,
        "needVideo": 0,
        "needAudio": 0,
        "utcTime": int(time.time()),
        "supportHeartBeat": True,
    }
    for _ in range(retries):
        client.send_cmd_json(login_obj, art_ver=2, art_typ=1)
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            got = client.recv()
            if not got:
                continue
            addr, data = got
            if addr[0] != CAMERA_IP:
                continue
            objs = client.handle_incoming_payload(data)
            for obj in objs:
                if obj.get("cmdId") == 0 and "token" in obj:
                    return int(obj["token"])
    return None


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
