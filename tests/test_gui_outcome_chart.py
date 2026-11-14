r"""The Statistics page's outcome chart: raised pills in the Soft design, flat pills in Classic and Plain (v0.6.22 final;
v0.6.23, the design audit's second round, F10: round-ended in every design).

The owner chose the look from a mock on 2026-11-08 ("A"): each outcome's bar is a pill - its corners half its height -
raised off the card with the control's lift, the shadows a raised button has, in the colour of its part in the success
rate. Classic and Plain draw the same pills flat, in the same colours, with no lift: a design changes depth, not shape -
their switch tracks, meters and scroll thumbs are round-ended too - and never where anything is.

The real compiled chart is made in the probe's own process, never shown, given three bars - a success, a failure and an
outcome the rate leaves out - and drawn to a bitmap in each design and theme. Its own Faces() says where each bar's body
is, and the pixels are read there: the fill at the middle, the card at a pill's corner in every design, and below the bar
the lift's shadow (Soft) or the card alone (Classic, Plain).

    python -m unittest tests.test_gui_outcome_chart       (a GUI module: gui_lock.sh)
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
LOOKS = [(design, theme) for design in ("soft", "classic", "plain") for theme in ("light", "dark")]
BARS = [("Recovered", 9, "success"), ("No progress", 6, "failure"), ("Cancelled", 3, "other")]

PROBE = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Windows.Forms
[Windows.Forms.Application]::SetUnhandledExceptionMode('ThrowException')
$assembly = [Reflection.Assembly]::LoadFile($env:CAR_EXE)
$static = [Reflection.BindingFlags]'Static,NonPublic,Public'
$instance = [Reflection.BindingFlags]'Instance,NonPublic,Public'
$form = $assembly.GetType('CodexAutoResume.SettingsForm', $true)
$palette = $assembly.GetType('CodexAutoResume.Palette', $true)
$chartType = $assembly.GetType('CodexAutoResume.OutcomeChart', $true)
$barType = $assembly.GetType('CodexAutoResume.OutcomeChart+Bar', $true)
$form.GetField('dpiScale', $static).SetValue($null, [double]1.0)
function Colour([string]$name) { return $palette.GetField($name, $static).GetValue($null) }
$out = @{}
foreach ($look in (ConvertFrom-Json $env:CAR_LOOKS)) {
    $null = $palette.GetMethod('AdoptDesign', $static).Invoke($null, [object[]]@([string]$look[0]))
    $null = $palette.GetMethod('Adopt', $static).Invoke($null, [object[]]@([string]$look[1]))
    $chart = $chartType.GetConstructors($instance)[0].Invoke([object[]]@())
    $chart.Font = New-Object Drawing.Font 'Segoe UI', 9
    $chart.BackColor = Colour 'Card'
    $chartType.GetField('BarColor', $instance).SetValue($chart, (Colour 'Accent'))
    $chartType.GetField('FailureColor', $instance).SetValue($chart, (Colour 'Warning'))
    $chartType.GetField('OtherColor', $instance).SetValue($chart, (Colour 'Paused'))
    $chartType.GetField('TextColor', $instance).SetValue($chart, (Colour 'Ink'))
    $bars = $chartType.GetField('Bars', $instance).GetValue($chart)
    foreach ($bar in (ConvertFrom-Json $env:CAR_BARS)) {
        $bars.Add($barType.GetConstructors($instance)[0].Invoke([object[]]@([string]$bar[0], [int]$bar[1], [string]$bar[2])))
    }
    $row = [int]$chartType.GetMethod('RowHeight', $instance).Invoke($chart, @())
    $chart.Size = New-Object Drawing.Size 420, ($bars.Count * $row + 4)
    $bitmap = New-Object Drawing.Bitmap $chart.Width, $chart.Height
    $chart.DrawToBitmap($bitmap, (New-Object Drawing.Rectangle 0, 0, $chart.Width, $chart.Height))
    $read = @()
    foreach ($face in $chartType.GetMethod('Faces', $instance).Invoke($chart, @())) {
        $middle = [int]($face.Y + $face.Height / 2)
        $centre = [int]($face.X + $face.Width / 2)
        $read += ,@{ face = @($face.X, $face.Y, $face.Width, $face.Height)
                     middle = [int]$bitmap.GetPixel($centre, $middle).ToArgb()
                     corner = [int]$bitmap.GetPixel($face.X, $face.Y).ToArgb()
                     below = [int]$bitmap.GetPixel($centre, $face.Bottom + 1).ToArgb() }
    }
    $bitmap.Dispose()
    $out[$look[0] + '-' + $look[1]] = @{ bars = $read; card = [int](Colour 'Card').ToArgb(); depth = [bool]$palette.GetField('Depth', $static).GetValue($null)
                                       colours = @([int](Colour 'Accent').ToArgb(), [int](Colour 'Warning').ToArgb(), [int](Colour 'Paused').ToArgb()) }
    $chart.Dispose()
}
[IO.File]::WriteAllText((Join-Path $env:CAR_WORK 'result.json'), ($out | ConvertTo-Json -Depth 8 -Compress), (New-Object Text.UTF8Encoding $false))
[Environment]::Exit(0)
"""


@unittest.skipUnless(CSC.is_file() and POWERSHELL.is_file(), "needs the in-box compiler and PowerShell")
class OutcomeChartLookTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        work = Path(cls.folder.name)
        exe = work / "CodexAutoResumeSettings.exe"
        subprocess.run([str(CSC), "/nologo", "/target:winexe", "/platform:x64", "/out:" + str(exe),
                        "/reference:System.dll", "/reference:System.Drawing.dll", "/reference:System.Windows.Forms.dll",
                        *[str(path) for path in guiscan.sources()]],
                       check=True, capture_output=True, timeout=300, creationflags=subprocess.CREATE_NO_WINDOW)
        probe = work / "chart.ps1"
        probe.write_text(PROBE, encoding="utf-8")
        cls.result = subprocess.run(
            [str(POWERSHELL), "-STA", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(probe)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300,
            creationflags=subprocess.CREATE_NO_WINDOW,
            env=dict(os.environ, CAR_EXE=str(exe), CAR_WORK=str(work), CAR_LOOKS=json.dumps(LOOKS),
                     CAR_BARS=json.dumps(BARS)))
        answer = work / "result.json"
        cls.answer = (json.loads(answer.read_text(encoding="utf-8-sig"))
                      if cls.result.returncode == 0 and answer.is_file() else {})

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def setUp(self):
        if not self.answer:
            self.fail("the probe did not run: " + (self.result.stderr or self.result.stdout)[-4000:])

    def test_each_bar_is_filled_with_its_group_s_colour_in_every_design_and_theme(self):
        for design, theme in LOOKS:
            found = self.answer[design + "-" + theme]
            with self.subTest(design=design, theme=theme):
                self.assertEqual([bar["middle"] for bar in found["bars"]], found["colours"])

    def test_soft_draws_raised_pills(self):
        """A pill's corner is round, so the card shows at its bounding box's corner; under the bar is the lift's
        shadow, not the bare card - in light the drop of a shadow and a highlight, in dark its one drop."""
        for theme in ("light", "dark"):
            found = self.answer["soft-" + theme]
            self.assertTrue(found["depth"])
            for index, bar in enumerate(found["bars"]):
                with self.subTest(theme=theme, bar=index):
                    self.assertGreaterEqual(bar["face"][2], bar["face"][3], "the bars are long enough to be pills")
                    self.assertNotEqual(bar["corner"], found["colours"][index], "a pill's corner is round")
                    self.assertNotEqual(bar["below"], found["card"], "the bar is raised: its shadow lies under it")

    def test_classic_and_plain_draw_flat_pills(self):
        for design in ("classic", "plain"):
            for theme in ("light", "dark"):
                found = self.answer[design + "-" + theme]
                self.assertFalse(found["depth"])
                for index, bar in enumerate(found["bars"]):
                    with self.subTest(design=design, theme=theme, bar=index):
                        self.assertNotEqual(bar["corner"], found["colours"][index], "a round end, as Soft's")
                        self.assertEqual(bar["below"], found["card"], "no shadow under a flat pill")

    def test_only_the_lift_is_the_soft_design_s(self):
        body = guiscan.type_body("OutcomeChart")
        self.assertNotIn("FillRectangle(flat, face)", body, "no square bar in any design")
        self.assertIn("Elevation.StampOuter", body.split("if (Palette.Depth)", 1)[1].split(";", 1)[0], "the lift alone")


class SourceTests(unittest.TestCase):
    def test_the_lift_and_the_body_are_the_soft_design_s_own(self):
        """The chart reuses the shadows and bodies every raised control draws with, and invents none."""
        body = guiscan.type_body("OutcomeChart")
        self.assertIn('Elevation.StampOuter(e.Graphics, face, "control", face.Height / 2f, ClientRectangle);', body)
        self.assertIn("Soft.Body(e.Graphics, face, face.Height / 2f, fill, fill, null);", body)
        self.assertNotIn("DrawString(", body, "text is drawn as the rest of the window draws it (TextRenderer)")

    def test_the_window_colours_by_the_answer_s_groups_not_a_list_of_its_own(self):
        apply = guiscan.member_body("SettingsForm", "ApplyStatistics")
        self.assertIn('Map(stats, "outcome_groups")', apply)
        for code in ("no_progress", "handed_over", "cancelled", "exhausted"):
            self.assertNotIn('"%s"' % code, apply)
            self.assertNotIn('"%s"' % code, guiscan.type_body("OutcomeChart"))
