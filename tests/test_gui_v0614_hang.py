r"""The window does no layout while a recovery waits and nothing on screen changes (v0.6.14).

With one usage-limit recovery waiting, the window hung: every stack taken while it did not answer was text being
measured inside a layout of a whole page. Three timers handed whole pages a layout for nothing a person could see:

- Every status (each five-second snapshot) wrote the power action card's two lines `Visible = true`. While Settings
  is not the page in front, `Visible` answers false whatever a line was told, so the write took the change branch
  every time and laid out the card and the whole of Settings > General - on a PC where sleep is not offered, or
  once a power action had run, from the first time Settings had been seen.
- History's "Open the conversation" button was written the same way on every snapshot, beside a row whose
  conversation is off.
- The clock wrote the Overview's "Next check in" line every second, and the line sits in an AutoSize card on an
  AutoSize grid, so each second laid out the Overview's grid and page and measured all four cards - hidden behind
  Pending, or in front for the same bounds.

This probe builds the real compiled window off-screen, as tests/test_gui_v069_idle.py does, brings each of those
states about, and counts the Layout events of the controls around them. Nothing of the real installation is read:
the bridge is rooted where nothing is, and nothing is shown or captured. What is drawn is unchanged: a line still
appears, disappears and moves its card exactly as before, and the Overview shown again says the countdown of now.
"""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
import guiscan

from codex_auto_resume import l10n, settings

from test_gui_layout import fullest_snapshot

CSC = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe"
POWERSHELL = (Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
              / "WindowsPowerShell" / "v1.0" / "powershell.exe")
TIMES = 5
TICKS = 10

PROBE = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Windows.Forms
[Windows.Forms.Application]::EnableVisualStyles()
[Windows.Forms.Application]::SetCompatibleTextRenderingDefault($false)
$assembly = [Reflection.Assembly]::LoadFile($env:CAR_EXE)
$static = [Reflection.BindingFlags]'Static,NonPublic,Public'
$instance = [Reflection.BindingFlags]'Instance,NonPublic,Public'
$form = $assembly.GetType('CodexAutoResume.SettingsForm', $true)
$bridgeType = $assembly.GetType('CodexAutoResume.Bridge', $true)
$persistentType = $assembly.GetType('CodexAutoResume.PersistentBridge', $true)
$parse = $assembly.GetType('CodexAutoResume.Json', $true).GetMethod('Parse', $static)
$ownState = [Windows.Forms.Control].GetMethod('GetState', $instance)
$work = [string]$env:CAR_WORK
$times = [int]$env:CAR_TIMES
$ticks = [int]$env:CAR_TICKS
$utf8 = New-Object Text.UTF8Encoding $false
# The comma keeps a list one value: PowerShell would hand the schema on as its items.
function Read-Json([string]$name) { return ,($parse.Invoke($null, [object[]]@([IO.File]::ReadAllText((Join-Path $work $name), $utf8)))) }
function Get-Field($target, [string]$name) { return $form.GetField($name, $instance).GetValue($target) }
function Invoke-Window($target, [string]$name, [object[]]$arguments) {
    $method = @($form.GetMethods($instance) | Where-Object { $_.Name -eq $name -and $_.GetParameters().Count -eq $arguments.Count })[0]
    $null = $method.Invoke($target, $arguments)
}
# What a control itself was told, whatever its parents are; `Visible` is false inside a hidden page.
function Test-Own($control) { return [bool]$ownState.Invoke($control, [object[]]@(2)) }
# Layout events, counted per name from now on.
$counts = @{}
function Watch-Layout([string]$name, $control) {
    $counts[$name] = 0
    $handler = { $counts[$name] = $counts[$name] + 1 }.GetNewClosure()
    $control.add_Layout([Windows.Forms.LayoutEventHandler]$handler)
}
# A line's words rewritten, counted per name from now on: each new countdown is measured to be laid out.
function Watch-Text([string]$name, $control) {
    $counts[$name] = 0
    $handler = { $counts[$name] = $counts[$name] + 1 }.GetNewClosure()
    $control.add_TextChanged([EventHandler]$handler)
}
function Take-Counts { $copy = @{}; foreach ($key in @($counts.Keys)) { $copy[$key] = $counts[$key]; $counts[$key] = 0 }; return $copy }
# The clock moving on by `seconds`: every waiting row's time comes that much nearer, as it does on the clock.
function Move-Clock($reply, [double]$seconds) {
    foreach ($row in $reply['pending']) {
        if ($row['eligible_at'] -ne $null) { $row['eligible_at'] = [double]$row['eligible_at'] - $seconds }
    }
}

$english = Read-Json 'strings-en.json'
$nowhere = [string](Join-Path $work 'nowhere')
$once = $bridgeType.GetConstructors($instance)[0].Invoke([object[]]@($nowhere))
$bridge = $persistentType.GetConstructors($instance)[0].Invoke([object[]]@($nowhere, $once))
$three = @($form.GetConstructors($instance) | Where-Object { $_.GetParameters().Count -eq 3 })[0]
$window = $three.Invoke([object[]]@($bridge, $english, [Drawing.SystemFonts]::MessageBoxFont))
$form.GetField('auditing', $instance).SetValue($window, $true)
$window.TopLevel = $false
$window.MinimumSize = [Drawing.Size]::Empty
$window.ClientSize = [Drawing.Size]::new([int]$form.GetField('OpeningWidth', $static).GetValue($null),
                                         [int]$form.GetField('OpeningHeight', $static).GetValue($null))
$out = @{}

# Every page built, as a person clicking through them builds them: Settings > General shown once (where the power
# card asks what Windows offers: sleep is not offered here, as on a Modern Standby PC), History with its first row
# chosen, the Overview; then Pending in front, as the notification opens the window.
Invoke-Window $window 'BuildEditors' @((Read-Json 'schema.json'), (Read-Json 'settings.json'))
Invoke-Window $window 'ApplyPowerOptions' @((Read-Json 'power.json'))
Invoke-Window $window 'ShowPage' @('settings')
Invoke-Window $window 'ShowPage' @('history')
$history = Get-Field $window 'historyList'
# A list keeps a selection only once it has a window of its own; nothing is shown.
$null = $history.Handle
Invoke-Window $window 'ShowPage' @('overview')
Invoke-Window $window 'ApplySnapshot' @((Read-Json 'snapshot.json'))
Invoke-Window $window 'ShowPage' @('pending')

$card = Get-Field $window 'powerCard'
$general = (Get-Field $window 'sections')['general']
$thread = Get-Field $window 'historyThread'
$overview = (Get-Field $window 'pages')['overview']
$next = Get-Field $window 'nextLine'
$out.lines = @((Test-Own (Get-Field $window 'powerUnavailable')), (Test-Own (Get-Field $window 'powerLast')))
$out.chosen = $history.SelectedIndices.Count
$out.threadOffered = (Test-Own $thread)
Watch-Layout 'powerCard' $card
Watch-Layout 'general' $general
Watch-Layout 'threadRow' $thread.Parent
Watch-Layout 'overview' $overview
Watch-Layout 'waitingCard' $next.Parent
Watch-Text 'waitingWords' (Get-Field $window 'waitingLine')
Watch-Text 'nextWords' $next
Watch-Text 'runningWords' (Get-Field $window 'runningLine')

# The same snapshot again, every five seconds, with Pending in front.
for ($i = 0; $i -lt $times; $i++) { Invoke-Window $window 'ApplySnapshot' @((Read-Json 'snapshot.json')) }
$out.snapshots = Take-Counts
$out.threadOfferedAfter = (Test-Own $thread)

# Clock seconds with the Overview built and hidden, a minute of waiting each, so its countdown moves.
$current = Get-Field $window 'snapshot'
$before = [string]$next.Text
for ($i = 0; $i -lt $ticks; $i++) { Move-Clock $current 60; Invoke-Window $window 'UpdateCountdowns' @() }
$out.hiddenTicks = Take-Counts
# Shown again: the countdown of now, not the one the clock last wrote before it was hidden.
Invoke-Window $window 'ShowPage' @('overview')
$shown = [string]$next.Text
Invoke-Window $window 'UpdateCountdowns' @()
$out.countdown = @($before, $shown, [string]$next.Text)
$null = Take-Counts

# Clock seconds with the Overview in front: one second each, so the countdown's words keep their width.
$widths = @()
for ($i = 0; $i -lt $ticks; $i++) {
    Move-Clock $current 1
    Invoke-Window $window 'UpdateCountdowns' @()
    $widths += [string]$next.Text
}
$out.frontTicks = Take-Counts
$out.frontWords = $widths
# And words of another width, which must still lay the card out: the countdown has come due.
$bounds = $next.Bounds
Move-Clock $current 86400
Invoke-Window $window 'UpdateCountdowns' @()
$out.due = Take-Counts
$out.dueWords = [string]$next.Text
$out.dueBounds = @($bounds.Width, $next.Bounds.Width)
$window.Dispose()
[IO.File]::WriteAllText((Join-Path $work 'result.json'), (ConvertTo-Json $out -Compress -Depth 6), $utf8)
"""


class WaitingWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        cls.answer, cls.result = {}, None
        if os.name != "nt" or not CSC.is_file():
            return
        work = Path(cls.folder.name)
        exe = work / "CodexAutoResumeSettings.exe"
        subprocess.run([str(CSC), "/nologo", "/target:winexe", "/platform:x64", "/out:" + str(exe),
                        "/reference:System.dll", "/reference:System.Drawing.dll", "/reference:System.Windows.Forms.dll",
                        *[str(path) for path in guiscan.sources()]],
                       check=True, capture_output=True, timeout=300)
        reply = {"ok": True, "language": "en", "strings": l10n.catalog("en"), "endonyms": dict(l10n.ENDONYMS),
                 "preference": "en", "system_language": "en"}
        (work / "strings-en.json").write_text(json.dumps(reply, ensure_ascii=False), encoding="utf-8")
        (work / "schema.json").write_text(json.dumps(settings.describe(), ensure_ascii=False), encoding="utf-8")
        (work / "settings.json").write_text(json.dumps(settings.defaults(), ensure_ascii=False), encoding="utf-8")
        # The window's clock held at one moment (CODEX_AR_STILL_NOW, as the pictures hold it): the probe moves the
        # waiting rows' times instead, so every countdown it reads is known to the second.
        now = float(int(time.time()))
        snapshot = copy.deepcopy(fullest_snapshot(now))
        # A power action that has run: its last line has words from the first status on, Settings seen or not.
        snapshot["status"]["power_action"] = {"last": {"action": "shut_down", "result": "done", "at": now - 2 * 86400}}
        # Every finished conversation off, so History's chosen row offers to open it.
        for row in snapshot["history"]:
            row["thread_enabled"] = False
        (work / "snapshot.json").write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")
        # What Windows offers: hibernate and shut down, and no sleep (a Modern Standby PC has no S1-S3).
        power = {"actions": [{"value": "sleep", "available": False, "reason": "no_sleep_state"},
                             {"value": "hibernate", "available": True}, {"value": "shut_down", "available": True}],
                 "managed": False, "upgrade_pending": False, "view": None}
        (work / "power.json").write_text(json.dumps(power, ensure_ascii=False), encoding="utf-8")
        probe = work / "hang.ps1"
        probe.write_text(PROBE, encoding="utf-8")
        cls.result = subprocess.run(
            [str(POWERSHELL), "-STA", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(probe)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            env=dict(os.environ, CAR_EXE=str(exe), CAR_WORK=str(work), CAR_TIMES=str(TIMES), CAR_TICKS=str(TICKS),
                     CODEX_AR_STILL_NOW=str(int(now))))
        answer = work / "result.json"
        cls.answer = (json.loads(answer.read_text(encoding="utf-8-sig"))
                      if cls.result.returncode == 0 and answer.is_file() else {})

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def setUp(self):
        if os.name != "nt" or not CSC.is_file():
            self.skipTest("the window is compiled with the in-box C# compiler on Windows")
        if not self.answer:
            self.fail("the probe did not run: " + (self.result.stderr or self.result.stdout)[-4000:])

    def test_the_states_are_the_ones_that_hung(self):
        """Otherwise every count below is zero for the wrong reason."""
        self.assertEqual(self.answer["lines"], [True, True],
                         "the power card's two lines (sleep not offered; the last action) have no words")
        self.assertEqual(self.answer["chosen"], 1, "History has no chosen row")
        self.assertTrue(self.answer["threadOffered"], "History's chosen row does not offer its conversation")
        before, shown, again = self.answer["countdown"]
        self.assertEqual(before, "Next check in 50:00", "the soonest recovery is not 50 minutes away")

    def test_an_unchanged_status_lays_out_nothing_in_settings(self):
        """Each five-second snapshot, with Settings > General built and Pending in front: 8 layouts each before."""
        counts = self.answer["snapshots"]
        self.assertEqual(counts["powerCard"], 0, "the power card was laid out by an unchanged status")
        self.assertEqual(counts["general"], 0, "Settings > General was laid out by an unchanged status")

    def test_an_unchanged_snapshot_lays_out_nothing_in_history(self):
        self.assertEqual(self.answer["snapshots"]["threadRow"], 0,
                         "History's button row was laid out by an unchanged snapshot")
        self.assertTrue(self.answer["threadOfferedAfter"],
                        "and the button must still be offered beside a row whose conversation is off")

    def test_a_clock_second_lays_out_nothing_behind_pending(self):
        """The Overview built and hidden: 3 layouts every second before, for the whole wait."""
        counts = self.answer["hiddenTicks"]
        self.assertEqual(counts["waitingCard"], 0, "the clock laid out the hidden Overview's Waiting card")
        self.assertEqual(counts["overview"], 0, "the clock laid out the hidden Overview")
        self.assertEqual([counts["waitingWords"], counts["nextWords"], counts["runningWords"]], [0, 0, 0],
                         "the clock rewrote (and so measured) the hidden Overview's Waiting lines")

    def test_the_overview_shown_again_says_the_countdown_of_now(self):
        before, shown, again = self.answer["countdown"]
        self.assertEqual(shown, "Next check in 40:00",
                         "the Overview came back without the ten minutes that passed while it was hidden")
        self.assertEqual(again, shown)

    def test_a_clock_second_in_front_lays_out_nothing_while_the_words_keep_their_room(self):
        """The Overview in front, as a window opened from the app usually is."""
        words = self.answer["frontWords"]
        self.assertEqual(words, ["Next check in 39:%02d" % (59 - second) for second in range(TICKS)],
                         "the countdown did not move every second")
        counts = self.answer["frontTicks"]
        self.assertEqual(counts["waitingCard"], 0, "a countdown second laid out the Waiting card")
        self.assertEqual(counts["overview"], 0, "a countdown second laid out the Overview")

    def test_words_that_need_other_room_are_laid_out_as_before(self):
        self.assertEqual(self.answer["dueWords"], "Due to be checked now")
        self.assertGreater(self.answer["due"]["waitingCard"], 0,
                           "a line that changed its width was not laid out")


if __name__ == "__main__":
    unittest.main()
