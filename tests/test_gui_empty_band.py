r"""v0.6.19: nothing that lays itself out is taller than what it holds - the window's layout audit says so where it is.

beta.2's early_reset line stood on Pending as an AutoSize row (a FlowLayoutPanel) whose preferred height was worked out
wrapped, at a width narrower than the one it was given: on a wide window an empty band stood under its buttons (the owner,
2026-10-24). The line is gone; the audit's EmptyBand (gui/WindowAudit.cs) is what keeps any such band from coming back,
on every page every layout audit walks (test_gui_layout, the advanced layout audits).

Held through the compiled window: EmptyBand finds a row taller than its content and passes one that hugs it, and the
audit's walk asks it of every control it walks.
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
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Windows.Forms
[Windows.Forms.Application]::SetUnhandledExceptionMode([Windows.Forms.UnhandledExceptionMode]::ThrowException)
$assembly = [Reflection.Assembly]::LoadFile($env:CAR_EXE)
$F = $assembly.GetType('CodexAutoResume.SettingsForm', $true)
$flags = [Reflection.BindingFlags]'Static,NonPublic,Public'
$band = $F.GetMethod('EmptyBand', $flags)
if (-not $band) { throw 'SettingsForm has no EmptyBand' }
function Row([int]$floor) {
    $host_ = New-Object Windows.Forms.Panel
    $host_.Size = New-Object Drawing.Size 1100, 400
    $flow = New-Object Windows.Forms.FlowLayoutPanel
    $flow.Dock = [Windows.Forms.DockStyle]::Top
    $flow.AutoSize = $true
    $flow.AutoSizeMode = [Windows.Forms.AutoSizeMode]::GrowAndShrink
    $flow.WrapContents = $true
    $flow.Padding = New-Object Windows.Forms.Padding 0, 0, 0, 8
    # A floor under its preferred height stands in for a height worked out wrapped at another width.
    $flow.MinimumSize = New-Object Drawing.Size 0, $floor
    foreach ($word in 'Check now', 'Early reset settings') {
        $button = New-Object Windows.Forms.Button
        $button.Text = $word
        $button.AutoSize = $true
        $flow.Controls.Add($button)
    }
    $host_.Controls.Add($flow)
    $null = $host_.Handle
    $host_.PerformLayout()
    return ,$flow
}
$out = @{}
try {
    $out.banded = [string]$band.Invoke($null, [object[]]@([Windows.Forms.Control](Row 120)))
    $out.hugging = [string]$band.Invoke($null, [object[]]@([Windows.Forms.Control](Row 0)))
} catch {
    [Console]::Error.WriteLine($_.Exception.ToString())
    exit 3
}
$out | ConvertTo-Json -Compress
"""


@unittest.skipUnless(CSC.is_file() and POWERSHELL.is_file(), "needs the in-box compiler and PowerShell")
class EmptyBandTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        work = Path(cls.folder.name)
        exe = work / "CodexAutoResumeSettings.exe"
        subprocess.run([str(CSC), "/nologo", "/target:winexe", "/platform:x64", "/out:" + str(exe),
                        "/reference:System.dll", "/reference:System.Drawing.dll",
                        "/reference:System.Windows.Forms.dll", *[str(path) for path in guiscan.sources()]],
                       check=True, capture_output=True, timeout=300,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        probe = work / "probe.ps1"
        probe.write_text(PROBE, encoding="utf-8")
        cls.result = subprocess.run(
            [str(POWERSHELL), "-STA", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(probe)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), env=dict(os.environ, CAR_EXE=str(exe)))
        cls.answer = json.loads(cls.result.stdout) if cls.result.returncode == 0 and cls.result.stdout.strip() else {}

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def setUp(self):
        if not self.answer:
            self.fail("the probe did not run: " + (self.result.stderr or self.result.stdout)[-2000:])

    def test_a_row_taller_than_what_it_holds_is_found(self):
        self.assertIn("empty band", self.answer["banded"])

    def test_a_row_that_hugs_what_it_holds_passes(self):
        self.assertEqual(self.answer["hugging"], "")


class WalkTests(unittest.TestCase):
    def test_the_audits_walk_asks_it_of_every_control(self):
        """Fails with the check reverted: no layout audit would see an empty band again."""
        body = guiscan.member_body("SettingsForm", "Walk")
        self.assertIn("EmptyBand(child)", body)


if __name__ == "__main__":
    unittest.main()
