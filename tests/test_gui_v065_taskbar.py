r"""The window's taskbar button wears the notification-area icon's motion while the window is open (v0.6.5).

The user asked, before v0.6.5's release, whether the app's icon at the bottom of Windows could move like the tray icon
while the window is open ("윈도우 아래 앱 켜있을때 아이콘도 트레이 아이콘 처럼 할 수 있나?"). It can, and this holds it:

  * Windows draws the taskbar button from the window's big icon (WM_SETICON, ICON_BIG) - measured on Windows 11 at
    150%: the 48 px big icon, drawn at 36 - and reads it again only when the window's small icon changes; a new big
    icon alone never reached the button. So TaskbarMark (gui/Controls.cs) sets each frame as the big icon and then
    sets the small icon again with the other of two handles to one image. The small icon - the title bar's, which the
    documentation screenshots capture - never changes by a pixel;
  * the state is the tray icon's for the same watcher. The window reads what the icon's popup reads (get_status and
    list_pending), and SettingsForm.TrayActivity makes of it the word tray.icon_state makes its state from, which
    Brand.Mark.IconState maps as tray.ICON_FOR_LIGHT does: the icon as it is with its popup open, since the window,
    like the open popup, reads the watcher now. That is held equal to tray.py's own code - snapshot_from,
    popup_attention over a PopupModel, icon_state - for every kind of watcher and of pending record the window can
    read, from the control layer's own describe_record; and the window itself tells its mark so. Where no icon of this
    version can be showing - no watcher running, or an older one still owning the state - the button is the header
    light's;
  * the rhythms are the tray's (Brand.Mark.Frame and FrameMs against tray.icon_frame and icon_frame_ms), and the
    frames are the tray's own pixels: MarkFrames composes, from what build/make_brand.py generated, exactly what
    tray.IconFrames composes, at each of the .ico's entries the big icon is from 100% to 300% (32, 40, 48 and 64 px);
  * the big icon changes over time while watching, turning and pulsing, and not at all under Reduce motion, Windows'
    animation effects, High Contrast or battery saver, nor while the session is locked or disconnected, nor with the
    window hidden - and moves again when the reason goes; with nothing to move there is no timer;
  * every icon made is destroyed once the next is held: GDI and USER objects stay level over hundreds of frames, and
    once the window closes the mark has left nothing, its timer included.

Windows' animation switch, High Contrast, battery saver and a locked session are the probe's own answers
(Soft.WindowsAnimates, Theme.HighContrastOn, TaskbarMark.BatterySaverOn and SessionLockedOn), so a runner's settings and
its session decide nothing, and the mark's clock is the
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
import types
import unittest

from codex_auto_resume import brand, control, l10n, machine, tray, tray_popup

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
# Watching's loop is five slots of brand's monitoring breath - three breaths, then a sweep out and back in the last
# two - so the moments cross each breath's edge, the sweep's start, its far end and the pause there, its way home,
# its rest there and a second loop. They are built from the rhythm, not written as seconds, so that softening the
# light (v0.6.6: 3.2 s to 4.4 s) moves the probe with it rather than leaving it sampling the middle of a breath.
SLOT = int(brand.GLOW["monitoring_ms"])
SWEEP_AT = SLOT * tray.ICON_MOTION["breaths"]
LOOP = SLOT * (tray.ICON_MOTION["breaths"] + tray.ICON_MOTION["sweep_breaths"])
OUT = int(SLOT * tray.ICON_MOTION["sweep_breaths"] * tray.ICON_MOTION["sweep_out"])
HOLD = int(SLOT * tray.ICON_MOTION["sweep_breaths"] * tray.ICON_MOTION["sweep_hold"])
MOMENTS = tuple(sorted({0, 150, SLOT // 4, SLOT // 2, SLOT // 2 + 80, SLOT - 1, SLOT, SLOT + 400, 2 * SLOT,
                        SWEEP_AT - 1, SWEEP_AT, SWEEP_AT + 50, SWEEP_AT + OUT, SWEEP_AT + OUT + HOLD,
                        SWEEP_AT + 2 * OUT + HOLD, LOOP - 1, LOOP, LOOP + 50, 31234, 59000}))
# One breath, sampled to its end, and the sweep's slot from just before it to just after it.
BREATH_WALK = tuple(range(0, SLOT + 1, max(50, SLOT // 32)))
TURN_WALK = tuple(range(SWEEP_AT - 100, LOOP + 200, 100))
SINCE = (-1, 0, 300, 700, 1399, 1400, 5000)
PROBE_SIZES = (16, 24, 32, 40, 48, 56, 64, 72)
# Windows' display scales, and the big icon's size at each: SM_CXICON, 32 px at 100%.
SCALES = (100, 125, 150, 175, 200, 225, 250, 300, 350, 400, 450, 500)
BIG_SIZES = tuple(32 * scale // 100 for scale in SCALES)
COLOURS = (brand.rgb(brand.ICON_ACCENT), tray.icon_head_colour("idle"), tray.icon_head_colour("attention"),
           tray.icon_head_colour("failed"), (0, 0, 0), (201, 7, 99))
NOW = 1_800_000_000.0


def for_light(light):
    """The tray icon's state for a status-light word (tray.ICON_FOR_LIGHT); anything else is idle."""
    return tray.ICON_FOR_LIGHT.get(light, "idle")


# ------------------------------------------------------------------ one watcher, as the window and the tray read it
def stored(index, state, now=NOW, **changes):
    """A pending record as the store keeps it: what control.describe_record and tray.snapshot_from read."""
    value = {"interruption_id": "%064x" % index, "thread_id": "%08d-0000-7000-8000-000000000000" % index,
             "state": state, "category": "usage_limit", "detected_at": now - 900, "reset_at": None,
             "next_retry_at": None, "recovery_attempts": 1, "no_progress_count": 0, "chain_continuations": 0,
             "chain_origin_id": None, "parent_interruption_id": None, "budget_resets": 0, "cancel_requested": 0,
             "recovery_turn_status": None, "user_joined": 0, "after_user_work": 0, "outcome_at": None,
             "first_queued_at": None, "gate_eval": None, "gate_eval_at": None, "last_error": None, "queue_id": None}
    value.update(changes)
    return value


def pending_kinds(now=NOW):
    """One record of every kind store.pending() returns: each stored state that is not final, and the two whose public
    code is more than their state's - a retry that never reached Codex's queue, a claim already in it."""
    kinds = [stored(index + 1, state, now, next_retry_at=now + 600)
             for index, state in enumerate(sorted(machine.WAITING))]
    kinds.append(stored(20, "waiting_retry", now, last_error="queue_process_not_started", next_retry_at=now + 60))
    kinds.append(stored(21, "submitting", now))
    kinds.append(stored(22, "submitting", now, queue_id="queue-entry"))
    kinds += [stored(30 + index, state, now)
              for index, state in enumerate(sorted(machine.IN_FLIGHT | machine.OBSERVING))]
    return kinds


# What the control layer knows of the watcher (Control._watcher), in each case the window can see.
WATCHERS = {
    "watching": {"running": True, "ticking": True, "engine_state": "verified"},
    "a compatible engine": {"running": True, "ticking": True, "engine_state": "structurally_compatible"},
    "no heartbeat yet": {"running": True, "ticking": None, "engine_state": "unknown"},
    "not ticking": {"running": True, "ticking": False, "engine_state": "verified"},
    "an incompatible engine": {"running": True, "ticking": True, "engine_state": "incompatible"},
    "not running": {"running": False, "ticking": None, "engine_state": "unknown"},
    "not known to run": {"running": None, "ticking": None, "engine_state": "unknown"},
}


class WatcherStore:
    """The watcher's store, as tray.snapshot_from reads it."""

    def __init__(self, records, enabled, marks=None):
        self.records, self.enabled = records, enabled
        self.marks = marks or {"failed_at": None, "started_at": None}

    def pending(self):
        return [dict(record) for record in self.records]

    def settings(self):
        return {"enabled": self.enabled}

    def failure_marks(self):
        return dict(self.marks)


def tray_icon(status, rows, records, enabled, popup_open, now=NOW, failure=None):
    """The notification-area icon's state for one watcher, by tray.py's own code, as Tray._observe makes it: the tick's
    snapshot of the store (snapshot_from), whether a failure in it is still unseen (Tray._failure_unseen, through the
    control layer's rule), and whether its popup, open or not, says a person must act (popup_attention over a
    PopupModel that read the same get_status and list_pending the window reads). `failure` is (marks, seen_at)."""
    marks, seen = failure or (None, None)
    snapshot = tray.snapshot_from(WatcherStore(records, enabled, marks), now)
    failed = control.unseen_failure(snapshot["failures"], seen) is not None
    model = tray_popup.PopupModel()
    model.status, model.rows = copy.deepcopy(status), copy.deepcopy(rows)
    popup = types.SimpleNamespace(visible=popup_open, attention=model.attention)
    return tray.icon_state(snapshot, attention=tray.popup_attention(popup), failed=failed)


def watcher_case(name, records, *, watcher, enabled=True, listed=True, upgrade=False, disabled=(), now=NOW,
                 listed_with=None, failure=None):
    """One watcher: what the window reads of it - control.get_status and control.list_pending, as the bridge's dashboard
    reply carries them, each row from control.describe_record - and, where a watcher of this version runs and so has an
    icon, that icon's state with its popup closed and open (tray_icon). A list that could not be read is None, and the
    open popup is then given the status alone, as the window has it. An older watcher that still owns the state
    (upgrade_pending) is read as get_status reads it - no codes - and its records are not listed. `listed_with` is the
    watcher as list_pending found it, a moment after get_status, where the two differ."""
    watcher = dict(watcher, last_tick_at=now - 5)
    listed_with = watcher if listed_with is None else dict(listed_with, last_tick_at=now - 5)
    codes = {}
    if not upgrade:
        for record in records:
            code = machine.public_code(record)
            codes[code] = codes.get(code, 0) + 1
    status = {"version": "0.6.5", "enabled": enabled, "watcher_running": watcher["running"], "watcher": watcher,
              "upgrade_pending": upgrade, "startup_enabled": True, "pending": len(records), "codes": codes}
    if failure is not None:
        # get_status's key, by the same rule the icon asks the control layer (Control.failure_unseen).
        status["failure_unseen"] = control.unseen_failure(*failure) is not None
    rows = None
    if listed and not upgrade:
        rows = []
        for record in records:
            on = record["thread_id"] not in disabled
            row = control.describe_record(record, enabled=enabled, thread_enabled=on, watcher=listed_with)
            row.update({"thread_enabled": on, "name": None, "project": None, "cwd_basename": None})
            rows.append(row)
    icon = None
    if watcher["running"] is True and not upgrade:
        icon = tuple(tray_icon(status, rows, records, enabled, opened, now, failure) for opened in (False, True))
    return {"name": name, "status": status, "rows": rows, "tray": icon}


def button_for(case):
    """The taskbar button's state for one watcher: the tray icon's with its popup open - the window reads the watcher
    now, as the open popup does. Where no icon of this version can be showing, the header light's: grey with no
    watcher running or none known to, and needing a person while an older watcher still owns the state."""
    if case["tray"] is not None:
        return case["tray"][1]
    status = case["status"]
    return "attention" if status["upgrade_pending"] and status["watcher_running"] is True else "idle"


def window_cases():
    """Every kind of watcher the window can read: each of WATCHERS, recovery on and paused, listed and not, with nothing
    pending, some waiting, one due, one of every pending kind beside a waiting one, a switched-off conversation and a
    cancel asked for; and an older watcher that still owns the state, running or not."""
    waiting = stored(90, "waiting_reset", next_retry_at=NOW + 600)
    due = stored(91, "waiting_poll", next_retry_at=NOW - 5)
    sets = [("nothing pending", [], ()), ("one waiting", [waiting], ()), ("one due", [waiting, due], ())]
    sets += [("one %s (%s)" % (machine.public_code(kind), kind["state"]), [waiting, kind], ())
             for kind in pending_kinds()]
    sets += [("a switched-off conversation", [waiting], (waiting["thread_id"],)),
             ("a cancel asked for", [stored(92, "turn_started", cancel_requested=1)], ())]
    cases = []
    for watcher_name, watcher in WATCHERS.items():
        for enabled in (True, False):
            for set_name, records, disabled in sets:
                for listed in (True, False):
                    name = "%s, %s, %s, %s" % (watcher_name, "on" if enabled else "paused", set_name,
                                               "listed" if listed else "unlisted")
                    cases.append(watcher_case(name, records, watcher=watcher, enabled=enabled, listed=listed,
                                              disabled=disabled))
    for watcher_name in ("watching", "not running"):
        for enabled in (True, False):
            name = "an older watcher owns the state, %s, %s" % (watcher_name, "on" if enabled else "paused")
            cases.append(watcher_case(name, [waiting], watcher=WATCHERS[watcher_name], enabled=enabled, upgrade=True))
    # v0.6.8: a certain failure, unseen, seen, and followed by a new recovery - red only while nobody has seen it and
    # nothing has started since, whatever else the watcher is doing, and never where no watcher of this version runs.
    failures = {"a failure nobody has seen": ({"failed_at": NOW - 60, "started_at": NOW - 90}, NOW - 3600),
                "a failure already seen": ({"failed_at": NOW - 60, "started_at": NOW - 90}, NOW - 30),
                "a failure a new recovery followed": ({"failed_at": NOW - 60, "started_at": NOW - 20}, NOW - 3600)}
    for failure_name, failure in failures.items():
        for watcher_name in ("watching", "not running", "an incompatible engine"):
            for enabled in (True, False):
                name = "%s, %s, %s, one waiting" % (watcher_name, "on" if enabled else "paused", failure_name)
                cases.append(watcher_case(name, [waiting], watcher=WATCHERS[watcher_name], enabled=enabled,
                                          failure=failure))
    # The list read a moment after the status, the watcher changed between: its records carry what the status does not
    # yet say (tray_popup.ATTENTION_OVERLAYS), which the open popup reads as a person needing to act.
    for watcher_name in ("an incompatible engine", "not running", "not ticking"):
        for enabled in (True, False):
            name = "watching, then %s, %s, one waiting, listed" % (watcher_name, "on" if enabled else "paused")
            cases.append(watcher_case(name, [waiting], watcher=WATCHERS["watching"], enabled=enabled,
                                      listed_with=WATCHERS[watcher_name]))
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
    // A message to the probe's own window, as Windows sends it.
    public static long Send(Form form, int message, int wParam, int lParam) { return (long)SendMessage(form.Handle, message, (IntPtr)wParam, (IntPtr)lParam); }
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
# Each watcher the window can read, as the bridge answers it: its header light (Activity), and its taskbar button's word
# (TrayActivity) and state.
$activity = $form.GetMethod('Activity', $static)
$trayActivity = $form.GetMethod('TrayActivity', $static)
$out.window = @()
foreach ($case in (Read-Json 'cases.json')) {
    $status = $case['status']
    $pending = $case['rows']
    $light = [string]$activity.Invoke($null, [object[]]@($status, $pending, [double]$env:CAR_NOW))
    $word = [string]$trayActivity.Invoke($null, [object[]]@($status, $pending, [double]$env:CAR_NOW))
    $out.window += ,@([string]$case['name'], $light, $word, [string]$iconState.Invoke($null, [object[]]@($word)))
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
                # The turn is written G17, not R: on .NET Framework R can print a double that does not read back.
                $out.frames += ,@([string]$state, [double]$ms, [double]$since, [bool]$reduced, [int]$arguments[4], [int]$arguments[5], $next,
                                  ([double]$turn.Invoke($null, [object[]]@([string]$state, [double]$ms))).ToString('G17', $invariant))
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
foreach ($bits in 0..63) {
    $flags = @((($bits -band 1) -ne 0), (($bits -band 2) -ne 0), (($bits -band 4) -ne 0), (($bits -band 8) -ne 0), (($bits -band 16) -ne 0),
               (($bits -band 32) -ne 0))
    $out.allowed += ,@($flags + @([bool]$allowed.Invoke($null, [object[]]$flags)))
}
# Windows' own answer for this session, as the mark reads it when no probe stands one in.
$out.sessionLocked = [bool]$markType.GetMethod('SessionLocked', $static).Invoke($null, @())

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
# The .ico entry the window's big icon is at each size Windows asks for. The window makes it with new Icon(path), which
# is Icon(path, SM_CXICON, SM_CXICON): System.Drawing takes the file's own entry nearest that size and scales none.
$out.picked = @()
foreach ($n in (ConvertFrom-Json $env:CAR_BIG_SIZES)) {
    $icon = New-Object Drawing.Icon -ArgumentList @([string]$env:CAR_ICO, [int]$n, [int]$n)
    $out.picked += ,@([int]$n, [int]$icon.Width, [int]$icon.Height)
    $icon.Dispose()
}

# ------------------------------------------------------------------ the mark on a window of the probe's own
# Windows' inputs are the probe's answers: animation effects on, High Contrast off, battery saver off, the session
# unlocked - and the light theme.
$animates = $soft.GetField('WindowsAnimates', $static)
$contrast = $themeType.GetField('HighContrastOn', $static)
$saver = $markType.GetField('BatterySaverOn', $static)
$locked = $markType.GetField('SessionLockedOn', $static)
$reduce = $soft.GetField('ReduceMotionSetting', $static)
$animates.SetValue($null, [Said]::Answer($true))
$contrast.SetValue($null, [Said]::Answer($false))
$saver.SetValue($null, [Said]::Answer($false))
$locked.SetValue($null, [Said]::Answer($false))
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

# Watching: three breaths, then a sweep out and back in the last two slots of every loop.
$null = $follow.Invoke($mark, [object[]]@('monitoring'))
$out.watching = @{ state = (StateOf $mark); moving = (Moving $mark); interval = [int](Field $mark 'interval')
                   breath = (Walk $mark $window 0 (ConvertFrom-Json $env:CAR_BREATH_WALK))
                   turn = (Walk $mark $window 0 (ConvertFrom-Json $env:CAR_TURN_WALK)) }
# Every frame shown is the composed frame the rule asks for at that moment.
$checks = @()
foreach ($ms in @(0, 400, 1600, 2800, 9700, 12200, 13600, 14400, 15300)) {
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
foreach ($reason in @('reduce', 'animation', 'contrast', 'saver', 'locked', 'hidden')) {
    switch ($reason) {
        'reduce' { $reduce.SetValue($null, $true) }
        'animation' { $animates.SetValue($null, [Said]::Answer($false)) }
        'contrast' { $contrast.SetValue($null, [Said]::Answer($true)) }
        'saver' { $saver.SetValue($null, [Said]::Answer($true)) }
        'locked' { $locked.SetValue($null, [Said]::Answer($true)) }
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
        'locked' { $locked.SetValue($null, [Said]::Answer($false)) }
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

# Recovering and a failure turn all the time, paused is grey and still, attention breathes slowly (since v0.6.8).
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

# Hundreds of frames: the objects the process holds stay level. The step is a fortieth of recovering's 2.88 s sweep
# and the three samples are forty steps apart in multiples, so each is at the same point of it: where the head is
# home and lit the button shows the window's own icon and holds no frame of its own, so samples at different points
# of the sweep would differ by that one icon without anything having leaked.
$null = $follow.Invoke($mark, [object[]]@('recovering'))
$leak = @()
for ($i = 0; $i -lt 360; $i++) {
    [ProbeClock]::Now = 500000 + $i * 72
    $null = $animate.Invoke($mark, @())
    if ($i -eq 10 -or $i -eq 170 -or $i -eq 330) { $leak += ,@($i, [Icons]::Resources()) }
}
$out.leak = @{ at = $leak; baseline = $baseline; before = $before; distinct = 0 }

# A shutdown or restart that another program calls off, and a Restart Manager query that ends nothing: Windows asks
# (WM_QUERYENDSESSION, which WinForms raises FormClosing for) and then says the session goes on (WM_ENDSESSION, FALSE).
# The window stays open, and its button keeps following it - a pause turns it grey - and moving.
$out.sessionEnd = @()
foreach ($why in @(0, 1)) {                              # a shutdown; ENDSESSION_CLOSEAPP
    [ProbeClock]::Now = 550000 + $why * 10000
    $null = $follow.Invoke($mark, [object[]]@('monitoring'))
    $entry = @{ why = $why; before = (Moving $mark) }
    $entry.answer = [Icons]::Send($window, 0x11, 0, $why)
    $null = [Icons]::Send($window, 0x16, 0, $why)
    Pump 30
    $entry.open = [bool]($window.IsHandleCreated -and -not $window.IsDisposed -and $window.Visible)
    $entry.stopping = [bool](Field $mark 'closing')
    $entry.moving = (Moving $mark)
    [ProbeClock]::Now = 551000 + $why * 10000
    $null = $follow.Invoke($mark, [object[]]@('paused'))
    $entry.state = (StateOf $mark)
    $entry.walk = (Walk $mark $window (551000 + $why * 10000) (0..5 | ForEach-Object { $_ * 100 }))
    $entry.rest = (Expected $table 'idle' 0 5000 $false).pixels
    $null = $follow.Invoke($mark, [object[]]@('recovering'))
    $entry.again = @{ state = (StateOf $mark); moving = (Moving $mark) }
    $out.sessionEnd += ,$entry
}

# Closing: while the window is asked to close, and the close can still be called off, it carries on; once the window has
# closed the timer is stopped, and the window ends with its own icons and nothing of the mark's.
$closing = @{}
$window.add_FormClosing({ $closing.asked = (Moving $mark); $closing.askedStopping = [bool](Field $mark 'closing') })
$window.add_FormClosed({ $closing.moving = (Moving $mark); $closing.stopping = [bool](Field $mark 'closing')
                         $closing.big = [int64][Icons]::Big($window); $closing.small = [int64][Icons]::Small($window) })
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

# The window itself: what it reads tells the mark, and a window LayoutAudit builds makes none of its own.
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
        cls.snapshots, cls.snapshot_cases = cls.window_snapshots(time.time())
        for name, snapshot in cls.snapshots.items():
            (work / (name + ".json")).write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")
        cls.cases = window_cases()
        (work / "cases.json").write_text(json.dumps([{"name": case["name"], "status": case["status"],
                                                      "rows": case["rows"]} for case in cls.cases]), encoding="utf-8")
        probe = work / "taskbar.ps1"
        probe.write_text(PROBE, encoding="utf-8")
        cls.result = subprocess.run(
            [str(POWERSHELL), "-STA", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(probe)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900,
            env=dict(os.environ, CAR_EXE=str(exe), CAR_WORK=str(work), CAR_ICO=str(ICO), CAR_NOW=repr(NOW),
                     CAR_LIGHTS=json.dumps(LIGHTS), CAR_STATES=json.dumps(STATES), CAR_MOMENTS=json.dumps(MOMENTS),
                     CAR_SINCE=json.dumps(SINCE), CAR_SIZES=json.dumps(PROBE_SIZES), CAR_BIG_SIZES=json.dumps(BIG_SIZES),
                     CAR_COLOURS=json.dumps([list(colour) for colour in COLOURS]),
                     CAR_BREATH_WALK=json.dumps(list(BREATH_WALK)),
                     CAR_TURN_WALK=json.dumps(list(TURN_WALK)),
                     CAR_SNAPSHOTS=json.dumps(list(cls.snapshots))))
        answer = work / "result.json"
        cls.answer = (json.loads(answer.read_text(encoding="utf-8-sig"))
                      if cls.result.returncode == 0 and answer.is_file() else {})

    @staticmethod
    def window_snapshots(now):
        """Dashboard replies for watchers the window can see - each the control layer's own shapes (watcher_case) in the
        fullest reply the pages are drawn from - and the watchers themselves. Among them the last review's: a record
        being withdrawn, an older watcher owning the state, a watcher not ticking and an incompatible engine."""
        fullest = fullest_snapshot(now)
        watching = WATCHERS["watching"]
        waiting = stored(90, "waiting_reset", now, next_retry_at=now + 3600)
        due = stored(91, "waiting_poll", now, next_retry_at=now - 60)
        kinds = {record["state"]: record for record in pending_kinds(now) if record["state"] != "submitting"}
        watchers = [
            ("monitoring", [], watching, {}), ("waiting", [waiting], watching, {}),
            ("checking", [waiting, due], watching, {}), ("recovering", [waiting, kinds["turn_started"]], watching, {}),
            ("withdrawing", [kinds["withdrawn_unconfirmed"]], watching, {}),
            ("paused", [waiting], watching, {"enabled": False}), ("stopped", [], WATCHERS["not running"], {}),
            ("an older watcher", [waiting], watching, {"upgrade": True}),
            ("not ticking", [waiting], WATCHERS["not ticking"], {}),
            ("incompatible", [waiting], WATCHERS["an incompatible engine"], {}),
            ("unlisted, one sent", [waiting, kinds["queued"]], watching, {"listed": False}),
            ("again", [waiting], watching, {}),
        ]
        replies, cases = {}, {}
        for name, records, watcher, options in watchers:
            case = watcher_case(name, records, watcher=watcher, now=now, **options)
            value = copy.deepcopy(fullest)
            value["status"].update(copy.deepcopy(case["status"]))
            if case["rows"] is None:
                del value["pending"]
                value["pending_error"] = "The pending list could not be read"
            else:
                value["pending"] = copy.deepcopy(case["rows"])
            replies[name], cases[name] = value, case
        return replies, cases

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
                self.assertEqual(lights[light], for_light(light))
        self.assertEqual({lights[light] for light in brand.STATUS_FILL}, set(tray.ICON_STATES))

    def test_the_cases_are_every_kind_of_pending_record_and_every_watcher(self):
        kinds = pending_kinds()
        self.assertEqual({kind["state"] for kind in kinds}, machine.STATES - machine.TERMINAL)
        codes = {machine.public_code(kind) for kind in kinds}
        self.assertEqual(codes, set(machine.WAITING_CODES) | {"submission_claimed", "submitted", "withdrawing",
                                                               "turn_running", "turn_finishing"})
        self.assertEqual(len({case["name"] for case in self.cases}), len(self.cases))
        icons = {case["tray"] for case in self.cases if case["tray"] is not None}
        # "failed" since v0.6.8: a certain failure nobody has seen (window_cases' failure cases).
        self.assertEqual({opened for _, opened in icons}, {"watching", "recovering", "idle", "attention", "failed"})

    def test_every_watcher_the_window_can_see_is_the_tray_icon_s_state_for_it(self):
        """The icon's state by tray.py's own code, not a snapshot or an attention written here: the last round's test
        wrote the tray's side by hand, and the button, which followed the header light, parted from the icon for an
        upgrade, a watcher not ticking, an incompatible engine, a record held for one, and a record being withdrawn."""
        rows = {name: (light, word, icon) for name, light, word, icon in self.answer["window"]}
        self.assertEqual(len(rows), len(self.cases))
        for case in self.cases:
            with self.subTest(case=case["name"]):
                light, word, icon = rows[case["name"]]
                self.assertEqual(icon, for_light(word))
                self.assertEqual(icon, button_for(case))
                if case["tray"] is None:
                    self.assertEqual(icon, for_light(light), "no icon of this version: the header light's")

    def test_the_button_is_the_icon_with_its_popup_closed_except_where_the_open_popup_says_attention(self):
        """The icon reads whether a person must act only while its popup is open (tray.popup_attention); the window
        reads the watcher now, as the open popup does. So that is the one way the button can part from the icon with
        its popup closed - and it does, for the watchers the window's header light says need a person too."""
        parted = []
        for case in self.cases:
            if case["tray"] is None:
                continue
            closed, opened = case["tray"]
            with self.subTest(case=case["name"]):
                if opened != closed:
                    self.assertEqual(opened, "attention")
                    parted.append(case["name"])
        self.assertTrue(parted)
        for name in parted:
            self.assertTrue(name.startswith(("not ticking,", "an incompatible engine,", "watching, then ")), name)

    def test_the_last_review_s_watchers(self):
        rows = {name: (light, icon) for name, light, _, icon in self.answer["window"]}
        expected = {
            "watching, on, one withdrawing (withdrawn_unconfirmed), listed": "recovering",
            "watching, on, one withdrawing (withdrawn_unconfirmed), unlisted": "recovering",
            "an older watcher owns the state, watching, on": "attention",
            "an older watcher owns the state, not running, on": "idle",
            "not ticking, on, nothing pending, listed": "attention",
            "not ticking, paused, one waiting, unlisted": "attention",
            "an incompatible engine, on, nothing pending, listed": "attention",
            "an incompatible engine, on, one waiting, listed": "attention",
            "not running, on, one submitted (queued), listed": "idle",
            "not known to run, on, one waiting, listed": "idle",
            "watching, paused, one turn_running (turn_started), listed": "idle",
        }
        for name, icon in expected.items():
            with self.subTest(case=name):
                self.assertEqual(rows[name][1], icon)
        # The header light is the window's own and is unchanged: an older watcher needs a person, no watcher is grey.
        self.assertEqual(rows["an older watcher owns the state, watching, on"][0], "attention")
        self.assertEqual(rows["not running, on, one submitted (queued), listed"][0], "idle")

    # ---------------------------------------------------------------- the rhythm: the tray's own
    def test_every_frame_and_interval_is_the_tray_icon_s(self):
        """The frame and the interval are the icon's exactly. The sweep's angle is compared to a billionth of a
        degree rather than bit for bit: the CLR's Math.Cos and Python's can part in the last bits, and the position
        that angle draws - the picture anybody sees - is compared exactly."""
        rows = self.answer["frames"]
        self.assertEqual(len(rows), len(STATES) * len(MOMENTS) * len(SINCE) * 2)
        for state, ms, since, reduced, position, level, interval, turned in rows:
            entered = since if since >= 0 else None
            with self.subTest(state=state, ms=ms, since=since, reduced=reduced):
                self.assertEqual((position, level), tray.icon_frame(state, ms, entered, reduced=reduced))
                expected = tray.icon_frame_ms(state, ms, entered, reduced=reduced)
                self.assertEqual(interval, -1 if expected is None else expected)
                turn = tray.icon_turn(state, ms)
                if turn is None:
                    self.assertEqual(float(turned), -1.0)
                else:
                    self.assertAlmostEqual(float(turned), turn, places=9)

    def test_the_head_s_colours_are_the_tray_icon_s(self):
        for state in STATES:
            with self.subTest(state=state):
                self.assertEqual(tuple(self.answer["heads"][state]), tray.icon_head_colour(state))
        for state, level, colour in self.answer["levels"]:
            with self.subTest(state=state, level=level):
                self.assertEqual(tuple(colour), tray.icon_level_colour(tray.icon_head_colour(state), level))

    def test_any_one_reason_holds_it_still(self):
        """The icon's own rule (tray.icon_motion_allowed), a window that is not shown standing where the icon has
        the overflow flyout: the two surfaces stop for the same reasons, a locked session among them."""
        rows = self.answer["allowed"]
        self.assertEqual(len(rows), 64)
        for reduced, contrast, saver, locked, shown, frames, allowed in rows:
            with self.subTest(reduced=reduced, contrast=contrast, saver=saver, locked=locked, shown=shown, frames=frames):
                self.assertEqual(allowed, shown and frames and not (reduced or contrast or saver or locked))
                self.assertEqual(allowed, tray.icon_motion_allowed(reduced=reduced, contrast=contrast,
                                                                   battery_saver=saver, locked=locked,
                                                                   hidden=not shown, frames=frames))

    def test_the_session_is_windows_own_answer_read_where_windows_writes_it(self):
        """The user's rule holds the icon and the button alike still while the session is locked; the review found the
        button went on moving - and explorer.exe on redrawing it - behind the lock screen. TaskbarMark.SessionLocked
        asks Windows (WTSQuerySessionInformation, WTSSessionInfoEx). Read here as well, with the session's id, which
        the mark does not read, showing the fields are where both read them."""
        import ctypes
        from ctypes import wintypes
        wts, kernel32 = ctypes.WinDLL("wtsapi32"), ctypes.WinDLL("kernel32")
        wts.WTSQuerySessionInformationW.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.c_int,
                                                    ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.DWORD)]
        wts.WTSQuerySessionInformationW.restype = wintypes.BOOL
        wts.WTSFreeMemory.argtypes = [ctypes.c_void_p]
        buffer, size = ctypes.c_void_p(), wintypes.DWORD()
        self.assertTrue(wts.WTSQuerySessionInformationW(None, 0xFFFFFFFF, 25, ctypes.byref(buffer),
                                                        ctypes.byref(size)))
        try:
            level, _, session, state, flags = (ctypes.c_int32 * 5).from_address(buffer.value)
        finally:
            wts.WTSFreeMemory(buffer)
        mine = wintypes.DWORD()
        self.assertTrue(kernel32.ProcessIdToSessionId(os.getpid(), ctypes.byref(mine)))
        self.assertEqual((level, session), (1, mine.value))
        self.assertEqual(self.answer["sessionLocked"], flags == 0 or state == 4)

    # ---------------------------------------------------------------- the pixels: the tray's own
    def test_the_frames_are_the_tray_icon_s_own_pixels_at_every_big_icon_size(self):
        sizes = self.answer["sizes"]
        self.assertEqual(make_brand.MARK_SIZES, (32, 40, 48, 64))
        for size in PROBE_SIZES:
            with self.subTest(size=size):
                if size in make_brand.MARK_SIZES:
                    self.assertEqual(sizes[str(size)], tray_frames_digest(size))
                else:
                    self.assertEqual(sizes[str(size)], "", "no frames at a size the big icon is never")

    def test_there_are_frames_for_each_ico_entry_the_big_icon_is_up_to_300_percent_and_for_no_other_size(self):
        """The big icon is one of the .ico's own entries, never scaled: 175% (56 px) is its 48 px entry, and 225% to 300%
        its 64 px one. Frames at 56 px were never shown - about a quarter of Brand.Mark's text - and 225% to 300% do
        move. From 350% the big icon is the 128 px entry, which has no frames: the button keeps the window's own icon
        there, and is neither grey nor moving."""
        picked = {size: (width, height) for size, width, height in self.answer["picked"]}
        self.assertEqual(sorted(picked), sorted(BIG_SIZES))
        entries = {width for width, _ in picked.values()}
        self.assertLessEqual(entries, {16, 20, 24, 32, 40, 48, 64, 128, 256}, "the .ico's own entries")
        for width, height in picked.values():
            self.assertEqual(width, height)
        used = {picked[32 * scale // 100][0] for scale in SCALES if scale <= 300}
        self.assertEqual(set(make_brand.MARK_SIZES), used)
        self.assertEqual(picked[56][0], 48)
        for scale in SCALES:
            if scale > 300:
                with self.subTest(scale=scale):
                    self.assertNotIn(picked[32 * scale // 100][0], make_brand.MARK_SIZES)

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

    def test_watching_breathes_and_sweeps_on_the_big_icon_and_the_small_icon_never_changes(self):
        watching = self.answer["watching"]
        self.assertEqual(watching["state"], "watching")
        self.assertTrue(watching["moving"])
        self.assertEqual(watching["interval"], tray.ICON_MOTION["breathe_frame_ms"])
        breath, turn = watching["breath"], watching["turn"]
        # The breath: the head's brightness, in its place - a picture for each level the rule asks for over one
        # slot, the first and the last the window's own icon again at full brightness.
        self.assertEqual(len({row[2] for row in breath}), len({tray.icon_frame("watching", row[0]) for row in breath}))
        self.assertGreaterEqual(len({row[2] for row in breath}), 12)
        self.assertEqual(breath[0][1], self.answer["own"]["big"])
        self.assertEqual(breath[-1][1], self.answer["own"]["big"])
        self.assertTrue(all(row[5] for row in breath))
        # The sweep: the head travels at full brightness, a picture for each position the rule asks for, with the
        # quicker frames while it does - and the slot starts and ends on the window's own icon.
        sweep_at = brand.GLOW["monitoring_ms"] * tray.ICON_MOTION["breaths"]
        loop = brand.GLOW["monitoring_ms"] * (tray.ICON_MOTION["breaths"] + tray.ICON_MOTION["sweep_breaths"])
        frames = [tray.icon_frame("watching", row[0]) for row in turn]
        self.assertEqual({level for (_, level), row in zip(frames, turn) if sweep_at <= row[0] < loop},
                         {tray.ICON_MOTION["levels"] - 1})
        self.assertEqual(len({row[2] for row in turn}), len(set(frames)))
        self.assertGreaterEqual(len({row[2] for row in turn}), 20)
        self.assertIn(tray.ICON_MOTION["turn_frame_ms"], {row[6] for row in turn})
        for row, frame in zip(turn, frames):
            if frame == (0, tray.ICON_MOTION["levels"] - 1):
                self.assertEqual(row[1], self.answer["own"]["big"], "in its place at full brightness: its own icon")
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

    def test_recovering_keeps_sweeping(self):
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

    def test_a_failure_sweeps_on_the_big_icon_twice_as_quickly_as_recovering(self):
        """v0.6.8: red never holds still, and its head moves: recovering's sweep in half the time, on the turn's
        frame rate, for as long as the failure is shown - past the 1.4 s a one-time pulse used to last."""
        entry = self.answer["failed"]
        walk = entry["walk"]
        self.assertEqual(entry["state"], "failed")
        self.assertTrue(entry["moving"])
        self.assertEqual(entry["interval"], tray.ICON_MOTION["turn_frame_ms"])
        late = [row for row in walk if row[0] >= 1400]
        self.assertGreaterEqual(len({row[2] for row in late}), 4, "the head stopped moving")
        self.assertTrue(all(row[5] for row in walk), "the timer stopped")
        self.assertTrue(entry["movingAfter"])
        self.small_is_still(walk)

    def test_attention_breathes_slowly_for_as_long_as_it_lasts(self):
        """v0.6.8: amber breathes at home on brand's attention rhythm, the slowest, and keeps the breathing rate's
        timer; until then it pulsed once and held."""
        entry = self.answer["attention"]
        walk = entry["walk"]
        self.assertEqual(entry["state"], "attention")
        self.assertTrue(entry["moving"])
        self.assertEqual(entry["interval"], tray.ICON_MOTION["breathe_frame_ms"])
        late = [row for row in walk if row[0] >= 1400]
        self.assertGreaterEqual(len({row[2] for row in late}), 4, "it stopped breathing after one pulse")
        self.assertTrue(all(row[5] for row in walk), "the timer stopped")
        self.assertTrue(entry["movingAfter"])
        self.small_is_still(walk)

    def test_each_reason_holds_it_still_and_it_moves_again_when_the_reason_goes(self):
        own = self.answer["own"]
        for reason in ("reduce", "animation", "contrast", "saver", "locked", "hidden"):
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

    def test_a_shutdown_called_off_leaves_the_button_following_the_window(self):
        """WinForms raises FormClosing for WM_QUERYENDSESSION too. A shutdown another program calls off, or a Restart
        Manager query that ends nothing, leaves the window open (WM_ENDSESSION, FALSE): a mark that had stopped for
        good there kept its last frame, and ignored every state after, for the rest of the window's life."""
        entries = self.answer["sessionEnd"]
        self.assertEqual([entry["why"] for entry in entries], [0, 1])
        for entry in entries:
            with self.subTest(lparam=entry["why"]):
                self.assertTrue(entry["before"])
                self.assertEqual(entry["answer"], 1, "the window lets the session end")
                self.assertTrue(entry["open"], "and it goes on: the window is still open")
                self.assertFalse(entry["stopping"])
                self.assertTrue(entry["moving"], "the button still moves")
                self.assertEqual(entry["state"], "idle", "and follows the window: a pause is grey")
                self.assertEqual({row[2] for row in entry["walk"]}, {entry["rest"]})
                self.assertEqual(entry["again"], {"state": "recovering", "moving": True})
                self.small_is_still(entry["walk"])

    def test_closing_stops_the_timer_and_leaves_the_window_its_own_icons_and_nothing_of_the_mark_s(self):
        closing = self.answer["closing"]
        self.assertTrue(closing["asked"], "while the close can still be called off, the button carries on")
        self.assertFalse(closing["askedStopping"])
        self.assertFalse(closing["moving"], "no timer once the window has closed")
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
    def test_what_the_window_reads_tells_the_mark_the_tray_icon_s_state_for_that_watcher(self):
        self.assertTrue(self.answer["audited"], "a window LayoutAudit builds has no mark of its own")
        rows = {name: (dot, state, big) for name, dot, state, big in self.answer["wired"]}
        self.assertEqual(list(rows), list(self.snapshots))
        for name, case in self.snapshot_cases.items():
            with self.subTest(snapshot=name):
                self.assertEqual(rows[name][1], button_for(case))
        self.assertEqual({name: rows[name][1] for name in ("withdrawing", "an older watcher", "not ticking",
                                                           "incompatible", "unlisted, one sent", "stopped")},
                         {"withdrawing": "recovering", "an older watcher": "attention", "not ticking": "attention",
                          "incompatible": "attention", "unlisted, one sent": "recovering", "stopped": "idle"})
        # The header light is the window's own rule, as it was.
        lights = {"monitoring": "monitoring", "waiting": "waiting", "checking": "checking", "recovering": "recovering",
                  "paused": "paused", "stopped": "idle", "an older watcher": "attention", "not ticking": "attention",
                  "again": "waiting"}
        for name, light in lights.items():
            with self.subTest(light=name):
                self.assertEqual(rows[name][0], light)

    def test_the_window_makes_its_mark_only_with_its_own_icon_and_asks_it_again_every_second(self):
        settings = (GUI / "SettingsApp.cs").read_text(encoding="utf-8")
        dashboard = (GUI / "Dashboard.cs").read_text(encoding="utf-8")
        controls = (GUI / "Controls.cs").read_text(encoding="utf-8")
        block = settings[settings.index('string icon = Path.Combine(root, "codex-auto-resume.ico");'):]
        block = block[:block.index("catch (Exception)")]
        self.assertIn("Icon = new Icon(icon);", block)
        self.assertIn("if (catalog == null) taskbar = new TaskbarMark(this);", block)
        self.assertEqual(len(re.findall(r"new TaskbarMark\(", settings + dashboard)), 1)
        tick = dashboard[dashboard.index("clock.Tick += delegate"):]
        tick = tick[:tick.index("clock.Start();")]
        self.assertIn("if (taskbar != null) taskbar.Sync();", tick)
        # Told what the window read wherever its header light is told, and as seldom: the light itself tells the
        # button nothing, and with a snapshot on screen ApplyStatus decides neither (tests/test_gui_v063.py).
        self.assertNotIn("StateSet", settings + dashboard + controls)
        self.assertEqual((settings + dashboard).count("stateDot.State ="), 4)

        def method(source, signature):
            start = source.index(signature)
            return source[start:source.index("\n        }\n", start)]

        for source, signature in ((settings, "private void StatusUnavailable("),
                                  (settings, "private void ApplyStatus("),
                                  (dashboard, "private void MarkUnavailable("),
                                  (dashboard, "private void UpdateCountdowns(")):
            with self.subTest(method=signature):
                body = method(source, signature)
                self.assertEqual(body.count("stateDot.State ="), 1)
                self.assertEqual(body.count("TellTaskbar("), 1)
                self.assertLess(body.index("stateDot.State ="), body.index("TellTaskbar("))
        self.assertIn("if (snapshot == null) TellTaskbar(status, null, Now());",
                      method(settings, "private void ApplyStatus("))

    def test_the_window_takes_a_taskbar_identity_of_its_own_so_its_button_can_change(self):
        """v0.6.6. Everything above was true in v0.6.5 and the installed window's button still never moved.

        Measured here, on Windows 11: the published executable, byte for byte, moved the button from a scratch
        folder and did not move it from the installed one, where an instrumented build showed the window setting
        frame after frame (state=watching, allowed=True, interval 156 then 62) into a button that stayed
        pixel-identical for twenty-four seconds. What decides it is the location: Windows files an installed window
        under the application registered there and paints its button from that application's icon, which no window
        can change. A Start Menu shortcut alone does not do it - one written for a scratch folder, carrying the
        same identity and the same icon, left the button moving.

        So the window asks Windows to file it under an identity of its own, which nothing registers, and the button
        falls back to the icon the window itself sets. With that one call the same build moved 74 of 163 frames in
        the installed location. It is made before any window exists, which is the only time Windows accepts it, and
        it changes this process alone: notifications are raised by the watcher under the watcher's AUMID, which is
        what makes them attributable, and that is untouched.
        """
        from codex_auto_resume import startup

        settings = (GUI / "SettingsApp.cs").read_text(encoding="utf-8")
        self.assertIn("SetCurrentProcessExplicitAppUserModelID", settings)
        self.assertIn('SetCurrentProcessExplicitAppUserModelID("CodexAutoResume.Settings")', settings)
        # The window's identity is its own: sharing the watcher's would resolve to the installer's shortcut again.
        self.assertNotIn('SetCurrentProcessExplicitAppUserModelID("%s")' % startup.AUMID, settings)
        self.assertEqual(startup.AUMID, "CodexAutoResume.Watcher")
        main = settings[settings.index("internal static int Main(string[] argv)"):]
        main = main[:main.index("Application.Run(")]
        self.assertIn("TakeOwnTaskbarIdentity();", main)
        # Before any window is made, and before the first control decides anything about itself.
        self.assertLess(main.index("TakeOwnTaskbarIdentity();"), main.index("Application.EnableVisualStyles();"))
        self.assertEqual(settings.count("TakeOwnTaskbarIdentity()"), 2)         # declared once, called once
        claim = settings[settings.index("internal static void TakeOwnTaskbarIdentity()"):]
        claim = claim[:claim.index("\n        }\n")]
        self.assertIn("catch (Exception) { }", claim)                           # an older shell decides nothing


if __name__ == "__main__":
    unittest.main()
