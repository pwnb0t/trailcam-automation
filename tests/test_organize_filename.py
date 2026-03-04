import os
import sys
import unittest
from datetime import datetime

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from src.sync.organize import final_filename  # noqa: E402
from src.sync.sync_state import MediaKey  # noqa: E402


class TestOrganizeFilename(unittest.TestCase):
    def test_final_filename_photo_back(self):
        dt = datetime.fromisoformat("2026-03-04T10:11:12-06:00")
        key = MediaKey(dir_num=100, media_num=123, file_type=0)
        self.assertEqual(final_filename("back", key, dt), "2026-03-04_10-11-12_back.jpg")

    def test_final_filename_video_front(self):
        dt = datetime.fromisoformat("2026-03-04T10:11:12-06:00")
        key = MediaKey(dir_num=102, media_num=940, file_type=1)
        self.assertEqual(final_filename("front", key, dt), "2026-03-04_10-11-12_front.mp4")


if __name__ == "__main__":
    unittest.main()
