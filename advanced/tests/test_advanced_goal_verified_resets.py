"""The goal continuation at a usage limit's verified reset (v0.6.22, issue #59): not held by its ceiling for one
conversation, and not by core's five.

One Goal, paused at every usage limit, its limit reset several times a day: each reset the watcher verified - the
record's interruption a usage limit, its expected reset passed, core's usage reading before the send showing room -
sets that same Goal active again through the Goal channel, the fourth to the seventh within 24 hours as the first.
What still holds is held here too: a continuation that answers no verified reset meets the ceiling at five; core's
fifteen minutes refuse one too soon; the capability's day still binds.

Against core's own engine and store, a simulated Codex home and a fake app server, as test_advanced_goal.py is.

    CODEX_AR_EDITION=advanced PYTHONPATH="src;advanced/src;tests;advanced/tests" python -m unittest test_advanced_goal_verified_resets
"""
from __future__ import annotations

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from advancedcase import ENGINE  # noqa: E402
from codex_auto_resume.domain.plug import Alternative, Point  # noqa: E402
from codex_auto_resume_advanced.registry import GOAL_CONTINUATION  # noqa: E402
from codex_auto_resume_advanced.vocabulary import JournalCode, Measurement, Verdict  # noqa: E402
from test_advanced_goal import CAP, GoalCase, goals_db, set_goal  # noqa: E402
from test_engine import T1  # noqa: E402

HOUR = 3600
# How far apart the resets come in these tests: seven of them in eighteen hours, inside one day.
APART = 3 * HOUR


class VerifiedResetCase(GoalCase):
    """A conversation the app holds, M2b passed for the Codex in force: the Goal channel sets the Goal active and
    then queues the continuation (test_advanced_goal.LoadedTests)."""

    def setUp(self):
        super().setUp()
        self.measured[Measurement.M2B] = (Verdict.PASS, ENGINE)

    def newest(self, h=None):
        return max((h or self.h).records(), key=lambda row: row["detected_at"])

    def limit_again(self, h=None, *, reset=True, wait=60):
        """Codex pauses the Goal at the next usage limit, and that turn fails on it; the watcher registers it.
        `reset`: the failure carries its reset time, `wait` seconds on (no reset recorded otherwise)."""
        h = h or self.h
        set_goal(h.home.root, T1, "usage_limited")
        h.home.fail_usage(T1, completed=int(h.now), reset=int(h.now) + wait if reset else None)
        h.tick()
        return self.newest(h)

    def reset_passes(self, h=None, wait=60):
        """The clock past the reset and the watcher's grace: the record is due at the next tick."""
        h = h or self.h
        h.now += wait + 61

    def channel_journal(self, plug, since=0):
        """(code, point) of each journal line of the capability's Goal channel or route, from the `since`th on."""
        lines = [(code, point) for code, point, _answer in self.journal(plug)]
        return [line for line in lines[since:] if line[1] in (Point.SENDER, Point.UNLOADED)]

    def first_reset(self):
        """The first usage limit, its reset passed, through the Goal channel: (plug, fake)."""
        plug, fake = self.armed(loaded=True)
        self.h.tick()
        self.assertEqual(self.status(), "active")
        self.follow()
        self.assertEqual(self.h.record()["state"], "recovered")
        return plug, fake

    def next_reset(self, plug, fake, *, apart=APART, reset=True):
        """The next usage limit `apart` seconds on, due once its reset (if any) has passed, and the tick that sends
        it: the record as it stands then."""
        self.h.now += apart
        record = self.limit_again(reset=reset)
        self.reset_passes()
        self.h.tick()
        return self.h.store.get(record["interruption_id"])


class FourthToSeventhTests(VerifiedResetCase):
    def test_the_fourth_to_the_seventh_verified_reset_in_a_day_each_go_through_the_goal_channel(self):
        plug, fake = self.first_reset()
        first = self.h.now
        for number in range(2, 8):
            with self.subTest(reset=number):
                sets = len(fake.sets())
                record = self.next_reset(plug, fake)
                self.assertLess(self.h.now - first, 86400, "every reset inside one day")
                self.assertEqual(len(fake.sets()), sets + 1, "the Goal channel set the Goal active")
                self.assertEqual(fake.methods()[-2:], ["thread/goal/set", "thread/queue/add"])
                self.assertEqual(self.status(), "active", "the stand-in's native Goal is active again")
                self.assertEqual(record["state"], "queued")
                self.follow()
                self.assertEqual(self.h.store.get(record["interruption_id"])["state"], "recovered")
        self.assertEqual(len(self.spends(plug)), 7, "one unit for each reset, every one paid for")
        self.assertNotIn(JournalCode.CEILING, [code for code, _point, _answer in self.journal(plug)])
        acted = [line for line in self.channel_journal(plug) if line == (JournalCode.ACTED, Point.SENDER)]
        self.assertEqual(len(acted), 7, "acted at the Goal channel at every reset")
        self.assertEqual(self.h.backend.send_calls, [], "nothing went through Codex's ordinary queue")


class UnverifiedTests(VerifiedResetCase):
    def fill(self, plug, h, count):
        """`count` of the capability's units already spent on T1 in the last day, two hours ago."""
        with plug.runtime.state._transaction() as connection:
            for index in range(count):
                plug.runtime.state.record_spend(connection, "main", CAP, T1, "%064x" % index, h.now - 2 * HOUR)

    def test_a_continuation_answering_no_verified_reset_still_meets_the_ceiling_at_five(self):
        per_conversation = GOAL_CONTINUATION.ceilings.per_conversation
        self.assertEqual(per_conversation, 5)
        base = self.where
        for verified in (True, False):
            with self.subTest(verified=verified):
                self.where = base / ("verified" if verified else "unverified")   # an advanced state of its own
                h = self.fresh()
                goals_db(h.home.root)
                set_goal(h.home.root, T1, "usage_limited")
                if verified:
                    self.ready_after_reset(h, loaded=True)
                else:
                    # A usage limit Codex gave no reset time for: no expected reset, so nothing verified it.
                    h.home.fail_usage(T1, reset=None)
                    h.backend.loaded_map[T1] = "loaded"
                    h.tick()
                    h.now += 4 * HOUR
                plug = self.advanced(h)
                self.code(plug, h)
                self.arm(plug)
                fake = self.server(h)
                self.plugged(plug, h)
                self.fill(plug, h, per_conversation)
                h.tick()
                codes = [code for code, _point, _answer in self.journal(plug)]
                if verified:
                    self.assertEqual(fake.methods(), ["thread/goal/set", "thread/queue/add"])
                    self.assertEqual(self.status(h), "active")
                    self.assertNotIn(JournalCode.CEILING, codes)
                    self.assertEqual(len(self.spends(plug)), per_conversation + 1)
                else:
                    self.assertEqual(fake.received, [], "past its ceiling the Goal channel is not taken")
                    self.assertEqual(self.status(h), "usage_limited")
                    self.assertIn(JournalCode.CEILING, codes)
                    self.assertEqual(len(self.spends(plug)), per_conversation)
                    self.assertEqual(len(h.backend.send_calls), 1, "core's own continuation, as the standard edition's")

    def test_the_goal_answers_a_verified_reset_only_once_the_reset_core_recorded_has_passed(self):
        code = self.code(self.advanced())
        record = {"category": "usage_limit", "thread_id": T1, "interruption_id": "%064x" % 1,
                  "reset_at": self.h.now - 1}
        self.assertIs(code.gate("known_failure", record, {}), Alternative.VERIFIED_RESET)
        for changed in ({"reset_at": self.h.now + 60}, {"reset_at": None}, {"category": "server_5xx"}):
            with self.subTest(changed=changed):
                self.assertIsNot(code.gate("known_failure", dict(record, **changed), {}), Alternative.VERIFIED_RESET)
        set_goal(self.h.home.root, T1, "active")
        self.assertIsNot(code.gate("known_failure", record, {}), Alternative.VERIFIED_RESET,
                         "a Goal not paused by the limit has nothing to answer for")


class SpacingTests(VerifiedResetCase):
    def test_core_s_fifteen_minutes_still_refuse_a_verified_reset_too_soon(self):
        plug, fake = self.first_reset()
        for _number in range(2, 6):
            self.next_reset(plug, fake)
            self.follow()
        sets = len(fake.sets())
        # The sixth: ten minutes after the fifth's claim, its reset already passed.
        claimed = max(row["last_claim_at"] for row in self.h.records())
        self.h.now = claimed + 60
        record = self.limit_again(wait=30)
        self.h.now = claimed + 600
        self.h.tick()
        held = self.h.store.get(record["interruption_id"])
        self.assertEqual(len(fake.sets()), sets, "too soon: the Goal is left as it is")
        self.assertEqual(self.status(), "usage_limited")
        self.assertEqual(held["last_error"], "thread_submission_cooldown")
        self.h.now = claimed + 600 + 900 + 1                 # the wait the spacing set, from the look that met it
        self.h.tick()
        self.assertEqual(len(fake.sets()), sets + 1, "once the fifteen minutes are past it goes")
        self.assertEqual(self.status(), "active")


class DayTests(VerifiedResetCase):
    def test_the_capabilitys_day_still_binds_a_verified_reset(self):
        per_day = GOAL_CONTINUATION.ceilings.per_day
        plug, fake = self.first_reset()
        for _number in range(2, 6):
            self.next_reset(plug, fake)
            self.follow()
        others = ["0a1b2c3d-0001-7000-8000-%012x" % (index + 16) for index in range(per_day - 6)]
        with plug.runtime.state._transaction() as connection:
            for index, thread in enumerate(others):
                plug.runtime.state.record_spend(connection, "main", CAP, thread, "%064x" % (index + 64),
                                                self.h.now - 2 * HOUR)
        self.assertEqual(len(self.spends(plug)), per_day - 1)
        sets = len(fake.sets())
        self.next_reset(plug, fake)
        self.assertEqual(len(fake.sets()), sets + 1, "the sixth verified reset is the day's last unit")
        self.assertEqual(self.status(), "active")
        self.follow()
        record = self.next_reset(plug, fake)
        self.assertEqual(len(fake.sets()), sets + 1, "the day is spent: the Goal is left as it is")
        self.assertEqual(self.status(), "usage_limited")
        self.assertIn(JournalCode.CEILING, [code for code, _point, _answer in self.journal(plug)])
        self.assertEqual(len(self.spends(plug)), per_day)
        self.assertEqual(record["last_error"], "daily_submission_cap", "and core's five hold it, as without it")


if __name__ == "__main__":
    unittest.main()
