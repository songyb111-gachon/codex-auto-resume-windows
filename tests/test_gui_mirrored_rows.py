r"""Each row's hairline runs the whole width of a list, mirrored as left to right (v0.6.20 final, the live re-check's finding 3).

In Arabic and Hebrew the lines between the rows of History, Pending, the Timeline and Install another version stopped before
the first column, which stands at the right of a mirrored list (SoftListHost.MirrorColumns): DrawCell drew each cell's
hairline across the bounds Windows handed it, and for the first column Windows hands the rectangle at the row's left edge,
not where the column stands (CellBounds says so and the cell's ground already used it). The line is now drawn across the
cell's own bounds, wherever its column is, so the cells' lines together are the row's.

The real compiled window is built in the probe's own process as test_gui_v065_rows builds it - a bridge rooted where nothing
is, a window of the probe's own far off the screen, never shown on anyone's desktop - once in English (left to right, the
control) and once in each language written right to left; its History and Pending lists are drawn to a bitmap and the row of
pixels at each row's hairline is read from the list's left to its right. Every pixel of it is the hairline's colour.

    python -m unittest tests.test_gui_mirrored_rows       (a GUI module: gui_lock.sh)
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest

import guiscan

from codex_auto_resume import l10n

from test_gui_layout import fullest_snapshot

ROOT = Path(__file__).resolve().parents[1]
CSC = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe"
POWERSHELL = (Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
              / "WindowsPowerShell" / "v1.0" / "powershell.exe")
LOCALES = ("en", "ar", "he")
LISTS = ("pendingList", "historyList")

PROBE = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Windows.Forms
[Windows.Forms.Application]::EnableVisualStyles()
[Windows.Forms.Application]::SetCompatibleTextRenderingDefault($false)
[Windows.Forms.Application]::SetUnhandledExceptionMode('ThrowException')
Add-Type -ReferencedAssemblies System.Windows.Forms, System.Drawing -TypeDefinition @'
using System;
using System.Drawing;
using System.Runtime.InteropServices;
using System.Windows.Forms;
public class QuietForm : Form {
    protected override bool ShowWithoutActivation { get { return true; } }
    protected override CreateParams CreateParams { get { CreateParams cp = base.CreateParams; cp.ExStyle |= 0x08000000 | 0x80; return cp; } }
}
public static class Placer {
    [DllImport("user32.dll")] static extern bool SetWindowPos(IntPtr hWnd, IntPtr after, int x, int y, int cx, int cy, uint flags);
    public static void Size(Control child, int width, int height) { SetWindowPos(child.Handle, IntPtr.Zero, 0, 0, width, height, 0x0002 | 0x0004 | 0x0010); }
}
'@
$assembly = [Reflection.Assembly]::LoadFile($env:CAR_EXE)
$static = [Reflection.BindingFlags]'Static,NonPublic,Public'
$instance = [Reflection.BindingFlags]'Instance,NonPublic,Public'
$form = $assembly.GetType('CodexAutoResume.SettingsForm', $true)
$palette = $assembly.GetType('CodexAutoResume.Palette', $true)
$soft = $assembly.GetType('CodexAutoResume.Soft', $true)
$mirror = $assembly.GetType('CodexAutoResume.Mirror', $true)
$parse = $assembly.GetType('CodexAutoResume.Json', $true).GetMethod('Parse', $static)
$work = [string]$env:CAR_WORK
$utf8 = New-Object Text.UTF8Encoding $false
function Read-Json([string]$name) { return $parse.Invoke($null, [object[]]@([IO.File]::ReadAllText((Join-Path $work $name), $utf8))) }
function Get-Field($target, [string]$name) { return $form.GetField($name, $instance).GetValue($target) }
function Invoke-Window($target, [string]$name, [object[]]$arguments) {
    $method = @($form.GetMethods($instance) | Where-Object { $_.Name -eq $name -and $_.GetParameters().Count -eq $arguments.Count })[0]
    return $method.Invoke($target, $arguments)
}
function Pump([int]$ms) { $sw = [Diagnostics.Stopwatch]::StartNew(); do { [Windows.Forms.Application]::DoEvents(); Start-Sleep -Milliseconds 2 } while ($sw.ElapsedMilliseconds -lt $ms) }
$soft.GetField('ReduceMotionSetting', $static).SetValue($null, $true)
$null = $palette.GetMethod('Adopt', $static).Invoke($null, [object[]]@('light'))
$line = [int]$palette.GetField('Line', $static).GetValue($null).ToArgb()
$systemScale = [double]$form.GetField('SystemScale', $static).GetValue($null)
$form.GetField('dpiScale', $static).SetValue($null, [double]1.0)
$factor = [single](1.0 / $systemScale)
$box = [Drawing.SystemFonts]::MessageBoxFont
[Drawing.Font]$font = New-Object Drawing.Font $box.FontFamily, ($box.SizeInPoints * $factor), $box.Style, ([Drawing.GraphicsUnit]::Point)
$nowhere = [string](Join-Path $work 'nowhere')
$bridgeType = $assembly.GetType('CodexAutoResume.Bridge', $true)
$persistentType = $assembly.GetType('CodexAutoResume.PersistentBridge', $true)
$three = @($form.GetConstructors($instance) | Where-Object { $_.GetParameters().Count -eq 3 })[0]
$out = @{ line = $line; hairline = [int]$soft.GetProperty('Hairline', $static).GetValue($null) }
foreach ($locale in (ConvertFrom-Json $env:CAR_LOCALES)) {
    $frame = New-Object QuietForm
    $frame.FormBorderStyle = 'None'; $frame.ShowInTaskbar = $false; $frame.StartPosition = 'Manual'
    $frame.Location = New-Object Drawing.Point -30000, -30000
    $opening = New-Object Drawing.Size ([int]$form.GetField('OpeningWidth', $static).GetValue($null)), ([int]$form.GetField('OpeningHeight', $static).GetValue($null))
    $frame.ClientSize = $opening
    $once = $bridgeType.GetConstructors($instance)[0].Invoke([object[]]@($nowhere))
    $bridge = $persistentType.GetConstructors($instance)[0].Invoke([object[]]@($nowhere, $once))
    $window = $three.Invoke([object[]]@($bridge, (Read-Json ('strings-' + $locale + '.json')), $font.PSObject.BaseObject))
    $form.GetField('auditing', $instance).SetValue($window, $true)
    $window.TopLevel = $false
    $window.FormBorderStyle = 'None'
    $window.MinimumSize = [Drawing.Size]::Empty
    $window.Location = [Drawing.Point]::Empty
    $window.ClientSize = $opening
    $frame.Controls.Add($window)
    [Placer]::Size($window, $opening.Width, $opening.Height)
    Invoke-Window $window 'ApplySnapshot' @((Read-Json 'snapshot.json'))
    $null = Invoke-Window $window 'ShowPage' @('pending')
    $window.Visible = $true
    $frame.Show()
    Pump 100
    $found = @{ mirrored = [bool]$mirror.GetField('Window', $static).GetValue($null) }
    foreach ($name in (ConvertFrom-Json $env:CAR_LISTS)) {
        $null = Invoke-Window $window 'ShowPage' @($(if ($name -eq 'pendingList') { 'pending' } else { 'history' }))
        Pump 60
        $list = Get-Field $window $name
        foreach ($item in $list.Items) { $item.Selected = $false }
        Pump 30
        $bitmap = New-Object Drawing.Bitmap $list.Width, $list.Height
        $list.DrawToBitmap($bitmap, (New-Object Drawing.Rectangle 0, 0, $list.Width, $list.Height))
        $rows = @()
        foreach ($item in $list.Items) {
            $bounds = $item.Bounds
            $y = $bounds.Bottom - [int]$out.hairline
            if ($y -lt 0 -or $y -ge $bitmap.Height) { continue }
            $from = [Math]::Max(0, $bounds.Left)
            $to = [Math]::Min($bitmap.Width, $bounds.Right)
            $missing = @()
            for ($x = $from; $x -lt $to; $x++) { if ([int]$bitmap.GetPixel($x, $y).ToArgb() -ne $line) { $missing += $x } }
            $rows += ,@{ y = [int]$y; from = [int]$from; to = [int]$to; missing = @($missing); columns = @($list.Columns | ForEach-Object { [int]$_.Width }) }
        }
        $bitmap.Dispose()
        $found[$name] = @{ rows = $rows; items = [int]$list.Items.Count }
    }
    $out[$locale] = $found
    $frame.Close()
    $frame.Dispose()
}
[IO.File]::WriteAllText((Join-Path $work 'result.json'), ($out | ConvertTo-Json -Depth 8 -Compress), $utf8)
[GC]::Collect()
[GC]::WaitForPendingFinalizers()
[Environment]::Exit(0)
"""


@unittest.skipUnless(CSC.is_file() and POWERSHELL.is_file(), "needs the in-box compiler and PowerShell")
class RowLineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        work = Path(cls.folder.name)
        exe = work / "CodexAutoResumeSettings.exe"
        subprocess.run([str(CSC), "/nologo", "/target:winexe", "/platform:x64", "/out:" + str(exe),
                        "/reference:System.dll", "/reference:System.Drawing.dll", "/reference:System.Windows.Forms.dll",
                        *[str(path) for path in guiscan.sources()]],
                       check=True, capture_output=True, timeout=300)
        for locale in LOCALES:
            reply = {"ok": True, "language": locale, "strings": l10n.catalog(locale), "endonyms": dict(l10n.ENDONYMS),
                     "preference": locale, "system_language": locale}
            (work / ("strings-%s.json" % locale)).write_text(json.dumps(reply, ensure_ascii=False), encoding="utf-8")
        (work / "snapshot.json").write_text(json.dumps(fullest_snapshot(time.time()), ensure_ascii=False), encoding="utf-8")
        probe = work / "rows.ps1"
        probe.write_text(PROBE, encoding="utf-8")
        cls.result = subprocess.run(
            [str(POWERSHELL), "-STA", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(probe)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600,
            env=dict(os.environ, CAR_EXE=str(exe), CAR_WORK=str(work), CAR_LOCALES=json.dumps(LOCALES),
                     CAR_LISTS=json.dumps(LISTS)))
        answer = work / "result.json"
        cls.answer = (json.loads(answer.read_text(encoding="utf-8-sig"))
                      if cls.result.returncode == 0 and answer.is_file() else {})

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def setUp(self):
        if not self.answer:
            self.fail("the probe did not run: " + (self.result.stderr or self.result.stdout)[-4000:])

    def test_the_locales_are_mirrored_where_they_are_written_right_to_left(self):
        self.assertEqual([self.answer[locale]["mirrored"] for locale in LOCALES], [False, True, True])

    def test_every_row_s_hairline_runs_the_whole_width_in_both_directions(self):
        for locale in LOCALES:
            for name in LISTS:
                found = self.answer[locale][name]
                self.assertGreaterEqual(len(found["rows"]), 3, "%s %s lists rows to read" % (locale, name))
                for number, row in enumerate(found["rows"]):
                    with self.subTest(locale=locale, list=name, row=number):
                        self.assertGreater(row["to"] - row["from"], 200)
                        self.assertEqual(row["missing"], [], "hairline missing at x (row %d of %s, y=%d)" % (
                            number, name, row["y"]))


class SourceTests(unittest.TestCase):
    def test_a_cell_draws_its_hairline_across_its_own_bounds_not_windows_answer(self):
        body = guiscan.member_body("SettingsForm", "DrawCell")
        self.assertIn("bounds.Left, bounds.Bottom - Soft.Hairline, bounds.Width, Soft.Hairline", body)
        self.assertNotIn("e.Bounds.Left, e.Bounds.Bottom - Soft.Hairline", body)


if __name__ == "__main__":
    unittest.main()
