import os
import sys
import unittest


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from src.flows import _parse_artemis_v4_payload_header  # noqa: E402


def _build_v4_payload(
    *,
    data_len: int,
    data_len_off: int,
    pts_ms: int = 12345,
    width: int = 1920,
    height: int = 1080,
    session_no: int = 4242,
) -> bytes:
    if data_len_off not in (16, 20):
        raise ValueError("data_len_off must be 16 or 20")
    header_len = 108
    payload = bytearray(header_len + data_len)
    payload[8:12] = int(pts_ms).to_bytes(4, "little", signed=False)
    payload[28:32] = int(width).to_bytes(4, "little", signed=False)
    payload[32:36] = int(height).to_bytes(4, "little", signed=False)
    payload[48:52] = int(session_no).to_bytes(4, "little", signed=False)
    payload[data_len_off : data_len_off + 4] = int(data_len).to_bytes(4, "little", signed=False)
    return bytes(payload)


class TestFlowsV4Header(unittest.TestCase):
    def test_parse_v4_header_valid_offset_16(self):
        payload = _build_v4_payload(data_len=64, data_len_off=16, pts_ms=111, width=1920, height=1080, session_no=99)
        hdr = _parse_artemis_v4_payload_header(payload)
        self.assertIsNotNone(hdr)
        self.assertEqual(hdr["header_len"], 108)
        self.assertEqual(hdr["data_len"], 64)
        self.assertEqual(hdr["data_len_off"], 16)
        self.assertEqual(hdr["pts_ms"], 111)
        self.assertEqual(hdr["width"], 1920)
        self.assertEqual(hdr["height"], 1080)
        self.assertEqual(hdr["session_no"], 99)

    def test_parse_v4_header_valid_offset_20_fallback(self):
        payload = bytearray(_build_v4_payload(data_len=80, data_len_off=20, pts_ms=222, width=0, height=0, session_no=1234))
        payload[16:20] = (0).to_bytes(4, "little", signed=False)  # force fallback path
        hdr = _parse_artemis_v4_payload_header(bytes(payload))
        self.assertIsNotNone(hdr)
        self.assertEqual(hdr["data_len"], 80)
        self.assertEqual(hdr["data_len_off"], 20)
        self.assertEqual(hdr["pts_ms"], 222)
        self.assertEqual(hdr["session_no"], 1234)

    def test_parse_v4_header_rejects_short_payload(self):
        self.assertIsNone(_parse_artemis_v4_payload_header(b"\x00" * 107))

    def test_parse_v4_header_rejects_invalid_data_len(self):
        payload = bytearray(_build_v4_payload(data_len=48, data_len_off=16))
        payload[16:20] = (47).to_bytes(4, "little", signed=False)  # mismatch
        payload[20:24] = (0).to_bytes(4, "little", signed=False)   # fallback also invalid
        self.assertIsNone(_parse_artemis_v4_payload_header(bytes(payload)))


if __name__ == "__main__":
    unittest.main()

