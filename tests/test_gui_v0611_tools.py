r"""v0.6.11: the Dashboard's own tools - Don't postpone, a conversation's message, the log, the state
folder's access and Show me what happens - held through the compiled window's own static methods.

What each decides is a static method so it can be asked without a window: whether Don't postpone
is offered for a row (only a person's postponement still ahead, never a made-up row), which rows are
made up, how a made-up row joins a list, the word for the state folder, what the log's count line
says, and a conversation's own message read from the settings. The source is read too, for what the
menus and the Diagnostics page offer and in which order - new things after the ones there were.

The window itself is built too, never shown (WindowTests), for what only a built window can say: that
the Log dialog's five-second look leaves the list where the person scrolled it, that the needs-you
notice's kinds, stall and sound are live only while the notice is on, what the Overview and Diagnostics
say of a watcher that stopped, and that a weekly limit whose reset has passed is not said to be current.
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
from codex_auto_resume import l10n, settings

CSC = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe"
POWERSHELL = (Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
              / "WindowsPowerShell" / "v1.0" / "powershell.exe")
THREAD = "0a1b2c3d-0001-7000-8000-000000000001"

PROBE = r"""
$ErrorActionPreference = 'Stop'
$assembly = [Reflection.Assembly]::LoadFile($env:CAR_EXE)
$form = $assembly.GetType('CodexAutoResume.SettingsForm', $true)
$flags = [Reflection.BindingFlags]'Static,NonPublic,Public'
function Method($name) { $m = $form.GetMethod($name, $flags); if (-not $m) { throw ('no ' + $name) }; return $m }

function To-Value {
    param($value)
    if ($null -eq $value) { return $null }
    if ($value -is [System.Management.Automation.PSCustomObject]) {
        $map = New-Object 'System.Collections.Generic.Dictionary[string,object]'
        foreach ($field in $value.PSObject.Properties) { $map.Add([string]$field.Name, (To-Value $field.Value)) }
        return ,$map
    }
    if ($value -is [Array]) {
        $list = New-Object 'System.Collections.Generic.List[object]'
        foreach ($item in $value) { $list.Add((To-Value $item)) }
        return ,$list
    }
    if ($value -is [bool] -or $value -is [string]) { return $value }
    return [double]$value
}

$out = @{ unpostpone = @{}; demo = @{}; access = @{}; count = @{}; text = @{}; joined = @{} }
$can = Method 'CanUnpostpone'
$isDemo = Method 'IsDemo'
foreach ($case in (ConvertFrom-Json $env:CAR_ROWS).PSObject.Properties) {
    $row = [Collections.Generic.Dictionary[string,object]](To-Value $case.Value)
    $out.unpostpone[$case.Name] = [bool]$can.Invoke($null, [object[]]@($row, $true, [double]1000))
    $out.demo[$case.Name] = [bool]$isDemo.Invoke($null, [object[]]@($row))
}
$out.unpostpone['busy'] = [bool]$can.Invoke($null, [object[]]@([Collections.Generic.Dictionary[string,object]](To-Value (ConvertFrom-Json $env:CAR_ROWS).mine), $false, [double]1000))
$word = Method 'StateAccessWord'
foreach ($access in @('owner_only', 'shared', 'unknown', 'other', '')) { $out.access[$access] = [string]$word.Invoke($null, [object[]]@($access)) }
$out.access['null'] = [string]$word.Invoke($null, [object[]]@($null))
$count = Method 'LogCount'
foreach ($case in (ConvertFrom-Json $env:CAR_LOGS).PSObject.Properties) {
    $result = [Collections.Generic.Dictionary[string,object]](To-Value $case.Value)
    $out.count[$case.Name] = [string]$count.Invoke($null, [object[]]@($result, '{shown} of {matched}', 'none', 'unavailable'))
}
$out.count['unreadable'] = [string]$count.Invoke($null, [object[]]@($null, '{shown} of {matched}', 'none', 'unavailable'))
$text = Method 'ConversationText'
$settings = [Collections.Generic.Dictionary[string,object]](To-Value (ConvertFrom-Json $env:CAR_SETTINGS))
$out.text['own'] = $text.Invoke($null, [object[]]@($settings, $env:CAR_THREAD))
$out.text['other'] = $text.Invoke($null, [object[]]@($settings, '0a1b2c3d-0001-7000-8000-000000000002'))
$out.text['none'] = $text.Invoke($null, [object[]]@($null, $env:CAR_THREAD))
$with = Method 'WithDemo'
[Collections.Generic.List[object]]$rows = New-Object 'System.Collections.Generic.List[object]'
$rows.Add('a'); $rows.Add('b')
[Collections.Generic.Dictionary[string,object]]$made = New-Object 'System.Collections.Generic.Dictionary[string,object]'
$made['demo'] = $true
$out.joined['last'] = @($with.Invoke($null, [object[]]@($rows, $made, $false)) | ForEach-Object { if ($_ -is [string]) { $_ } else { 'demo' } })
$out.joined['first'] = @($with.Invoke($null, [object[]]@($rows, $made, $true)) | ForEach-Object { if ($_ -is [string]) { $_ } else { 'demo' } })
$out.joined['none'] = @($with.Invoke($null, [object[]]@($rows, $null, $true)))
$out | ConvertTo-Json -Depth 5 -Compress
"""

WAITING = {"code": "waiting_reset", "cancel_requested": False}
ROWS = {
    "mine": dict(WAITING, postponed_until=5000.0, not_before=5000.0),
    "over": dict(WAITING, postponed_until=900.0, not_before=900.0),
    "window": dict(WAITING, not_before=5000.0),
    "cancelled": dict(WAITING, postponed_until=5000.0, cancel_requested=True),
    "sent": {"code": "submitted", "postponed_until": 5000.0},
    "made_up": dict(WAITING, postponed_until=5000.0, demo=True),
}
LOGS = {"some": {"lines": [{"at": "x", "text": "y"}, {"at": "x", "text": "z"}], "matched": 7},
        "none": {"lines": [], "matched": 0}}
SETTINGS = {"custom_message_by_thread": {THREAD: "Go on, please."}}


@unittest.skipUnless(CSC.is_file() and POWERSHELL.is_file(), "needs the in-box compiler and PowerShell")
class ToolsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        work = Path(cls.folder.name)
        exe = work / "CodexAutoResumeSettings.exe"
        subprocess.run([str(CSC), "/nologo", "/target:winexe", "/platform:x64", "/out:" + str(exe),
                        "/reference:System.dll", "/reference:System.Drawing.dll",
                        "/reference:System.Windows.Forms.dll", *[str(path) for path in guiscan.sources()]],
                       check=True, capture_output=True, timeout=300,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        probe = work / "probe.ps1"
        probe.write_text(PROBE, encoding="utf-8")
        result = subprocess.run(
            [str(POWERSHELL), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(probe)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            env=dict(os.environ, CAR_EXE=str(exe), CAR_ROWS=json.dumps(ROWS), CAR_LOGS=json.dumps(LOGS),
                     CAR_SETTINGS=json.dumps(SETTINGS), CAR_THREAD=THREAD))
        cls.result = result
        cls.answer = json.loads(result.stdout) if result.returncode == 0 and result.stdout.strip() else {}

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def setUp(self):
        if not self.answer:
            self.fail("the probe did not run: " + (self.result.stderr or self.result.stdout)[-2000:])

    def test_dont_postpone_is_offered_only_for_a_persons_postponement_still_ahead(self):
        self.assertEqual(self.answer["unpostpone"], {"mine": True, "over": False, "window": False, "cancelled": False,
                                                     "sent": False, "made_up": False, "busy": False})

    def test_only_the_made_up_row_is_made_up_and_it_joins_a_list_where_it_belongs(self):
        self.assertEqual({name for name, made in self.answer["demo"].items() if made}, {"made_up"})
        self.assertEqual(self.answer["joined"], {"last": ["a", "b", "demo"], "first": ["demo", "a", "b"],
                                                 "none": ["a", "b"]})

    def test_the_state_folder_has_three_words_and_anything_else_is_unknown(self):
        self.assertEqual(self.answer["access"], {"owner_only": "owner_only", "shared": "shared", "unknown": "unknown",
                                                 "other": "unknown", "": "unknown", "null": "unknown"})

    def test_the_log_count_says_what_is_shown_of_what_matched(self):
        self.assertEqual(self.answer["count"], {"some": "2 of 7", "none": "none", "unreadable": "unavailable"})

    def test_a_conversations_message_is_read_for_that_conversation_alone(self):
        self.assertEqual(self.answer["text"], {"own": "Go on, please.", "other": None, "none": None})


WINDOW_PROBE = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Windows.Forms
[Windows.Forms.Application]::EnableVisualStyles()
[Windows.Forms.Application]::SetCompatibleTextRenderingDefault($false)
$assembly = [Reflection.Assembly]::LoadFile($env:CAR_EXE)
$F = $assembly.GetType('CodexAutoResume.SettingsForm', $true)
$PB = $assembly.GetType('CodexAutoResume.PersistentBridge', $true)
$BT = $assembly.GetType('CodexAutoResume.Bridge', $true)
$J = $assembly.GetType('CodexAutoResume.Json', $true)
$flags = [Reflection.BindingFlags]'Instance,Static,NonPublic,Public'
$utf8 = New-Object Text.UTF8Encoding $false
# Returned whole (`,`): PowerShell would otherwise hand a dictionary on as its entries.
function Parse($name) { return ,$J.GetMethod('Parse', $flags).Invoke($null, [object[]]@([IO.File]::ReadAllText((Join-Path $env:CAR_WORK $name), $utf8))) }
function Call($name, $target, $arguments) {
  $m = $F.GetMethod($name, $flags)
  if (-not $m) { throw ('no ' + $name) }
  $given = New-Object 'object[]' $arguments.Count
  for ($i = 0; $i -lt $arguments.Count; $i++) {
    $value = $arguments[$i]
    if ($null -ne $value -and $value -is [psobject]) { $value = $value.PSObject.BaseObject }
    $given[$i] = $value
  }
  return $m.Invoke($target, $given)
}
# A bridge rooted where nothing is, and the window's own `auditing`, so nothing is asked of anything.
[string]$nowhere = Join-Path $env:CAR_WORK 'nowhere'
$bridge = $BT.GetConstructor($flags, $null, [type[]]@([string]), $null).Invoke([object[]]@($nowhere))
$persistent = $PB.GetConstructor($flags, $null, [type[]]@([string], $BT), $null).Invoke([object[]]@($nowhere, $bridge))
$catalog = (Parse 'strings.json')['strings']
$make = $F.GetConstructor($flags, $null, [type[]]@($PB, [Collections.Generic.Dictionary[string,object]], [Drawing.Font]), $null)
$form = $make.Invoke([object[]]@($persistent, $catalog, [Drawing.SystemFonts]::MessageBoxFont))
$F.GetField('auditing', $flags).SetValue($form, $true)
$form.TopLevel = $false
$out = @{}

# The Log dialog: 200 lines, then the person scrolls up and picks one, then the five-second look.
$dialog = Call 'BuildLogs' $form @()
$dialog.TopLevel = $false
Call 'Materialise' $null @($dialog) | Out-Null
$dialog.PerformLayout()
$view = $F.GetField('logsList', $flags).GetValue($form)
$count = New-Object Windows.Forms.Label
function Lines($first, $last) {
  $lines = New-Object 'System.Collections.Generic.List[object]'
  for ($i = $first; $i -le $last; $i++) {
    $line = New-Object 'System.Collections.Generic.Dictionary[string,object]'
    $line['at'] = '2026-09-27 14:00:00'
    $line['text'] = 'thread 00000000-0000-4000-8000-00000000de30: waiting for reset (' + $i + ')'
    $lines.Add($line.PSObject.BaseObject)
  }
  $result = New-Object 'System.Collections.Generic.Dictionary[string,object]'
  $result['lines'] = $lines.PSObject.BaseObject
  $result['matched'] = [double]($last - $first + 1)
  return ,$result.PSObject.BaseObject
}
function Seen() { return @{ top = $view.TopItem.SubItems[1].Text; selected = @($view.SelectedItems | ForEach-Object { $_.SubItems[1].Text }); count = $view.Items.Count } }
Call 'ShowLogLines' $form @($view, $count, (Lines 0 199), $false) | Out-Null
$out.first = Seen
$view.TopItem = $view.Items[50]
$view.Items[60].Selected = $true
Call 'ShowLogLines' $form @($view, $count, (Lines 0 199), $true) | Out-Null
$out.same = Seen
Call 'ShowLogLines' $form @($view, $count, (Lines 1 200), $true) | Out-Null
$out.newer = Seen
$view.EnsureVisible($view.Items.Count - 1)
Call 'ShowLogLines' $form @($view, $count, (Lines 2 201), $true) | Out-Null
$out.following = Seen
$view.TopItem = $view.Items[0]
Call 'ShowLogLines' $form @($view, $count, (Lines 2 201), $false) | Out-Null
$out.searched = Seen
$dialog.Dispose()

# Settings > Notifications at the defaults, with When a conversation needs you on, and with notifications off.
$form.ClientSize = New-Object Drawing.Size 1100, 760
Call 'BuildEditors' $form @((Parse 'schema.json'), (Parse 'defaults.json')) | Out-Null
$editors = $F.GetField('editors', $flags).GetValue($form)
$parts = @('notify_needs_you_invalid', 'notify_needs_you_policy', 'notify_needs_you_auth', 'notify_needs_you_failure', 'stall_after', 'needs_you_sound')
function Live() { $live = @{}; foreach ($name in @('notify_needs_you') + $parts) { $live[$name] = [bool]$editors[$name].Enabled }; return $live }
$out.defaults = Live
# How far in each starts in the card: the row a drop-down stands in, and a check box itself.
$card = $editors['notify_needs_you'].Parent
$out.indent = @{}
foreach ($name in @('notify_needs_you') + $parts) {
  $c = $editors[$name]
  while ($null -ne $c.Parent -and $c.Parent -ne $card) { $c = $c.Parent }
  $out.indent[$name] = [int]$c.Margin.Left
}
$editors['notify_needs_you'].Checked = $true
$out.told = Live
$editors['notifications'].Checked = $false
$out.silent = Live

# What the Overview and Diagnostics say of a watcher that stopped, and of a weekly limit read before its reset.
$now = [double]$env:CAR_NOW
# Values as the window's own parser gives them: the objects themselves, never PowerShell's wrappers around them.
function Base($value) { if ($null -ne $value -and $value -is [psobject]) { return ,$value.PSObject.BaseObject }; return ,$value }
function Map($pairs) { $map = New-Object 'System.Collections.Generic.Dictionary[string,object]'; foreach ($k in $pairs.Keys) { $map[$k] = (Base $pairs[$k]) }; return ,$map.PSObject.BaseObject }
$out.stopped = @{}
foreach ($ended in @('memory_guard', 'unexpected')) {
  $watcher = Map @{ ended = $ended; ended_at = ($now - 2 * 86400) }
  $out.stopped[$ended] = @([string](Call 'StoppedText' $form @($watcher, $false)), [string](Call 'StoppedText' $form @($watcher, $true)))
}
$out.weekly = @{}
foreach ($case in @(@('ahead', 3), @('past', -3))) {
  $window = Map @{ bucket = 'codex'; window = 'secondary'; used_percent = [double]100; window_minutes = [double]10080; reset_at = ($now + $case[1] * 86400) }
  $windows = New-Object 'System.Collections.Generic.List[object]'
  $windows.Add((Base $window))
  $reading = Map @{ read_at = ($now - 10 * 86400); windows = $windows.PSObject.BaseObject }
  $block = Call 'WeeklyBlock' $form @($reading)
  $F.GetField('snapshot', $flags).SetValue($form, (Map @{ status = (Map @{ watcher = (Map @{ usage = $reading }) }) }))
  $note = Call 'WithUsage' $form @((Map @{ category = 'usage_limit' }), $null)
  $out.weekly[$case[0]] = @{ block = $block; note = $note }
}
$form.Dispose()
$out | ConvertTo-Json -Depth 6 -Compress
"""

PARTS = ("notify_needs_you_invalid", "notify_needs_you_policy", "notify_needs_you_auth", "notify_needs_you_failure",
         "stall_after", "needs_you_sound")


@unittest.skipUnless(CSC.is_file() and POWERSHELL.is_file(), "needs the in-box compiler and PowerShell")
class WindowTests(unittest.TestCase):
    """The window built and never shown, asked what only a built window can answer."""

    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        work = Path(cls.folder.name)
        exe = work / "CodexAutoResumeSettings.exe"
        subprocess.run([str(CSC), "/nologo", "/target:winexe", "/platform:x64", "/out:" + str(exe),
                        "/reference:System.dll", "/reference:System.Drawing.dll",
                        "/reference:System.Windows.Forms.dll", *[str(path) for path in guiscan.sources()]],
                       check=True, capture_output=True, timeout=300,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        (work / "schema.json").write_text(json.dumps(settings.describe()), encoding="utf-8")
        (work / "defaults.json").write_text(json.dumps(settings.defaults()), encoding="utf-8")
        (work / "strings.json").write_text(json.dumps({"strings": l10n.catalog("en")}, ensure_ascii=False),
                                           encoding="utf-8")
        probe = work / "probe.ps1"
        probe.write_text(WINDOW_PROBE, encoding="utf-8")
        cls.now = time.time()
        result = subprocess.run(
            [str(POWERSHELL), "-STA", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(probe)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            env=dict(os.environ, CAR_EXE=str(exe), CAR_WORK=str(work), CAR_NOW=repr(cls.now)))
        cls.result = result
        cls.answer = json.loads(result.stdout) if result.returncode == 0 and result.stdout.strip() else {}

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def setUp(self):
        if not self.answer:
            self.fail("the probe did not run: " + (self.result.stderr or self.result.stdout)[-2000:])

    @staticmethod
    def line(number):
        return "thread 00000000-0000-4000-8000-00000000de30: waiting for reset (%d)" % number

    def test_the_logs_five_second_look_leaves_the_list_where_the_person_left_it(self):
        """It cleared the list and scrolled to the newest line every five seconds, so nothing older could be read and
        what was selected was dropped (the review, reproduced). Now the same lines leave it as it is, new ones keep
        the line at the top and what is selected, and the newest is followed only while it was in view."""
        answer = self.answer
        self.assertEqual(answer["first"]["count"], 200)
        self.assertNotEqual(answer["first"]["top"], self.line(0), "the first answer shows the newest")
        self.assertEqual((answer["same"]["top"], answer["same"]["selected"]), (self.line(50), [self.line(60)]))
        self.assertEqual((answer["newer"]["top"], answer["newer"]["selected"]), (self.line(50), [self.line(60)]))
        self.assertNotEqual(answer["following"]["top"], self.line(50), "the newest was in view, and is followed")
        self.assertNotEqual(answer["searched"]["top"], self.line(2), "a search shows the newest")

    def test_the_needs_you_notices_parts_are_live_only_while_it_is_told(self):
        """At the defaults When a conversation needs you is off, and its four kinds, its stall and its sound stood
        checked, enabled and at its own indent under it - read as on, while none is ever raised (the review). They
        follow it now, as the events follow the notifications switch, one step further in."""
        self.assertTrue(self.answer["defaults"]["notify_needs_you"])
        for name in PARTS:
            with self.subTest(name):
                self.assertFalse(self.answer["defaults"][name], "live while the notice is off")
                self.assertTrue(self.answer["told"][name], "not live while the notice is on")
                self.assertFalse(self.answer["silent"][name], "live while notifications are off")
                self.assertGreater(self.answer["indent"][name], self.answer["indent"]["notify_needs_you"])
        self.assertFalse(self.answer["silent"]["notify_needs_you"])

    def test_right_now_says_how_a_watcher_stopped_in_its_one_line_and_diagnostics_says_when(self):
        english = l10n.catalog("en")
        for ended in ("memory_guard", "unexpected"):
            key = "stopped_memory_guard" if ended == "memory_guard" else "stopped_unexpectedly"
            short, full = self.answer["stopped"][ended]
            with self.subTest(ended):
                self.assertEqual(short, english["overview." + key])
                self.assertEqual(full, english["diag." + key].replace("{time}", time.strftime(
                    "%Y-%m-%d %H:%M", time.localtime(self.now - 2 * 86400))))

    def test_a_weekly_limit_is_said_only_while_its_reset_is_ahead_with_the_credit_sentence(self):
        """A reading older than its weekly reset said "It resets <a time already past>" as if current (J7), and the
        fixed sentence that Codex's /usage can redeem a reset credit (decision C13) was said nowhere."""
        english = l10n.catalog("en")
        ahead, past = self.answer["weekly"]["ahead"], self.answer["weekly"]["past"]
        self.assertTrue(ahead["block"].startswith(english["usage.weekly_block"].split("{time}")[0]))
        self.assertIn(english["usage.weekly_credit"], ahead["note"].splitlines())
        self.assertIsNone(past["block"])
        self.assertNotIn(english["usage.weekly_credit"], past["note"])
        self.assertNotIn(english["usage.weekly_block"].split("{time}")[0], past["note"])
        self.assertIn("Codex usage, read 10d ago", past["note"], "what was read is still said, with its age")


class SourceTests(unittest.TestCase):
    """What the menus and Diagnostics offer, and where: the new after what there was."""

    def test_the_row_menu_ends_with_a_conversations_message_and_postpone_with_dont_postpone(self):
        menu = guiscan.member_body("SettingsForm", "FillRowMenu")
        order = [menu.index(text) for text in ('"menu.postpone"', '"menu.unpostpone"', '"action.continue"',
                                               '"menu.tier"', '"menu.project_never"', '"menu.conversation_message"')]
        self.assertEqual(order, sorted(order))
        self.assertIn("IsDemo(row)", menu, "nothing is offered on a made-up row")

    def test_diagnostics_adds_its_tools_after_the_five_and_its_fact_after_the_memory(self):
        page = guiscan.member_body("SettingsForm", "BuildDiagnostics")
        shown = page[page.index("foreach (Button button in new[] {"):]
        # v0.6.12: Install another version... after them, last (tests/test_gui_versions.py).
        order = [shown.index(text) for text in ("stopButton,", '"action.search_logs"', "demoButton,", "versionsButton })")]
        self.assertEqual(order, sorted(order), "the Tools card's buttons, in the order they are added")
        self.assertLess(page.index('"diag.memory_peak"'), page.index('"diag.state_access"'))

    def test_no_action_reaches_a_made_up_row(self):
        for member in ("ToggleAutoResume", "ShowTimeline", "UpdatePendingButtons", "UpdateHistoryButtons"):
            with self.subTest(member):
                self.assertIn("IsDemo(row)", guiscan.member_body("SettingsForm", member))


if __name__ == "__main__":
    unittest.main()
