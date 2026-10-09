"""Counting the usage windows' resets and fills (engine/resetwatch.py): the five steps, a rule's adoption,
a gap, a window Codex stopped reporting, and when this edition reads usage itself.

Run from the repository root:

    PYTHONPATH=src python -m unittest discover -s advanced/tests
"""
from __future__ import annotations

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import advancedcase as ac  # noqa: E402
from codex_auto_resume_advanced.engine import resetwatch  # noqa: E402
from codex_auto_resume_advanced.engine.resetwatch import CLOSE_AFTER, POLL, READ_SPACING, TOL, Watch, advance  # noqa: E402
from codex_auto_resume_advanced.registry import Registry  # noqa: E402
from codex_auto_resume_advanced.state import AdvancedState  # noqa: E402
from codex_auto_resume_advanced.vocabulary import RuleReason, RuleState  # noqa: E402

FIVE = ("codex", 300)
T = 1_800_000_000
RESET = T + 3 * 3600


def window(used, reset_at, minutes=300, bucket="codex"):
    return {"bucket": bucket, "window": "primary", "used_percent": used, "window_minutes": minutes,
            "reset_at": reset_at}


def usage(*windows):
    """Codex's reply, as the reader hands it back: the windows the tracker reads, and a count."""
    by_slot = {}
    for found, slot in zip(windows, ("primary", "secondary")):
        by_slot[slot] = {"usedPercent": found["used_percent"], "windowDurationMins": found["window_minutes"],
                         "resetsAt": found["reset_at"]}
    return {"rateLimitsByLimitId": {"codex": by_slot}, "rateLimitResetCredits": {"availableCount": 1, "credits": []}}


class StepTests(unittest.TestCase):
    """`advance`, pure: one successful reading applied to one family's row."""

    def test_an_idle_window_opens_nothing_whatever_reset_time_it_shows(self):
        row, events = advance(resetwatch.blank(*FIVE), window(0, RESET), T)
        self.assertEqual((row["open_reset_at"], row["resets"], row["hits"], events), (None, 0, 0, ()))

    def test_a_used_window_opens_fills_and_closes_by_time(self):
        row, events = advance(resetwatch.blank(*FIVE), window(40, RESET), T)
        self.assertEqual((row["open_reset_at"], events), (RESET, ("opened",)))
        row, events = advance(row, window(100, RESET), T + 60)
        self.assertEqual((row["hits"], row["open_full"], events), (1, True, ("hit",)))
        row, events = advance(row, window(100, RESET), T + 120)
        self.assertEqual((row["hits"], events), (1, ()), "one fill is counted once")
        row, events = advance(row, window(0, None), RESET + CLOSE_AFTER)
        self.assertEqual((row["resets"], row["last_closed_at"], row["open_reset_at"], events), (1, RESET, None, ("reset",)))

    def test_a_window_replaced_early_is_one_reset_and_the_new_one_may_open(self):
        row = advance(resetwatch.blank(*FIVE), window(100, RESET), T)[0]
        row, events = advance(row, window(5, T + 600 + 5 * 3600), T + 600)
        self.assertEqual((row["resets"], row["open_reset_at"], events), (1, T + 600 + 5 * 3600, ("reset", "opened")))
        row = advance(resetwatch.blank(*FIVE), window(100, RESET), T)[0]
        row, events = advance(row, window(0, None), T + 600)          # a credit reset it, and nothing is used since
        self.assertEqual((row["resets"], row["open_reset_at"], events), (1, None, ("reset",)))
        moved = advance(advance(resetwatch.blank(*FIVE), window(40, RESET), T)[0], window(40, RESET + TOL), T + 60)
        self.assertEqual((moved[0]["resets"], moved[1]), (0, ()), "a reset time that moves within TOL is the same window")

    def test_with_step_two_off_a_window_ends_only_by_time(self):
        row = advance(resetwatch.blank(*FIVE), window(100, RESET), T)[0]
        row, events = advance(row, window(0, None), T + 600, early=False)
        self.assertEqual((row["resets"], row["open_reset_at"], events), (0, RESET, ()))
        row, events = advance(row, window(10, RESET + 5 * 3600), RESET + CLOSE_AFTER, early=False)
        self.assertEqual((row["resets"], row["open_reset_at"], events), (1, RESET + 5 * 3600, ("reset", "opened")))

    def test_our_own_reset_closes_the_window_once(self):
        row = advance(resetwatch.blank(*FIVE), window(100, RESET), T)[0]
        row = resetwatch.closed(row, T + 30)
        self.assertEqual((row["resets"], row["open_reset_at"]), (1, None))
        row, events = advance(row, window(0, None), T + 60)
        self.assertEqual((row["resets"], events), (1, ()), "the reading after it does not count it again")
        row, events = advance(row, window(3, T + 60 + 5 * 3600), T + 90)
        self.assertEqual(events, ("opened",))

    def test_the_reset_just_closed_does_not_open_again(self):
        row = advance(resetwatch.blank(*FIVE), window(40, RESET), T)[0]
        row = resetwatch.by_time(row, RESET + CLOSE_AFTER)[0]
        row, events = advance(row, window(40, RESET), RESET + CLOSE_AFTER + 1)
        self.assertEqual((row["open_reset_at"], events), (None, ()), "a stale reading of the old window")

    def test_a_gap_longer_than_the_window_and_three_misses(self):
        row = advance(resetwatch.blank(*FIVE), window(40, RESET), T)[0]
        self.assertIn("gap", advance(row, window(40, RESET), T + 300 * 60 + 1)[1])
        self.assertNotIn("gap", advance(row, window(40, RESET), T + 300 * 60)[1])
        events = []
        for step in range(3):
            row, found = advance(row, None, T + 60 * (step + 1))
            events.append(found)
        self.assertEqual(events, [("missing",), ("missing",), ("gone",)])
        row = advance(row, window(40, RESET), T + 300)[0]
        self.assertEqual(row["misses"], 0)


class Reader:
    """This edition's own reading, as a test hands it: the replies in turn, or an exception."""

    def __init__(self, *replies):
        self.replies, self.asked = list(replies), []

    def __call__(self, params):
        self.asked.append(params)
        reply = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        if isinstance(reply, Exception):
            raise reply
        return reply


class View:
    """Core's view of its store, as the tracker reads it: the last usage reading and the waiting records."""

    def __init__(self, last=None, waiting=()):
        self.last, self.waiting = last, list(waiting)

    def last_usage(self):
        return self.last

    def records_in(self, states):
        return list(self.waiting)


class WatchCase(ac.AdvancedCase):
    def setUp(self):
        super().setUp()
        self.now = T
        self.state = AdvancedState(self.paths, registry=Registry(()), clock=lambda: self.now)
        self.addCleanup(self.state.close)
        self.state._open(create=True)

    def message(self, ordinal=1):
        return self.state.add_reset_rule("reset_message", "codex", 300, ordinal, thread_id=ac.THREAD,
                                         words="hello", record_id="%064x" % (len(self.state.reset_rules()) + 1))

    def credit(self, ordinal=1):
        return self.state.add_reset_rule("reset_credit", "codex", 300, ordinal)

    def watch(self, reader=None, **options):
        return Watch(self.state, lambda: self.now, reader=reader, **options)


class RunnerTests(WatchCase):
    def test_with_no_rule_pending_nothing_is_read_and_nothing_counted(self):
        reader = Reader(usage(window(40, RESET)))
        looked = self.watch(reader).step(View())
        self.assertEqual((looked["rows"], reader.asked, self.state.windows()), ({}, [], {}))

    def test_a_rule_is_adopted_on_the_errands_own_fresh_reading(self):
        rule = self.credit()
        reader = Reader(usage(window(100, RESET)))
        self.watch(reader).step(View())
        adopted = self.state.reset_rule(rule)
        self.assertEqual((adopted["base"], adopted["adopted_at"]), (1, T), "a window full when it is made is not its next")
        self.assertEqual(reader.asked, [{}], "a detailed read: MU has not passed")
        message = self.message()
        self.now += READ_SPACING
        self.watch(reader).step(View())
        self.assertEqual(self.state.reset_rule(message)["base"], 0, "the window open then is its first reset")

    def test_cores_own_reading_counts_and_adopts_nothing(self):
        rule = self.credit()
        self.state.set_reading(asked_at=T)                            # this edition read a moment ago
        looked = self.watch(Reader(usage())).step(View(last=(T - 10, [window(40, RESET)])))
        self.assertEqual(looked["rows"][FIVE]["open_reset_at"], RESET)
        self.assertIsNone(self.state.reset_rule(rule)["adopted_at"])

    def test_a_new_instance_from_the_table_goes_on_counting(self):
        self.credit()
        self.watch(Reader(usage(window(40, RESET)))).step(View())
        self.now = RESET + CLOSE_AFTER
        again = Watch(self.state, lambda: self.now, reader=Reader(usage(window(0, None))))
        looked = again.step(View())
        self.assertEqual(looked["rows"][FIVE]["resets"], 1, "closed by time, counted from what was kept")

    def test_a_failed_reading_or_one_with_no_windows_changes_nothing(self):
        self.credit()
        self.watch(Reader(usage(window(40, RESET)))).step(View())
        before = self.state.windows()
        for reply in (RuntimeError("no app server"), {"rateLimitsByLimitId": {}}, "x"):
            with self.subTest(reply=reply):
                self.now += POLL
                reader = Reader(reply)
                self.watch(reader).step(View())
                self.assertEqual(len(reader.asked), 1, "it was read")
                self.assertEqual(self.state.windows(), before)

    def test_a_gap_holds_the_rule_with_what_it_has_left_to_count(self):
        rule = self.message(ordinal=3)
        self.watch(Reader(usage(window(40, RESET)))).step(View())
        self.now = RESET + CLOSE_AFTER
        later = RESET + CLOSE_AFTER + 6 * 3600
        self.watch(Reader(usage(window(10, later)))).step(View())          # one counted of three
        self.now += 300 * 60 + 1                                           # the PC was off longer than the window
        self.watch(Reader(usage(window(10, later)))).step(View())
        held = self.state.reset_rule(rule)
        self.assertEqual((held["state"], held["reason"], held["ordinal"], held["base"]),
                         (RuleState.HELD, RuleReason.COUNT_GAP, 2, None))

    def test_a_window_missing_from_three_readings_holds_its_rules(self):
        rule = self.credit()
        self.watch(Reader(usage(window(40, RESET)))).step(View())
        for _ in range(3):
            self.now += POLL
            self.watch(Reader(usage(window(40, RESET + 9999, minutes=10080)))).step(View())
        self.assertEqual((self.state.reset_rule(rule)["state"], self.state.reset_rule(rule)["reason"]),
                         (RuleState.HELD, RuleReason.WINDOW_GONE))

    def test_by_time_closes_a_window_with_no_reading(self):
        self.message()
        self.watch(Reader(usage(window(40, RESET)))).step(View())
        self.now = RESET + CLOSE_AFTER
        rows = self.watch().by_time()
        self.assertEqual(rows[FIVE]["resets"], 1)
        self.assertEqual(self.state.windows()[FIVE]["resets"], 1)


class ReadTests(WatchCase):
    """When this edition reads usage itself: at a rule's adoption, a minute after a reset, when core noticed a
    usage limit, every fifteen minutes - five minutes apart at most - and only while a rule is pending."""

    def reads(self, view=None, **options):
        reader = Reader(usage(window(40, RESET)))
        self.watch(reader, **options).step(view or View())
        return reader.asked

    def test_adoption_reads_and_then_nothing_for_fifteen_minutes(self):
        self.credit()
        self.assertEqual(len(self.reads()), 1)
        self.now += READ_SPACING
        self.assertEqual(self.reads(), [])
        self.now = T + POLL
        self.assertEqual(len(self.reads()), 1)

    def test_five_minutes_between_two_whatever_asks(self):
        self.credit()
        self.reads()
        self.message()                                                # waits for adoption
        self.now += READ_SPACING - 1
        self.assertEqual(self.reads(), [])
        self.now += 1
        self.assertEqual(len(self.reads()), 1)

    def test_a_minute_after_an_open_windows_reset(self):
        self.credit()
        self.reads()
        self.now = RESET + CLOSE_AFTER
        self.assertEqual(len(self.reads()), 1)

    def test_a_usage_limit_core_noticed_since_the_last_look(self):
        self.credit()
        self.reads()
        self.now += READ_SPACING
        waiting = View(waiting=[{"category": "usage_limit", "detected_at": self.now - 5}])
        self.assertEqual(len(self.reads(waiting)), 1)
        self.now += READ_SPACING
        self.assertEqual(self.reads(waiting), [], "noticed once")

    def test_a_poll_leaves_the_details_out_only_where_mu_passed(self):
        self.credit()
        self.reads()
        self.now = T + POLL
        self.assertEqual(self.reads(light=True), [{"excludeResetCreditDetails": True}])
        self.now = T + 2 * POLL
        self.assertEqual(self.reads(light=False), [{}])

    def test_the_count_and_the_expiry_are_kept_only_for_the_credits_capability(self):
        self.credit()
        self.watch(Reader(usage(window(40, RESET)))).step(View())
        self.assertIsNone(self.state.reading()["credits"])
        self.now += POLL
        self.watch(Reader(usage(window(40, RESET))), keep_credits=True).step(View())
        self.assertEqual(self.state.reading()["credits"], 1)


if __name__ == "__main__":
    unittest.main()
