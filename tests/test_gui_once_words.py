r"""v0.6.16-beta.3: words for this time in the Dashboard - the Pending row's menu, the dialog, and the row's note.

A waiting task's menu on Pending offers "Add words for this time..." - or, when it has some, "Change words for this
time..." and "Remove words for this time" - after "Message for this conversation...". The dialog is a small one in
the window's theme (no icon, as every small dialog), with a text box, the Custom message's 2000-character count, the
Custom message's refusal in its own words, the Preview of the next continuation with the words after it, and Save
and Cancel. The listing says only whether a row has words (`once_words`), never what: the dialog reads them through
the bridge, and the row says so in its "Why it is waiting" note - no new column, nothing moved.

Held through the compiled window (WindowTests: the menu as FillRowMenu fills it, the dialog as BuildOnceWords builds
it, the note) and its source (SourceTests).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import guiscan
from codex_auto_resume import l10n

CSC = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe"
POWERSHELL = (Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
              / "WindowsPowerShell" / "v1.0" / "powershell.exe")
THREAD = "0a1b2c3d-0001-7000-8000-000000000001"
KEY = "a" * 64

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
[string]$nowhere = Join-Path $env:CAR_WORK 'nowhere'
$bridge = $BT.GetConstructor($flags, $null, [type[]]@([string]), $null).Invoke([object[]]@($nowhere))
$persistent = $PB.GetConstructor($flags, $null, [type[]]@([string], $BT), $null).Invoke([object[]]@($nowhere, $bridge))
$catalog = (Parse 'strings.json')['strings']
$make = $F.GetConstructor($flags, $null, [type[]]@($PB, [Collections.Generic.Dictionary[string,object]], [Drawing.Font]), $null)
$form = $make.Invoke([object[]]@($persistent, $catalog, [Drawing.SystemFonts]::MessageBoxFont))
$F.GetField('auditing', $flags).SetValue($form, $true)
$form.TopLevel = $false
$out = @{ menu = @{}; can = @{}; has = @{}; note = @{} }

$rows = Parse 'rows.json'
# The Pending page, and with it its row menu, is built the first time it is shown.
$form.ClientSize = New-Object Drawing.Size 1100, 760
Call 'ShowPage' $form @('pending') | Out-Null
$menu =$F.GetField('pendingMenu', $flags).GetValue($form)
foreach ($name in $rows.Keys) {
  $row = $rows[$name]
  $filled = [bool](Call 'FillRowMenu' $form @($row))
  $items = @()
  foreach ($item in $menu.Items) {
    if ($item -is [Windows.Forms.ToolStripMenuItem]) { $items += ,@([string]$item.Text, [bool]$item.Enabled) }
  }
  $out.menu[$name] = @{ filled = $filled; items = $items }
  $out.can[$name] = [bool](Call 'CanAddOnceWords' $null @($row, $true))
  $out.has[$name] = [bool](Call 'HasOnceWords' $null @($row))
  $out.note[$name] = [string](Call 'WithOnceWords' $null @($row, 'Waiting for the reset', 'WORDS'))
}
$out.can['busy'] = [bool](Call 'CanAddOnceWords' $null @($rows['waiting'], $false))
$out.note['alone'] = [string](Call 'WithOnceWords' $null @($rows['worded'], $null, 'WORDS'))

$dialog = Call 'BuildOnceWords' $form @($rows['worded'], "Then run the tests.`nPlease.")
$area = $F.GetField('onceWordsArea', $flags).GetValue($form)
$typed = [string]$area.GetType().GetField('Box', $flags).GetValue($area).Text
$dialog.TopLevel = $false
Call 'Materialise' $null @($dialog) | Out-Null
$dialog.PerformLayout()
$labels = @()
$buttons = @()
function Walk($control) {
  foreach ($child in $control.Controls) {
    if ($child -is [Windows.Forms.Button]) { $script:buttons += [string]$child.Text }
    elseif ($child -is [Windows.Forms.Label]) { $script:labels += [string]$child.Text }
    Walk $child
  }
}
Walk $dialog
$out.dialog = @{ title = [string]$dialog.Text; showIcon = [bool]$dialog.ShowIcon; taskbar = [bool]$dialog.ShowInTaskbar;
                 text = $typed; labels = $labels; buttons = $buttons;
                 inside = [bool]($area.Right -le $dialog.ClientSize.Width) }
$dialog.Dispose()
$form.Dispose()
$out | ConvertTo-Json -Depth 6 -Compress
"""

WAITING = {"interruption_id": KEY, "thread_id": THREAD, "code": "waiting_reset", "state": "waiting_reset",
           "category": "usage_limit", "cancel_requested": False, "terminal": False, "once_words": False,
           "name": "example-project"}
ROWS = {
    "waiting": WAITING,
    "worded": dict(WAITING, once_words=True),
    "cancelled": dict(WAITING, cancel_requested=True),
    "sent": dict(WAITING, code="submitted", state="queued"),
    "sent_worded": dict(WAITING, code="submitted", state="queued", once_words=True),
}


@unittest.skipUnless(CSC.is_file() and POWERSHELL.is_file(), "needs the in-box compiler and PowerShell")
class WindowTests(unittest.TestCase):
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
        (work / "strings.json").write_text(json.dumps({"strings": l10n.catalog("en")}, ensure_ascii=False),
                                           encoding="utf-8")
        (work / "rows.json").write_text(json.dumps(ROWS), encoding="utf-8")
        probe = work / "probe.ps1"
        probe.write_text(WINDOW_PROBE, encoding="utf-8")
        result = subprocess.run(
            [str(POWERSHELL), "-STA", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(probe)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            env=dict(os.environ, CAR_EXE=str(exe), CAR_WORK=str(work)))
        cls.result = result
        cls.answer = json.loads(result.stdout) if result.returncode == 0 and result.stdout.strip() else {}
        cls.english = l10n.catalog("en")

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def setUp(self):
        if not self.answer:
            self.fail("the probe did not run: " + (self.result.stderr or self.result.stdout)[-2000:])

    def items(self, name):
        return [tuple(item) for item in self.answer["menu"][name]["items"]]

    def test_a_waiting_task_offers_to_add_words_last_after_the_conversations_message(self):
        items = self.items("waiting")
        texts = [text for text, _ in items]
        self.assertEqual(texts[-2:], [self.english["menu.conversation_message"], self.english["menu.once_words_add"]])
        self.assertIn((self.english["menu.once_words_add"], True), items)
        self.assertNotIn(self.english["menu.once_words_remove"], texts)

    def test_a_task_with_words_offers_to_change_and_remove_them(self):
        texts = [text for text, _ in self.items("worded")]
        self.assertEqual(texts[-3:], [self.english["menu.conversation_message"], self.english["menu.once_words_change"],
                                      self.english["menu.once_words_remove"]])
        self.assertNotIn(self.english["menu.once_words_add"], texts)
        self.assertEqual(dict(self.items("worded"))[self.english["menu.once_words_change"]], True)

    def test_words_are_added_only_to_a_task_that_still_waits_and_taking_them_away_always_works(self):
        self.assertEqual(self.answer["can"], {"waiting": True, "worded": True, "cancelled": False, "sent": False,
                                              "sent_worded": False, "busy": False})
        self.assertEqual(dict(self.items("cancelled"))[self.english["menu.once_words_add"]], False)
        self.assertEqual(dict(self.items("sent"))[self.english["menu.once_words_add"]], False)
        self.assertEqual(dict(self.items("sent_worded"))[self.english["menu.once_words_remove"]], True)

    def test_the_row_says_it_has_words_in_its_note_and_nothing_else_changes(self):
        self.assertEqual(self.answer["has"]["worded"], True)
        self.assertEqual(self.answer["has"]["waiting"], False)
        self.assertEqual(self.answer["note"]["worded"], "Waiting for the reset\nWORDS")
        self.assertEqual(self.answer["note"]["waiting"], "Waiting for the reset")
        self.assertEqual(self.answer["note"]["alone"], "WORDS")

    def test_the_dialog_is_a_small_one_with_the_words_their_count_a_preview_and_save_and_cancel(self):
        dialog = self.answer["dialog"]
        self.assertTrue(dialog["title"].startswith(self.english["once.title"] + " - "))
        self.assertIn("example-project", dialog["title"])
        self.assertFalse(dialog["showIcon"], "a small dialog shows no icon")
        self.assertFalse(dialog["taskbar"])
        self.assertEqual(dialog["text"], "Then run the tests.\r\nPlease.")
        self.assertIn(self.english["once.help"], dialog["labels"])
        self.assertIn(self.english["custom.placeholders"], dialog["labels"])
        self.assertIn("27 / 2000", dialog["labels"], "the Custom message's count, as the settings layer counts it")
        self.assertEqual(sorted(dialog["buttons"]), sorted([self.english["action.save"], self.english["action.cancel"]]))
        self.assertTrue(dialog["inside"], "the text box stays inside the dialog")


class SourceTests(unittest.TestCase):
    """What the window asks the bridge, and what it never shows."""

    def test_the_dialog_reads_and_writes_through_the_bridges_once_words_alone(self):
        edit = guiscan.member_body("SettingsForm", "EditOnceWords")
        self.assertIn('CallAsync("once-words"', edit)
        self.assertNotIn('\\"text\\":', edit, "opening the dialog only reads")
        save = guiscan.member_body("SettingsForm", "SaveOnceWords")
        for part in ('CallAsync("once-words"', '\\"interruption_id\\":', '\\"thread_id\\":', '\\"text\\":'):
            self.assertIn(part, save)
        self.assertNotIn("WakeEvent", save)

    def test_the_preview_is_the_bridges_with_the_words_and_the_refusal_is_the_custom_messages(self):
        build = guiscan.member_body("SettingsForm", "BuildOnceWords")
        self.assertIn('bridge.Call("preview-continuation"', build)
        self.assertIn("bridge.Queue(delegate", build, "a read the bridge counts while it runs")
        self.assertIn('\\"once_words\\":', build)
        self.assertIn("RefusalText(result)", build)
        self.assertIn("UpdateCount(area, count)", build)
        self.assertIn("Soft.DialogBar(dialog)", build, "and so no icon in its title bar (test_gui_dialog_icons)")

    def test_the_list_refills_when_a_row_gains_or_loses_words_and_the_note_follows(self):
        self.assertIn("HasOnceWords(row)", guiscan.member_body("SettingsForm", "ListSignature"))
        self.assertIn("WithOnceWords(row", guiscan.member_body("SettingsForm", "ShowExplain"))

    def test_the_layout_audit_builds_the_dialog(self):
        self.assertIn("BuildOnceWords(row", guiscan.member_body("SettingsForm", "AuditOnceWords"))

    def test_no_made_up_row_is_offered_them(self):
        self.assertIn("IsDemo(row)", guiscan.member_body("SettingsForm", "CanAddOnceWords"))
        self.assertIn("IsDemo(row)", guiscan.member_body("SettingsForm", "EditOnceWords"))


if __name__ == "__main__":
    unittest.main()
