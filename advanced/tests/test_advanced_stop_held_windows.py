"""The forced stop's continuation after a reset waits while another of its windows still holds (v0.6.18, the advanced
audit's R2): the five-hour window stopped at 97% resets while the weekly one is still held at 98% - the pause's own
promise, "no further continuation from this product until that window resets", holds the stop's own turn too.
"""
from __future__ import annotations

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_advanced_usagestop import StopCase  # noqa: E402


class HeldWindowTests(StopCase):
    def weekly(self, plug, percent, reset):
        plug.runtime.state.save_meter([{"bucket": "codex", "window_minutes": 300, "used_percent": 1,
                                        "reset_at": self.reset + 5 * 3600},
                                       {"bucket": "codex", "window_minutes": 10080, "used_percent": percent,
                                        "reset_at": reset}], at=self.h.now)

    def test_no_continuation_starts_while_the_weekly_window_still_holds(self):
        """Fails with the hold check reverted: the turn was started through the app while holding() was True."""
        plug, turn = self.running()
        self.h.tick(advance=61)
        self.h.tick(advance=61)
        self.after_reset(plug, turn)
        weekly_reset = int(self.h.now) + 2 * 86400
        self.weekly(plug, 98, weekly_reset)
        for _ in range(3):
            self.h.tick(advance=61)
        self.assertTrue(self.code(plug).holding(), "the weekly window is held")
        self.assertEqual(self.starts, [], "nothing of its own starts while a window it holds has not reset")
        # The weekly window resets: the continuation goes, once.
        self.h.now = weekly_reset + 120
        plug.runtime.state.save_meter([{"bucket": "codex", "window_minutes": 300, "used_percent": 1,
                                        "reset_at": int(self.h.now) + 3600},
                                       {"bucket": "codex", "window_minutes": 10080, "used_percent": 1,
                                        "reset_at": int(self.h.now) + 7 * 86400}], at=self.h.now)
        for _ in range(3):
            self.h.tick(advance=61)
        self.assertEqual(len(self.starts), 1)


if __name__ == "__main__":
    unittest.main()
