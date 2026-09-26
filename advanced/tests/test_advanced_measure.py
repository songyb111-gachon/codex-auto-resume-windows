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

import io
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
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
        self.declined = list(declined)
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

    def test_a_protocol_that_cannot_be_reached_is_blocked_not_a_pass(self):
        def broken(_measurement):
            raise AdapterError("unavailable")
        summary = self.run_one(Measurement.M2, session_factory=broken)
        self.assertEqual(summary["verdict"], str(Verdict.BLOCKED))
        record = json.loads(Path(summary["recorded"]).read_text(encoding="utf-8"))
        self.assertIn("note", record)

    def test_the_wmi_escape_is_a_pass_only_when_it_left_the_job_and_survived(self):
        escaped = self.run_one(Measurement.MW,
                               launcher=lambda: {"started": True, "in_job": False, "survived": True})
        self.assertEqual(escaped["verdict"], str(Verdict.PASS))
        caught = self.run_one(Measurement.MW,
                              launcher=lambda: {"started": True, "in_job": True, "survived": False})
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
        self.assertEqual(facts, {"started": False, "in_job": None, "kill_on_close": False,
                                 "survived": False})

    @unittest.skipUnless(os.environ.get("CODEX_AR_LIVE_WMI") == "1" and sys.platform == "win32",
                         "opt-in: CODEX_AR_LIVE_WMI=1 runs the real WMI escape")
    def test_live_the_wmi_started_heartbeat_leaves_the_job_and_survives(self):
        facts = wmi_escape.probe()
        self.assertTrue(facts["started"], facts)
        self.assertFalse(facts["in_job"], facts)
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
