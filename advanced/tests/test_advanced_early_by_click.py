# ADVANCED-EDITION-CODE: in the advanced edition's tree, never the standard one's.
"""v0.6.19 (the owner's decision of 2026-10-24): with early_reset on, the reading a person's Rescan - or Retry now - asks
for is one of early reset's two readings; Check now, which asked for that probe alone, is gone.

The window asks it in two halves: the bridge's `rescan` asks core for a reading of each recovery that waits for a usage
reset (store.ask_usage_check, as a Rescan), and the advanced window's UsageAsked asks the capability for its probe
(advanced-early-check). Held here against core's own engine, store and simulated Codex home (takingcase.py), as
test_advanced_early_check is: the click's look reads usage once - core's request and the probe it opens share the one
reading - and that look is early reset's probe (its time is the click's, and its five minutes start from it).

    PYTHONPATH=src;advanced/src;tests python -m unittest discover -s advanced/tests -p test_advanced_early_by_click.py
"""
from __future__ import annotations

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_advanced_early_reset import NO_USAGE, SPACING, EarlyCase  # noqa: E402
from codex_auto_resume_advanced.control import earlycheck  # noqa: E402

WAKE = "codex_auto_resume_advanced.control.sendnow.wake"


class ClickCountsTests(EarlyCase):
    def setUp(self):
        super().setUp()
        self.reads = []
        real = self.h.backend.usage
        self.h.backend.usage = lambda: (self.reads.append(self.h.now), real())[1]

    def click(self, plug, key):
        """A Rescan in the advanced window: core's request for the recovery, then the capability's probe."""
        self.assertTrue(self.h.store.ask_usage_check(key, self.h.now, source="rescan"))
        with patch(WAKE, lambda _paths: True):
            return earlycheck.check(plug.runtime, store=self.h.store)

    def test_the_clicks_reading_is_early_resets_probe_and_is_read_once(self):
        """Fails with core's early window reading afresh for it (engine/relaxed.py before v0.6.19): two readings at the
        click's look. The window's half, UsageAsked, is held by test_advanced_page_early."""
        key = self.waiting()["interruption_id"]
        plug = self.armed()
        self.h.backend.usage_result = dict(NO_USAGE)
        self.h.tick(advance=60)                              # an early look of its own: still limited
        own = earlycheck.view(plug.runtime, store=self.h.store)["early_check"]["checked_at"]
        self.h.tick(advance=60)
        before = len(self.reads)
        self.assertEqual(self.click(plug, key)["check"], earlycheck.ASKED)
        self.h.tick(advance=1)
        self.assertEqual(len(self.reads) - before, 1, "core's request and early reset's probe share one reading (C9)")
        shown = earlycheck.view(plug.runtime, store=self.h.store)["early_check"]
        self.assertEqual(shown["checked_at"], int(self.h.now), "the click's look is early reset's probe")
        self.assertGreater(shown["checked_at"], own)
        self.assertEqual(shown["read"], "still_limited")
        check = [event for event in self.h.events(key) if event == "usage_checked"]
        self.assertEqual(len(check), 1, "the Rescan's own reading is journalled for the row")
        self.assertEqual(len(self.h.backend.send_calls), 0)
        # Its five minutes start at the click: nothing more is read before them.
        self.h.tick(advance=SPACING - 30)
        self.assertEqual(len(self.reads) - before, 1)


if __name__ == "__main__":
    unittest.main()
