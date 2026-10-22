"""The P5 channels write their first change of state inside core's launch guard (v0.6.18, the advanced audit's M3):
goal_continuation's thread/goal/set and marker_free_continuation's thread/queue/add go with the session's start, so a
Pause or Cancel that commits once the guard is let go stops them - as core's queue launch and the stop's IPC request
are guarded. The answer is awaited outside the guard, which holds core's write lock.
"""
from __future__ import annotations

import contextlib
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from codex_auto_resume_advanced.codex import protocol  # noqa: E402
import test_advanced_goal as goal_tests  # noqa: E402
import test_advanced_marker_free as marker_free_tests  # noqa: E402
from test_engine import T1  # noqa: E402


def guard(held):
    @contextlib.contextmanager
    def one():
        held.append(True)
        try:
            yield True
        finally:
            held.pop()
    return one()


class GoalTests(unittest.TestCase):
    Session = goal_tests.RouteTests.Session
    setUp, made, activate = goal_tests.RouteTests.setUp, goal_tests.RouteTests.made, goal_tests.RouteTests.activate

    def test_the_set_is_written_inside_the_guard(self):
        """Fails with the guard reverted to the session's start alone: the set was written after it was let go."""
        held, written = [], []
        session = self.Session(self, then=lambda method, params: (written.append((method, bool(held))),
                                                                  self.activate(method, params)))
        self.assertEqual(self.made(session).send(T1, "go", launch_guard=guard(held))["outcome"], "accepted")
        self.assertEqual(written[0], ("thread/goal/set", True))
        self.assertEqual(written[1], ("thread/queue/add", False), "the add follows the set, its answer read outside")


class MarkerFreeTests(unittest.TestCase):
    CID, channel = marker_free_tests.ChannelTests.CID, marker_free_tests.ChannelTests.channel

    def test_the_add_is_written_inside_the_guard(self):
        """Fails with the guard reverted to the session's start alone."""
        held, written = [], []

        class Session(marker_free_tests.ChannelTests.Session):
            def call(self, method, params):
                written.append((method, bool(held)))
                return super().call(method, params)
        session = Session(result={})
        self.assertEqual(self.channel(session).send(T1, "go", launch_guard=guard(held), client_id=self.CID)["outcome"],
                         "accepted")
        self.assertEqual(written, [("thread/queue/add", True)])


class SubmittedTests(unittest.TestCase):
    def test_a_real_session_writes_now_and_reads_the_answer_later(self):
        order = []

        class Session:
            def submit(self, method, params=None):
                order.append(("submit", method))
                return 7

            def receive(self, method, sequence, params=None):
                order.append(("receive", sequence))
                return {"ok": True}
        pending = protocol.submitted(Session(), "thread/queue/add", {})
        self.assertEqual(order, [("submit", "thread/queue/add")])
        self.assertEqual(pending(), {"ok": True})
        self.assertEqual(order[-1], ("receive", 7))

    def test_a_failed_write_is_raised_when_the_answer_is_asked(self):
        class Session:
            def submit(self, method, params=None):
                raise protocol.SessionRefused("method not permitted for this session")

            def receive(self, *unused):
                raise AssertionError("never")
        pending = protocol.submitted(Session(), "x")
        with self.assertRaises(protocol.SessionRefused):
            pending()


if __name__ == "__main__":
    unittest.main()
