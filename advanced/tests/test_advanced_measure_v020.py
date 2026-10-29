"""The v0.6.20 probes (issue #50, plans/v0619-design/D-issue50.md): MIMG - an image beside the words in Codex's queue -
and MSTEER - turn/steer for the exact active turn. Each is driven here through a fake session alone: the fakes refuse a
method the measurement did not declare, as the real session does, and nothing opens a real Codex, writes to a real
conversation or sends anything. A record is written through evidence.build, so each observation is content-free or the
run fails.

What these hold, beyond the shape of every probe: MIMG's picture is a file in a scratch folder the run removes, and the
add is never repeated after an answer that did not come; MSTEER calls turn/steer once on every path that reaches it,
never again after an uncertain answer, and not at all unless the history says the turn it names is running.

    CODEX_AR_EDITION=advanced PYTHONPATH="src;advanced/src;tests" python -m unittest test_advanced_measure_v020
"""
from __future__ import annotations

import base64
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import advancedcase  # noqa: E402,F401  (puts src, advanced/src and tests on the path)
from codex_auto_resume.codex.errors import AdapterError  # noqa: E402
from codex_auto_resume_advanced import measure, measured  # noqa: E402
from codex_auto_resume_advanced.codex import protocol, turns  # noqa: E402
from codex_auto_resume_advanced.vocabulary import Measurement, Verdict  # noqa: E402
from test_advanced_measure_stage4 import THREAD, TURN, VERSIONS, Backend, FakeSession, refused  # noqa: E402

MIMG, MSTEER = Measurement.MIMG, Measurement.MSTEER
OTHER_TURN = "deadbeef-0000-7000-8000-00000000cafe"
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def item_of(params):
    return {"id": "q", "clientUserMessageId": params["clientUserMessageId"], "input": params["input"]}


class Case(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(self.dir, ignore_errors=True))
        for name, value in (("_MC1_QUEUE_SECONDS", 0.05), ("_MC1_START_SECONDS", 0.05), ("_M2B_POLL_SECONDS", 0.01),
                            ("_MSTEER_LOOK_SECONDS", 0.05), ("_MSTEER_POLL_SECONDS", 0.01)):
            patcher = patch.object(measure, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.sessions, self.looked_for = [], []

    def calls(self):
        return [(method, params) for session in self.sessions for method, params in session.calls]

    def methods(self):
        return [method for method, _params in self.calls()]

    def run_probe(self, measurement, replies, *, thread=THREAD, recorded=True, started="inProgress", backend=None):
        def factory(measured_one):
            self.sessions.append(FakeSession(measured_one, replies))
            return self.sessions[-1]

        def history(ctx, client_id):
            self.looked_for.append(client_id)
            return recorded
        with patch.object(measure, "_client_recorded", history), \
                patch.object(measure, "_latest_kinds", lambda ctx: (started, False, True)):
            summary = measure.run(measurement, session_factory=factory, backend=backend or Backend(self.dir),
                                  versions=VERSIONS, thread=thread, clock=lambda: 1_800_000_000.0, directory=self.dir)
        text = Path(summary["recorded"]).read_text(encoding="utf-8")
        for private in (THREAD, TURN, OTHER_TURN):
            self.assertNotIn(private, text)
        return json.loads(text)


class AllowListTests(Case):
    def test_each_probe_is_registered_with_exactly_the_methods_it_calls(self):
        """Fails with the probes reverted: the ids have no probe and no allow-list."""
        self.assertIs(measure.PROBES[MIMG], measure._mimg)
        self.assertIs(measure.PROBES[MSTEER], measure._msteer)
        self.assertEqual(protocol.methods_for(MIMG), {"initialize", "initialized", "thread/queue/add",
                                                      "thread/queue/list"})
        self.assertEqual(protocol.methods_for(MSTEER), {"initialize", "initialized", "thread/loaded/list",
                                                        "turn/steer"})
        self.assertIn("turn/steer", protocol.ADVANCED_METHODS)

    def test_no_capability_may_call_what_only_these_two_declared(self):
        """turn/steer is a measurement's until a capability's own row is added with the capability."""
        for capability, methods in protocol.CAPABILITY_METHODS.items():
            with self.subTest(capability):
                self.assertNotIn("turn/steer", methods)

    def test_neither_has_been_measured(self):
        for measurement in (MIMG, MSTEER):
            self.assertNotIn(measurement, measured.MEASURED)

    def test_the_ids_are_the_words_the_bridge_and_the_runbook_use(self):
        self.assertEqual((str(MIMG), str(MSTEER)), ("mimg", "msteer"))


class ImageTests(Case):
    def replies(self, *, add=None, taken=True):
        seen = self.seen = {"files": []}

        def queue_add(params):
            image = params["input"][1]
            path = image.get("path")
            if path is not None:
                seen["path"] = path
                seen["bytes"] = Path(path).read_bytes()
            seen["adds"] = seen.get("adds", []) + [params]
            return add(params) if add is not None else {"queuedSubmission": item_of(params)}

        def queue_list(params):
            return {"data": [] if taken else [{"id": "q", "clientUserMessageId": seen["adds"][-1]["clientUserMessageId"]}]}
        return {"thread/queue/add": queue_add, "thread/queue/list": queue_list}

    def test_without_a_conversation_it_opens_no_session(self):
        record = self.run_probe(MIMG, self.replies(), thread=None)
        self.assertEqual((record["verdict"], record["observed"]["add_calls"]), ("blocked", 0))
        self.assertEqual(self.sessions, [])

    def test_a_local_image_file_beside_the_words_is_queued_taken_and_found_by_its_client_id(self):
        record = self.run_probe(MIMG, self.replies())
        self.assertEqual(record["verdict"], "blocked", "the person who watched settles it")
        observed = record["observed"]
        self.assertEqual((observed["add_calls"], observed["local_image_accepted"], observed["queued_input_items"],
                          observed["queued_keeps_image"], observed["taken"], observed["turn_started"],
                          observed["client_id_on_user_item"]), (1, True, 2, True, True, True, True))
        self.assertNotIn("data_address_accepted", observed, "a second shape is tried only after a refusal")
        self.assertEqual(self.methods(), ["thread/queue/add", "thread/queue/list"])
        added = self.seen["adds"][0]
        self.assertEqual(added["threadId"], THREAD)
        self.assertEqual([part["type"] for part in added["input"]], ["text", "localImage"])
        self.assertEqual(self.looked_for, [added["clientUserMessageId"]])
        self.assertIn("picture", record["note"])

    def test_the_picture_is_a_real_png_that_exists_while_the_add_is_made_and_is_removed_after(self):
        self.run_probe(MIMG, self.replies())
        self.assertTrue(self.seen["bytes"].startswith(PNG_MAGIC))
        self.assertFalse(Path(self.seen["path"]).exists(), "the picture is removed when the run ends")
        self.assertFalse(Path(self.seen["path"]).parent.exists(), "and so is its scratch folder")

    def test_the_record_holds_neither_the_picture_nor_where_it_was(self):
        record = self.run_probe(MIMG, self.replies())
        text = json.dumps(record)
        self.assertNotIn(self.seen["path"], text)
        self.assertNotIn("car-mimg", text)
        self.assertNotIn(measure._MIMG_PNG_BASE64, text)

    def test_a_refused_local_file_is_followed_once_by_the_data_address_under_another_client_id(self):
        def add(params):
            if params["input"][1]["type"] == "localImage":
                return refused("thread/queue/add", -32602)
            return {"queuedSubmission": item_of(params)}
        record = self.run_probe(MIMG, self.replies(add=add))
        observed = record["observed"]
        self.assertEqual((observed["add_calls"], observed["local_image_accepted"], observed["local_image_refusal_code"],
                          observed["data_address_accepted"], observed["queued_keeps_image"]), (2, False, -32602, True,
                                                                                                True))
        adds = self.seen["adds"]
        self.assertEqual([call["input"][1]["type"] for call in adds], ["localImage", "image"])
        self.assertTrue(adds[1]["input"][1]["url"].startswith("data:image/png;base64,"))
        self.assertEqual(base64.b64decode(adds[1]["input"][1]["url"].split(",", 1)[1])[:8], PNG_MAGIC)
        self.assertNotEqual(adds[0]["clientUserMessageId"], adds[1]["clientUserMessageId"])
        self.assertEqual(self.looked_for, [adds[1]["clientUserMessageId"]])
        self.assertEqual(record["verdict"], "blocked")

    def test_both_shapes_refused_is_a_fail_with_the_codes_and_nothing_followed(self):
        record = self.run_probe(MIMG, self.replies(add=lambda params: refused("thread/queue/add", -32600)))
        self.assertEqual(record["verdict"], Verdict.FAIL)
        observed = record["observed"]
        self.assertEqual((observed["add_calls"], observed["local_image_accepted"], observed["data_address_accepted"],
                          observed["local_image_refusal_code"], observed["data_address_refusal_code"]),
                         (2, False, False, -32600, -32600))
        self.assertEqual(self.methods(), ["thread/queue/add", "thread/queue/add"], "no queue followed, no history")
        self.assertEqual(self.looked_for, [])
        self.assertIn("refused", record["note"])

    def test_an_answer_that_did_not_come_is_never_followed_by_a_second_add(self):
        """The message may be queued: adding it again could send it twice. Fails with the retry rule back."""
        record = self.run_probe(MIMG, self.replies(add=lambda params: AdapterError("protocol_timeout")))
        self.assertEqual(record["verdict"], "blocked")
        observed = record["observed"]
        self.assertEqual((observed["add_calls"], observed["add_answer_uncertain"], observed["local_image_accepted"]),
                         (1, True, False))
        self.assertEqual(self.methods(), ["thread/queue/add"])
        self.assertEqual(self.looked_for, [])
        self.assertFalse(Path(self.seen["path"]).parent.exists(), "the scratch folder goes on this path too")

    def test_an_item_the_app_never_takes_is_recorded_as_not_taken(self):
        record = self.run_probe(MIMG, self.replies(taken=False))
        observed = record["observed"]
        self.assertEqual((record["verdict"], observed["taken"], observed["turn_started"]), ("blocked", False, False))
        self.assertIn("remove it", record["note"])

    def test_a_submission_without_the_image_is_recorded_as_one(self):
        record = self.run_probe(MIMG, self.replies(add=lambda params: {"queuedSubmission": {
            "id": "q", "clientUserMessageId": params["clientUserMessageId"], "input": params["input"][:1]}}))
        observed = record["observed"]
        self.assertEqual((observed["queued_input_items"], observed["queued_keeps_image"]), (1, False))

    def test_a_method_it_did_not_declare_is_refused_by_the_session(self):
        def sneak(params):
            raise protocol.SessionRefused("method not permitted for this session")
        record = self.run_probe(MIMG, self.replies(add=sneak))
        self.assertEqual(record["verdict"], "blocked")
        self.assertTrue(record["note"].startswith("not reached"))


class RunningTurn:
    """A stand-in for the history's latest turn: only what MSTEER reads of it."""

    def __init__(self, turn_id, status):
        self.turn_id, self.status = turn_id, status


class SteerTests(Case):
    def run_steer(self, *, steer=None, latest=(RunningTurn(TURN, "inProgress"),), held=True, thread=THREAD,
                  recorded=True, history_error=False):
        """MSTEER against a fake: the history's latest turn is each of `latest` in turn (the last again); turn/steer
        answers `steer`; the app holds the conversation or not."""
        order = list(latest)

        def newest(self_, thread_id):
            if history_error:
                raise turns.TurnsUnavailable("the turn history cannot be read")
            return order.pop(0) if len(order) > 1 else order[0]
        asked = self.asked = []

        def answer(params):
            asked.append(params)
            return steer(params) if steer is not None else {"turnId": params["expectedTurnId"]}
        replies = {"thread/loaded/list": {"data": [THREAD] if held else []}, "turn/steer": answer}
        with patch.object(turns.Turns, "latest", newest):
            return self.run_probe(MSTEER, replies, thread=thread, recorded=recorded)

    def steers(self):
        return [params for method, params in self.calls() if method == "turn/steer"]

    def test_without_a_conversation_nothing_is_called(self):
        record = self.run_steer(thread=None)
        self.assertEqual((record["verdict"], record["observed"]["steer_calls"]), ("blocked", 0))
        self.assertEqual(self.sessions, [])

    def test_unless_the_history_says_the_turn_runs_nothing_is_called(self):
        for latest in ((RunningTurn(TURN, "completed"),), (None,)):
            with self.subTest(latest=latest):
                self.sessions.clear()
                record = self.run_steer(latest=latest)
                self.assertEqual((record["verdict"], record["observed"]["turn_in_progress"],
                                  record["observed"]["steer_calls"]), ("blocked", False, 0))
                self.assertEqual(self.sessions, [], "no session, so nothing could be sent")

    def test_an_unreadable_history_calls_nothing(self):
        record = self.run_steer(history_error=True)
        self.assertEqual((record["verdict"], record["observed"]["history_read"], record["observed"]["steer_calls"]),
                         ("blocked", False, 0))
        self.assertEqual(self.sessions, [])

    def test_an_accepted_steer_names_the_exact_active_turn_once_and_is_looked_for_in_the_history(self):
        record = self.run_steer()
        self.assertEqual(record["verdict"], "blocked", "that it showed in the turn is the person's to confirm")
        observed = record["observed"]
        self.assertEqual((observed["steer_calls"], observed["steer_accepted"], observed["answer_uncertain"],
                          observed["answer_names_same_turn"], observed["client_id_on_user_item"],
                          observed["latest_turn_unchanged"], observed["held_by_app"]),
                         (1, True, False, True, True, True, True))
        self.assertEqual(self.methods(), ["thread/loaded/list", "turn/steer"])
        steer, = self.steers()
        self.assertEqual((steer["threadId"], steer["expectedTurnId"], steer["clientUserMessageId"]),
                         (THREAD, TURN, measure._SAMPLE_MSTEER_CLIENT_ID))
        self.assertEqual(steer["input"], [{"type": "text", "text": measure._MSTEER_TEXT}])
        self.assertEqual(self.looked_for[0], measure._SAMPLE_MSTEER_CLIENT_ID)

    def test_a_refusal_is_a_fail_with_its_code_and_the_call_is_made_once(self):
        record = self.run_steer(steer=lambda params: refused("turn/steer", -32600))
        self.assertEqual(record["verdict"], Verdict.FAIL)
        observed = record["observed"]
        self.assertEqual((observed["steer_calls"], observed["steer_accepted"], observed["answer_uncertain"],
                          observed["refusal_code"]), (1, False, False, -32600))
        self.assertEqual(len(self.steers()), 1)
        self.assertEqual(self.looked_for, [], "a refusal delivered nothing, so there is nothing to look for")

    def test_an_answer_that_did_not_come_is_uncertain_and_never_followed_by_a_second_call(self):
        """The line may be in the turn: calling again could put it there twice. Fails with the retry rule back."""
        for failure in (AdapterError("protocol_timeout"), AdapterError("protocol_unavailable")):
            with self.subTest(failure.args):
                self.sessions.clear()
                record = self.run_steer(steer=lambda params, failure=failure: failure)
                self.assertEqual(record["verdict"], "blocked")
                observed = record["observed"]
                self.assertEqual((observed["steer_calls"], observed["steer_accepted"], observed["answer_uncertain"]),
                                 (1, False, True))
                self.assertNotIn("refusal_code", observed)
                self.assertEqual(len(self.steers()), 1)
                self.assertIn("not sent again", record["note"])

    def test_an_answer_naming_another_turn_is_recorded_as_one(self):
        record = self.run_steer(steer=lambda params: {"turnId": OTHER_TURN})
        self.assertFalse(record["observed"]["answer_names_same_turn"])
        record = self.run_steer(steer=lambda params: {})
        self.assertFalse(record["observed"]["answer_names_same_turn"])

    def test_a_new_turn_after_the_steer_is_recorded_as_a_changed_latest_turn(self):
        record = self.run_steer(latest=(RunningTurn(TURN, "inProgress"), RunningTurn(OTHER_TURN, "inProgress")))
        self.assertFalse(record["observed"]["latest_turn_unchanged"])

    def test_a_line_the_history_never_shows_is_recorded_as_not_seen(self):
        record = self.run_steer(recorded=False)
        self.assertFalse(record["observed"]["client_id_on_user_item"])
        self.assertEqual(record["observed"]["steer_accepted"], True)

    def test_a_conversation_the_app_does_not_hold_is_recorded_not_stopped_on(self):
        """The call still is made once: the answer to it is what is measured."""
        record = self.run_steer(held=False)
        self.assertEqual((record["observed"]["held_by_app"], record["observed"]["steer_calls"]), (False, 1))

    def test_the_record_is_content_free(self):
        record = self.run_steer()
        for value in record["observed"].values():
            self.assertTrue(isinstance(value, (bool, int)) or value is None, value)


if __name__ == "__main__":
    unittest.main()
