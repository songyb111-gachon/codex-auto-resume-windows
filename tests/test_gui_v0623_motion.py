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
public static class Quiet {
    [System.Runtime.InteropServices.DllImport("user32.dll")] public static extern IntPtr SendMessage(IntPtr window, int message, IntPtr wParam, IntPtr lParam);
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
function Bare([object[]]$items) { $bare = New-Object 'object[]' $items.Length; for ($i = 0; $i -lt $items.Length; $i++) { $one = $items[$i]; if ($one -is [Management.Automation.PSObject]) { $one = $one.PSObject.BaseObject }; $bare[$i] = $one }; return ,$bare }
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


PROBE_CONTROLS = r"""
# ------------------------------------------------------------------ helpers
$None = [EventArgs]::Empty
function Left { return New-Object Windows.Forms.MouseEventArgs ([Windows.Forms.MouseButtons]::Left), 1, 2, 2, 0 }
function Key([Windows.Forms.Keys]$key) { return New-Object Windows.Forms.KeyEventArgs $key }
$space = [Windows.Forms.Keys]::Space
function Lift($control) { return (T 'ISoftLifted').GetProperty('Lift').GetValue($control, $null) }
function Fill($glide) { return Argb (F (P $glide 'Now') 'Fill') }
function Edge($glide) { return Argb (F (P $glide 'Now') 'Edge') }
function Ink($glide) { return Argb (F (P $glide 'Now') 'Ink') }
function Length($glide) { return [int](F (F $glide 'time') 'length') }
function Colour([string]$name) { return Argb (SProp 'Palette' $name) }
function Frames($control, [Drawing.Rectangle]$clip, [int]$count) {
    $bitmap = New-Object Drawing.Bitmap $control.Width, $control.Height
    $g = [Drawing.Graphics]::FromImage($bitmap)
    for ($i = 0; $i -lt $count; $i++) { $e = New-Object Windows.Forms.PaintEventArgs $g, $clip; $null = Call $control 'OnPaint' @($e) }
    $g.Dispose(); $bitmap.Dispose()
}
function Reduce([bool]$on) { SetSF 'Soft' 'ReduceMotionSetting' $on }
function Place($control, [int]$x, [int]$y, [int]$w, [int]$h) { $control.Location = New-Object Drawing.Point $x, $y; $control.Size = New-Object Drawing.Size $w, $h; $form.Controls.Add($control) }
function Enter($control) { $null = Call $control 'OnMouseEnter' @($None) }
function Leave($control) { $null = Call $control 'OnMouseLeave' @($None) }
function Down($control) { $null = Call $control 'OnMouseDown' @((Left)) }
function Up($control) { $null = Call $control 'OnMouseUp' @((Left)) }
function Pixels([scriptblock]$draw, [int]$w, [int]$h) {
    $bitmap = New-Object Drawing.Bitmap $w, $h, ([Drawing.Imaging.PixelFormat]::Format32bppArgb)
    $g = [Drawing.Graphics]::FromImage($bitmap)
    $g.Clear([Drawing.Color]::White)
    & $draw $g
    $g.Dispose()
    return $bitmap
}
function Same($one, $other) {
    for ($y = 0; $y -lt $one.Height; $y++) { for ($x = 0; $x -lt $one.Width; $x++) { if ($one.GetPixel($x, $y).ToArgb() -ne $other.GetPixel($x, $y).ToArgb()) { return $false } } }
    return $true
}
Pump 20
$out.colours = @{ raised = (Colour 'Raised'); surface = (Colour 'Surface'); inset = (Colour 'Inset'); accent = (Colour 'Accent'); accentHover = (Colour 'AccentHover');
                  accentPressed = (Colour 'AccentPressed'); muted = (Colour 'Muted'); line = (Colour 'Line'); card = (Colour 'Card') }

# ------------------------------------------------------------------ the button
$b = MakeWith 'SoftButton' @($false); $b.Text = 'Button'; Place $b 20 20 120 34; Pump 30
$g = F $b 'glide'
$out.buttonRest = @((Fill $g), [bool](P $g 'Running'))
Enter $b
$out.buttonHover = @{ running = [bool](P $g 'Running'); start = (Fill $g); length = (Length $g) }
Pump 400
$out.buttonHover.end = (Fill $g); $out.buttonHover.after = [bool](P $g 'Running')
$before = (Lift $b)
Down $b
$out.buttonPress = @{ running = [bool](P $g 'Running'); length = (Length $g); liftBefore = $before; liftNow = (Lift $b); pressed = [bool](F $b 'pressed') }
Pump 300
$out.buttonPress.end = (Fill $g)
Up $b
$out.buttonPress.releaseLength = (Length $g)
$out.buttonPress.liftBack = (Lift $b)
Pump 300
$null = Call $b 'OnKeyDown' @((Key $space))
$out.buttonKey = @{ down = [bool](F $b 'pressed'); running = [bool](P $g 'Running') }
$null = Call $b 'OnKeyUp' @((Key $space))
$out.buttonKey.up = [bool](F $b 'pressed')
Pump 200
Leave $b
Pump 400
Reduce $true
Enter $b
$out.buttonReduced = @{ running = [bool](P $g 'Running'); fill = (Fill $g) }
Leave $b
Reduce $false
$p = MakeWith 'SoftButton' @($true); $p.Text = 'Primary'; Place $p 160 20 120 34; Pump 30
$pg = F $p 'glide'
Enter $p
Pump 400
$out.primaryHover = (Fill $pg)
Down $p
Pump 300
$out.primaryPress = (Fill $pg)
Up $p; Leave $p
Pump 300

# ------------------------------------------------------------------ a call's first moments
$out.hold = @{}
$out.hold.began = [bool](S 'BusyHold' 'Begin' @($null))
$b.Enabled = $false
$out.hold.held = [bool](F $b 'held')
$out.hold.real = [bool]$b.Enabled
$out.hold.running = [bool](P $g 'Running')
$out.hold.fill = (Fill $g)
$out.hold.lift = (Lift $b)
$b.Enabled = $true
$null = S 'BusyHold' 'End' @()
$out.hold.afterEnd = @([bool](F $b 'held'), [bool](P $g 'Running'), (Fill $g), [bool](SProp 'BusyHold' 'On'))
$null = S 'BusyHold' 'Begin' @($null)
$b.Enabled = $false
Pump 500
$out.hold.long = @([bool](F $b 'held'), (Fill $g), (Ink $g), (Lift $b), [bool](SProp 'BusyHold' 'On'))
$null = S 'BusyHold' 'End' @()
$b.Enabled = $true
Pump 300
Reduce $true
$out.hold.reduced = [bool](S 'BusyHold' 'Begin' @($null))
$b.Enabled = $false
$out.hold.reducedHeld = [bool](F $b 'held')
$b.Enabled = $true
Reduce $false
Pump 50

# ------------------------------------------------------------------ the switch
$s = Make 'SoftCheck'; $s.Text = 'A switch'; Place $s 20 70 240 30; Pump 30
$hot = F $s 'hot'; $held = F $s 'down'; $turn = F $s 'turn'; $live = F $s 'live'
Enter $s
$out.switchHover = @{ running = [bool](P $hot 'Running') }
Pump 400
$out.switchHover.end = [double](P $s 'Hot')
Down $s
$out.switchPress = @{ running = [bool](P $held 'Running'); length = [int](F $held 'length') }
Pump 300
$out.switchPress.end = [double](P $s 'Down')
Up $s
Pump 300
$out.switchPress.released = [double](P $s 'Down')
Leave $s
Pump 300
$out.switchHover.left = [double](P $s 'Hot')
$null = Call $s 'OnKeyDown' @((Key $space))
Pump 300
$out.switchKey = [double](P $s 'Down')
$null = Call $s 'OnKeyUp' @((Key $space))
Pump 300
$where = F $turn 'Where'
$first = $where.Invoke()
$s.Height = 60
$second = $where.Invoke()
$out.switchWhere = @([int]$first.Y, [int]$second.Y)
$s.Height = 30
Pump 30
$s.Checked = $false
Pump 300
$made = [int](SF 'GroundShot' 'Made')
$s.Checked = $true
$running = [bool](P $turn 'Running')
Frames $s (P $s 'Glyph') 6
$out.switchFrames = @{ running = $running; made = ([int](SF 'GroundShot' 'Made') - $made) }
Pump 400
$out.switchFrames.shotLeft = ((F (F $s 'shot') 'picture') -ne $null)
Frames $s $s.ClientRectangle 1
$out.switchFrames.shotAfterRest = ((F (F $s 'shot') 'picture') -ne $null)
$s.Checked = $false
Pump 400
$s.Enabled = $false
$out.switchDisabled = @{ running = [bool](P $live 'Running') }
Pump 400
$out.switchDisabled.end = [double](P $live 'Value')
$s.Enabled = $true
Pump 400
Reduce $true
Enter $s
$out.switchReduced = @([bool](P $hot 'Running'), [double](P $s 'Hot'))
Leave $s
Reduce $false

# drawn: exact at rest, and what each part does
$track = New-Object Drawing.Rectangle 4, 4, 40, 22
$ground = (SProp 'Palette' 'Card')
function DrawLive($g, [double]$on, [double]$lv, [double]$hv, [double]$pr) { $null = S 'Soft' 'SwitchLive' @($g, $track, $on, $lv, $hv, $pr, $ground, $false) }
$out.switchDrawn = @{}
foreach ($on in 0.0, 0.5, 1.0) {
    $a = Pixels { param($g) $null = S 'Soft' 'SwitchSide' @($g, $track, [double]$on, $true, $ground, $false) } 50 30
    $c = Pixels { param($g) DrawLive $g $on 1.0 0.0 0.0 } 50 30
    $out.switchDrawn["same$on"] = (Same $a $c); $a.Dispose(); $c.Dispose()
}
$a = Pixels { param($g) $null = S 'Soft' 'SwitchSide' @($g, $track, [double]0, $false, $ground, $false) } 50 30
$c = Pixels { param($g) DrawLive $g 0.0 0.0 0.0 0.0 } 50 30
$out.switchDrawn.sameDisabled = (Same $a $c); $a.Dispose(); $c.Dispose()
function KnobWidth($bitmap, [int]$y, [int]$from) { $n = 0; $knob = (Colour 'Muted'); for ($x = 0; $x -lt $bitmap.Width; $x++) { if ($bitmap.GetPixel($x, $y).ToArgb() -eq $knob) { $n++ } }; return $n }
$rest = Pixels { param($g) DrawLive $g 0.0 1.0 0.0 0.0 } 50 30
$down = Pixels { param($g) DrawLive $g 0.0 1.0 0.0 1.0 } 50 30
$hov = Pixels { param($g) DrawLive $g 0.0 1.0 1.0 0.0 } 50 30
$out.switchDrawn.knob = @((KnobWidth $rest 15 0), (KnobWidth $down 15 0))
$out.switchDrawn.hoverWell = (Argb $hov.GetPixel(38, 15)); $out.switchDrawn.restWell = (Argb $rest.GetPixel(38, 15))
$rest.Dispose(); $down.Dispose(); $hov.Dispose()

# ------------------------------------------------------------------ the check box
$k = Make 'SoftCheck'; $k.Text = 'A box'; $null = $k.GetType().GetProperty('Box', $instance).SetValue($k, $true, $null); Place $k 20 110 240 30; Pump 30
$glyph = P $k 'Glyph'
$made = [int](SF 'SoftCheck+BoxGlyphs' 'Made')
$k.Checked = $true
Frames $k $glyph 6
$first = [int](SF 'SoftCheck+BoxGlyphs' 'Made') - $made
Pump 400
$k.Checked = $false
$made2 = [int](SF 'SoftCheck+BoxGlyphs' 'Made')
Frames $k $glyph 6
$out.boxFrames = @{ first = $first; second = ([int](SF 'SoftCheck+BoxGlyphs' 'Made') - $made2) }
Pump 400
$face = New-Object Drawing.Rectangle 4, 4, 18, 18
function BoxAt([double]$on) { return Pixels { param($g) $null = S 'SoftCheck' 'DrawBoxAt' @($g, $face, $on, $true) } 26 26 }
function Light($bitmap, [int]$fromX) { $n = 0; for ($y = 0; $y -lt 26; $y++) { for ($x = $fromX; $x -lt 22; $x++) { $p = $bitmap.GetPixel($x, $y); if ($p.R -gt 235 -and $p.G -gt 235 -and $p.B -gt 235 -and $x -gt 5 -and $y -gt 5 -and $y -lt 20 -and $x -lt 21) { $n++ } } }; return $n }
$early = BoxAt 0.2; $late = BoxAt 0.92
$out.boxDrawn = @{ earlyRight = (Light $early 14); lateRight = (Light $late 14) }
$early.Dispose(); $late.Dispose()

# ------------------------------------------------------------------ the tab
$n = Make 'NavButton'; $n.Text = 'Pending'; Place $n 300 20 120 40; Pump 30
$ng = F $n 'glide'
$out.navRest = @{ fillAlpha = (((Fill $ng) -shr 24) -band 255); running = [bool](P $ng 'Running') }
Enter $n
$out.navHover = @{ running = [bool](P $ng 'Running'); length = (Length $ng) }
Pump 400
$out.navHover.end = (Fill $ng)
Down $n
$out.navPress = @{ running = [bool](P $ng 'Running'); length = (Length $ng); pressed = [bool](F $n 'pressed') }
Pump 300
$out.navPress.end = (Fill $ng)
Up $n; Leave $n
Pump 400
$n.GetType().GetProperty('Current', $instance).SetValue($n, $true, $null)
$out.navCurrent = @{ running = [bool](P $ng 'Running'); length = (Length $ng) }
Pump 400
$out.navCurrent.end = (Fill $ng); $out.navCurrent.ink = (Ink $ng)
$face2 = (F $ng 'time')
$w = F $face2 'Where'
$out.navWhere = @([int]$w.Invoke().Width, [int](P $n 'Face').Width)

# ------------------------------------------------------------------ the choice card
$a1 = MakeWith 'ChoiceCard' @('a', 'Title', 'Help'); Place $a1 300 80 300 60; Pump 30
$ag = F $a1 'glide'
$null = Fill $ag      # what a painted control knows it is showing: a window this far off the screen is not painted
Enter $a1
$out.choiceHover = @{ running = [bool](P $ag 'Running') }
Pump 400
$out.choiceHover.end = (Fill $ag)
Leave $a1
Pump 400
$out.choiceLiftRest = (Lift $a1)
$a1.Checked = $true
$out.choiceChosen = @{ running = [bool](P $ag 'Running'); lift = (Lift $a1) }
Pump 400
$out.choiceChosen.end = (Fill $ag); $out.choiceChosen.edge = (Edge $ag)

# ------------------------------------------------------------------ the number and the text well
$num = Make 'SoftNumber'; Place $num 300 160 120 34; Pump 40
$focus = F $num 'focus'
$null = Call (F $num 'Spin') 'OnEnter' @($None)
$out.numberFocus = @{ running = [bool](P $focus 'Running') }
Pump 400
$out.numberFocus.end = [double](P $focus 'Value')
$null = Call (F $num 'Spin') 'OnLeave' @($None)
Pump 400
$buttons = (F $num 'Spin').Controls[0]
$painter = F $num 'painter'
$glow = F $painter 'glow'
function Msg($handle, [int]$m, [int]$lp) { $null = [Quiet]::SendMessage($handle, $m, [IntPtr]::Zero, [IntPtr]$lp) }
$hh = $buttons.Handle
$hgt = $buttons.ClientSize.Height
Msg $hh 0x0200 (2 -shl 16 -bor 2)
$out.spin = @{ upper = [int](P $painter 'Half'); running = [bool](P $glow 'Running'); length = [int](F $glow 'length') }
Pump 200
Msg $hh 0x0200 ((($hgt - 2) -shl 16) -bor 2)
$out.spin.lower = [int](P $painter 'Half')
Msg $hh 0x02A3 0
$out.spin.left = [int](P $painter 'Half')
Pump 200
$out.spin.gone = [double](P $glow 'Value')
$area = Make 'SoftTextArea'; Place $area 440 160 200 80; Pump 40
$af = F $area 'focus'
$null = Call (F $area 'Box') 'OnGotFocus' @($None)
$out.areaFocus = @{ running = [bool](P $af 'Running') }
Pump 400
$out.areaFocus.end = [double](P $af 'Value')
$null = Call (F $area 'Box') 'OnLostFocus' @($None)
Pump 400

# ------------------------------------------------------------------ the drop-down
SetSF 'SoftDropList' 'Area' (New-Object Drawing.Rectangle ($origin.X - 3000), ($origin.Y - 3000), 8000, 8000)
$combo = Make 'SoftCombo'; Place $combo 20 200 240 34
foreach ($i in 1..14) { $null = $combo.Items.Add("Item $i") }
$combo.SelectedIndex = 0
Pump 40
$cg = F $combo 'faceGlide'
Enter $combo
$out.comboHover = @{ running = [bool](P $cg 'Running') }
Pump 400
$out.comboHover.edge = (Edge $cg)
$null = Call $combo 'OpenList' @($false)
$drop = P $combo 'DropList'
$out.comboOpen = @{ open = [bool](P $combo 'Open'); turning = [bool](P (F $combo 'chevron') 'Running') }
Pump 500
$out.comboOpen.turn = [double](P $combo 'ChevronTurn')
$out.comboOpen.edge = (Edge $cg)
$renders = [int](P $drop 'Renders'); $patches = [int](P $drop 'Patches')
function Pill($index) { return (Call $drop 'PillRect' @([int]$index)) }
function AtPill($index) {
    $r = Pill $index
    $m = F $drop 'margin'
    return (P $drop 'Image').GetPixel($r.X + $m.Left + 3, $r.Y + $m.Top + [int]($r.Height / 2)).ToArgb()
}
$null = Call $drop 'SetHover' @([int]4)
$h4 = AtPill 4
$null = Call $drop 'SetHover' @([int]5)
$h4b = AtPill 4; $h5 = AtPill 5
$out.comboList = @{ renders = ([int](P $drop 'Renders') - $renders); patches = ([int](P $drop 'Patches') - $patches); raised4 = $h4; back4 = $h4b; raised5 = $h5; hover = [int](F $drop 'hover') }
$null = Call $combo 'CloseList' @()
$fade = F $combo 'fading'
$out.comboClose = @{ open = [bool](P $combo 'Open'); closing = [bool](P $fade 'Closing'); turning = [bool](P (F $combo 'chevron') 'Running') }
Pump 400
$out.comboClose.fading = ((F $combo 'fading') -ne $null)
$out.comboClose.turn = [double](P $combo 'ChevronTurn')
Reduce $true
$null = Call $combo 'OpenList' @($false)
$null = Call $combo 'CloseList' @()
$out.comboReduced = @(((F $combo 'fading') -ne $null), [bool](P $combo 'Open'), [double](P $combo 'ChevronTurn'))
Reduce $false
Leave $combo
Pump 300
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


class ControlTests(Probed):
    sections = (PROBE_CONTROLS,)

    @property
    def c(self):
        return self.answer["colours"]

    # ------------------------------------------------------------------ the button
    def test_a_button_glides_to_its_hover_in_brands_transition(self):
        hover = self.answer["buttonHover"]
        self.assertTrue(hover["running"])
        self.assertEqual(hover["length"], brand.MOTION["transition_ms"])
        self.assertEqual(hover["end"], self.c["surface"])
        self.assertFalse(hover["after"], "no timer is left running")

    def test_a_press_glides_in_the_press_time_and_swaps_the_shadow_at_once(self):
        press = self.answer["buttonPress"]
        self.assertTrue(press["running"])
        self.assertEqual(press["length"], brand.MOTION["press_ms"])
        self.assertEqual(press["releaseLength"], brand.MOTION["press_ms"])
        self.assertEqual(press["liftBefore"], "control")
        self.assertIsNone(press["liftNow"], "the shadow goes at the press")
        self.assertEqual(press["liftBack"], "control", "and comes back at the release")
        self.assertEqual(press["end"], self.c["inset"])

    def test_a_key_press_shows_as_a_mouse_press_does(self):
        key = self.answer["buttonKey"]
        self.assertTrue(key["down"])
        self.assertTrue(key["running"])
        self.assertFalse(key["up"])

    def test_enter_on_a_focused_button_shows_too(self):
        body = guiscan.member_body("SoftButton", "ProcessDialogKey")
        self.assertIn("Keys.Enter", body)
        self.assertIn("Press(true)", body)
        self.assertIn("Press(false)", guiscan.member_body("SoftButton", "OnLostFocus"), "a key lost to a dialog is no press held")

    def test_with_motion_reduced_a_button_changes_at_once(self):
        reduced = self.answer["buttonReduced"]
        self.assertFalse(reduced["running"])
        self.assertEqual(reduced["fill"], self.c["surface"])

    def test_a_primary_button_mixes_its_accents(self):
        self.assertEqual(self.answer["primaryHover"], self.c["accentHover"])
        self.assertEqual(self.answer["primaryPress"], self.c["accentPressed"])

    # ------------------------------------------------------------------ a call's first moments
    def test_a_button_turned_off_by_a_call_looks_as_it_did_for_its_first_moments(self):
        hold = self.answer["hold"]
        self.assertTrue(hold["began"])
        self.assertFalse(hold["real"], "it refuses a click at once")
        self.assertTrue(hold["held"])
        self.assertFalse(hold["running"], "nothing has started to move")
        self.assertEqual(hold["lift"], "control", "and it keeps its shadow")

    def test_a_call_over_in_time_has_shown_nothing(self):
        self.assertEqual(self.answer["hold"]["afterEnd"][:2], [False, False])
        self.assertEqual(self.answer["hold"]["afterEnd"][2], self.answer["hold"]["fill"])
        self.assertFalse(self.answer["hold"]["afterEnd"][3], "nothing is left held")

    def test_a_call_still_running_shows_and_nothing_is_held_for_ever(self):
        held, fill, ink, lift, on = self.answer["hold"]["long"]
        self.assertFalse(held)
        self.assertEqual(fill, self.c["surface"])
        self.assertEqual(ink, self.c["muted"])
        self.assertIsNone(lift)
        self.assertFalse(on)

    def test_with_motion_reduced_nothing_is_held(self):
        self.assertFalse(self.answer["hold"]["reduced"])
        self.assertFalse(self.answer["hold"]["reducedHeld"])

    def test_every_call_goes_through_the_hold(self):
        body = guiscan.member_body("SettingsForm", "SetBusy")
        self.assertIn("BusyHold.Begin(", body)
        self.assertIn("BusyHold.End()", body)

    # ------------------------------------------------------------------ the switch and the box
    def test_a_switch_answers_the_pointer(self):
        hover, press = self.answer["switchHover"], self.answer["switchPress"]
        self.assertTrue(hover["running"])
        self.assertEqual(hover["end"], 1.0)
        self.assertEqual(hover["left"], 0.0)
        self.assertTrue(press["running"])
        self.assertEqual(press["length"], brand.MOTION["press_ms"])
        self.assertEqual(press["end"], 1.0)
        self.assertEqual(press["released"], 0.0)
        self.assertEqual(self.answer["switchKey"], 1.0, "Space holds it down as the mouse does")

    def test_with_motion_reduced_a_switch_answers_at_once(self):
        self.assertEqual(self.answer["switchReduced"], [False, 1.0])

    def test_a_glide_repaints_where_the_glyph_is_now(self):
        first, second = self.answer["switchWhere"]
        self.assertGreater(second, first, "Transition.Where, not an Area taken once")

    def test_a_switch_takes_one_picture_of_the_ground_for_a_glide_and_none_for_a_frame(self):
        frames = self.answer["switchFrames"]
        self.assertTrue(frames["running"])
        self.assertEqual(frames["made"], 1, "six frames of one glide")
        self.assertFalse(frames["shotAfterRest"], "and lets it go at rest")

    def test_a_switch_fades_when_it_is_disabled(self):
        self.assertTrue(self.answer["switchDisabled"]["running"])
        self.assertEqual(self.answer["switchDisabled"]["end"], 0.0)

    def test_the_switch_is_the_old_switch_at_rest(self):
        drawn = self.answer["switchDrawn"]
        for key in ("same0", "same0.5", "same1", "sameDisabled"):
            self.assertTrue(drawn[key], key)

    def test_held_down_the_knob_widens_and_under_the_pointer_the_well_comes_up(self):
        drawn = self.answer["switchDrawn"]
        rest, held = drawn["knob"]
        self.assertGreater(held, rest)
        self.assertNotEqual(drawn["hoverWell"], drawn["restWell"])

    def test_a_check_box_makes_no_bitmap_for_a_frame(self):
        frames = self.answer["boxFrames"]
        self.assertLessEqual(frames["first"], 2, "two pictures, at most, the first time")
        self.assertEqual(frames["second"], 0, "and none the next")
        for member in ("DrawBoxAt", "DrawBoxLive"):
            self.assertNotIn("new Bitmap", guiscan.member_body("SoftCheck", member))

    def test_a_check_mark_is_drawn_on_along_its_stroke(self):
        drawn = self.answer["boxDrawn"]
        self.assertEqual(drawn["earlyRight"], 0, "a fifth of the way along, the long leg has not begun")
        self.assertGreater(drawn["lateRight"], 0)

    # ------------------------------------------------------------------ the tab
    def test_a_tab_has_no_body_at_rest_and_fades_one_in_under_the_pointer(self):
        self.assertEqual(self.answer["navRest"]["fillAlpha"], 0)
        hover = self.answer["navHover"]
        self.assertTrue(hover["running"])
        self.assertEqual(hover["length"], brand.MOTION["transition_ms"])
        self.assertEqual(hover["end"], self.c["raised"])

    def test_a_tab_presses_and_a_chosen_tab_glides_into_its_well(self):
        press, current = self.answer["navPress"], self.answer["navCurrent"]
        self.assertTrue(press["running"])
        self.assertEqual(press["length"], brand.MOTION["press_ms"])
        self.assertEqual(press["end"], self.c["inset"])
        self.assertTrue(current["running"])
        self.assertEqual(current["end"], self.c["inset"])
        self.assertEqual(current["ink"], self.c["accent"])

    def test_a_tab_repaints_its_own_body(self):
        where, face = self.answer["navWhere"]
        self.assertEqual(where, face)

    def test_the_page_under_a_tab_is_still_one_finished_frame(self):
        for member in ("ShowPage",):
            self.assertNotIn("Transition", guiscan.member_body("SettingsForm", member))

    # ------------------------------------------------------------------ the choice card
    def test_a_choice_glides_its_colours_and_swaps_its_shadow_at_the_start(self):
        self.assertTrue(self.answer["choiceHover"]["running"])
        self.assertEqual(self.answer["choiceHover"]["end"], self.c["surface"])
        self.assertEqual(self.answer["choiceLiftRest"], "control")
        chosen = self.answer["choiceChosen"]
        self.assertTrue(chosen["running"])
        self.assertIsNone(chosen["lift"])
        self.assertEqual(chosen["end"], self.c["inset"])
        self.assertEqual(chosen["edge"], self.c["accent"])

    # ------------------------------------------------------------------ the number and the text well
    def test_a_field_s_focus_line_glides(self):
        for key in ("numberFocus", "areaFocus"):
            self.assertTrue(self.answer[key]["running"], key)
            self.assertEqual(self.answer[key]["end"], 1.0, key)

    def test_the_spin_buttons_answer_the_pointer(self):
        spin = self.answer["spin"]
        self.assertEqual(spin["upper"], 0)
        self.assertTrue(spin["running"])
        self.assertEqual(spin["length"], brand.MOTION["press_ms"])
        self.assertEqual(spin["lower"], 1)
        self.assertEqual(spin["left"], -1)
        self.assertEqual(spin["gone"], 0.0)

    # ------------------------------------------------------------------ the drop-down
    def test_a_drop_down_s_face_answers_the_pointer_and_its_chevron_turns(self):
        self.assertTrue(self.answer["comboHover"]["running"])
        self.assertNotEqual(self.answer["comboHover"]["edge"], self.c["line"])
        opened = self.answer["comboOpen"]
        self.assertTrue(opened["open"])
        self.assertTrue(opened["turning"])
        self.assertEqual(opened["turn"], 1.0)
        self.assertNotEqual(opened["edge"], self.answer["comboHover"]["edge"], "a step more with its list open")

    def test_moving_down_the_list_never_draws_the_whole_card_again(self):
        moved = self.answer["comboList"]
        self.assertEqual(moved["renders"], 0, "two rows' change drew the whole card")
        self.assertEqual(moved["patches"], 2)
        self.assertEqual(moved["hover"], 5)
        self.assertEqual(moved["raised4"], self.c["raised"])
        self.assertEqual(moved["back4"], self.c["card"], "the row left goes back")
        self.assertEqual(moved["raised5"], self.c["raised"])

    def test_a_list_closed_fades_out_but_is_closed_at_once(self):
        closed = self.answer["comboClose"]
        self.assertFalse(closed["open"])
        self.assertTrue(closed["closing"])
        self.assertTrue(closed["turning"])
        self.assertFalse(closed["fading"], "and is gone")
        self.assertEqual(closed["turn"], 0.0)

    def test_with_motion_reduced_a_list_is_simply_gone(self):
        self.assertEqual(self.answer["comboReduced"], [False, False, 0.0])


if __name__ == "__main__":
    unittest.main()
