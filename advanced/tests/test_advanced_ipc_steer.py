"""MSTEER2's channel (v0.6.20, issue #50): one line added to the turn the Desktop app is running, over its IPC pipe, the
connection the forced stop already uses (MIPC) - against a scratch pipe of the test's own (fakeipc), never the real one.
What is held: the request's shape and pinned version, one request written and never a second, and each failure one
closed word.

    PYTHONPATH=src;advanced/src python -m unittest discover -s advanced/tests -p test_advanced_ipc_steer.py
"""
from __future__ import annotations

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

from codex_auto_resume_advanced.codex import ipc  # noqa: E402

THREAD = "aaaaaaaa-0000-7000-8000-00000000a001"
MESSAGE = "cccccccc-0000-7000-8000-00000000c003"


@unittest.skipUnless(sys.platform == "win32", "a Windows named pipe")
class SteerTests(unittest.TestCase):
    def app(self, **script):
        import fakeipc
        found = fakeipc.FakeApp(script)
        self.addCleanup(found.close)
        return found

    def steer(self, app, text="Also: end with ok.", message=MESSAGE, gate=None):
        return ipc.steer_turn(THREAD, text, message=message, channel=ipc.Channel(app.name), gate=gate)

    def test_a_steer_is_initialize_then_the_owner_then_one_steer_to_that_owner(self):
        app = self.app()
        self.assertEqual(self.steer(app), ipc.Steer.STEERED)
        self.assertEqual([(method, version) for method, version, _params, _target in app.seen],
                         [("initialize", 0), ("thread-owner-discovery", 1), ("thread-follower-steer-turn", 1)])
        method, version, params, target = app.seen[-1]
        self.assertEqual(target, "owner-client")
        self.assertEqual((params["conversationId"], params["clientUserMessageId"]), (THREAD, MESSAGE))
        self.assertEqual(params["input"], [{"type": "text", "text": "Also: end with ok.", "text_elements": []}])
        self.assertEqual(params["restoreMessage"]["id"], MESSAGE)
        self.assertEqual(params["restoreMessage"]["text"], "Also: end with ok.")
        self.assertIsNone(params["restoreMessage"]["cwd"], "null falls back to the thread's own (the 2026-10-16 run)")
        self.assertNotIn("expectedTurnId", params, "the pipe's steer names no turn: the caller checks the history")

    def test_exactly_one_steer_is_written_on_every_path(self):
        for script in ({}, {"thread-follower-steer-turn": {"resultType": "error", "error": "refused by app"}},
                       {"thread-follower-steer-turn": {"resultType": "error", "error": "request-version-mismatch"}},
                       {"thread-follower-steer-turn": None}):
            with self.subTest(script), patch.object(ipc, "READ_SECONDS", 1.0):
                app = self.app(**script)
                self.steer(app)
                self.assertEqual([seen[0] for seen in app.seen].count("thread-follower-steer-turn"), 1,
                                 "never asked again, whatever the answer")

    def test_each_failure_is_one_closed_word(self):
        for script, word in (({"thread-owner-discovery": {"resultType": "error", "error": "no-client-found"}},
                              ipc.Stop.NO_CLIENT),
                             ({"thread-follower-steer-turn": {"resultType": "error",
                                                              "error": "request-version-mismatch"}},
                              ipc.Stop.VERSION_MISMATCH),
                             ({"thread-follower-steer-turn": {"resultType": "error", "error": "words of its own"}},
                              ipc.Stop.REFUSED),
                             ({"thread-owner-discovery": None}, ipc.Stop.NO_ANSWER),
                             ({"thread-follower-steer-turn": None}, ipc.Stop.UNCONFIRMED)):
            with self.subTest(word=word), patch.object(ipc, "READ_SECONDS", 1.0):
                self.assertEqual(self.steer(self.app(**script)), word)
        with patch.object(ipc, "PIPE", r"\\.\pipe\car-test-ipc-none-%d" % id(self)):
            self.assertEqual(ipc.steer_turn(THREAD, "x"), ipc.Stop.NO_PIPE, "the app not running")

    def test_it_is_written_only_inside_cores_guard(self):
        from contextlib import contextmanager
        entered = []

        def gate(permitted):
            @contextmanager
            def one():
                entered.append(permitted)
                yield permitted
            return one
        refused = self.app()
        self.assertEqual(self.steer(refused, gate=gate(False)), ipc.Stop.HELD)
        self.assertNotIn("thread-follower-steer-turn", [seen[0] for seen in refused.seen], "never written")
        allowed = self.app()
        self.assertEqual(self.steer(allowed, gate=gate(True)), ipc.Steer.STEERED)
        self.assertEqual(entered, [False, True])

    def test_no_message_id_given_one_is_made(self):
        app = self.app()
        self.assertEqual(ipc.steer_turn(THREAD, "x", channel=ipc.Channel(app.name)), ipc.Steer.STEERED)
        self.assertRegex(app.seen[-1][2]["clientUserMessageId"], r"^[0-9a-f-]{36}$")

    def test_the_steer_is_its_own_request_beside_the_stop_and_the_start(self):
        self.assertEqual(ipc.REQUESTS["thread-follower-steer-turn"][0], 1)
        self.assertNotEqual(ipc.REQUESTS["thread-follower-steer-turn"], ipc.REQUESTS["thread-follower-start-turn"])
        self.assertEqual(ipc.REQUESTS["thread-follower-start-turn"][0], 2, "the start is unchanged")


if __name__ == "__main__":
    unittest.main()
