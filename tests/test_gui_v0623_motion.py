r"""v0.6.23: the motion inside the windows (the owner: "모션이 없는건 추가하고 / 이미 있는건 더 부드럽게").

The real compiled window is loaded and its controls are made in a window of the probe's own, placed far off the screen and
shown without taking activation. Windows' animation switch is the probe's own answer (Soft.WindowsAnimates), so a machine
with it off - GitHub's runner - tests the same glides. Every piece is reached by reflection into the compiled window, so a
piece reverted fails here; a few rules are read from the source through guiscan.

GUI test module (it compiles the window and opens one of its own): run on its own, through gui_lock.sh.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import tempfile
import unittest

import guiscan
from codex_auto_resume import brand
from codex_auto_resume.brand import css as brand_css
from test_gui_v0611_access import CSC, POWERSHELL, compile_window, run_probe  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]

PROBE_HEAD = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Windows.Forms
[System.Windows.Forms.Application]::SetUnhandledExceptionMode('ThrowException')
Add-Type -ReferencedAssemblies System.Windows.Forms, System.Drawing -TypeDefinition @'
using System;
using System.Windows.Forms;
public class QuietForm : Form {
    protected override bool ShowWithoutActivation { get { return true; } }
    protected override CreateParams CreateParams { get { CreateParams cp = base.CreateParams; cp.ExStyle |= 0x08000000 | 0x80; return cp; } }
}
public static class Said {
    public static bool Yes() { return true; }
    public static bool No() { return false; }
    public static Func<bool> Answer(bool yes) { return yes ? new Func<bool>(Yes) : new Func<bool>(No); }
}
'@
$assembly = [Reflection.Assembly]::LoadFile($env:CAR_EXE)
$static = [Reflection.BindingFlags]'Static,NonPublic,Public'
$instance = [Reflection.BindingFlags]'Instance,NonPublic,Public'
function T([string]$name) { return $assembly.GetType('CodexAutoResume.' + $name, $true) }
function P($target, [string]$name) { return $target.GetType().GetProperty($name, $instance).GetValue($target, $null) }
function F($target, [string]$name) { return $target.GetType().GetField($name, $instance).GetValue($target) }
function SetF($target, [string]$name, $value) { $target.GetType().GetField($name, $instance).SetValue($target, $value) }
function Call($target, [string]$name, [object[]]$arguments) {
    $m = @($target.GetType().GetMethods($instance) | Where-Object { $_.Name -eq $name -and $_.GetParameters().Count -eq $arguments.Count })[0]
    return $m.Invoke($target, (Bare $arguments))
}
function S([string]$type, [string]$name, [object[]]$arguments) {
    $m = @((T $type).GetMethods($static) | Where-Object { $_.Name -eq $name -and $_.GetParameters().Count -eq $arguments.Count })[0]
    return $m.Invoke($null, (Bare $arguments))
}
function SProp([string]$type, [string]$name) { $p = (T $type).GetProperty($name, $static); if ($p) { return $p.GetValue($null, $null) }; return (T $type).GetField($name, $static).GetValue($null) }
function SF([string]$type, [string]$name) { return (T $type).GetField($name, $static).GetValue($null) }
function SetSF([string]$type, [string]$name, $value) { (T $type).GetField($name, $static).SetValue($null, $value) }
function Pump([int]$ms) { $sw = [Diagnostics.Stopwatch]::StartNew(); do { [Windows.Forms.Application]::DoEvents(); Start-Sleep -Milliseconds 3 } while ($sw.ElapsedMilliseconds -lt $ms) }
function Argb($colour) { return [int]$colour.ToArgb() }
function Make([string]$type) { return [Activator]::CreateInstance((T $type), $instance, $null, [object[]]@(), $null) }
function Bare([object[]]$items) { return [object[]]@($items | ForEach-Object { if ($_ -is [Management.Automation.PSObject]) { $_.PSObject.BaseObject } else { $_ } }) }
function MakeWith([string]$type, [object[]]$arguments) { return [Activator]::CreateInstance((T $type), $instance, $null, (Bare $arguments), $null) }

$null = S 'Palette' 'Adopt' @('light')
SetSF 'Soft' 'WindowsAnimates' ([Said]::Answer($true))
SetSF 'Soft' 'ReduceMotionSetting' $false
$out = @{}
$origin = New-Object Drawing.Point -30000, -30000
function New-Window {
    $form = New-Object QuietForm
    $form.FormBorderStyle = 'None'
    $form.ShowInTaskbar = $false
    $form.StartPosition = 'Manual'
    $form.Location = $origin
    $form.Size = New-Object Drawing.Size 700, 500
    $form.BackColor = (SProp 'Palette' 'Canvas')
    return $form
}
$form = New-Window
$form.Show()
Pump 30
$out.allowedHere = -not [bool](SProp 'Soft' 'ReduceMotion')
"""

PROBE_TAIL = r"""
$form.Close()
$form.Dispose()
[IO.File]::WriteAllText((Join-Path $env:CAR_WORK 'result.json'), ($out | ConvertTo-Json -Depth 8 -Compress))
"""

PROBE_SHARED = r"""
# ------------------------------------------------------------------ the shared pieces
$red = [Drawing.Color]::FromArgb(255, 200, 0, 0); $blue = [Drawing.Color]::FromArgb(255, 0, 0, 200)
$see = S 'SurfaceLook' 'None' @($blue)
$one = MakeWith 'SurfaceLook' @($red, $red, $red, $see)
$two = MakeWith 'SurfaceLook' @($blue, $blue, $blue, $blue)
$half = S 'SurfaceLook' 'Between' @($one, $two, [double]0.5)
$out.lookHalf = @((Argb (F $half 'Fill')), (Argb (F $half 'Mark')))
$out.lookEnds = @((Argb (F (S 'SurfaceLook' 'Between' @($one, $two, [double]0)) 'Fill')), (Argb (F (S 'SurfaceLook' 'Between' @($one, $two, [double]1)) 'Fill')))
$out.press = [int](SProp 'Motion' 'Press')
$out.duration = [int](SProp 'Motion' 'Duration')
$host1 = New-Object Windows.Forms.Panel
$host1.Size = New-Object Drawing.Size 40, 40
$form.Controls.Add($host1)
Pump 30
$time = MakeWith 'Transition' @($host1, [double]0)
$before = [int](SF 'Transition' 'Moving')
$time.GetType().GetMethod('To', $instance, $null, [Type[]]@([double], [bool], [int]), $null).Invoke($time, [object[]]@([double]1, $true, [int]80)) | Out-Null
$out.shortRuns = [bool](P $time 'Running')
$out.shortMoving = [int](SF 'Transition' 'Moving') - $before
Pump 400
$out.shortArrived = @([double](P $time 'Value'), [bool](P $time 'Running'), ([int](SF 'Transition' 'Moving') - $before))
$time.GetType().GetMethod('To', $instance, $null, [Type[]]@([double], [bool]), $null).Invoke($time, [object[]]@([double]0, $false)) | Out-Null
$out.immediate = @([double](P $time 'Value'), [bool](P $time 'Running'))
$time.GetType().GetMethod('Dispose').Invoke($time, @()) | Out-Null
"""


class Probed(unittest.TestCase):
    """The compiled window, one probe, one answer."""

    sections: tuple[str, ...] = ()
    timeout = 240

    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        work = Path(cls.folder.name)
        exe = compile_window(work)
        cls.answer = run_probe(PROBE_HEAD + "".join(cls.sections) + PROBE_TAIL, work, cls.timeout, CAR_EXE=str(exe))
        assert cls.answer["allowedHere"], "motion was reduced with Windows' switch answered 'on'"

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()


class TokenTests(unittest.TestCase):
    def test_the_press_is_brands_one_shorter_time_for_the_window_and_the_panel_alike(self):
        self.assertEqual(brand.MOTION["press_ms"], 80)
        self.assertLess(brand.MOTION["press_ms"], brand.MOTION["transition_ms"])
        self.assertIn("const int TransitionPressMs = 80;", guiscan.read("gui/Brand.cs"))
        self.assertIn("--transition-press: 80ms;", brand_css.css_scale())
        panel = (ROOT / "src/codex_auto_resume/mcp/assets/panel.css").read_text(encoding="utf-8")
        self.assertEqual(len(re.findall(r"button[^{\n]*:active:not\(\[disabled\]\) \{[^}]*transition-duration: var\(--transition-press\);",
                                        panel)), 2, "a plain and a primary button press in the same time")

    def test_the_helper_is_one_transition_and_nothing_but_paint(self):
        body = guiscan.type_body("SoftSurfaceGlide")
        self.assertEqual(body.count("new Transition("), 1)
        for never in ("PerformLayout", "new Bitmap", "new Timer", "Sleep"):
            self.assertNotIn(never, body)
        self.assertIn("Motion.Allowed(owner)", body, "every glide is asked through the one gate")


class SharedPieceTests(Probed):
    sections = (PROBE_SHARED,)

    def test_tokens_reach_the_window(self):
        self.assertEqual(self.answer["press"], brand.MOTION["press_ms"])
        self.assertEqual(self.answer["duration"], brand.MOTION["transition_ms"])

    def test_a_look_mixes_every_colour_and_a_part_with_nothing_behind_it_only_appears(self):
        fill, mark = self.answer["lookHalf"]
        self.assertEqual((fill >> 16) & 255, 100)
        self.assertEqual(fill & 255, 100)
        self.assertEqual((mark >> 24) & 255, 128, "half way in from nothing is half see-through")
        self.assertEqual(mark & 0xFFFFFF, 200, "and keeps the colour it is going to")
        start, end = self.answer["lookEnds"]
        self.assertEqual((start >> 16) & 255, 200)
        self.assertEqual(end & 255, 200)

    def test_a_transition_takes_the_time_it_is_given_and_leaves_no_timer(self):
        self.assertTrue(self.answer["shortRuns"])
        self.assertEqual(self.answer["shortMoving"], 1)
        self.assertEqual(self.answer["shortArrived"], [1.0, False, 0])
        self.assertEqual(self.answer["immediate"], [0.0, False])


if __name__ == "__main__":
    unittest.main()
