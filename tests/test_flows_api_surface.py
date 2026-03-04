import os
import sys
import unittest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import src.flows.media_list as media_list  # noqa: E402
import src.flows.photo_download as photo_download  # noqa: E402
import src.flows.video_download as video_download  # noqa: E402


class TestFlowsModuleSurface(unittest.TestCase):
    def test_media_list_symbols_present(self):
        expected = [
            "fetch_media_list_page",
            "normalize_media_entry",
            "_collect_media_entries",
            "_is_video_entry",
            "_is_photo_entry",
        ]
        for name in expected:
            self.assertTrue(hasattr(media_list, name), f"media_list missing: {name}")

    def test_photo_download_symbols_present(self):
        expected = [
            "send_photo_download_flow",
            "download_photo_to_out",
            "download_photo_to_out_item",
        ]
        for name in expected:
            self.assertTrue(hasattr(photo_download, name), f"photo_download missing: {name}")

    def test_video_download_symbols_present(self):
        expected = [
            "send_video_download_flow",
            "send_video_download_flow_item",
            "_parse_artemis_v4_payload_header",
        ]
        for name in expected:
            self.assertTrue(hasattr(video_download, name), f"video_download missing: {name}")


if __name__ == "__main__":
    unittest.main()
