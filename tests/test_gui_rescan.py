r"""v0.6.16 (issue #39): Rescan and reconcile on the Dashboard's Pending page.

A button after Cancel all, in the same row, offered whenever Cancel all is - never for Show me what happens'
made-up row alone. It asks first, in the window's own dialog, then calls the bridge's no-argument `rescan` and says
in the row's note how many were retired, rechecked, left unresolved and changed meanwhile. It sends nothing; the
rules are tests/test_rescan.py's.

Held through the compiled window (WindowTests: the button, its place and the note as RescanNote fills it) and its
source (SourceTests: confirmation before the call, the call itself, when it is offered).
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
from codex_auto_resume import l10n

CSC = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe"
POWERSHELL = (Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
              / "WindowsPowerShell" / "v1.0" / "powershell.exe")

WINDOW_PROBE = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false
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
[string]$nowhere = Join-Path $env:CAR_WORK 'nowhere'
$bridge = $BT.GetConstructor($flags, $null, [type[]]@([string]), $null).Invoke([object[]]@($nowhere))
$persistent = $PB.GetConstructor($flags, $null, [type[]]@([string], $BT), $null).Invoke([object[]]@($nowhere, $bridge))
$catalog = Parse 'strings.json'
$make = $F.GetConstructor($flags, $null, [type[]]@($PB, [Collections.Generic.Dictionary[string,object]], [Drawing.Font]), $null)
$form = $make.Invoke([object[]]@($persistent, $catalog, [Drawing.SystemFonts]::MessageBoxFont))
$F.GetField('auditing', $flags).SetValue($form, $true)
$form.TopLevel = $false
$form.ClientSize = New-Object Drawing.Size 1100, 760
$F.GetMethod('ShowPage', $flags).Invoke($form, [object[]]@('pending')) | Out-Null
$button = $F.GetField('rescanButton', $flags).GetValue($form)
$cancelAll = $F.GetField('cancelAllButton', $flags).GetValue($form)
$row = $button.Parent
$result = Parse 'result.json'
$note = $F.GetMethod('RescanNote', $flags)
$out = @{
  text = [string]$button.Text
  sameRow = [bool]([object]::ReferenceEquals($row, $cancelAll.Parent))
  index = [int]$row.Controls.GetChildIndex($button)
  cancelAllIndex = [int]$row.Controls.GetChildIndex($cancelAll)
  enabled = [bool]$button.Enabled
  note = [string]$note.Invoke($null, [object[]]@([string]$catalog['strings']['result.rescan'], $result))
}
$form.Dispose()
$out | ConvertTo-Json -Depth 4 -Compress
"""


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
        (work / "strings.json").write_text(json.dumps({"ok": True, "language": "en", "strings": l10n.catalog("en")}, ensure_ascii=False),
                                           encoding="utf-8")
        (work / "result.json").write_text(json.dumps({"retired": 2, "rechecked": 3, "unresolved": 1, "changed": 4}),
                                          encoding="utf-8")
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

    def test_the_button_is_after_cancel_all_in_the_same_row(self):
        self.assertEqual(self.answer["text"], self.english["action.rescan"])
        self.assertTrue(self.answer["sameRow"])
        self.assertEqual(self.answer["index"], self.answer["cancelAllIndex"] + 1)

    def test_it_is_not_offered_with_nothing_pending(self):
        self.assertFalse(self.answer["enabled"])

    def test_the_note_says_all_four_counts(self):
        self.assertEqual(self.answer["note"],
                         "Retired: 2 \u00b7 Rechecked: 3 \u00b7 Unresolved: 1 \u00b7 Changed meanwhile: 4")


class SourceTests(unittest.TestCase):
    def test_it_asks_first_then_calls_the_bridges_rescan_with_no_argument(self):
        body = guiscan.member_body("SettingsForm", "Rescan")
        confirm, call = body.index("Confirm("), body.index('CallAsync("rescan", null,')
        self.assertLess(confirm, call, "the person says yes before anything is asked of the bridge")
        self.assertIn('S("confirm.rescan"', body[confirm:call])
        self.assertIn('S("action.rescan"', body[confirm:call], "the dialog's button says what it does")
        self.assertIn("pendingNoteFor = BulkNote", body)
        self.assertIn('S("result.rescan"', body)

    def test_it_is_offered_exactly_when_cancel_all_is(self):
        body = guiscan.member_body("SettingsForm", "UpdatePendingButtons")
        rule = re.search(r"cancelAllButton\.Enabled = (.+);", body).group(1)
        self.assertIn("rescanButton.Enabled = " + rule + ";", body)

    def test_every_fallback_is_the_catalogs_english(self):
        english = l10n.catalog("en")
        body = guiscan.member_body("SettingsForm", "Rescan")
        for key in ("confirm.rescan", "action.rescan", "result.rescan"):
            found = re.search(r'S\("%s",\s*"((?:[^"\\]|\\.)*)"' % re.escape(key), body)
            self.assertIsNotNone(found, key)
            fallback = found.group(1).encode("utf-8").decode("unicode_escape")
            self.assertEqual(fallback, english[key], key)


if __name__ == "__main__":
    unittest.main()
