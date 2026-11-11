r"""Diagnostics' watcher button follows the watcher's state, both ways (v0.6.20 final, the live re-check's finding 4).

With the watcher stopped, Diagnostics still offered "Stop watcher" while the header offered "Start watcher" (and that one
worked). The one button there is the header's twin now: from the status the header's Start reads (ApplyStatus), it says
Stop watcher while the watcher runs - or is not known to - and Start watcher while it is stopped, and it is greyed while an
action or the start is in flight, as the header's is, with the header's light the working one for whatever is in flight
(the owner's rule of v0.6.20: every in-progress state shows as in progress; BusyLight, StartWatcher).

The real compiled window is built in the probe's own process as test_gui_v065_rows builds it - a bridge rooted where nothing
is, a window far off the screen that is never shown on anyone's desktop. Nothing here presses the button: Start watcher
would ask the bridge to start a watcher.

    python -m unittest tests.test_gui_diagnostics_watcher_button       (a GUI module: gui_lock.sh)
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
LOCALES = ("en", "ko")

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
$systemScale = [double]$form.GetField('SystemScale', $static).GetValue($null)
$form.GetField('dpiScale', $static).SetValue($null, [double]1.0)
$factor = [single](1.0 / $systemScale)
$box = [Drawing.SystemFonts]::MessageBoxFont
[Drawing.Font]$font = New-Object Drawing.Font $box.FontFamily, ($box.SizeInPoints * $factor), $box.Style, ([Drawing.GraphicsUnit]::Point)
$nowhere = [string](Join-Path $work 'nowhere')
$bridgeType = $assembly.GetType('CodexAutoResume.Bridge', $true)
$persistentType = $assembly.GetType('CodexAutoResume.PersistentBridge', $true)
$three = @($form.GetConstructors($instance) | Where-Object { $_.GetParameters().Count -eq 3 })[0]
$out = @{}
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
    $startButton = Get-Field $window 'startButton'
    $dot = Get-Field $window 'stateDot'
    $state = $dot.GetType().GetProperty('State', $instance)
    # The Diagnostics page is built when it is first shown: the button is read after that.
    function Look([string]$name) {
        Pump 40
        $stopButton = Get-Field $window 'stopButton'
        return @{ name = $name; text = [string]$stopButton.Text; enabled = [bool]$stopButton.Enabled
                  start = [bool]$startButton.Visible; startEnabled = [bool]$startButton.Enabled
                  light = [string]$state.GetValue($dot, $null) }
    }
    $steps = @()
    Invoke-Window $window 'ApplySnapshot' @((Read-Json 'running.json'))
    $null = Invoke-Window $window 'ShowPage' @('diagnostics')
    $window.Visible = $true
    $frame.Show()
    Pump 100
    $steps += ,(Look 'running')
    Invoke-Window $window 'ApplySnapshot' @((Read-Json 'stopped.json'))
    $steps += ,(Look 'stopped')
    # An action in flight while it is stopped: both buttons wait.
    $null = Invoke-Window $window 'SetBusy' @($true)
    $steps += ,(Look 'stopped, busy')
    $null = Invoke-Window $window 'SetBusy' @($false)
    $steps += ,(Look 'stopped, idle again')
    # The start in flight (StartWatcher sets it; nothing here starts one).
    $form.GetField('starting', $instance).SetValue($window, $true)
    $null = Invoke-Window $window 'UpdateWatcherButton' @()
    $steps += ,(Look 'stopped, starting')
    $form.GetField('starting', $instance).SetValue($window, $false)
    $null = Invoke-Window $window 'UpdateWatcherButton' @()
    Invoke-Window $window 'ApplySnapshot' @((Read-Json 'running.json'))
    $steps += ,(Look 'running again')
    # An action in flight while it runs: the button waits, and the header's light is the working one.
    $null = Invoke-Window $window 'SetBusy' @($true)
    $steps += ,(Look 'running, busy')
    $null = Invoke-Window $window 'SetBusy' @($false)
    $steps += ,(Look 'running, idle again')
    $out[$locale] = $steps
    $frame.Close()
    $frame.Dispose()
}
[IO.File]::WriteAllText((Join-Path $work 'result.json'), ($out | ConvertTo-Json -Depth 6 -Compress), $utf8)
[GC]::Collect()
[GC]::WaitForPendingFinalizers()
[Environment]::Exit(0)
"""


@unittest.skipUnless(CSC.is_file() and POWERSHELL.is_file(), "needs the in-box compiler and PowerShell")
class WatcherButtonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        work = Path(cls.folder.name)
        exe = work / "CodexAutoResumeSettings.exe"
        subprocess.run([str(CSC), "/nologo", "/target:winexe", "/platform:x64", "/out:" + str(exe),
                        "/reference:System.dll", "/reference:System.Drawing.dll", "/reference:System.Windows.Forms.dll",
                        *[str(path) for path in guiscan.sources()]],
                       check=True, capture_output=True, timeout=300)
        cls.catalogs = {}
        for locale in LOCALES:
            cls.catalogs[locale] = l10n.catalog(locale)
            reply = {"ok": True, "language": locale, "strings": cls.catalogs[locale], "endonyms": dict(l10n.ENDONYMS),
                     "preference": locale, "system_language": locale}
            (work / ("strings-%s.json" % locale)).write_text(json.dumps(reply, ensure_ascii=False), encoding="utf-8")
        running = fullest_snapshot(time.time())
        running["status"]["watcher_running"] = True
        stopped = json.loads(json.dumps(running))
        stopped["status"]["watcher_running"] = False
        for name, snapshot in (("running", running), ("stopped", stopped)):
            (work / (name + ".json")).write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")
        probe = work / "button.ps1"
        probe.write_text(PROBE, encoding="utf-8")
        cls.result = subprocess.run(
            [str(POWERSHELL), "-STA", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(probe)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600,
            env=dict(os.environ, CAR_EXE=str(exe), CAR_WORK=str(work), CAR_LOCALES=json.dumps(LOCALES)))
        answer = work / "result.json"
        cls.answer = (json.loads(answer.read_text(encoding="utf-8-sig"))
                      if cls.result.returncode == 0 and answer.is_file() else {})

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def setUp(self):
        if not self.answer:
            self.fail("the probe did not run: " + (self.result.stderr or self.result.stdout)[-4000:])

    def look(self, locale, name):
        found = [step for step in self.answer[locale] if step["name"] == name]
        self.assertEqual(len(found), 1, name)
        return found[0]

    def test_it_offers_stop_while_the_watcher_runs_and_start_while_it_is_stopped_both_ways(self):
        for locale in LOCALES:
            words = self.catalogs[locale]
            with self.subTest(locale=locale):
                stop, start = words["action.stop_watcher"], words["action.start"]
                self.assertNotEqual(stop, start)
                self.assertEqual(self.look(locale, "running")["text"], stop)
                self.assertEqual(self.look(locale, "stopped")["text"], start,
                                 "Diagnostics kept offering to stop a watcher that is stopped")
                self.assertEqual(self.look(locale, "running again")["text"], stop)

    def test_it_follows_the_status_the_headers_start_reads(self):
        for locale in LOCALES:
            with self.subTest(locale=locale):
                for name, stopped in (("running", False), ("stopped", True), ("running again", False)):
                    self.assertEqual(self.look(locale, name)["start"], stopped, "the header's Start watcher: " + name)

    def test_it_waits_while_an_action_or_the_start_is_in_flight_and_is_live_otherwise(self):
        for locale in LOCALES:
            with self.subTest(locale=locale):
                for name, enabled in (("running", True), ("stopped", True), ("stopped, busy", False),
                                      ("stopped, idle again", True), ("stopped, starting", False),
                                      ("running again", True), ("running, busy", False), ("running, idle again", True)):
                    self.assertEqual(self.look(locale, name)["enabled"], enabled, name)

    def test_the_header_s_light_is_the_working_one_while_a_running_watcher_is_busy(self):
        for locale in LOCALES:
            with self.subTest(locale=locale):
                busy, idle = self.look(locale, "running, busy"), self.look(locale, "running, idle again")
                self.assertEqual(busy["light"], "checking")
                self.assertNotEqual(idle["light"], "checking")

    def test_a_stopped_watcher_keeps_its_own_light_while_busy(self):
        for locale in LOCALES:
            with self.subTest(locale=locale):
                self.assertEqual(self.look(locale, "stopped, busy")["light"], self.look(locale, "stopped")["light"])


class SourceTests(unittest.TestCase):
    def test_the_button_does_what_its_words_say(self):
        body = guiscan.member_body("SettingsForm", "WatcherButton")
        self.assertIn("if (watcherStopped) StartWatcher();", body)
        self.assertIn("else StopWatcher();", body)
        page = guiscan.member_body("SettingsForm", "DiagnosticsSteps")
        self.assertIn("delegate { WatcherButton(); }", page)
        self.assertNotIn("delegate { StopWatcher(); }", page)

    def test_it_is_set_where_the_header_s_start_is(self):
        body = guiscan.member_body("SettingsForm", "ApplyStatus")
        self.assertLess(body.index("startButton.Visible = Equals(running, false);"), body.index("FollowWatcher(running);"))

    def test_the_start_and_every_counted_action_grey_it(self):
        self.assertIn("stopButton.Enabled = busy == 0 && !starting;", guiscan.member_body("SettingsForm", "UpdateWatcherButton"))
        self.assertIn("UpdateWatcherButton();", guiscan.member_body("SettingsForm", "SetBusy"))
        self.assertIn("UpdateWatcherButton();", guiscan.member_body("SettingsForm", "StartWatcher"))
        self.assertIn("UpdateWatcherButton();", guiscan.member_body("SettingsForm", "StartWatcherFinished"))


if __name__ == "__main__":
    unittest.main()
