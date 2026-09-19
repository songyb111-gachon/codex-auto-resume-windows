r"""The window's taskbar button wears the notification-area icon's motion while the window is open (v0.6.5).

The user asked, before v0.6.5's release, whether the app's icon at the bottom of Windows could move like the tray icon
while the window is open ("윈도우 아래 앱 켜있을때 아이콘도 트레이 아이콘 처럼 할 수 있나?"). It can, and this holds it:

  * Windows draws the taskbar button from the window's big icon (WM_SETICON, ICON_BIG) - measured on Windows 11 at
    150%: the 48 px big icon, drawn at 36 - and reads it again only when the window's small icon changes; a new big
    icon alone never reached the button. So TaskbarMark (gui/Controls.cs) sets each frame as the big icon and then
    sets the small icon again with the other of two handles to one image. The small icon - the title bar's, which the
    documentation screenshots capture - never changes by a pixel;
  * the state is the tray icon's for the header light's: Brand.Mark.IconState is tray.ICON_FOR_LIGHT, which
    tests/test_tray_icon_motion.py holds equal to tray.icon_state, and here it is held equal across every status the
    window can see, through the window's own Activity, and through the window itself (its light tells the mark);
  * the rhythms are the tray's (Brand.Mark.Frame and FrameMs against tray.icon_frame and icon_frame_ms), and the
    frames are the tray's own pixels: MarkFrames composes, from what build/make_brand.py generated, exactly what
    tray.IconFrames composes, at every size the big icon has from 100% to 200%;
  * the big icon changes over time while watching, turning and pulsing, and not at all under Reduce motion, Windows'
    animation effects, High Contrast or battery saver, nor with the window hidden - and moves again when the reason
    goes; with nothing to move there is no timer;
  * every icon made is destroyed once the next is held: GDI and USER objects stay level over hundreds of frames, and
    once the window closes the mark has left nothing, its timer included.

Windows' animation switch, High Contrast and battery saver are the probe's own answers (Soft.WindowsAnimates,
Theme.HighContrastOn, TaskbarMark.BatterySaverOn), so a runner's settings decide nothing, and the mark's clock is the
probe's (TaskbarMark.Clock), so each frame is asked for at a moment the probe chooses. The windows are the probe's own,
far off the screen, shown without activation and without a taskbar button; nothing is sent to any other window.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import unittest

from codex_auto_resume import brand, l10n, tray

from test_gui_layout import fullest_snapshot

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "build"))
import make_brand                                    # noqa: E402

GUI = ROOT / "gui"
ICO = ROOT / "assets" / "codex-auto-resume.ico"
CSC = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe"
POWERSHELL = (Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
              / "WindowsPowerShell" / "v1.0" / "powershell.exe")

LIGHTS = ("monitoring", "waiting", "checking", "recovering", "paused", "idle", "attention", "failed", "", "stopped",
          "Monitoring", "watching")
STATES = tray.ICON_STATES + ("", "paused", "monitoring")
MOMENTS = (0, 150, 800, 1600, 1799, 2400, 3200, 5000, 9999, 27599, 27600, 28000, 28800, 29400, 29999, 30000, 31234,
           57700, 59000)
SINCE = (-1, 0, 300, 700, 1399, 1400, 5000)
PROBE_SIZES = (16, 24, 32, 40, 48, 56, 64, 72)
COLOURS = (brand.rgb(brand.ICON_ACCENT), tray.icon_head_colour("idle"), tray.icon_head_colour("attention"),
           tray.icon_head_colour("failed"), (0, 0, 0), (201, 7, 99))
NOW = 1_800_000_000.0


def window_cases():
    """Every kind of status the window's header light is decided from (SettingsForm.Activity), with what the tray's
    own rule makes of the same watcher: a tick snapshot and its attention, or - for a watcher that is not running,
    which has no tray icon at all - the light alone."""
    def status(**changes):
        value = {"watcher_running": True, "enabled": True, "upgrade_pending": False, "pending": 0,
                 "watcher": {"running": True, "ticking": True}}
        value.update(changes)
        return value

    def row(code, eligible=None):
        return {"code": code, "eligible_at": eligible}

    waiting, due = row("waiting_for_reset", NOW + 600), row("waiting_for_retry", NOW - 5)
    cases = [
        ("not running", status(watcher_running=False), [], "idle", None),
        ("not known to run", status(watcher_running=None), [], "idle", None),
        ("an unfinished upgrade", status(upgrade_pending=True), [waiting], "attention", ({"enabled": True}, True)),
        ("not ticking", status(watcher={"running": True, "ticking": False}), [], "attention", ({}, True)),
        ("paused", status(enabled=False), [waiting], "paused", ({"enabled": False, "waiting": 1}, False)),
        ("paused while one runs", status(enabled=False), [row("turn_running")], "paused",
         ({"enabled": False, "running": 1}, False)),
        ("paused with an upgrade", status(enabled=False, upgrade_pending=True), [], "attention",
         ({"enabled": False}, True)),
        ("nothing to do", status(), [], "monitoring", ({"enabled": True, "waiting": 0, "running": 0}, False)),
        ("waiting", status(pending=1), [waiting], "waiting",
         ({"enabled": True, "waiting": 1, "next_at": NOW + 600}, False)),
        ("due", status(pending=2), [waiting, due], "checking",
         ({"enabled": True, "waiting": 2, "next_at": NOW - 5}, False)),
        ("list unreadable, some waiting", status(pending=2), None, "waiting", ({"enabled": True, "waiting": 2}, False)),
        ("list unreadable, none waiting", status(pending=0), None, "monitoring", ({"enabled": True}, False)),
    ]
    for code in ("submission_claimed", "submitted", "turn_running", "turn_finishing"):
        cases.append(("recovering: " + code, status(pending=2), [waiting, row(code)], "recovering",
                      ({"enabled": True, "waiting": 1, "running": 1}, False)))
    return cases


def tray_frames_digest(size) -> str:
    """The tray icon's own frames at `size`, every head position in each of COLOURS, with no badge."""
    frames = tray.IconFrames(size)
    digest = hashlib.sha256()
    for position in range(tray.ICON_MOTION["positions"]):
        for colour in COLOURS:
            digest.update(frames.compose(position, colour))
    return digest.hexdigest()


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
using System.Security.Cryptography;
using System.Windows.Forms;
public class QuietForm : Form {
    protected override bool ShowWithoutActivation { get { return true; } }
    protected override CreateParams CreateParams { get { CreateParams cp = base.CreateParams; cp.ExStyle |= 0x08000000 | 0x80; return cp; } }
}
// Answers for the window's inputs from Windows, compiled, so they hold on any thread.
public static class Said {
    public static bool Yes() { return true; }
    public static bool No() { return false; }
    public static Func<bool> Answer(bool yes) { return yes ? new Func<bool>(Yes) : new Func<bool>(No); }
}
// The mark's clock, the probe's.
public static class ProbeClock {
    public static double Now;
    public static double Read() { return Now; }
    public static Func<double> Func() { return new Func<double>(Read); }
}
public sealed class Digest {
    private readonly SHA256 sha = SHA256.Create();
    public void Add(byte[] bytes) { sha.TransformBlock(bytes, 0, bytes.Length, null, 0); }
    public string Hex() { sha.TransformFinalBlock(new byte[0], 0, 0); return BitConverter.ToString(sha.Hash).Replace("-", "").ToLowerInvariant(); }
    public static string Of(byte[] bytes) { if (bytes == null) return ""; var d = new Digest(); d.Add(bytes); return d.Hex(); }
}
public static class Icons {
    [StructLayout(LayoutKind.Sequential)] struct IconInfo { public bool Icon; public int X; public int Y; public IntPtr Mask; public IntPtr Colour; }
    [StructLayout(LayoutKind.Sequential)] struct Bmp { public int Type; public int Width; public int Height; public int WidthBytes; public short Planes; public short BitsPixel; public IntPtr Bits; }
    [StructLayout(LayoutKind.Sequential)] struct Header { public int Size; public int Width; public int Height; public short Planes; public short BitCount; public int Compression; public int SizeImage; public int X; public int Y; public int Used; public int Important; }
    [DllImport("user32.dll")] static extern IntPtr SendMessage(IntPtr window, int message, IntPtr wParam, IntPtr lParam);
    [DllImport("user32.dll")] static extern bool GetIconInfo(IntPtr icon, out IconInfo info);
    [DllImport("gdi32.dll")] static extern int GetObject(IntPtr item, int size, out Bmp bmp);
    [DllImport("gdi32.dll")] static extern int GetDIBits(IntPtr dc, IntPtr bitmap, uint start, uint lines, byte[] bits, ref Header header, uint usage);
    [DllImport("gdi32.dll")] static extern bool DeleteObject(IntPtr item);
    [DllImport("user32.dll")] static extern IntPtr GetDC(IntPtr window);
    [DllImport("user32.dll")] static extern int ReleaseDC(IntPtr window, IntPtr dc);
    [DllImport("user32.dll")] static extern uint GetGuiResources(IntPtr process, uint flags);
    public static IntPtr Big(Form form) { return SendMessage(form.Handle, 0x7F, (IntPtr)1, IntPtr.Zero); }
    public static IntPtr Small(Form form) { return SendMessage(form.Handle, 0x7F, (IntPtr)0, IntPtr.Zero); }
    // An icon's colour bitmap, top-down BGRA, as Windows holds it; the copies GetIconInfo makes are deleted.
    public static byte[] Pixels(IntPtr icon) {
        IconInfo info;
        if (icon == IntPtr.Zero || !GetIconInfo(icon, out info)) return null;
        try {
            Bmp bmp;
            if (GetObject(info.Colour, Marshal.SizeOf(typeof(Bmp)), out bmp) == 0) return null;
            var header = new Header();
            header.Size = Marshal.SizeOf(typeof(Header)); header.Width = bmp.Width; header.Height = -bmp.Height; header.Planes = 1; header.BitCount = 32;
            var bits = new byte[bmp.Width * bmp.Height * 4];
            IntPtr dc = GetDC(IntPtr.Zero);
            try { if (GetDIBits(dc, info.Colour, 0, (uint)bmp.Height, bits, ref header, 0) == 0) return null; }
            finally { ReleaseDC(IntPtr.Zero, dc); }
            return bits;
        } finally {
            if (info.Mask != IntPtr.Zero) DeleteObject(info.Mask);
            if (info.Colour != IntPtr.Zero) DeleteObject(info.Colour);
        }
    }
    public static int[] Resources() {
        IntPtr process = System.Diagnostics.Process.GetCurrentProcess().Handle;
        return new int[] { (int)GetGuiResources(process, 0), (int)GetGuiResources(process, 1) };
    }
}
'@
$assembly = [Reflection.Assembly]::LoadFile($env:CAR_EXE)
$static = [Reflection.BindingFlags]'Static,NonPublic,Public'
$instance = [Reflection.BindingFlags]'Instance,NonPublic,Public'
$rule = $assembly.GetType('CodexAutoResume.Brand+Mark', $true)
$markType = $assembly.GetType('CodexAutoResume.TaskbarMark', $true)
$framesType = $assembly.GetType('CodexAutoResume.MarkFrames', $true)
$form = $assembly.GetType('CodexAutoResume.SettingsForm', $true)
$soft = $assembly.GetType('CodexAutoResume.Soft', $true)
$themeType = $assembly.GetType('CodexAutoResume.Theme', $true)
$palette = $assembly.GetType('CodexAutoResume.Palette', $true)
$parse = $assembly.GetType('CodexAutoResume.Json', $true).GetMethod('Parse', $static)
$work = [string]$env:CAR_WORK
$utf8 = New-Object Text.UTF8Encoding $false
$invariant = [Globalization.CultureInfo]::InvariantCulture
function Read-Json([string]$name) { return $parse.Invoke($null, [object[]]@([IO.File]::ReadAllText((Join-Path $work $name), $utf8))) }
function Pump([int]$ms) { $sw = [Diagnostics.Stopwatch]::StartNew(); do { [Windows.Forms.Application]::DoEvents(); Start-Sleep -Milliseconds 2 } while ($sw.ElapsedMilliseconds -lt $ms) }
function Rgb([Drawing.Color]$c) { return ,@([int]$c.R, [int]$c.G, [int]$c.B) }
$out = @{}

# ------------------------------------------------------------------ the rule, as tables
$iconState = $rule.GetMethod('IconState', $static)
# Pairs, not a hashtable: PowerShell's keys ignore case, and 'Monitoring' is not 'monitoring'.
$out.lights = @()
foreach ($light in (ConvertFrom-Json $env:CAR_LIGHTS)) { $out.lights += ,@([string]$light, [string]$iconState.Invoke($null, [object[]]@([string]$light))) }
$out.nullLight = [string]$iconState.Invoke($null, [object[]]@($null))
$activity = $form.GetMethod('Activity', $static)
$out.window = @()
foreach ($case in (ConvertFrom-Json $env:CAR_CASES)) {
    $status = $parse.Invoke($null, [object[]]@([string]$case.status))
    $pending = $null
    if ($case.pending -ne $null) { $pending = $parse.Invoke($null, [object[]]@([string]$case.pending)) }
    $light = [string]$activity.Invoke($null, [object[]]@($status, $pending, [double]$env:CAR_NOW))
    $out.window += ,@([string]$case.name, $light, [string]$iconState.Invoke($null, [object[]]@($light)))
}
$frame = $rule.GetMethod('Frame', $static)
$frameMs = $rule.GetMethod('FrameMs', $static)
$turn = $rule.GetMethod('Turn', $static)
$out.frames = @()
foreach ($state in (ConvertFrom-Json $env:CAR_STATES)) {
    foreach ($ms in (ConvertFrom-Json $env:CAR_MOMENTS)) {
        foreach ($since in (ConvertFrom-Json $env:CAR_SINCE)) {
            foreach ($reduced in @($false, $true)) {
                $arguments = [object[]]@([string]$state, [double]$ms, [double]$since, [bool]$reduced, [int]0, [int]0)
                $null = $frame.Invoke($null, $arguments)
                $next = [int]$frameMs.Invoke($null, [object[]]@([string]$state, [double]$ms, [double]$since, [bool]$reduced))
                $out.frames += ,@([string]$state, [double]$ms, [double]$since, [bool]$reduced, [int]$arguments[4], [int]$arguments[5], $next,
                                  ([double]$turn.Invoke($null, [object[]]@([string]$state, [double]$ms))).ToString('R', $invariant))
            }
        }
    }
}
$head = $rule.GetMethod('HeadColour', $static)
$level = $rule.GetMethod('LevelColour', $static)
$out.heads = @{}
$out.levels = @()
foreach ($state in (ConvertFrom-Json $env:CAR_STATES)) {
    $full = $head.Invoke($null, [object[]]@([string]$state))
    $out.heads[[string]$state] = Rgb $full
    foreach ($l in -1..10) { $out.levels += ,@([string]$state, $l, (Rgb $level.Invoke($null, [object[]]@($full, [int]$l)))) }
}
$allowed = $markType.GetMethod('MotionAllowed', $static)
$out.allowed = @()
foreach ($bits in 0..31) {
    $flags = @((($bits -band 1) -ne 0), (($bits -band 2) -ne 0), (($bits -band 4) -ne 0), (($bits -band 8) -ne 0), (($bits -band 16) -ne 0))
    $out.allowed += ,@($flags + @([bool]$allowed.Invoke($null, [object[]]$flags)))
}

# ------------------------------------------------------------------ the frames: the tray's own pixels
$for = $framesType.GetMethod('For', $static)
$compose = $framesType.GetMethod('Compose', $instance)
$positions = [int]$rule.GetField('Positions', $static).GetValue($null)
$colours = @()
foreach ($c in (ConvertFrom-Json $env:CAR_COLOURS)) { $colours += [Drawing.Color]::FromArgb([int]$c[0], [int]$c[1], [int]$c[2]) }
$out.sizes = @{}
foreach ($size in (ConvertFrom-Json $env:CAR_SIZES)) {
    $table = $for.Invoke($null, [object[]]@([int]$size))
    if ($table -eq $null) { $out.sizes[[string]$size] = ''; continue }
    $digest = New-Object Digest
    for ($p = 0; $p -lt $positions; $p++) { foreach ($c in $colours) { $digest.Add([byte[]]$compose.Invoke($table, [object[]]@([int]$p, $c))) } }
    $out.sizes[[string]$size] = $digest.Hex()
}

# ------------------------------------------------------------------ the mark on a window of the probe's own
# Windows' inputs are the probe's answers: animation effects on, High Contrast off, battery saver off - and the light theme.
$animates = $soft.GetField('WindowsAnimates', $static)
$contrast = $themeType.GetField('HighContrastOn', $static)
$saver = $markType.GetField('BatterySaverOn', $static)
$reduce = $soft.GetField('ReduceMotionSetting', $static)
$animates.SetValue($null, [Said]::Answer($true))
$contrast.SetValue($null, [Said]::Answer($false))
$saver.SetValue($null, [Said]::Answer($false))
$reduce.SetValue($null, $false)
$null = $palette.GetMethod('Adopt', $static).Invoke($null, [object[]]@('light'))
$animate = $markType.GetMethod('Animate', $instance)
$sync = $markType.GetMethod('Sync', $instance)
$follow = $markType.GetMethod('Follow', $instance)
function Field($mark, [string]$name) { return $markType.GetField($name, $instance).GetValue($mark) }
$movingProperty = $markType.GetProperty('Moving', $instance)
$stateProperty = $markType.GetProperty('State', $instance)
function Moving($mark) { return [bool]$movingProperty.GetValue($mark, $null) }
function StateOf($mark) { return [string]$stateProperty.GetValue($mark, $null) }
function New-Host {
    $window = New-Object QuietForm
    $window.ShowInTaskbar = $false
    $window.StartPosition = 'Manual'
    $window.Location = New-Object Drawing.Point -30000, -30000
    $window.ClientSize = New-Object Drawing.Size 200, 120
    $window.Icon = New-Object Drawing.Icon ([string]$env:CAR_ICO)
    $window.Show()
    Pump 60
    return $window
}
# What the window shows now: the big icon's handle and pixels, the small icon's.
function Look($window) {
    $big = [Icons]::Big($window); $small = [Icons]::Small($window)
    return @{ big = [int64]$big; bigPixels = [Digest]::Of([Icons]::Pixels($big)); small = [int64]$small; smallPixels = [Digest]::Of([Icons]::Pixels($small)) }
}
function Expected($table, [string]$state, [double]$ms, [double]$since, [bool]$reduced) {
    $arguments = [object[]]@($state, $ms, $since, $reduced, [int]0, [int]0)
    $null = $frame.Invoke($null, $arguments)
    $colour = $level.Invoke($null, [object[]]@($head.Invoke($null, [object[]]@($state)), [int]$arguments[5]))
    return @{ position = [int]$arguments[4]; level = [int]$arguments[5]; pixels = [Digest]::Of([byte[]]$compose.Invoke($table, [object[]]@([int]$arguments[4], $colour))) }
}
# Steps the probe's clock through `moments` from `start`, a frame asked for at each, and says what the window shows.
function Walk($mark, $window, [double]$start, $moments) {
    $seen = @()
    foreach ($ms in $moments) {
        [ProbeClock]::Now = $start + [double]$ms
        $null = $animate.Invoke($mark, @())
        $look = Look $window
        $seen += ,@([double]$ms, $look.big, $look.bigPixels, $look.small, $look.smallPixels, (Moving $mark), [int](Field $mark 'interval'))
    }
    return ,$seen
}

$before = [Icons]::Resources()
$window = New-Host
$own = Look $window
$out.own = $own
$out.ownSize = [int]$window.Icon.Width
$table = $for.Invoke($null, [object[]]@([int]$window.Icon.Width))
$out.table = [bool]($table -ne $null)
$baseline = [Icons]::Resources()
$mark = $markType.GetConstructors($instance)[0].Invoke([object[]]@($window.PSObject.BaseObject))
$markType.GetField('Clock', $instance).SetValue($mark, [ProbeClock]::Func())
[ProbeClock]::Now = 0
$out.before = @{ state = (StateOf $mark); moving = (Moving $mark); look = (Look $window) }

# Watching: breathes, and turns once in the last 2.4 s of every 30 s.
$null = $follow.Invoke($mark, [object[]]@('monitoring'))
$out.watching = @{ state = (StateOf $mark); moving = (Moving $mark); interval = [int](Field $mark 'interval')
                   breath = (Walk $mark $window 0 (0..32 | ForEach-Object { $_ * 100 }))
                   turn = (Walk $mark $window 0 (0..30 | ForEach-Object { 27000 + $_ * 100 })) }
# Every frame shown is the composed frame the rule asks for at that moment.
$checks = @()
foreach ($ms in @(0, 400, 1600, 2800, 27700, 28400, 29100, 29800)) {
    [ProbeClock]::Now = $ms
    $null = $animate.Invoke($mark, @())
    $want = Expected $table 'watching' $ms $ms $false
    $look = Look $window
    $checks += ,@($ms, $want.position, $want.level, $want.pixels, $look.bigPixels, $look.big, $own.big)
}
$out.watching.checks = $checks
# The frame timer itself, on real time: frames come without the probe asking.
$sw = [Diagnostics.Stopwatch]::StartNew()
$timed = @()
while ($sw.ElapsedMilliseconds -lt 2500) {
    [ProbeClock]::Now = 100000 + $sw.Elapsed.TotalMilliseconds
    [Windows.Forms.Application]::DoEvents()
    Start-Sleep -Milliseconds 5
    $timed += [int64][Icons]::Big($window)
}
$out.watching.timed = @($timed | Select-Object -Unique).Count

# Each reason holds it still, and it moves again when the reason goes.
$out.held = @{}
foreach ($reason in @('reduce', 'animation', 'contrast', 'saver', 'hidden')) {
    switch ($reason) {
        'reduce' { $reduce.SetValue($null, $true) }
        'animation' { $animates.SetValue($null, [Said]::Answer($false)) }
        'contrast' { $contrast.SetValue($null, [Said]::Answer($true)) }
        'saver' { $saver.SetValue($null, [Said]::Answer($true)) }
        'hidden' { $window.Hide() }
    }
    [ProbeClock]::Now = 200000
    $null = $sync.Invoke($mark, @())
    $held = @{ moving = (Moving $mark); interval = [int](Field $mark 'interval'); look = (Look $window) }
    $sw = [Diagnostics.Stopwatch]::StartNew()
    $handles = @()
    while ($sw.ElapsedMilliseconds -lt 900) {
        [ProbeClock]::Now = 200000 + $sw.Elapsed.TotalMilliseconds
        [Windows.Forms.Application]::DoEvents()
        Start-Sleep -Milliseconds 5
        $handles += [int64][Icons]::Big($window)
    }
    $held.handles = @($handles | Select-Object -Unique)
    $held.after = Look $window
    switch ($reason) {
        'reduce' { $reduce.SetValue($null, $false) }
        'animation' { $animates.SetValue($null, [Said]::Answer($true)) }
        'contrast' { $contrast.SetValue($null, [Said]::Answer($false)) }
        'saver' { $saver.SetValue($null, [Said]::Answer($false)) }
        'hidden' { $window.Show(); Pump 30 }
    }
    [ProbeClock]::Now = 201600
    $null = $sync.Invoke($mark, @())
    $held.again = @{ moving = (Moving $mark); interval = [int](Field $mark 'interval')
                     walk = (Walk $mark $window 201600 (0..16 | ForEach-Object { $_ * 100 })) }
    $out.held[$reason] = $held
}
# The product's Reduce motion held while the state changes: every state at rest, in its colour only.
$reduce.SetValue($null, $true)
$null = $sync.Invoke($mark, @())
$out.reduced = @{}
foreach ($light in @('monitoring', 'recovering', 'paused', 'attention', 'failed')) {
    [ProbeClock]::Now = 300000
    $null = $follow.Invoke($mark, [object[]]@($light))
    $out.reduced[$light] = @{ state = (StateOf $mark); moving = (Moving $mark)
                              walk = (Walk $mark $window 300000 (0..20 | ForEach-Object { $_ * 100 }))
                              want = (Expected $table ((StateOf $mark)) 0 0 $true).pixels }
}
$reduce.SetValue($null, $false)

# Recovering turns all the time, paused is grey and still, a problem pulses once and holds.
foreach ($pair in @(@('recovering', 'recovering'), @('paused', 'idle'), @('attention', 'attention'), @('failed', 'failed'), @('idle', 'idle'))) {
    [ProbeClock]::Now = 400000
    $null = $follow.Invoke($mark, [object[]]@($pair[0]))
    $entry = @{ state = (StateOf $mark); moving = (Moving $mark); interval = [int](Field $mark 'interval')
                walk = (Walk $mark $window 400000 (0..24 | ForEach-Object { $_ * 100 })) }
    $entry.rest = (Expected $table ((StateOf $mark)) 0 5000 $false).pixels
    $entry.movingAfter = (Moving $mark)
    $out[$pair[0]] = $entry
    # The next state starts from watching, so each is entered afresh.
    $null = $follow.Invoke($mark, [object[]]@('monitoring'))
}

# Hundreds of frames: the objects the process holds stay level.
$null = $follow.Invoke($mark, [object[]]@('recovering'))
$leak = @()
for ($i = 0; $i -lt 360; $i++) {
    [ProbeClock]::Now = 500000 + $i * 67
    $null = $animate.Invoke($mark, @())
    if ($i -eq 10 -or $i -eq 180 -or $i -eq 359) { $leak += ,@($i, [Icons]::Resources()) }
}
$out.leak = @{ at = $leak; baseline = $baseline; before = $before; distinct = 0 }

# Closing: the timer stops as the window starts to close, and the window ends with its own icons and nothing of the mark's.
$closing = @{}
$window.add_FormClosing({ $closing.moving = (Moving $mark); $closing.stopping = [bool](Field $mark 'closing') })
$window.add_FormClosed({ $closing.big = [int64][Icons]::Big($window); $closing.small = [int64][Icons]::Small($window) })
$window.Close()
Pump 50
$closing.disposed = [bool](Field $mark 'disposed')
$closing.shown = [int64](Field $mark 'shown')
$closing.copy = [int64](Field $mark 'smallCopy')
$closing.timer = (Moving $mark)
[ProbeClock]::Now = 600000
$null = $animate.Invoke($mark, @())
$null = $sync.Invoke($mark, @())
$null = $follow.Invoke($mark, [object[]]@('recovering'))
$closing.timerAfter = (Moving $mark)
$window.Dispose()
Pump 50
[GC]::Collect()
[GC]::WaitForPendingFinalizers()
$closing.resources = [Icons]::Resources()
$closing.baseline = $baseline
$out.closing = $closing

# The window itself: its header light tells the mark, and a window LayoutAudit builds makes none of its own.
$nowhere = [string](Join-Path $work 'nowhere')
$bridgeType = $assembly.GetType('CodexAutoResume.Bridge', $true)
$persistentType = $assembly.GetType('CodexAutoResume.PersistentBridge', $true)
$three = @($form.GetConstructors($instance) | Where-Object { $_.GetParameters().Count -eq 3 })[0]
$once = $bridgeType.GetConstructors($instance)[0].Invoke([object[]]@($nowhere))
$bridge = $persistentType.GetConstructors($instance)[0].Invoke([object[]]@($nowhere, $once))
$settings = $three.Invoke([object[]]@($bridge, (Read-Json 'strings-en.json').PSObject.BaseObject, [Drawing.SystemFonts]::MessageBoxFont))
$form.GetField('auditing', $instance).SetValue($settings, $true)
$out.audited = [bool]($form.GetField('taskbar', $instance).GetValue($settings) -eq $null)
$second = New-Host
$told = $markType.GetConstructors($instance)[0].Invoke([object[]]@($second.PSObject.BaseObject))
$markType.GetField('Clock', $instance).SetValue($told, [ProbeClock]::Func())
[ProbeClock]::Now = 700000
$form.GetField('taskbar', $instance).SetValue($settings, $told)
$dot = $form.GetField('stateDot', $instance).GetValue($settings)
$dotState = $assembly.GetType('CodexAutoResume.HaloDot', $true).GetProperty('State', $instance)
$method = @($form.GetMethods($instance) | Where-Object { $_.Name -eq 'ApplySnapshot' -and $_.GetParameters().Count -eq 1 })[0]
$out.wired = @()
foreach ($name in (ConvertFrom-Json $env:CAR_SNAPSHOTS)) {
    $null = $method.Invoke($settings, [object[]]@((Read-Json ($name + '.json')).PSObject.BaseObject))
    $out.wired += ,@([string]$name, [string]$dotState.GetValue($dot, $null), (StateOf $told), [int64][Icons]::Big($second))
}
$second.Close()
$second.Dispose()
$settings.Dispose()
[IO.File]::WriteAllText((Join-Path $work 'result.json'), ($out | ConvertTo-Json -Depth 10 -Compress), $utf8)
[GC]::Collect()
[GC]::WaitForPendingFinalizers()
[Environment]::Exit(0)
"""


@unittest.skipUnless(CSC.is_file() and POWERSHELL.is_file(), "needs the in-box compiler and PowerShell")
class TaskbarMarkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        work = Path(cls.folder.name)
        exe = work / "CodexAutoResumeSettings.exe"
        subprocess.run([str(CSC), "/nologo", "/target:winexe", "/platform:x64", "/out:" + str(exe),
                        "/reference:System.dll", "/reference:System.Drawing.dll", "/reference:System.Windows.Forms.dll",
                        *[str(GUI / name) for name in ("SettingsApp.cs", "Dashboard.cs", "Controls.cs", "Brand.cs")]],
                       check=True, capture_output=True, timeout=300)
        reply = {"ok": True, "language": "en", "strings": l10n.catalog("en"), "endonyms": dict(l10n.ENDONYMS),
                 "preference": "en", "system_language": "en"}
        (work / "strings-en.json").write_text(json.dumps(reply, ensure_ascii=False), encoding="utf-8")
        cls.snapshots = cls.window_snapshots(time.time())
        for name, snapshot in cls.snapshots.items():
            (work / (name + ".json")).write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")
        cls.cases = window_cases()
        probe = work / "taskbar.ps1"
        probe.write_text(PROBE, encoding="utf-8")
        cases = [{"name": name, "status": json.dumps(status),
                  "pending": None if pending is None else json.dumps(pending)}
                 for name, status, pending, _, _ in cls.cases]
        cls.result = subprocess.run(
            [str(POWERSHELL), "-STA", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(probe)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900,
            env=dict(os.environ, CAR_EXE=str(exe), CAR_WORK=str(work), CAR_ICO=str(ICO), CAR_NOW=repr(NOW),
                     CAR_LIGHTS=json.dumps(LIGHTS), CAR_STATES=json.dumps(STATES), CAR_MOMENTS=json.dumps(MOMENTS),
                     CAR_SINCE=json.dumps(SINCE), CAR_SIZES=json.dumps(PROBE_SIZES),
                     CAR_COLOURS=json.dumps([list(colour) for colour in COLOURS]), CAR_CASES=json.dumps(cases),
                     CAR_SNAPSHOTS=json.dumps(list(cls.snapshots))))
        answer = work / "result.json"
        cls.answer = (json.loads(answer.read_text(encoding="utf-8-sig"))
                      if cls.result.returncode == 0 and answer.is_file() else {})

    @staticmethod
    def window_snapshots(now):
        """Dashboard replies whose status and list put the header light in each state it has."""
        fullest = fullest_snapshot(now)
        waiting = [row for row in fullest["pending"] if row.get("eligible_at")][:1]
        if not waiting:
            raise AssertionError("the fullest snapshot has no waiting row")

        def reply(pending, **status):
            value = copy.deepcopy(fullest)
            value["pending"] = copy.deepcopy(pending)
            value["status"].update(status)
            value["status"]["pending"] = len(pending)
            return value

        future = copy.deepcopy(waiting[0])
        future["eligible_at"] = now + 3600
        due = copy.deepcopy(waiting[0])
        due["eligible_at"] = now - 60
        running = copy.deepcopy(waiting[0])
        running["code"] = running["state"] = "turn_running"
        running["eligible_at"] = None
        return {"monitoring": reply([]), "waiting": reply([future]), "checking": reply([future, due]),
                "recovering": reply([future, running]), "paused": reply([future], enabled=False),
                "stopped": reply([], watcher_running=False), "attention": reply([future], upgrade_pending=True),
                "again": reply([future])}

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def setUp(self):
        if not self.answer:
            self.fail("the probe did not run: " + (self.result.stderr or self.result.stdout)[-4000:])

    # ---------------------------------------------------------------- the state: the tray's own rule
    def test_every_light_is_the_tray_icon_s_state_for_it(self):
        self.assertEqual(self.answer["nullLight"], "idle")
        lights = dict(self.answer["lights"])
        self.assertEqual(list(lights), list(LIGHTS))
        for light in LIGHTS:
            with self.subTest(light=light):
                self.assertEqual(lights[light], tray.icon_state_for_light(light))
        self.assertEqual({lights[light] for light in brand.STATUS_FILL}, set(tray.ICON_STATES))

    def test_every_status_the_window_can_see_is_the_tray_icon_s_state_for_the_same_watcher(self):
        rows = {name: (light, icon) for name, light, icon in self.answer["window"]}
        self.assertEqual(len(rows), len(self.cases))
        seen = set()
        for name, _, _, light, tray_side in self.cases:
            with self.subTest(case=name):
                got_light, got_icon = rows[name]
                self.assertEqual(got_light, light, "the window's light for this status")
                if tray_side is None:
                    expected = tray.icon_state_for_light(light)       # no watcher, no tray icon: its rule for the light
                else:
                    snapshot, attention = tray_side
                    expected = tray.icon_state(snapshot, attention=attention)
                self.assertEqual(got_icon, expected)
                seen.add(got_light)
        # Every light the window's Activity gives was exercised.
        self.assertEqual(seen, {"idle", "attention", "paused", "monitoring", "waiting", "checking", "recovering"})

    # ---------------------------------------------------------------- the rhythm: the tray's own
    def test_every_frame_and_interval_is_the_tray_icon_s(self):
        rows = self.answer["frames"]
        self.assertEqual(len(rows), len(STATES) * len(MOMENTS) * len(SINCE) * 2)
        for state, ms, since, reduced, position, level, interval, turned in rows:
            entered = since if since >= 0 else None
            with self.subTest(state=state, ms=ms, since=since, reduced=reduced):
                self.assertEqual((position, level), tray.icon_frame(state, ms, entered, reduced=reduced))
                expected = tray.icon_frame_ms(state, ms, entered, reduced=reduced)
                self.assertEqual(interval, -1 if expected is None else expected)
                turn = tray.icon_turn(state, ms)
                self.assertEqual(float(turned), -1.0 if turn is None else turn)

    def test_the_head_s_colours_are_the_tray_icon_s(self):
        for state in STATES:
            with self.subTest(state=state):
                self.assertEqual(tuple(self.answer["heads"][state]), tray.icon_head_colour(state))
        for state, level, colour in self.answer["levels"]:
            with self.subTest(state=state, level=level):
                self.assertEqual(tuple(colour), tray.icon_level_colour(tray.icon_head_colour(state), level))

    def test_any_one_reason_holds_it_still(self):
        rows = self.answer["allowed"]
        self.assertEqual(len(rows), 32)
        for reduced, contrast, saver, shown, frames, allowed in rows:
            with self.subTest(reduced=reduced, contrast=contrast, saver=saver, shown=shown, frames=frames):
                self.assertEqual(allowed, shown and frames and not (reduced or contrast or saver))

    # ---------------------------------------------------------------- the pixels: the tray's own
    def test_the_frames_are_the_tray_icon_s_own_pixels_at_every_big_icon_size(self):
        sizes = self.answer["sizes"]
        self.assertEqual(make_brand.MARK_SIZES, (32, 40, 48, 56, 64))
        for size in PROBE_SIZES:
            with self.subTest(size=size):
                if size in make_brand.MARK_SIZES:
                    self.assertEqual(sizes[str(size)], tray_frames_digest(size))
                else:
                    self.assertEqual(sizes[str(size)], "", "no frames at a size the big icon never has here")

    def test_the_big_icon_is_windows_own_size_and_there_are_frames_for_it(self):
        self.assertIn(self.answer["ownSize"], make_brand.MARK_SIZES)
        self.assertTrue(self.answer["table"])
        own = self.answer["own"]
        self.assertTrue(own["big"] and own["small"] and own["bigPixels"] and own["smallPixels"])
        before = self.answer["before"]
        self.assertIsNone(before["state"] or None)
        self.assertFalse(before["moving"])
        self.assertEqual(before["look"]["big"], own["big"])

    # ---------------------------------------------------------------- the button over time
    def small_is_still(self, walk):
        """The small icon - the title bar's - keeps its own image in every frame, whichever of the two handles it is."""
        own = self.answer["own"]
        self.assertEqual({row[4] for row in walk}, {own["smallPixels"]})
        self.assertLessEqual(len({row[3] for row in walk}), 2)

    def test_watching_breathes_and_turns_once_on_the_big_icon_and_the_small_icon_never_changes(self):
        watching = self.answer["watching"]
        self.assertEqual(watching["state"], "watching")
        self.assertTrue(watching["moving"])
        self.assertEqual(watching["interval"], tray.ICON_MOTION["breathe_frame_ms"])
        breath, turn = watching["breath"], watching["turn"]
        # The breath: the head's brightness, in its place - many pictures over one 3.2 s cycle, the first the window's
        # own icon again at full brightness.
        self.assertGreaterEqual(len({row[2] for row in breath}), tray.ICON_MOTION["levels"] - 2)
        self.assertEqual(breath[0][1], self.answer["own"]["big"])
        self.assertTrue(all(row[5] for row in breath))
        # The turn: the head travels, faster frames while it does.
        self.assertGreaterEqual(len({row[2] for row in turn}), 15)
        self.assertIn(tray.ICON_MOTION["turn_frame_ms"], {row[6] for row in turn})
        self.small_is_still(breath + turn)
        for ms, position, level, wanted, shown, handle, own in watching["checks"]:
            with self.subTest(ms=ms):
                self.assertEqual((position, level), tray.icon_frame("watching", ms, ms))
                if position == 0 and level == tray.ICON_MOTION["levels"] - 1:
                    self.assertEqual(handle, own, "at rest the big icon is the window's own")
                else:
                    self.assertEqual(shown, wanted, "the big icon is the composed frame")

    def test_the_frame_timer_moves_it_by_itself(self):
        self.assertGreaterEqual(self.answer["watching"]["timed"], 5)

    def test_recovering_keeps_turning(self):
        recovering = self.answer["recovering"]
        self.assertEqual(recovering["state"], "recovering")
        self.assertTrue(recovering["moving"])
        self.assertEqual(recovering["interval"], tray.ICON_MOTION["turn_frame_ms"])
        self.assertGreaterEqual(len({row[2] for row in recovering["walk"]}), 12)
        self.assertTrue(recovering["movingAfter"])
        self.small_is_still(recovering["walk"])

    def test_paused_and_stopped_are_grey_and_still_with_no_timer(self):
        for light in ("paused", "idle"):
            entry = self.answer[light]
            with self.subTest(light=light):
                self.assertEqual(entry["state"], "idle")
                self.assertFalse(entry["moving"])
                self.assertEqual(entry["interval"], -1)
                self.assertEqual({row[2] for row in entry["walk"]}, {entry["rest"]})
                self.assertEqual(len({row[1] for row in entry["walk"]}), 1)
                self.assertNotEqual(entry["walk"][0][1], self.answer["own"]["big"])
                self.small_is_still(entry["walk"])

    def test_a_problem_pulses_once_and_then_holds_its_colour(self):
        for light in ("attention", "failed"):
            entry = self.answer[light]
            walk = entry["walk"]
            with self.subTest(light=light):
                self.assertEqual(entry["state"], light)
                self.assertTrue(entry["moving"], "the pulse runs the timer")
                pulse = [row for row in walk if row[0] < brand.GLOW["attention_ms"]]
                after = [row for row in walk if row[0] >= brand.GLOW["attention_ms"]]
                self.assertGreaterEqual(len({row[2] for row in pulse}), 4)
                self.assertEqual({row[2] for row in after}, {entry["rest"]})
                self.assertFalse(after[-1][5], "no timer once the pulse is over")
                self.assertFalse(entry["movingAfter"])
                self.small_is_still(walk)

    def test_each_reason_holds_it_still_and_it_moves_again_when_the_reason_goes(self):
        own = self.answer["own"]
        for reason in ("reduce", "animation", "contrast", "saver", "hidden"):
            held = self.answer["held"][reason]
            with self.subTest(reason=reason):
                self.assertFalse(held["moving"])
                self.assertEqual(held["interval"], -1)
                # Watching at rest is the window's own big icon, and for almost a second nothing changed it.
                self.assertEqual(held["handles"], [own["big"]])
                self.assertEqual(held["after"]["big"], own["big"])
                self.assertEqual(held["after"]["smallPixels"], own["smallPixels"])
                again = held["again"]
                self.assertTrue(again["moving"])
                self.assertGreaterEqual(len({row[2] for row in again["walk"]}), 3)

    def test_with_motion_reduced_every_state_is_its_colour_at_rest(self):
        own = self.answer["own"]
        for light, entry in self.answer["reduced"].items():
            with self.subTest(light=light):
                self.assertFalse(entry["moving"])
                self.assertEqual(len({row[1] for row in entry["walk"]}), 1, "the big icon never changed")
                if entry["state"] in ("watching", "recovering"):
                    self.assertEqual(entry["walk"][0][1], own["big"])
                else:
                    self.assertEqual(entry["walk"][0][2], entry["want"])
                self.small_is_still(entry["walk"])

    # ---------------------------------------------------------------- what it holds, and what it leaves
    def test_hundreds_of_frames_hold_the_gdi_and_user_objects_level(self):
        leak = self.answer["leak"]
        (_, early), (_, middle), (_, late) = leak["at"]
        for index, name in enumerate(("GDI", "USER")):
            with self.subTest(objects=name):
                self.assertLessEqual(abs(late[index] - early[index]), 1)
                self.assertLessEqual(abs(middle[index] - early[index]), 1)
                # The frame on show and the second small handle, and nothing else.
                self.assertLessEqual(early[index] - leak["baseline"][index], 6)

    def test_closing_stops_the_timer_and_leaves_the_window_its_own_icons_and_nothing_of_the_mark_s(self):
        closing = self.answer["closing"]
        self.assertFalse(closing["moving"], "no timer once the window starts closing")
        self.assertTrue(closing["stopping"])
        self.assertEqual(closing["big"], self.answer["own"]["big"])
        self.assertEqual(closing["small"], self.answer["own"]["small"])
        self.assertTrue(closing["disposed"])
        self.assertEqual((closing["shown"], closing["copy"]), (0, 0))
        self.assertFalse(closing["timer"])
        self.assertFalse(closing["timerAfter"], "nothing starts it again once the window is gone")
        for index, name in enumerate(("GDI", "USER")):
            with self.subTest(objects=name):
                self.assertLessEqual(closing["resources"][index], closing["baseline"][index])

    # ---------------------------------------------------------------- the window
    def test_the_window_s_header_light_tells_the_mark(self):
        self.assertTrue(self.answer["audited"], "a window LayoutAudit builds has no mark of its own")
        rows = {name: (dot, state, big) for name, dot, state, big in self.answer["wired"]}
        expected = {"monitoring": "monitoring", "waiting": "waiting", "checking": "checking",
                    "recovering": "recovering", "paused": "paused", "stopped": "idle", "attention": "attention",
                    "again": "waiting"}
        for name, light in expected.items():
            with self.subTest(snapshot=name):
                dot, state, _ = rows[name]
                self.assertEqual(dot, light)
                self.assertEqual(state, tray.icon_state_for_light(light))

    def test_the_window_makes_its_mark_only_with_its_own_icon_and_asks_it_again_every_second(self):
        settings = (GUI / "SettingsApp.cs").read_text(encoding="utf-8")
        dashboard = (GUI / "Dashboard.cs").read_text(encoding="utf-8")
        block = settings[settings.index('string icon = Path.Combine(root, "codex-auto-resume.ico");'):]
        block = block[:block.index("catch (Exception)")]
        self.assertIn("Icon = new Icon(icon);", block)
        self.assertIn("if (catalog == null) taskbar = new TaskbarMark(this);", block)
        self.assertEqual(len(re.findall(r"new TaskbarMark\(", settings + dashboard)), 1)
        self.assertIn("stateDot.StateSet += delegate { if (taskbar != null) taskbar.Follow(stateDot.State); };",
                      settings)
        tick = dashboard[dashboard.index("clock.Tick += delegate"):]
        tick = tick[:tick.index("clock.Start();")]
        self.assertIn("if (taskbar != null) taskbar.Sync();", tick)


if __name__ == "__main__":
    unittest.main()
