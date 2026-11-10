"""window_anchor: a passing failure does not use the occasion up (v0.6.23).

On the owner's PC a usage read that failed once (2026-11-07 01:05:15, `anchor.skip_unreadable`) stamped the reset it was
acting on as handled. An idle window teaches no new reset, so with no time picked nothing started again for 29 hours,
until someone used Codex. A passing failure now leaves the occasion open: looked at again every RETRY_EVERY, for a time
picked within SLOT_GRACE, for a reset seen five hours after it. The span's end is its one journal line.

Every usage read is a fake session and every request a stub process; every home is a temporary folder.

    CODEX_AR_EDITION=advanced PYTHONPATH="src;advanced/src;advanced/tests" python -m unittest test_advanced_window_anchor_retry
"""
from __future__ import annotations

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

from codex_auto_resume_advanced import surfaces  # noqa: E402
from codex_auto_resume_advanced.engine import anchor  # noqa: E402
from codex_auto_resume_advanced.registry import WINDOW_ANCHOR  # noqa: E402
from codex_auto_resume_advanced.vocabulary import OptionKey  # noqa: E402
from test_advanced_window_anchor import CAP, FIVE, AnchorCase  # noqa: E402

EVERY = anchor.RETRY_EVERY
SEVEN = anchor.encode_time(7, 0)


class RetryCase(AnchorCase):
    def slot(self):
        """07:00 picked, the failure in place before it comes due."""
        self.on(anchor_at_1=SEVEN, anchor_after_reset=2)

    def reset(self):
        """No time picked and a reset seen a minute and more ago: the owner's case."""
        self.on()
        self.seen = int(self.now) - anchor.AFTER_RESET - 5
        self.rt.state.stamp(CAP, OptionKey.ANCHOR_SEEN_RESET, self.seen)

    def to_reads(self, seconds):
        """Looks every LOOK_EVERY for `seconds`; how many usage reads they made."""
        before = len(self.world.calls)
        for _look in range(int(seconds // anchor.LOOK_EVERY)):
            self.look()
        return sum(1 for call in self.world.calls[before:] if call != "account/read")

    def done(self):
        return self.stamped(OptionKey.ANCHOR_SLOT_DONE), self.stamped(OptionKey.ANCHOR_RESET_DONE)

    def shown(self):
        return surfaces.status(self.rt)[CAP]


class AFailedReadTests(RetryCase):
    def test_a_failed_read_stamps_nothing_and_journals_nothing(self):
        """Fails with `_skip` stamping every reason: the owner's 01:05."""
        self.reset()
        self.world.broken = True
        self.look()
        self.assertEqual(self.done(), (None, None))
        self.assertEqual(self.codes(), [])
        self.assertEqual(len([line for line in self.lines if "trying again" in line]), 1)

    def test_it_is_tried_again_after_the_spacing_and_not_before(self):
        """Fails with no spacing: the tick looks every 15 s, and each look would open a session."""
        self.reset()
        self.world.broken = True
        self.look()
        self.assertEqual(self.to_reads(EVERY - 2 * anchor.LOOK_EVERY), 0, "not before the spacing")
        self.look(anchor.LOOK_EVERY * 3)
        self.assertEqual(len([call for call in self.world.calls if call == "account/read"]), 2, "one read a retry")

    def test_a_retry_that_reads_idle_starts_the_window(self):
        """Fails with the occasion used up by the first failure."""
        self.reset()
        self.world.broken = True
        self.look()
        self.world.broken = False
        self.look(EVERY + 1)
        self.run_through()
        self.assertEqual(len(self.world.started), 1)
        self.assertEqual(self.codes().count("anchor.started"), 1)
        self.assertEqual(self.done(), (None, self.seen))
        self.assertIsNone(self.shown()["retry_until"], "nothing is being tried any more")

    def test_a_reset_s_span_ends_five_hours_after_it_in_exactly_one_journal_line(self):
        """Fails with a line per try (sixty) or none."""
        self.reset()
        self.world.broken = True
        self.look()
        self.assertEqual(self.shown()["retry_until"], self.seen + FIVE)
        while self.now < self.seen + FIVE + 2 * EVERY:
            self.look(EVERY / 2)
        self.assertEqual(self.codes(), ["anchor.skip_unreadable"])
        self.assertEqual(self.done(), (None, self.seen))
        shown = self.shown()
        self.assertIsNone(shown["retry_until"])
        self.assertIsNotNone(shown["stopped_at"], "its card says it stopped")
        self.assertEqual(len([line for line in self.lines if "trying again" in line]), 1, "one line in the log too")

    def test_a_time_picked_is_tried_within_its_grace_and_ended_after_it(self):
        self.slot()
        self.world.broken = True
        self.look(45)
        occurrence = anchor.midnight(self.now) + 7 * 3600
        self.assertEqual(self.done(), (None, None))
        self.assertEqual(self.shown()["retry_until"], occurrence + anchor.SLOT_GRACE)
        while self.now < occurrence + anchor.SLOT_GRACE + EVERY:
            self.look(EVERY / 2)
        self.assertEqual(self.codes(), ["anchor.skip_unreadable"])
        self.assertEqual(self.done(), (occurrence, None))
        self.assertEqual(self.world.started, [])

    def test_a_word_the_span_ended_on_is_the_last_failure_s(self):
        self.slot()
        self.world.broken = True
        self.look(45)
        self.world.broken, self.world.signed = False, False
        occurrence = anchor.midnight(self.now) + 7 * 3600
        while self.now < occurrence + anchor.SLOT_GRACE + EVERY:
            self.look(EVERY / 2)
        self.assertEqual(self.codes(), ["anchor.skip_signed_out"])

    def test_a_reset_seen_long_ago_ends_at_once_with_one_line(self):
        self.reset()
        self.rt.state.stamp(CAP, OptionKey.ANCHOR_SEEN_RESET, self.seen - FIVE)
        self.world.broken = True
        self.look()
        self.assertEqual(self.codes(), ["anchor.skip_unreadable"])
        self.assertEqual(self.done(), (None, self.seen - FIVE))


class TheSecondReadTests(RetryCase):
    def test_a_second_read_that_fails_leaves_the_occasion_open(self):
        """Fails with `_second` still stamping on UNREADABLE."""
        self.reset()
        self.look()
        self.assertIsNotNone(self.code._pending, "the first read is held")
        self.world.broken = True
        self.look(anchor.STEADY_GAP)
        self.assertIsNone(self.code._pending)
        self.assertEqual((self.done(), self.codes()), ((None, None), []))
        self.world.broken = False
        self.look(EVERY + 1)
        self.run_through()
        self.assertEqual(len(self.world.started), 1)


class TheOtherWordsTests(RetryCase):
    def test_no_codex_told_is_held_and_tried_again(self):
        self.reset()
        told, self.told = self.told, None
        self.look()
        self.assertEqual((self.done(), self.codes()), ((None, None), []))
        self.told = told
        self.look(EVERY + 1)
        self.run_through()
        self.assertEqual(len(self.world.started), 1)

    def test_a_folder_not_empty_is_held_and_tried_again(self):
        self.reset()
        folder = anchor.folder_of(self.paths)
        folder.mkdir(parents=True, exist_ok=True)
        left = folder / "left.txt"
        left.write_text("x", encoding="utf-8")
        self.run_through()
        self.assertEqual((self.done(), self.codes(), self.world.started), ((None, None), [], []))
        left.unlink()
        self.look(EVERY + 1)
        self.run_through()
        self.assertEqual(len(self.world.started), 1)

    def test_a_state_that_cannot_be_read_is_held_and_tried_again(self):
        self.reset()
        with patch.object(anchor.WindowAnchor, "_before", lambda inner, view, now: "state"):
            self.look()
        self.assertEqual((self.done(), self.codes()), ((None, None), []))
        self.look(EVERY + 1)
        self.run_through()
        self.assertEqual(len(self.world.started), 1)

    def test_a_reset_that_fell_in_a_pause_is_still_there_when_recovery_resumes(self):
        """Fails with `paused` ending the occasion: a skip stamped it done just as a failed read did."""
        self.reset()
        self.view.enabled = False
        self.look()
        self.assertEqual((self.done(), self.codes(), self.world.calls), ((None, None), [], []))
        self.view.enabled = True
        self.look(EVERY + 1)
        self.run_through()
        self.assertEqual(len(self.world.started), 1)

    def test_a_person_signed_out_may_sign_in_again_within_the_span(self):
        self.reset()
        self.world.signed = False
        self.look()
        self.assertEqual((self.done(), self.codes()), ((None, None), []))
        self.world.signed = True
        self.look(EVERY + 1)
        self.run_through()
        self.assertEqual(len(self.world.started), 1)


class DefiniteAnswersTests(RetryCase):
    def test_a_window_that_runs_ends_the_occasion_at_once(self):
        """Fails with `running` held open too."""
        self.reset()
        self.world.running_until = int(self.now) + 3600
        self.world.used = 12.0
        self.look()
        self.assertEqual(self.codes(), ["anchor.skip_running"])
        self.assertEqual(self.done(), (None, self.seen))

    def test_a_retry_that_finds_the_window_running_ends_it_and_learns_the_new_reset(self):
        self.reset()
        self.world.broken = True
        self.look()
        self.world.broken = False
        self.world.running_until, self.world.used = int(self.now) + 3600, 12.0
        self.look(EVERY + 1)
        self.assertEqual(self.codes(), ["anchor.skip_running"])
        self.assertEqual(self.stamped(OptionKey.ANCHOR_SEEN_RESET), self.world.running_until)
        self.assertIsNone(self.shown()["retry_until"])
        self.assertIsNone(self.shown()["stopped_at"])

    def test_a_full_weekly_window_ends_a_time_picked_at_once(self):
        """Ending it is right: a time picked comes back by itself tomorrow."""
        self.slot()
        self.world.week = 100.0
        self.run_through()
        self.assertEqual(self.codes(), ["anchor.skip_weekly"])


class HeldToTheWeeklyResetTests(RetryCase):
    def full(self):
        """The weekly window full, its reset two days off, as the world reads it from now on."""
        self.world.week = 100.0
        self.weekly_reset = int(self.now) + 2 * anchor.DAY
        reply = self.world.reply

        def answered():
            found = reply()
            found["rateLimitsByLimitId"]["codex"]["secondary"]["resetsAt"] = self.weekly_reset
            return found
        self.world.reply = answered

    def test_a_reset_under_a_full_weekly_window_is_held_past_five_hours_and_starts_once_it_is_free(self):
        """Fails with `weekly` ending the occasion at once: the chain's end the owner's first report asked about."""
        self.reset()
        self.full()
        self.look()
        self.assertEqual((self.done(), self.codes()), ((None, None), []))
        self.look(FIVE + EVERY)
        self.assertEqual((self.done(), self.codes(), self.world.started), ((None, None), [], []), "past a reset's five hours")
        self.now = float(self.weekly_reset - anchor.LOOK_EVERY)
        self.world.week = 3.0
        self.look(anchor.LOOK_EVERY + EVERY)
        self.run_through()
        self.assertEqual(len(self.world.started), 1)

    def test_it_ends_with_the_weekly_word_only_past_that_reset(self):
        self.reset()
        self.full()
        self.look()
        self.now = float(self.weekly_reset - EVERY)
        self.look(1)
        self.assertEqual(self.codes(), [])
        self.now = float(self.weekly_reset + 3 * EVERY)
        self.look(1)
        self.look(EVERY + 1)
        self.assertEqual(self.codes(), ["anchor.skip_weekly"])
        self.assertEqual(self.done(), (None, self.seen))

    def test_with_no_weekly_reset_read_it_ends_at_once(self):
        self.reset()
        self.world.week = 100.0
        reply = self.world.reply

        def answered():
            found = reply()
            del found["rateLimitsByLimitId"]["codex"]["secondary"]["resetsAt"]
            return found
        self.world.reply = answered
        self.look()
        self.assertEqual(self.codes(), ["anchor.skip_weekly"])


class StartThatCouldNotBeMadeTests(RetryCase):
    def test_a_request_that_could_not_be_started_is_held_and_tried_again(self):
        """Fails with `failed` ending the occasion: `start_request` raised once and the reset was used up."""
        self.reset()
        with patch.object(anchor, "start_request", side_effect=OSError("no")):
            self.run_through()
        self.assertEqual((self.done(), self.codes()), ((None, None), []))
        self.assertIsNone(self.stamped(OptionKey.ANCHOR_STARTED_AT))
        self.look(EVERY + 1)
        self.run_through()
        self.assertEqual(len(self.world.started), 1)

    def test_it_ends_in_one_failed_line_past_its_span(self):
        self.reset()
        with patch.object(anchor, "start_request", side_effect=OSError("no")):
            self.run_through()
            while self.now < self.seen + FIVE + 2 * EVERY:
                self.look(EVERY / 2)
                self.run_through(2)
        self.assertEqual(self.codes(), ["anchor.failed"])


class HeldForTheCeilingTests(RetryCase):
    def test_a_reset_at_its_ceiling_is_held_for_a_day_and_starts_once_it_clears(self):
        """Fails with `ceiling` ending a reset's occasion: five starts in a day ended the chain."""
        self.reset()
        for _start in range(WINDOW_ANCHOR.ceilings.per_day):
            self.assertTrue(self.rt.state.counted(CAP, "started", at=self.now - 3600))
        self.look()
        self.look(FIVE + EVERY)
        self.assertEqual((self.done(), self.codes().count("anchor.skip_ceiling"), self.world.calls), ((None, None), 0, []))
        self.now = float(self.seen + anchor.DAY - EVERY)
        self.run_through()
        self.assertEqual(len(self.world.started), 1)

    def test_a_ceiling_that_never_clears_ends_in_one_line_a_day_after(self):
        self.reset()
        real = self.rt.state.counted_since
        with patch.object(self.rt.state, "counted_since", lambda capability, code, since: 99):
            self.look()
            self.now = float(self.seen + anchor.DAY + EVERY)
            self.look(1)
        self.assertIsNotNone(real)
        self.assertEqual(self.codes(), ["anchor.skip_ceiling"])

    def test_a_time_picked_at_its_ceiling_ends_at_once(self):
        self.slot()
        for _start in range(WINDOW_ANCHOR.ceilings.per_day):
            self.assertTrue(self.rt.state.counted(CAP, "started"))
        self.look(45)
        self.assertEqual(self.codes().count("anchor.skip_ceiling"), 1)


class NoFloodTests(RetryCase):
    def test_a_span_of_failures_writes_one_journal_line_and_a_stamp_only_when_it_changes(self):
        self.reset()
        self.world.broken = True
        stamps = []
        real = anchor.WindowAnchor._stamp

        def noted(inner, key, value):
            stamps.append(str(key))
            return real(inner, key, value)
        with patch.object(anchor.WindowAnchor, "_stamp", noted):
            while self.now < self.seen + FIVE + 2 * EVERY:
                self.look(EVERY / 2)
        self.assertEqual(len(self.codes()), 1)
        self.assertEqual(stamps.count(str(OptionKey.ANCHOR_RETRY_UNTIL)), 1)
        self.assertLessEqual(len([call for call in self.world.calls if call != "account/read"]), FIVE // EVERY + 2,
                             "at most a read a retry, no learning reads besides")

    def test_an_end_whose_stamp_cannot_be_written_is_still_one_line(self):
        self.reset()
        self.world.broken = True
        self.look()
        with patch.object(anchor.WindowAnchor, "_stamp", lambda inner, key, value: None):
            while self.now < self.seen + FIVE + 2 * EVERY:
                self.look(EVERY / 2)
        self.assertEqual(self.codes(), ["anchor.skip_unreadable"])


class CeilingsStillCountTests(RetryCase):
    def test_a_retry_counts_under_its_ceiling_as_any_occasion_does(self):
        self.reset()
        self.world.broken = True
        self.look()
        self.world.broken = False
        for _start in range(WINDOW_ANCHOR.ceilings.per_day):
            self.assertTrue(self.rt.state.counted(CAP, "started"))
        self.run_through()
        self.look(EVERY + 1)
        self.run_through()
        self.assertEqual(self.world.started, [])


if __name__ == "__main__":
    unittest.main()
