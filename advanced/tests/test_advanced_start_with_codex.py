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

    def test_core_starts_the_watcher_outside_the_job_through_the_armed_capability(self):
        plug = self.plug(START_WITH_CODEX)
        self.assertTrue(plug.runtime.arming.arm(
            CAP, state=ArmingState.ARMED, revision=1,
            generation=plug.runtime.state.meta()["generation"],
            acknowledged_version=ENGINE, warnings=[], actor="dashboard")["done"])
        layer = control.Control(self.paths, plug=plug)
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


if __name__ == "__main__":
    unittest.main()
