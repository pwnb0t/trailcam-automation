import os
import sys
import time
import unittest
from datetime import datetime, timezone

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from src.sync.organize import _parse_media_time_unix  # noqa: E402


class TestMediaTimeParse(unittest.TestCase):
    def setUp(self):
        self._orig_tz = os.environ.get("TZ")

    def tearDown(self):
        if self._orig_tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = self._orig_tz
        time.tzset()

    def test_trailcam_local_epoch_keeps_wall_clock_fields(self):
        os.environ["TZ"] = "America/Chicago"
        time.tzset()

        # TrailCam mediaTime example: local wall-clock 2026-04-05 00:03:50
        # encoded as if that wall-clock were UTC.
        ts = int(datetime(2026, 4, 5, 0, 3, 50, tzinfo=timezone.utc).timestamp())

        dt = _parse_media_time_unix(ts)
        self.assertIsNotNone(dt)
        assert dt is not None
        self.assertEqual(dt.year, 2026)
        self.assertEqual(dt.month, 4)
        self.assertEqual(dt.day, 5)
        self.assertEqual(dt.hour, 0)
        self.assertEqual(dt.minute, 3)
        self.assertEqual(dt.second, 50)

    def test_invalid_media_time_returns_none(self):
        self.assertIsNone(_parse_media_time_unix("not-a-number"))


if __name__ == "__main__":
    unittest.main()
