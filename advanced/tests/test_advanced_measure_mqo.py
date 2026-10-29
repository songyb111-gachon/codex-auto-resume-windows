"""MQO (v0.6.17, issue #42): a continuation queued for opening with no marker, proven by its client id.

The probe calls exactly the methods it declared, stops before adding anything where the app holds the conversation,
adds one item with no marker under a client id of no one's, follows the queue while the person opens the
conversation, and looks for that client id in Codex's history the way core proves a marker-free continuation
delivered (measure._client_recorded: LocalSource.marker_rows, which engine/reconcile.py reads). It records booleans
and a bucket only, and its verdict stays blocked for the person who watched. Nothing here opens a real Codex.

    PYTHONPATH=src python -m unittest discover -s advanced/tests
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
import advancedcase  # noqa: E402,F401  (puts src, advanced/src and tests on the path)
from codex_auto_resume_advanced import measure, measured  # noqa: E402
from codex_auto_resume_advanced.codex import protocol  # noqa: E402
from codex_auto_resume_advanced.vocabulary import Measurement, Verdict  # noqa: E402
from test_advanced_measure_stage4 import THREAD, VERSIONS, Backend, FakeSession  # noqa: E402

MQO = Measurement.MQO
ITEM = {"id": "q", "clientUserMessageId": measure._SAMPLE_MQO_CLIENT_ID}


class MqoCase(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(self.dir, ignore_errors=True))
        for name, value in (("_MQO_OPEN_SECONDS", 0.05), ("_MQO_FIND_SECONDS", 0.05), ("_M2B_POLL_SECONDS", 0.01)):
            patcher = patch.object(measure, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.sessions, self.looked_for = [], []
        # Who holds a conversation is core's loaded check and Restart Manager on its writer lock (measure._look), never a
        # list from the probe's own session: the conversations `held_now` names are held, by the app, by one process.
        self.held_now = ()
        patcher = patch.object(measure, "_look", lambda ctx, thread: (thread in self.held_now,
                                                                      1 if thread in self.held_now else 0))
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_one(self, *, held=(), lists=None, recorded=True):
        """MQO against a fake: the app holds `held`; each thread/queue/list answers the next of `lists` (the last
        again once they run out); the history has the client id or not (`recorded`)."""
        answers = list(lists if lists is not None else ([ITEM], []))

        def queue_list(_params):
            return {"data": answers.pop(0) if len(answers) > 1 else answers[0]}
        self.held_now = tuple(held)
        replies = {"thread/queue/add": {"queuedSubmissionId": "q"}, "thread/queue/list": queue_list}

        def factory(measurement):
            self.sessions.append(FakeSession(measurement, replies))
            return self.sessions[-1]

        def history(ctx, client_id):
            self.looked_for.append(client_id)
            return recorded
        with patch.object(measure, "_client_recorded", history):
            summary = measure.run(MQO, session_factory=factory, backend=Backend(), versions=VERSIONS, thread=THREAD,
                                  clock=lambda: 1_800_000_000.0, directory=self.dir)
        return summary, json.loads(Path(summary["recorded"]).read_text(encoding="utf-8"))

    def calls(self):
        return [(method, params) for session in self.sessions for method, params in session.calls]


class ShapeTests(MqoCase):
    def test_it_declares_its_three_methods_and_has_a_probe(self):
        self.assertEqual(protocol.MEASUREMENT_METHODS[MQO], ("thread/queue/add", "thread/queue/list"))
        self.assertIs(measure.PROBES[MQO], measure._mqo)
        self.assertEqual(measured.MEASURED[MQO][0], Verdict.PASS, "the run of 2026-10-20 passed")

    def test_queued_then_taken_on_open_and_found_by_its_client_id_in_the_history(self):
        summary, record = self.run_one()
        self.assertEqual(record["verdict"], Verdict.BLOCKED, "the person who watched settles it")
        observed = record["observed"]
        self.assertEqual({key: observed[key] for key in ("held_before", "add_accepted", "queued_while_not_held",
                                                          "taken", "client_id_on_user_item")},
                         {"held_before": False, "add_accepted": True, "queued_while_not_held": True, "taken": True,
                          "client_id_on_user_item": True})
        self.assertEqual(self.looked_for[:1], [measure._SAMPLE_MQO_CLIENT_ID], "core's proof, by that client id")
        (add,) = [params for method, params in self.calls() if method == "thread/queue/add"]
        self.assertEqual(add["clientUserMessageId"], measure._SAMPLE_MQO_CLIENT_ID)
        self.assertNotIn("codex-auto-resume", json.dumps(add), "no marker")
        self.assertTrue({method for method, _params in self.calls()} <= set(protocol.MEASUREMENT_METHODS[MQO]))
        self.assertIn("open the throwaway conversation in the Desktop", record["note"])

    def test_a_conversation_the_app_holds_is_not_added_to(self):
        summary, record = self.run_one(held=(THREAD,))
        self.assertEqual(record["observed"]["held_before"], True)
        self.assertNotIn("thread/queue/add", [method for method, _params in self.calls()])

    def test_not_taken_in_time_and_the_history_is_not_read(self):
        summary, record = self.run_one(lists=([ITEM],), recorded=True)
        self.assertEqual((record["observed"]["taken"], record["observed"]["client_id_on_user_item"]), (False, False))
        self.assertEqual(self.looked_for, [])

    def test_the_record_is_content_free(self):
        summary, record = self.run_one()
        text = json.dumps(record)
        for secret in (THREAD, measure._SAMPLE_MQO_CLIENT_ID, measure._M2B_PROMPT):
            self.assertNotIn(secret, text)
        self.assertTrue(all(isinstance(value, (bool, int, str)) for value in record["observed"].values()))

    def test_the_client_id_look_is_cores_own_delivery_proof(self):
        """The look reads LocalSource.marker_rows with the client id - what core's reconcile follows a marker-free
        continuation by (engine/reconcile.py) - so a pass means marker-free can prove it."""
        found = []

        class Source:
            def __init__(self, home):
                pass

            def marker_rows(self, thread, token):
                found.append((thread, token))
                return [object()]
        ctx = measure.Context(MQO, backend=Backend(home=self.dir), thread=THREAD)
        with patch("codex_auto_resume.codex.LocalSource", Source):
            self.assertTrue(measure._client_recorded(ctx, measure._SAMPLE_MQO_CLIENT_ID))
        self.assertEqual(found, [(THREAD, measure._SAMPLE_MQO_CLIENT_ID)])
        reconcile = (Path(measure.__file__).resolve().parents[2].parent / "src" / "codex_auto_resume" / "engine"
                     / "reconcile.py").read_text(encoding="utf-8")
        self.assertIn("self.source.marker_rows(thread, marker)", reconcile)



THREADS = ("0a1b2c3d-0001-7000-8000-0000000000a1", "0a1b2c3d-0001-7000-8000-0000000000a2",
           "0a1b2c3d-0001-7000-8000-0000000000a3")


class MqpTests(MqoCase):
    """MQP (v0.6.17): two to four conversations sent to at once, each under its own client id."""

    def run_mqp(self, *, threads=THREADS, held=(), crossed=False, late=()):
        seen = {}

        def queue_list(params):
            thread = params["threadId"]
            index = list(threads).index(thread)
            looks = seen[thread] = seen.get(thread, 0) + 1
            if looks > 1:
                return {"data": []}                      # taken: the person opened it
            mine = measure._SAMPLE_MQP_CLIENT_IDS[index]
            other = measure._SAMPLE_MQP_CLIENT_IDS[(index + 1) % len(threads)]
            return {"data": [{"clientUserMessageId": mine}] + ([{"clientUserMessageId": other}] if crossed else [])}
        self.held_now = tuple(held)
        replies = {"thread/queue/add": {"queuedSubmissionId": "q"}, "thread/queue/list": queue_list}

        def factory(measurement):
            self.sessions.append(FakeSession(measurement, replies))
            return self.sessions[-1]

        reads = {}

        def history(ctx, thread, client_id):
            own = client_id == measure._SAMPLE_MQP_CLIENT_IDS[list(threads).index(thread)]
            reads[thread] = reads.get(thread, 0) + 1
            return own and not (thread in late and reads[thread] == 1)     # `late`: written only by the second read
        with patch.object(measure, "_recorded_in", history):
            summary = measure.run(Measurement.MQP, session_factory=factory, backend=Backend(), versions=VERSIONS,
                                  thread=",".join(threads), clock=lambda: 1_800_000_000.0, directory=self.dir)
        return json.loads(Path(summary["recorded"]).read_text(encoding="utf-8"))

    def test_it_declares_its_methods_and_has_a_probe(self):
        self.assertEqual(protocol.MEASUREMENT_METHODS[Measurement.MQP],
                         ("thread/queue/add", "thread/queue/list"))
        self.assertIs(measure.PROBES[Measurement.MQP], measure._mqp)
        self.assertEqual(measured.MEASURED[Measurement.MQP][0], Verdict.PASS, "the run of 2026-10-20 passed")

    def test_each_add_in_its_own_session_each_lands_in_its_own_conversation_only(self):
        record = self.run_mqp()
        self.assertEqual(record["verdict"], Verdict.BLOCKED)
        observed = record["observed"]
        self.assertEqual({key: observed[key] for key in ("conversations", "accepted", "queued_in_own",
                                                          "queued_elsewhere", "taken", "found_in_own",
                                                          "found_elsewhere")},
                         {"conversations": 3, "accepted": 3, "queued_in_own": 3, "queued_elsewhere": 0, "taken": 3,
                          "found_in_own": 3, "found_elsewhere": 0})
        adds = [params for session in self.sessions for method, params in session.calls
                if method == "thread/queue/add"]
        self.assertEqual(sorted((add["threadId"], add["clientUserMessageId"]) for add in adds),
                         sorted(zip(THREADS, measure._SAMPLE_MQP_CLIENT_IDS)))
        adders = [session for session in self.sessions
                  if [method for method, _params in session.calls] == ["thread/queue/add"]]
        self.assertEqual(len(adders), 3, "each add in a session of its own")
        text = json.dumps(record)
        for secret in THREADS + measure._SAMPLE_MQP_CLIENT_IDS:
            self.assertNotIn(secret, text)

    def test_a_message_the_history_has_only_at_the_second_read_is_found(self):
        """Fails with the one read the owner's run of 2026-10-20 made: found_in_own was 1 of 2."""
        self.assertEqual(self.run_mqp(late=(THREADS[1],))["observed"]["found_in_own"], 3)

    def test_an_item_in_another_conversations_queue_is_counted(self):
        self.assertEqual(self.run_mqp(crossed=True)["observed"]["queued_elsewhere"], 3)

    def test_one_conversation_the_app_holds_and_nothing_is_added(self):
        record = self.run_mqp(held=(THREADS[1],))
        self.assertEqual(record["observed"]["held_before"], 1)
        self.assertNotIn("thread/queue/add", [method for s in self.sessions for method, _p in s.calls])

    def test_it_takes_two_to_four_different_conversations_and_no_other_measurement_takes_a_list(self):
        for named in (THREADS[:1], THREADS + THREADS[:2], (THREADS[0], THREADS[0])):
            with self.subTest(named), self.assertRaises(measure.EvidenceUnavailable):
                measure.run(Measurement.MQP, session_factory=lambda m: None, backend=Backend(), versions=VERSIONS,
                            thread=",".join(named), directory=self.dir)
        with self.assertRaises(measure.EvidenceUnavailable):
            measure.run(MQO, session_factory=lambda m: None, backend=Backend(), versions=VERSIONS,
                        thread=",".join(THREADS[:2]), directory=self.dir)


class MqgTests(MqoCase):
    """MQG (v0.6.17): a goal set active and a continuation queued for opening, in one conversation opened."""

    def run_mqg(self, *, goal="paused", held=(), ran=2):
        statuses = [goal, "active", "active"]

        def goal_get(_params):
            status = statuses.pop(0) if len(statuses) > 1 else statuses[0]
            return {"goal": None} if goal is None else {"goal": {"status": status, "objective": "secret words"}}
        looks = []

        def queue_list(_params):
            looks.append(1)
            return {"data": [{"clientUserMessageId": measure._SAMPLE_MQG_CLIENT_ID}] if len(looks) == 1 else []}
        self.held_now = tuple(held)
        replies = {"thread/goal/get": goal_get, "thread/goal/set": {},
                   "thread/queue/add": {"queuedSubmissionId": "q"}, "thread/queue/list": queue_list}

        def factory(measurement):
            self.sessions.append(FakeSession(measurement, replies))
            return self.sessions[-1]
        with patch.object(measure, "_turns_after", lambda home, thread, first: ran), \
                patch.object(measure, "_client_recorded", lambda ctx, client_id: True), \
                patch.object(measure, "_MQG_SETTLE_SECONDS", 0.05):
            summary = measure.run(Measurement.MQG, session_factory=factory, backend=Backend(), versions=VERSIONS,
                                  thread=THREAD, clock=lambda: 1_800_000_000.0, directory=self.dir)
        return json.loads(Path(summary["recorded"]).read_text(encoding="utf-8"))

    def test_it_declares_its_methods_and_has_a_probe(self):
        self.assertEqual(protocol.MEASUREMENT_METHODS[Measurement.MQG],
                         ("thread/goal/get", "thread/goal/set", "thread/queue/add", "thread/queue/list"))
        self.assertIs(measure.PROBES[Measurement.MQG], measure._mqg)
        self.assertEqual(measured.MEASURED[Measurement.MQG][0], Verdict.PASS, "the second run of 2026-10-20 passed")

    def test_goal_set_active_message_queued_taken_and_the_turns_after_counted(self):
        record = self.run_mqg()
        self.assertEqual(record["verdict"], Verdict.BLOCKED)
        observed = record["observed"]
        self.assertEqual({key: observed[key] for key in ("goal_found", "goal_set_active", "add_accepted",
                                                          "queued_while_not_held", "taken", "turns_after_open",
                                                          "client_id_on_user_item", "goal_active_after")},
                         {"goal_found": True, "goal_set_active": True, "add_accepted": True,
                          "queued_while_not_held": True, "taken": True, "turns_after_open": 2,
                          "client_id_on_user_item": True, "goal_active_after": True})
        calls = [method for session in self.sessions for method, _params in session.calls]
        self.assertLess(calls.index("thread/goal/set"), calls.index("thread/queue/add"), "the goal first")
        (goal_set,) = [params for s in self.sessions for method, params in s.calls if method == "thread/goal/set"]
        self.assertEqual(goal_set, {"threadId": THREAD, "status": "active"}, "never an objective: never creating one")
        self.assertNotIn("secret words", json.dumps(record))
        self.assertIn("two turns ran", record["note"])

    def test_no_goal_and_nothing_is_set_or_added(self):
        record = self.run_mqg(goal=None)
        self.assertEqual(record["observed"]["goal_found"], False)
        calls = [method for session in self.sessions for method, _params in session.calls]
        self.assertNotIn("thread/goal/set", calls)
        self.assertNotIn("thread/queue/add", calls)

    def test_held_and_nothing_is_read_set_or_added(self):
        record = self.run_mqg(held=(THREAD,))
        self.assertEqual(record["observed"]["held_before"], True)
        self.assertEqual([method for session in self.sessions for method, _params in session.calls], [],
                         "who holds it is read before any session is opened")


if __name__ == "__main__":
    unittest.main()
