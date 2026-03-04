import os
import sys
import unittest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import src.flows as flows  # noqa: E402


class TestFlowsApiSurface(unittest.TestCase):
    def test_expected_symbols_are_present(self):
        expected = [
            "fetch_media_list_page",
            "send_photo_download_flow",
            "download_photo_to_out",
            "download_photo_to_out_item",
            "send_video_download_flow",
            "send_video_download_flow_item",
            "normalize_media_entry",
            "_collect_media_entries",
            "_is_video_entry",
            "_is_photo_entry",
            "_parse_artemis_v4_payload_header",
        ]
        for name in expected:
            self.assertTrue(hasattr(flows, name), f"missing: {name}")


if __name__ == "__main__":
    unittest.main()
