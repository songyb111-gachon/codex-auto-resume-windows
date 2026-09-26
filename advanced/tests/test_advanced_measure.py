"""The measurement harness: what the owner runs by hand to find whether a capability can work.

Every external effect is a seam the harness is driven through, so nothing here opens a real
Codex or starts a real process: the session is a fake that answers what a test tells it, and the
launcher is a fake. What is held here is the machinery around them - that the command exists for
each of the M-list, that a run writes one content-free record in the live-acceptance envelope,
that a session may call only the methods its measurement declared, and that nothing runs unless a
person asks for it.

Run from the repository root:

    PYTHONPATH=src python -m unittest discover -s advanced/tests
"""
from __future__ import annotations

from collections import Counter
import io
import json
import os
from pathlib import Path
import queue
import shutil
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

import advancedcase as ac  # noqa: E402
from codex_auto_resume import control, controlcli  # noqa: E402
from codex_auto_resume.codex.appserver import PROTOCOL_METHODS  # noqa: E402
from codex_auto_resume.codex.errors import AdapterError  # noqa: E402
from codex_auto_resume.domain.plug import Surface  # noqa: E402
from codex_auto_resume_advanced import evidence, measure, plug as advanced  # noqa: E402
from codex_auto_resume_advanced.codex import protocol, wmi_escape  # noqa: E402
from codex_auto_resume_advanced.vocabulary import McpTool, Measurement, NoteCode, Verdict  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import live_evidence  # noqa: E402


class FakeSession:
    """A session that answers what a test set, and refuses a method its measurement did not
    declare exactly as the real one does - so a probe reaches only its own methods here too."""

    def __init__(self, measurement, *, replies=None, events=None, declined=()):
        self.measurement = Measurement(measurement)
        self.allowed = protocol.methods_for(self.measurement)
        self.replies = replies or {}
        self._events = list(events or [])
        self.declined = Counter(declined)
        self.calls = []
        self.params = []

    def __enter__(self):
        return self

    def __exit__(self, *unused):
        return False

    def call(self, method, params=None):
        if method not in self.allowed:
            raise protocol.SessionRefused("not permitted for this measurement")
        self.calls.append(method)
        self.params.append((method, params))
        reply = self.replies.get(method, {})
        if isinstance(reply, Exception):
            raise reply
        return reply

    def drain_events(self):
        return list(self._events)

    def declined_count(self):
        return sum(self.declined.values())


def setUpModule():
    # M6 follows its turn for up to three minutes; a fake that never completes one is not made
    # to wait that long here. The M6 tests set their own bounds.
    global _M6_TIMING
    _M6_TIMING = (measure._M6_TURN_SECONDS, measure._M6_INTERRUPT_SECONDS, measure._M6_POLL_SECONDS)
    measure._M6_TURN_SECONDS, measure._M6_INTERRUPT_SECONDS, measure._M6_POLL_SECONDS = 0.05, 0.05, 0.01


def tearDownModule():
    measure._M6_TURN_SECONDS, measure._M6_INTERRUPT_SECONDS, measure._M6_POLL_SECONDS = _M6_TIMING


# A UUID a person might type as the throwaway conversation. It is a Codex thread id in shape, and
# the tests hold that it never reaches the record.
SAMPLE_THREAD = "0a1b2c3d-0001-7000-8000-0000000000aa"


def factory(replies=None, events=None):
    return lambda measurement: FakeSession(measurement, replies=replies, events=events)


class FakeBackend:
    """Core's Backend as a measurement reads it: the Codex version its check found, or none."""

    def __init__(self, version="0.155.0"):
        self.engine_version = version


class AllowListTests(unittest.TestCase):
    def test_every_measurement_has_an_allow_list_and_a_probe(self):
        self.assertEqual(set(protocol.MEASUREMENT_METHODS), set(Measurement))
        self.assertEqual(set(measure.PROBES), set(Measurement))

    def test_the_extra_methods_live_only_here_beyond_cores_three(self):
        """Core's finite helper may call three methods; everything a measurement adds is here,
        and none of it is one of core's three (codex/appserver.PROTOCOL_METHODS)."""
        self.assertTrue(protocol.ADVANCED_METHODS)
        self.assertTrue(protocol.ADVANCED_METHODS.isdisjoint(set(PROTOCOL_METHODS)))

    def test_a_session_may_call_only_its_measurements_methods_and_never_a_forbidden_one(self):
        allowed = protocol.methods_for(Measurement.M2)
        self.assertIn("thread/goal/set", allowed)
        self.assertIn("initialize", allowed)
        self.assertNotIn("thread/resume", allowed)          # M6's, not M2's
        for measurement in Measurement:
            self.assertTrue(protocol.methods_for(measurement).isdisjoint(protocol.FORBIDDEN_METHODS))

    def test_a_fake_session_refuses_a_method_off_its_list(self):
        session = FakeSession(Measurement.M2)
        session.call("thread/goal/set", {"threadId": "t"})
        with self.assertRaises(protocol.SessionRefused):
            session.call("thread/resume", {"threadId": "t"})


class RecordTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(self.dir, ignore_errors=True))

    def run_one(self, measurement, *, session_factory=None, launcher=None):
        return measure.run(measurement, session_factory=session_factory, launcher=launcher,
                           versions={"product_version": "0.6.11-alpha", "codex_version": "0.155.0",
                                     "windows_build": "10.0.26200"},
                           clock=lambda: 1_800_000_000.0, directory=self.dir)

    def test_every_measurement_writes_one_content_free_record_in_the_envelope(self):
        for measurement in Measurement:
            with self.subTest(measurement):
                summary = self.run_one(measurement, session_factory=factory(),
                                       launcher=(lambda: {"started": True}) if measurement == Measurement.MW else None)
                path = Path(summary["recorded"])
                self.assertTrue(path.is_file())
                record = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(record["format"], evidence.MEASUREMENT_FORMAT)
                self.assertEqual(record["step"], str(measurement))
                self.assertIn(record["verdict"], {str(v) for v in Verdict})
                self.assertEqual(record["product_version"], "0.6.11-alpha")
                # Content-free by the same test the validator holds every committed file to.
                self.assertEqual(live_evidence.content_refusals(record), [])

    def test_the_format_tag_is_the_one_the_validator_skips(self):
        self.assertEqual(evidence.MEASUREMENT_FORMAT, live_evidence.MEASUREMENT_FORMAT)

    def test_an_empty_queue_add_that_lists_is_a_pass(self):
        summary = self.run_one(Measurement.M3, session_factory=factory(
            {"thread/queue/add": {"queuedSubmissionId": "x"}, "thread/queue/list": {"items": []}}))
        self.assertEqual(summary["verdict"], str(Verdict.PASS))

    def test_a_queue_add_that_raises_is_blocked_not_a_pass(self):
        summary = self.run_one(Measurement.M3, session_factory=factory(
            {"thread/queue/add": AdapterError("no"), "thread/queue/list": {"items": []}}))
        # The probe's own call raised, so it never reached a verdict of its own: blocked, not a pass.
        self.assertEqual(summary["verdict"], str(Verdict.BLOCKED))

    def test_every_request_carries_params_even_when_there_are_none(self):
        """Codex refuses a request without the field; the session always sends one."""
        session = protocol.Session.__new__(protocol.Session)
        session.allowed = protocol.methods_for(Measurement.M1)
        session.sequence, session._subscribed, written = 0, [], []
        session._write = written.append
        import queue as queue_module
        session.responses = queue_module.Queue()
        session.responses.put({"id": 1, "result": {"data": []}})
        self.assertEqual(session.call("thread/loaded/list"), {"data": []})
        self.assertEqual(written[0]["params"], {})

    def test_a_call_codex_refuses_is_a_fail_that_names_the_method_and_code(self):
        """What M3 found on codex-cli 0.158.0-alpha.2.1: an empty thread/queue/add is refused
        (-32600, "only user input can be added"). Codex was reached and said no, so the capability's
        premise fails - a fail, not "not reached" - and its words are never recorded."""
        refusal = protocol._refused_by_codex("thread/queue/add", -32600)
        self.assertIsInstance(refusal, AdapterError)
        summary = self.run_one(Measurement.M3, session_factory=factory(
            {"thread/queue/add": refusal, "thread/queue/list": {"items": []}}))
        self.assertEqual(summary["verdict"], str(Verdict.FAIL))
        record = json.loads(Path(summary["recorded"]).read_text(encoding="utf-8"))
        self.assertEqual((record["observed"]["refused_method"], record["observed"]["refusal_code"]),
                         ("thread/queue/add", -32600))
        self.assertNotIn("only user input", json.dumps(record))

    def test_a_protocol_that_cannot_be_reached_is_blocked_not_a_pass(self):
        def broken(_measurement):
            raise AdapterError("unavailable")
        summary = self.run_one(Measurement.M2, session_factory=broken)
        self.assertEqual(summary["verdict"], str(Verdict.BLOCKED))
        record = json.loads(Path(summary["recorded"]).read_text(encoding="utf-8"))
        self.assertIn("note", record)

    def test_the_wmi_escape_is_a_pass_only_when_nothing_can_end_the_watcher(self):
        held = {"started": True, "kill_on_close": True, "survived": True}
        # In a job of Windows' own with no KILL_ON_JOB_CLOSE - what WMI really gives - is a pass;
        # the first version asked for no job at all and blocked a working escape.
        for in_job in (False, True):
            with self.subTest(in_job=in_job):
                escaped = self.run_one(Measurement.MW, launcher=lambda: dict(
                    held, in_job=in_job, job_kills_on_close=False))
                self.assertEqual(escaped["verdict"], str(Verdict.PASS))
        for broken in ({"job_kills_on_close": True, "in_job": True}, {"survived": False},
                       {"kill_on_close": False}, {"started": False}):
            with self.subTest(broken):
                caught = self.run_one(Measurement.MW, launcher=lambda: {
                    **held, "in_job": True, "job_kills_on_close": False, **broken})
                self.assertEqual(caught["verdict"], str(Verdict.BLOCKED))

    def test_the_wmi_measurement_without_a_launcher_is_blocked(self):
        self.assertEqual(self.run_one(Measurement.MW)["verdict"], str(Verdict.BLOCKED))

    def test_a_free_string_in_an_observation_is_refused(self):
        with self.assertRaises(evidence.EvidenceError):
            evidence.build(Measurement.M1, Verdict.PASS, {"note": "a whole sentence"},
                           product_version="0.6.11", codex_version="0.155.0",
                           windows_build="10.0.0", recorded_at="2026-01-01T00:00Z")

    def test_a_record_written_here_is_skipped_by_the_validator_and_not_an_error(self):
        self.run_one(Measurement.M3, session_factory=factory())
        result = live_evidence.review(self.dir, product_version="0.6.11-alpha")
        self.assertEqual(result["refusals"], [])
        self.assertEqual(result["files"], [])            # not counted towards acceptance
        self.assertEqual(len(result["measurements"]), 1)


# What codex-cli 0.158.0-alpha.2.1's schema says each request's refusal is (ServerRequest.json and
# each *Response.json), written out here rather than read from protocol.DECLINE_ANSWERS, so the
# table cannot drift and take its test with it.
SCHEMA_REFUSALS = {
    "item/commandExecution/requestApproval": {"decision": "decline"},
    "item/fileChange/requestApproval": {"decision": "decline"},
    "item/permissions/requestApproval": {"permissions": {}, "scope": "turn"},
    "execCommandApproval": {"decision": {"denied": {"rejection": "declined by codex-auto-resume"}}},
    "applyPatchApproval": {"decision": {"denied": {"rejection": "declined by codex-auto-resume"}}},
    "item/tool/requestUserInput": {"answers": {}},
    "mcpServer/elicitation/request": {"action": "decline", "content": None},
}
# Every request the schema lets Codex make of a client, the answered and the never-answered.
SCHEMA_SERVER_REQUESTS = set(SCHEMA_REFUSALS) | {
    "item/tool/call", "account/chatgptAuthTokens/refresh", "attestation/generate", "currentTime/read"}
# Every word in those response types that grants something: a decision that runs or allows, a
# persisted rule, a session-wide scope. Nothing the session sends may hold one.
SCHEMA_ACCEPTING = {
    "accept", "acceptForSession", "acceptWithExecpolicyAmendment", "applyNetworkPolicyAmendment",
    "approved", "approved_for_session", "approved_execpolicy_amendment",
    "approved_mcp_policy_amendment", "network_policy_amendment", "allow", "session"}


def _words(value):
    if isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from _words(item)
    elif isinstance(value, list):
        for item in value:
            yield from _words(item)
    elif isinstance(value, str):
        yield value


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
    """`codex app-server --stdio` as M6 meets it, in the shapes of codex-cli 0.158.0-alpha.2.1's
    schema: it answers initialize, thread/resume, turn/start, turn/interrupt and thread/unsubscribe;
    after turn/start (and `delay`) it asks the client each of `requests`; and once every one is
    answered it sends turn/completed - or, with `completes=False`, only when interrupted. It keeps
    everything the client wrote, and each answer by the id it asked with."""

    TURN = "deadbeef-0000-7000-8000-00000000beef"

    def __init__(self, home, requests=(), *, completes=True, delay=0.0):
        self.home, self.requests, self.completes, self.delay = home, list(requests), completes, delay
        self.lines = queue.Queue()
        self.received, self.answers, self.asked = [], {}, {}
        self.thread = None
        self.stdin, self.stdout = _Stdin(self), _Stdout(self.lines)

    def send(self, message):
        self.lines.put(json.dumps(message) + "\n")

    def receive(self, message):
        self.received.append(message)
        method, ident = message.get("method"), message.get("id")
        if method is None:                            # the client answering a request of ours
            self.answers[ident] = message
            if self.completes and len(self.answers) == len(self.requests):
                self.finish("completed")
            return
        if ident is None:                             # a notification (initialized)
            return
        params = message.get("params") or {}
        if method == "initialize":
            self.send({"id": ident, "result": {"codexHome": str(self.home), "userAgent": "fake"}})
        elif method == "thread/resume":
            self.thread = params.get("threadId")
            self.send({"id": ident, "result": {"thread": {"id": self.thread}}})
        elif method == "turn/start":
            self.send({"id": ident, "result": {"turn": {"id": self.TURN, "status": "inProgress",
                                                         "items": []}}})
            self.send({"method": "turn/started", "params": {"threadId": self.thread,
                                                            "turn": {"id": self.TURN}}})
            if self.delay:
                threading.Timer(self.delay, self.ask).start()
            else:
                self.ask()
        elif method == "turn/interrupt":
            self.send({"id": ident, "result": {}})
            self.finish("interrupted")
        elif method == "thread/unsubscribe":
            self.send({"id": ident, "result": {"status": "unsubscribed"}})
        else:
            self.send({"id": ident, "error": {"code": -32601, "message": "unknown"}})

    def ask(self):
        for number, (method, params) in enumerate(self.requests):
            # Codex's ids may be numbers or strings; the answer must carry the one it was asked with.
            ident = 9000 + number if number % 2 else "srv-%d" % number
            self.asked[ident] = method
            self.send({"id": ident, "method": method, "params": params})
        if self.completes and not self.requests:
            self.finish("completed")

    def finish(self, status):
        self.send({"method": "turn/completed",
                   "params": {"threadId": self.thread,
                              "turn": {"id": self.TURN, "status": status, "items": []}}})

    def wait(self, timeout=None):
        return 0

    def terminate(self):
        pass

    def calls(self, method):
        return [message for message in self.received if message.get("method") == method]


class SessionBackend:
    """Core's Backend as a Session uses it, pointing at a temporary home and no real Codex."""

    def __init__(self, home):
        self.codex_home, self.engine_version = home, "0.158.0-alpha.2.1"

    def _compatible(self):
        return {}

    def _argv(self):
        return ["codex"]

    def _environment(self):
        return {}


# Each request with the shape of its schema's params, and fields that invite an accepting answer.
EVERY_REQUEST = [
    ("item/commandExecution/requestApproval",
     {"threadId": SAMPLE_THREAD, "turnId": FakeAppServer.TURN, "itemId": "i1", "startedAtMs": 1,
      "command": "whoami", "availableDecisions": ["accept", "acceptForSession", "decline"],
      "proposedExecpolicyAmendment": ["whoami"]}),
    ("item/fileChange/requestApproval",
     {"threadId": SAMPLE_THREAD, "turnId": FakeAppServer.TURN, "itemId": "i2", "startedAtMs": 1}),
    ("item/permissions/requestApproval",
     {"threadId": SAMPLE_THREAD, "turnId": FakeAppServer.TURN, "itemId": "i3", "startedAtMs": 1,
      "cwd": "C:/work", "permissions": {"network": {"enabled": True}}}),
    ("execCommandApproval", {"conversationId": SAMPLE_THREAD, "callId": "c1", "command": ["whoami"],
                             "cwd": "C:/work", "parsedCmd": []}),
    ("applyPatchApproval", {"conversationId": SAMPLE_THREAD, "callId": "c2", "fileChanges": {}}),
    ("item/tool/requestUserInput", {"threadId": SAMPLE_THREAD, "turnId": FakeAppServer.TURN,
                                    "itemId": "i4", "isBlocking": True,
                                    "questions": [{"id": "q", "question": "Allow?"}]}),
    ("mcpServer/elicitation/request", {"threadId": SAMPLE_THREAD, "serverName": "s",
                                       "mode": "form", "message": "Accept?"}),
    ("account/chatgptAuthTokens/refresh", {"reason": "unauthorized"}),
    ("attestation/generate", {}),
    ("item/tool/call", {"threadId": SAMPLE_THREAD, "tool": "t", "arguments": {}}),
    ("currentTime/read", {}),
]


class M6Tests(unittest.TestCase):
    """M6 against a fake app-server stream: the real Session answers what Codex asks - each
    approval with its schema's own refusal, never an accepting one - and the probe follows the
    turn until Codex says it completed."""

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(self.dir, ignore_errors=True))
        self.home = (self.dir / "home").resolve()
        self.home.mkdir()
        for name, value in (("_M6_TURN_SECONDS", 10.0), ("_M6_INTERRUPT_SECONDS", 5.0),
                            ("_M6_POLL_SECONDS", 0.01)):
            patcher = patch.object(measure, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def run_m6(self, server):
        sessions = []

        def opening(measurement):
            sessions.append(protocol.Session(SessionBackend(self.home), measurement))
            return sessions[-1]

        with patch.object(protocol.S, "Popen", lambda *a, **k: server):
            summary = measure.run(Measurement.M6, session_factory=opening, thread=SAMPLE_THREAD,
                                  versions={"product_version": "0.6.11-alpha",
                                            "codex_version": "0.158.0-alpha.2.1",
                                            "windows_build": "10.0.26200"},
                                  clock=lambda: 1_800_000_000.0, directory=self.dir)
        record = json.loads(Path(summary["recorded"]).read_text(encoding="utf-8"))
        return summary, record, sessions[0]

    def test_each_request_is_answered_with_its_schemas_refusal_and_counted(self):
        server = FakeAppServer(self.home, EVERY_REQUEST)
        summary, record, session = self.run_m6(server)
        self.assertEqual(set(server.answers), set(server.asked))
        for ident, method in server.asked.items():
            with self.subTest(method):
                answer = server.answers[ident]
                if method in SCHEMA_REFUSALS:
                    self.assertEqual(answer, {"id": ident, "result": SCHEMA_REFUSALS[method]})
                else:
                    # Never answered with what it asks - a token, an attestation, a tool result.
                    self.assertNotIn("result", answer)
                    self.assertEqual(answer["error"]["code"], -32601)
        self.assertEqual(session.declined, Counter({method: 1 for method in SCHEMA_REFUSALS}))
        self.assertEqual(session.refused, Counter({
            "account/chatgptAuthTokens/refresh": 1, "attestation/generate": 1,
            "item/tool/call": 1, "currentTime/read": 1}))
        self.assertEqual(summary["verdict"], str(Verdict.BLOCKED))     # the person confirms
        self.assertEqual(record["observed"], {"approvals_declined": 7, "turn_status": "completed",
                                              "turn_ended_by_itself": True, "unsubscribed": True,
                                              "thread_given": True})
        self.assertEqual(live_evidence.content_refusals(record), [])
        self.assertNotIn(SAMPLE_THREAD, json.dumps(record))

    def test_nothing_the_session_sends_accepts_anything(self):
        server = FakeAppServer(self.home, EVERY_REQUEST)
        self.run_m6(server)
        for message in server.received:
            with self.subTest(message.get("method") or message.get("id")):
                self.assertTrue(set(_words(message)).isdisjoint(SCHEMA_ACCEPTING), message)

    def test_the_turn_asks_for_whoami_under_untrusted_approvals_and_a_read_only_sandbox(self):
        server = FakeAppServer(self.home, EVERY_REQUEST[:1])
        self.run_m6(server)
        (resume,) = server.calls("thread/resume")
        self.assertEqual(resume["params"], {"threadId": SAMPLE_THREAD, "excludeTurns": True})
        (start,) = server.calls("turn/start")
        params = start["params"]
        self.assertEqual(params["threadId"], SAMPLE_THREAD)
        self.assertEqual(len(params["input"]), 1)
        self.assertEqual(params["input"][0]["type"], "text")
        self.assertIn("whoami", params["input"][0]["text"])
        self.assertEqual(params["approvalPolicy"], "untrusted")
        self.assertEqual(params["approvalsReviewer"], "user")
        self.assertEqual(params["sandboxPolicy"]["type"], "readOnly")
        self.assertEqual(server.calls("turn/interrupt"), [])
        # Unsubscribed once, after the turn - by the probe, not again by the session's exit.
        (unsubscribe,) = server.calls("thread/unsubscribe")
        self.assertEqual(unsubscribe["params"], {"threadId": SAMPLE_THREAD})
        self.assertGreater(server.received.index(unsubscribe), server.received.index(start))

    def test_the_probe_waits_for_the_turn_to_complete(self):
        # Codex asks only after a while, and completes only once answered: a probe that read the
        # notifications once and left would see neither.
        server = FakeAppServer(self.home, EVERY_REQUEST[:1], delay=0.4)
        _summary, record, session = self.run_m6(server)
        self.assertEqual(record["observed"]["approvals_declined"], 1)
        self.assertEqual(record["observed"]["turn_status"], "completed")
        self.assertIs(record["observed"]["turn_ended_by_itself"], True)
        self.assertEqual(server.calls("turn/interrupt"), [])
        self.assertEqual(session.declined, Counter({"item/commandExecution/requestApproval": 1}))

    def test_a_turn_that_does_not_end_is_interrupted_at_the_bound(self):
        server = FakeAppServer(self.home, EVERY_REQUEST[:2], completes=False)
        with patch.object(measure, "_M6_TURN_SECONDS", 0.3):
            _summary, record, _session = self.run_m6(server)
        (interrupt,) = server.calls("turn/interrupt")
        self.assertEqual(interrupt["params"], {"threadId": SAMPLE_THREAD, "turnId": FakeAppServer.TURN})
        self.assertEqual(record["observed"]["approvals_declined"], 2)
        self.assertEqual(record["observed"]["turn_status"], "interrupted")
        self.assertIs(record["observed"]["turn_ended_by_itself"], False)
        self.assertEqual(record["verdict"], str(Verdict.BLOCKED))


class RefusalTests(unittest.TestCase):
    """Every decision the session can send, enumerated: whatever Codex asks, the reply is one of
    the schema's refusals or an error, and nothing in it accepts."""

    def test_the_table_is_the_schemas_refusals_and_names_only_requests_codex_makes(self):
        self.assertEqual(protocol.DECLINE_ANSWERS, SCHEMA_REFUSALS)
        self.assertEqual(protocol.DECLINED_REQUESTS, frozenset(SCHEMA_REFUSALS))
        self.assertTrue(set(protocol.DECLINE_ANSWERS) <= SCHEMA_SERVER_REQUESTS)
        self.assertTrue(set(protocol.DECLINE_ANSWERS).isdisjoint(protocol.FORBIDDEN_METHODS))
        self.assertTrue(SCHEMA_ACCEPTING <= protocol.ACCEPTING_WORDS)

    def test_every_decision_the_code_can_send_is_a_refusal(self):
        methods = sorted(SCHEMA_SERVER_REQUESTS) + sorted(protocol.FORBIDDEN_METHODS) + [
            "accept", "approved", "Item/CommandExecution/RequestApproval",
            "item/commandExecution/requestApproval ", "commandExecution/approval", "", None, 7,
            ["item/fileChange/requestApproval"], {"method": "execCommandApproval"}, True]
        params = [None, {}, {"availableDecisions": ["accept"]}, {"decision": "accept"},
                  {"permissions": {"network": {"enabled": True}}}, "accept", [1, 2]]
        sent = []
        for method in methods:
            for param in params:
                for ident in (1, "x", None):
                    request = {"id": ident, "method": method, "params": param}
                    reply = protocol.reply_to(request)
                    json.dumps(reply)                            # always writable
                    self.assertEqual(reply["id"], ident)
                    self.assertEqual(set(reply) - {"id"}, {"result"} if "result" in reply else {"error"})
                    sent.append(reply)
        for reply in (protocol.reply_to(None), protocol.reply_to([]), protocol.reply_to("x")):
            self.assertIn("error", reply)
            sent.append(reply)
        decisions = [reply["result"] for reply in sent if "result" in reply]
        # Every decision the code sent is one of the schema's refusals, and every refusal was sent.
        self.assertEqual({json.dumps(d, sort_keys=True) for d in decisions},
                         {json.dumps(r, sort_keys=True) for r in SCHEMA_REFUSALS.values()})
        for decision in decisions:
            self.assertTrue(set(_words(decision)).isdisjoint(SCHEMA_ACCEPTING), decision)
            self.assertEqual(decision.get("permissions", {}), {})
            self.assertEqual(decision.get("answers", {}), {})
            self.assertIsNone(decision.get("content"))
            self.assertIn(decision.get("action", "decline"), {"decline", "cancel"})
        for reply in sent:
            if "error" in reply:
                self.assertEqual(reply["error"]["code"], -32601)

    def test_a_reply_cannot_be_changed_by_changing_the_one_sent_before(self):
        first = protocol.reply_to({"id": 1, "method": "item/permissions/requestApproval"})
        first["result"]["permissions"]["network"] = {"enabled": True}
        again = protocol.reply_to({"id": 2, "method": "item/permissions/requestApproval"})
        self.assertEqual(again["result"], {"permissions": {}, "scope": "turn"})

    def test_an_accepting_entry_in_the_table_is_never_sent(self):
        """The table is checked again when a reply is made: an accepting entry, however it got
        there, becomes an error, not an acceptance."""
        for method, tampered in (("item/commandExecution/requestApproval", {"decision": "accept"}),
                                 ("execCommandApproval", {"decision": "approved"}),
                                 ("item/permissions/requestApproval",
                                  {"permissions": {"network": {"enabled": True}}}),
                                 ("item/tool/requestUserInput", {"answers": {"q": {"answers": ["y"]}}}),
                                 ("mcpServer/elicitation/request", {"action": "accept"}),
                                 ("item/fileChange/requestApproval", {"decision": "acceptForSession"})):
            with self.subTest(method), patch.dict(protocol.DECLINE_ANSWERS, {method: tampered}):
                reply = protocol.reply_to({"id": 1, "method": method})
                self.assertNotIn("result", reply)
                self.assertEqual(reply["error"]["code"], -32601)

    @unittest.skipUnless(os.environ.get("CODEX_AR_SCHEMA_DIR"),
                         "opt-in: CODEX_AR_SCHEMA_DIR names a generated app-server schema")
    def test_the_refusals_match_a_generated_schema(self):
        schema = Path(os.environ["CODEX_AR_SCHEMA_DIR"])
        requests = json.loads((schema / "ServerRequest.json").read_text(encoding="utf-8"))
        named = {branch["properties"]["method"]["enum"][0] for branch in requests["oneOf"]}
        self.assertEqual(named, SCHEMA_SERVER_REQUESTS)
        responses = {"item/commandExecution/requestApproval": "CommandExecutionRequestApprovalResponse",
                     "item/fileChange/requestApproval": "FileChangeRequestApprovalResponse",
                     "item/permissions/requestApproval": "PermissionsRequestApprovalResponse",
                     "execCommandApproval": "ExecCommandApprovalResponse",
                     "applyPatchApproval": "ApplyPatchApprovalResponse",
                     "item/tool/requestUserInput": "ToolRequestUserInputResponse",
                     "mcpServer/elicitation/request": "McpServerElicitationRequestResponse"}
        for method, name in responses.items():
            with self.subTest(method):
                shape = json.loads((schema / (name + ".json")).read_text(encoding="utf-8"))
                refusal = protocol.DECLINE_ANSWERS[method]
                self.assertTrue(set(shape.get("required", [])) <= set(refusal))
                self.assertTrue(set(refusal) <= set(shape["properties"]))
                text = json.dumps(shape)
                for word in _words(refusal):
                    if word in ("decline", "denied", "rejection", "turn"):
                        self.assertIn('"%s"' % word, text)


class ThreadTests(unittest.TestCase):
    """A measurement can be pointed at a real throwaway conversation, and the record still holds
    only that one was given - never the id."""

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(self.dir, ignore_errors=True))

    def run_one(self, measurement, *, thread=None, session_factory=None):
        return measure.run(measurement, session_factory=session_factory or factory(), thread=thread,
                           versions={"product_version": "0.6.11-alpha", "codex_version": "0.155.0",
                                     "windows_build": "10.0.26200"},
                           clock=lambda: 1_800_000_000.0, directory=self.dir)

    def test_a_given_thread_is_recorded_only_as_a_boolean_never_the_id(self):
        summary = self.run_one(Measurement.M3, thread=SAMPLE_THREAD)
        self.assertIs(summary["observed"]["thread_given"], True)
        text = Path(summary["recorded"]).read_text(encoding="utf-8")
        self.assertNotIn(SAMPLE_THREAD, text)
        self.assertNotIn(SAMPLE_THREAD[:8], text)
        record = json.loads(text)
        self.assertIs(record["observed"]["thread_given"], True)
        self.assertEqual(live_evidence.content_refusals(record), [])

    def test_no_thread_records_that_none_was_given(self):
        summary = self.run_one(Measurement.M3)
        self.assertIs(summary["observed"]["thread_given"], False)

    def test_a_given_thread_is_the_one_the_probe_calls_with(self):
        seen = []

        def capturing(measurement):
            session = FakeSession(measurement,
                                  replies={"thread/queue/add": {}, "thread/queue/list": {}})
            seen.append(session)
            return session

        self.run_one(Measurement.M3, thread=SAMPLE_THREAD, session_factory=capturing)
        threads = {params.get("threadId") for _method, params in seen[0].params
                   if isinstance(params, dict) and "threadId" in params}
        self.assertEqual(threads, {SAMPLE_THREAD})

    def test_a_conversation_id_that_is_not_a_thread_id_is_refused_and_nothing_is_written(self):
        with self.assertRaises(measure.EvidenceUnavailable):
            self.run_one(Measurement.M3, thread="not-a-thread-id")
        self.assertEqual(sorted(self.dir.iterdir()), [])

    def test_the_bridge_refuses_a_non_string_thread(self):
        # A structural guard in the surface, before the harness: a thread that is not even text.
        from codex_auto_resume_advanced import surfaces
        result = surfaces.measure(_UnusedRuntime(), "m3", {"nested": "object"})
        self.assertFalse(result["done"])


class _UnusedRuntime:
    def run_measurement(self, *a, **k):     # pragma: no cover - a bad request never reaches this
        raise AssertionError("a bad request must not reach the runtime")


class VerdictTests(unittest.TestCase):
    """After a probe leaves a verdict blocked, a person completes it with measure-verdict: a pass
    or a fail and one closed note code, appended to the blocked record for this Codex version."""

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(self.dir, ignore_errors=True))

    def _blocked(self, measurement=Measurement.M1, codex_version="0.155.0"):
        record = evidence.build(measurement, Verdict.BLOCKED, {"thread_given": False},
                                product_version="0.6.11-alpha", codex_version=codex_version,
                                windows_build="10.0.26200", recorded_at="2026-09-26T09:00Z",
                                note="open the thread and confirm, then set the verdict")
        return evidence.write(record, directory=self.dir)

    def test_a_completion_is_appended_to_the_blocked_record(self):
        self._blocked()
        target = evidence.complete(Measurement.M1, Verdict.PASS, NoteCode.AS_EXPECTED,
                                   codex_version="0.155.0", recorded_at="2026-09-26T09:05Z",
                                   directory=self.dir)
        record = json.loads(target.read_text(encoding="utf-8"))
        self.assertEqual(record["verdict"], str(Verdict.BLOCKED))       # the probe's finding stays
        self.assertEqual(record["completion"],
                         {"verdict": "pass", "note": "as_expected", "recorded_at": "2026-09-26T09:05Z"})
        self.assertEqual(live_evidence.content_refusals(record), [])

    def test_a_completion_for_another_codex_is_refused(self):
        self._blocked(codex_version="0.155.0")
        with self.assertRaises(evidence.EvidenceError):
            evidence.complete(Measurement.M1, Verdict.FAIL, NoteCode.NOT_AS_EXPECTED,
                              codex_version="0.156.0", recorded_at="2026-09-26T09:05Z",
                              directory=self.dir)

    def test_only_a_blocked_record_can_be_completed(self):
        record = evidence.build(Measurement.M3, Verdict.PASS, {"thread_given": False},
                                product_version="0.6.11-alpha", codex_version="0.155.0",
                                windows_build="10.0.26200", recorded_at="2026-09-26T09:00Z")
        evidence.write(record, directory=self.dir)
        with self.assertRaises(evidence.EvidenceError):
            evidence.complete(Measurement.M3, Verdict.PASS, NoteCode.AS_EXPECTED,
                              codex_version="0.155.0", recorded_at="2026-09-26T09:05Z",
                              directory=self.dir)

    def test_a_completion_with_no_record_is_refused(self):
        with self.assertRaises(evidence.EvidenceError):
            evidence.complete(Measurement.M2, Verdict.PASS, NoteCode.AS_EXPECTED,
                              codex_version="0.155.0", recorded_at="2026-09-26T09:05Z",
                              directory=self.dir)

    def test_a_completion_is_a_pass_or_a_fail_only(self):
        self._blocked()
        with self.assertRaises(evidence.EvidenceError):
            evidence.complete(Measurement.M1, Verdict.BLOCKED, NoteCode.AS_EXPECTED,
                              codex_version="0.155.0", recorded_at="2026-09-26T09:05Z",
                              directory=self.dir)


class VerdictBridgeTests(ac.AdvancedCase):
    """measure-verdict is the Dashboard's, reachable from the long-lived bridge like measure, and
    reached by no MCP tool."""

    def setUp(self):
        super().setUp()
        self.paths.ensure()
        self.evidence_dir = Path(self.home).parent / "evidence"
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        self.plug_obj = advanced.AdvancedPlug(self.paths, measure_session_factory=factory(),
                                              measure_backend=FakeBackend("0.155.0"),
                                              evidence_dir=self.evidence_dir, **self.options())
        self.control = control.Control(self.paths, plug=self.plug_obj)

    def bridge(self, command, argument):
        request = {"id": 1, "command": command, "argument": argument}
        out = io.StringIO()
        controlcli.serve(self.control, io.StringIO(json.dumps(request) + "\n"), out)
        return json.loads(out.getvalue())["reply"]

    def test_a_blocked_measurement_is_completed_from_the_bridge(self):
        self.assertTrue(self.bridge("measure", {"measurement": "m1"})["ok"])
        reply = self.bridge("measure-verdict",
                            {"measurement": "m1", "verdict": "pass", "note": "as_expected"})
        self.assertTrue(reply["ok"], reply)
        self.assertTrue(reply["result"]["done"])
        record = json.loads((self.evidence_dir / "measurement-m1.json").read_text(encoding="utf-8"))
        self.assertEqual(record["completion"]["verdict"], "pass")

    def test_a_verdict_for_a_measurement_with_no_record_is_refused(self):
        reply = self.bridge("measure-verdict",
                            {"measurement": "m2", "verdict": "fail", "note": "not_as_expected"})
        self.assertFalse(reply["result"]["done"])

    def test_an_unknown_note_code_is_refused(self):
        self.bridge("measure", {"measurement": "m1"})
        reply = self.bridge("measure-verdict",
                            {"measurement": "m1", "verdict": "pass", "note": "looked fine to me"})
        self.assertFalse(reply["result"]["done"])

    def test_an_unexpected_argument_is_refused(self):
        reply = self.bridge("measure-verdict",
                            {"measurement": "m1", "verdict": "pass", "note": "as_expected",
                             "thread": SAMPLE_THREAD})
        self.assertFalse(reply["result"]["done"])

    def test_no_mcp_tool_completes_a_measurement(self):
        self.assertNotIn("measure-verdict", {str(tool) for tool in McpTool})
        tools = self.plug_obj.surface(Surface.MCP, {"request": "tools"})["tools"]
        self.assertTrue(all("verdict" not in tool["name"] for tool in tools))


class WmiEscapeTests(unittest.TestCase):
    """MW's launcher, driven with fakes: nothing here starts a real process or touches product
    state. The one real chain is the opt-in live test below."""

    def test_the_heartbeat_writes_only_its_job_words(self):
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder) / "heartbeat.json"
            with patch.object(wmi_escape, "_HEARTBEAT_SECONDS", 0.0), \
                    patch("codex_auto_resume.win.kernel.process_context",
                          return_value={"in_job": False, "kill_on_close": False}):
                wmi_escape._heartbeat_main(str(out))
            data = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(set(data), {"pid", "in_job", "kill_on_close"})
        self.assertIs(data["in_job"], False)
        self.assertIsInstance(data["pid"], int)

    def test_the_helper_asks_wmi_with_showwindow_zero_and_never_createflags(self):
        seen = {}

        def fake_run(script, values, *, timeout):
            seen["script"], seen["values"] = script, values
            return 0

        with patch.object(wmi_escape, "_HELPER_SECONDS", 0.0), \
                patch("codex_auto_resume.pwsh.run", fake_run):
            wmi_escape._helper_main("srcpaths", "C:\\tmp\\work", "C:\\py\\pythonw.exe",
                                    "C:\\tmp\\work\\bootstrap.py")
        self.assertIn("ShowWindow", seen["script"])
        self.assertNotIn("CreateFlags", seen["script"])
        self.assertIn("heartbeat", seen["values"]["HEARTBEAT_CMD"])
        self.assertIn("heartbeat.json", seen["values"]["HEARTBEAT_CMD"])

    def test_the_role_dispatcher_routes_to_each_hand(self):
        calls = []
        with patch.object(wmi_escape, "_helper_main", lambda *a: calls.append(("helper", a))), \
                patch.object(wmi_escape, "_heartbeat_main", lambda *a: calls.append(("heartbeat", a))):
            wmi_escape._role("helper", "srcpaths", ["work", "pythonw", "bootstrap"])
            wmi_escape._role("heartbeat", "srcpaths", ["out.json"])
        self.assertEqual(calls[0], ("helper", ("srcpaths", "work", "pythonw", "bootstrap")))
        self.assertEqual(calls[1], ("heartbeat", ("out.json",)))

    def test_without_a_windowless_interpreter_nothing_is_started(self):
        from codex_auto_resume import startup
        with patch.object(startup, "python_launcher", side_effect=startup.StartupError("none")):
            facts = wmi_escape.probe()
        self.assertEqual(facts, {"started": False, "in_job": None, "job_kills_on_close": None,
                                 "kill_on_close": False, "survived": False})

    @unittest.skipUnless(os.environ.get("CODEX_AR_LIVE_WMI") == "1" and sys.platform == "win32",
                         "opt-in: CODEX_AR_LIVE_WMI=1 runs the real WMI escape")
    def test_live_the_wmi_started_heartbeat_leaves_the_job_and_survives(self):
        facts = wmi_escape.probe()
        self.assertTrue(facts["started"], facts)
        self.assertFalse(facts["job_kills_on_close"], facts)
        self.assertTrue(facts["kill_on_close"], facts)
        self.assertTrue(facts["survived"], facts)


class InvocationTests(ac.AdvancedCase):
    """Nothing runs unless a person asks: the harness runs only when a surface is invoked with a
    measurement, and it reaches the plug only through the long-lived bridge, the Dashboard's."""

    def setUp(self):
        super().setUp()
        self.paths.ensure()
        self.evidence_dir = Path(self.home).parent / "evidence"
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        self.opened = []

        def watching_factory(measurement):
            self.opened.append(str(measurement))
            return FakeSession(measurement)

        self.plug_obj = advanced.AdvancedPlug(self.paths, measure_session_factory=watching_factory,
                                              measure_backend=FakeBackend(),
                                              evidence_dir=self.evidence_dir, **self.options())
        self.control = control.Control(self.paths, plug=self.plug_obj)

    def bridge(self, command, argument):
        request = {"id": 1, "command": command, "argument": argument}
        out = io.StringIO()
        controlcli.serve(self.control, io.StringIO(json.dumps(request) + "\n"), out)
        return json.loads(out.getvalue())["reply"]

    def test_building_the_edition_runs_no_measurement(self):
        # Constructing the plug and reading its badge opens no session and writes no record.
        self.plug_obj.surface(Surface.STATUS, {})
        self.assertEqual(self.opened, [])
        self.assertEqual(sorted(self.evidence_dir.iterdir()), [])

    def test_the_dashboard_runs_a_measurement_and_it_is_recorded(self):
        reply = self.bridge("measure", {"measurement": "m3"})
        self.assertTrue(reply["ok"], reply)
        self.assertTrue(reply["result"]["done"])
        self.assertEqual(reply["result"]["measurement"], "m3")
        self.assertEqual(self.opened, ["m3"])
        self.assertTrue((self.evidence_dir / "measurement-m3.json").is_file())

    def test_a_record_says_which_codex_it_measured(self):
        """The Dashboard's run opens the installed Codex and records the version it checked -
        the one fact a measurement decides a capability by (C7). It recorded "unknown" always,
        since the backend it opened was never handed to the record."""
        opened = []

        class Found:
            def __init__(self, codex_home, codex_exe):
                self.engine_version = None

            def _compatible(self):
                self.engine_version = "0.155.0"
                return {}

        def session(backend, measurement):
            opened.append(backend.engine_version)
            return FakeSession(measurement)

        live = advanced.AdvancedPlug(self.paths, evidence_dir=self.evidence_dir, **self.options())
        self.control = control.Control(self.paths, plug=live)
        with patch("codex_auto_resume.codex.transport.Backend", Found), \
                patch.object(measure.config, "discover_codex_exe", return_value=Path("codex.exe")), \
                patch.object(measure, "Session", session):
            reply = self.bridge("measure", {"measurement": "m3"})
        self.assertTrue(reply["result"]["done"], reply)
        record = json.loads((self.evidence_dir / "measurement-m3.json").read_text(encoding="utf-8"))
        self.assertEqual(record["codex_version"], "0.155.0")
        self.assertEqual(opened, ["0.155.0"])

    def test_a_run_that_cannot_say_which_codex_records_nothing(self):
        unknown = advanced.AdvancedPlug(self.paths, measure_session_factory=factory(),
                                        measure_backend=FakeBackend(None),
                                        evidence_dir=self.evidence_dir, **self.options())
        self.control = control.Control(self.paths, plug=unknown)
        reply = self.bridge("measure", {"measurement": "m3"})
        self.assertFalse(reply["result"]["done"])
        self.assertEqual(sorted(self.evidence_dir.iterdir()), [])

    def test_an_unknown_measurement_id_is_refused(self):
        reply = self.bridge("measure", {"measurement": "m99"})
        self.assertFalse(reply["result"]["done"])
        self.assertEqual(self.opened, [])

    def test_no_mcp_tool_runs_a_measurement(self):
        self.assertNotIn("measure", {str(tool) for tool in McpTool})
        tools = self.plug_obj.surface(Surface.MCP, {"request": "tools"})["tools"]
        self.assertTrue(all("measure" not in tool["name"] for tool in tools))


if __name__ == "__main__":
    unittest.main()
