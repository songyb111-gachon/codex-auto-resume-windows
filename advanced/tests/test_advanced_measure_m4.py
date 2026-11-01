"""M4 (v0.6.20): plugin Stop hooks run after a failed turn, and the failed turn is in Codex's history when the hook
runs. The probe makes the failed turn itself - one turn asked of a model no Codex offers, from its own session on a
throwaway conversation nothing holds, as M6 starts its turn - and reads three things: the hooks Codex lists (a plugin
Stop hook on and trusted), the hook/started and hook/completed notifications for that turn, and the note the
measurement-only Stop hook writes (when it ran, its input's key names, the turn's status in the history then). Driven
here through fakes alone: a fake session, fake hands and a patched holder count.

    CODEX_AR_EDITION=advanced PYTHONPATH="src;advanced/src" python -m unittest discover -s advanced/tests
"""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_advanced_measure_stage4 import THREAD, VERSIONS, Backend, FakeSession  # noqa: E402
from codex_auto_resume_advanced import measure  # noqa: E402
from codex_auto_resume_advanced.codex import protocol  # noqa: E402
from codex_auto_resume_advanced.vocabulary import Measurement  # noqa: E402

TRUSTED_STOP = {"data": [{"cwd": "C:/work", "errors": [], "warnings": [], "hooks": [
    {"eventName": "stop", "source": "plugin", "trustStatus": "trusted", "enabled": True, "key": "k",
     "sourcePath": "C:/private/hooks.json"}]}]}
UNTRUSTED_STOP = {"data": [{"cwd": "C:/work", "errors": [], "warnings": [], "hooks": [
    {"eventName": "stop", "source": "plugin", "trustStatus": "untrusted", "enabled": True}]}]}
KEYS = ["session_id", "turn_id", "hook_event_name", "stop_hook_active", "last_assistant_message"]


def completed(status):
    return {"method": "turn/completed", "params": {"threadId": THREAD, "turn": {"id": "t1", "status": status}}}


def hook(method, status="completed", source="plugin", event="stop"):
    return {"method": method, "params": {"threadId": THREAD, "turnId": "t1", "run": {
        "eventName": event, "source": source, "status": status, "entries": [{"text": "PRIVATE-WORDS"}]}}}


class M4Tests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(self.dir, ignore_errors=True))
        for name, value in (("_M4_TURN_SECONDS", 0.2), ("_M4_NOTE_SECONDS", 0.2), ("_M6_INTERRUPT_SECONDS", 0.1),
                            ("_M6_POLL_SECONDS", 0.0)):
            patcher = patch.object(measure, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.sessions = []

    def run_one(self, *, listed=TRUSTED_STOP, events=(), notes=(), holders=0, thread=THREAD, start=None):
        def made(measured):
            replies = {"hooks/list": listed, "turn/start": start or {"turn": {"id": "t1"}}}
            self.sessions.append(FakeSession(measured, replies, events))
            return self.sessions[-1]
        with patch.object(measure, "_lock_users", lambda ctx, given: holders):
            summary = measure.run(Measurement.M4, session_factory=made, backend=Backend(), versions=VERSIONS,
                                  thread=thread, clock=lambda: 1_800_000_000.0, directory=self.dir,
                                  hands={"m4_hook_note": lambda: list(notes)})
        text = Path(summary["recorded"]).read_text(encoding="utf-8")
        for private in (THREAD, "PRIVATE-WORDS", "C:/private", "car-m4-no-such-model"):
            self.assertNotIn(private, text)
        return json.loads(text)

    def note(self, status="failed", keys=KEYS):
        return {"at": 4_000_000_000.0, "keys": keys, "status": status}

    def calls(self):
        return [method for method, _params in self.sessions[0].calls]

    def test_its_methods_are_the_ones_a_failed_turn_of_its_own_needs(self):
        self.assertEqual(protocol.methods_for(Measurement.M4),
                         {"initialize", "initialized", "hooks/list", "thread/resume", "turn/start", "turn/interrupt",
                          "thread/unsubscribe"})

    def test_a_stop_hook_that_ran_after_the_failed_turn_and_saw_it_failed_is_a_pass(self):
        record = self.run_one(events=[hook("hook/started"), completed("failed"), hook("hook/completed")],
                              notes=[self.note()])
        self.assertEqual(record["verdict"], "pass", record)
        observed = record["observed"]
        self.assertEqual((observed["turn_status"], observed["stop_hook_started"], observed["stop_hook_completed"],
                          observed["history_status_when_hook_ran"], observed["plugin_stop_hooks_trusted"]),
                         ("failed", 1, 1, "failed", 1))
        self.assertTrue(observed["input_session_id"] and observed["input_turn_id"] and observed["input_stop_hook_active"])
        self.assertFalse(observed["input_transcript_path"])

    def test_the_turn_asks_a_model_no_codex_offers_and_is_followed_to_its_end(self):
        self.run_one(events=[completed("failed")], notes=[self.note()])
        started = [params for method, params in self.sessions[0].calls if method == "turn/start"]
        self.assertEqual(len(started), 1)
        self.assertEqual(started[0]["model"], measure._M4_MODEL)
        self.assertEqual(started[0]["threadId"], THREAD)
        self.assertEqual(self.calls(), ["hooks/list", "thread/resume", "turn/start", "thread/unsubscribe"])

    def test_no_stop_hook_run_after_the_failed_turn_is_a_fail(self):
        """Fails with the old probe: it only listed the hooks and left everything to the person."""
        record = self.run_one(events=[completed("failed")])
        self.assertEqual((record["verdict"], record["observed"]["stop_hook_started"], record["observed"]["hook_noted"]),
                         ("fail", 0, False))
        self.assertIn("did not run", record["note"])

    def test_a_hook_that_ran_before_the_failed_turn_was_in_the_history_is_a_fail(self):
        record = self.run_one(events=[hook("hook/started"), completed("failed"), hook("hook/completed")],
                              notes=[self.note("inProgress")])
        self.assertEqual((record["verdict"], record["observed"]["history_status_when_hook_ran"]),
                         ("fail", "inProgress"))
        self.assertIn("not yet in Codex's history", record["note"])

    def test_a_turn_that_did_not_fail_settles_nothing(self):
        record = self.run_one(events=[completed("completed"), hook("hook/completed")], notes=[self.note("completed")])
        self.assertEqual((record["verdict"], record["observed"]["turn_status"]), ("blocked", "completed"))

    def test_a_turn_codex_would_not_start_settles_nothing(self):
        record = self.run_one(start=protocol._refused_by_codex("turn/start", -32600))
        self.assertEqual((record["verdict"], record["observed"]["turn_started"], record["observed"]["turn_status"]),
                         ("blocked", False, "none"))

    def test_no_trusted_plugin_stop_hook_starts_no_turn(self):
        for listed in (UNTRUSTED_STOP, {"data": []}, {}):
            with self.subTest(listed):
                self.sessions.clear()
                record = self.run_one(listed=listed)
                self.assertEqual((record["verdict"], record["observed"]["plugin_stop_hooks_trusted"]), ("blocked", 0))
                self.assertEqual(self.calls(), ["hooks/list"], "no turn is started without a hook to run after it")

    def test_another_hook_or_another_source_is_not_counted(self):
        record = self.run_one(events=[hook("hook/started", event="sessionStart"),
                                      hook("hook/completed", source="user"), completed("failed")])
        self.assertEqual((record["verdict"], record["observed"]["stop_hook_started"],
                          record["observed"]["stop_hook_completed"]), ("fail", 0, 0))

    def test_a_held_or_unreadable_conversation_opens_no_session(self):
        for holders in (1, None):
            with self.subTest(holders):
                self.sessions.clear()
                record = self.run_one(holders=holders)
                self.assertEqual(record["verdict"], "blocked")
                self.assertEqual(self.sessions, [])

    def test_no_conversation_opens_no_session(self):
        record = self.run_one(thread=None)
        self.assertEqual(record["verdict"], "blocked")
        self.assertEqual(self.sessions, [])

    def test_a_note_from_before_the_turn_is_not_counted(self):
        record = self.run_one(events=[completed("failed")], notes=[dict(self.note(), at=1.0)])
        self.assertEqual((record["verdict"], record["observed"]["hook_noted"]), ("fail", False))


if __name__ == "__main__":
    unittest.main()
