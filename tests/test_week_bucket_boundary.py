import os
import sys
import unittest
from datetime import datetime

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from src.sync.organize import _week_bucket_label  # noqa: E402


class TestWeekBucketBoundary(unittest.TestCase):
    def test_sunday_boundary_before_rollover_stays_current_iso_week(self):
        # Sunday before 11:00 should still be in the current ISO week bucket.
        dt = datetime.fromisoformat("2026-03-01T10:59:59-06:00")
        self.assertEqual(_week_bucket_label(dt, boundary_weekday=6, boundary_hour_local=11), "2026-09")

    def test_sunday_boundary_at_rollover_goes_next_iso_week(self):
        # At/after Sunday 11:00 should be in next ISO week bucket.
        dt = datetime.fromisoformat("2026-03-01T11:00:00-06:00")
        self.assertEqual(_week_bucket_label(dt, boundary_weekday=6, boundary_hour_local=11), "2026-10")

    def test_non_boundary_days_follow_normal_iso_week(self):
        # Saturday night before rollover still maps to the current week.
        sat = datetime.fromisoformat("2026-02-28T23:00:00-06:00")
        self.assertEqual(_week_bucket_label(sat, boundary_weekday=6, boundary_hour_local=11), "2026-09")

        # Monday after rollover remains in that next week.
        mon = datetime.fromisoformat("2026-03-02T00:10:00-06:00")
        self.assertEqual(_week_bucket_label(mon, boundary_weekday=6, boundary_hour_local=11), "2026-10")


if __name__ == "__main__":
    unittest.main()
