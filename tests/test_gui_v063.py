r"""The v0.6.3 window decisions: what the header's halo says, how it moves, and the lists
the window keeps in step with the Python side.

Like `test_gui_decisions.py`, the real compiled window is loaded and its real static methods
are called through reflection, so a rule inverted in an edit fails here rather than showing
a watcher "monitoring" while it is stopped.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

from codex_auto_resume import brand, machine, settings

ROOT = Path(__file__).resolve().parents[1]
CSC = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe"
POWERSHELL = (Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
              / "WindowsPowerShell" / "v1.0" / "powershell.exe")
NOW = 1000000.0

RUNNING = {"watcher_running": True, "enabled": True, "watcher": {"ticking": True}}

# name -> (status, pending rows, expected activity)
CASES = {
    "no_status": (None, [], "idle"),
    "watcher_unknown": ({"enabled": True}, [], "idle"),
    # A stopped watcher is grey, as it was until v0.6.3: amber is for one that runs and is not well.
    "watcher_stopped": ({"watcher_running": False, "enabled": True}, [], "idle"),
    "not_ticking": ({"watcher_running": True, "enabled": True, "watcher": {"ticking": False}}, [], "attention"),
    "upgrade_pending": (dict(RUNNING, upgrade_pending=True), [], "attention"),
    # A pause wins over everything that is waiting: nothing is recovered while paused.
    "paused": (dict(RUNNING, enabled=False), [{"code": "waiting_reset", "eligible_at": NOW - 5}], "paused"),
    "nothing": (RUNNING, [], "monitoring"),
    "waiting": (RUNNING, [{"code": "waiting_reset", "eligible_at": NOW + 600}], "waiting"),
    "due": (RUNNING, [{"code": "scheduled", "eligible_at": NOW - 1}], "checking"),
    "running_in_codex": (RUNNING, [{"code": "turn_running"}], "recovering"),
    "recovering_beats_due": (RUNNING, [{"code": "scheduled", "eligible_at": NOW - 1},
                                       {"code": "submitted"}], "recovering"),
    # No pending list, because it could not be read: the status's own count decides, so an
    # unreadable list is never shown as nothing to do, and an alarm still wins.
    "unreadable_waiting": (dict(RUNNING, pending=2), None, "waiting"),
    "unreadable_nothing": (dict(RUNNING, pending=0), None, "monitoring"),
    "unreadable_upgrade": (dict(RUNNING, upgrade_pending=True, pending=2), None, "attention"),
}

# Custom messages as the counter under the box sees them: line breaks, characters outside
# the Basic Multilingual Plane, and surrogates left unpaired.
TEXTS = ("", "plain words", "two\r\nlines\r\n", "\U0001f9e9" * 1200, "a\U0001f9e9b",
         "\U00020000\U0002a6d6", "\ud83e", "\udde9", "\ud83e🧩", "\udde9\ud83e")

STATES = ("monitoring", "waiting", "checking", "recovering", "paused", "attention", "failed", "idle")
MOMENTS = (0.0, 300.0, 600.0, 1200.0, 1800.0, 5000.0)

PROBE = r"""
$ErrorActionPreference = 'Stop'
$assembly = [Reflection.Assembly]::LoadFile($env:CAR_EXE)
$form = $assembly.GetType('CodexAutoResume.SettingsForm', $true)
$halo = $assembly.GetType('CodexAutoResume.HaloDot', $true)
$flags = [Reflection.BindingFlags]'Static,NonPublic,Public'
$activity = $form.GetMethod('Activity', $flags)
$opacity = $halo.GetMethod('HaloOpacity', $flags)
$loops = $halo.GetMethod('Loops', $flags)
$once = $halo.GetMethod('PulsesOnce', $flags)
$length = $form.GetMethod('CustomLength', $flags)
foreach ($pair in @(@('Activity', $activity), @('HaloOpacity', $opacity), @('Loops', $loops), @('PulsesOnce', $once), @('CustomLength', $length))) {
    if (-not $pair[1]) { throw ('missing ' + $pair[0]) }
}

function To-Value {
    param($value)
    if ($null -eq $value) { return $null }
    if ($value -is [bool]) { return [bool]$value }
    if ($value -is [string]) { return [string]$value }
    if ($value -is [Array]) {
        $list = New-Object 'System.Collections.Generic.List[object]'
        foreach ($item in $value) { $list.Add((To-Value $item)) }
        return ,$list
    }
    if ($value -is [Management.Automation.PSCustomObject]) {
        $map = New-Object 'System.Collections.Generic.Dictionary[string,object]'
        foreach ($field in $value.PSObject.Properties) { $map.Add([string]$field.Name, (To-Value $field.Value)) }
        return ,$map
    }
    return [double]$value
}

$out = @{ activity = @{}; opacity = @{}; loops = @{}; once = @{}; lengths = @() }
foreach ($case in (ConvertFrom-Json $env:CAR_CASES).PSObject.Properties) {
    $status = $null
    if ($null -ne $case.Value.status) { $status = [Collections.Generic.Dictionary[string,object]](To-Value $case.Value.status) }
    $pending = New-Object 'System.Collections.Generic.List[object]'
    foreach ($row in $case.Value.pending) { $pending.Add([Collections.Generic.Dictionary[string,object]](To-Value $row)) }
    # A list that could not be read reaches Activity as no list at all.
    if ($case.Value.unreadable) { $pending = $null }
    # Cast at the call: a PowerShell variable hands reflection its PSObject wrapper otherwise.
    $out.activity[$case.Name] = [string]$activity.Invoke($null, [object[]]@($status, [Collections.Generic.List[object]]$pending, [double]$env:CAR_NOW))
}
foreach ($state in (ConvertFrom-Json $env:CAR_STATES)) {
    $out.loops[$state] = [bool]$loops.Invoke($null, [object[]]@([string]$state))
    $out.once[$state] = [bool]$once.Invoke($null, [object[]]@([string]$state))
    $out.opacity[$state] = @{ moving = @(); reduced = @() }
    foreach ($ms in (ConvertFrom-Json $env:CAR_MOMENTS)) {
        # The same moment for the breathing clock and for the time since the state was entered.
        $out.opacity[$state].moving += [double]$opacity.Invoke($null, [object[]]@([string]$state, [double]$ms, [double]$ms, $false))
        $out.opacity[$state].reduced += [double]$opacity.Invoke($null, [object[]]@([string]$state, [double]$ms, [double]$ms, $true))
    }
}
foreach ($text in (ConvertFrom-Json $env:CAR_TEXTS)) {
    $out.lengths += [int]$length.Invoke($null, [object[]]@([string]$text))
}
$out | ConvertTo-Json -Depth 6 -Compress
"""


@unittest.skipUnless(CSC.is_file() and POWERSHELL.is_file(), "needs the in-box compiler and PowerShell")
class AliveStateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        work = Path(cls.folder.name)
        exe = work / "CodexAutoResumeSettings.exe"
        subprocess.run([str(CSC), "/nologo", "/target:winexe", "/platform:x64", "/out:" + str(exe),
                        "/reference:System.dll", "/reference:System.Drawing.dll",
                        "/reference:System.Windows.Forms.dll",
                        *[str(ROOT / "gui" / name)
                          for name in ("SettingsApp.cs", "Dashboard.cs", "Controls.cs", "Brand.cs")]],
                       check=True, capture_output=True, timeout=300)
        probe = work / "probe.ps1"
        probe.write_text(PROBE, encoding="utf-8")
        cases = {name: {"status": status, "pending": pending or [], "unreadable": pending is None}
                 for name, (status, pending, _) in CASES.items()}
        cls.result = subprocess.run(
            [str(POWERSHELL), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(probe)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600,
            env=dict(os.environ, CAR_EXE=str(exe), CAR_NOW=str(NOW), CAR_CASES=json.dumps(cases),
                     CAR_STATES=json.dumps(list(STATES)), CAR_MOMENTS=json.dumps(list(MOMENTS)),
                     # ASCII, surrogates escaped: an unpaired one cannot cross an environment block.
                     CAR_TEXTS=json.dumps(list(TEXTS))))
        cls.answer = (json.loads(cls.result.stdout)
                      if cls.result.returncode == 0 and cls.result.stdout.strip() else {})

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def setUp(self):
        if not self.answer:
            self.fail("the probe did not run: " + (self.result.stderr or self.result.stdout)[-2000:])

    def test_the_header_says_what_the_watcher_is_doing(self):
        for name, (_, _, expected) in sorted(CASES.items()):
            with self.subTest(name):
                self.assertEqual(self.answer["activity"][name], expected)

    def test_only_the_working_states_loop_and_only_the_alarms_pulse_once(self):
        self.assertEqual({state for state in STATES if self.answer["loops"][state]},
                         {"monitoring", "checking", "recovering"})
        self.assertEqual({state for state in STATES if self.answer["once"][state]},
                         {"attention", "failed"})

    def test_monitoring_breathes_within_the_glow_range(self):
        values = self.answer["opacity"]["monitoring"]["moving"]
        self.assertGreater(max(values) - min(values), 0.1, "it does not visibly breathe")
        for value in values:
            self.assertGreaterEqual(value, brand.GLOW["monitoring_low"] - 1e-9)
            self.assertLessEqual(value, brand.GLOW["monitoring_high"] + 1e-9)

    def test_nothing_moves_when_motion_is_reduced(self):
        for state in STATES:
            with self.subTest(state):
                self.assertEqual(len(set(round(v, 6) for v in self.answer["opacity"][state]["reduced"])), 1,
                                 "the halo still changes with motion reduced")

    def test_still_states_have_no_halo_and_waiting_holds_one(self):
        for state in ("paused", "idle"):
            self.assertEqual(set(self.answer["opacity"][state]["moving"]), {0})
        waiting = set(round(v, 6) for v in self.answer["opacity"]["waiting"]["moving"])
        self.assertEqual(len(waiting), 1)
        self.assertGreater(waiting.pop(), 0)

    def test_an_alarm_pulses_once_and_then_holds(self):
        values = self.answer["opacity"]["attention"]["moving"]
        still = brand.GLOW["still"]
        self.assertGreater(values[MOMENTS.index(600.0)], still, "no pulse on entering the state")
        for moment in (1800.0, 5000.0):
            self.assertAlmostEqual(values[MOMENTS.index(moment)], still, places=9)

    def test_the_custom_message_counter_counts_what_the_settings_layer_counts(self):
        """Code points of the text as stored, as Python's len() counts them - not UTF-16 units,
        which showed 1200 emoji as a red "2400 / 2000" over a message Save accepts."""
        self.assertEqual(len(self.answer["lengths"]), len(TEXTS))
        for index, text in enumerate(TEXTS):
            with self.subTest(index):
                self.assertEqual(self.answer["lengths"][index], len(text.replace("\r\n", "\n")))


class ReviewedRulesTests(unittest.TestCase):
    """Window rules a pre-release review of v0.6.3 found broken, pinned where an edit would
    quietly undo them. None of them can be seen without High Contrast, a right-click, a
    minimized window or a particular width, which is how each one got past."""

    def setUp(self):
        self.dashboard = (ROOT / "gui" / "Dashboard.cs").read_text(encoding="utf-8")
        self.window = (ROOT / "gui" / "SettingsApp.cs").read_text(encoding="utf-8")
        self.controls = (ROOT / "gui" / "Controls.cs").read_text(encoding="utf-8")
        self.card = self.controls[self.controls.index("internal sealed class ChoiceCard"):
                                  self.controls.index("internal sealed class ChoiceGroup")]

    @staticmethod
    def method(source, signature):
        start = source.index(signature)
        return source[start:source.index("\n        }\n", start)]

    def test_text_on_a_high_contrast_highlight_is_highlight_text(self):
        """Every contrast theme pairs Highlight with HighlightText. WindowText on it was under
        1.5:1 in Aquatic and Desert, and a radio dot in Highlight on it was not there at all."""
        paint = self.method(self.card, "protected override void OnPaint(")
        self.assertIn("bool onHighlight = Checked && Palette.Contrast;", paint)
        self.assertEqual(paint.count("onHighlight ? SystemColors.HighlightText"), 3,
                         "the radio mark, the title and the help")
        combo = self.method(self.controls, "protected override void OnDrawItem(")
        self.assertIn("highlighted && Palette.Contrast ? SystemColors.HighlightText", combo)
        cell = self.method(self.dashboard, "private void DrawCell(")
        self.assertIn("Palette.Contrast && selected ? ink : Soft.Mix(ink, Secondary, 0.4)", cell)
        self.assertEqual(cell.count("Soft.Mix(ink, Secondary"), 1)

    def test_only_a_left_click_switches_auto_resume(self):
        """A ListView raises MouseClick for the right button too, and off asks nothing."""
        start = self.dashboard.index("pendingList.MouseClick +=")
        handler = self.dashboard[start:self.dashboard.index("};", start)]
        self.assertIn("if (e.Button != MouseButtons.Left) return;", handler)
        self.assertLess(handler.index("MouseButtons.Left"), handler.index("ToggleAutoResume"))

    def test_a_refresh_decides_the_header_dot_once(self):
        """Each change of state restarts the halo, so a coarse state and then the refined one
        in the same refresh made an alarm pulse again every five seconds."""
        status = self.method(self.window, "private void ApplyStatus(")
        self.assertEqual(status.count("stateDot.State ="), 1)
        self.assertRegex(status, r"if \(snapshot == null\)\s+stateDot\.State =",
                         "with a snapshot on screen, UpdateCountdowns decides the dot")
        self.assertNotIn("stateDot.State", self.method(self.dashboard, "private void ApplySnapshot("))
        countdowns = self.method(self.dashboard, "private void UpdateCountdowns(")
        self.assertEqual(countdowns.count("stateDot.State ="), 1)
        self.assertLess(countdowns.index("stateDot.State ="), countdowns.index("if (unreadable)"),
                        "an unreadable pending list must still leave the dot decided")

    def test_a_restored_window_starts_the_halo_again(self):
        """Minimizing stops the timer; a restore changes neither the state nor the visibility."""
        self.assertIn("stateDot.Sync();", self.method(self.window, "protected override void OnResize("))

    def test_a_choice_card_measures_its_text_in_the_column_it_draws_it_in(self):
        for signature in ("internal int HeightFor(", "protected override void OnPaint("):
            with self.subTest(signature):
                self.assertIn("TextColumn(", self.method(self.card, signature))
        self.assertNotIn("Soft.Px(52)", self.card, "a width worked out a second way drifts again")


class KeptInStepTests(unittest.TestCase):
    def setUp(self):
        self.dashboard = (ROOT / "gui" / "Dashboard.cs").read_text(encoding="utf-8")
        self.window = (ROOT / "gui" / "SettingsApp.cs").read_text(encoding="utf-8")
        self.controls = (ROOT / "gui" / "Controls.cs").read_text(encoding="utf-8")

    def test_why_it_is_waiting_lists_the_watchers_checks_in_its_order(self):
        declared = re.search(r"GateOrder\s*=\s*\{([^}]*)\}", self.dashboard)
        self.assertIsNotNone(declared)
        self.assertEqual(tuple(re.findall(r'"([a-z_]+)"', declared.group(1))), machine.GATES)

    def test_every_gate_and_result_has_words(self):
        english = json.loads((ROOT / "src" / "codex_auto_resume" / "locales" / "en.json").read_text(encoding="utf-8"))
        for name in machine.GATES:
            self.assertIn("gate." + name, english)
        for result in ("pass", "wait", "block", "unknown"):
            self.assertIn("gate.result." + result, english)

    def test_every_settings_group_the_window_shows_has_a_section(self):
        shown = {entry["group"] for entry in settings.describe()} - {"advanced"}
        placed = set(re.findall(r'group == "([a-z]+)"', self.window))
        # General and Continuation are laid out by hand rather than routed by group.
        self.assertLessEqual(shown - {"general", "continuation"}, placed)
        self.assertIn('"continuation_language"', self.window)
        self.assertIn('"interface_language"', self.window)

    def test_the_soft_controls_take_every_colour_from_the_palette(self):
        literal = re.findall(r"Color\.FromArgb\(\s*0x", self.controls)
        self.assertEqual(literal, [], "a hexadecimal colour in Controls.cs belongs in brand.py")
        self.assertNotIn("DeviceDpi", "\n".join(line for line in self.controls.splitlines()
                                                 if not line.lstrip().startswith("//")))

    def test_the_window_never_writes_a_custom_message_it_did_not_show(self):
        """Blank means "not set", and a Windows line break is stored as a plain one - the
        only change the window makes to what somebody typed."""
        method = self.window[self.window.index("private static string TextJson("):]
        method = method[:method.index("\n        }\n")]
        self.assertIn('Replace("\\r\\n", "\\n")', method)
        self.assertIn('"null"', method)
        self.assertNotIn("Substring", method, "the window must not cut a message to length")


if __name__ == "__main__":
    unittest.main()
