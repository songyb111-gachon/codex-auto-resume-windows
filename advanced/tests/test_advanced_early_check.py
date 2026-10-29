# ADVANCED-EDITION-CODE: in the advanced edition's tree, never the standard one's.
"""early_reset on Pending (v0.6.19, issue #50): its line and Check now.

Held against core's own engine, store and simulated Codex home (takingcase.py), as test_advanced_early_reset is: Check
now opens the next early look at once, past the five minutes between two, and that reading is one of the two - which
still have to be five minutes apart; clicks are one request; a still-limited, unknown or failed reading releases
nothing; nothing is sent without every gate; with no watcher nothing stays asked and the answer says so; it is refused
unless early_reset stands on; and the line says when it last read, what it read and whether anything went on. A Check
now request left in the standard edition's state changes nothing there.

    PYTHONPATH=src;advanced/src;tests python -m unittest discover -s advanced/tests -p test_advanced_early_check.py
"""
from __future__ import annotations

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_advanced_early_reset import NO_USAGE, SPACING, USAGE, EarlyCase  # noqa: E402
from codex_auto_resume_advanced.control import earlycheck  # noqa: E402
from codex_auto_resume_advanced.vocabulary import OptionKey, Refusal  # noqa: E402
from test_engine import T1  # noqa: E402

UNKNOWN = {"available": None, "reset_at": None, "limit_type": None, "reason": "unknown"}
WAKE = "codex_auto_resume_advanced.control.sendnow.wake"


class CheckCase(EarlyCase):
    def setUp(self):
        super().setUp()
        self.reads = []
        real = self.h.backend.usage
        self.h.backend.usage = lambda: (self.reads.append(self.h.now), real())[1]

    def check(self, plug, running=True):
        with patch(WAKE, lambda _paths: running):
            return earlycheck.check(plug.runtime, store=self.h.store)

    def line(self, plug):
        return earlycheck.view(plug.runtime, store=self.h.store).get("early_check")

    def sends(self):
        return len(self.h.backend.send_calls)


class CheckNowTests(CheckCase):
    def test_check_now_reads_at_once_and_that_reading_is_one_of_the_two(self):
        """Fails with Check now reverted (core's or the capability's half): the yes waits for the next five minutes, and
        so does the second - nothing is sent at the time a Check now made possible."""
        self.waiting()
        plug = self.armed()
        self.h.backend.usage_result = dict(NO_USAGE)
        self.h.tick(advance=60)                              # an early look: still limited
        started = self.h.now
        self.assertEqual(self.line(plug)["read"], "still_limited")
        self.h.backend.usage_result = dict(USAGE)
        self.h.tick(advance=60)
        self.assertEqual(len(self.reads), 1, "nothing is read between two looks of its own")
        self.assertEqual(self.check(plug)["check"], earlycheck.ASKED)
        self.h.tick(advance=1)                               # read at once: a first yes
        self.assertEqual(len(self.reads), 2)
        self.assertEqual(self.sends(), 0, "one yes never sends")
        first = self.h.now
        shown = self.line(plug)
        self.assertEqual((shown["read"], shown["available_at"], shown["confirm_at"], shown["lifted"]),
                         ("available", int(first), int(first) + SPACING, False))
        self.h.tick(advance=SPACING - 2)
        self.assertEqual(self.sends(), 0, "the second reading is at least five minutes after it")
        self.h.tick(advance=2)
        self.assertEqual(self.sends(), 1)
        self.assertLess(self.h.now, started + 2 * SPACING, "sooner than two looks of its own would have gone")
        self.assertTrue(self.line(plug)["lifted"])

    def test_clicks_are_one_request_and_a_reading_just_made_is_the_one_it_gets(self):
        self.waiting()
        plug = self.armed()
        self.h.tick(advance=60)                              # a look of its own
        self.assertEqual(self.check(plug)["check"], earlycheck.COALESCED, "within one reading's life: that reading")
        self.h.tick(advance=60)
        reads = len(self.reads)
        self.assertEqual(self.check(plug)["check"], earlycheck.ASKED)
        self.assertEqual(self.check(plug)["check"], earlycheck.COALESCED)
        self.assertEqual(self.check(plug)["check"], earlycheck.COALESCED)
        self.h.tick(advance=1)
        self.h.tick(advance=5)
        self.assertEqual(len(self.reads), reads + 1, "three clicks, one reading")
        self.assertFalse(self.h.store.early_check_asked(self.h.now), "taken by the look it opened")
        self.assertIsNone(plug.runtime.state.stamped(self.cap, OptionKey.CHECK_ASKED))
        self.assertFalse(self.line(plug)["asked"])


class NothingReleasedTests(CheckCase):
    def test_a_still_limited_unknown_or_failed_reading_releases_nothing(self):
        for name, answer in (("still limited", NO_USAGE), ("unknown", UNKNOWN), ("failed", None)):
            with self.subTest(name):
                self.setUp()
                self.waiting()
                plug = self.armed()
                self.h.backend.usage_result = dict(NO_USAGE)
                self.h.tick(advance=60)
                self.h.tick(advance=60)
                if answer is None:
                    def failing():
                        raise RuntimeError("no answer")
                    self.h.backend.usage = failing
                else:
                    self.h.backend.usage_result = dict(answer)
                self.assertEqual(self.check(plug)["check"], earlycheck.ASKED)
                for _ in range(3):
                    self.h.tick(advance=SPACING)
                self.assertEqual(self.sends(), 0)
                self.assertEqual(self.h.record()["state"], "waiting_reset")
                self.assertIsNone(plug.runtime.state.stamped(self.cap, OptionKey.AVAILABLE_AT))
                self.assertIn(self.line(plug)["read"], ("still_limited", "unknown", "not_read"))

    def test_nothing_is_sent_without_every_gate(self):
        """Two yeses, the second at a Check now, and the conversation not open in the app: it waits (A11)."""
        self.waiting()
        plug = self.armed()
        self.h.tick(advance=60)                              # a first yes
        self.h.backend.loaded_map[T1] = "notLoaded"
        self.h.tick(advance=SPACING - 30)
        self.assertEqual(self.check(plug)["check"], earlycheck.ASKED)
        for _ in range(3):
            self.h.tick(advance=SPACING)
        self.assertEqual(self.sends(), 0)
        self.assertEqual(self.line(plug)["read"], "not_read", "an earlier gate held it before usage was read")

    def test_with_no_watcher_running_nothing_stays_asked_and_it_says_so(self):
        self.waiting()
        plug = self.armed()
        self.h.tick(advance=60)
        self.h.tick(advance=60)
        self.assertEqual(self.check(plug, running=False)["check"], earlycheck.NOT_RUNNING)
        self.assertFalse(self.h.store.early_check_asked(self.h.now))
        self.assertIsNone(plug.runtime.state.stamped(self.cap, OptionKey.CHECK_ASKED))
        reads = len(self.reads)
        self.h.tick(advance=1)
        self.assertEqual(len(self.reads), reads)

    def test_refused_unless_it_stands_on_and_nothing_to_check_without_a_wait(self):
        plug = self.armed()
        self.assertEqual(self.check(plug)["check"], earlycheck.NOTHING_WAITS)
        self.assertFalse(self.h.store.early_check_asked(self.h.now))
        watched = self.armed(state="shadow")
        self.waiting()
        self.assertEqual(self.check(watched), {"done": False, "refusal": Refusal.NOT_ON})
        self.assertEqual(earlycheck.view(watched.runtime, store=self.h.store), {}, "no line while it only watches")

    def test_the_status_carries_the_line_only_while_it_stands_on(self):
        """Fails with the status's part reverted: Pending is never told what early_reset did."""
        from codex_auto_resume_advanced import surfaces
        self.waiting()
        off = self.advanced()
        self.assertNotIn("early_check", surfaces.status(off.runtime))
        plug = self.armed()
        self.h.tick(advance=60)
        line = surfaces.status(plug.runtime).get("early_check")
        self.assertIsNotNone(line)
        self.assertEqual(line["checked_at"], int(self.h.now))

    def test_a_request_in_the_standard_editions_state_changes_nothing(self):
        expected = self.fresh()
        self.waiting(expected)
        reads = []
        real = expected.backend.usage
        expected.backend.usage = lambda: (reads.append(expected.now), real())[1]
        expected.tick(advance=60)
        self.assertTrue(expected.store.ask_early_check(expected.now))
        expected.tick(advance=1)
        self.assertEqual((reads, len(expected.backend.send_calls)), ([], 0))
        self.assertTrue(expected.store.early_check_asked(expected.now), "never taken: no early look in this edition")


if __name__ == "__main__":
    unittest.main()
