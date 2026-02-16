from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

from src.command.command import Command, CommandError
from src.constants import CAMERA_IP
from src.protocol import make_ack_body_seq_list16, unpack_f1
from src.session import TrailCamSession


@dataclass
class FormatSdCardCommand(Command):
    session: TrailCamSession

    def validate(self) -> None:
        s = self.session
        if s.client is None:
            raise CommandError("session.client is required")
        if not isinstance(s.login_token_u32, int) or s.login_token_u32 <= 0:
            raise CommandError("session.login_token_u32 must be a positive int")

    def run(self, *, retries: int = 3, timeout_s: float = 25.0) -> Dict[str, Any]:
        self.validate()
        s = self.session
        client = s.client
        token = int(s.login_token_u32)
        debug = bool(s.cfg.debug)

        req = {"cmdId": 518, "token": token}
        last_resp: Optional[Dict[str, Any]] = None

        for attempt in range(1, retries + 1):
            print(f"TX JSON: format sd card (attempt {attempt}/{retries})")
            # In capture the app sends this more than once.
            client.send_cmd_json(req, art_ver=2, art_typ=42)
            if attempt == 1:
                time.sleep(0.05)
                client.send_cmd_json(req, art_ver=2, art_typ=42)

            deadline = time.time() + timeout_s
            while time.time() < deadline:
                got = client.recv()
                if not got:
                    continue
                addr, data = got
                if addr[0] != CAMERA_IP:
                    continue

                parsed = unpack_f1(data)
                if parsed:
                    opcode, body, _ = parsed
                    if opcode in (0x41, 0x42):
                        client.send_f1(opcode, body)
                    elif opcode == 0xE0:
                        client.send_f1(0xE1, b"")
                    elif opcode == 0xD0 and len(body) >= 4 and body[0] == 0xD1 and body[1] == 0x00:
                        seq0 = (body[2] << 8) | body[3]
                        client.send_f1(0xD1, make_ack_body_seq_list16(0x00, [seq0]))

                objs = client.handle_incoming_payload(data)
                for obj in objs:
                    if obj.get("cmdId") != 518:
                        continue
                    last_resp = obj
                    if debug:
                        print("RX JSON format:", obj)
                    if int(obj.get("result", -1)) == 0 and int(obj.get("formatRet", -1)) == 0:
                        return obj
        if last_resp is not None:
            raise CommandError(f"Format SD failed: {last_resp}")
        raise CommandError("Format SD failed: no cmdId=518 response")

