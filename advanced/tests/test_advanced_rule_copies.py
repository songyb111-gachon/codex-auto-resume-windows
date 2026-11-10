"""The window's copy of a rule the advanced engine holds, compared as text: the window cannot import a Python constant."""
from __future__ import annotations

from pathlib import Path
import re
import unittest

from codex_auto_resume_advanced.engine import anchor

ANCHOR_WINDOW = Path(__file__).resolve().parents[1] / "gui" / "AdvancedAnchor.cs"


class AnchorTimeEncoding(unittest.TestCase):
    """A time of day is held as a whole number shifted from the off choice; both sides must shift it alike."""

    def test_the_window_shifts_a_time_as_the_engine_does(self):
        source = ANCHOR_WINDOW.read_text(encoding="utf-8")
        shift = re.search(r"const int AnchorShift = (\d+);", source)
        self.assertIsNotNone(shift, "the window has no AnchorShift")
        self.assertEqual(int(shift.group(1)), anchor.TIME_SHIFT)

    def test_the_last_minute_of_the_day_is_the_engines_top_of_range(self):
        source = ANCHOR_WINDOW.read_text(encoding="utf-8")
        self.assertIn("1439 + AnchorShift", source)
        self.assertEqual(anchor.TIME_RANGE[1], 1439 + anchor.TIME_SHIFT)


if __name__ == "__main__":
    unittest.main()
