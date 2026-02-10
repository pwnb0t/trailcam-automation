import socket
import struct
import threading
import time
from typing import Dict, List, Optional, Tuple

from config import CAMERA_IP, DISCOVERY_PORT, LOCAL_PORT
from protocol import build_artemis_record, decrypt_artemis_json, encrypt_cmd_json, unpack_f1


class TrailCamClient:
    def __init__(self, local_port: int = LOCAL_PORT, timeout_s: float = 0.25):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self.sock.bind(("0.0.0.0", local_port))
        self.sock.settimeout(timeout_s)
        self.camera_addr: Optional[Tuple[str, int]] = None
        self._stop = threading.Event()
        self._keepalive_thread: Optional[threading.Thread] = None
        self._seq8 = 0
        self.token_int: Optional[int] = None

    def close(self):
        self._stop.set()
        if self._keepalive_thread:
            self._keepalive_thread.join(timeout=1.0)
        self.sock.close()

    def send_raw(self, payload: bytes, addr: Optional[Tuple[str, int]] = None):
        if addr is None:
            if not self.camera_addr:
                raise RuntimeError("Camera addr not known yet")
            addr = self.camera_addr
        self.sock.sendto(payload, addr)

    def send_f1(self, opcode: int, body: bytes = b""):
        payload = bytes([0xF1, opcode]) + struct.pack("!H", len(body)) + body
        self.send_raw(payload)

    def send_beacons(self, count: int = 2):
        for _ in range(count):
            self.send_raw(bytes.fromhex("f1300000"), ("192.168.43.255", DISCOVERY_PORT))
            self.send_raw(bytes.fromhex("f1300000"), ("255.255.255.255", DISCOVERY_PORT))
            time.sleep(0.05)

    def recv(self) -> Optional[Tuple[Tuple[str, int], bytes]]:
        try:
            data, addr = self.sock.recvfrom(65535)
            return addr, data
        except socket.timeout:
            return None

    def learn_camera_port(self, max_wait_s: float = 5.0):
        deadline = time.time() + max_wait_s
        while time.time() < deadline:
            got = self.recv()
            if not got:
                continue
            addr, data = got
            if addr[0] != CAMERA_IP:
                continue
            self.camera_addr = addr
            return
        raise TimeoutError("Did not see any inbound UDP from camera")

    def start_keepalive(self, interval_s: float = 1.0):
        def loop():
            while not self._stop.is_set():
                try:
                    if self.camera_addr:
                        self.send_f1(0xE0, b"")
                except Exception:
                    pass
                self._stop.wait(interval_s)

        self._keepalive_thread = threading.Thread(target=loop, daemon=True)
        self._keepalive_thread.start()

    def send_cmd_json(self, obj: Dict, art_ver: int = 2, art_typ: int = 1):
        payload_b64 = encrypt_cmd_json(obj)
        if not payload_b64.endswith(b"\x00"):
            payload_b64 += b"\x00"
        art = build_artemis_record(payload_b64, art_ver, art_typ)

        max_chunk = 1024
        offset = 0
        while offset < len(art):
            chunk = art[offset : offset + max_chunk]
            seq = self._seq8 & 0xFF
            self._seq8 = (self._seq8 + 1) & 0xFF
            body = bytes([0xD1, 0x00, 0x00, seq]) + chunk
            self.send_f1(0xD0, body)
            offset += max_chunk

    def handle_incoming_payload(self, data: bytes) -> List[Dict]:
        parsed = unpack_f1(data)
        if not parsed:
            return []
        opcode, body, _ = parsed
        if opcode != 0xD0:
            return []
        return decrypt_artemis_json(body)
