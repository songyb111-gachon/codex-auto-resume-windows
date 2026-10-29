r"""v0.6.19: Diagnostics' Compatibility report from this PC..., held through the compiled window and its source.

The button is the Tools card's last (so no button before it moves) and opens a dialog of its own
(gui/DashboardOwnReport.cs) that asks the bridge's `own-report` on the bridge's worker, shows what it says in a
read-only well and copies the report's own text, so the SHA-256 shown holds for what is pasted. What the well says
is a static method (OwnReportText), asked here without a window over answers of the test's own; the source is read
for where the button sits, which bridge command it asks, and that the layout audit builds the dialog.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

import guiscan

ROOT = Path(__file__).resolve().parents[1]
CSC = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe"
POWERSHELL = (Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
              / "WindowsPowerShell" / "v1.0" / "powershell.exe")
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# Only static methods are asked: no form is made, and a .NET error is never shown as a dialog.
PROBE = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
try { [System.Windows.Forms.Application]::SetUnhandledExceptionMode([System.Windows.Forms.UnhandledExceptionMode]::ThrowException) } catch { }
$script:assembly = [Reflection.Assembly]::LoadFile($env:CAR_EXE)
$script:form = $script:assembly.GetType('CodexAutoResume.SettingsForm', $true)
$script:flags = [Reflection.BindingFlags]'Static,NonPublic,Public'

function To-Value {
    param($value)
    if ($null -eq $value) { return $null }
    if ($value -is [System.Management.Automation.PSCustomObject]) {
        $map = New-Object 'System.Collections.Generic.Dictionary[string,object]'
        foreach ($field in $value.PSObject.Properties) { $map.Add([string]$field.Name, (To-Value $field.Value)) }
        return ,$map
    }
    if ($value -is [array]) {
        $list = New-Object 'System.Collections.Generic.List[object]'
        foreach ($item in $value) { $list.Add((To-Value $item)) }
        return ,$list
    }
    if ($value -is [bool] -or $value -is [string]) { return $value }
    return [double]$value
}

$out = @{}
try {
    $method = $script:form.GetMethod('OwnReportText', $script:flags)
    if (-not $method) { throw 'no OwnReportText' }
    $words = [System.Collections.Generic.Dictionary[string,string]]::new()
    foreach ($field in (ConvertFrom-Json $env:CAR_WORDS).PSObject.Properties) { $words.Add([string]$field.Name, [string]$field.Value) }
    foreach ($case in (ConvertFrom-Json $env:CAR_CASES).PSObject.Properties) {
        $answer = [Collections.Generic.Dictionary[string,object]](To-Value $case.Value)
        $out[$case.Name] = $method.Invoke($null, [object[]]@($answer, $words.psobject.BaseObject))
    }
    $out['no answer'] = $method.Invoke($null, [object[]]@($null, $words.psobject.BaseObject))
} catch {
    $out['error'] = [string]$_
}
$out | ConvertTo-Json -Depth 5 -Compress
"""

WORDS = {"unavailable": "UNAVAILABLE", "refused": "REFUSED:{reason}", "no_state": "NOSTATE",
         "no_engine_version": "NOENGINE", "current": "NOW:{version}",
         "row": "ROW:{version}|{counted}|{records}|{delivered}", "too_many": "TOOMANY:{version}",
         "left_out": "LEFT:{hidden}|{routed}|{unknown}|{unplaced}", "sha": "SHA:{sha}",
         "worked": "W", "failed": "F", "neither": "N", "both": "B"}
TEXT = '{\n  "format": "codex-auto-resume-own-report/1"\n}\n'


def entry(version, **counted):
    words = dict({"worked": False, "failed": False, "neither": False, "both": False}, **counted)
    return dict({"codex_version": version, "refusal": None, "verdict": "PASS", "records": 3, "delivered": 2}, **words)


CASES = {
    "written": {"sha256": "ab" * 32, "bytes": len(TEXT), "text": TEXT,
                "engine": {"current": "codex-cli 0.163.0", "from": "log"},
                "versions": [entry("codex-cli 0.163.0", worked=True),
                             entry("codex-cli 0.162.0", worked=True, failed=True, both=True),
                             entry("codex-cli 0.161.0", failed=True),
                             entry("codex-cli 0.160.0", neither=True),
                             {"codex_version": "codex-cli 0.159.0", "refusal": "too_many_records", "verdict": None,
                              "records": None, "delivered": None, "worked": None, "failed": None, "neither": None,
                              "both": None}],
                "left_out": {"hidden": 1, "another_route": 2, "beyond_reach": 3,
                             "unplaced": {"no_engine_line_before": 4, "engine_changed_during": 1}}},
    "no state": {"refusal": "no_state"},
    "no engine": {"refusal": "no_engine_version"},
    "other refusal": {"refusal": "state_busy"},
    "no text": {"versions": []},
}


@unittest.skipUnless(CSC.is_file() and POWERSHELL.is_file(), "needs the in-box compiler and PowerShell")
class OwnReportTextTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        work = Path(cls.folder.name).resolve()
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
            env=dict(os.environ, CAR_EXE=str(exe), CAR_WORDS=json.dumps(WORDS), CAR_CASES=json.dumps(CASES)))
        cls.result = result
        cls.answer = json.loads(result.stdout) if result.returncode == 0 and result.stdout.strip() else {}

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def setUp(self):
        if not self.answer or "error" in self.answer:
            self.fail("the probe did not run: " + str(self.answer.get("error"))
                      + (self.result.stderr or self.result.stdout)[-2000:])

    def test_a_written_report_says_each_version_its_count_what_was_left_out_and_its_sha256_then_the_report(self):
        lines = self.answer["written"].split("\r\n")
        self.assertEqual(lines[:8], [
            "NOW:codex-cli 0.163.0",
            "ROW:codex-cli 0.163.0|W|3|2",
            "ROW:codex-cli 0.162.0|B|3|2",
            "ROW:codex-cli 0.161.0|F|3|2",
            "ROW:codex-cli 0.160.0|N|3|2",
            "TOOMANY:codex-cli 0.159.0",
            "LEFT:1|2|3|5",
            "SHA:" + "ab" * 32])
        self.assertEqual(lines[8], "")
        self.assertEqual("\r\n".join(lines[9:]), TEXT.replace("\n", "\r\n"))

    def test_a_refusal_is_said_by_its_reason_and_no_answer_is_unavailable(self):
        self.assertEqual(self.answer["no state"], "REFUSED:NOSTATE")
        self.assertEqual(self.answer["no engine"], "REFUSED:NOENGINE")
        self.assertEqual(self.answer["other refusal"], "REFUSED:state_busy")
        self.assertEqual(self.answer["no answer"], "UNAVAILABLE")
        self.assertEqual(self.answer["no text"], "UNAVAILABLE")


class SourceTests(unittest.TestCase):
    def test_the_button_is_the_tools_cards_last_and_opens_the_dialog(self):
        body = guiscan.member_body("SettingsForm", "BuildDiagnostics")
        start = body.index("foreach (Button button in new[] {")
        buttons = body[start:body.index("button.Margin", start)]
        self.assertTrue(re.search(r'S\("action\.own_report", "Compatibility report from this PC\.\.\."\), false,\s*'
                                  r'delegate \{ OpenOwnReport\(\); \}\) \}\)\s*\{\s*$', buttons), buttons[-300:])
        self.assertIn("BuildOwnReport()", guiscan.member_body("SettingsForm", "OpenOwnReport"))

    def test_the_dialog_asks_own_report_on_the_bridges_worker_and_copies_the_reports_own_text(self):
        body = guiscan.member_body("SettingsForm", "BuildOwnReport")
        self.assertIn('bridge.Call("own-report", null)', body)
        self.assertIn("bridge.Queue(delegate", body)
        self.assertNotIn("QueueUserWorkItem", body)
        self.assertIn('reportText = Str(result, "text");', body)
        self.assertIn('Clipboard.SetText(reportText ?? "");', body)
        self.assertIn("well.Box.ReadOnly = true;", body)

    def test_it_is_compiled_with_the_dashboard_and_the_audit_builds_it(self):
        self.assertIn(ROOT / "gui" / "DashboardOwnReport.cs", [Path(path).resolve() for path in guiscan.sources()])
        self.assertIn("gui/DashboardOwnReport.cs", guiscan.group("dashboard"))
        audit = (ROOT / "gui" / "WindowAudit.cs").read_text(encoding="utf-8")
        self.assertIn('AuditSpoken("own_report", dialog, findings);', audit)

    def test_every_word_it_says_is_in_the_english_catalog(self):
        source = (ROOT / "gui" / "DashboardOwnReport.cs").read_text(encoding="utf-8")
        english = json.loads((ROOT / "src" / "codex_auto_resume" / "locales" / "en.json").read_text(encoding="utf-8"))
        said = dict(re.findall(r'S\("([a-z_.]+)", "((?:[^"\\]|\\.)*)"\)', source))
        self.assertGreaterEqual(len(said), 15)
        for key, fallback in said.items():
            with self.subTest(key):
                self.assertEqual(english.get(key), json.loads('"%s"' % fallback))


if __name__ == "__main__":
    unittest.main()
