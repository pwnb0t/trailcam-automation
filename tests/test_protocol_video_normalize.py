import os
import sys
import unittest


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from src.protocol import normalize_v4_video_payload_to_annexb_with_mode  # noqa: E402


class TestProtocolVideoNormalize(unittest.TestCase):
    def test_normalize_annexb_trims_small_prefix(self):
        payload = b"\x00\x00" + b"\x00\x00\x00\x01\x67\x64\x00\x28"
        out, mode = normalize_v4_video_payload_to_annexb_with_mode(payload)
        self.assertEqual(mode, "annexb")
        self.assertEqual(out, b"\x00\x00\x00\x01\x67\x64\x00\x28")

    def test_normalize_annexb_keeps_large_prefix(self):
        payload = b"prefix_" + b"\x00\x00\x00\x01\x67\x64\x00\x28"
        out, mode = normalize_v4_video_payload_to_annexb_with_mode(payload)
        self.assertEqual(mode, "annexb")
        self.assertEqual(out, payload)

    def test_normalize_len16_to_annexb(self):
        # Two len16-be NAL units:
        #  - 0x67 ... (SPS)
        #  - 0x68 ... (PPS)
        payload = (
            b"\x00\x04\x67\x64\x00\x28"
            b"\x00\x03\x68\xee\x3c"
        )
        out, mode = normalize_v4_video_payload_to_annexb_with_mode(payload)
        self.assertEqual(mode, "len16")
        self.assertEqual(
            out,
            b"\x00\x00\x00\x01\x67\x64\x00\x28"
            b"\x00\x00\x00\x01\x68\xee\x3c",
        )

    def test_normalize_raw_fallback(self):
        payload = b"\x12\x34\x56\x78\x9a\xbc"
        out, mode = normalize_v4_video_payload_to_annexb_with_mode(payload)
        self.assertEqual(mode, "raw")
        self.assertEqual(out, payload)


if __name__ == "__main__":
    unittest.main()

