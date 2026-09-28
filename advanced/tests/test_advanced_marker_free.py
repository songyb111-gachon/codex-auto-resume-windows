"""The marker-free continuation: sent with no marker, proven by the client id core derives (P15).

Held against the shipped definition and the shipped statement, and against core's own engine,
store and simulated Codex home (tests/codexsim.py): off until armed; watched, it only journals;
armed, core sends the words with no marker through this channel's one `thread/queue/add`, under
the id it derived from the interruption, and proves delivery by that id; the unit is spent before
the send; past its ceilings core sends with the marker as the standard edition does; a send it
cannot prove is held as an uncertain submission, never sent again, and turns it off; MCP cannot
arm it; and with the package gone the standard edition follows what it sent and sends only what
the standard edition sends.

No test opens a real Codex or starts a process: the channel's session speaks to a fake app
server that puts the item into codexsim's queue, the way Codex's own would.

    PYTHONPATH=src python -m unittest discover -s advanced/tests
"""
from __future__ import annotations

import contextlib
import json
from pathlib import Path
import queue
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import advancedcase as ac  # noqa: E402
from advancedcase import ENGINE  # noqa: E402
from codex_auto_resume import config  # noqa: E402
from codex_auto_resume.codex.errors import AdapterError  # noqa: E402
from codex_auto_resume.domain import ids  # noqa: E402
from codex_auto_resume.domain.plug import BACKEND, DEFER, Alternative, Point  # noqa: E402
from codex_auto_resume.engine import Engine  # noqa: E402
from codex_auto_resume.store import Store  # noqa: E402
from codex_auto_resume.win.kernel import NO_WINDOW  # noqa: E402
from codex_auto_resume_advanced import statement  # noqa: E402
from codex_auto_resume_advanced.codex import protocol  # noqa: E402
from codex_auto_resume_advanced.engine import markerfree  # noqa: E402
from codex_auto_resume_advanced.engine.markerfree import MarkerFreeContinuation  # noqa: E402
from codex_auto_resume_advanced.registry import MARKER_FREE, Registry  # noqa: E402
from codex_auto_resume_advanced.vocabulary import (Actor, ArmingState, ArmingWarning,  # noqa: E402
                                                   JournalCode, Measurement, OffReason, Verdict)
from test_engine import T1  # noqa: E402
from test_plug_points import PluggedCase  # noqa: E402

CAP = "marker_free_continuation"


class _Stdin:
    def __init__(self, server):
        self.server, self.buffer = server, ""

    def write(self, text):
        self.buffer += text
        while "\n" in self.buffer:
            line, self.buffer = self.buffer.split("\n", 1)
            if line.strip():
                self.server.receive(json.loads(line))

    def flush(self):
        pass

    def close(self):
        self.server.lines.put("")


class _Stdout:
    def __init__(self, lines):
        self.lines = lines

    def readline(self, _limit=-1):
        try:
            return self.lines.get(timeout=10)
        except queue.Empty:
            return ""

    def close(self):
        pass


class FakeAppServer:
    """`codex app-server --stdio` as the channel meets it: it answers initialize, and
    thread/queue/add puts the item into codexsim's queue under the clientUserMessageId it came
    with - which Codex keeps as the queued item's client_id and the message's clientId - and the
    desktop app starts it at once, or leaves it queued. `refuse` answers the add with Codex's
    error instead; `vanish` answers it as added and keeps nothing. `on_add` is told of each add
    as it arrives."""

    def __init__(self, h, *, refuse=False, dispatch=True, on_add=None, vanish=False):
        self.h, self.refuse, self.dispatch, self.on_add = h, refuse, dispatch, on_add
        self.vanish = vanish
        self.lines = queue.Queue()
        self.received, self.started = [], []
        self.stdin, self.stdout = _Stdin(self), _Stdout(self.lines)

    def popen(self, *arguments, **options):
        self.started.append(options)
        return self

    def send(self, message):
        self.lines.put(json.dumps(message) + "\n")

    def receive(self, message):
        self.received.append(message)
        method, ident, params = message.get("method"), message.get("id"), message.get("params") or {}
        if ident is None:
            return
        if method == "initialize":
            self.send({"id": ident, "result": {"codexHome": str(self.h.home.root.resolve())}})
        elif method == "thread/queue/add":
            if self.on_add:
                self.on_add(params)
            if self.refuse:
                self.send({"id": ident, "error": {"code": -32600, "message": "refused"}})
                return
            if self.vanish:
                self.send({"id": ident, "result": {"queuedSubmissionId": "0a1b2c3d-0001-7000-8000-0000000000ee"}})
                return
            queued = self.h.home.enqueue(params["threadId"], params["input"][0]["text"],
                                         client_id=params.get("clientUserMessageId"))
            if self.dispatch:
                self.h.home.dispatch(params["threadId"])
            self.send({"id": ident, "result": {"queuedSubmissionId": queued}})
        else:
            self.send({"id": ident, "error": {"code": -32601, "message": "unknown"}})

    def adds(self):
        return [message["params"] for message in self.received if message.get("method") == "thread/queue/add"]

    def wait(self, timeout=None):
        return 0

    def terminate(self):
        pass


class FakeBackend:
    """Core's Backend as a Session uses it, pointing at the harness's Codex home."""

    def __init__(self, home):
        self.codex_home, self.engine_version = Path(home).resolve(), ENGINE

    def _compatible(self):
        return {}

    def _argv(self):
        return ["codex"]

    def _environment(self):
        return {}


class MarkerFreeCase(PluggedCase):
    """The engine's own harness, with an advanced plug that ships only this capability, its
    shipped statement, and a view and measurements on which it arms with no warning:
    recovery_turn_tracking COMPATIBLE on ENGINE, M7 passed on ENGINE."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.where = Path(temporary.name)
        self.compat = ac.view(state="COMPATIBLE", capability="recovery_turn_tracking", version=ENGINE)
        self.measured = {Measurement.M7: (Verdict.PASS, ENGINE)}
        super().setUp()

    def advanced(self, h=None):
        h = h or self.h
        made = ac.advanced.AdvancedPlug(
            config.Paths(self.where / "home"), registry=Registry((MARKER_FREE,)), clock=lambda: h.now,
            policy=lambda: ac.policy.NONE, view=lambda: self.compat, measured=lambda: self.measured,
            catalogs=statement.CATALOGS)
        self.addCleanup(lambda: made._runtime and made._runtime.state.close())
        return made

    def arm(self, plug, state="armed", **changes):
        runtime = plug.runtime
        request = dict(state=state, revision=MARKER_FREE.revision,
                       generation=runtime.state.meta()["generation"], acknowledged_version=ENGINE,
                       actor=Actor.DASHBOARD)
        request.update(changes)
        result = runtime.arming.arm(CAP, **request)
        self.assertTrue(result["done"], result)
        runtime.states(fresh=True)
        return result

    def server(self, h=None, **options):
        """A fake app server the channel's live session will reach, and the patches that make it
        the one it reaches: Popen gives the server, and the session is one over the harness's home."""
        h = h or self.h
        server = FakeAppServer(h, **options)
        for target, name, value in (
                (protocol.S, "Popen", server.popen),
                (MarkerFreeContinuation, "_session",
                 lambda _self: protocol.Session(FakeBackend(h.home.root), capability=CAP))):
            patcher = patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        return server

    def armed(self, h=None, state="armed", **server):
        h = h or self.h
        self.due(h)
        plug = self.advanced(h)
        self.arm(plug, state=state)
        fake = self.server(h, **server)
        self.plugged(plug, h)
        return plug, fake

    def spends(self, plug):
        with contextlib.closing(sqlite3.connect(plug.runtime.state.path)) as connection:
            return connection.execute("SELECT capability, thread_id, interruption_id FROM spend").fetchall()

    def journal(self, plug):
        return [(line["code"], line["point"], line["answer"]) for line in plug.runtime.state.journal(capability=CAP)]


class OffTests(MarkerFreeCase):
    def test_off_by_default_it_is_the_standard_edition(self):
        """Nothing armed: the marker, core's backend, no app server, nothing spent."""
        self.due()
        plug = self.advanced()
        fake = self.server()
        self.plugged(plug)
        self.h.tick()
        self.assertEqual(len(self.h.backend.send_calls), 1)
        self.assertTrue(self.prompt().endswith(self.h.record()["marker"]))
        self.assertEqual((fake.started, fake.received), ([], []))
        self.assertIs(plug.delivery({"interruption_id": ac.KEY, "thread_id": T1}), DEFER)


class ArmedTests(MarkerFreeCase):
    def test_no_marker_goes_out_under_the_derived_id_through_the_app_server_and_the_id_proves_it(self):
        plug, fake = self.armed()
        key = self.h.record()["interruption_id"]
        self.h.tick()
        self.assert_no_send()
        (add,) = fake.adds()
        self.assertEqual(add["threadId"], T1)
        self.assertEqual(add["clientUserMessageId"], ids.continuation_client_id(key))
        self.assertNotIn(ids.MARKER_PREFIX, add["input"][0]["text"])
        self.assertEqual([options["creationflags"] for options in fake.started], [NO_WINDOW])
        self.assertEqual(self.h.record()["recovery_client_id"], ids.continuation_client_id(key))
        ours = self.h.turn_ids()[-1]
        self.follow()
        row = self.h.record()
        self.assertEqual((row["state"], row["recovery_turn_id"]), ("recovered", ours))
        self.assertIn((JournalCode.ACTED, Point.DELIVERY, Alternative.CLIENT_ID), self.journal(plug))
        self.assertIn((JournalCode.ACTED, Point.SENDER, Point.SENDER), self.journal(plug))
        self.h.tick(advance=3600)
        self.assertEqual(len(fake.adds()), 1, "a recovered interruption is never resent")
        self.assert_no_send()

    def test_the_same_interruption_is_always_sent_under_the_same_id(self):
        made = [ids.continuation_client_id(ac.KEY) for _ in range(3)]
        self.assertEqual(len(set(made)), 1)
        self.assertNotEqual(made[0], ids.continuation_client_id("b" * 64))


class ShadowNeverActsTests(MarkerFreeCase):
    def test_watched_it_journals_what_it_would_have_done_and_core_sends_the_marker(self):
        """ShadowNeverActs: asked at P5 and P15, its answers written as what it would have done,
        none taken - core's backend sends with the marker, no app server is opened, nothing spent."""
        plug, fake = self.armed(state="shadow")
        self.h.tick()
        self.assertEqual(len(self.h.backend.send_calls), 1)
        self.assertTrue(self.prompt().endswith(self.h.record()["marker"]))
        self.assertEqual((fake.started, fake.received), ([], []))
        codes = {code for code, _point, _answer in self.journal(plug)}
        self.assertIn(JournalCode.WOULD_HAVE, codes)
        self.assertNotIn(JournalCode.ACTED, codes)
        self.assertEqual(self.spends(plug), [])
        self.assertNotEqual(self.h.record()["recovery_client_id"],
                            ids.continuation_client_id(self.h.record()["interruption_id"]))


class SpendBeforeSendTests(MarkerFreeCase):
    def test_the_unit_is_spent_before_the_app_server_is_asked(self):
        seen = []
        plug, fake = self.armed(on_add=lambda params: seen.append(self.spends(plug)))
        key = self.h.record()["interruption_id"]
        self.h.tick()
        self.assertEqual(seen, [[(CAP, T1, key)]], "paid for, once, before the add arrived")
        self.assertEqual(self.spends(plug), [(CAP, T1, key)])

    def test_turned_off_between_its_answer_and_the_claim_nothing_is_sent(self):
        """A disarm always wins: the ledger finds it off at the claim, holds it, and nothing goes
        - neither through the app server nor with the marker."""
        plug, fake = self.armed()
        ask = ac.advanced.AdvancedPlug.delivery

        def delivery(made, record):
            answer = ask(made, record)
            plug.runtime.arming.disarm(CAP, actor=Actor.DASHBOARD)
            return answer
        with patch.object(ac.advanced.AdvancedPlug, "delivery", delivery):
            self.h.tick()
        self.assertEqual((fake.adds(), self.h.backend.send_calls), ([], []))
        self.assertEqual(self.spends(plug), [])


class CeilingTests(MarkerFreeCase):
    def fill(self, plug, capability_thread, count):
        with plug.runtime.state._transaction() as connection:
            for index in range(count):
                plug.runtime.state.record_spend(connection, "main", CAP, capability_thread(index),
                                                "%064x" % index, self.h.now - 60)

    def test_past_its_conversation_ceiling_core_sends_the_marker_as_the_standard_edition_does(self):
        plug, fake = self.armed()
        self.fill(plug, lambda index: T1, MARKER_FREE.ceilings.per_conversation)
        self.h.tick()
        self.assertEqual(fake.adds(), [])
        self.assertEqual(len(self.h.backend.send_calls), 1)
        self.assertTrue(self.prompt().endswith(self.h.record()["marker"]))
        self.assertIn(JournalCode.CEILING, {code for code, _point, _answer in self.journal(plug)})

    def test_past_its_daily_ceiling_too(self):
        plug, fake = self.armed()
        others = ["0a1b2c3d-0001-7000-8000-%012x" % (index + 16) for index in range(MARKER_FREE.ceilings.per_day)]
        self.fill(plug, lambda index: others[index], MARKER_FREE.ceilings.per_day)
        self.h.now += 3601                               # past the global hour, inside the day
        self.h.tick()
        self.assertEqual(fake.adds(), [])
        self.assertEqual(len(self.h.backend.send_calls), 1)


class TripwireTests(MarkerFreeCase):
    def test_a_send_it_cannot_prove_is_held_never_resent_and_turns_it_off(self):
        """The app server refuses the add: nothing proves what came of it, so the record is an
        uncertain submission, exactly as one of `codex queue`'s - never sent again, by either
        route - and the tripwire for a paid send gone submission_unknown turns the capability off."""
        plug, fake = self.armed(refuse=True)
        self.h.tick()
        row = self.h.record()
        self.assertEqual((row["state"], row["last_error"]),
                         ("submission_unknown", "queue_result_unknown_do_not_resend"))
        stored = plug.runtime.state.arming()[CAP]
        self.assertEqual((stored["state"], stored["reason"]),
                         (ArmingState.OFF, OffReason.SUBMISSION_UNKNOWN))
        for _ in range(12):
            self.h.tick(advance=900)
        self.assertEqual(len(fake.adds()), 1)
        self.assert_no_send()
        self.assertEqual(self.h.record()["state"], "submission_unknown")

    def test_an_item_that_never_shows_is_held_never_resent_and_turns_it_off(self):
        """Accepted, and then nothing under its id - in the queue or the history - within the
        delivery window: an uncertain submission, as the standard path holds one."""
        plug, fake = self.armed(vanish=True)
        self.h.tick()
        self.assertEqual(self.h.record()["state"], "queued")
        for _ in range(4):
            self.h.tick(advance=60)
        row = self.h.record()
        self.assertEqual((row["state"], row["last_error"]), ("submission_unknown", "no_receipt_do_not_resend"))
        self.assertEqual(plug.runtime.state.arming()[CAP]["reason"], OffReason.SUBMISSION_UNKNOWN)
        for _ in range(12):
            self.h.tick(advance=900)
        self.assertEqual(len(fake.adds()), 1)
        self.assert_no_send()

    def test_a_hook_that_raises_trips_it_off_and_core_sends_the_marker(self):
        """Its channel was taken before the hook raised, so the claim it would have paid for is
        held - it is off now - and the next dispatch is core's own, with the marker."""
        plug, fake = self.armed()
        with patch.object(MarkerFreeContinuation, "delivery", side_effect=RuntimeError("boom")):
            self.h.tick()
        stored = plug.runtime.state.arming()[CAP]
        self.assertEqual((stored["state"], stored["reason"]), (ArmingState.OFF, OffReason.HOOK_EXCEPTION))
        self.assertEqual((fake.adds(), self.h.backend.send_calls), ([], []))
        self.h.tick(advance=61)
        self.assertEqual(fake.adds(), [])
        self.assertEqual(len(self.h.backend.send_calls), 1)
        self.assertTrue(self.prompt().endswith(self.h.record()["marker"]))

    def test_re_arming_is_always_possible_after_a_trip(self):
        plug, fake = self.armed(refuse=True)
        self.h.tick()
        self.assertEqual(plug.runtime.state.arming()[CAP]["state"], ArmingState.OFF)
        self.arm(plug)
        self.assertEqual(plug.runtime.state.arming()[CAP]["state"], ArmingState.ARMED)


class WarningTests(MarkerFreeCase):
    def test_m7_unmeasured_for_this_codex_is_a_warning_the_person_confirms_never_a_refusal(self):
        self.measured = {Measurement.M7: (Verdict.PASS, "0.158.0-alpha.2.1")}
        plug = self.advanced()
        runtime = plug.runtime
        shown = runtime.arming.statement(MARKER_FREE, "en")
        self.assertEqual([item["warning"] for item in shown["warnings"]["items"]],
                         [ArmingWarning.UNMEASURED])
        self.assertEqual(shown["departs_from"], ["A2", "A4"])
        self.assertTrue(self.arm(plug, warnings=[ArmingWarning.UNMEASURED])["done"])


class McpTests(MarkerFreeCase):
    def test_mcp_cannot_arm_it_and_may_only_read_or_turn_it_off(self):
        """McpCannotArm: a model has list and disarm and nothing that turns a capability on."""
        from codex_auto_resume_advanced import surfaces
        from codex_auto_resume_advanced.vocabulary import McpTool
        plug = self.advanced()
        self.arm(plug)
        runtime = plug.runtime
        tools = {tool["name"] for tool in surfaces.mcp(runtime, {"request": "tools"})["tools"]}
        self.assertNotIn("arm_advanced_capability", tools)
        self.assertLessEqual(tools, set(McpTool))
        refused = runtime.arming.arm(CAP, state="armed", revision=MARKER_FREE.revision,
                                     generation=runtime.state.meta()["generation"],
                                     acknowledged_version=ENGINE, actor=Actor.MCP)
        self.assertFalse(refused["done"])
        reply = surfaces.mcp(runtime, {"request": "call", "tool": McpTool.DISARM_ADVANCED_CAPABILITY,
                                       "arguments": {"capability": CAP}})
        self.assertIn("data", reply)
        self.assertEqual(runtime.state.arming()[CAP]["state"], ArmingState.OFF)


class EditionRoundTripTests(MarkerFreeCase):
    def test_with_the_package_gone_the_standard_edition_follows_it_and_sends_only_what_it_would(self):
        """EditionRoundTrip: armed, it sent one continuation with no marker, still queued. Then the
        package is gone: the standard Store opens the state as it is, and a standard engine - NULL
        plug - on it follows that record by the id it holds to its end, sends nothing for it, and
        sends the next interruption as the standard edition does, with the marker, through
        `codex queue`."""
        plug, fake = self.armed(dispatch=False)
        self.h.tick()
        self.assertEqual(self.h.record()["state"], "queued")
        self.assertEqual(len(fake.adds()), 1)
        standard_store = Store(self.h.root)
        self.addCleanup(self.h.store.close)          # the advanced run's, closed last
        (row,) = [record for record in standard_store.all_records() if record["thread_id"] == T1]
        self.assertEqual(row["recovery_client_id"], ids.continuation_client_id(row["interruption_id"]))
        self.h.store = standard_store
        self.h.engine = Engine(standard_store, self.h.source, self.h.backend, clock=lambda: self.h.now,
                               log=lambda *args: self.h.logs.append(args), options=self.h.options,
                               notify=lambda *args: self.h.notifications.append(args))
        self.h.watch(advance=1)
        self.assertEqual(self.h.record()["state"], "queued")
        self.h.home.dispatch(T1)
        self.follow()
        self.assertEqual(self.h.record()["state"], "recovered")
        self.h.tick(advance=3600)
        self.assert_no_send()
        self.assertEqual(len(fake.adds()), 1)
        # The next interruption, on another conversation, goes as the standard edition sends one.
        other = "0a1b2c3d-0001-7000-8000-00000000abcd"
        self.h.home.fail_usage(other, "0a1b2c3d-0001-7000-8000-00000000abce",
                               completed=int(self.h.now) - 10, reset=int(self.h.now) - 5)
        self.h.backend.loaded_map[other] = "loaded"
        self.h.tick()
        self.h.tick(advance=120)
        sent = [call for call in self.h.backend.send_calls if call[0] == other]
        self.assertEqual(len(sent), 1)
        (record,) = [record for record in standard_store.all_records() if record["thread_id"] == other]
        self.assertTrue(sent[0][1].endswith(record["marker"]))
        self.assertEqual(len(fake.adds()), 1)


class ChannelTests(unittest.TestCase):
    """The channel on its own: what it says of a send, and that it never raises."""

    class Session:
        def __init__(self, *, enter=None, call=None, result=None):
            self.enter, self.call_error, self.result, self.params = enter, call, result, []

        def __enter__(self):
            if self.enter:
                raise self.enter
            return self

        def call(self, method, params):
            self.params.append((method, params))
            if self.call_error:
                raise self.call_error
            return self.result

        def __exit__(self, *unused):
            return None

    def channel(self, session):
        return MarkerFreeContinuation(None, session=lambda: session)

    CID = ids.continuation_client_id("a" * 64)

    def test_it_answers_core_at_its_two_points_and_names_itself_the_channel(self):
        made = markerfree.make(None)
        self.assertIs(made.sender({}, BACKEND), made)
        self.assertIs(made.delivery({}), Alternative.CLIENT_ID)

    def test_what_core_would_not_send_is_not_started_and_nothing_is_opened(self):
        session = self.Session(enter=AssertionError("must not open"))
        for thread, prompt, client in (("t", "go", self.CID), (T1, "", self.CID), (T1, "x" * 8193, self.CID),
                                       (T1, "a\0b", self.CID), (T1, "go", "not an id")):
            with self.subTest(thread=thread, prompt=prompt[:8], client=client):
                self.assertEqual(self.channel(session).send(thread, prompt, client_id=client)["outcome"],
                                 "not_started")

    def test_no_app_server_is_not_started(self):
        reply = self.channel(self.Session(enter=AdapterError("codex_binary_unavailable"))).send(
            T1, "go", client_id=self.CID)
        self.assertEqual(reply, {"outcome": "not_started", "error_code": "queue_spawn_failed"})

    def test_a_refusal_or_no_answer_is_unknown_never_not_started(self):
        refused = protocol._refused_by_codex("thread/queue/add", -32600)
        for error, code in ((refused, "queue_result_unknown"),
                            (AdapterError("protocol_timeout"), "queue_timeout"),
                            (AdapterError("protocol_unavailable"), "queue_result_unknown")):
            with self.subTest(code=code):
                self.assertEqual(self.channel(self.Session(call=error)).send(T1, "go", client_id=self.CID),
                                 {"outcome": "unknown", "error_code": code})

    def test_accepted_with_the_queued_items_id_where_codex_says_one(self):
        queued = "0a1b2c3d-0001-7000-8000-0000000000ff"
        for result, expected in (({"queuedSubmissionId": queued}, queued), ({"id": queued}, queued),
                                 ({"queuedSubmission": {"id": queued}}, queued), ({}, None),
                                 ({"id": "x"}, None), (None, None)):
            with self.subTest(result=result):
                session = self.Session(result=result)
                reply = self.channel(session).send(T1, "go", client_id=self.CID)
                self.assertEqual(reply, {"outcome": "accepted", "queue_id": expected})
                self.assertEqual(session.params, [("thread/queue/add", {
                    "threadId": T1, "clientUserMessageId": self.CID,
                    "input": [{"type": "text", "text": "go"}]})])

    def test_with_no_client_id_the_add_names_none(self):
        session = self.Session(result={})
        self.channel(session).send(T1, "go [codex-auto-resume:0123456789abcdef]")
        self.assertNotIn("clientUserMessageId", session.params[0][1])

    def test_a_consent_refused_at_the_guard_opens_nothing(self):
        @contextlib.contextmanager
        def refusing():
            yield False
        session = self.Session(enter=AssertionError("must not open"))
        self.assertEqual(self.channel(session).send(T1, "go", launch_guard=refusing(), client_id=self.CID),
                         {"outcome": "not_started", "error_code": "queue_consent_refused"})

    def test_a_guard_that_fails_as_it_closes_asks_nothing_of_codex(self):
        @contextlib.contextmanager
        def failing():
            yield True
            raise OSError("the lock went away")
        closed = []
        session = self.Session(result={})
        session.__exit__ = lambda *unused: closed.append(True)
        self.assertEqual(self.channel(session).send(T1, "go", launch_guard=failing(), client_id=self.CID),
                         {"outcome": "not_started", "error_code": "queue_spawn_failed"})
        self.assertEqual((session.params, closed), ([], [True]))

    def test_its_session_may_call_its_one_method_and_nothing_else(self):
        allowed = protocol.methods_for_capability(CAP)
        self.assertEqual(allowed, frozenset({"initialize", "initialized", "thread/queue/add"}))
        self.assertTrue(allowed.isdisjoint(protocol.FORBIDDEN_METHODS))
        self.assertEqual(protocol.methods_for_capability("no_such"), frozenset({"initialize", "initialized"}))
        with self.assertRaises(ValueError):
            protocol.Session(FakeBackend("."))
        with self.assertRaises(ValueError):
            protocol.Session(FakeBackend("."), Measurement.M7, capability=CAP)


if __name__ == "__main__":
    unittest.main()
