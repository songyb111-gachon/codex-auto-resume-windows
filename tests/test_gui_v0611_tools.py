r"""v0.6.11: the Dashboard's own tools - Don't postpone, a conversation's message, the log, the state
folder's access and Show me what happens - held through the compiled window's own static methods.

What each decides is a static method so it can be asked without a window: whether Don't postpone
is offered for a row (only a person's postponement still ahead, never a made-up row), which rows are
made up, how a made-up row joins a list, the word for the state folder, what the log's count line
says, and a conversation's own message read from the settings. The source is read too, for what the
menus and the Diagnostics page offer and in which order - new things after the ones there were.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import guiscan

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
        order = [shown.index(text) for text in ("stopButton,", '"action.search_logs"', "demoButton })")]
        self.assertEqual(order, sorted(order), "the Tools card's buttons, in the order they are added")
        self.assertLess(page.index('"diag.memory_peak"'), page.index('"diag.state_access"'))

    def test_no_action_reaches_a_made_up_row(self):
        for member in ("ToggleAutoResume", "ShowTimeline", "UpdatePendingButtons", "UpdateHistoryButtons"):
            with self.subTest(member):
                self.assertIn("IsDemo(row)", guiscan.member_body("SettingsForm", member))


if __name__ == "__main__":
    unittest.main()
