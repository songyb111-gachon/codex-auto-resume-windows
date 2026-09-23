"""The gates nothing was taking, each taken once.

The engine decides whether to send by evaluating a vector of gates and waiting on the first
one that does not pass. Four of those answers had no test reaching them at all - not a missing
assertion, a missing execution - and they are the ones that stop a send when the machine, not
the record, is wrong: an engine the registry cannot vouch for, another watcher holding the
Codex home, a category the person switched off, and the last look before the queue process
starts.

Written before v0.6.10-alpha moves the engine into `engine/`, because a branch nothing runs is
a branch a move can break in silence. Each test says what a person would have to do for the
branch to matter, and asserts the state and the reason a front end would show them.

They are characterization tests: they record what the engine does today, so the move has
something to be identical to.
"""
from __future__ import annotations

from pathlib import Path
import sys
import unittest

_HERE = str(Path(__file__).resolve().parent)
for entry in (str(Path(_HERE).parent / "src"), _HERE):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from codexsim import BASE, RESET  # noqa: E402
from test_engine import EngineCase, T1, TURN_A  # noqa: E402

# The harness starts ten seconds after BASE and the usage limit resets an hour in; every test
# here needs the schedule gate open, so that its own gate is the one that answers.
PAST_RESET = RESET - BASE + 600.0


class GateTestCase(EngineCase):
    def failing_turn(self):
        """One usage-limit failure, waiting to be recovered."""
        self.h.home.fail_usage(T1, TURN_A)
        self.h.tick()
        record = self.h.record()
        self.assertIsNotNone(record, "the fixture did not produce a record to gate")
        return record

    def waited(self):
        record = self.h.record()
        return record["state"], record["last_error"]


class EngineCompatibilityGateTests(GateTestCase):
    """What happens when the registry cannot vouch for the Codex that is installed."""

    def test_an_engine_the_registry_says_nothing_about_waits(self):
        """`unknown` is not `incompatible`: it is "nobody has checked this build".

        The send waits rather than being refused outright, so that a Codex released this
        morning stops nothing permanently - it waits for the data to say something.
        """
        self.failing_turn()
        self.h.engine.engine_state = lambda: "unknown"
        self.h.tick(advance=PAST_RESET)
        self.assertEqual(self.waited(), ("waiting_for_app", "engine_unknown"))

    def test_an_engine_the_data_calls_incompatible_waits_and_says_which(self):
        self.failing_turn()
        self.h.engine.engine_state = lambda: "incompatible"
        self.h.tick(advance=PAST_RESET)
        self.assertEqual(self.waited(), ("waiting_for_app", "engine_incompatible"))

    def test_a_check_that_failed_on_this_computer_waits_the_same_way(self):
        """v0.6.7's `failed_here`: the data vouches for the version, this machine does not."""
        self.failing_turn()
        self.h.engine.engine_state = lambda: "failed_here"
        self.h.tick(advance=PAST_RESET)
        self.assertEqual(self.waited(), ("waiting_for_app", "engine_incompatible"))

    def test_every_word_the_registry_can_say_is_answered(self):
        """A new word in the registry must not fall into the wrong branch by accident."""
        passing = ("verified", "checked", "structurally_compatible")
        blocking = ("incompatible", "failed_here")
        for word in passing + blocking + ("unknown",):
            with self.subTest(word):
                harness = self.fresh()
                harness.home.fail_usage(T1, TURN_A)
                harness.tick()
                harness.engine.engine_state = lambda word=word: word
                harness.tick(advance=PAST_RESET)
                record = harness.record()
                if word in passing:
                    self.assertNotEqual(record["last_error"], "engine_unknown")
                    self.assertNotEqual(record["last_error"], "engine_incompatible")
                else:
                    self.assertEqual(record["state"], "waiting_for_app")


class HomeLockGateTests(GateTestCase):
    """Another watcher holds this Codex home: ours must not send into it."""

    def test_a_home_somebody_else_holds_waits(self):
        self.failing_turn()
        self.h.engine.home_lock = lambda: False
        self.h.tick(advance=PAST_RESET)
        self.assertEqual(self.waited(), ("waiting_for_app", "home_lock_unavailable"))

    def test_the_wait_ends_when_the_home_is_ours_again(self):
        """The point of waiting rather than refusing."""
        self.failing_turn()
        self.h.engine.home_lock = lambda: False
        self.h.tick(advance=PAST_RESET)
        self.assertEqual(self.h.record()["state"], "waiting_for_app")
        self.h.engine.home_lock = lambda: True
        self.h.tick(advance=120)
        self.assertNotEqual(self.h.record()["last_error"], "home_lock_unavailable")


class CategoryDisabledGateTests(GateTestCase):
    """A kind of failure the person switched off in Settings."""

    def test_a_category_switched_off_waits_where_it_is(self):
        """It waits rather than being cancelled: switching it back on resumes it.

        And it waits on the conservative poll, not the fast one - nothing is going to change
        until a person changes it.
        """
        self.failing_turn()
        self.h.engine.options["recoverable_categories"] = ()
        before = self.h.record()["state"]
        self.h.tick(advance=PAST_RESET)
        state, reason = self.waited()
        self.assertEqual(reason, "category_disabled")
        self.assertEqual(state, before, "a disabled category waits where it was")

    def test_switching_it_back_on_lets_it_go_again(self):
        self.failing_turn()
        self.h.engine.options["recoverable_categories"] = ()
        self.h.tick(advance=PAST_RESET)
        self.assertEqual(self.h.record()["last_error"], "category_disabled")
        self.h.engine.options.pop("recoverable_categories")
        # Past the conservative poll, which is what a disabled category waits on: nothing was
        # going to change until a person changed it, so it is not asked again every minute.
        self.h.tick(advance=self.h.options["conservative_poll_seconds"] + 60)
        self.assertNotEqual(self.h.record()["last_error"], "category_disabled")


class PresendProblemTests(GateTestCase):
    """The last look, after the claim is granted and before the queue process starts.

    Everything here changed *since* the gates ran, which is the only reason this check exists
    separately: at this moment the claim is ours and giving it back is still provably safe.
    """

    def claim(self):
        """A record claimed for sending, as the engine claims it."""
        record = self.failing_turn()
        self.h.tick(advance=PAST_RESET)
        return self.h.store.get(record["interruption_id"])

    def test_nothing_wrong_means_nothing_to_report(self):
        claimed = self.claim()
        if claimed["state"] == "submitting":
            self.assertIsNone(self.h.engine.presend_problem(claimed))

    def test_a_record_that_is_no_longer_claimed_gives_the_claim_back(self):
        """Something else moved it while the process was being started."""
        claimed = dict(self.claim(), state="waiting_reset", queue_id=None)
        target, reason, delay = self.h.engine.presend_problem(claimed)
        self.assertEqual((target, reason), ("waiting_retry", "released_before_send"))
        self.assertGreater(delay, 0)

    def test_a_claim_that_already_reached_the_queue_is_not_sent_twice(self):
        claimed = dict(self.claim(), state="submitting",
                       queue_id="0a1b2c3d-0009-7000-8000-000000000009")
        target, reason, _delay = self.h.engine.presend_problem(claimed)
        self.assertEqual((target, reason), ("waiting_retry", "released_before_send"))

    def test_a_cancellation_asked_for_in_the_meantime_wins_at_once(self):
        claimed = dict(self.claim(), state="submitting", queue_id=None, cancel_requested=True)
        target, reason, delay = self.h.engine.presend_problem(claimed)
        self.assertEqual((target, reason, delay), ("cancelled", "user_cancelled", 0))

    def test_a_pause_in_the_meantime_gives_the_claim_back(self):
        claimed = dict(self.claim(), state="submitting", queue_id=None)
        self.h.store.set_enabled(False, self.h.now)
        target, reason, _delay = self.h.engine.presend_problem(claimed)
        self.assertEqual(reason, "released_before_send")
        self.assertIn("waiting", target)

    def test_the_home_slipping_away_at_the_last_moment_waits_for_the_app(self):
        """The same gate as above, at the other end of the decision - and the reason it is
        checked twice: between the gates and the queue process, another watcher can take it."""
        claimed = dict(self.claim(), state="submitting", queue_id=None)
        self.h.engine.home_lock = lambda: False
        target, reason, _delay = self.h.engine.presend_problem(claimed)
        self.assertEqual((target, reason), ("waiting_for_app", "home_lock_unavailable"))

    def test_a_missing_claim_is_a_problem_rather_than_a_crash(self):
        self.assertEqual(self.h.engine.presend_problem(None)[:2],
                         ("waiting_retry", "released_before_send"))


if __name__ == "__main__":
    unittest.main()
