"""The pace of a usage window (v0.6.19, usage_analytics; engine/analytics.pace): a least-squares slope over the last
hour of the meter's samples of that window since its last reset, an estimate only with three samples over fifteen
minutes and a rising slope - and never one past the window's reset.

    PYTHONPATH=src;advanced/src python -m unittest discover -s advanced/tests -p test_advanced_pace.py
"""
from __future__ import annotations

import unittest

from codex_auto_resume_advanced.engine.analytics import PACE_SAMPLES, PACE_SPAN, pace

NOW = 1_800_000_000
RESET = NOW + 4 * 3600


def row(used, reset=RESET, minutes=300, bucket="codex"):
    return {"bucket": bucket, "minutes": minutes, "used_percent": used, "reset_at": reset}


def sample(ago, used, reset=RESET, minutes=300, bucket="codex"):
    return {"bucket": bucket, "minutes": minutes, "at": NOW - ago, "used_percent": used, "reset_at": reset}


class PaceTests(unittest.TestCase):
    def test_a_steady_climb_gives_when_it_would_be_full(self):
        # 10 points in 30 minutes: 20 points an hour; at 60, full in two hours.
        samples = [sample(1800, 50.0), sample(900, 55.0), sample(0, 60.0)]
        found = pace(samples, row(60.0), NOW)
        self.assertTrue(found["enough"])
        self.assertEqual(found["change_hour"], 10.0)
        self.assertEqual(found["eta"], NOW + 2 * 3600)
        self.assertEqual((found["minutes"], found["bucket"], found["reset_at"]), (300, "codex", RESET))

    def test_the_slope_is_least_squares_over_every_sample(self):
        samples = [sample(1800, 40.0), sample(1200, 46.0), sample(600, 44.0), sample(0, 52.0)]
        found = pace(samples, row(52.0), NOW)
        # Fitted: 10200 / 1800000 points a second (20.4 an hour) - 48 points to go is 8470.6 seconds.
        self.assertEqual(found["eta"], NOW + 8470)

    def test_fewer_than_three_samples_or_under_fifteen_minutes_give_no_estimate(self):
        self.assertEqual(PACE_SAMPLES, 3)
        self.assertEqual(PACE_SPAN, 900)
        two = pace([sample(1800, 50.0), sample(0, 60.0)], row(60.0), NOW)
        self.assertEqual((two["enough"], two["eta"]), (False, None))
        self.assertEqual(two["change_hour"], 10.0)
        short = pace([sample(800, 50.0), sample(400, 55.0), sample(0, 60.0)], row(60.0), NOW)
        self.assertEqual((short["enough"], short["eta"]), (False, None))

    def test_no_estimate_where_it_would_come_after_the_reset(self):
        samples = [sample(1800, 50.0), sample(900, 51.0), sample(0, 52.0)]
        found = pace(samples, row(52.0, reset=NOW + 3600), NOW)
        self.assertTrue(found["enough"])
        self.assertIsNone(found["eta"])

    def test_a_flat_or_falling_window_gives_no_estimate(self):
        for values in ((50.0, 50.0, 50.0), (60.0, 55.0, 50.0)):
            samples = [sample(1800, values[0]), sample(900, values[1]), sample(0, values[2])]
            with self.subTest(values=values):
                self.assertIsNone(pace(samples, row(values[2]), NOW)["eta"])

    def test_only_this_window_s_samples_since_its_last_reset_and_in_the_last_hour_count(self):
        samples = [sample(3000, 0.0), sample(1800, 50.0), sample(900, 55.0), sample(0, 60.0),
                   sample(600, 99.0, reset=RESET - 18000),          # the window before the last reset
                   sample(600, 1.0, minutes=10080),                 # the weekly window
                   sample(600, 1.0, bucket="premium"),              # another bucket's
                   sample(7200, 0.0)]                               # over an hour ago
        found = pace(samples, row(60.0), NOW)
        # The first sample (50 minutes ago) is in the hour; it moves the fit.
        self.assertTrue(found["enough"])
        self.assertEqual(found["change_hour"], 60.0)
        self.assertIsNotNone(found["eta"])
        alone = pace([sample(1800, 50.0), sample(900, 55.0), sample(0, 60.0)], row(60.0), NOW)
        self.assertNotEqual(found["eta"], alone["eta"])
        # A window that reset 20 minutes ago reads only the samples after it.
        recent = pace(samples, row(60.0, reset=NOW + 300 * 60 - 1200), NOW)
        self.assertFalse(recent["enough"])

    def test_no_reading_no_number(self):
        found = pace([], row(None, reset=None), NOW)
        self.assertEqual((found["used"], found["change_hour"], found["eta"], found["enough"]), (None, None, None, False))


if __name__ == "__main__":
    unittest.main()
