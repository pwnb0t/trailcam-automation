import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from src.constants import CAMERA_IP  # noqa: E402
from src.flows import legacy as flows_legacy  # noqa: E402


class _FakeClient:
    def __init__(self, recv_items=None, initial_none_reads=0, activate_on_download=False):
        self._recv_items = list(recv_items or [])
        self._initial_none_reads = int(initial_none_reads)
        self._activate_on_download = bool(activate_on_download)
        self._active = not self._activate_on_download
        self.sent_f1 = []
        self.sent_cmd_json = []

    def recv(self):
        if self._initial_none_reads > 0:
            self._initial_none_reads -= 1
            return None
        if not self._active:
            return None
        if self._recv_items:
            return self._recv_items.pop(0)
        return None

    def send_f1(self, opcode, body):
        self.sent_f1.append((opcode, bytes(body)))

    def send_cmd_json(self, obj, art_ver=None, art_typ=None):
        obj = dict(obj)
        self.sent_cmd_json.append((obj, art_ver, art_typ))
        if self._activate_on_download and int(obj.get("cmdId", -1)) == 1285:
            self._active = True

    def handle_incoming_payload(self, _data):
        return []


def _mk_session(client, *, listen_s=0.2, idle_s=0.01, debug=False):
    cfg = SimpleNamespace(
        client=SimpleNamespace(
            download_listen_s=listen_s,
            download_idle_s=idle_s,
            video_fps=12,
            strict_video=False,
        ),
        paths=SimpleNamespace(tmp_dir="/tmp", staging_dir="/tmp/staging"),
        camera=SimpleNamespace(alias="back"),
        debug=debug,
        dir_num=None,
        media_num=None,
        video_out="",
    )
    return SimpleNamespace(cfg=cfg, client=client, login_token_u32=12345)


class TestFlowsFlowContracts(unittest.TestCase):
    def test_seq16_order_and_missing_wraparound(self):
        keys = [0xFFFE, 0x0000, 0x0002, 0xFFFF]
        ordered = flows_legacy._order_seq16_from_anchor(keys, anchor=0xFFFE)
        self.assertEqual(ordered, [0xFFFE, 0xFFFF, 0x0000, 0x0002])
        missing = flows_legacy._seq16_missing_from_anchor(keys, anchor=0xFFFE)
        # Expected sequence span from FFFE to 0002 has 5 values; we provided 4.
        self.assertEqual(missing, 1)

    def test_photo_flow_ack_cadence_subtype03(self):
        recv_items = []
        for i in range(10):
            recv_items.append(((CAMERA_IP, 20000), f"pkt{i}".encode("ascii")))

        # drain_inbound() runs before main capture loop; keep recv inactive until
        # cmdId=1285 is sent so test packets are consumed by the main loop.
        client = _FakeClient(recv_items=recv_items, activate_on_download=True)
        session = _mk_session(client, listen_s=0.2, idle_s=0.01, debug=False)

        def fake_unpack(data):
            # Map pktN -> D0 subtype=0x03, seq=N
            if not data.startswith(b"pkt"):
                return None
            seq = int(data[3:])
            body = bytes([0xD1, 0x03, (seq >> 8) & 0xFF, seq & 0xFF]) + b"x"
            return 0xD0, body, b""

        with patch("src.flows.photo_download.unpack_f1", side_effect=fake_unpack):
            res = flows_legacy.send_photo_download_flow(
                session,
                dir_num=100,
                media_num=1,
                dump_dir="/tmp/photo-flow-test",
                file_type=0,
            )

        self.assertEqual(res["seq3_chunks"], 10)

        # ACK packets for subtype=0x03 should be emitted multiple times
        # (first 3 eagerly + trailing flush in finally path).
        subtype03_acks = [
            (op, body) for (op, body) in client.sent_f1 if op == 0xD1 and len(body) >= 2 and body[1] == 0x03
        ]
        self.assertGreaterEqual(len(subtype03_acks), 4)

    def test_video_flow_no_subtype02_raises_and_stops(self):
        client = _FakeClient(recv_items=[])
        session = _mk_session(client, listen_s=0.05, idle_s=0.01, debug=False)

        with self.assertRaisesRegex(RuntimeError, "No D0 subtype=0x02 chunks captured"):
            flows_legacy.send_video_download_flow_item(
                session,
                dir_num=100,
                media_num=2,
                out_mp4_path="/tmp/video-flow-contract-test.mp4",
            )

        # Verify cleanup contract sends stop playback command (cmdId=770).
        stop_cmds = [obj for (obj, _ver, _typ) in client.sent_cmd_json if obj.get("cmdId") == 770]
        self.assertGreaterEqual(len(stop_cmds), 1)


if __name__ == "__main__":
    unittest.main()
