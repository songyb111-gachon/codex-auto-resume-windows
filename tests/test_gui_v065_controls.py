r"""The v0.6.5 controls: the drop-down's own list, the switch that glides, and a list's bar across its bottom.

The real compiled window is loaded and its controls are made in a window of the probe's own, placed far off
the screen and shown without taking activation - nothing is sent to any window but that one and the list it
opens. Keys, clicks and the wheel are the messages Windows sends for them, sent straight to those windows; a
screen reader's view is read the way one reads it, through the accessibility events the window raises and
the objects Windows hands back for them.

  * The drop-down's list is its own (requirement 14): a raised card in the cards' material, never Windows'
    list, opening under the drop-down or above it where there is no room, and doing everything Windows' list
    did - the keys, typing to find, the wheel, closing on a click elsewhere or when the window is left - with
    the focus on the drop-down throughout and a screen reader hearing the list and the item the keyboard is on.
  * A switch glides and a check box fades (requirement 15): brand's one transition on one curve, paint only,
    no timer left running, and immediate when motion is reduced.
  * A list whose columns are wider than it is scrolls sideways on the soft bar, with Windows' own horizontal
    bar hidden the way the vertical one is (requirement 12).
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

from codex_auto_resume import brand

ROOT = Path(__file__).resolve().parents[1]
CSC = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe"
POWERSHELL = (Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
              / "WindowsPowerShell" / "v1.0" / "powershell.exe")

ITEMS = ["System (English)", "English", "Deutsch", "Espanol", "Francais", "Italiano", "Japanese", "Korean",
         "Portugues (Brasil)", "Chinese (Simplified)"]

PROBE = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName Accessibility
Add-Type -ReferencedAssemblies System.Windows.Forms, System.Drawing, Accessibility -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Windows.Forms;
using Accessibility;
public class QuietForm : Form {
    protected override bool ShowWithoutActivation { get { return true; } }
    protected override CreateParams CreateParams { get { CreateParams cp = base.CreateParams; cp.ExStyle |= 0x08000000 | 0x80; return cp; } }
}
public static class Probe {
    [DllImport("user32.dll")] public static extern IntPtr SendMessage(IntPtr window, int message, IntPtr wParam, IntPtr lParam);
    [DllImport("user32.dll")] public static extern int GetWindowLong(IntPtr window, int index);
    [DllImport("user32.dll")] public static extern IntPtr GetWindow(IntPtr window, int command);
    [DllImport("user32.dll")] public static extern IntPtr GetFocus();
    [DllImport("user32.dll")] public static extern IntPtr GetActiveWindow();
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr window);
    [StructLayout(LayoutKind.Sequential)] public struct Rect { public int Left, Top, Right, Bottom; }
    [StructLayout(LayoutKind.Sequential)] public struct ComboInfo { public int Size; public Rect Item, Button; public int State; public IntPtr Combo, Edit, List; }
    [DllImport("user32.dll")] public static extern bool GetComboBoxInfo(IntPtr window, ref ComboInfo info);
    public static IntPtr NativeList(IntPtr combo) {
        var info = new ComboInfo(); info.Size = Marshal.SizeOf(typeof(ComboInfo));
        return GetComboBoxInfo(combo, ref info) ? info.List : IntPtr.Zero;
    }
    public static IntPtr Key(IntPtr window, int message, int key, bool alt) {
        return SendMessage(window, message, new IntPtr(key), new IntPtr(alt ? 0x20000001 : 1));
    }
    public static IntPtr Wheel(IntPtr window, int delta) {
        return SendMessage(window, 0x020A, new IntPtr((delta & 0xFFFF) << 16), IntPtr.Zero);
    }
    public static IntPtr At(int x, int y) { return new IntPtr((y << 16) | (x & 0xFFFF)); }

    public delegate void EventProc(IntPtr hook, uint e, IntPtr window, int obj, int child, uint thread, uint time);
    [DllImport("user32.dll")] static extern IntPtr SetWinEventHook(uint min, uint max, IntPtr module, EventProc proc, uint process, uint thread, uint flags);
    [DllImport("user32.dll")] static extern bool UnhookWinEvent(IntPtr hook);
    [DllImport("oleacc.dll")] static extern int AccessibleObjectFromEvent(IntPtr window, int obj, int child, [MarshalAs(UnmanagedType.Interface)] out IAccessible accessible, out object childId);
    [DllImport("oleacc.dll")] static extern int AccessibleObjectFromWindow(IntPtr window, int obj, ref Guid iid, [MarshalAs(UnmanagedType.Interface)] out object accessible);
    static EventProc keep;
    static IntPtr hook, watched;
    public static List<string> Seen = new List<string>();
    public static void Listen(IntPtr window) {
        watched = window; Seen.Clear(); keep = OnEvent;
        hook = SetWinEventHook(0x8002, 0x800E, IntPtr.Zero, keep, (uint)System.Diagnostics.Process.GetCurrentProcess().Id, 0, 0);
    }
    public static void Stop() { if (hook != IntPtr.Zero) UnhookWinEvent(hook); hook = IntPtr.Zero; }
    static void OnEvent(IntPtr h, uint e, IntPtr window, int obj, int child, uint thread, uint time) {
        if (window != watched) return;
        string name = "", role = "", state = "";
        try {
            IAccessible accessible; object id;
            if (AccessibleObjectFromEvent(window, obj, child, out accessible, out id) == 0 && accessible != null) {
                name = accessible.get_accName(id) ?? "";
                role = Convert.ToString(accessible.get_accRole(id));
                state = Convert.ToString(accessible.get_accState(id));
            }
        } catch (Exception ex) { name = "!" + ex.GetType().Name; }
        Seen.Add(e.ToString("X") + "|" + obj + "|" + child + "|" + name + "|" + role + "|" + state);
    }
    public static string[] Client(IntPtr window) {
        var iid = new Guid(0x618736e0, 0x3c3d, 0x11cf, 0x81, 0x0c, 0x00, 0xaa, 0x00, 0x38, 0x9b, 0x71); object found;
        if (AccessibleObjectFromWindow(window, -4, ref iid, out found) != 0 || found == null) return new string[0];
        var accessible = (IAccessible)found;
        var result = new List<string>();
        result.Add(accessible.get_accName(0) ?? "");
        result.Add(Convert.ToString(accessible.get_accRole(0)));
        result.Add(Convert.ToString(accessible.accChildCount));
        return result.ToArray();
    }
}
// An answer for the window's input from Windows' animation switch (Soft.WindowsAnimates), compiled, so it holds on
// any thread.
public static class Said {
    public static bool Yes() { return true; }
    public static bool No() { return false; }
    public static Func<bool> Answer(bool yes) { return yes ? new Func<bool>(Yes) : new Func<bool>(No); }
}
'@
$assembly = [Reflection.Assembly]::LoadFile($env:CAR_EXE)
$static = [Reflection.BindingFlags]'Static,NonPublic,Public'
$instance = [Reflection.BindingFlags]'Instance,NonPublic,Public'
$t = @{}
foreach ($n in 'Palette','SettingsForm','Soft','Motion','SoftCombo','SoftDropList','SoftCheck','SoftList','SoftListHost','ISoftScroller') { $t[$n] = $assembly.GetType('CodexAutoResume.' + $n, $true) }
function P($target, [string]$name) { return $target.GetType().GetProperty($name, $instance).GetValue($target, $null) }
function F($target, [string]$name) { return $target.GetType().GetField($name, $instance).GetValue($target) }
function Call($target, [string]$name, [object[]]$arguments) {
    $m = @($target.GetType().GetMethods($instance) | Where-Object { $_.Name -eq $name -and $_.GetParameters().Count -eq $arguments.Count })[0]
    return $m.Invoke($target, $arguments)
}
function S([string]$type, [string]$name, [object[]]$arguments) {
    $m = @($t[$type].GetMethods($static) | Where-Object { $_.Name -eq $name -and $_.GetParameters().Count -eq $arguments.Count })[0]
    return $m.Invoke($null, $arguments)
}
function Pump([int]$ms) { $sw = [Diagnostics.Stopwatch]::StartNew(); do { [Windows.Forms.Application]::DoEvents(); Start-Sleep -Milliseconds 3 } while ($sw.ElapsedMilliseconds -lt $ms) }
function Box($r) { return ,@([int]$r.X, [int]$r.Y, [int]$r.Width, [int]$r.Height) }
$reduce = $t.Soft.GetField('ReduceMotionSetting', $static)
$areaField = $t.SoftDropList.GetField('Area', $static)
$adopt = $t.Palette.GetMethod('Adopt', $static)
# Windows' two inputs to motion are the probe's own answers, not this machine's: the light theme (High Contrast holds
# everything still) and the animation switch on - off only where that is what is tested, as GitHub's runner has it.
$null = $adopt.Invoke($null, [object[]]@('light'))
$animates = $t.Soft.GetField('WindowsAnimates', $static)
$animates.SetValue($null, [Said]::Answer($true))
$out = @{}
$out.scale = [double]$t.SettingsForm.GetProperty('DpiScale', $static).GetValue($null)
$out.duration = [int]$t.Motion.GetProperty('Duration', $static).GetValue($null)
$out.reducedHere = [bool]$t.Soft.GetProperty('ReduceMotion', $static).GetValue($null)
$out.lines = [int][Windows.Forms.SystemInformation]::MouseWheelScrollLines

# ------------------------------------------------------------------ the arithmetic
$out.ease = @()
foreach ($x in (ConvertFrom-Json $env:CAR_EASE)) { $out.ease += [double](S 'Motion' 'Ease' @([double]$x)) }
$out.place = @()
foreach ($case in (ConvertFrom-Json $env:CAR_PLACE)) {
    $field = New-Object Drawing.Rectangle $case[0][0], $case[0][1], $case[0][2], $case[0][3]
    $area = New-Object Drawing.Rectangle $case[1][0], $case[1][1], $case[1][2], $case[1][3]
    $call = [object[]]@($field, [int]$case[2], [int]$case[3], [int]$case[4], [int]$case[5], [int]$case[6], $area, [int]$case[7], $false, 0)
    $m = $t.SoftDropList.GetMethod('Place', $static)
    $rect = $m.Invoke($null, $call)
    $out.place += ,@((Box $rect), [bool]$call[8], [int]$call[9])
}
$out.find = @()
foreach ($case in (ConvertFrom-Json $env:CAR_FIND)) {
    $out.find += [int](S 'SoftCombo' 'Find' @([string[]]$case[0], [string]$case[1], [int]$case[2]))
}

# ------------------------------------------------------------------ a window of the probe's own, off the screen
$origin = New-Object Drawing.Point -30000, -30000
$areaField.SetValue($null, (New-Object Drawing.Rectangle ($origin.X - 3000), ($origin.Y - 3000), 8000, 8000))
$null = $adopt.Invoke($null, [object[]]@('light'))
function New-Window {
    $form = New-Object QuietForm
    $form.FormBorderStyle = 'None'
    $form.ShowInTaskbar = $false
    $form.StartPosition = 'Manual'
    $form.Location = $origin
    $form.Size = New-Object Drawing.Size 600, 400
    $form.BackColor = $t.Palette.GetField('Canvas', $static).GetValue($null)
    return $form
}
$form = New-Window
$combo = [Activator]::CreateInstance($t.SoftCombo, $true)
$combo.Width = 240
$combo.Location = New-Object Drawing.Point 40, 40
$combo.AccessibleName = 'Continuation language'
foreach ($item in (ConvertFrom-Json $env:CAR_ITEMS)) { $null = $combo.Items.Add([string]$item) }
$combo.SelectedIndex = 2
$other = New-Object Windows.Forms.Button
$other.Text = 'elsewhere'
$other.Location = New-Object Drawing.Point 400, 40
$form.Controls.Add($combo)
$form.Controls.Add($other)
$script:changed = 0
$script:committed = 0
$script:wheeled = 0
$combo.add_SelectedIndexChanged({ $script:changed++ })
$combo.add_SelectionChangeCommitted({ $script:committed++ })
$combo.add_MouseWheel({ $script:wheeled++ })
$form.Show()
Pump 50
$h = $combo.Handle
$nativeList = [Probe]::NativeList($h)
$out.nativeListFound = $nativeList -ne [IntPtr]::Zero
function State {
    $drop = P $combo 'DropList'
    return @{ open = [bool](P $combo 'Open'); dropped = [bool]$combo.DroppedDown; highlight = [int](P $combo 'Highlight')
              selected = [int]$combo.SelectedIndex; cues = [bool](P $combo 'KeyboardCues'); changed = $script:changed
              committed = $script:committed; native = [bool]([Probe]::IsWindowVisible($nativeList))
              offset = $(if ($drop) { [int](P $drop 'Offset') } else { -1 }) }
}
$WM_KEYDOWN = 0x0100; $WM_SYSKEYDOWN = 0x0104; $WM_CHAR = 0x0102
$reduce.SetValue($null, $true)

# Every way Windows' own list could open opens this one, and Windows' list stays hidden.
$out.opening = @{}
$null = [Probe]::SendMessage($h, 0x014F, [IntPtr]1, [IntPtr]::Zero); $out.opening.show = State
$null = [Probe]::SendMessage($h, 0x014F, [IntPtr]::Zero, [IntPtr]::Zero); $out.opening.hide = State
$null = [Probe]::Key($h, $WM_KEYDOWN, 0x73, $false); $out.opening.f4 = State
$null = [Probe]::Key($h, $WM_KEYDOWN, 0x1B, $false); $out.opening.escape = State
$null = [Probe]::Key($h, $WM_SYSKEYDOWN, 0x28, $true); $out.opening.altDown = State
$null = [Probe]::Key($h, $WM_SYSKEYDOWN, 0x26, $true); $out.opening.altUp = State
$null = [Probe]::SendMessage($h, 0x0201, [IntPtr]1, [Probe]::At(10, 10)); $out.opening.click = State
$null = [Probe]::SendMessage($h, 0x0202, [IntPtr]::Zero, [Probe]::At(10, 10))
$null = [Probe]::SendMessage($h, 0x0201, [IntPtr]1, [Probe]::At(10, 10)); $out.opening.clickAgain = State
$null = [Probe]::SendMessage($h, 0x0202, [IntPtr]::Zero, [Probe]::At(10, 10))
$null = [Probe]::Key($h, $WM_KEYDOWN, 0x20, $false); $out.opening.space = State
$null = [Probe]::SendMessage($h, $WM_CHAR, [IntPtr]0x20, [IntPtr]1); $out.opening.spaceChar = State
$null = [Probe]::Key($h, $WM_KEYDOWN, 0x1B, $false)
$combo.DroppedDown = $true; $out.opening.property = State
$combo.DroppedDown = $false; $out.opening.propertyOff = State

# The keys, while it is open.
$out.keys = @()
$null = [Probe]::Key($h, $WM_KEYDOWN, 0x73, $false)
foreach ($key in @(0x28, 0x28, 0x26, 0x24, 0x23, 0x21, 0x22, 0x26, 0x25, 0x27)) {
    $null = [Probe]::Key($h, $WM_KEYDOWN, $key, $false)
    $out.keys += ,@($key, (State))
}
$drop = P $combo 'DropList'
$out.rows = [int](P $drop 'Rows')
$null = [Probe]::Key($h, $WM_KEYDOWN, 0x28, $false)
$null = [Probe]::Key($h, $WM_KEYDOWN, 0x0D, $false); $out.enter = State
$null = [Probe]::SendMessage($h, $WM_CHAR, [IntPtr]0x0D, [IntPtr]1); $out.enterChar = State
$null = [Probe]::Key($h, $WM_KEYDOWN, 0x73, $false)
$null = [Probe]::Key($h, $WM_KEYDOWN, 0x28, $false)
$null = [Probe]::Key($h, $WM_KEYDOWN, 0x1B, $false); $out.escape = State
$null = [Probe]::Key($h, $WM_KEYDOWN, 0x73, $false)
$null = [Probe]::Key($h, $WM_KEYDOWN, 0x26, $false)
$null = [Probe]::Key($h, $WM_SYSKEYDOWN, 0x26, $true); $out.altUpTakes = State
$null = [Probe]::Key($h, $WM_KEYDOWN, 0x73, $false)
$null = [Probe]::Key($h, $WM_KEYDOWN, 0x28, $false)
# Nothing to move on to: Tab takes the item, and the focus stays in this window.
$combo.TabStop = $false
$other.TabStop = $false
$tab = $combo.GetType().GetMethod('ProcessDialogKey', $instance)
$null = $tab.Invoke($combo, [object[]]@([Windows.Forms.Keys]::Tab)); $out.tabTakes = State
$input = $combo.GetType().GetMethod('IsInputKey', $instance)
$out.inputClosed = @([bool]$input.Invoke($combo, [object[]]@([Windows.Forms.Keys]::Escape)), [bool]$input.Invoke($combo, [object[]]@([Windows.Forms.Keys]::Return)))
$null = [Probe]::Key($h, $WM_KEYDOWN, 0x73, $false)
$out.inputOpen = @()
foreach ($k in @('Escape', 'Return', 'Up', 'Down', 'Home', 'End', 'PageUp', 'PageDown', 'Space')) { $out.inputOpen += [bool]$input.Invoke($combo, [object[]]@([Windows.Forms.Keys]$k)) }
$null = [Probe]::Key($h, $WM_KEYDOWN, 0x1B, $false)

# Typing finds.
$combo.SelectedIndex = 2
$null = [Probe]::Key($h, $WM_KEYDOWN, 0x73, $false)
$out.typed = @()
foreach ($c in @('e', 'e', 'x')) { $null = [Probe]::SendMessage($h, $WM_CHAR, [IntPtr][int][char]$c, [IntPtr]1); $out.typed += [int](P $combo 'Highlight') }
Start-Sleep -Milliseconds 1150
foreach ($c in @('p', 'o', 'r', 't', ' ')) {
    if ($c -eq ' ') { $null = [Probe]::Key($h, $WM_KEYDOWN, 0x20, $false) }
    $null = [Probe]::SendMessage($h, $WM_CHAR, [IntPtr][int][char]$c, [IntPtr]1)
    $out.typed += [int](P $combo 'Highlight')
}
$out.typedOpen = [bool](P $combo 'Open')
$null = [Probe]::Key($h, $WM_KEYDOWN, 0x1B, $false)

# Where it opens: under the drop-down, its items' words under the drop-down's own.
$null = [Probe]::Key($h, $WM_KEYDOWN, 0x73, $false)
$drop = P $combo 'DropList'
$field = $combo.RectangleToScreen($combo.ClientRectangle)
$out.where = @{ field = (Box $field); card = (Box (P $drop 'Card')); above = [bool](P $drop 'Above'); margin = @((P $drop 'Margin').Left, (P $drop 'Margin').Top, (P $drop 'Margin').Right, (P $drop 'Margin').Bottom)
                rows = [int](P $drop 'Rows'); scrolls = [bool](P $drop 'Scrolls'); pill = (Box (Call $drop 'PillRect' @([int]0))); pitch = [int](P $drop 'Pitch') }
$popup = $drop.Handle
$out.window = @{ exStyle = [int]([Probe]::GetWindowLong($popup, -20)); style = [int]([Probe]::GetWindowLong($popup, -16))
                 owner = ([Probe]::GetWindow($popup, 4) -eq $form.Handle); visible = [bool]([Probe]::IsWindowVisible($popup))
                 activate = [int]([Probe]::SendMessage($popup, 0x0021, $form.Handle, [IntPtr]::Zero)) }
$image = P $drop 'Image'
$out.window.image = @($image.Width, $image.Height)
# A press on the list's shadow goes through it; on the card it is the list's.
$card = P $drop 'Card'
$margin = P $drop 'Margin'
$out.window.hitCard = [int]([Probe]::SendMessage($popup, 0x0084, [IntPtr]::Zero, [Probe]::At(($card.X + 20), ($card.Y + 20))))
$out.window.hitShadow = [int]([Probe]::SendMessage($popup, 0x0084, [IntPtr]::Zero, [Probe]::At(($card.X + 20), ($card.Bottom + 3))))
# Its pixels: the card, a shadow that fades, the chosen item sunken, the keyboard's item ringed.
function Pixel($x, $y) { return $image.GetPixel($x, $y).ToArgb() }
$pill = Call $drop 'PillRect' @([int]2)
$out.pixels = @{ card = (Pixel ($margin.Left + [int]($card.Width / 2)) ($margin.Top + 3))
                 below = @((Pixel ($margin.Left + [int]($card.Width / 2)) ($margin.Top + $card.Height + 2)), (Pixel ($margin.Left + [int]($card.Width / 2)) ($margin.Top + $card.Height + [int]($margin.Bottom / 2))))
                 chosen = (Pixel ($margin.Left + $pill.Right - 20) ($margin.Top + $pill.Y + [int]($pill.Height / 2)))
                 ring = (Pixel ($margin.Left + $pill.X - 3) ($margin.Top + $pill.Y + [int]($pill.Height / 2)))
                 corner = (Pixel $margin.Left $margin.Top) }
$out.colours = @{ card = $t.Palette.GetField('Card', $static).GetValue($null).ToArgb(); inset = $t.Palette.GetField('Inset', $static).GetValue($null).ToArgb()
                  focus = $t.Palette.GetField('Focus', $static).GetValue($null).ToArgb(); raised = $t.Palette.GetField('Raised', $static).GetValue($null).ToArgb() }

# The focus stays where it was: nothing activates, and a click on an item takes it. Opened with the pointer,
# the item under it rises.
$null = [Probe]::Key($h, $WM_KEYDOWN, 0x1B, $false)
$null = [Probe]::SendMessage($h, 0x0201, [IntPtr]1, [Probe]::At(10, 10))
$null = [Probe]::SendMessage($h, 0x0202, [IntPtr]::Zero, [Probe]::At(10, 10))
$drop = P $combo 'DropList'
$popup = $drop.Handle
$margin = P $drop 'Margin'
$focusBefore = [Probe]::GetFocus()
$activeBefore = [Probe]::GetActiveWindow()
$item = Call $drop 'PillRect' @([int]5)
$x = $margin.Left + $item.X + 10
$y = $margin.Top + $item.Y + [int]($item.Height / 2)
$null = [Probe]::SendMessage($popup, 0x0200, [IntPtr]::Zero, [Probe]::At($x, $y))
$out.hover = [int](P $drop 'Hover')
$hovered = P $drop 'Image'
$out.hoverFill = $hovered.GetPixel($margin.Left + $item.X + 4, $margin.Top + $item.Y + [int]($item.Height / 2)).ToArgb()
$null = [Probe]::SendMessage($popup, 0x0201, [IntPtr]1, [Probe]::At($x, $y))
$null = [Probe]::SendMessage($popup, 0x0202, [IntPtr]::Zero, [Probe]::At($x, $y))
$out.click = State
$out.focus = @(([Probe]::GetFocus() -eq $focusBefore), ([Probe]::GetActiveWindow() -eq $activeBefore))

# What closes it: a press elsewhere (which goes no further), a press on a title bar (which does), the window
# losing activation or moving, and the drop-down hiding. A press on the list is the list's.
function Offer([IntPtr]$window, [int]$message) {
    $filter = F $combo 'filter'
    $m = [Windows.Forms.Message]::Create($window, $message, [IntPtr]1, [IntPtr]::Zero)
    $call = [object[]]@($m)
    $eaten = [bool]$filter.GetType().GetMethod('PreFilterMessage').Invoke($filter, $call)
    return @($eaten, [bool](P $combo 'Open'))
}
$out.closing = @{}
$null = [Probe]::Key($h, $WM_KEYDOWN, 0x73, $false)
$out.closing.onList = Offer (P $combo 'DropList').Handle 0x0201
$out.closing.elsewhere = Offer $other.Handle 0x0201
$null = [Probe]::Key($h, $WM_KEYDOWN, 0x73, $false)
$out.closing.titleBar = Offer $form.Handle 0x00A1
$null = [Probe]::Key($h, $WM_KEYDOWN, 0x73, $false)
$null = $form.GetType().GetMethod('OnDeactivate', $instance).Invoke($form, [object[]]@([EventArgs]::Empty))
$out.closing.deactivated = [bool](P $combo 'Open')
$null = [Probe]::Key($h, $WM_KEYDOWN, 0x73, $false)
$form.Location = New-Object Drawing.Point ($origin.X + 5), $origin.Y
$out.closing.moved = [bool](P $combo 'Open')
$form.Location = $origin
$null = [Probe]::Key($h, $WM_KEYDOWN, 0x73, $false)
$combo.Visible = $false
$out.closing.hidden = [bool](P $combo 'Open')
$combo.Visible = $true
$out.closing.selected = [int]$combo.SelectedIndex

# The wheel: over a closed drop-down it goes to whoever handles it, as before; while the list is open it
# scrolls the list and nothing else, wherever the pointer is.
$long = [Activator]::CreateInstance($t.SoftCombo, $true)
$long.Width = 200
$long.Location = New-Object Drawing.Point 40, 120
for ($i = 1; $i -le 30; $i++) { $null = $long.Items.Add('Item ' + $i) }
$long.SelectedIndex = 0
$script:longWheel = 0
$long.add_MouseWheel({ param($sender, $e) $script:longWheel++; $e.Handled = $true })
$form.Controls.Add($long)
Pump 20
$lh = $long.Handle
$null = [Probe]::Wheel($lh, -120)
$out.wheelClosed = @($script:longWheel, [int]$long.SelectedIndex)
$null = [Probe]::Key($lh, $WM_KEYDOWN, 0x73, $false)
$ld = P $long 'DropList'
$out.longList = @{ rows = [int](P $ld 'Rows'); scrolls = [bool](P $ld 'Scrolls'); max = [int]$long.MaxDropDownItems; pitch = [int](P $ld 'Pitch') }
$null = [Probe]::Wheel($lh, -120)
$out.wheelOpen = @($script:longWheel, [int]$long.SelectedIndex, [int](P $ld 'Offset'))
$m = [Windows.Forms.Message]::Create($form.Handle, 0x020A, [IntPtr](-120 -shl 16), [IntPtr]::Zero)
$filter = F $long 'filter'
$eaten = [bool]$filter.GetType().GetMethod('PreFilterMessage').Invoke($filter, [object[]]@($m))
$out.wheelElsewhere = @($eaten, [int](P $ld 'Offset'))
$null = [Probe]::Key($lh, $WM_KEYDOWN, 0x23, $false)
$out.endShown = @([int](P $long 'Highlight'), [int](P $ld 'Offset'), [bool](Call $ld 'Shows' @([int]29)))
$null = [Probe]::Key($lh, $WM_KEYDOWN, 0x1B, $false)

# Near the screen's bottom edge it opens above, with the same gap; with no room either side it shows the rows that fit.
$field = $combo.RectangleToScreen($combo.ClientRectangle)
$areaField.SetValue($null, (New-Object Drawing.Rectangle ($origin.X - 3000), ($origin.Y - 3000), 8000, ($field.Bottom + 50 - ($origin.Y - 3000))))
$null = [Probe]::Key($h, $WM_KEYDOWN, 0x73, $false)
$drop = P $combo 'DropList'
$out.bottom = @{ field = (Box $field); card = (Box (P $drop 'Card')); above = [bool](P $drop 'Above'); rows = [int](P $drop 'Rows') }
$null = [Probe]::Key($h, $WM_KEYDOWN, 0x1B, $false)
$areaField.SetValue($null, (New-Object Drawing.Rectangle ($origin.X - 3000), ($field.Top - 150), 8000, ($field.Height + 300)))
$null = [Probe]::Key($h, $WM_KEYDOWN, 0x73, $false)
$drop = P $combo 'DropList'
$out.cramped = @{ card = (Box (P $drop 'Card')); above = [bool](P $drop 'Above'); rows = [int](P $drop 'Rows'); scrolls = [bool](P $drop 'Scrolls') }
$null = [Probe]::Key($h, $WM_KEYDOWN, 0x1B, $false)
$areaField.SetValue($null, (New-Object Drawing.Rectangle ($origin.X - 3000), ($origin.Y - 3000), 8000, 8000))

# What a screen reader hears: the drop-down, its list and its items, and the events as the highlight moves.
$null = $combo.Focus()
$out.focusedForA11y = [bool]$combo.Focused
$acc = $combo.AccessibilityObject
$list = $acc.GetChild(0)
$out.a11y = @{ role = [string]$acc.Role; closedState = [int]$acc.State; children = [int]$acc.GetChildCount(); listRole = [string]$list.Role
               listName = [string]$list.Name; items = [int]$list.GetChildCount(); itemRole = [string]$list.GetChild(3).Role
               itemName = [string]$list.GetChild(3).Name; closedItem = [int]$list.GetChild(3).State; listClosed = [int]$list.State }
[Probe]::Listen($h)
$null = [Probe]::Key($h, $WM_KEYDOWN, 0x73, $false)
Pump 30
$null = [Probe]::Key($h, $WM_KEYDOWN, 0x28, $false)
Pump 30
$out.a11y.openState = [int]$acc.State
$out.a11y.focusedItem = [int]$list.GetChild([int](P $combo 'Highlight')).State
$out.a11y.otherItem = [int]$list.GetChild(0).State
$out.a11y.highlight = [int](P $combo 'Highlight')
$out.a11y.focused = [string]$list.GetFocused().Name
$out.a11y.bounds = (Box $list.GetChild([int](P $combo 'Highlight')).Bounds)
$out.a11y.listBounds = (Box $list.Bounds)
$out.a11y.popupClient = @([Probe]::Client((P $combo 'DropList').Handle))
$null = [Probe]::Key($h, $WM_KEYDOWN, 0x1B, $false)
Pump 30
[Probe]::Stop()
$out.a11y.events = @([Probe]::Seen)
$out.a11y.closedAgain = [int]$acc.State
$out.a11y.listId = [int]$t.SoftCombo.GetField('ListObjectId', $static).GetValue($null)

# Opening with motion: it fades in and rises into place, and its timer stops; with motion reduced it is there.
$reduce.SetValue($null, $false)
$out.motionAllowed = -not [bool]$t.Soft.GetProperty('ReduceMotion', $static).GetValue($null)
$null = [Probe]::Key($h, $WM_KEYDOWN, 0x73, $false)
$drop = P $combo 'DropList'
$out.appear = @{ first = @([int](P $drop 'Alpha'), [bool](P $drop 'Appearing'), ((P $drop 'CardOnScreen').Y - (P $drop 'Card').Y)) }
Pump 400
$out.appear.last = @([int](P $drop 'Alpha'), [bool](P $drop 'Appearing'), ((P $drop 'CardOnScreen').Y - (P $drop 'Card').Y))
$null = [Probe]::Key($h, $WM_KEYDOWN, 0x1B, $false)
$reduce.SetValue($null, $true)
$null = [Probe]::Key($h, $WM_KEYDOWN, 0x73, $false)
$drop = P $combo 'DropList'
$out.appear.reduced = @([int](P $drop 'Alpha'), [bool](P $drop 'Appearing'), ((P $drop 'CardOnScreen').Y - (P $drop 'Card').Y))
$null = [Probe]::Key($h, $WM_KEYDOWN, 0x1B, $false)
# Windows' "Animation effects" off, the product's own setting not: simply there too.
$reduce.SetValue($null, $false)
$animates.SetValue($null, [Said]::Answer($false))
$null = [Probe]::Key($h, $WM_KEYDOWN, 0x73, $false)
$drop = P $combo 'DropList'
$out.appear.windows = @([int](P $drop 'Alpha'), [bool](P $drop 'Appearing'), ((P $drop 'CardOnScreen').Y - (P $drop 'Card').Y))
$null = [Probe]::Key($h, $WM_KEYDOWN, 0x1B, $false)
$animates.SetValue($null, [Said]::Answer($true))
$reduce.SetValue($null, $true)

# High Contrast: no shadow, so no room for one; system colours; the chosen item is Highlight.
$form.Close(); $form.Dispose()
foreach ($theme in @('dark', 'contrast')) {
    $null = $adopt.Invoke($null, [object[]]@([string]$theme))
    $form = New-Window
    $combo = [Activator]::CreateInstance($t.SoftCombo, $true)
    $combo.Width = 240
    $combo.Location = New-Object Drawing.Point 40, 40
    foreach ($item in (ConvertFrom-Json $env:CAR_ITEMS)) { $null = $combo.Items.Add([string]$item) }
    $combo.SelectedIndex = 2
    $form.Controls.Add($combo)
    $form.Show()
    Pump 30
    $null = [Probe]::Key($combo.Handle, $WM_KEYDOWN, 0x73, $false)
    $drop = P $combo 'DropList'
    $image = P $drop 'Image'
    $margin = P $drop 'Margin'
    $card = P $drop 'Card'
    $pill = Call $drop 'PillRect' @([int]2)
    $out[$theme] = @{ margin = @($margin.Left, $margin.Top, $margin.Right, $margin.Bottom); image = @($image.Width, $image.Height); card = (Box $card)
                      chosen = $image.GetPixel($margin.Left + $pill.Right - 20, $margin.Top + $pill.Y + [int]($pill.Height / 2)).ToArgb()
                      middle = $image.GetPixel($margin.Left + [int]($card.Width / 2), $margin.Top + 3).ToArgb()
                      highlight = [Drawing.SystemColors]::Highlight.ToArgb(); window = [Drawing.SystemColors]::Window.ToArgb()
                      cardColour = $t.Palette.GetField('Card', $static).GetValue($null).ToArgb(); inset = $t.Palette.GetField('Inset', $static).GetValue($null).ToArgb() }
    $null = [Probe]::Key($combo.Handle, $WM_KEYDOWN, 0x1B, $false)
    $form.Close(); $form.Dispose()
}
$null = $adopt.Invoke($null, [object[]]@('light'))

# ------------------------------------------------------------------ the switch and the check box
$switchAt = $t.Soft.GetMethod('SwitchAt', $static)
$switch = $t.Soft.GetMethod('Switch', $static)
$box = $t.SoftCheck.GetMethod('DrawBox', $static)
$boxAt = $t.SoftCheck.GetMethod('DrawBoxAt', $static)
function Draw([scriptblock]$paint) {
    $bitmap = New-Object Drawing.Bitmap 60, 40
    $g = [Drawing.Graphics]::FromImage($bitmap)
    $g.Clear($t.Palette.GetField('Card', $static).GetValue($null))
    & $paint $g
    $g.Dispose()
    $pixels = New-Object 'int[]' (60 * 40)
    for ($y = 0; $y -lt 40; $y++) { for ($x = 0; $x -lt 60; $x++) { $pixels[$y * 60 + $x] = $bitmap.GetPixel($x, $y).ToArgb() } }
    $bitmap.Dispose()
    return ,$pixels
}
$ground = $t.Palette.GetField('Card', $static).GetValue($null)
$track = New-Object Drawing.Rectangle 8, 9, 40, 22
$face = New-Object Drawing.Rectangle 20, 11, 18, 18
$out.rest = @{}
foreach ($on in @($false, $true)) {
    $v = if ($on) { 1.0 } else { 0.0 }
    $a = Draw { param($g) $null = $switch.Invoke($null, [object[]]@($g, $track, $on, $true, $ground)) }
    $b = Draw { param($g) $null = $switchAt.Invoke($null, [object[]]@($g, $track, [double]$v, $true, $ground)) }
    $c = Draw { param($g) $null = $box.Invoke($null, [object[]]@($g, $face, $on, $true)) }
    $d = Draw { param($g) $null = $boxAt.Invoke($null, [object[]]@($g, $face, [double]$v, $true)) }
    $same = [bool]((Compare-Object $a $b -SyncWindow 0).Count -eq 0)
    $sameBox = [bool]((Compare-Object $c $d -SyncWindow 0).Count -eq 0)
    $out.rest[[string]$on] = @($same, $sameBox)
}
$out.halfway = @()
foreach ($v in @(0.0, 0.25, 0.5, 0.75, 1.0)) {
    $p = Draw { param($g) $null = $switchAt.Invoke($null, [object[]]@($g, $track, [double]$v, $true, $ground)) }
    # The knob's middle row, and the track's colour between knob and edge on each side.
    $row = @(); for ($x = 0; $x -lt 60; $x++) { $row += $p[20 * 60 + $x] }
    $q = Draw { param($g) $null = $boxAt.Invoke($null, [object[]]@($g, $face, [double]$v, $true)) }
    # A pixel of the track above the knob's path, and one of the box away from its mark.
    $out.halfway += ,@($v, $row, $p[11 * 60 + 28], $q[25 * 60 + 25])
}
$out.onColours = @{ accent = $t.Palette.GetField('Accent', $static).GetValue($null).ToArgb(); inset = $t.Palette.GetField('Inset', $static).GetValue($null).ToArgb()
                    onAccent = $t.Palette.GetField('OnAccent', $static).GetValue($null).ToArgb(); muted = $t.Palette.GetField('Muted', $static).GetValue($null).ToArgb() }

# A real switch: immediate when motion is reduced or it is not on screen, gliding and then still when it is.
$form = New-Window
$check = [Activator]::CreateInstance($t.SoftCheck, $true)
$check.Text = 'Reduce motion'
$check.AutoSize = $true
$check.Location = New-Object Drawing.Point 40, 40
$unshown = [Activator]::CreateInstance($t.SoftCheck, $true)
$unshown.Checked = $true
$out.check = @{ unshown = @([double](P $unshown 'Progress'), [bool](P $unshown 'Moving')) }
$form.Controls.Add($check)
$form.Show()
Pump 30
$reduce.SetValue($null, $true)
$check.Checked = $true
$out.check.reduced = @([double](P $check 'Progress'), [bool](P $check 'Moving'))
$check.Checked = $false
$reduce.SetValue($null, $false)
# Windows' "Animation effects" off, the product's own setting not: at once too.
$animates.SetValue($null, [Said]::Answer($false))
$check.Checked = $true
$out.check.windows = @([double](P $check 'Progress'), [bool](P $check 'Moving'))
$check.Checked = $false
$animates.SetValue($null, [Said]::Answer($true))
$check.Checked = $true
$out.check.started = @([double](P $check 'Progress'), [bool](P $check 'Moving'))
Pump 60
$out.check.middle = @([double](P $check 'Progress'), [bool](P $check 'Moving'))
$check.Checked = $false
$out.check.reversed = @([double](P $check 'Progress'), [bool](P $check 'Moving'))
Pump 400
$out.check.settled = @([double](P $check 'Progress'), [bool](P $check 'Moving'))
$check.GetType().GetProperty('Box', $instance).SetValue($check, $true, $null)
$check.Checked = $true
Pump 60
$out.check.box = @([double](P $check 'Progress'), [bool](P $check 'Moving'))
Pump 400
$out.check.boxSettled = @([double](P $check 'Progress'), [bool](P $check 'Moving'))
$form.Close(); $form.Dispose()
$reduce.SetValue($null, $true)

# ------------------------------------------------------------------ a list's bar across its bottom
$form = New-Window
function New-List([int]$rows, [int[]]$widths) {
    $list = [Activator]::CreateInstance($t.SoftList, $true)
    $list.View = [Windows.Forms.View]::Details
    $list.BorderStyle = [Windows.Forms.BorderStyle]::None
    foreach ($w in $widths) { $null = $list.Columns.Add('Column', $w) }
    for ($i = 0; $i -lt $rows; $i++) { $null = $list.Items.Add('row ' + $i) }
    $listHost = $t.SoftListHost.GetConstructors($instance)[0].Invoke([object[]]@($list))
    $listHost.Size = New-Object Drawing.Size 300, 200
    $form.Controls.Add($listHost)
    return ,@($listHost, $list)
}
$cases = @{ fits = (New-List 5 @(100, 100, 80)); wide = (New-List 5 @(300, 300, 300)); both = (New-List 60 @(300, 300, 300)); tall = (New-List 60 @(100, 100, 80)) }
$form.Show()
Pump 50
$out.across = @{}
foreach ($name in $cases.Keys) {
    $listHost = $cases[$name][0]; $list = $cases[$name][1]
    $null = Call $listHost 'Sync' @()
    Pump 20
    $null = Call $listHost 'Sync' @()
    $clip = P $listHost 'Clip'
    $bar = P $listHost 'AcrossBar'
    $out.across[$name] = @{ across = [bool](P $listHost 'OverflowingAcross'); down = [bool](P $listHost 'Overflowing')
                            nativeH = (([Probe]::GetWindowLong($list.Handle, -16)) -band 0x00100000) -ne 0
                            host = @($listHost.Width, $listHost.Height); clip = @($clip.Width, $clip.Height)
                            client = @($list.ClientSize.Width, $list.ClientSize.Height); list = @($list.Width, $list.Height)
                            track = (Box (P $bar 'Track')); downTrack = (Box (P (P $listHost 'Bar') 'Track')); barAcross = [bool](P $bar 'Across') }
}
$wide = $cases['wide'][0]
$sideways = F $wide 'sideways'
$scroller = $t.ISoftScroller
$out.across.scroll = @{ extent = [int]$scroller.GetProperty('Extent').GetValue($sideways, $null); viewport = [int]$scroller.GetProperty('Viewport').GetValue($sideways, $null) }
$null = $scroller.GetMethod('ScrollTo').Invoke($sideways, [object[]]@([int]120))
$out.across.scroll.after = [int]$scroller.GetProperty('Offset').GetValue($sideways, $null)
$bar = P $wide 'AcrossBar'
$out.across.scroll.thumb = (Box (P $bar 'Thumb'))
$form.Close(); $form.Dispose()

[Console]::Out.Write(($out | ConvertTo-Json -Depth 10 -Compress))
[Console]::Out.Flush()
# The accessibility objects Windows made for the drop-downs are released here, on this thread, while it can
# still answer them: left to the end of the process, their release waited on this thread forever.
[GC]::Collect()
[GC]::WaitForPendingFinalizers()
[Environment]::Exit(0)
"""

# What UI Automation - how Narrator reads a window - makes of a drop-down, in a process whose accessibility is the
# window's own: .NET's accessibility improvements switched on before any control exists, as Program.Main does.
PROBE_UIA = r"""
$ErrorActionPreference = 'Stop'
[AppContext]::SetSwitch("Switch.UseLegacyAccessibilityFeatures", $false)
[AppContext]::SetSwitch("Switch.UseLegacyAccessibilityFeatures.2", $false)
[AppContext]::SetSwitch("Switch.UseLegacyAccessibilityFeatures.3", $false)
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type -AssemblyName WindowsBase
Add-Type -ReferencedAssemblies System.Windows.Forms, System.Drawing, UIAutomationClient, UIAutomationTypes, WindowsBase -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Threading;
using System.Windows.Automation;
using System.Windows.Forms;
public class QuietForm : Form {
    protected override bool ShowWithoutActivation { get { return true; } }
    protected override CreateParams CreateParams { get { CreateParams cp = base.CreateParams; cp.ExStyle |= 0x08000000 | 0x80; return cp; } }
}
public static class Uia {
    [DllImport("user32.dll")] public static extern IntPtr SendMessage(IntPtr window, int message, IntPtr wParam, IntPtr lParam);
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr window);
    [DllImport("uiautomationcore.dll")] static extern bool UiaHasServerSideProvider(IntPtr window);
    [StructLayout(LayoutKind.Sequential)] public struct Rect { public int Left, Top, Right, Bottom; }
    [StructLayout(LayoutKind.Sequential)] public struct ComboInfo { public int Size; public Rect Item, Button; public int State; public IntPtr Combo, Edit, List; }
    [DllImport("user32.dll")] static extern bool GetComboBoxInfo(IntPtr window, ref ComboInfo info);
    public static IntPtr NativeList(IntPtr combo) {
        var info = new ComboInfo(); info.Size = Marshal.SizeOf(typeof(ComboInfo));
        return GetComboBoxInfo(combo, ref info) ? info.List : IntPtr.Zero;
    }
    public static IntPtr Key(IntPtr window, int key) { return SendMessage(window, 0x0100, new IntPtr(key), new IntPtr(1)); }
    static readonly List<string> seen = new List<string>();
    static void Add(string line) { lock (seen) seen.Add(line); }
    public static string[] Seen() { lock (seen) return seen.ToArray(); }
    // UI Automation is asked from a thread of its own, as a screen reader asks from its own process, while this
    // thread keeps answering the window's messages.
    static void Off(ThreadStart work) {
        var thread = new Thread(delegate() { try { work(); } catch (Exception ex) { Add("!!|" + ex.GetType().Name + "|" + ex.Message); } });
        thread.SetApartmentState(ApartmentState.MTA);
        thread.Start();
        while (thread.IsAlive) { Application.DoEvents(); Thread.Sleep(5); }
    }
    // [control type, name, server-side provider, expand state, selection, value, children's control types]
    public static string[] Read(IntPtr window) {
        string[] found = new[] { "!!" };
        Off(delegate {
            AutomationElement e = AutomationElement.FromHandle(window);
            object p;
            string expand = e.TryGetCurrentPattern(ExpandCollapsePattern.Pattern, out p) ? ((ExpandCollapsePattern)p).Current.ExpandCollapseState.ToString() : "";
            var chosen = new List<string>();
            if (e.TryGetCurrentPattern(SelectionPattern.Pattern, out p))
                foreach (AutomationElement item in ((SelectionPattern)p).Current.GetSelection()) chosen.Add(item.Current.Name);
            string value = e.TryGetCurrentPattern(ValuePattern.Pattern, out p) ? ((ValuePattern)p).Current.Value : "";
            var children = new List<string>();
            TreeWalker walker = TreeWalker.RawViewWalker;
            for (AutomationElement child = walker.GetFirstChild(e); child != null && children.Count < 20; child = walker.GetNextSibling(child))
                children.Add(child.Current.ControlType.ProgrammaticName);
            found = new[] { e.Current.ControlType.ProgrammaticName, e.Current.Name, UiaHasServerSideProvider(window).ToString(), expand,
                            string.Join("|", chosen.ToArray()), value, string.Join("|", children.ToArray()) };
        });
        return found;
    }
    public static bool Expand(IntPtr window, bool expand) {
        bool had = false;
        Off(delegate {
            object p;
            if (!AutomationElement.FromHandle(window).TryGetCurrentPattern(ExpandCollapsePattern.Pattern, out p)) return;
            had = true;
            if (expand) ((ExpandCollapsePattern)p).Expand(); else ((ExpandCollapsePattern)p).Collapse();
        });
        return had;
    }
    static AutomationFocusChangedEventHandler focus;
    public static void Listen() {
        Off(delegate {
            focus = delegate(object sender, AutomationFocusChangedEventArgs a) {
                try { var e = (AutomationElement)sender; Add("focus|" + e.Current.ControlType.ProgrammaticName + "|" + e.Current.Name); }
                catch (Exception ex) { Add("focus|!" + ex.GetType().Name); }
            };
            Automation.AddAutomationFocusChangedEventHandler(focus);
        });
    }
    public static void Unlisten() { Off(delegate { Automation.RemoveAllEventHandlers(); }); }
}
'@
$assembly = [Reflection.Assembly]::LoadFile($env:CAR_EXE)
$static = [Reflection.BindingFlags]'Static,NonPublic,Public'
$instance = [Reflection.BindingFlags]'Instance,NonPublic,Public'
$t = @{}
foreach ($n in 'Palette','Soft','SoftCombo','SoftDropList') { $t[$n] = $assembly.GetType('CodexAutoResume.' + $n, $true) }
function P($target, [string]$name) { return $target.GetType().GetProperty($name, $instance).GetValue($target, $null) }
function Pump([int]$ms) { $sw = [Diagnostics.Stopwatch]::StartNew(); do { [Windows.Forms.Application]::DoEvents(); Start-Sleep -Milliseconds 3 } while ($sw.ElapsedMilliseconds -lt $ms) }
# Events arrive on UI Automation's own threads: waited for, up to three seconds.
function Heard([string]$line) {
    $sw = [Diagnostics.Stopwatch]::StartNew()
    do { if (@([Uia]::Seen()) -contains $line) { return $true }; Pump 20 } while ($sw.ElapsedMilliseconds -lt 3000)
    return $false
}
$null = $t.Palette.GetMethod('Adopt', $static).Invoke($null, [object[]]@('light'))
$t.Soft.GetField('ReduceMotionSetting', $static).SetValue($null, $true)
$origin = New-Object Drawing.Point -30000, -30000
$t.SoftDropList.GetField('Area', $static).SetValue($null, (New-Object Drawing.Rectangle ($origin.X - 3000), ($origin.Y - 3000), 8000, 8000))
$form = New-Object QuietForm
$form.FormBorderStyle = 'None'
$form.ShowInTaskbar = $false
$form.StartPosition = 'Manual'
$form.Location = $origin
$form.Size = New-Object Drawing.Size 600, 400
$combo = [Activator]::CreateInstance($t.SoftCombo, $true)
$combo.Width = 240
$combo.Location = New-Object Drawing.Point 40, 40
$combo.AccessibleName = 'Continuation language'
# Assigned, not wrapped: PowerShell 5 hands ConvertFrom-Json's array on as one object.
$items = ConvertFrom-Json $env:CAR_ITEMS
foreach ($item in $items) { $null = $combo.Items.Add([string]$item) }
$combo.SelectedIndex = 2
$form.Controls.Add($combo)
$form.Show()
Pump 50
$null = $combo.Focus()
$h = $combo.Handle
$native = [Uia]::NativeList($h)
$out = @{}
$out.closed = @([Uia]::Read($h))
[Uia]::Listen()
Pump 100
$null = [Uia]::Key($h, 0x73)
$out.heardOpen = Heard ('focus|ControlType.ListItem|' + $items[2])
$out.open = @([Uia]::Read($h))
$null = [Uia]::Key($h, 0x28)
$out.heardDown = Heard ('focus|ControlType.ListItem|' + $items[3])
$null = [Uia]::Key($h, 0x0D)
Pump 50
$out.picked = @([Uia]::Read($h))
$out.expandable = [Uia]::Expand($h, $true)
Pump 100
$out.expanded = @([bool](P $combo 'Open'), [bool]([Uia]::IsWindowVisible($native)))
$out.expandedRead = @([Uia]::Read($h))
$null = [Uia]::Expand($h, $false)
Pump 100
$out.collapsed = [bool](P $combo 'Open')
[Uia]::Unlisten()
$out.events = @([Uia]::Seen())
$form.Close(); $form.Dispose()
[Console]::Out.Write(($out | ConvertTo-Json -Depth 6 -Compress))
[Console]::Out.Flush()
[GC]::Collect()
[GC]::WaitForPendingFinalizers()
[Environment]::Exit(0)
"""

EASE = [0.0, 0.1, 0.25, 0.5, 0.75, 0.9, 1.0]
# (field, area, width, wanted, pill, rowGap, pad, gap) -> (card, above, rows)
PLACE = [
    (((100, 100, 240, 35), (0, 0, 1920, 1080), 256, 10, 31, 4, 8, 4), ((92, 139, 256, 362), False, 10)),
    (((100, 900, 240, 35), (0, 0, 1920, 1080), 256, 10, 31, 4, 8, 4), ((92, 534, 256, 362), True, 10)),
    (((100, 250, 240, 35), (0, 0, 1920, 600), 256, 10, 31, 4, 8, 4), ((92, 289, 256, 292), False, 8)),
    (((100, 350, 240, 35), (0, 0, 1920, 600), 256, 10, 31, 4, 8, 4), ((92, 19, 256, 327), True, 9)),
    (((1800, 100, 240, 35), (0, 0, 1920, 1080), 256, 3, 31, 4, 8, 4), ((1664, 139, 256, 117), False, 3)),
    (((-5, 100, 240, 35), (0, 0, 1920, 1080), 256, 3, 31, 4, 8, 4), ((0, 139, 256, 117), False, 3)),
    (((100, 40, 240, 35), (0, 0, 1920, 90), 256, 10, 31, 4, 8, 4), ((92, -11, 256, 47), True, 1)),
]
# (texts, typed, from) -> index
FIND = [
    ((ITEMS, "e", 2), 3), ((ITEMS, "ee", 3), 1), ((ITEMS, "E", 0), 1), ((ITEMS, "en", 0), 1),
    ((ITEMS, "port", 2), 8), ((ITEMS, "portu", 8), 8), ((ITEMS, "port ", 2), -1), ((ITEMS, "x", 2), -1), ((ITEMS, "d", 2), 2),
    ((ITEMS, "de", 2), 2), ((ITEMS, "s", 9), 0), ((["Last 7 days", "Last 30 days", "All time"], "last 3", 0), 1),
]


def channels(pixel: int) -> tuple:
    pixel &= 0xFFFFFFFF
    return ((pixel >> 24) & 255, (pixel >> 16) & 255, (pixel >> 8) & 255, pixel & 255)


def px(value: int, scale: float) -> int:
    return int(round(value * scale))


@unittest.skipUnless(CSC.is_file() and POWERSHELL.is_file(), "needs the in-box compiler and PowerShell")
class ControlsTests(unittest.TestCase):
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
        probe = work / "controls.ps1"
        probe.write_text(PROBE, encoding="utf-8")
        cls.result = subprocess.run(
            [str(POWERSHELL), "-STA", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(probe)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900,
            env=dict(os.environ, CAR_EXE=str(exe), CAR_ITEMS=json.dumps(ITEMS), CAR_EASE=json.dumps(EASE),
                     CAR_PLACE=json.dumps([case for case, _ in PLACE]),
                     CAR_FIND=json.dumps([case for case, _ in FIND])))
        cls.answer = (json.loads(cls.result.stdout)
                      if cls.result.returncode == 0 and cls.result.stdout.strip() else {})
        uia = work / "uia.ps1"
        uia.write_text(PROBE_UIA, encoding="utf-8")
        cls.uia_result = subprocess.run(
            [str(POWERSHELL), "-STA", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(uia)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300,
            env=dict(os.environ, CAR_EXE=str(exe), CAR_ITEMS=json.dumps(ITEMS)))
        cls.uia = (json.loads(cls.uia_result.stdout)
                   if cls.uia_result.returncode == 0 and cls.uia_result.stdout.strip() else {})

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def setUp(self):
        if not self.answer:
            self.fail("the probe did not run: " + (self.result.stderr or self.result.stdout)[-4000:])
        self.scale = self.answer["scale"]

    def px(self, value):
        return px(value, self.scale)

    # ---------------------------------------------------------------- one transition, one curve

    def test_every_change_moves_on_brands_one_transition_and_curve(self):
        self.assertEqual(self.answer["duration"], brand.MOTION["transition_ms"])
        for t, got in zip(EASE, self.answer["ease"]):
            with self.subTest(t=t):
                self.assertAlmostEqual(got, brand.ease(t), places=6, msg="brand's one curve, as the popup and panel have it")
        self.assertEqual(self.answer["ease"], sorted(self.answer["ease"]), "it never goes back")
        self.assertGreater(self.answer["ease"][3], 0.75, "most of the way in the first half: it settles, ease-out")

    # ---------------------------------------------------------------- the drop-down's own list

    def test_every_way_windows_list_could_open_opens_this_one_and_windows_list_never_shows(self):
        self.assertTrue(self.answer["nativeListFound"])
        opening = self.answer["opening"]
        for name in ("show", "f4", "altDown", "click", "space", "property"):
            with self.subTest(name):
                self.assertTrue(opening[name]["open"], name + " did not open the list")
                self.assertTrue(opening[name]["dropped"], "DroppedDown answers for this list")
        for name in ("hide", "escape", "altUp", "clickAgain", "propertyOff"):
            with self.subTest(name):
                self.assertFalse(opening[name]["open"], name + " left the list open")
        for name, state in opening.items():
            with self.subTest(name):
                self.assertFalse(state["native"], "Windows' own list appeared")
                self.assertEqual(state["selected"], 2, "opening and closing chose nothing")
                self.assertEqual(state["changed"], 0)
        self.assertTrue(opening["f4"]["cues"], "opened from the keyboard, the highlight has the focus ring")
        self.assertFalse(opening["click"]["cues"], "opened with the pointer, it has none")
        self.assertTrue(opening["spaceChar"]["open"], "the space that opened it is not taken as typing")

    def test_the_keys_move_the_highlight_and_choose_nothing_until_enter(self):
        rows = self.answer["rows"]
        self.assertEqual(rows, len(ITEMS))
        expected, at = [], 2
        page = max(1, rows - 1)
        for key in (0x28, 0x28, 0x26, 0x24, 0x23, 0x21, 0x22, 0x26, 0x25, 0x27):
            at = {0x28: at + 1, 0x26: at - 1, 0x24: 0, 0x23: len(ITEMS) - 1, 0x21: at - page, 0x22: at + page}.get(key, at)
            at = max(0, min(len(ITEMS) - 1, at))
            expected.append(at)
        for (key, state), want in zip(self.answer["keys"], expected):
            with self.subTest(key=hex(key)):
                self.assertEqual(state["highlight"], want)
                self.assertTrue(state["open"])
                self.assertEqual(state["selected"], 2, "moving the highlight chooses nothing")
                self.assertTrue(state["cues"])
                self.assertFalse(state["native"])
        enter = self.answer["enter"]
        self.assertFalse(enter["open"])
        self.assertEqual(enter["selected"], min(len(ITEMS) - 1, expected[-1] + 1))
        self.assertEqual((enter["changed"], enter["committed"]), (1, 1),
                         "SelectedIndexChanged and SelectionChangeCommitted, once each")
        self.assertEqual(self.answer["enterChar"]["open"], False, "the Enter's character goes no further")
        escape = self.answer["escape"]
        self.assertFalse(escape["open"])
        self.assertEqual(escape["selected"], enter["selected"], "Escape leaves the choice as it was")
        self.assertEqual(escape["changed"], 1)
        self.assertEqual(self.answer["altUpTakes"]["selected"], enter["selected"] - 1, "Alt+Up takes the highlighted item")
        self.assertFalse(self.answer["altUpTakes"]["open"])
        self.assertEqual(self.answer["tabTakes"]["selected"], self.answer["altUpTakes"]["selected"] + 1, "and so does Tab")
        self.assertFalse(self.answer["tabTakes"]["open"])

    def test_while_it_is_open_the_keys_are_the_drop_downs_and_not_the_windows(self):
        self.assertEqual(self.answer["inputOpen"], [True] * 9,
                         "Escape and Enter reach the list, not a dialog's Cancel or default button")

    def test_typing_finds_the_next_item_that_starts_with_it(self):
        for (case, expected), got in zip(FIND, self.answer["find"]):
            with self.subTest(typed=case[1], start=case[2]):
                self.assertEqual(got, expected)
        # e from Deutsch: Espanol; e again: on to English; x: nothing, stays. Then "port " finds and keeps Portugues.
        self.assertEqual(self.answer["typed"], [3, 1, 1, 8, 8, 8, 8, 8])
        self.assertTrue(self.answer["typedOpen"], "a space inside a search is part of it, and takes nothing")

    def test_it_opens_under_the_drop_down_with_its_words_under_the_fields_own(self):
        where = self.answer["where"]
        field, card, margin = where["field"], where["card"], where["margin"]
        self.assertFalse(where["above"])
        self.assertEqual(card[1], field[1] + field[3] + self.px(brand.SPACING["xs"]), "just under it, the xs gap below")
        pad = self.px(brand.SPACING["s"])
        self.assertEqual(card[0], field[0] - pad, "its pills start where the field starts")
        self.assertEqual(where["pill"][0], pad)
        self.assertGreaterEqual(card[2], field[2] + 2 * pad)
        self.assertEqual(where["rows"], len(ITEMS))
        self.assertFalse(where["scrolls"])
        self.assertEqual(where["pitch"] - where["pill"][3], self.px(brand.SPACING["xs"]), "items SpaceXs apart")
        self.assertTrue(all(m > 0 for m in margin), "room for the shadow on every side")
        for (case, (box, above, rows)), got in zip(PLACE, self.answer["place"]):
            with self.subTest(case=case):
                self.assertEqual(got, [list(box), above, rows])

    def test_near_the_screens_bottom_edge_it_opens_above_and_where_neither_fits_it_scrolls(self):
        bottom = self.answer["bottom"]
        self.assertTrue(bottom["above"])
        field, card = bottom["field"], bottom["card"]
        self.assertEqual(card[1] + card[3], field[1] - self.px(brand.SPACING["xs"]), "the same gap, above it")
        self.assertEqual(bottom["rows"], len(ITEMS))
        cramped = self.answer["cramped"]
        self.assertLess(cramped["rows"], len(ITEMS))
        self.assertGreaterEqual(cramped["rows"], 1)
        self.assertTrue(cramped["scrolls"])

    def test_the_list_is_a_window_that_never_activates_and_lets_its_shadow_be_clicked_through(self):
        window = self.answer["window"]
        ex = window["exStyle"] & 0xFFFFFFFF
        for flag, name in ((0x00080000, "WS_EX_LAYERED"), (0x08000000, "WS_EX_NOACTIVATE"), (0x00000080, "WS_EX_TOOLWINDOW")):
            with self.subTest(name):
                self.assertTrue(ex & flag, name)
        self.assertTrue(window["style"] & 0x80000000, "a pop-up, never a child: its shadow may leave the window")
        self.assertTrue(window["owner"], "owned by the drop-down's window, so it stays above it")
        self.assertTrue(window["visible"])
        self.assertEqual(window["activate"], 3, "MA_NOACTIVATE")
        self.assertEqual(window["hitCard"], 1, "HTCLIENT on the card")
        self.assertEqual(window["hitShadow"], -1, "HTTRANSPARENT on its shadow")
        self.assertEqual(self.answer["focus"], [True, True], "the focus and the active window are where they were")

    def test_the_card_is_the_cards_material_and_its_items_say_which_is_chosen_and_where_the_keyboard_is(self):
        pixels, colours = self.answer["pixels"], self.answer["colours"]
        self.assertEqual(pixels["card"], colours["card"], "the cards' ground")
        near, far = pixels["below"]
        near_alpha, far_alpha = channels(near)[0], channels(far)[0]
        self.assertTrue(0 < far_alpha < near_alpha < 255, "a shadow under the card, fading out")
        self.assertEqual(channels(pixels["corner"])[0] < 255, True, "the card's corner is round")
        self.assertEqual(pixels["chosen"], colours["inset"], "the chosen item is a sunken pill")
        self.assertEqual(pixels["ring"], colours["focus"], "the keyboard's item has the focus ring")
        self.assertEqual(self.answer["hover"], 5)
        self.assertEqual(self.answer["hoverFill"], colours["raised"], "the item under the pointer rises")
        click = self.answer["click"]
        self.assertFalse(click["open"])
        self.assertEqual(click["selected"], 5, "a click takes the item")

    def test_a_click_elsewhere_the_window_left_or_moved_or_the_drop_down_hidden_closes_it(self):
        closing = self.answer["closing"]
        self.assertEqual(closing["onList"], [False, True], "a press on the list is the list's")
        self.assertEqual(closing["elsewhere"], [True, False], "a press elsewhere closes it and goes no further")
        self.assertEqual(closing["titleBar"], [False, False], "a press on a title bar closes it and still moves the window")
        self.assertFalse(closing["deactivated"])
        self.assertFalse(closing["moved"])
        self.assertFalse(closing["hidden"])
        self.assertEqual(closing["selected"], 5, "none of them chose anything")

    def test_the_wheel_scrolls_an_open_list_and_nothing_else(self):
        self.assertEqual(self.answer["wheelClosed"], [1, 0], "closed, the wheel goes where it always went (IgnoreWheel)")
        long = self.answer["longList"]
        self.assertEqual(long["rows"], long["max"], "MaxDropDownItems rows, and the rest scroll")
        self.assertTrue(long["scrolls"])
        handled, selected, offset = self.answer["wheelOpen"]
        self.assertEqual((handled, selected), (1, 0), "open, the wheel is the list's: no handler, no change")
        lines = self.answer["lines"]
        if lines > 0:
            self.assertEqual(offset, lines * long["pitch"])
        eaten, after = self.answer["wheelElsewhere"]
        self.assertTrue(eaten, "a turn anywhere in the window scrolls the list, not the page under it")
        if lines > 0:
            self.assertGreater(after, offset)
        self.assertEqual(self.answer["endShown"][0], 29)
        self.assertTrue(self.answer["endShown"][2], "End scrolls the last item into view")

    def test_a_screen_reader_hears_the_list_and_the_item_the_keyboard_is_on(self):
        a11y = self.answer["a11y"]
        self.assertEqual(a11y["role"], "ComboBox")
        self.assertEqual(a11y["children"], 1)
        self.assertEqual((a11y["listRole"], a11y["listName"]), ("List", "Continuation language"))
        self.assertEqual(a11y["items"], len(ITEMS))
        self.assertEqual((a11y["itemRole"], a11y["itemName"]), ("ListItem", ITEMS[3]))
        collapsed, expanded, has_popup, focused, selected, invisible = 0x400, 0x200, 0x40000000, 0x4, 0x2, 0x8000
        self.assertTrue(a11y["closedState"] & collapsed)
        self.assertFalse(a11y["closedState"] & expanded)
        self.assertTrue(a11y["closedState"] & has_popup)
        self.assertTrue(a11y["openState"] & expanded)
        self.assertTrue(a11y["closedAgain"] & collapsed)
        self.assertTrue(a11y["listClosed"] & invisible)
        self.assertTrue(a11y["closedItem"] & invisible)
        self.assertTrue(a11y["focusedItem"] & focused and a11y["focusedItem"] & selected)
        self.assertFalse(a11y["otherItem"] & focused)
        self.assertEqual(a11y["focused"], ITEMS[a11y["highlight"]])
        self.assertGreater(a11y["bounds"][2], 0, "an item on the list has its place on the screen")
        self.assertGreater(a11y["listBounds"][3], 0)
        self.assertEqual(a11y["popupClient"][:3], ["Continuation language", str(0x21), str(len(ITEMS))],
                         "asked of the list's own window, the list answers")
        events = [line.split("|") for line in a11y["events"]]
        list_id = str(a11y["listId"])
        focus = [e for e in events if e[0] == "8005" and e[1] == list_id]
        self.assertGreaterEqual(len(focus), 2, "a focus event when it opens and when the highlight moves")
        self.assertEqual(focus[-1][2], str(a11y["highlight"] + 1), "for the item, by its child id")
        self.assertEqual(focus[-1][3], ITEMS[a11y["highlight"]], "and it resolves to the item's name")
        self.assertEqual(focus[-1][4], str(0x22), "ROLE_SYSTEM_LISTITEM")
        self.assertTrue(any(e[0] == "8006" and e[1] == list_id for e in events), "a selection event with it")
        self.assertTrue(any(e[0] == "800A" and e[1] == "-4" for e in events), "the drop-down's expanded state changes")
        self.assertTrue(any(e[0] == "8005" and e[1] == "-4" for e in events[-3:]), "and the focus is back on it when it closes")

    def ui_automation(self):
        if not self.uia:
            self.fail("the UI Automation probe did not run: " + (self.uia_result.stderr or self.uia_result.stdout)[-4000:])
        return self.uia

    def test_ui_automation_reads_a_drop_down_as_a_combo_box_with_its_choice_that_it_can_open(self):
        """What Narrator reads (v0.6.5 review): .NET's own UI Automation provider around the drop-down's accessible object
        said "pane" - no choice, no expanded or collapsed, no Expand - where v0.6.4 said "combo box, Deutsch, collapsed".
        Asked for a provider of its own, the drop-down now has none, as a Win32 drop-down list has none, and UI Automation
        reads it as it reads every one of those: a combo box with its choice, collapsed or expanded, whose Expand and
        Collapse open and close this list - Windows' own never showing."""
        uia = self.ui_automation()
        kind, name, server, expand, chosen = uia["closed"][:5]
        self.assertEqual(kind, "ControlType.ComboBox", uia["closed"])
        self.assertEqual(name, "Continuation language")
        self.assertEqual(server, "False", "no provider of .NET's own, which reads as a pane")
        self.assertEqual(expand, "Collapsed")
        self.assertEqual(chosen, ITEMS[2], "the choice is read")
        self.assertIn("ControlType.List", uia["closed"][6].split("|"), "it has its list")
        self.assertEqual(uia["open"][3], "Expanded", "open, it says so")
        self.assertEqual(uia["picked"][4], ITEMS[3], "a choice from the list is the choice read")
        self.assertTrue(uia["expandable"], "Expand can be called")
        self.assertEqual(uia["expanded"], [True, False], "Expand opens this list, and Windows' stays hidden")
        self.assertEqual(uia["expandedRead"][3], "Expanded")
        self.assertFalse(uia["collapsed"], "Collapse closes it")

    def test_ui_automation_hears_the_item_the_highlight_is_on(self):
        """The keyboard's focus stays on the drop-down, so UI Automation hears the highlight only through the focus
        event raised to it for the item (SoftDropList.RaiseFocus): as the list opens, on the chosen item, and as the
        highlight moves - a list item, by its name."""
        uia = self.ui_automation()
        self.assertTrue(uia["heardOpen"], "\n".join(uia["events"]))
        self.assertTrue(uia["heardDown"], "\n".join(uia["events"]))
        self.assertNotIn("!!", "".join(uia["events"]))

    def test_it_fades_in_and_rises_and_with_motion_reduced_it_is_simply_there(self):
        """On every machine: Windows' animation switch is the probe's own answer (Soft.WindowsAnimates), so GitHub's
        runner, which has it off, sees the list rise too - and sees it simply there with the switch answered off."""
        appear = self.answer["appear"]
        self.assertEqual(appear["reduced"], [255, False, 0])
        self.assertEqual(appear["windows"], [255, False, 0], "Windows' animation effects off: simply there")
        self.assertTrue(self.answer["motionAllowed"], "motion was reduced with Windows' switch answered 'on'")
        alpha, running, rise = appear["first"]
        self.assertTrue(running)
        self.assertLess(alpha, 255)
        self.assertGreater(rise, 0, "lower than where it settles")
        self.assertLessEqual(rise, self.px(brand.SPACING["xs"]))
        self.assertEqual(appear["last"], [255, False, 0], "then there, and its timer stopped")

    def test_dark_has_the_cards_dark_material_and_high_contrast_has_system_colours_and_no_shadow(self):
        dark = self.answer["dark"]
        self.assertEqual(dark["middle"], dark["cardColour"])
        self.assertEqual(dark["chosen"], dark["inset"])
        self.assertTrue(all(m > 0 for m in dark["margin"]))
        contrast = self.answer["contrast"]
        self.assertEqual(contrast["margin"], [0, 0, 0, 0], "no shadow, so no room for one")
        self.assertEqual(contrast["image"], contrast["card"][2:], "the window is the card")
        self.assertEqual(contrast["middle"], contrast["window"])
        self.assertEqual(contrast["chosen"], contrast["highlight"], "the chosen item is Highlight")

    # ---------------------------------------------------------------- the switch and the check box

    def test_at_rest_the_switch_and_the_box_are_exactly_what_they_were(self):
        for on, (switch_same, box_same) in self.answer["rest"].items():
            with self.subTest(on=on):
                self.assertTrue(switch_same, "SwitchAt at rest differs from Switch")
                self.assertTrue(box_same, "DrawBoxAt at rest differs from DrawBox")

    def test_the_knob_slides_and_the_track_cross_fades_and_the_box_fades(self):
        colours = self.answer["onColours"]
        knobs, tracks, boxes = [], [], []
        for v, row, track, box in self.answer["halfway"]:
            knob = [x for x in range(60) if row[x] & 0xFFFFFF == knob_colour(v, colours) & 0xFFFFFF]
            knobs.append(sum(knob) / len(knob) if knob else None)
            tracks.append(channels(track)[1:])
            boxes.append(channels(box)[1:])
        self.assertTrue(all(k is not None for k in knobs), "the knob is one colour, between muted and on-accent")
        self.assertEqual(knobs, sorted(knobs), "the knob moves one way")
        self.assertAlmostEqual(knobs[-1] - knobs[0], self.px(brand.LAYOUT["knob_travel"]), delta=1)
        for index in (1, 2, 3):
            v = self.answer["halfway"][index][0]
            with self.subTest(v=v):
                self.assertAlmostEqual(knobs[index] - knobs[0], v * (knobs[-1] - knobs[0]), delta=1.0,
                                       msg="the knob is as far along as the switch is on")
                for part in (tracks, boxes):
                    for c in range(3):
                        # A cross-fade: the off state, and the on state over it at v.
                        self.assertAlmostEqual(part[index][c], part[0][c] + (part[-1][c] - part[0][c]) * v, delta=2)
        self.assertEqual(tracks[-1], channels(colours["accent"])[1:], "on, the accent")
        self.assertEqual(boxes[-1], channels(colours["accent"])[1:], "checked, the accent")

    def test_a_real_switch_glides_then_stops_and_is_immediate_when_it_cannot_be_seen_or_motion_is_reduced(self):
        check = self.answer["check"]
        self.assertEqual(check["unshown"], [1.0, False], "not on screen: at once")
        self.assertEqual(check["reduced"], [1.0, False], "motion reduced: at once")
        self.assertEqual(check["windows"], [1.0, False], "Windows' animation effects off: at once")
        self.assertEqual(check["settled"], [0.0, False], "arrived, and its timer stopped")
        self.assertEqual(check["boxSettled"], [1.0, False])
        self.assertTrue(self.answer["motionAllowed"], "motion was reduced with Windows' switch answered 'on'")
        progress, moving = check["started"]
        self.assertTrue(moving)
        self.assertLess(progress, 0.5)
        middle, moving = check["middle"]
        self.assertTrue(0.0 < middle < 1.0 and moving, "between off and on, on its way")
        reversed_, moving = check["reversed"]
        self.assertAlmostEqual(reversed_, middle, delta=0.35, msg="turned back, it goes back from where it was")
        self.assertTrue(moving)
        progress, moving = check["box"]
        self.assertTrue(0.0 < progress < 1.0 and moving, "a check box fades too")

    # ---------------------------------------------------------------- a list's bar across its bottom

    def test_a_list_wider_than_its_host_scrolls_sideways_on_the_soft_bar_and_hides_windows_own(self):
        across = self.answer["across"]
        gutter, margin, width = self.px(18), self.px(3), self.px(12)
        fits = across["fits"]
        self.assertFalse(fits["across"])
        self.assertEqual(fits["track"], [0, 0, 0, 0], "no bar while the columns fit")
        self.assertEqual(fits["clip"], fits["host"], "and the whole host shows the rows")
        wide = across["wide"]
        if not wide["nativeH"]:
            self.skipTest("the list computed no horizontal bar off the screen")
        self.assertTrue(wide["across"])
        self.assertTrue(wide["barAcross"])
        self.assertEqual(wide["clip"], [300, 200 - gutter], "the rows end where the gutter starts")
        self.assertEqual(wide["client"][1], wide["clip"][1], "the list's rows fill the clip exactly")
        self.assertGreater(wide["list"][1], wide["clip"][1], "and its own bar lies under the clip, unseen")
        self.assertEqual(wide["track"], [margin, 200 - margin - width, 300 - 2 * margin, width])
        both = across["both"]
        self.assertTrue(both["across"] and both["down"])
        self.assertEqual(both["clip"], [300 - gutter, 200 - gutter])
        self.assertEqual(both["track"][2], 300 - gutter - 2 * margin, "the bar across stops at the bar beside")
        self.assertEqual(both["downTrack"][1] + both["downTrack"][3], 200 - gutter - margin,
                         "and the bar beside stops above the bar across")
        tall = across["tall"]
        self.assertTrue(tall["down"])
        self.assertFalse(tall["across"])
        scroll = across["scroll"]
        self.assertEqual(scroll["extent"], 900)
        self.assertEqual(scroll["viewport"], 300)
        self.assertEqual(scroll["after"], 120, "the soft bar scrolls the list itself")
        self.assertGreater(scroll["thumb"][0], margin + self.px(2))


def knob_colour(v, colours):
    """The knob's colour at `v`: Soft.Mix of the muted and on-accent colours."""
    if v <= 0:
        return colours["muted"]
    if v >= 1:
        return colours["onAccent"]
    a, b = channels(colours["muted"])[1:], channels(colours["onAccent"])[1:]
    mixed = [int(round(a[i] + (b[i] - a[i]) * v)) for i in range(3)]
    return (0xFF << 24) | (mixed[0] << 16) | (mixed[1] << 8) | mixed[2]


class SourceRuleTests(unittest.TestCase):
    """Rules that hold for the source, so they fail without a compiler too."""

    def setUp(self):
        self.controls = guiscan.controls()

    def block(self, signature, end="\n        }\n"):
        start = self.controls.index(signature)
        return self.controls[start:self.controls.index(end, start)]

    def test_motion_is_brands_one_transition_and_stops_when_it_is_reduced(self):
        motion = self.block("internal static class Motion", "\n    }\n")
        self.assertIn("return Brand.TransitionMs;", motion)
        # v0.6.10: through the controls' gate, which is every stopper Soft.ReduceMotion knows and a design that does not
        # glide (Still).
        self.assertIn("Soft.ControlsStill", self.block("internal static bool Allowed(Control control)"))
        still = self.block("internal static bool ControlsStill")
        self.assertIn("ReduceMotion", still)
        self.assertIn("Brand.DesignGlides(Palette.Design)", still)
        transition = self.block("internal sealed class Transition ", "\n    }\n")
        self.assertIn("timer.Stop();", self.block("private void Tick()"), "the timer stops when it arrives")
        self.assertNotIn("PerformLayout", transition, "paint only")

    def test_a_switch_changes_by_painting_alone(self):
        changed = self.block("protected override void OnCheckedChanged(EventArgs e)")
        self.assertIn("turn.To(Checked ? 1.0 : 0.0, Motion.Allowed(this));", changed)
        self.assertNotIn("PerformLayout", changed)
        self.assertIn("turn.Area = Glyph;", changed, "only the glyph is repainted while it moves")

    def test_the_list_never_activates_and_has_no_shadow_in_high_contrast(self):
        show = self.block("internal void Show()")
        self.assertIn("cp.ExStyle = WS_EX_LAYERED | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE;", show)
        self.assertIn("SW_SHOWNOACTIVATE", show)
        measure = self.block("private void Measure()")
        self.assertIn("margin = Palette.Contrast ? Padding.Empty : Elevation.Reach(\"card\");", measure)
        self.assertIn("bool animate = Motion.Allowed(combo);", show, "no fade or rise with motion reduced")
        self.assertIn("UpdateLayeredWindow(", self.controls)

    def test_every_message_that_opens_windows_list_is_answered_by_the_drop_down(self):
        messages = self.block("private bool ListMessage(ref Message m)")
        for name in ("CB_SHOWDROPDOWN", "CB_GETDROPPEDSTATE", "WM_LBUTTONDOWN", "WM_LBUTTONDBLCLK", "WM_MOUSEWHEEL",
                     "WM_KEYDOWN", "WM_SYSKEYDOWN", "WM_CHAR"):
            with self.subTest(name):
                self.assertIn(name, messages)
        wndproc = self.block("protected override void WndProc(ref Message m)\n        {\n            if (IsHandleCreated && NativePaint")
        self.assertLess(wndproc.index("ListMessage(ref m)"), wndproc.index("base.WndProc(ref m);"))

    def test_no_guid_shaped_text_but_made_up_ones_even_before_it_is_tracked(self):
        """tests/test_repo_hygiene.py holds every tracked file to made-up GUIDs, and a new file only once it is committed:
        the IID of IAccessible, written as a string in the window's controls and in this file's probe, turned the whole suite red.
        Windows' constants are built from their fields instead. Checked here for every window source and every window
        test, tracked or not."""
        import test_repo_hygiene as hygiene
        found = []
        for path in sorted((ROOT / "gui").glob("*.cs")) + sorted((ROOT / "tests").glob("test_gui*.py")):
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                for value in hygiene.UUID.findall(line):
                    if not hygiene.SYNTHETIC_UUID.match(value):
                        found.append("%s:%d %s" % (path.name, number, value))
        self.assertEqual(found, [])

    def test_no_string_switch_and_no_initialized_constant_array(self):
        code = "\n".join(line for line in self.controls.splitlines() if not line.lstrip().startswith("//"))
        self.assertNotRegex(code, r"switch\s*\(\s*\w*(?:[Nn]ame|[Tt]ext|[Ss]tate|[Kk]ey)\s*\)")
        self.assertNotRegex(code, r"new\s+(?:byte|short|int|long|float|double|char|bool)\s*\[\s*\d*\s*\]\s*\{")
        self.assertNotRegex(code, r"(?:byte|short|int|long|float|double|char|bool)\s*\[\s*\]\s+\w+\s*=\s*\{")


if __name__ == "__main__":
    unittest.main()
