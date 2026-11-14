r"""Pending says nothing is waiting only once a read has said so (v0.6.23, the final's live acceptance).

The Dashboard the setup program reopened after an update opened on Pending, and in its first second showed the header's
Loading... over an empty list that said "Nothing is waiting" - while a recovery was waiting. The page is built before the
first snapshot has answered (ShowPage at Load, ApplySnapshot after), and its empty line was made with the empty list's
words. Until the snapshot is written it now says Loading..., the header's word for the same moment (status.loading); a
snapshot with no rows says Nothing is waiting, one with rows hides the line, as before.

The real compiled window is built as LayoutAudit builds one - a bridge rooted where nothing is, nothing asked, nothing shown -
and its Pending page built before any snapshot and after one.

    PYTHONPATH="src;tests" python -m unittest test_gui_pending_before_read      (a GUI module: gui_lock.sh)
"""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import time
import unittest

from codex_auto_resume import l10n

from test_gui_layout import fullest_snapshot
from test_gui_v0611_access import CSC, POWERSHELL, compile_window, run_probe

PROBE = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Windows.Forms
[Windows.Forms.Application]::SetUnhandledExceptionMode([Windows.Forms.UnhandledExceptionMode]::ThrowException)
$assembly = [Reflection.Assembly]::LoadFile($env:CAR_EXE)
$static = [Reflection.BindingFlags]'Static,NonPublic,Public'
$instance = [Reflection.BindingFlags]'Instance,NonPublic,Public'
$form = $assembly.GetType('CodexAutoResume.SettingsForm', $true)
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
$own = $soft.GetMethod('OwnVisible', $static)
$nowhere = [string](Join-Path $work 'nowhere')
$bridgeType = $assembly.GetType('CodexAutoResume.Bridge', $true)
$persistentType = $assembly.GetType('CodexAutoResume.PersistentBridge', $true)
$three = @($form.GetConstructors($instance) | Where-Object { $_.GetParameters().Count -eq 3 })[0]
function New-Window {
    $once = $bridgeType.GetConstructors($instance)[0].Invoke([object[]]@($nowhere))
    $bridge = $persistentType.GetConstructors($instance)[0].Invoke([object[]]@($nowhere, $once))
    $window = $three.Invoke([object[]]@($bridge, (Read-Json 'strings-en.json'), [Drawing.SystemFonts]::MessageBoxFont))
    $form.GetField('auditing', $instance).SetValue($window, $true)
    return $window
}
function Line($window) {
    $label = Get-Field $window 'pendingEmpty'
    $list = Get-Field $window 'pendingList'
    return @{ text = [string]$label.Text; shown = [bool]$own.Invoke($null, [object[]]@($label)); rows = [int]$list.Items.Count }
}
$out = @{}
# Built before the first read has answered, as a window opened on Pending is; then the read comes, with nothing, and with rows.
$window = New-Window
$null = Invoke-Window $window 'ShowPage' @('pending')
$out.before = Line $window
Invoke-Window $window 'ApplySnapshot' @((Read-Json 'empty.json'))
$out.empty = Line $window
Invoke-Window $window 'ApplySnapshot' @((Read-Json 'snapshot.json'))
$out.rows = Line $window
$window.Dispose()
# Built after a read with nothing: it says so at once.
$window = New-Window
Invoke-Window $window 'ApplySnapshot' @((Read-Json 'empty.json'))
$null = Invoke-Window $window 'ShowPage' @('pending')
$out.builtAfter = Line $window
$window.Dispose()
[IO.File]::WriteAllText((Join-Path $work 'result.json'), (ConvertTo-Json $out -Compress -Depth 4), $utf8)
"""


@unittest.skipUnless(CSC.is_file() and POWERSHELL.is_file(), "needs the in-box compiler and PowerShell")
class PendingBeforeReadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        work = Path(cls.folder.name)
        exe = compile_window(work)
        cls.catalog = l10n.catalog("en")
        reply = {"ok": True, "language": "en", "strings": cls.catalog, "endonyms": dict(l10n.ENDONYMS),
                 "preference": "en", "system_language": "en"}
        (work / "strings-en.json").write_text(json.dumps(reply, ensure_ascii=False), encoding="utf-8")
        (work / "snapshot.json").write_text(json.dumps(fullest_snapshot(time.time()), ensure_ascii=False), encoding="utf-8")
        empty = fullest_snapshot(time.time())
        empty["pending"], empty["history"] = [], []
        (work / "empty.json").write_text(json.dumps(empty, ensure_ascii=False), encoding="utf-8")
        cls.answer = run_probe(PROBE, work, 300, CAR_EXE=str(exe))

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def test_before_the_first_read_the_page_does_not_say_nothing_is_waiting(self):
        before = self.answer["before"]
        self.assertEqual(before["rows"], 0)
        self.assertNotEqual(before["text"], self.catalog["pending.empty"],
                            "nothing has been read yet: a recovery may well be waiting")
        self.assertEqual(before["text"], self.catalog["status.loading"])
        self.assertTrue(before["shown"])

    def test_a_read_with_nothing_waiting_says_so(self):
        for case in ("empty", "builtAfter"):
            with self.subTest(case):
                found = self.answer[case]
                self.assertEqual((found["rows"], found["text"], found["shown"]), (0, self.catalog["pending.empty"], True))

    def test_a_read_with_rows_shows_them_and_no_line(self):
        rows = self.answer["rows"]
        self.assertGreater(rows["rows"], 0)
        self.assertFalse(rows["shown"])


if __name__ == "__main__":
    unittest.main()
