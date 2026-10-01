"""start-with-Codex: the first advanced capability, at P9 (control/codexstart.py).

Held here against the shipped definition and the shipped statement, not a test's own: that it is
off until armed, that armed it names a route and watched it only journals, that the route starts
the watcher through a windowless WMI create and reports the created pid, that it spends no
ceiling unit (it starts, it does not send), that a hook that raises trips it off, that MCP cannot
arm it, that arming touches only the advanced state, and that core carries the route out end to
end. Nothing here starts a real process or reaches WMI: `pwsh` is faked.

    PYTHONPATH=src python -m unittest discover -s advanced/tests
"""
from __future__ import annotations

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import advancedcase as ac  # noqa: E402
from advancedcase import ENGINE, THREAD, AdvancedCase  # noqa: E402
from codex_auto_resume import config, control, pwsh, startup  # noqa: E402
from codex_auto_resume.domain.plug import DEFER, Point  # noqa: E402
from codex_auto_resume_advanced import statement  # noqa: E402
from codex_auto_resume_advanced.control.codexstart import StartWithCodex  # noqa: E402
from codex_auto_resume_advanced.registry import START_WITH_CODEX, Registry  # noqa: E402
from codex_auto_resume_advanced.runtime import SENDING  # noqa: E402
from codex_auto_resume_advanced.vocabulary import (ArmingState, JournalCode, Measurement,  # noqa: E402
                                                   OffReason, Verdict)

CAP = "start_with_codex"
JOB_ENDS = {"in_job": True, "kill_on_close": True, "breakaway_ok": False, "silent_breakaway_ok": False}


def fake_pwsh(pid=4242, code=0):
    """A `pwsh.run` stand-in: writes `pid` to the pidfile and returns `code`, so `start` reads a
    pid without any process being created. It checks the script it was handed is the constant."""
    def run(script, values, *, timeout):
        assert "Win32_Process" in script and "ShowWindow" in script, "the fixed WMI script"
        assert set(values) == {"WMI_COMMAND", "WMI_PIDFILE"}, "only environment-variable values"
        if code == 0:
            Path(values["WMI_PIDFILE"]).write_text(str(pid), encoding="utf-8")
        return code
    return run


class StartWithCodexCase(AdvancedCase):
    """A home whose only capability is the shipped start-with-Codex, its shipped statement, and a
    view and measurements on which it arms with no warning: engine_present COMPATIBLE on ENGINE,
    MW passed on ENGINE."""

    def setUp(self):
        super().setUp()
        self.catalogs = statement.CATALOGS
        self.compat = ac.view(state="COMPATIBLE", capability="engine_present", version=ENGINE)
        self.measured = {Measurement.MW: (Verdict.PASS, ENGINE)}

    def armed_runtime(self):
        runtime = self.runtime(START_WITH_CODEX)
        result = self.arm(runtime, CAP)
        self.assertTrue(result["done"], result)
        runtime.states(fresh=True)
        return runtime


class ArmingTests(StartWithCodexCase):
    def test_off_by_default_offers_no_route(self):
        runtime = self.runtime(START_WITH_CODEX)
        self.assertEqual(runtime.states()[CAP], ArmingState.OFF)
        self.assertIs(runtime.ask(Point.START_ROUTE, dict(JOB_ENDS)), DEFER)

    def test_armed_it_names_a_route_and_journals_that_it_acted(self):
        runtime = self.armed_runtime()
        route = runtime.ask(Point.START_ROUTE, dict(JOB_ENDS))
        self.assertIsInstance(route, StartWithCodex)
        self.assertTrue(callable(getattr(route, "start", None)))
        codes = [line["code"] for line in runtime.state.journal(capability=CAP)]
        self.assertIn(JournalCode.ACTED, codes)

    def test_watched_it_only_journals_would_have_and_offers_no_route(self):
        """ShadowNeverActs: watched, it is asked and its answer is written as what it would have
        done, but no route is handed back for core to carry out."""
        runtime = self.runtime(START_WITH_CODEX)
        self.assertTrue(self.arm(runtime, CAP, state="shadow")["done"])
        runtime.states(fresh=True)
        self.assertIs(runtime.ask(Point.START_ROUTE, dict(JOB_ENDS)), DEFER)
        codes = [line["code"] for line in runtime.state.journal(capability=CAP)]
        self.assertIn(JournalCode.WOULD_HAVE, codes)
        self.assertNotIn(JournalCode.ACTED, codes)


class RouteTests(StartWithCodexCase):
    def test_the_route_starts_through_a_windowless_wmi_create_and_reports_the_pid(self):
        route = StartWithCodex(self.paths)
        with patch.object(pwsh, "executable", return_value="powershell.exe"), \
                patch.object(pwsh, "run", fake_pwsh(pid=7321)):
            self.assertEqual(route.start('"pythonw.exe" "launcher.py" "run"'), {"pid": 7321})

    def test_a_wmi_refusal_is_a_code_not_a_pid(self):
        route = StartWithCodex(self.paths)
        with patch.object(pwsh, "executable", return_value="powershell.exe"), \
                patch.object(pwsh, "run", fake_pwsh(code=121)):
            self.assertEqual(route.start("cmd"), {"code": 121})

    def test_without_powershell_it_refuses_and_starts_nothing(self):
        route = StartWithCodex(self.paths)
        with patch.object(pwsh, "executable", return_value=None), \
                patch.object(pwsh, "run", side_effect=AssertionError("must not run")):
            self.assertEqual(route.start("cmd"), {"code": "no_powershell"})

    def test_a_temporary_file_that_cannot_be_made_is_a_code_not_an_exception(self):
        """`start` says it never raises, and every step is inside the guard - mkstemp included. A
        temporary directory that cannot be used is a code, so core writes a WMI-refused line, not
        its `failed:` line, and the capability is neither left untripped for it nor uncounted."""
        route = StartWithCodex(self.paths)
        with patch.object(pwsh, "executable", return_value="powershell.exe"), \
                patch("codex_auto_resume_advanced.control.codexstart.tempfile.mkstemp",
                      side_effect=FileNotFoundError(2, "no such directory")), \
                patch.object(pwsh, "run", side_effect=AssertionError("must not run")):
            self.assertEqual(route.start("cmd"), {"code": "FileNotFoundError"})

    def test_a_runner_timeout_is_uncertain_not_a_refusal(self):
        """The runner's 30 s timeout kills PowerShell after Win32_Process.Create may already have
        returned, so the outcome is unknown, not "not started": the route says so with `uncertain`."""
        import subprocess
        route = StartWithCodex(self.paths)
        with patch.object(pwsh, "executable", return_value="powershell.exe"), \
                patch.object(pwsh, "run", side_effect=subprocess.TimeoutExpired("ps", 30)):
            self.assertEqual(route.start("cmd"), {"uncertain": "timeout"})


class NoSpendTests(StartWithCodexCase):
    def test_it_spends_no_ceiling_unit_it_starts_it_does_not_send(self):
        """SpendBeforeSend has no hold on it: START_ROUTE is not a sending point, so asking the
        route acts without paying a unit, and no capability-day, conversation or global count moves."""
        runtime = self.armed_runtime()
        self.assertNotIn(Point.START_ROUTE, SENDING)     # the start route spends no unit
        runtime.ask(Point.START_ROUTE, dict(JOB_ENDS))
        self.assertEqual(runtime._acted, {})
        counts = runtime.state.spent(CAP, THREAD)
        self.assertEqual(set(counts.values()), {0})


class TripwireTests(StartWithCodexCase):
    def test_a_hook_that_raises_trips_it_off(self):
        runtime = self.armed_runtime()
        with patch.object(StartWithCodex, "start_route", side_effect=RuntimeError("boom")):
            self.assertIs(runtime.ask(Point.START_ROUTE, dict(JOB_ENDS)), DEFER)
        self.assertEqual(runtime.state.arming()[CAP]["state"], ArmingState.OFF)
        self.assertEqual(runtime.state.arming()[CAP]["reason"], OffReason.HOOK_EXCEPTION)


class McpTests(StartWithCodexCase):
    def test_mcp_cannot_arm_it_and_may_only_read_or_turn_it_off(self):
        """McpCannotArm: a model reaches list and disarm and nothing that turns it on; there is no
        arm tool at all, and a call that names one is not recognized."""
        from codex_auto_resume_advanced import surfaces
        from codex_auto_resume_advanced.vocabulary import McpTool
        runtime = self.armed_runtime()
        tools = {tool["name"] for tool in surfaces.mcp(runtime, {"request": "tools"})["tools"]}
        self.assertNotIn("arm_advanced_capability", tools)
        self.assertLessEqual(tools, set(McpTool))
        # The disarm tool turns it off from a model; nothing turns it on.
        reply = surfaces.mcp(runtime, {"request": "call", "tool": McpTool.DISARM_ADVANCED_CAPABILITY,
                                       "arguments": {"capability": CAP}})
        self.assertIn("data", reply)
        self.assertEqual(runtime.state.arming()[CAP]["state"], ArmingState.OFF)


class RegistryMetadataTests(StartWithCodexCase):
    def test_it_declares_no_journal_codes_of_its_own(self):
        """Nothing ever writes swc.started or swc.refused: the journal is the runtime's own -
        ACTED where core takes the route, WOULD_HAVE where it is watched - so the definition
        declares no codes of its own, and none can be formed from it."""
        self.assertEqual(START_WITH_CODEX.codes, ())
        self.assertIsNone(START_WITH_CODEX.code("started"))
        self.assertIsNone(START_WITH_CODEX.code("refused"))

    def test_the_listing_marks_whether_a_capability_sends(self):
        """START_ROUTE is not a sending point, so start-with-Codex spends no unit and its ceilings
        never bind; a surface is told it does not send rather than shown a limit it will never
        meet. A capability that gates or sends is marked the other way."""
        (swc,) = self.runtime(START_WITH_CODEX).arming.listing()["capabilities"]
        self.assertIs(swc["sends"], False)
        (wake,) = self.runtime(ac.definition()).arming.listing()["capabilities"]
        self.assertIs(wake["sends"], True)


class EditionRoundTripTests(StartWithCodexCase):
    def test_arming_writes_only_to_the_advanced_state_the_standard_store_is_untouched(self):
        """EditionRoundTrip: start-with-Codex makes no record and sends nothing, so a standard
        installation opening this home's state finds exactly what standard would - here, none of
        it. Arming and asking the route write only advanced.sqlite; state.sqlite is never made."""
        runtime = self.armed_runtime()
        runtime.ask(Point.START_ROUTE, dict(JOB_ENDS))
        self.assertTrue((self.paths.advanced_dir / "advanced.sqlite").exists())
        self.assertFalse((self.paths.state_dir / "state.sqlite").exists(),
                         "the standard store was never opened")


class CoreCarryOutTests(StartWithCodexCase):
    """The whole path: core reaches P9, the advanced plug names the route, core builds the command
    line from the stable launcher and carries it out, and writes the one content-free line."""

    def setUp(self):
        super().setUp()
        self.paths.ensure()
        (self.paths.home / "watcher-launcher.py").write_text("# launcher\n", encoding="utf-8")

    def armed_layer(self):
        plug = self.plug(START_WITH_CODEX)
        self.assertTrue(plug.runtime.arming.arm(
            CAP, state=ArmingState.ARMED, revision=1,
            generation=plug.runtime.state.meta()["generation"],
            acknowledged_version=ENGINE, warnings=[], actor="dashboard")["done"])
        return control.Control(self.paths, plug=plug), plug

    def test_core_starts_the_watcher_outside_the_job_through_the_armed_capability(self):
        layer, _plug = self.armed_layer()
        seen = {}

        def run(script, values, *, timeout):
            seen["command"] = values["WMI_COMMAND"]
            Path(values["WMI_PIDFILE"]).write_text("5150", encoding="utf-8")
            return 0

        with patch.object(control.Control, "watcher_running", return_value=False), \
                patch.object(startup, "python_launcher", return_value=Path("pythonw.exe")), \
                patch.object(pwsh, "executable", return_value="powershell.exe"), \
                patch.object(pwsh, "run", run), \
                patch("codex_auto_resume.windows.process_context", return_value=dict(JOB_ENDS)), \
                patch("codex_auto_resume.windows.install_in_progress", return_value=False):
            line = layer.start_for_codex()
        self.assertTrue(line.endswith("started through WMI pid 5150"), line)
        self.assertIn("watcher-launcher.py", seen["command"])
        self.assertNotIn(str(self.paths.home), line)     # the log line carries no path

    def test_nothing_armed_is_the_standard_edition_at_codex_start(self):
        """An advanced installation with nothing armed answers Codex's start exactly as the
        standard edition does - "off", no watcher probe, no WMI - and reads no policy, view or
        measurement doing it (the arming has nothing on)."""
        probed = []
        for label, plug in (("advanced, nothing armed", self.plug(START_WITH_CODEX)),
                            ("standard", None)):
            layer = control.Control(self.paths, plug=plug) if plug is not None \
                else control.Control(self.paths)
            with patch.object(control.Control, "watcher_running",
                              side_effect=lambda *a: probed.append(label) or False), \
                    patch.object(pwsh, "run", side_effect=AssertionError("no WMI")), \
                    patch("codex_auto_resume.windows.process_context", return_value=dict(JOB_ENDS)), \
                    patch("codex_auto_resume.windows.install_in_progress", return_value=False):
                self.assertTrue(layer.start_for_codex().endswith("; off"), label)
        self.assertEqual(probed, [], "an unarmed advanced start touched nothing the standard one did not")

    def test_armed_it_starts_even_where_the_job_would_not_end_the_watcher(self):
        """"Start with Codex" starts the watcher whenever Codex starts. Where the job would not
        end it - not in a job, breakaway allowed, or Windows will not say - core starts it on its
        own account (the WMI route is only for the job that would end it), so the person who armed
        it is never left with "off"."""
        for context in ({"in_job": False},
                        {"in_job": True, "kill_on_close": True, "breakaway_ok": True,
                         "silent_breakaway_ok": False},
                        {"in_job": None}):
            with self.subTest(context=context):
                layer, _plug = self.armed_layer()
                with patch.object(control.Control, "watcher_running", return_value=False), \
                        patch.object(control.Control, "_launch_watcher",
                                     return_value=type("P", (), {"pid": 4242})()), \
                        patch.object(pwsh, "run", side_effect=AssertionError("no WMI off the job")), \
                        patch("codex_auto_resume.windows.process_context", return_value=dict(context)), \
                        patch("codex_auto_resume.windows.install_in_progress", return_value=False):
                    self.assertIn("started pid 4242", layer.start_for_codex())

    def test_a_pause_stops_the_start_and_no_wmi_create_is_made(self):
        """Pause stops every capability along with everything else: with recovery paused, an
        armed start-with-Codex makes no WMI create; with it on, the create is made."""
        for enabled, expected, wmi in ((False, "not started: recovery is paused", False),
                                       (True, "started through WMI pid 5150", True)):
            with self.subTest(enabled=enabled):
                layer, _plug = self.armed_layer()
                layer.set_enabled(enabled)                    # writes state.sqlite
                created = []

                def run(script, values, *, timeout):
                    created.append(1)
                    Path(values["WMI_PIDFILE"]).write_text("5150", encoding="utf-8")
                    return 0

                with patch.object(control.Control, "watcher_running", return_value=False), \
                        patch.object(startup, "python_launcher", return_value=Path("pythonw.exe")), \
                        patch.object(pwsh, "executable", return_value="powershell.exe"), \
                        patch.object(pwsh, "run", run), \
                        patch("codex_auto_resume.windows.process_context", return_value=dict(JOB_ENDS)), \
                        patch("codex_auto_resume.windows.install_in_progress", return_value=False):
                    line = layer.start_for_codex()
                self.assertTrue(line.endswith(expected), line)
                self.assertEqual(bool(created), wmi)

    def test_an_uncertain_route_is_not_written_as_a_definite_refusal(self):
        import subprocess
        layer, _plug = self.armed_layer()
        with patch.object(control.Control, "watcher_running", return_value=False), \
                patch.object(startup, "python_launcher", return_value=Path("pythonw.exe")), \
                patch.object(pwsh, "executable", return_value="powershell.exe"), \
                patch.object(pwsh, "run", side_effect=subprocess.TimeoutExpired("ps", 30)), \
                patch("codex_auto_resume.windows.process_context", return_value=dict(JOB_ENDS)), \
                patch("codex_auto_resume.windows.install_in_progress", return_value=False):
            line = layer.start_for_codex()
        self.assertTrue(line.endswith("start uncertain: WMI did not answer (timeout)"), line)
        self.assertNotIn("not started", line)


if __name__ == "__main__":
    unittest.main()
