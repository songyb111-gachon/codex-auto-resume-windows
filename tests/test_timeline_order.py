r"""The Timeline dialog lists its lines in time order (v0.6.20 final, A10).

The dialog shows one recovery's whole chain: its events, oldest first as the journal gives them, and what delivery showed
of each continuation (its receipts, v0.6.11). The receipts were added after every event, so in the final's live acceptance
(2026-11-01) "Seen starting a turn in its conversation" at 10:07 stood under the 10:14 and 10:15 events. Now every line
stands at its time (SettingsForm.InTimeOrder): oldest first, lines of one time in the order they came, a line without a
time after the line before it.
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

PROBE = r"""
$ErrorActionPreference = 'Stop'
$assembly = [Reflection.Assembly]::LoadFile($env:CAR_EXE)
$any = [Reflection.BindingFlags]'Static,Instance,NonPublic,Public'
$order = $assembly.GetType('CodexAutoResume.SettingsForm', $true).GetMethod('InTimeOrder', $any)
$out = @()
foreach ($case in (ConvertFrom-Json $env:CAR_CASES)) {
    $times = [System.Collections.Generic.List[double]]::new()
    foreach ($at in $case) { $times.Add([double]$at) }
    $argv = [object[]]::new(1)
    $argv[0] = $times
    $out += ,@($order.Invoke($null, $argv))
}
ConvertTo-Json -InputObject $out -Depth 4 -Compress
"""

CASES = [
    # The acceptance's chain: three events, then a receipt at 10:07 between the first two.
    [36000.0, 36840.0, 36900.0, 36420.0],
    # Lines of one time keep the order they came in: the event before what delivery showed.
    [100.0, 200.0, 200.0, 150.0],
    # A line without a time stays after the line before it.
    [100.0, 300.0, 0.0, 200.0],
    [],
]
EXPECTED = [[0, 3, 1, 2], [0, 3, 1, 2], [0, 3, 1, 2], []]


class TimeOrderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        work = Path(cls.folder.name)
        exe = work / "CodexAutoResumeSettings.exe"
        subprocess.run([str(CSC), "/nologo", "/target:winexe", "/platform:x64", "/out:" + str(exe),
                        "/reference:System.dll", "/reference:System.Drawing.dll", "/reference:System.Windows.Forms.dll",
                        *[str(path) for path in guiscan.sources()]], check=True, capture_output=True, timeout=300)
        script = work / "order.ps1"
        script.write_text(PROBE, encoding="utf-8")
        cls.result = subprocess.run(
            [str(POWERSHELL), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(script)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300,
            env=dict(os.environ, CAR_EXE=str(exe), CAR_CASES=json.dumps(CASES)))
        cls.answer = json.loads(cls.result.stdout) if cls.result.returncode == 0 and cls.result.stdout.strip() else None

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def test_every_line_stands_at_its_time(self):
        if self.answer is None:
            self.fail("the probe did not run: " + (self.result.stderr or self.result.stdout)[-3000:])
        answer = [[] if case is None else (case if isinstance(case, list) else [case]) for case in self.answer]
        self.assertEqual(answer, EXPECTED)


class SourceTests(unittest.TestCase):
    def test_the_dialog_adds_its_lines_in_time_order(self):
        body = guiscan.member_body("SettingsForm", "BuildTimeline")
        self.assertIn("foreach (int index in InTimeOrder(times)) view.Items.Add(lines[index]);", body)
        self.assertNotIn("view.Items.Add(line);", body, "a line added where it was read, not at its time")
        self.assertEqual(body.count("times.Add(Number("), 2, "the events' times and the receipts'")


if __name__ == "__main__":
    unittest.main()
