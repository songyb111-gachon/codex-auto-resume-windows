r"""Two states the Dashboard passed through for one frame, never painted again (v0.6.24, the v0.6.23 final's live acceptance).

The live acceptance of the v0.6.23 final (2026-11-14, plans/v0623-live-acceptance-result-3.md) took a picture of the
Dashboard about every half second after it was reopened, and saw two states that lasted one frame:

* I3, History: "in the 4.9 s frame only, a horizontal scroll bar showed under the list", on the list's first fill. Its
  columns had been fitted to the empty list's whole width; the rows brought Windows' bar beside them, the columns were
  then wider than the list by that bar, and Windows turned on its bar across the bottom in the same step. The window fits
  the columns to the narrower list inside Windows' own handling of the size (SettingsForm.FitColumns, on
  ClientSizeChanged), and Windows, which does not look at its bars again from there, kept the bar across under columns
  that fit. The list's host read it a turn later and laid its soft bar out along the bottom, until the list, laid out for
  it, made Windows take its bar away and the host laid itself out once more. The list now takes a kept bar away as soon
  as its outermost message is over (SoftList.DropKeptBar).
* I2, Settings: "At 12.6 s both 기본값 복원 and 저장 were greyed (inactive) for one frame, then plain again." Settings > General
  asks the bridge what Windows offers the power action's card as it is shown (LoadPower), and that read was counted as an
  action in flight (SetBusy): it turned every button in the window off and on again at its answer, greyed once it
  outlasted BusyHold's moment - Save and Restore defaults with them, which could act all along. A read that only fills a
  card as it is shown no longer turns the buttons off (CallAsync's CardRead); the header's light still shows it as work
  (SetCardRead), and the power switch waits for its own card's read.

Both probes run the real compiled window in a frame far off the screen that is never activated, as the other GUI probes
do, with a bridge rooted where nothing is: History filled from a snapshot of forty finished recoveries, every step of the
list and its host noted; Settings shown on General and then Advanced, Save's and Restore defaults' every change noted.

    PYTHONPATH="src;tests" python -m unittest test_gui_one_frame      (a GUI module: gui_lock.sh)
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
from codex_auto_resume import settings

from test_gui_layout import fullest_snapshot
import corestandin  # noqa: E402
from test_gui_v0611_access import CSC, NO_WINDOW, POWERSHELL, compile_window, reply, run_probe

COMMON = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Windows.Forms
[Windows.Forms.Application]::SetUnhandledExceptionMode([Windows.Forms.UnhandledExceptionMode]::ThrowException)
[Windows.Forms.Application]::EnableVisualStyles()
Add-Type -ReferencedAssemblies System.Windows.Forms, System.Drawing -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
using System.Windows.Forms;
public class OneFrameForm : Form {
    protected override bool ShowWithoutActivation { get { return true; } }
    protected override CreateParams CreateParams { get { CreateParams cp = base.CreateParams; cp.ExStyle |= 0x08000000 | 0x80; return cp; } }
}
public static class OneFrameNative {
    [DllImport("user32.dll")] public static extern int GetWindowLong(IntPtr w, int i);
}
'@
$assembly = [Reflection.Assembly]::LoadFile($env:CAR_EXE)
$any = [Reflection.BindingFlags]'Static,Instance,NonPublic,Public'
$work = [string]$env:CAR_WORK
$utf8 = New-Object Text.UTF8Encoding $false
$parse = $assembly.GetType('CodexAutoResume.Json', $true).GetMethod('Parse', $any)
$type = $assembly.GetType('CodexAutoResume.SettingsForm', $true)
function Read-Json([string]$name) { return $parse.Invoke($null, [object[]]@([IO.File]::ReadAllText((Join-Path $work $name), $utf8))) }
function Invoke-Window([string]$name, [object[]]$arguments) {
    $method = @($type.GetMethods($any) | Where-Object { $_.Name -eq $name -and $_.GetParameters().Count -eq $arguments.Count })[0]
    return $method.Invoke($script:window, $arguments)
}
$nowhere = [string](Join-Path $work 'nowhere')
$once = $assembly.GetType('CodexAutoResume.Bridge', $true).GetConstructors($any)[0].Invoke([object[]]@($nowhere))
$two = @($assembly.GetType('CodexAutoResume.PersistentBridge', $true).GetConstructors($any) | Where-Object { $_.GetParameters().Count -eq 2 })[0]
$bridge = $two.Invoke([object[]]@($nowhere, $once))
$three = @($type.GetConstructors($any) | Where-Object { $_.GetParameters().Count -eq 3 })[0]
$script:frame = New-Object OneFrameForm
$script:frame.FormBorderStyle = 'None'
$script:frame.ShowInTaskbar = $false
$script:frame.StartPosition = 'Manual'
$script:frame.Location = New-Object Drawing.Point -30000, -30000
$script:frame.ClientSize = New-Object Drawing.Size 1000, 664
$script:window = $three.Invoke([object[]]@($bridge, (Read-Json 'strings-en.json'), [Drawing.SystemFonts]::MessageBoxFont))
$type.GetField('auditing', $any).SetValue($script:window, $true)
$script:window.TopLevel = $false
$script:window.FormBorderStyle = 'None'
$script:window.MinimumSize = [Drawing.Size]::Empty
$script:window.Location = [Drawing.Point]::Empty
$script:window.ClientSize = $script:frame.ClientSize
$script:frame.Controls.Add($script:window)
function Pump($times) { for ($k = 0; $k -lt $times; $k++) { [Windows.Forms.Application]::DoEvents(); Start-Sleep -Milliseconds 10 } }
"""

HISTORY = COMMON + r"""
$hostType = $assembly.GetType('CodexAutoResume.SoftListHost', $true)
$listType = $assembly.GetType('CodexAutoResume.SoftList', $true)
# History on the screen before any read, its list empty under "Loading...", as the window reopened showed it.
$null = Invoke-Window 'ShowPage' @('history')
$script:window.Visible = $true
$script:frame.Show()
Pump 30
$script:list = $type.GetField('historyList', $any).GetValue($script:window)
$script:soft = $script:list.Parent.Parent
$script:across = $hostType.GetProperty('OverflowingAcross', $any)
$script:steps = New-Object Collections.ArrayList
function Note([string]$when) {
    $style = [OneFrameNative]::GetWindowLong($script:list.Handle, -16)
    $columns = 0; foreach ($column in $script:list.Columns) { $columns += $column.Width }
    $null = $script:steps.Add(@{ when = $when; bar_across = (($style -band 0x00100000) -ne 0); bar_beside = (($style -band 0x00200000) -ne 0)
        soft_across = [bool]$script:across.GetValue($script:soft, $null); columns = $columns; client = $script:list.ClientSize.Width
        rows = $script:list.Items.Count })
}
# Every message the list tells its host of (a resize, a bar coming or going, a paint), every layout and paint of the host.
$told = [EventHandler]{ param($s, $e) try { Note 'list' } catch { [Console]::Error.WriteLine($_.ToString()); [Environment]::Exit(7) } }
$listType.GetEvent('ScrollChanged', $any).GetAddMethod($true).Invoke($script:list, @($told))
$script:soft.add_Layout([Windows.Forms.LayoutEventHandler]{ param($s, $e) try { Note 'host layout' } catch { [Environment]::Exit(8) } })
$script:soft.add_Paint([Windows.Forms.PaintEventHandler]{ param($s, $e) try { Note 'host paint' } catch { [Environment]::Exit(9) } })
Note 'empty'
# The first read: the rows written in one turn, as the reply of the window's first read writes them.
$null = Invoke-Window 'ApplySnapshot' @((Read-Json 'snapshot.json'))
Note 'turn'
for ($k = 0; $k -lt 30; $k++) { [Windows.Forms.Application]::DoEvents(); Note 'turn'; Start-Sleep -Milliseconds 10 }
# And the window made narrower, which fits the columns again as the list takes its width.
foreach ($narrower in @(37, 61)) {
    $script:frame.ClientSize = New-Object Drawing.Size ($script:frame.ClientSize.Width - $narrower), 664
    $script:window.ClientSize = $script:frame.ClientSize
    Note 'turn'
    for ($k = 0; $k -lt 20; $k++) { [Windows.Forms.Application]::DoEvents(); Note 'turn'; Start-Sleep -Milliseconds 10 }
}
$script:frame.Close()
$script:frame.Dispose()
[IO.File]::WriteAllText((Join-Path $work 'result.json'), (ConvertTo-Json @{ steps = @($script:steps) } -Compress -Depth 5), $utf8)
"""

SETTINGS = COMMON + r"""
# The schema read as it is, a List: a function's return of it would be unrolled into an array.
$schema = $parse.Invoke($null, [object[]]@([IO.File]::ReadAllText((Join-Path $work 'schema.json'), $utf8)))
$null = $type.GetMethod('BuildEditors', $any).Invoke($script:window, [object[]]@($schema, (Read-Json 'settings.json')))
# A snapshot read, the watcher running: the header's light is the watcher's, and moves to the working one while work runs.
$null = Invoke-Window 'ApplySnapshot' @((Read-Json 'snapshot.json'))
$dot = $type.GetField('stateDot', $any).GetValue($script:window)
function Light { return [string]$dot.GetType().GetProperty('State', $any).GetValue($dot, $null) }
$null = Invoke-Window 'ShowPage' @('settings')
$script:window.Visible = $true
$script:frame.Show()
Pump 30
$save = $type.GetField('saveButton', $any).GetValue($script:window)
$restore = $type.GetField('restoreButton', $any).GetValue($script:window)
$script:changes = New-Object Collections.ArrayList
$save.add_EnabledChanged([EventHandler]{ param($s, $e) $null = $script:changes.Add(@{ button = 'save'; enabled = [bool]$s.Enabled }) })
$restore.add_EnabledChanged([EventHandler]{ param($s, $e) $null = $script:changes.Add(@{ button = 'restore'; enabled = [bool]$s.Enabled }) })
$out = @{ before = (Light); shown = @{ save = ([bool]$save.Visible -and [bool]$save.Enabled); restore = ([bool]$restore.Visible -and [bool]$restore.Enabled) } }
# From here the window asks as a window on the screen does: the power action's card asks the bridge what Windows offers as
# General is shown, the homes' card its suggestion as Advanced is.
$type.GetField('auditing', $any).SetValue($script:window, $false)
function Section([string]$name, [string]$flag) {
    $script:changes.Clear()
    $null = Invoke-Window 'ShowSection' @($name)
    $asked = [bool]$type.GetField($flag, $any).GetValue($script:window)
    $during = Light
    $waited = 0
    while ([bool]$type.GetField($flag, $any).GetValue($script:window) -and $waited -lt 1500) { [Windows.Forms.Application]::DoEvents(); Start-Sleep -Milliseconds 10; $waited++ }
    Pump 30
    return @{ asked = $asked; during = $during; after = (Light); answered = -not [bool]$type.GetField($flag, $any).GetValue($script:window); changes = @($script:changes)
              save = [bool]$save.Enabled; restore = [bool]$restore.Enabled; visible = [bool]$save.Visible }
}
$out.general = Section 'general' 'powerReading'
$out.advanced = Section 'advanced' 'homesSuggestReading'
$type.GetField('auditing', $any).SetValue($script:window, $true)
$script:frame.Close()
$script:frame.Dispose()
[IO.File]::WriteAllText((Join-Path $work 'result.json'), (ConvertTo-Json $out -Compress -Depth 6), $utf8)
"""

# A stand-in for the bridge's Python, as tests/busycase.py has one: every command answered at once with an empty result,
# each one's name written to CAR_FAKE_LOG, and `power-action` answered only once the file CAR_FAKE_GATE exists.
FAKE = r"""
using System;
using System.IO;
using System.Text.RegularExpressions;
using System.Threading;
static class Fake {
    static int Main(string[] args) {
        if (Array.IndexOf(args, "serve") < 0) { Console.Out.Write("{\"ok\":true,\"result\":{}}"); return 0; }
        string gate = Environment.GetEnvironmentVariable("CAR_FAKE_GATE");
        string log = Environment.GetEnvironmentVariable("CAR_FAKE_LOG");
        string line;
        while ((line = Console.In.ReadLine()) != null) {
            string id = Regex.Match(line, "\"id\":(\\d+)").Groups[1].Value;
            string name = Regex.Match(line, "\"command\":\"([a-z_-]+)\"").Groups[1].Value;
            if (name == "power-action") while (!File.Exists(gate)) Thread.Sleep(20);
            File.AppendAllText(log, name + "\n");
            Console.Out.Write("{\"id\":" + id + ",\"reply\":{\"ok\":true,\"result\":{}}}\n");
            Console.Out.Flush();
        }
        return 0;
    }
}
"""

HELD_CLICK = COMMON.replace("$nowhere = [string](Join-Path $work 'nowhere')", "$nowhere = [string]$env:CAR_HOME") + r"""
$gate = [string]$env:CAR_FAKE_GATE
$log = [string]$env:CAR_FAKE_LOG
$schema = $parse.Invoke($null, [object[]]@([IO.File]::ReadAllText((Join-Path $work 'schema.json'), $utf8)))
$null = $type.GetMethod('BuildEditors', $any).Invoke($script:window, [object[]]@($schema, (Read-Json 'settings.json')))
$null = Invoke-Window 'ShowPage' @('settings')
$null = $script:window.Handle
$script:asked = 0
$type.GetField('DialogAnswers', $any).SetValue($null, [Func[string,string,bool]]{ param($text, $affirm) $script:asked++; $true })
function Reading { return [bool]$type.GetField('powerReading', $any).GetValue($script:window) }
function Busy { return [int]$type.GetField('busy', $any).GetValue($script:window) }
function Asked([string]$name) { if (-not (Test-Path $log)) { return 0 }; return @(Get-Content $log | Where-Object { $_ -eq $name }).Count }
function Settle {
    $end = [DateTime]::UtcNow.AddSeconds(30)
    while (((Reading) -or (Busy) -gt 0) -and [DateTime]::UtcNow -lt $end) { [Windows.Forms.Application]::DoEvents(); Start-Sleep -Milliseconds 20 }
    for ($k = 0; $k -lt 25; $k++) { [Windows.Forms.Application]::DoEvents(); Start-Sleep -Milliseconds 20 }
}
$type.GetField('auditing', $any).SetValue($script:window, $false)
# The card's first read, answered: what Windows offers is known, and the switch can be turned.
New-Item -ItemType File -Path $gate -Force | Out-Null
$null = Invoke-Window 'ShowSection' @('general')
Settle
$out = @{ can = [bool]$type.GetField('powerCanSwitch', $any).GetValue($script:window)
          enabled = [bool]$type.GetField('powerSwitch', $any).GetValue($script:window).Enabled }
# General shown again: the card asks again, and the answer waits. The switch is clicked meanwhile.
Remove-Item $gate
$null = Invoke-Window 'ShowSection' @('advanced')
$null = Invoke-Window 'ShowSection' @('general')
$out.reading = Reading
$null = Invoke-Window 'PowerSwitched' @()
for ($k = 0; $k -lt 25; $k++) { [Windows.Forms.Application]::DoEvents(); Start-Sleep -Milliseconds 20 }
$out.while = @{ asked = $script:asked; arms = (Asked 'power-arm'); reading = (Reading) }
# The answer comes.
New-Item -ItemType File -Path $gate -Force | Out-Null
Settle
$out.after = @{ asked = $script:asked; arms = (Asked 'power-arm'); reading = (Reading) }
$type.GetField('DialogAnswers', $any).SetValue($null, $null)
$type.GetField('auditing', $any).SetValue($script:window, $true)
$script:window.Dispose()
$null = $bridge.GetType().GetMethod('Stop', $any).Invoke($bridge, @())
[IO.File]::WriteAllText((Join-Path $work 'result.json'), (ConvertTo-Json $out -Compress -Depth 5), $utf8)
"""

_exe = None
_folder = None


def setUpModule():
    global _exe, _folder
    if not (CSC.is_file() and POWERSHELL.is_file()):
        return
    _folder = tempfile.TemporaryDirectory()
    _exe = compile_window(Path(_folder.name))


def tearDownModule():
    if _folder is not None:
        _folder.cleanup()


def workspace() -> Path:
    work = Path(tempfile.mkdtemp(dir=_folder.name))
    (work / "strings-en.json").write_text(json.dumps(reply("en"), ensure_ascii=False), encoding="utf-8")
    return work


@unittest.skipUnless(CSC.is_file() and POWERSHELL.is_file(), "needs the in-box compiler and PowerShell")
class HistoryFirstFillTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        work = workspace()
        snapshot = fullest_snapshot(time.time())
        finished = snapshot["history"]
        # More rows than show: the list takes Windows' bar beside them, as a history of any length does.
        snapshot["history"] = [dict(finished[i % len(finished)], interruption_id="%064x" % (i + 1)) for i in range(40)]
        (work / "snapshot.json").write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")
        cls.steps = run_probe(HISTORY, work, 300, CAR_EXE=str(_exe))["steps"]

    def test_what_the_test_stands_on(self):
        """The rows went in, more than show: Windows' bar came beside them and narrowed the list."""
        first, last = self.steps[0], [step for step in self.steps if step["when"] == "turn"][-1]
        self.assertEqual((first["rows"], first["bar_beside"]), (0, False))
        self.assertEqual(last["rows"], 40)
        self.assertTrue(last["bar_beside"])
        self.assertLess(last["client"], first["client"])

    def test_the_soft_bar_along_the_bottom_is_never_laid_out(self):
        laid = [step for step in self.steps if step["soft_across"]]
        self.assertEqual(laid, [], "the host laid its bar out along the bottom of a list whose columns fit it")

    def test_no_turn_ends_with_windows_bar_across_the_list(self):
        """Within a turn Windows may turn its bar on and off as the columns are fitted; nothing is painted until the turn
        is over, and no turn ends with the bar on - under the clip it is drawn white across the rows' bottom."""
        for index, step in enumerate(self.steps):
            if step["when"] in ("turn", "host paint"):
                with self.subTest(step=index):
                    self.assertLessEqual(step["columns"], step["client"], "the columns fit the list")
                    self.assertFalse(step["bar_across"], "Windows' bar across the bottom, under columns that fit")


@unittest.skipUnless(CSC.is_file() and POWERSHELL.is_file(), "needs the in-box compiler and PowerShell")
class SettingsButtonsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        work = workspace()
        (work / "schema.json").write_text(json.dumps(settings.describe(), ensure_ascii=False), encoding="utf-8")
        (work / "settings.json").write_text(json.dumps(settings.defaults(), ensure_ascii=False), encoding="utf-8")
        (work / "snapshot.json").write_text(json.dumps(fullest_snapshot(time.time()), ensure_ascii=False), encoding="utf-8")
        cls.answer = run_probe(SETTINGS, work, 300, CAR_EXE=str(_exe))

    def test_what_the_test_stands_on(self):
        """Save and Restore defaults showed, able to act; each card asked the bridge as its section showed, and had its
        answer (the bridge, rooted where nothing is, refuses at once)."""
        self.assertEqual(self.answer["shown"], {"save": True, "restore": True})
        for section in ("general", "advanced"):
            with self.subTest(section):
                seen = self.answer[section]
                self.assertTrue(seen["asked"], "the card did not ask the bridge as it showed")
                self.assertTrue(seen["answered"])
                self.assertTrue(seen["visible"])

    def test_save_and_restore_defaults_stay_as_they_are_while_a_card_is_read(self):
        for section in ("general", "advanced"):
            with self.subTest(section):
                seen = self.answer[section]
                self.assertEqual(seen["changes"], [], "Save or Restore defaults turned off and on around a card's read")
                self.assertTrue(seen["save"] and seen["restore"])

    def test_the_headers_light_shows_the_card_read_as_work(self):
        """The owner's rule (a light that does not move while work runs reads as broken or idle): a card's read lights the
        header's working light while it is on its way, as an action does, and the watcher's own light comes back after."""
        self.assertNotEqual(self.answer["before"], "checking", "nothing was in flight before the sections were shown")
        for section in ("general", "advanced"):
            with self.subTest(section):
                seen = self.answer[section]
                self.assertEqual(seen["during"], "checking", "the header's light did not show the card's read")
                self.assertEqual(seen["after"], self.answer["before"])


@unittest.skipUnless(CSC.is_file() and POWERSHELL.is_file(), "needs the in-box compiler and PowerShell")
class HeldPowerClickTests(unittest.TestCase):
    """The switch looks as it did while its card is read: a click then is kept and taken at the answer, never dropped."""

    @classmethod
    def setUpClass(cls):
        work = workspace()
        (work / "schema.json").write_text(json.dumps(settings.describe(), ensure_ascii=False), encoding="utf-8")
        (work / "settings.json").write_text(json.dumps(settings.defaults(), ensure_ascii=False), encoding="utf-8")
        cls.home = work / "home"
        (cls.home / "app" / "src").mkdir(parents=True)
        source = work / "fake.cs"
        source.write_text(corestandin.shimmed(FAKE), encoding="utf-8")
        corestandin.place(CSC, source, cls.home, extra=("python.exe", "pythonw.exe"))
        try:
            cls.answer = run_probe(HELD_CLICK, work, 300, CAR_EXE=str(_exe), CAR_HOME=str(cls.home),
                                   CAR_FAKE_GATE=str(work / "gate"), CAR_FAKE_LOG=str(work / "asked.log"))
        finally:
            # The stand-in, if the probe left it running: only processes run from this test's own home.
            script = ("Get-Process -Name codex-auto-resume,python,pythonw,CodexAutoResume -ErrorAction SilentlyContinue | Where-Object { $_.Path -and "
                      "$_.Path.StartsWith($env:CAR_HOME, [StringComparison]::OrdinalIgnoreCase) } | Stop-Process -Force")
            subprocess.run([str(POWERSHELL), "-NoProfile", "-NonInteractive", "-Command", script], capture_output=True,
                           timeout=120, creationflags=NO_WINDOW, env=dict(os.environ, CAR_HOME=str(cls.home)))

    def test_what_the_test_stands_on(self):
        """The first read answered let the switch be turned, and the second was on its way when it was clicked."""
        self.assertTrue(self.answer["can"])
        self.assertTrue(self.answer["enabled"], "the switch looks as it can be turned")
        self.assertTrue(self.answer["reading"])
        self.assertTrue(self.answer["while"]["reading"])

    def test_a_click_during_the_read_is_taken_once_at_its_answer(self):
        held, after = self.answer["while"], self.answer["after"]
        self.assertEqual((held["asked"], held["arms"]), (0, 0), "nothing is asked or armed before the answer")
        self.assertFalse(after["reading"])
        self.assertEqual(after["asked"], 1, "turning on asks once, after the answer")
        self.assertEqual(after["arms"], 1, "the click was dropped: the switch was never turned")


class SourceTests(unittest.TestCase):
    def test_a_cards_read_is_no_action_in_flight(self):
        call = guiscan.member_body("SettingsForm", "CallAsync")
        for on in ("true", "false"):
            with self.subTest(on=on):
                self.assertIn("if (cardRead) SetCardRead(%s);" % on, call)
                self.assertIn("else SetBusy(%s);" % on, call)
        self.assertIn("busy > 0 || cardReads > 0", guiscan.member_body("SettingsForm", "Hero"))
        for member in ("LoadPower", "LoadHomeSuggestion"):
            with self.subTest(member):
                self.assertIn("}, CardRead);", guiscan.member_body("SettingsForm", member))

    def test_the_power_switch_waits_for_its_cards_read(self):
        self.assertIn("|| powerReading) return;", guiscan.member_body("SettingsForm", "PowerSwitched"))

    def test_the_list_takes_a_kept_bar_away_once_its_outermost_message_is_over(self):
        # The list's own WndProc, not its header's (SoftList.PinnedHeader, nested in it, has one too).
        body = guiscan.type_body("SoftList")
        start = body.index("if (messageDepth == 0 && resizedWithin)")
        self.assertLess(body.index("DropKeptBar();", start), body.index("ScrollChanged(this, EventArgs.Empty);", start))
        self.assertIn("return columns <= ClientSize.Width;", body)


if __name__ == "__main__":
    unittest.main()
