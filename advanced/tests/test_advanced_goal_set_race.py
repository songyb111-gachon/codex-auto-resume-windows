"""The goal continuation's last instant: the app opens the conversation between core's look and the set (v0.6.18).

The route asks core's look - consent still given, the app still not holding the conversation - once its session is
up, at the last moment before thread/goal/set (test_advanced_goal RaceTests). The app could still open the
conversation between that look and the set (the stage 3a reviewer's GoalRace repro, on_set). M2 found a goal set
while the app holds the conversation is not seen, so the goal reading back active then proved nothing would carry
the conversation on; it was still accepted. Now the look is asked again once the goal reads back active, and where
the app holds the conversation then the answer is unknown: an uncertain submission, never tried again by either
route, and the capability's tripwire for a paid send gone unknown turns it off - what its statement says of a result
it cannot confirm. The set is never taken back: that would race the app again.

No real Codex: core's engine and simulated home, a goals database and a fake app server of the tests' own.
"""
from __future__ import annotations

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_advanced_goal as goal_tests  # noqa: E402
from test_advanced_goal import CAP, goal_row, set_goal  # noqa: E402
from test_engine import T1  # noqa: E402
from codex_auto_resume_advanced.vocabulary import ArmingState, OffReason  # noqa: E402


class OpenedAtTheSetTests(goal_tests.GoalCase):
    def test_a_set_the_app_may_not_see_is_unknown_and_never_followed_by_a_send(self):
        def app_opens_it(params):
            self.h.backend.loaded_map[T1] = "loaded"
        plug, fake = self.armed(on_set=app_opens_it)
        self.h.tick()
        self.assertEqual(len(fake.sets()), 1, "the look before the set said not held, so it was made")
        row = self.h.record()
        self.assertEqual((row["state"], row["last_error"]),
                         ("submission_unknown", "queue_result_unknown_do_not_resend"))
        stored = plug.runtime.state.arming()[CAP]
        self.assertEqual((stored["state"], stored["reason"]), (ArmingState.OFF, OffReason.SUBMISSION_UNKNOWN))
        for _ in range(12):
            self.h.tick(advance=900)
        self.assert_no_send()
        self.assertEqual(len(fake.sets()), 1, "never set twice")
        self.assertEqual(self.status(), "active", "never taken back")

    def test_where_the_app_still_does_not_hold_it_the_set_is_accepted(self):
        plug, fake = self.armed()
        self.h.tick()
        row = self.h.record()
        self.assertEqual((row["state"], row["last_error"]), ("waiting_retry", "notLoaded"))
        self.assertEqual(plug.runtime.state.arming()[CAP]["state"], ArmingState.ARMED)


class RouteAfterSetTests(unittest.TestCase):
    """The route alone, in RouteTests' own harness: the look's second answer decides between accepted and unknown."""
    Session = goal_tests.RouteTests.Session
    setUp, made, activate = goal_tests.RouteTests.setUp, goal_tests.RouteTests.made, goal_tests.RouteTests.activate

    def test_the_look_is_asked_again_after_the_goal_reads_back(self):
        answers = iter((True, False))
        session = self.Session(self, then=self.activate)
        self.assertEqual(self.made(session).resume(T1, still_unloaded=lambda: next(answers)),
                         {"outcome": "unknown", "error_code": "queue_result_unknown"})
        self.assertEqual(goal_row(self.root, T1)[2], "active")
        for second in (OSError("gone"), None):
            with self.subTest(second=second):
                set_goal(self.root, T1, "usage_limited")
                answers = iter((True, second))

                def look():
                    answer = next(answers)
                    if isinstance(answer, Exception):
                        raise answer
                    return answer
                self.assertEqual(self.made(self.Session(self, then=self.activate)).resume(T1, still_unloaded=look),
                                 {"outcome": "unknown", "error_code": "queue_result_unknown"})


if __name__ == "__main__":
    unittest.main()
