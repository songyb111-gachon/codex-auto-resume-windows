"""v0.6.23 second round M6 (limits R4): with the weekly window full, window_anchor looks again when it resets, not every
RETRY_EVERY.

A reset seen under a full weekly window was held to that window's reset - right, so the chain does not end - but looked
at every RETRY_EVERY (300 s) meanwhile, and each look opened a Codex session for account/read and rateLimits/read: up to
about 2,000 sessions over a week, where the comment said "sixty at the very most". Now the one look is a little past the
weekly reset, and the card says no "trying again every 5 minutes" in between.

The clock is the test's and every usage read a fake session it counts (test_advanced_window_anchor.AnchorCase).

    CODEX_AR_EDITION=advanced PYTHONPATH="src;advanced/src;advanced/tests" python -m unittest test_advanced_window_anchor_weekly_looks
"""
from __future__ import annotations

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from codex_auto_resume_advanced.engine import anchor  # noqa: E402
from test_advanced_window_anchor import FIVE  # noqa: E402
from test_advanced_window_anchor_retry import EVERY, RetryCase  # noqa: E402

DAY = anchor.DAY


class UnderAFullWeeklyWindow(RetryCase):
    def full(self, days=2):
        """The weekly window full, its reset `days` off, as the world reads it from now on."""
        self.world.week = 100.0
        self.weekly_reset = int(self.now) + days * DAY
        reply = self.world.reply

        def answered():
            found = reply()
            found["rateLimitsByLimitId"]["codex"]["secondary"]["resetsAt"] = self.weekly_reset
            return found
        self.world.reply = answered

    def reads(self):
        return sum(1 for call in self.world.calls if call != "account/read")

    def step_to(self, until, step=EVERY / 2):
        """Looks every `step` seconds of the test's clock up to `until` - each a tick, as the watcher's would be."""
        while self.now + step <= until:
            self.look(step)

    def test_no_session_is_opened_before_the_weekly_reset(self):
        """Fails with the old hold: a read every RETRY_EVERY, 576 over the two days."""
        self.reset()
        self.full(days=2)
        self.look()
        self.assertEqual(self.reads(), 1, "the read that found the weekly window full")
        self.step_to(self.weekly_reset - 60)
        self.assertEqual(self.reads(), 1)
        self.assertEqual((self.done(), self.codes(), self.world.started), ((None, None), [], []), "still held, not ended")

    def test_the_stated_bound_holds_for_a_week(self):
        """A reset seen opens at most sixty sessions in its five hours and one more past a full weekly window's reset."""
        self.reset()
        self.world.broken = True                           # a passing failure first: retried every RETRY_EVERY
        self.look()
        self.step_to(self.now + 3600)
        self.world.broken = False
        self.full(days=6)
        self.step_to(self.weekly_reset + 3 * EVERY, step=EVERY)
        self.assertLessEqual(self.reads(), FIVE // EVERY + 1)
        self.assertEqual(self.codes(), ["anchor.skip_weekly"], "ended past that reset in its one line")

    def test_once_the_weekly_window_resets_the_window_is_started(self):
        """A guard: the chain does not end at a full weekly window (it passes with the fix reverted)."""
        self.reset()
        self.full(days=2)
        self.look()
        self.now = float(self.weekly_reset - anchor.LOOK_EVERY)
        self.world.week = 3.0
        self.look(anchor.LOOK_EVERY + EVERY)
        self.run_through()
        self.assertEqual(len(self.world.started), 1)

    def test_the_card_says_no_retrying_every_five_minutes_meanwhile(self):
        """Fails with the old card line: "tries again every 5 minutes until" the weekly reset, two days off."""
        self.reset()
        self.full(days=2)
        self.look()
        self.assertIsNone(self.shown()["retry_until"])
        self.assertEqual([line for line in self.lines if "trying again every" in line], [])
        self.assertEqual(len([line for line in self.lines if "weekly limit is reached" in line]), 1)

    def test_a_ceilings_hold_still_reads_nothing(self):
        """A guard: a reset held for its ceiling looks every RETRY_EVERY but opens no session (`_before` first)."""
        from codex_auto_resume_advanced.registry import WINDOW_ANCHOR
        from test_advanced_window_anchor import CAP
        self.reset()
        for _start in range(WINDOW_ANCHOR.ceilings.per_day):
            self.assertTrue(self.rt.state.counted(CAP, "started", at=self.now - 3600))
        self.look()
        self.step_to(self.now + FIVE)
        self.assertEqual(self.reads(), 0)


if __name__ == "__main__":
    unittest.main()
