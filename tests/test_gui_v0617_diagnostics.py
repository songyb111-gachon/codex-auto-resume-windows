r"""v0.6.17: the Diagnostics page's row for where the watcher and this window run, held through the compiled window.

Inside another app (the MSIX work's item 6): the bridge's `host-app` answer (control/tools.py host_app) is drawn as
one line under Health - "no", or which of the watcher and this window runs inside which app - and, only while one
does, a sentence under the facts saying what that means and what to do. What is said is a static method
(HostAppLines), asked here without a window over answers of the test's own; the source is read for where the row
sits (last, so no row before it moves), that it is asked with the state folder, and that the layout audit gives it
its longest answer.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import guiscan

CSC = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe"
POWERSHELL = (Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
              / "WindowsPowerShell" / "v1.0" / "powershell.exe")
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

PROBE = r"""
$ErrorActionPreference = 'Stop'
$assembly = [Reflection.Assembly]::LoadFile($env:CAR_EXE)
$form = $assembly.GetType('CodexAutoResume.SettingsForm', $true)
$flags = [Reflection.BindingFlags]'Static,NonPublic,Public'
function Method($name) { $m = $form.GetMethod($name, $flags); if (-not $m) { throw ('no ' + $name) }; return $m }

function To-Value {
    param($value)
    if ($null -eq $value) { return $null }
    if ($value -is [System.Management.Automation.PSCustomObject]) {
        $map = New-Object 'System.Collections.Generic.Dictionary[string,object]'
        foreach ($field in $value.PSObject.Properties) { $map.Add([string]$field.Name, (To-Value $field.Value)) }
        return ,$map
    }
    if ($value -is [bool] -or $value -is [string]) { return $value }
    return [double]$value
}

$out = @{ host = @{}; access = @{} }
$state = Method 'StateAccessSaid'
foreach ($word in @('owner_only', 'shared', 'codex_sandbox', 'unknown', 'other')) {
    $said = $state.Invoke($null, [object[]]@($word, 'OWNER', 'SHARED', 'SANDBOX', 'UNKNOWN', 'NOTE'))
    $out.access[$word] = @($said[0], $said[1])
}
$lines = Method 'HostAppLines'
foreach ($case in (ConvertFrom-Json $env:CAR_HOST).PSObject.Properties) {
    $answer = [Collections.Generic.Dictionary[string,object]](To-Value $case.Value)
    $said = $lines.Invoke($null, [object[]]@($answer, 'NO', 'UNKNOWN', 'W:{app}', 'D:{app}', 'B:{app}', 'ANOTHER', 'NOTE:{app}'))
    $out.host[$case.Name] = @($said[0], $said[1])
}
$said = $lines.Invoke($null, [object[]]@($null, 'NO', 'UNKNOWN', 'W:{app}', 'D:{app}', 'B:{app}', 'ANOTHER', 'NOTE:{app}'))
$out.host['no answer'] = @($said[0], $said[1])
$out | ConvertTo-Json -Depth 5 -Compress
"""


def part(state, app=None):
    return {"state": state, "family": None if app is None else app + "_2p2nqsd0c76g0", "app": app}


HOST = {
    "both outside": {"watcher": part("outside"), "bridge": part("outside")},
    "no watcher": {"watcher": part("not_running"), "bridge": part("outside")},
    "watcher unknown": {"watcher": part("unknown"), "bridge": part("outside")},
    "watcher inside": {"watcher": part("inside", "OpenAI.Codex"), "bridge": part("outside")},
    "window inside": {"watcher": part("not_running"), "bridge": part("inside", "Claude")},
    "both inside one app": {"watcher": part("inside", "OpenAI.Codex"), "bridge": part("inside", "OpenAI.Codex")},
    "both inside, apart": {"watcher": part("inside", "OpenAI.Codex"), "bridge": part("inside", "Claude")},
    "inside, no name": {"watcher": {"state": "inside", "family": None, "app": None}, "bridge": part("unknown")},
}


@unittest.skipUnless(CSC.is_file() and POWERSHELL.is_file(), "needs the in-box compiler and PowerShell")
class HostAppLinesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        work = Path(cls.folder.name)
        exe = work / "CodexAutoResumeSettings.exe"
        subprocess.run([str(CSC), "/nologo", "/target:winexe", "/platform:x64", "/out:" + str(exe),
                        "/reference:System.dll", "/reference:System.Drawing.dll",
                        "/reference:System.Windows.Forms.dll", *[str(path) for path in guiscan.sources()]],
                       check=True, capture_output=True, timeout=300, creationflags=NO_WINDOW)
        probe = work / "probe.ps1"
        probe.write_text(PROBE, encoding="utf-8")
        result = subprocess.run(
            [str(POWERSHELL), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(probe)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600, creationflags=NO_WINDOW,
            env=dict(os.environ, CAR_EXE=str(exe), CAR_HOST=json.dumps(HOST)))
        cls.result = result
        cls.answer = json.loads(result.stdout) if result.returncode == 0 and result.stdout.strip() else {}

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def setUp(self):
        if not self.answer:
            self.fail("the probe did not run: " + (self.result.stderr or self.result.stdout)[-2000:])

    def test_outside_is_the_normal_line_and_says_nothing_under_the_facts(self):
        for case in ("both outside", "no watcher"):
            with self.subTest(case):
                self.assertEqual(self.answer["host"][case], ["NO", ""])

    def test_a_part_not_known_is_unknown_unless_the_other_is_inside(self):
        self.assertEqual(self.answer["host"]["watcher unknown"], ["UNKNOWN", ""])
        self.assertEqual(self.answer["host"]["no answer"], ["UNKNOWN", ""])
        self.assertEqual(self.answer["host"]["inside, no name"], ["W:ANOTHER", "NOTE:ANOTHER"])

    def test_inside_names_the_app_and_says_what_it_means(self):
        self.assertEqual(self.answer["host"]["watcher inside"], ["W:OpenAI.Codex", "NOTE:OpenAI.Codex"])
        self.assertEqual(self.answer["host"]["window inside"], ["D:Claude", "NOTE:Claude"])
        self.assertEqual(self.answer["host"]["both inside one app"], ["B:OpenAI.Codex", "NOTE:OpenAI.Codex"])
        self.assertEqual(self.answer["host"]["both inside, apart"],
                         ["W:OpenAI.Codex\r\nD:Claude", "NOTE:OpenAI.Codex"])


    def test_codexs_sandbox_reading_is_said_on_the_line_and_only_other_accounts_get_the_advice(self):
        """v0.6.17: CodexSandboxUsers reading the folder is a line naming the group, not the warning; the advice -
        take the other accounts' access away - is under the facts only while other accounts can open it."""
        self.assertEqual(self.answer["access"], {"owner_only": ["OWNER", ""], "shared": ["SHARED", "NOTE"],
                                                 "codex_sandbox": ["SANDBOX", ""], "unknown": ["UNKNOWN", ""],
                                                 "other": ["UNKNOWN", ""]})


class HostAppPlacementTests(unittest.TestCase):
    def test_the_row_comes_last_so_no_row_before_it_moves(self):
        page = guiscan.member_body("SettingsForm", "DiagnosticsSteps")
        self.assertLess(page.index('"diag.while_waiting"'), page.index('"diag.host_app"'))
        self.assertLess(page.index("health.Controls.Add(diagStateNote)"), page.index("health.Controls.Add(diagHostNote)"))

    def test_it_is_asked_with_the_state_folder_and_nothing_else_is_done(self):
        self.assertIn("LoadHostApp();", guiscan.member_body("SettingsForm", "LoadCompatibility"))
        loader = guiscan.member_body("SettingsForm", "LoadHostApp")
        self.assertIn('bridge.Call("host-app", null)', loader)
        self.assertEqual(loader.count("bridge.Call("), 1)

    def test_the_layout_audit_gives_it_its_longest_answer(self):
        # The audit's part of the window, by its type block (guiscan.member_body reads the window's own group).
        audit = guiscan.type_body("SettingsForm", guiscan.read("WindowAudit.cs"))
        self.assertIn("form.ApplyHostApp(AuditHostApp())", audit)
        self.assertEqual(audit.count('"inside"'), 2, "both inside, in two apps: two lines and the sentence")
        self.assertIn('"OpenAI.Codex"', audit)
        self.assertIn('"Claude"', audit)


if __name__ == "__main__":
    unittest.main()
