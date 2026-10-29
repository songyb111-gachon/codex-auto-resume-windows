r"""v0.6.18's audit of the window (plans/v0620-audit/gui.md): the four REAL findings and the MINOR ones fixed with them.

R1. The one-shot bridge (Bridge.Call) read the child's stdout to its end, then its stderr, and only then waited 30 s for
    an exit that had already come: nothing limited it. A controlcli that hung held the call for good - and, run as the
    long-lived bridge's fallback inside its lock, every later call of the window behind it: the window painted on and
    every action stayed busy. A child that wrote more than a pipe holds to stderr first deadlocked both sides, and the
    window's close could not end the one-shot child. Now both streams are read at once, the argument is written on its
    own task, the call ends after a time limit with the child and what it started (ChildTree.End) - all but a
    pythonw.exe, the watcher, which is never ended - and the window's close ends every one-shot child on its way.
R2. With no words cached the window waited for them on its own thread before it existed, with no bound: no window, no
    taskbar button, and a second click a second invisible process. Now it waits StringsWaitMilliseconds, opens in
    English past it, and opens again in its own language once the words come (TakeLateWords).
R3. The manifest says per-monitor v2, and the window was drawn at the sign-in scale on every monitor and after a change
    of scaling. Now it is drawn at the scale of the monitor it opens on, and opens again at the next one's when it is
    moved there (WM_DPICHANGED, CheckScale).
R4. KeepOnScreen measured the primary screen while CenterScreen put the window on the pointer's. Now both are the
    screen it opens on (OpeningScreen).
M1. Three failures gave the long-lived bridge up for the window's life; it is tried again after RetryMilliseconds.

The built half compiles the real window and runs it against a stand-in python.exe this test compiles, whose behaviour
CAR_FAKE_MODE says; every process the stand-in starts is written down, and whatever of them still runs at the end is
ended by its path, inside the test's own folder. Nothing of the real installation is read, nothing is shown.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import guiscan
from test_gui_v0611_access import CSC, NO_WINDOW, POWERSHELL, compile_window, run_probe


def body(type_name: str, member: str) -> str:
    return guiscan.member_body(type_name, member)


# A stand-in for the installation's python.exe. `[-X OPTION ...] -c CODE APP_SRC serve` answers one request a line; `-c CODE APP_SRC
# COMMAND [-]` answers once. CAR_FAKE_MODE: ok answers {"ok":true,"echo":COMMAND,"took":LENGTH-OF-ARGUMENT}; hang
# does not answer for two minutes (CAR_FAKE_HANG_MS), every process it starts alike; flood writes 300 KB to stderr
# before it reads its stdin, then answers; tree starts a python.exe that keeps its stdout and a pythonw.exe of its own, and ends without a word; slow answers strings in Korean after 3 s.
# Every process writes "role pid" to CAR_FAKE_PIDS.
FAKE = r"""
using System;
using System.Diagnostics;
using System.IO;
using System.Text.RegularExpressions;
using System.Threading;
static class Fake {
    static void Note(string role) {
        string pids = Environment.GetEnvironmentVariable("CAR_FAKE_PIDS");
        if (!string.IsNullOrEmpty(pids))
            for (int i = 0; i < 50; i++) {
                try { File.AppendAllText(pids, role + " " + Process.GetCurrentProcess().Id + "\n"); return; }
                catch (IOException) { Thread.Sleep(20); }
            }
    }
    // "Never answers", for as long as a test can need it - never for ever: a stand-in nothing ends (the watcher's) ends
    // itself, so a test that could not end it still finishes (CAR_FAKE_HANG_MS, two minutes unless a test says less).
    static int HangMs() {
        int ms;
        return int.TryParse(Environment.GetEnvironmentVariable("CAR_FAKE_HANG_MS"), out ms) && ms > 0 ? ms : 120000;
    }
    static string Answer(string mode, string command, string argument) {
        if (mode == "slow") {
            Thread.Sleep(3000);
            return "{\"ok\":true,\"language\":\"ko\",\"preference\":\"system\",\"system_language\":\"ko\",\"strings\":{\"nav.settings\":\"\\uc124\\uc815\"}}";
        }
        return "{\"ok\":true,\"echo\":\"" + command + "\",\"took\":" + argument.Length + "}";
    }
    static Process Start(string exe, string role, bool keepOutput) {
        var info = new ProcessStartInfo(exe, "--hang " + role);
        info.UseShellExecute = false;
        info.CreateNoWindow = true;
        info.RedirectStandardInput = true;
        if (!keepOutput) { info.RedirectStandardOutput = true; info.RedirectStandardError = true; }
        return Process.Start(info);
    }
    static int Main(string[] args) {
        if (args.Length > 0 && args[0] == "--hang") { Note(args[1]); Thread.Sleep(HangMs()); return 0; }
        // The interpreter's own options come first (-X disable-remote-debug, v0.6.19-beta.3), as python.exe reads them.
        int options = 0;
        while (options + 1 < args.Length && args[options] == "-X") options += 2;
        if (options > 0) { var rest = new string[args.Length - options]; Array.Copy(args, options, rest, 0, rest.Length); args = rest; }
        string mode = Environment.GetEnvironmentVariable("CAR_FAKE_MODE") ?? "ok";
        string command = args.Length > 3 ? args[3] : "";
        Note((command == "serve" ? "serve-" : "child-") + mode);
        if (mode == "hang") { Thread.Sleep(HangMs()); return 0; }
        if (command != "serve") {
            if (mode == "tree") {
                string self = Process.GetCurrentProcess().MainModule.FileName;
                Start(self, "grandchild", true);
                Start(Path.Combine(Path.GetDirectoryName(self), "pythonw.exe"), "watcher", false);
                Thread.Sleep(300);
                return 0;
            }
            if (mode == "flood") { Console.Error.Write(new string('x', 300 * 1024)); Console.Error.Flush(); }
            string argument = args.Length > 4 && args[4] == "-" ? Console.In.ReadToEnd() : "";
            Console.Out.Write(Answer(mode, command, argument));
            return 0;
        }
        string line;
        while ((line = Console.In.ReadLine()) != null) {
            string id = Regex.Match(line, "\"id\":(\\d+)").Groups[1].Value;
            string name = Regex.Match(line, "\"command\":\"([a-z_-]+)\"").Groups[1].Value;
            Console.Out.Write("{\"id\":" + id + ",\"reply\":" + Answer(mode, name, "") + "}\n");
            Console.Out.Flush();
        }
        return 0;
    }
}
"""

PROBE = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Windows.Forms
[Windows.Forms.Application]::EnableVisualStyles()
[Windows.Forms.Application]::SetCompatibleTextRenderingDefault($false)
$assembly = [Reflection.Assembly]::LoadFile($env:CAR_EXE)
$flags = [Reflection.BindingFlags]'Instance,Static,NonPublic,Public'
$F = $assembly.GetType('CodexAutoResume.SettingsForm', $true)
$BT = $assembly.GetType('CodexAutoResume.Bridge', $true)
$PB = $assembly.GetType('CodexAutoResume.PersistentBridge', $true)
$work = [string]$env:CAR_WORK
$home_ = [string]$env:CAR_HOME
$pids = [string]$env:CAR_FAKE_PIDS
$utf8 = New-Object Text.UTF8Encoding $false
$out = @{}

function Listed {
    $list = @()
    if (Test-Path $pids) { foreach ($line in [IO.File]::ReadAllLines($pids)) { $p = $line.Split(' '); $list += ,@($p[0], [int]$p[1]) } }
    return ,$list
}
function Alive([int]$id) {
    $p = Get-Process -Id $id -ErrorAction SilentlyContinue
    return ($p -ne $null -and $p.Path -ne $null -and $p.Path.StartsWith($home_, [StringComparison]::OrdinalIgnoreCase))
}
function Roles-Alive {
    $alive = @{}
    foreach ($entry in (Listed)) { $alive[$entry[0]] = (Alive $entry[1]) }
    return $alive
}
function End-Ours {
    foreach ($entry in (Listed)) { if (Alive $entry[1]) { Stop-Process -Id $entry[1] -Force -ErrorAction SilentlyContinue } }
    Start-Sleep -Milliseconds 300
    if (Test-Path $pids) { Remove-Item $pids }
}

# ------------------------------------------------------------------ R1: the one-shot bridge, alone
$once = $BT.GetConstructors($flags)[0].Invoke([object[]]@($home_))
$call = $BT.GetMethod('Call', $flags, $null, [type[]]@([string], [string], [int]), $null)
function Timed([string]$mode, [string]$argument, [int]$limit) {
    $env:CAR_FAKE_MODE = $mode
    $clock = [Diagnostics.Stopwatch]::StartNew()
    $result = @{}
    try {
        $reply = $call.Invoke($once, [object[]]@('status', $argument, $limit))
        $result.ok = $true
        $result.echo = [string]$reply['echo']
        $result.took = [int]$reply['took']
    } catch {
        $result.ok = $false
        $result.error = $_.Exception.InnerException.GetType().Name
    }
    $result.ms = [int]$clock.ElapsedMilliseconds
    Start-Sleep -Milliseconds 600
    $result.alive = (Roles-Alive)
    End-Ours
    return $result
}
$out.ok = Timed 'ok' '{"a":1}' 20000
$out.hang = Timed 'hang' '' 2000
# 200 KB of argument, which the child reads only after it has written 300 KB to stderr.
$out.flood = Timed 'flood' ('{"text":"' + ('y' * (200 * 1024)) + '"}') 20000
$out.tree = Timed 'tree' '' 2500
$out.limits = @([int]$BT.GetField('CallMilliseconds', $flags).GetValue($null), [int]$BT.GetField('LongCallMilliseconds', $flags).GetValue($null))

# ------------------------------------------------------------------ R2 and the close: a window whose words do not come
$F.GetField('StringsWaitMilliseconds', $flags).SetValue($null, [int]1500)
$PB.GetField('RetryMilliseconds', $flags).SetValue($null, [int]600000)
function New-Window([string]$mode) {
    $env:CAR_FAKE_MODE = $mode
    $script:oneShot = $BT.GetConstructors($flags)[0].Invoke([object[]]@($home_))
    $script:bridge = $PB.GetConstructors($flags)[0].Invoke([object[]]@($home_, $script:oneShot))
    # Given up already, so the words are asked of the one-shot bridge at once.
    $PB.GetField('failures', $flags).SetValue($script:bridge, [int]3)
    $PB.GetField('givenUp', $flags).GetValue($script:bridge).Start()
    $one = @($F.GetConstructors($flags) | Where-Object { $_.GetParameters().Count -eq 1 })[0]
    $clock = [Diagnostics.Stopwatch]::StartNew()
    $window = $one.Invoke([object[]]@($script:bridge))
    $script:made = [int]$clock.ElapsedMilliseconds
    return $window
}
$window = New-Window 'hang'
$stuck = @{ made = $made; late = [bool]$F.GetField('lateWords', $flags).GetValue($window)
            running = [int]$BT.GetProperty('Running', $flags).GetValue($oneShot)
            words = [int]$F.GetField('strings', $flags).GetValue($window).Count }
Start-Sleep -Milliseconds 300
$stuck.before = (Roles-Alive)
$clock = [Diagnostics.Stopwatch]::StartNew()
$PB.GetMethod('Stop', $flags).Invoke($bridge, @())
$stuck.stopMs = [int]$clock.ElapsedMilliseconds
Start-Sleep -Milliseconds 800
$stuck.after = (Roles-Alive)
$window.Dispose()
End-Ours
$out.stuck = $stuck

# Words that come after the window opened: kept to open it again in them.
$window = New-Window 'slow'
$null = $window.Handle
$late = @{ made = $made; openedBefore = [string]$F.GetField('openedLanguage', $flags).GetValue($window) }
$clock = [Diagnostics.Stopwatch]::StartNew()
while ($clock.ElapsedMilliseconds -lt 15000 -and [bool]$F.GetField('lateWords', $flags).GetValue($window)) {
    [Windows.Forms.Application]::DoEvents()
    Start-Sleep -Milliseconds 50
}
$late.openedAfter = [string]$F.GetField('openedLanguage', $flags).GetValue($window)
$late.marker = [string]$F.GetField('LateLanguage', $flags).GetValue($null)
$PB.GetMethod('Stop', $flags).Invoke($bridge, @())
$window.Dispose()
End-Ours
$out.late = $late

# ------------------------------------------------------------------ M1: given up, then tried again
$env:CAR_FAKE_MODE = 'ok'
$oneShot = $BT.GetConstructors($flags)[0].Invoke([object[]]@($home_))
$bridge = $PB.GetConstructors($flags)[0].Invoke([object[]]@($home_, $oneShot))
$PB.GetField('failures', $flags).SetValue($bridge, [int]3)
$PB.GetField('givenUp', $flags).GetValue($bridge).Start()
$PB.GetField('RetryMilliseconds', $flags).SetValue($null, [int]600000)
$null = $PB.GetMethod('Call', $flags).Invoke($bridge, [object[]]@('status', $null))
$retry = @{ heldBack = [bool]$PB.GetProperty('GivenUp', $flags).GetValue($bridge); servedBefore = @((Listed) | Where-Object { $_[0] -eq 'serve-ok' }).Count }
$PB.GetField('RetryMilliseconds', $flags).SetValue($null, [int]0)
$null = $PB.GetMethod('Call', $flags).Invoke($bridge, [object[]]@('status', $null))
$retry.after = [bool]$PB.GetProperty('GivenUp', $flags).GetValue($bridge)
$retry.served = @((Listed) | Where-Object { $_[0] -eq 'serve-ok' }).Count
$PB.GetMethod('Stop', $flags).Invoke($bridge, @())
End-Ours
$out.retry = $retry

# ------------------------------------------------------------------ R3 and R4: the pure rules
$decide = $F.GetMethod('ScaleDecision', $flags)
$out.scaleDecisions = @()
foreach ($case in @(@(1.0, 1.0, $false), @(1.5, 1.5, $true), @(2.0, 1.0, $false), @(1.0, 2.0, $true), @(1.25, 0.0, $false), @(1.0, 1.001, $false))) {
    $out.scaleDecisions += [int]$decide.Invoke($null, [object[]]@([double]$case[0], [double]$case[1], [bool]$case[2]))
}
$codes = @{ keep = [int]$F.GetField('KeepWindow', $flags).GetValue($null); reopen = [int]$F.GetField('ReopenWindow', $flags).GetValue($null)
            once = [int]$F.GetField('ReopenOnceSaved', $flags).GetValue($null) }
$out.codes = $codes
$scaled = $F.GetMethod('ScaledBounds', $flags).Invoke($null, [object[]]@([Drawing.Rectangle]::new(100, 50, 1022, 720), [double]1.0, [double]2.0))
$out.scaled = @($scaled.X, $scaled.Y, $scaled.Width, $scaled.Height)
$scaled = $F.GetMethod('ScaledBounds', $flags).Invoke($null, [object[]]@([Drawing.Rectangle]::new(-1900, 10, 1522, 1052), [double]1.5, [double]1.0))
$out.scaledDown = @($scaled.X, $scaled.Y, $scaled.Width, $scaled.Height)
$center = $F.GetMethod('CenterOn', $flags)
$out.centred = @()
foreach ($case in @(@(0, 0, 2560, 1400, 1022, 720), @(2560, 300, 1366, 728, 1022, 720), @(-1080, -200, 1080, 1880, 1522, 2000))) {
    $p = $center.Invoke($null, [object[]]@([Drawing.Rectangle]::new($case[0], $case[1], $case[2], $case[3]), [Drawing.Size]::new($case[4], $case[5])))
    $out.centred += ,@($p.X, $p.Y)
}
$requestType = $assembly.GetType('CodexAutoResume.OpenRequest', $true)
$request = [Activator]::CreateInstance($requestType, $true)
$place = $F.GetMethod('OpeningPlace', $flags)
$p = $place.Invoke($null, [object[]]@($request, [Drawing.Point]::new(3000, 400)))
$out.placePointer = @($p.X, $p.Y, $p.Width, $p.Height)
$requestType.GetField('HasBounds', $flags).SetValue($request, $true)
$requestType.GetField('Bounds', $flags).SetValue($request, [Drawing.Rectangle]::new(-1500, 20, 900, 600))
$p = $place.Invoke($null, [object[]]@($request, [Drawing.Point]::new(3000, 400)))
$out.placeBounds = @($p.X, $p.Y, $p.Width, $p.Height)
# A monitor of twice the sign-in scale: every pixel and every point twice as large, and back.
$system = [double]$F.GetField('SystemScale', $flags).GetValue($null)
$adopt = $F.GetMethod('AdoptDisplayScale', $flags)
$null = $adopt.Invoke($null, [object[]]@([double]($system * 2)))
$font = [Drawing.Font]::new('Segoe UI', [single]9)
$out.doubled = @(([double]$F.GetProperty('DpiScale', $flags).GetValue($null, $null) / $system),
                 [double]$F.GetMethod('AtDisplayScale', $flags).Invoke($null, [object[]]@($font)).SizeInPoints)
$null = $adopt.Invoke($null, [object[]]@($system))
$out.restored = @(([double]$F.GetProperty('DpiScale', $flags).GetValue($null, $null) / $system),
                  [double]$F.GetMethod('AtDisplayScale', $flags).Invoke($null, [object[]]@($font)).SizeInPoints)
$primary = [Windows.Forms.Screen]::PrimaryScreen.Bounds
$out.monitorScale = [double]$F.GetMethod('ScaleOfMonitor', $flags).Invoke($null, [object[]]@($primary))

[IO.File]::WriteAllText((Join-Path $work 'result.json'), (ConvertTo-Json $out -Compress -Depth 6), $utf8)
"""


class SourceTests(unittest.TestCase):
    """What the built half cannot see without a second monitor or a stuck interpreter of its own."""

    def test_the_one_shot_reads_both_streams_at_once_and_has_a_time_limit(self):
        call = guiscan.type_body("Bridge")
        self.assertIn("process.StandardOutput.ReadToEndAsync()", call)
        self.assertIn("process.StandardError.ReadToEndAsync()", call)
        self.assertNotIn("process.StandardOutput.ReadToEnd()", call)
        self.assertNotIn("WaitForExit(30000)", call)
        self.assertIn("ChildTree.End(process);", call)

    def test_the_watcher_is_never_ended(self):
        tree = guiscan.type_body("ChildTree")
        self.assertIn('internal const string Spared = "pythonw.exe";', tree)
        self.assertIn("string.Equals(one.Image, Spared, StringComparison.OrdinalIgnoreCase)", body("ChildTree", "Under"))

    def test_the_window_s_close_ends_the_one_shot_children(self):
        self.assertIn("once.Stop();", body("PersistentBridge", "Stop"))
        self.assertIn("try { return once.Call(command, argument, Bridge.LongCallMilliseconds); }",
                      guiscan.type_body("PersistentBridge"))

    def test_the_words_are_waited_for_with_a_bound(self):
        source = guiscan.settings()
        wait = source.find("if (asking.Wait(Math.Max(0, StringsWaitMilliseconds)))")
        self.assertGreater(wait, 0, "the constructor waits for the words with no bound")
        self.assertEqual(source.count("asking.Result"), 1)
        self.assertLess(wait, source.index("asking.Result"), "the result is read only once the bounded wait says it came")

    def test_a_change_of_monitor_scale_is_heard(self):
        handler = body("SettingsForm", "WndProc")
        self.assertIn("m.Msg == WM_DPICHANGED", handler)
        before = handler.index("m.Msg == WM_DPICHANGED")
        self.assertLess(before, handler.index("base.WndProc(ref m);"),
                        "WM_DPICHANGED is taken before .NET's own handling, which scales the fonts alone")
        self.assertIn("WM_EXITSIZEMOVE", handler)
        self.assertIn("Reopen(false);", body("SettingsForm", "CheckScale"))
        self.assertIn("if (recheckScale) CheckScale();", body("SettingsForm", "TickReopen"))

    def test_the_window_is_drawn_at_the_scale_of_the_monitor_it_opens_on(self):
        main = body("Program", "Main")
        adopt = main.index("SettingsForm.AdoptDisplayScale(SettingsForm.ScaleOfMonitor(")
        self.assertLess(adopt, main.index("SettingsForm.AdoptTextSize("), "the text size is fitted at the monitor's scale")
        self.assertIn("dpiScale = displayScale * TextSize;", body("SettingsForm", "AdoptTextSize"))
        self.assertIn("AtDisplayScale(TextScale.Apply(SystemFonts.MessageBoxFont", guiscan.settings())
        self.assertIn("SettingsForm.AdoptDisplayScale(", body("SettingsRemove", "Look"))

    def test_keep_on_screen_measures_the_screen_the_window_opens_on(self):
        keep = "\n".join(line for line in body("SettingsForm", "KeepOnScreen").splitlines()
                         if not line.lstrip().startswith("//"))
        # The screen it opens on; Screen.FromControl (the primary) only for a window the audit builds, never shown.
        self.assertIn("Rectangle screen = (opening ?? Screen.FromControl(this)).WorkingArea;", keep)
        constructor = guiscan.settings()
        self.assertLess(constructor.index("if (catalog == null) opening = OpeningScreen(request);"),
                        constructor.index("            KeepOnScreen();"))
        self.assertNotIn("Screen.FromPoint(Cursor.Position).WorkingArea.Size", body("Program", "Main"))


class MinorTests(unittest.TestCase):
    """M2 and M5 of the audit, which change no behaviour a probe could tell apart in the time a test has. M4 (a Region
    replaced without disposing it, SoftPin.Cut) was not a finding: Windows Forms' Control.Region setter disposes the
    region it replaces (its IL calls Region.Dispose, read 2026-10-22), so Cut is left as it was."""

    def test_the_log_dialog_s_five_second_look_waits_while_one_is_on_its_way(self):
        tools = guiscan.read("gui/DashboardTools.cs")
        self.assertIn("if (lookingAgain && looking > 0) return;", tools)
        self.assertIn("looking = Math.Max(0, looking - 1);", tools)

    def test_the_installer_bar_tells_a_screen_reader_it_moved(self):
        show = body("InstallerBar", "Show")
        self.assertIn("AccessibilityNotifyClients(AccessibleEvents.ValueChange, -1);", show)
        self.assertIn("AccessibilityNotifyClients(AccessibleEvents.DescriptionChange, -1);", show)


@unittest.skipUnless(os.name == "nt" and CSC.is_file() and POWERSHELL.is_file(),
                     "needs the in-box C# compiler and Windows PowerShell")
class BuiltTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        # Resolved: on a runner whose TEMP is an 8.3 short name, the stand-ins' own paths are the long ones, and the
        # cleanup below - which ends what the stand-in started by its path inside this folder - matched nothing.
        work = Path(cls.folder.name).resolve()
        cls.home = work / "home"
        (cls.home / "runtime").mkdir(parents=True)
        (cls.home / "app" / "src").mkdir(parents=True)
        exe = compile_window(work)
        source = work / "fake.cs"
        source.write_text(FAKE, encoding="utf-8")
        for name in ("python.exe", "pythonw.exe"):
            subprocess.run([str(CSC), "/nologo", "/target:exe", "/out:" + str(cls.home / "runtime" / name), str(source)],
                           check=True, capture_output=True, timeout=300, creationflags=NO_WINDOW)
        cls.pids = work / "pids.txt"
        try:
            cls.answer = run_probe(PROBE, work, 300, CAR_EXE=str(exe), CAR_HOME=str(cls.home), CAR_FAKE_PIDS=str(cls.pids))
        finally:
            cls.end_ours()

    @classmethod
    def end_ours(cls):
        """Whatever the stand-in started and still runs, by its path inside this test's folder."""
        script = ("Get-Process -Name python,pythonw -ErrorAction SilentlyContinue | Where-Object { $_.Path -and "
                  "$_.Path.StartsWith($env:CAR_HOME, [StringComparison]::OrdinalIgnoreCase) } | Stop-Process -Force")
        subprocess.run([str(POWERSHELL), "-NoProfile", "-NonInteractive", "-Command", script], capture_output=True,
                       timeout=120, creationflags=NO_WINDOW, env=dict(os.environ, CAR_HOME=str(cls.home)))

    @classmethod
    def tearDownClass(cls):
        cls.end_ours()
        cls.folder.cleanup()

    def test_an_answer_comes_back_as_before(self):
        self.assertEqual({k: self.answer["ok"][k] for k in ("ok", "echo", "took")}, {"ok": True, "echo": "status", "took": 7})

    def test_a_child_that_never_answers_is_ended_at_the_limit(self):
        hang = self.answer["hang"]
        self.assertFalse(hang["ok"])
        self.assertEqual(hang["error"], "TimeoutException")
        self.assertGreaterEqual(hang["ms"], 1900)
        self.assertLess(hang["ms"], 8000, "the call outlasted its limit")
        self.assertEqual(hang["alive"], {"child-hang": False}, "the child was left running")

    def test_a_child_that_floods_stderr_before_reading_its_argument_still_answers(self):
        flood = self.answer["flood"]
        self.assertTrue(flood["ok"], flood)
        self.assertEqual(flood["took"], 200 * 1024 + len('{"text":""}'))

    def test_a_grandchild_holding_the_output_is_ended_and_the_watcher_is_spared(self):
        tree = self.answer["tree"]
        self.assertFalse(tree["ok"])
        self.assertEqual(tree["error"], "TimeoutException")
        self.assertLess(tree["ms"], 8000)
        self.assertEqual(tree["alive"], {"child-tree": False, "grandchild": False, "watcher": True},
                         "the grandchild that kept the stdout must end, a pythonw.exe (the watcher) never")

    def test_the_limits(self):
        self.assertEqual(self.answer["limits"], [60000, 180000])

    def test_a_window_whose_words_do_not_come_opens_anyway(self):
        stuck = self.answer["stuck"]
        self.assertLess(stuck["made"], 6000, "the window waited for its words past the bound")
        self.assertTrue(stuck["late"])
        self.assertEqual(stuck["words"], 0, "it opens in its own English words")
        self.assertEqual(stuck["running"], 1, "the words are still on their way, on the one-shot bridge")
        self.assertEqual(stuck["before"], {"child-hang": True})

    def test_the_window_s_close_ends_the_one_shot_child(self):
        stuck = self.answer["stuck"]
        self.assertLess(stuck["stopMs"], 2000, "the close waited")
        self.assertEqual(stuck["after"], {"child-hang": False}, "the one-shot child outlived the window")

    def test_words_that_come_late_open_the_window_again_in_its_language(self):
        late = self.answer["late"]
        self.assertLess(late["made"], 3000)
        self.assertEqual(late["openedBefore"], "")
        self.assertEqual(late["openedAfter"], late["marker"],
                         "Korean words came after the window opened in English: it must open again in them")

    def test_a_given_up_bridge_is_tried_again_after_the_back_off(self):
        retry = self.answer["retry"]
        self.assertTrue(retry["heldBack"], "tried again before the back-off")
        self.assertEqual(retry["servedBefore"], 0)
        self.assertFalse(retry["after"], "not tried again once the back-off passed")
        self.assertEqual(retry["served"], 1)

    def test_a_monitor_of_another_scale_reopens_the_window_unless_edits_are_unsaved(self):
        codes = self.answer["codes"]
        self.assertEqual(self.answer["scaleDecisions"],
                         [codes["keep"], codes["keep"], codes["reopen"], codes["once"], codes["keep"], codes["keep"]])

    def test_a_reopen_for_another_scale_keeps_the_size_one_sees(self):
        self.assertEqual(self.answer["scaled"], [100, 50, 2044, 1440])
        self.assertEqual(self.answer["scaledDown"], [-1900, 10, 1015, 701])

    def test_the_window_is_centred_on_the_screen_it_opens_on(self):
        self.assertEqual(self.answer["centred"], [[769, 340], [2732, 304], [-1080, -200]])

    def test_the_opening_place_is_a_reopen_s_bounds_or_the_pointer(self):
        self.assertEqual(self.answer["placePointer"], [3000, 400, 1, 1])
        self.assertEqual(self.answer["placeBounds"], [-1500, 20, 900, 600])

    def test_a_monitor_s_scale_draws_pixels_and_points_alike(self):
        self.assertEqual(self.answer["doubled"], [2.0, 18.0])
        self.assertEqual(self.answer["restored"], [1.0, 9.0])
        self.assertGreaterEqual(self.answer["monitorScale"], 1.0)


if __name__ == "__main__":
    unittest.main()
