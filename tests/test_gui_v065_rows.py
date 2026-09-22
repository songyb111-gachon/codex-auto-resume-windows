r"""The window's lists of conversations are flat rows on their card, by the user's choice (v0.6.5).

For a few hours v0.6.5 drew Pending's and History's rows as raised tiles on the popup's recipe - a lift under each,
brand's tile gap between them, the chosen row pressed into a well, the Auto-resume switch pinned to the tile's right
edge and the empty states as sunken wells in the list. The user looked at the window and said it was too much
neumorphism and that the look before was prettier (2026-09-19: "앱에서 pending 쪽은 너무 과도하게 뉴모피즘을 적용한거
같아 / 기존이 더 예뻐"). So the window's lists are what they were before the tiles (bb0671e) again, and are held here:

  * each row lies flat on the card, filled with the card's colour and closed by a full hairline, with nothing drawn
    under, over or between rows but that hairline - no lift, no shadow, no top light;
  * the column headings are closed by a hairline too;
  * the chosen row is filled with the soft inset colour (Highlight in High Contrast), not pressed into a well;
  * rows follow each other with no gap, each as tall as the image list's 34 px (a ListView makes a row a pixel
    taller than the image it is asked to hold);
  * the Auto-resume switch stands where its column puts it - 12 px in (the cell's 10 and 2 more) - and every heading,
    Auto-resume's too, starts where its column's cells do, however wide the column;
  * the columns share the list's width as they did, a heading's and a cell's inset the 10 px before and 4 after that
    DrawHeader and DrawCell give them and nothing of a tile's;
  * the keyboard's mark is at the chosen row's left end;
  * with nothing to list, or a list that cannot be read, a line over the list's card says so, and the list shows only
    its headings.

The popup and the panel keep their tiles (tests/test_tray_popup.py, tests/test_mcpui_v065.py): the user spoke about the
app window only. The window is therefore deliberately different from them here, and the three-surface design
consistency check must treat that as intended, not as drift - which is why there is no window-to-popup tile parity
test any more.

The real compiled window is built in the probe's own process, as LayoutAudit builds it - a bridge rooted where nothing
is, nothing asked of the watcher - inside a window of the probe's own far off the screen, shown without taking
activation, and sized by SetWindowPos once it is a child so that no screen clamps it - as it opens, wider, and as narrow
as it may be made; its lists are drawn to a bitmap at 100, 150 and 200% in light, dark and High Contrast and read pixel
by pixel. Nothing is sent to any other window.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
import unittest

from codex_auto_resume import brand, l10n

from test_gui_layout import fullest_snapshot

ROOT = Path(__file__).resolve().parents[1]
GUI = ROOT / "gui"
CSC = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe"
POWERSHELL = (Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
              / "WindowsPowerShell" / "v1.0" / "powershell.exe")
SCALES = (1.0, 1.5, 2.0)
THEMES = ("light", "dark", "contrast")
LISTS = ("pendingList", "historyList")
# The proportions the lists' columns were declared with, and how much of what a column holds is kept readable before a
# heading gives way, as the window had them before the tiles (bb0671e: BuildPending, BuildHistory, ReadableCells).
DECLARED = {"pendingList": (140, 190, 110, 84, 70, 100), "historyList": (220, 200, 130, 130, 130)}
READABLE = 96

PROBE = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Windows.Forms
[Windows.Forms.Application]::EnableVisualStyles()
[Windows.Forms.Application]::SetCompatibleTextRenderingDefault($false)
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
    // SWP_NOMOVE | SWP_NOZORDER | SWP_NOACTIVATE: Windows holds only top-level windows to the screen's size.
    public static void Size(Control child, int width, int height) { SetWindowPos(child.Handle, IntPtr.Zero, 0, 0, width, height, 0x0002 | 0x0004 | 0x0010); }
}
public static class Headings {
    [StructLayout(LayoutKind.Sequential)] struct Box { public int Left, Top, Right, Bottom; }
    [DllImport("user32.dll")] static extern IntPtr SendMessage(IntPtr window, int message, IntPtr wParam, IntPtr lParam);
    [DllImport("user32.dll")] static extern bool GetWindowRect(IntPtr window, out Box box);
    // Where a list's column headings end, in its coordinates (LVM_GETHEADER).
    public static int Bottom(ListView list) {
        IntPtr header = SendMessage(list.Handle, 0x101F, IntPtr.Zero, IntPtr.Zero);
        Box box;
        if (header == IntPtr.Zero || !GetWindowRect(header, out box)) return -1;
        return list.PointToClient(new Point(box.Left, box.Bottom)).Y;
    }
}
public static class Pixels {
    // How far past `from` the first pixel of row `y` that is not `ground` is, before `to`; -1 if there is none.
    public static int FirstInk(Bitmap bitmap, int y, int from, int to, int ground) {
        for (int x = from; x < Math.Min(to, bitmap.Width); x++) if (bitmap.GetPixel(x, y).ToArgb() != ground) return x - from;
        return -1;
    }
}
'@
$assembly = [Reflection.Assembly]::LoadFile($env:CAR_EXE)
$static = [Reflection.BindingFlags]'Static,NonPublic,Public'
$instance = [Reflection.BindingFlags]'Instance,NonPublic,Public'
$form = $assembly.GetType('CodexAutoResume.SettingsForm', $true)
$palette = $assembly.GetType('CodexAutoResume.Palette', $true)
$soft = $assembly.GetType('CodexAutoResume.Soft', $true)
$choiceType = $assembly.GetType('CodexAutoResume.ChoiceCard', $true)
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
function Box($r) { return ,@([int]$r.X, [int]$r.Y, [int]$r.Width, [int]$r.Height) }
function Colour([string]$name) { return [int]$palette.GetField($name, $static).GetValue($null).ToArgb() }
function In-Window($window, $control) {
    $p = $window.PointToClient($control.PointToScreen([Drawing.Point]::Empty))
    return ,@([int]$p.X, [int]$p.Y, [int]$control.Width, [int]$control.Height)
}
function Picture($list) {
    $bitmap = New-Object Drawing.Bitmap $list.Width, $list.Height
    $list.DrawToBitmap($bitmap, (New-Object Drawing.Rectangle 0, 0, $list.Width, $list.Height))
    return $bitmap
}
function Down($bitmap, [int]$x, [int]$to) {
    $column = @()
    for ($y = 0; $y -lt [Math]::Min($bitmap.Height, $to); $y++) { $column += [int]$bitmap.GetPixel($x, $y).ToArgb() }
    return ,$column
}
function Across($bitmap, [int]$y, [int]$from, [int]$to) {
    $row = @()
    for ($x = $from; $x -lt [Math]::Min($bitmap.Width, $to); $x++) { $row += [int]$bitmap.GetPixel($x, $y).ToArgb() }
    return ,$row
}
# Where each column's heading starts: how far into its column, across the headings' middle, the first pixel that is not
# the card's is.
function Inks($bitmap, $list, [int]$ground) {
    $y = [int]([Headings]::Bottom($list) / 2)
    $inks = @()
    $left = 0
    foreach ($column in $list.Columns) { $inks += [Pixels]::FirstInk($bitmap, $y, $left, $left + $column.Width, $ground); $left += $column.Width }
    return ,$inks
}
# The columns as they were fitted before the tiles (bb0671e's FitColumns), worked out from the probe's own measures rather
# than the window's: each heading in the list's font with DrawHeader's inset - 10 before, 4 after - and never under 48;
# each column's widest cell as MeasureCells measures it - a state chip in the second column, Pending's switch in its
# last, the words anywhere else - with DrawCell's same inset; the least a column is drawn at, 48 or the switch whole with
# the inset; the floors those give (ColumnFloors, whose arithmetic tests/test_gui_v065_window.py holds) with a dozen
# characters kept readable; and what the list has past them shared in the proportions the columns were declared with,
# the last column taking the rest.
$fitting = ConvertFrom-Json $env:CAR_FITTING
$floorsOf = $form.GetMethod('ColumnFloors', $static)
$switchWidth = [int]$assembly.GetType('CodexAutoResume.Brand', $true).GetField('SwitchWidth', $static).GetValue($null)
$chipSize = $soft.GetMethod('ChipSize', $static)
$clock = $form.GetMethod('Now', $static)
function Px([double]$value) { return [int][Math]::Round($value * [double]$form.GetField('dpiScale', $static).GetValue($null)) }
function Fitted($window, $list, [string]$name) {
    $count = $list.Columns.Count
    $switchColumn = $name -eq 'pendingList'
    $unbounded = New-Object Drawing.Size ([int]::MaxValue), ([int]::MaxValue)
    $single = [Windows.Forms.TextFormatFlags]::SingleLine
    $heading = New-Object int[] $count
    $cells = New-Object int[] $count
    $least = New-Object int[] $count
    for ($c = 0; $c -lt $count; $c++) {
        $ink = [Windows.Forms.TextRenderer]::MeasureText($list.Columns[$c].Text, $list.Font, $unbounded, $single).Width
        $heading[$c] = [Math]::Max((Px 48), $ink + (Px 14))
        $least[$c] = $(if ($switchColumn -and $c -eq $count - 1) { (Px ($switchWidth + 2)) + (Px 14) } else { Px 48 })
    }
    $now = [double]$clock.Invoke($null, @())
    foreach ($item in $list.Items) {
        for ($c = 0; $c -lt $count -and $c -lt $item.SubItems.Count; $c++) {
            # Pending's Next check as the clock writes it (CountdownText): a row holds nothing there before a tick.
            $text = $(if ($switchColumn -and $c -eq 3) { [string](Invoke-Window $window 'CountdownText' @($item.Tag, $now)) } else { $item.SubItems[$c].Text })
            if ($c -eq 1 -and $item.Tag -is [Collections.Generic.Dictionary[string,object]]) { $width = $chipSize.Invoke($null, [object[]]@($text, $list.Font)).Width }
            elseif ($switchColumn -and $c -eq $count - 1) { $width = Px ($switchWidth + 2) }
            else { $width = [Windows.Forms.TextRenderer]::MeasureText($text, $list.Font, $unbounded, $single).Width }
            $cells[$c] = [Math]::Max($cells[$c], $width + (Px 14))
        }
    }
    $available = [int]$list.ClientSize.Width
    $floor = $floorsOf.Invoke($null, [object[]]@([int[]]$heading, [int[]]$cells, [int[]]$least, [int](Px $fitting.readable), $available))
    $weights = @($fitting.declared.$name | ForEach-Object { [int]$_ })
    $total = 0
    foreach ($weight in $weights) { $total += $weight }
    $floors = 0
    foreach ($part in $floor) { $floors += $part }
    $spare = [Math]::Max(0, $available - $floors)
    $expected = @()
    $used = 0
    for ($c = 0; $c -lt $count; $c++) {
        $width = $(if ($c -eq $count - 1) { [Math]::Max($floor[$c], $available - $used) } else { $floor[$c] + [int][Math]::Floor($spare * [double]$weights[$c] / $total) })
        $expected += $width
        $used += $width
    }
    return @{ columns = @($list.Columns | ForEach-Object { [int]$_.Width }); expected = $expected; client = $available
              heading = @($heading); cells = @($cells); least = @($least) }
}
# Nothing moves: the product's own Reduce motion, so a switch is drawn at rest.
$soft.GetField('ReduceMotionSetting', $static).SetValue($null, $true)
$systemScale = [double]$form.GetField('SystemScale', $static).GetValue($null)
$nowhere = [string](Join-Path $work 'nowhere')
$bridgeType = $assembly.GetType('CodexAutoResume.Bridge', $true)
$persistentType = $assembly.GetType('CodexAutoResume.PersistentBridge', $true)
$three = @($form.GetConstructors($instance) | Where-Object { $_.GetParameters().Count -eq 3 })[0]
# Where the keyboard is while a list is not to have it: a text box in a window of the probe's own, off the screen.
$sinkFrame = New-Object QuietForm
$sinkFrame.FormBorderStyle = 'None'; $sinkFrame.ShowInTaskbar = $false; $sinkFrame.StartPosition = 'Manual'
$sinkFrame.Location = New-Object Drawing.Point -32000, -32000
$sinkFrame.ClientSize = New-Object Drawing.Size 100, 40
$sink = New-Object Windows.Forms.TextBox
$sinkFrame.Controls.Add($sink)
$sinkFrame.Show()
$out = @{ system = $systemScale; scales = @{} }
# At each scale the audit measures, whatever this machine's: the window's scale and its font with it, as LayoutAudit sets
# them.
foreach ($scale in (ConvertFrom-Json $env:CAR_SCALES)) {
    $form.GetField('dpiScale', $static).SetValue($null, [double]$scale)
    $factor = [single]($scale / $systemScale)
    $box = [Drawing.SystemFonts]::MessageBoxFont
    [Drawing.Font]$font = New-Object Drawing.Font $box.FontFamily, ($box.SizeInPoints * $factor), $box.Style, ([Drawing.GraphicsUnit]::Point)
    $key = ([double]$scale).ToString('0.0', [Globalization.CultureInfo]::InvariantCulture)
    $out.scales[$key] = @{ hairline = [int]$soft.GetProperty('Hairline', $static).GetValue($null) }
    foreach ($theme in @('light', 'dark', 'contrast')) {
        # The theme is the probe's, not this machine's.
        $null = $palette.GetMethod('Adopt', $static).Invoke($null, [object[]]@($theme))
        $frame = New-Object QuietForm
        $frame.FormBorderStyle = 'None'
        $frame.ShowInTaskbar = $false
        $frame.StartPosition = 'Manual'
        $frame.Location = New-Object Drawing.Point -30000, -30000
        # Every Form is held to the screen's size (MaxWindowTrackSize), and at 150% and 200% the opening
        # size is larger than a CI runner's screen - larger than many - so the window inside is sized by
        # Windows itself once it is a child, which nothing clamps.
        $opening = New-Object Drawing.Size ([int][Math]::Round([int]$form.GetField('OpeningWidth', $static).GetValue($null) * $scale)), ([int][Math]::Round([int]$form.GetField('OpeningHeight', $static).GetValue($null) * $scale))
        $frame.ClientSize = $opening
        $once = $bridgeType.GetConstructors($instance)[0].Invoke([object[]]@($nowhere))
        $bridge = $persistentType.GetConstructors($instance)[0].Invoke([object[]]@($nowhere, $once))
        $window = $three.Invoke([object[]]@($bridge, (Read-Json 'strings-en.json'), $font.PSObject.BaseObject))
        $form.GetField('auditing', $instance).SetValue($window, $true)
        $window.TopLevel = $false
        $window.FormBorderStyle = 'None'
        $window.MinimumSize = [Drawing.Size]::Empty
        $window.Location = [Drawing.Point]::Empty
        $window.ClientSize = $opening
        $frame.Controls.Add($window)
        [Placer]::Size($window, $opening.Width, $opening.Height)
        if ($window.ClientSize -ne $opening) { throw ('the window is ' + $window.ClientSize + ', not its opening size ' + $opening) }
        Invoke-Window $window 'ApplySnapshot' @((Read-Json 'snapshot.json'))
        $null = Invoke-Window $window 'ShowPage' @('pending')
        $window.Visible = $true
        $frame.Show()
        Pump 100
        if ($window.ClientSize -ne $opening) { throw ('the window became ' + $window.ClientSize + ', not its opening size ' + $opening) }
        $entry = @{ card = (Colour 'Card'); inset = (Colour 'Inset'); line = (Colour 'Line'); chosen = (Colour 'AccentSoft')
                    focus = (Colour 'Focus'); secondary = (Colour 'Secondary'); highlightText = [int][Drawing.SystemColors]::HighlightText.ToArgb() }
        foreach ($name in @('pendingList', 'historyList')) {
            $null = Invoke-Window $window 'ShowPage' @($(if ($name -eq 'pendingList') { 'pending' } else { 'history' }))
            Pump 60
            $list = Get-Field $window $name
            $rows = @()
            foreach ($item in $list.Items) { $rows += ,(Box $item.Bounds) }
            $columns = @($list.Columns | ForEach-Object { [int]$_.Width })
            # Down a column no cell's words and no heading reach: the last pixels of the Status column, whose chip and
            # heading stop 4 px short of its end.
            $clear = [int]$columns[0] + [int]$columns[1] - [int][Math]::Round(2 * $scale)
            $to = $rows[2][1] + $rows[2][3] + [int][Math]::Round(20 * $scale)
            $last = 0
            for ($c = 0; $c -lt $columns.Count - 1; $c++) { $last += $columns[$c] }
            $found = @{ rows = $rows; columns = $columns; client = @($list.ClientSize.Width, $list.ClientSize.Height)
                        headings = [Headings]::Bottom($list); children = [int]$list.Controls.Count; last = $last
                        fit = (Fitted $window $list $name) }
            foreach ($state in @('none', 'chosen', 'focus')) {
                foreach ($item in $list.Items) { $item.Selected = $false }
                if ($state -ne 'none') { $list.Items[0].Selected = $true }
                if ($state -eq 'focus') { $null = $list.Focus() } else { $null = $sink.Focus() }
                Pump 60
                $bitmap = Picture $list
                $shot = @{ down = (Down $bitmap $clear $to); focused = [bool]$list.Focused
                           # Across the first row's middle, from its left end: where the keyboard's mark is.
                           mark = (Across $bitmap ($rows[0][1] + [int]($rows[0][3] / 2)) 0 ([int][Math]::Round(12 * $scale))) }
                if ($state -eq 'none') {
                    # Across the second row's middle, over the last column: where its switch stands.
                    $shot.through = Across $bitmap ($rows[1][1] + [int]($rows[1][3] / 2)) $last ($last + [int]$columns[$columns.Count - 1])
                    $shot.inks = Inks $bitmap $list $entry.card
                }
                $bitmap.Dispose()
                $found[$state] = $shot
            }
            $null = $sink.Focus()
            $entry[$name] = $found
        }
        # The same window wider than it opens, so that every column has room past its heading and what it holds - where a
        # heading drawn at its column's right end would stand apart from one at its left - and as narrow as the window may
        # be made (its MinimumSize, 800), where the headings give way.
        foreach ($size in @(@('wide', ($opening.Width + [int][Math]::Round(600 * $scale))), @('narrow', [int][Math]::Round(800 * $scale)))) {
            [Placer]::Size($window, $size[1], $opening.Height)
            Pump 100
            if ($window.ClientSize.Width -ne $size[1]) { throw ('the window is ' + $window.ClientSize + ', not ' + $size[1] + ' wide') }
            foreach ($name in @('pendingList', 'historyList')) {
                $null = Invoke-Window $window 'ShowPage' @($(if ($name -eq 'pendingList') { 'pending' } else { 'history' }))
                Pump 60
                $list = Get-Field $window $name
                foreach ($item in $list.Items) { $item.Selected = $false }
                Pump 30
                $at = @{ fit = (Fitted $window $list $name) }
                if ($size[0] -eq 'wide') {
                    $columns = @($list.Columns | ForEach-Object { [int]$_.Width })
                    $last = 0
                    for ($c = 0; $c -lt $columns.Count - 1; $c++) { $last += $columns[$c] }
                    $second = $list.Items[1].Bounds
                    $bitmap = Picture $list
                    $at.inks = Inks $bitmap $list $entry.card
                    $at.through = Across $bitmap ($second.Y + [int]($second.Height / 2)) $last ($last + [int]$columns[$columns.Count - 1])
                    $bitmap.Dispose()
                }
                $entry[$name][$size[0]] = $at
            }
        }
        [Placer]::Size($window, $opening.Width, $opening.Height)
        Pump 100
        if ($window.ClientSize -ne $opening) { throw ('the window is ' + $window.ClientSize + ' again, not its opening size ' + $opening) }
        # Nothing to list, and a list that cannot be read: a line over the card, the list with its headings only.
        foreach ($reply in @('empty', 'unreadable')) {
            Invoke-Window $window 'ApplySnapshot' @((Read-Json ($reply + '.json')))
            foreach ($pair in @(@('pendingList', 'pendingEmpty', 'pending'), @('historyList', 'historyEmpty', 'history'))) {
                $null = Invoke-Window $window 'ShowPage' @($pair[2])
                Pump 80
                $list = Get-Field $window $pair[0]
                $label = Get-Field $window $pair[1]
                $card = $list
                while ($card -ne $null -and $card.GetType().Name -ne 'SoftCard') { $card = $card.Parent }
                $bitmap = Picture $list
                $middle = Down $bitmap ([int]($list.ClientSize.Width / 2)) $list.ClientSize.Height
                $bitmap.Dispose()
                $entry[$reply + ':' + $pair[1]] = @{
                    type = $label.GetType().Name; parent = $(if ($label.Parent) { $label.Parent.GetType().Name } else { '' })
                    inList = [bool]($label.Parent -eq $list); visible = [bool]$label.Visible; dock = [string]$label.Dock
                    text = [string]$label.Text; ink = [int]$label.ForeColor.ToArgb(); bounds = (In-Window $window $label)
                    card = (In-Window $window $card); rows = [int]$list.Items.Count; children = [int]$list.Controls.Count
                    headings = [Headings]::Bottom($list); middle = $middle; fit = (Fitted $window $list $pair[0]) }
            }
        }
        # A choice card, resting and chosen, down a column clear of its words and its corners.
        $cards = @{}
        foreach ($chosen in @($false, $true)) {
            $card = [Activator]::CreateInstance($choiceType, $instance, $null, [object[]]@('standard', 'Standard', 'Says why.'), $null)
            $card.Size = New-Object Drawing.Size ([int][Math]::Round(300 * $scale)), ([int][Math]::Round(60 * $scale))
            $card.Checked = $chosen
            $bitmap = New-Object Drawing.Bitmap $card.Width, $card.Height
            $card.DrawToBitmap($bitmap, (New-Object Drawing.Rectangle 0, 0, $card.Width, $card.Height))
            $column = @()
            for ($y = 0; $y -lt $card.Height; $y++) { $column += [int]$bitmap.GetPixel([int]($card.Width - [Math]::Round(30 * $scale)), $y).ToArgb() }
            $bitmap.Dispose()
            $card.Dispose()
            $cards[[string]$chosen] = $column
        }
        $entry.choice = $cards
        $out.scales[$key][$theme] = $entry
        $frame.Close()
        $frame.Dispose()
    }
}
$sinkFrame.Close()
$form.GetField('dpiScale', $static).SetValue($null, $systemScale)
[IO.File]::WriteAllText((Join-Path $work 'result.json'), ($out | ConvertTo-Json -Depth 12 -Compress), $utf8)
[GC]::Collect()
[GC]::WaitForPendingFinalizers()
[Environment]::Exit(0)
"""


def channels(pixel) -> tuple:
    if not isinstance(pixel, int):
        return tuple(int(round(value)) for value in pixel)
    pixel &= 0xFFFFFFFF
    return ((pixel >> 16) & 255, (pixel >> 8) & 255, pixel & 255)


def luminance(pixel) -> float:
    r, g, b = channels(pixel)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def near(one, other, levels=3) -> bool:
    return all(abs(a - b) <= levels for a, b in zip(channels(one), channels(other)))


def card_top_light(theme="dark") -> tuple:
    """The dark card's one-pixel top light over `raised`, as a raised tile carries it (tray_popup.DEPTH)."""
    light = [shadow for shadow in brand.shadows("card", theme) if shadow.inset]
    assert len(light) == 1
    raised = brand.palette(theme)["raised"]
    return brand.rgb(brand.mix(raised, brand.palette(theme)[light[0].token], light[0].alpha))


@unittest.skipUnless(CSC.is_file() and POWERSHELL.is_file(), "needs the in-box compiler and PowerShell")
class RowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        work = Path(cls.folder.name)
        exe = work / "CodexAutoResumeSettings.exe"
        subprocess.run([str(CSC), "/nologo", "/target:winexe", "/platform:x64", "/out:" + str(exe),
                        "/reference:System.dll", "/reference:System.Drawing.dll", "/reference:System.Windows.Forms.dll",
                        *[str(GUI / name) for name in ("SettingsApp.cs", "Dashboard.cs", "Controls.cs", "Brand.cs")]],
                       check=True, capture_output=True, timeout=300)
        cls.catalog = l10n.catalog("en")
        reply = {"ok": True, "language": "en", "strings": cls.catalog, "endonyms": dict(l10n.ENDONYMS),
                 "preference": "en", "system_language": "en"}
        (work / "strings-en.json").write_text(json.dumps(reply, ensure_ascii=False), encoding="utf-8")
        (work / "snapshot.json").write_text(json.dumps(fullest_snapshot(time.time()), ensure_ascii=False), encoding="utf-8")
        empty = fullest_snapshot(time.time())
        empty["pending"], empty["history"] = [], []
        (work / "empty.json").write_text(json.dumps(empty, ensure_ascii=False), encoding="utf-8")
        unreadable = dict(empty)
        unreadable["pending_error"] = unreadable["history_error"] = "unreadable"
        (work / "unreadable.json").write_text(json.dumps(unreadable, ensure_ascii=False), encoding="utf-8")
        probe = work / "rows.ps1"
        probe.write_text(PROBE, encoding="utf-8")
        cls.result = subprocess.run(
            [str(POWERSHELL), "-STA", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(probe)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600,
            env=dict(os.environ, CAR_EXE=str(exe), CAR_WORK=str(work), CAR_SCALES=json.dumps(SCALES),
                     CAR_FITTING=json.dumps({"declared": DECLARED, "readable": READABLE})))
        answer = work / "result.json"
        cls.answer = (json.loads(answer.read_text(encoding="utf-8-sig"))
                      if cls.result.returncode == 0 and answer.is_file() else {})

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def setUp(self):
        if not self.answer:
            self.fail("the probe did not run: " + (self.result.stderr or self.result.stdout)[-4000:])
        self.assertEqual(sorted(self.answer["scales"]), ["%.1f" % scale for scale in SCALES])

    def each(self):
        """(scale, theme, what was drawn in that theme) at every scale and theme."""
        return [(scale, theme, self.answer["scales"]["%.1f" % scale][theme]) for scale in SCALES for theme in THEMES]

    def at(self, scale, theme):
        """A subtest for what was drawn at `scale` in `theme`; px and hairline then answer for that scale."""
        self.scale, self.hairline = scale, self.answer["scales"]["%.1f" % scale]["hairline"]
        return self.subTest(scale=scale, theme=theme)

    def px(self, value):
        return int(round(value * self.scale))

    def band(self, down, top, bottom, colour, what):
        """Every pixel of `down` from `top` to `bottom` is exactly `colour`."""
        wrong = [(y, channels(down[y])) for y in range(top, bottom) if down[y] != colour]
        self.assertEqual(wrong, [], "%s: not %s" % (what, channels(colour)))

    # ---------------------------------------------------------------- the rows

    def test_rows_follow_each_other_at_the_pitch_they_had(self):
        """No gap between rows, each as tall as the image list's 34 px and the pixel a ListView adds - not a tile's
        height and brand's tile gap - and as wide as the columns, from the list's left edge."""
        for scale, theme, drawn in self.each():
            with self.at(scale, theme):
                for name in LISTS:
                    found = drawn[name]
                    rows = found["rows"]
                    with self.subTest(name):
                        self.assertGreaterEqual(len(rows), 3)
                        self.assertEqual(rows[0][1], found["headings"], "the first row starts where the headings end")
                        for x, y, w, h in rows:
                            self.assertEqual(h, self.px(34) + 1)
                            self.assertEqual((x, w), (0, sum(found["columns"])))
                        for above, below in zip(rows, rows[1:]):
                            self.assertEqual(below[1], above[1] + above[3], "no gap between rows")

    def test_rows_lie_flat_on_the_card_closed_by_a_hairline(self):
        """Nothing chosen: every row is the card's own colour down to a full hairline, and the headings are closed by
        a hairline too. Exact colours, so nothing else - no lift, no shadow, no top light - is drawn anywhere."""
        for scale, theme, drawn in self.each():
            with self.at(scale, theme):
                for name in LISTS:
                    found = drawn[name]
                    down, rows = found["none"]["down"], found["rows"]
                    card, line = drawn["card"], drawn["line"]
                    with self.subTest(name):
                        headings = found["headings"]
                        self.band(down, headings - self.hairline, headings, line, "the headings' hairline")
                        self.band(down, 0, headings - self.hairline, card, "the headings' ground")
                        for index, (x, y, w, h) in enumerate(rows[:3]):
                            self.band(down, y, y + h - self.hairline, card, "row %d's ground" % index)
                            self.band(down, y + h - self.hairline, y + h, line, "row %d's hairline" % index)
                        self.assertEqual(set(down[headings:rows[2][1] + rows[2][3]]), {card, line},
                                         "only the card and its hairlines between the rows: nothing lifts a row")

    def test_the_chosen_row_is_filled_softly_not_pressed_into_a_well(self):
        """The chosen row takes the inset colour - Highlight in High Contrast - flat to its hairline, with no shadow
        inside its top edge, and the rows beside it and the headings over it are as they were."""
        for scale, theme, drawn in self.each():
            with self.at(scale, theme):
                for name in LISTS:
                    found = drawn[name]
                    down, rows = found["chosen"]["down"], found["rows"]
                    fill = drawn["chosen"] if theme == "contrast" else drawn["inset"]
                    with self.subTest(name):
                        self.assertFalse(found["chosen"]["focused"])
                        x, y, w, h = rows[0]
                        self.band(down, y, y + h - self.hairline, fill, "the chosen row's fill")
                        self.band(down, y + h - self.hairline, y + h, drawn["line"], "the chosen row's hairline")
                        headings = found["headings"]
                        self.band(down, headings - self.hairline, headings, drawn["line"], "the headings' hairline over it")
                        x, y, w, h = rows[1]
                        self.band(down, y, y + h - self.hairline, drawn["card"], "the row under it")

    def test_the_keyboard_mark_is_at_the_chosen_rows_left_end(self):
        for scale, theme, drawn in self.each():
            with self.at(scale, theme):
                for name in LISTS:
                    found = drawn[name]
                    fill = drawn["chosen"] if theme == "contrast" else drawn["inset"]
                    ink = drawn["highlightText"] if theme == "contrast" else drawn["focus"]
                    with self.subTest(name):
                        self.assertTrue(found["focus"]["focused"], "the probe could not give the list the keyboard")
                        mark = found["focus"]["mark"]
                        at = self.px(2)
                        self.assertTrue(any(near(mark[x], ink, 8) for x in (at - 1, at)),
                                        "%s: the mark 2 px in" % [channels(mark[x]) for x in (at - 1, at)])
                        # Between the mark and where the row's words start (the cell's 10 px), nothing but the row's fill.
                        self.assertTrue(all(pixel == fill for pixel in mark[self.px(4):self.px(10)]),
                                        "nothing else at the row's left end")
                        self.assertTrue(all(pixel == fill for pixel in found["chosen"]["mark"][:self.px(10)]),
                                        "no mark without the keyboard")

    def test_the_switch_stands_where_its_column_puts_it(self):
        """The cell's 10 px and 2 more from the column's left edge, brand's switch wide, and the card after it to the
        column's end - not pinned to the column's or the list's right edge, in the window as it opens and in one wider,
        where the column has room past its heading."""
        for scale, theme, drawn in self.each():
            with self.at(scale, theme):
                found = drawn["pendingList"]
                for where, through in (("opening", found["none"]["through"]), ("wider", found["wide"]["through"])):
                    with self.subTest(where):
                        drawn_at = [x for x, pixel in enumerate(through) if pixel != drawn["card"]]
                        self.assertTrue(drawn_at, "no switch in the Auto-resume column")
                        self.assertAlmostEqual(drawn_at[0], self.px(12), delta=1)
                        self.assertAlmostEqual(drawn_at[-1] + 1, self.px(12) + self.px(brand.LAYOUT["switch_width"]), delta=1)
                        self.assertGreater(len(through) - (drawn_at[-1] + 1), self.px(4), "room after it in its column")

    def test_every_heading_starts_where_its_cells_do(self):
        """Every heading, Auto-resume's too, is drawn from its column's left edge, the cells' 10 px in. In a window
        wider than it opens every column is wider than at the opening size - Auto-resume's by 40 px and more past its
        heading - and each heading's first ink stays exactly as far into its column as it was there; a heading drawn at
        its column's right end, as the tile's Auto-resume heading was, would stand as much further in as its column grew.
        (At the opening size the Auto-resume column is only as wide as its heading, so there alone the two looked the
        same.)"""
        for scale, theme, drawn in self.each():
            with self.at(scale, theme):
                for name in LISTS:
                    found = drawn[name]
                    opening, wider = found["fit"]["columns"], found["wide"]["fit"]["columns"]
                    first, later = found["none"]["inks"], found["wide"]["inks"]
                    with self.subTest(name):
                        self.assertEqual(len(first), len(opening))
                        self.assertEqual(len(later), len(wider))
                        for column, (was, now, at, stays) in enumerate(zip(opening, wider, first, later)):
                            with self.subTest(column=column):
                                self.assertGreaterEqual(now - was, self.px(20), "the column wider than at the opening size")
                                self.assertNotEqual(at, -1, "no heading over the column")
                                self.assertGreaterEqual(at, self.px(10), "where the cells' words start, or past it")
                                self.assertAlmostEqual(stays, at, delta=1,
                                                       msg="as far into its column %d px wider" % (now - was))
                found = drawn["pendingList"]
                # The cell's 10 px, then TextRenderer's own padding before the first letter and that letter's side
                # bearing.
                self.assertLessEqual(found["none"]["inks"][-1], self.px(10) + self.px(6))
                self.assertGreaterEqual(found["wide"]["fit"]["columns"][-1] - found["wide"]["fit"]["heading"][-1],
                                        self.px(40), "room past Auto-resume's heading in the wider window")

    # ---------------------------------------------------------------- the columns

    def fits(self, drawn):
        """(list, where, what the probe found there) for each fitting it recorded: the window as it opens, wider, as
        narrow as it may be made, and with nothing to list and a list that cannot be read."""
        for name, empty in (("pendingList", "pendingEmpty"), ("historyList", "historyEmpty")):
            yield name, "opening", drawn[name]["fit"]
            yield name, "wider", drawn[name]["wide"]["fit"]
            yield name, "narrowest", drawn[name]["narrow"]["fit"]
            for reply in ("empty", "unreadable"):
                yield name, reply, drawn["%s:%s" % (reply, empty)]["fit"]

    def test_the_columns_share_the_list_as_they_did(self):
        """Each column's width is what the window gave it before the tiles, worked out by the probe from its own
        measures of the headings and the cells (Fitted): a heading's inset is DrawHeader's 10 and 4 and a cell's
        DrawCell's, and nothing more - a tile's 12 px before the first column and 16 after the last, under whatever
        name, moves them - in the window as it opens, wider, as narrow as it may be made and with no rows."""
        for scale, theme, drawn in self.each():
            with self.at(scale, theme):
                for name, where, fit in self.fits(drawn):
                    with self.subTest(name, where=where):
                        self.assertEqual(len(fit["expected"]), len(DECLARED[name]))
                        self.assertEqual(fit["columns"], fit["expected"],
                                         "%d wide: headings %s, cells %s, least %s" % (
                                             fit["client"], fit["heading"], fit["cells"], fit["least"]))
                # Different fittings, not one four times: the wider list shares what it has past every column whole, a
                # list with no rows is fitted by its headings alone, and Pending in the narrowest window has not room for
                # every column whole past its first heading, so headings give way (History's list, with its page's width
                # to itself, still has).
                fits = {(name, where): fit for name, where, fit in self.fits(drawn)}
                for name in LISTS:
                    with self.subTest(name):
                        self.assertEqual(sum(fits[name, "wider"]["columns"]), fits[name, "wider"]["client"])
                        self.assertEqual(fits[name, "empty"]["cells"], [0] * len(DECLARED[name]))
                narrow = fits["pendingList", "narrowest"]
                whole = [max(parts) for parts in zip(narrow["heading"], narrow["cells"], narrow["least"])]
                self.assertGreater(narrow["heading"][0] + sum(whole[1:]), narrow["client"])

    # ---------------------------------------------------------------- nothing to list

    def test_nothing_to_list_is_a_line_over_the_card_and_the_list_keeps_its_headings(self):
        """'Nothing is waiting', 'No recoveries yet' and 'This cannot be read right now' are a line of the quieter ink
        on the page over the list's card, where they were before the tiles; the list under them shows its headings,
        closed by their hairline, over the bare card - nothing in it."""
        texts = {"empty:pendingEmpty": self.catalog["pending.empty"], "empty:historyEmpty": self.catalog["history.empty"],
                 "unreadable:pendingEmpty": self.catalog["pending.unavailable"],
                 "unreadable:historyEmpty": self.catalog["pending.unavailable"]}
        for scale, theme, drawn in self.each():
            with self.at(scale, theme):
                for key, text in texts.items():
                    found = drawn[key]
                    with self.subTest(key):
                        self.assertEqual(found["text"], text)
                        self.assertEqual((found["type"], found["parent"], found["dock"]),
                                         ("GroundLabel", "SoftPage", "Top"))
                        self.assertTrue(found["visible"])
                        self.assertFalse(found["inList"])
                        self.assertEqual(found["ink"], drawn["secondary"])
                        x, y, w, h = found["bounds"]
                        cx, cy, cw, ch = found["card"]
                        self.assertEqual(x, cx, "over the card, from its left edge")
                        self.assertEqual(y + h, cy, "right over the card")
                        self.assertEqual((found["rows"], found["children"]), (0, 0), "an empty list, nothing in it")
                        middle, headings = found["middle"], found["headings"]
                        self.assertGreater(headings, 0)
                        self.band(middle, headings - self.hairline, headings, drawn["line"], "the headings' hairline")
                        self.band(middle, headings, len(middle), drawn["card"], "the bare card under the headings")

    # ---------------------------------------------------------------- the choice cards

    def test_a_resting_choice_card_is_the_panels_segment(self):
        """Message style is the one setting with a twin on another surface: the panel's .segment, raised on brand's
        control lift with no top light, as every button is. Resting, a choice card has no top light in dark; chosen, it
        is a well."""
        for scale in SCALES:
            drawn = self.answer["scales"]["%.1f" % scale]
            hairline = drawn["hairline"]
            with self.subTest(scale=scale):
                resting, chosen = drawn["dark"]["choice"]["False"], drawn["dark"]["choice"]["True"]
                raised = brand.rgb(brand.DARK["raised"])
                self.assertTrue(near(resting[hairline], raised, 0),
                                "%s: no top light inside the hairline" % (channels(resting[hairline]),))
                self.assertFalse(near(resting[hairline], card_top_light(), 1), "not a tile's top light")
                self.assertTrue(near(resting[len(resting) // 2], raised, 0))
                self.assertLessEqual(luminance(chosen[hairline]), luminance(chosen[len(chosen) // 2]),
                                     "chosen, a well: no light")
                resting = drawn["light"]["choice"]["False"]
                self.assertTrue(near(resting[hairline], brand.rgb(brand.LIGHT["raised"]), 0), "light has no top light")


class RowSourceTests(unittest.TestCase):
    """The same held in the source, so it fails without a compiler too."""

    @classmethod
    def setUpClass(cls):
        cls.sources = {name: (GUI / name).read_text(encoding="utf-8")
                       for name in ("Controls.cs", "Dashboard.cs", "SettingsApp.cs")}
        cls.dashboard = cls.sources["Dashboard.cs"]

    def method(self, source, signature):
        start = source.index(signature)
        return source[start:source.index("\n        }\n", start)]

    def test_nothing_of_the_window_tiles_is_left(self):
        """The tiles' code went with them: nothing else used it."""
        for name, source in self.sources.items():
            for piece in ("Soft.Tile(", "TileLift", "TileLight", "TileRows(", "RowTile(", "DrawTile(", "TileBefore(",
                          "TileAfter(", "EmptyWell", "ShowWhenEmpty", "RowTileBelow"):
                with self.subTest(name, piece=piece):
                    self.assertNotIn(piece, source)
            with self.subTest(name):
                self.assertIsNone(re.search(r"static void Tile\(", source))

    def test_a_row_is_drawn_flat_with_its_hairline(self):
        # v0.6.9 draws it with a kept brush (Soft.Fill) rather than one made for every cell; the hairline
        # itself - full width, at the row's bottom, in Line - is what this holds.
        hairline = ("e.Graphics.FillRectangle(Soft.Fill(Line), e.Bounds.Left, e.Bounds.Bottom - Soft.Hairline, "
                    "e.Bounds.Width, Soft.Hairline);")
        cell = self.method(self.dashboard, "private void DrawCell(")
        self.assertIn("Color back = !selected ? Card : Palette.Contrast ? Palette.AccentSoft : Palette.Inset;", cell)
        self.assertIn(hairline, cell, "a full hairline under every row")
        self.assertNotIn("StampOuter", cell, "no lift under a row")
        header = self.method(self.dashboard, "private void DrawHeader(")
        self.assertIn(hairline, header, "and under the headings")
        self.assertNotIn("StampOuter", header)
        self.assertNotIn("TextFormatFlags.Right", header, "every heading left-aligned, Auto-resume's too")
        self.assertIn("var track = new Rectangle(cell.X + Px(2),", self.method(self.dashboard, "private void DrawResumeBox("),
                      "the switch where its column puts it")
        self.assertIn("list.SmallImageList.ImageSize = new Size(1, Math.Max(16, Math.Min(255, Px(34))));", self.dashboard)

    def test_nothing_to_list_is_a_line_over_the_card(self):
        for build, name, key in (("private Control BuildPending(", "pendingEmpty", "pending.empty"),
                                 ("private Control BuildHistory(", "historyEmpty", "history.empty")):
            with self.subTest(name):
                body = self.method(self.dashboard, build)
                self.assertIn('%s = GroundText(S("%s"' % (name, key), body)
                self.assertIn("%s.Dock = DockStyle.Top;" % name, body)
                self.assertIn("page.Controls.Add(%s);" % name, body)
        self.assertIn("private Control ListCard(ListView list)\n", self.dashboard)


if __name__ == "__main__":
    unittest.main()
