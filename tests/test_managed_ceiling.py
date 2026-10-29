r"""v0.6.19: an administrator's MaxRecoveryAttempts is a ceiling, and the surfaces draw it as one.

managed.admit has kept any number of attempts up to the ceiling since v0.6.11, and the guide said so, but the
Dashboard's Settings and the panel in Codex greyed **Attempts per interruption** like a setting a key fixes, so
nobody could choose a lower number there. The schema now carries the ceiling on that setting
(managed.ceilings), and both surfaces keep the field editable, hold its maximum to the ceiling and say the
ceiling under it. A key that fixes a value - ForceObserveOnly, QuietHours, DisableStatusFile - still greys
its settings.

Nothing here reads this machine's registry: the one function that asks is stood in for, and the window is
built from the worktree's sources, never shown, with a bridge rooted where nothing is.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import guiscan  # noqa: E402
from codex_auto_resume import l10n, managed, settings  # noqa: E402
from codex_auto_resume.control import policy as control_policy  # noqa: E402
from test_control import ControlTestCase  # noqa: E402
from test_mcpui_v064 import NODE, run_page, say, snapshot  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CSC = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe"
POWERSHELL = (Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
              / "WindowsPowerShell" / "v1.0" / "powershell.exe")
NIGHT = {"quiet_hours_start": "22:00", "quiet_hours_end": "07:00", "quiet_hours_days": "every_day"}
FIXING = dict(force_observe_only=True, quiet_hours=(NIGHT,))


def entry(schema: list, name: str) -> dict:
    return next(item for item in schema if item["name"] == name)


class SchemaTests(ControlTestCase):
    def manage(self, **values):
        stand_in = patch.object(control_policy, "managed_policy", return_value=managed.Managed(**values))
        stand_in.start()
        self.addCleanup(stand_in.stop)

    def test_the_attempts_carry_their_ceiling(self):
        self.manage(max_recovery_attempts=3)
        attempts = entry(self.control.describe_settings(), "max_recovery_attempts")
        self.assertEqual((attempts["managed"], attempts["ceiling"]), (True, 3))
        self.assertEqual(managed.ceilings(managed.Managed(max_recovery_attempts=3)), {"max_recovery_attempts": 3})

    def test_a_key_that_fixes_a_value_carries_no_ceiling(self):
        self.manage(**FIXING, disable_status_file=True)
        marked = [item for item in self.control.describe_settings() if item.get("managed")]
        self.assertTrue(marked)
        self.assertEqual([item["name"] for item in marked if "ceiling" in item], [])
        self.assertEqual(managed.ceilings(managed.Managed(**FIXING)), {})

    def test_the_ceiling_is_all_admit_lets_through(self):
        """What the surfaces now offer is exactly what is stored: up to the ceiling, and nothing above."""
        held = managed.Managed(max_recovery_attempts=3)
        effective = {"max_recovery_attempts": 3}
        for value in (1, 2, 3):
            self.assertEqual(managed.admit({"max_recovery_attempts": value}, effective, held)[1], None)
        self.assertEqual(managed.admit({"max_recovery_attempts": 4}, effective, held)[1], "max_recovery_attempts")


def managed_schema(**values) -> list:
    """settings.describe() marked as describe_settings marks it under these keys."""
    held = managed.Managed(**values)
    decided, ceilings = managed.fields(held), managed.ceilings(held)
    return [dict(item, managed=True, **({"ceiling": ceilings[item["name"]]} if item["name"] in ceilings else {}))
            if item["name"] in decided else item for item in settings.describe()]


SEEN = """(function () {
  var seen = {};
  ['max_recovery_attempts', 'observe_only'].forEach(function (name) {
    var input = byId('car-' + name);
    seen[name] = {disabled: !!input.disabled, max: input.max === undefined ? null : Number(input.max),
                  value: input.type === 'checkbox' ? input.checked : Number(input.value)};
  });
  var attempts = byId('car-max_recovery_attempts');
  attempts.value = '9';
  seen.typedAbove = EDITORS['max_recovery_attempts']();
  attempts.value = '2';
  seen.typedBelow = EDITORS['max_recovery_attempts']();
  seen.note = ROOT_NODE.all(function (n) { return n.textContent === S['settings.managed_ceiling'].replace('{n}', '3'); }).length;
  return seen;
})()"""


@unittest.skipUnless(NODE, "the panel's script runs in Node")
class PanelTests(unittest.TestCase):
    def drawn(self, **values):
        data = snapshot(max_recovery_attempts=5)
        data["schema"] = managed_schema(**values)
        return run_page(say(SEEN), data=data)

    def test_the_attempts_stay_editable_below_the_ceiling(self):
        seen = self.drawn(max_recovery_attempts=3, **FIXING)
        attempts = seen["max_recovery_attempts"]
        self.assertFalse(attempts["disabled"], "a ceiling leaves the field the person's to lower")
        self.assertEqual(attempts["max"], 3)
        self.assertEqual(attempts["value"], 3, "a stored 5 is shown as the ceiling holds it")
        self.assertEqual((seen["typedAbove"], seen["typedBelow"]), (3, 2))
        self.assertGreaterEqual(seen["note"], 1, "the ceiling is said beside the field")
        self.assertTrue(seen["observe_only"]["disabled"], "a key that fixes a value still greys it")

    def test_with_no_key_nothing_changes(self):
        seen = self.drawn()
        self.assertFalse(seen["max_recovery_attempts"]["disabled"])
        self.assertEqual(seen["max_recovery_attempts"]["max"], 20)
        self.assertEqual(seen["typedAbove"], 9)


PROBE = r"""
$ErrorActionPreference = 'Stop'
try {
    Add-Type -AssemblyName System.Drawing
    Add-Type -AssemblyName System.Windows.Forms
    # Never a dialog on anyone's desktop: an exception ends the probe with a code, nothing is shown.
    [Windows.Forms.Application]::SetUnhandledExceptionMode([Windows.Forms.UnhandledExceptionMode]::ThrowException)
    [Windows.Forms.Application]::EnableVisualStyles()
    $assembly = [Reflection.Assembly]::LoadFile($env:CAR_EXE)
    $static = [Reflection.BindingFlags]'Static,NonPublic,Public'
    $instance = [Reflection.BindingFlags]'Instance,NonPublic,Public'
    $form = $assembly.GetType('CodexAutoResume.SettingsForm', $true)
    $parse = $assembly.GetType('CodexAutoResume.Json', $true).GetMethod('Parse', $static)
    $work = [string]$env:CAR_WORK
    $utf8 = New-Object Text.UTF8Encoding $false
    function Read-Json([string]$name) { return ,$parse.Invoke($null, [object[]]@([IO.File]::ReadAllText((Join-Path $work $name), $utf8))) }
    $english = Read-Json 'strings-en.json'
    $nowhere = [string](Join-Path $work 'nowhere')
    $bridgeType = $assembly.GetType('CodexAutoResume.Bridge', $true)
    $persistentType = $assembly.GetType('CodexAutoResume.PersistentBridge', $true)
    $three = @($form.GetConstructors($instance) | Where-Object { $_.GetParameters().Count -eq 3 })[0]
    $build = @($form.GetMethods($instance) | Where-Object { $_.Name -eq 'BuildEditors' -and $_.GetParameters().Count -eq 2 })[0]
    function Get-Texts($control) {
        $found = @()
        foreach ($child in $control.Controls) { $found += [string]$child.Text; $found += Get-Texts $child }
        return $found
    }
    $out = @{}
    foreach ($case in @('ceiling', 'none')) {
        $once = $bridgeType.GetConstructors($instance)[0].Invoke([object[]]@($nowhere))
        $bridge = $persistentType.GetConstructors($instance)[0].Invoke([object[]]@($nowhere, $once))
        $window = $three.Invoke([object[]]@($bridge, $english, [Drawing.SystemFonts]::MessageBoxFont))
        $window.TopLevel = $false
        $null = $build.Invoke($window, [object[]]@((Read-Json ('schema-' + $case + '.json')), (Read-Json 'settings.json')))
        $editors = $form.GetField('editors', $instance).GetValue($window)
        $spin = $editors['max_recovery_attempts']
        $observe = $editors['observe_only']
        $state = @{ enabled = [bool]$spin.Enabled; maximum = [int]$spin.Maximum; value = [int]$spin.Value;
                    observeEnabled = [bool]$observe.Enabled }
        try { $spin.Value = [decimal]($spin.Maximum + 1); $state.above = 'taken' } catch { $state.above = 'refused' }
        $spin.Value = [decimal]2
        $state.below = [int]$spin.Value
        $state.note = @(Get-Texts $window | Where-Object { $_ -eq 'Your administrator allows at most 3.' }).Count
        $out[$case] = $state
        $window.Dispose()
    }
    [IO.File]::WriteAllText((Join-Path $work 'result.json'), ($out | ConvertTo-Json -Depth 4), $utf8)
    exit 0
} catch {
    [Console]::Error.WriteLine($_.Exception.ToString())
    exit 3
}
"""


@unittest.skipUnless(CSC.is_file(), "the window is compiled with the in-box C# compiler")
class WindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        work = Path(cls.folder.name)
        exe = work / "CodexAutoResumeSettings.exe"
        subprocess.run([str(CSC), "/nologo", "/target:winexe", "/platform:x64", "/out:" + str(exe),
                        "/reference:System.dll", "/reference:System.Drawing.dll",
                        "/reference:System.Windows.Forms.dll",
                        *[str(path) for path in guiscan.sources()]],
                       check=True, capture_output=True, timeout=300)
        (work / "schema-ceiling.json").write_text(
            json.dumps(managed_schema(max_recovery_attempts=3, **FIXING), ensure_ascii=False), encoding="utf-8")
        (work / "schema-none.json").write_text(json.dumps(settings.describe(), ensure_ascii=False), encoding="utf-8")
        (work / "settings.json").write_text(json.dumps(dict(settings.defaults(), max_recovery_attempts=5)),
                                            encoding="utf-8")
        reply = {"ok": True, "language": "en", "strings": l10n.catalog("en"), "endonyms": dict(l10n.ENDONYMS),
                 "preference": "en", "system_language": "en"}
        (work / "strings-en.json").write_text(json.dumps(reply, ensure_ascii=False), encoding="utf-8")
        probe = work / "probe.ps1"
        probe.write_text(PROBE, encoding="utf-8")
        cls.result = subprocess.run(
            [str(POWERSHELL), "-STA", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(probe)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600,
            env=dict(os.environ, CAR_EXE=str(exe), CAR_WORK=str(work)),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        answer = work / "result.json"
        cls.answer = (json.loads(answer.read_text(encoding="utf-8-sig"))
                      if cls.result.returncode == 0 and answer.is_file() else {})

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def setUp(self):
        self.assertEqual(self.result.returncode, 0, self.result.stderr[-3000:])

    def test_the_attempts_stay_editable_and_go_no_higher_than_the_ceiling(self):
        state = self.answer["ceiling"]
        self.assertTrue(state["enabled"], "a ceiling leaves the field the person's to lower")
        self.assertEqual(state["maximum"], 3)
        self.assertEqual(state["value"], 3, "a stored 5 is shown as the ceiling holds it")
        self.assertEqual(state["above"], "refused")
        self.assertEqual(state["below"], 2)
        self.assertEqual(state["note"], 1, "the ceiling is said under the field")

    def test_a_key_that_fixes_a_value_still_greys_it(self):
        self.assertFalse(self.answer["ceiling"]["observeEnabled"])
        self.assertTrue(self.answer["none"]["observeEnabled"])

    def test_with_no_key_nothing_changes(self):
        state = self.answer["none"]
        self.assertTrue(state["enabled"])
        self.assertEqual((state["maximum"], state["value"], state["note"]), (20, 5, 0))


if __name__ == "__main__":
    unittest.main()
