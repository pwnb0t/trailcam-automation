import os
import sys
import unittest


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from src.flows.media_list import (  # noqa: E402
    _collect_media_entries,
    _is_photo_entry,
    _is_video_entry,
    normalize_media_entry,
)


class TestMediaListHelpers(unittest.TestCase):
    def test_collect_media_entries_recurses_nested_shapes(self):
        node = {
            "outer": [
                {"mediaDirNum": 102, "mediaNum": 940, "fileType": 0},
                {"x": {"dirNum": 100, "mediaNum": 105, "fileType": 1}},
            ],
            "other": {"ignore": 123},
        }
        out = []
        _collect_media_entries(node, out)
        self.assertEqual(len(out), 2)
        nums = sorted((int(e.get("mediaNum")), int(e.get("fileType", 0))) for e in out)
        self.assertEqual(nums, [(105, 1), (940, 0)])

    def test_normalize_media_entry_infers_file_type_from_name(self):
        photo = normalize_media_entry({"mediaDirNum": "102", "mediaNum": "940", "fileName": "DSCF0940.JPG"})
        video = normalize_media_entry({"dirNum": 100, "mediaNum": 105, "name": "DSCF0105.MP4"})
        self.assertIsNotNone(photo)
        self.assertIsNotNone(video)
        assert photo is not None and video is not None
        self.assertEqual(photo["fileType"], 0)
        self.assertEqual(video["fileType"], 1)
        self.assertEqual(photo["dirNum"], 102)
        self.assertEqual(photo["mediaNum"], 940)

    def test_normalize_media_entry_rejects_invalid_numbers(self):
        self.assertIsNone(normalize_media_entry({"dirNum": "abc", "mediaNum": "1"}))
        self.assertIsNone(normalize_media_entry({"dirNum": "100"}))

    def test_is_video_and_is_photo_entry_helpers(self):
        self.assertTrue(_is_video_entry({"fileType": 1}))
        self.assertFalse(_is_video_entry({"fileType": 0}))
        self.assertTrue(_is_video_entry({"fileName": "clip.MP4"}))
        self.assertFalse(_is_video_entry({"fileName": "img.JPG"}))

        self.assertTrue(_is_photo_entry({"fileType": 0}))
        self.assertFalse(_is_photo_entry({"fileType": 1}))
        self.assertTrue(_is_photo_entry({"fileName": "img.JPG"}))
        self.assertFalse(_is_photo_entry({"fileName": "clip.MP4"}))


if __name__ == "__main__":
    unittest.main()

