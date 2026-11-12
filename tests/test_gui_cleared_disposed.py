r"""A rebuilt card disposes what it removed, so no window handle is parked for the life of the process (v0.6.23, the
windows audit's G4).

ControlCollection.Clear removes and does not dispose: a removed control whose handle was made keeps it, re-parented
to the parking window, with everything it holds. The Overview's Recently finished (FillRecent, rebuilt on a changed
history, and ClearRecent, on every read that failed) and the Codex homes' rows (ShowHomes) collect what they hold,
clear, then dispose it (ClearDisposing) - as the Advanced page's cards and the compatibility card already did.

Held by the handles themselves: each card's controls are given their handles, the card is rebuilt, and every
control it held before must be disposed with no handle left; with Clear() alone they all keep theirs.

The window is built and never shown (its own `auditing`, a bridge rooted where nothing is).

GUI test module: compiles the window, so it runs on its own (gui_lock.sh).
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
from codex_auto_resume import l10n
from test_gui_layout import fullest_snapshot

CSC = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe"
POWERSHELL = (Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
              / "WindowsPowerShell" / "v1.0" / "powershell.exe")
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

PROBE = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Windows.Forms
# A probe never shows a dialog: an exception is thrown here, never put in a window on the screen.
[Windows.Forms.Application]::SetUnhandledExceptionMode([Windows.Forms.UnhandledExceptionMode]::ThrowException)
[Windows.Forms.Application]::EnableVisualStyles()
[Windows.Forms.Application]::SetCompatibleTextRenderingDefault($false)
$assembly = [Reflection.Assembly]::LoadFile($env:CAR_EXE)
$script:F = $assembly.GetType('CodexAutoResume.SettingsForm', $true)
$PB = $assembly.GetType('CodexAutoResume.PersistentBridge', $true)
$BT = $assembly.GetType('CodexAutoResume.Bridge', $true)
$J = $assembly.GetType('CodexAutoResume.Json', $true)
$script:flags = [Reflection.BindingFlags]'Instance,Static,NonPublic,Public'
$utf8 = New-Object Text.UTF8Encoding $false
function Read($name) { return [IO.File]::ReadAllText((Join-Path $env:CAR_WORK $name), $utf8) }
function Parse($name) { return ,$J.GetMethod('Parse', $script:flags).Invoke($null, [object[]]@((Read $name))) }
function Call($name, $target, $arguments) {
  $m = $script:F.GetMethod($name, $script:flags)
  if (-not $m) { throw ('no ' + $name) }
  return $m.Invoke($target, [object[]]$arguments)
}
function Field($name) { return $script:F.GetField($name, $script:flags).GetValue($script:form) }
function SetField($name, $value) { $script:F.GetField($name, $script:flags).SetValue($script:form, $value) }
# Every control `parent` holds, each given its handle as a shown window gives it one.
function Held($parent) {
  $found = New-Object 'System.Collections.Generic.List[object]'
  foreach ($child in $parent.Controls) { $null = $child.Handle; $found.Add($child) }
  return ,$found
}
# Of the controls held before a rebuild: how many there were with a handle, how many are not disposed, how many
# keep a handle.
function Left($before) {
  $handled = 0; $alive = 0; $kept = 0
  foreach ($control in $before) {
    $handled++
    if (-not $control.IsDisposed) { $alive++ }
    if ($control.IsHandleCreated) { $kept++ }
  }
  return @($handled, $alive, $kept)
}
try {
  [string]$nowhere = Join-Path $env:CAR_WORK 'nowhere'
  $bridge = $BT.GetConstructor($script:flags, $null, [type[]]@([string]), $null).Invoke([object[]]@($nowhere))
  $persistent = $PB.GetConstructor($script:flags, $null, [type[]]@([string], $BT), $null).Invoke([object[]]@($nowhere, $bridge))
  $catalog = (Parse 'strings.json')['strings']
  $make = $script:F.GetConstructor($script:flags, $null, [type[]]@($PB, [Collections.Generic.Dictionary[string,object]], [Drawing.Font]), $null)
  $script:form = $make.Invoke([object[]]@($persistent, $catalog, [Drawing.SystemFonts]::MessageBoxFont))
  SetField 'auditing' $true
  $script:form.TopLevel = $false
  $null = $script:form.Handle
  Call 'Materialise' $null @($script:form) | Out-Null
  $out = @{}

  # Recently finished: a changed history rebuilds it; a read that failed clears it.
  Call 'ShowPage' $script:form @('overview') | Out-Null
  $grid = Field 'recentGrid'
  if ($null -eq $grid) { throw 'no recentGrid' }
  $null = $grid.Handle
  Call 'FillRecent' $script:form @(,(Parse 'history-a.json')) | Out-Null
  $before = Held $grid
  Call 'FillRecent' $script:form @(,(Parse 'history-b.json')) | Out-Null
  $out.rebuilt = Left $before
  $before = Held $grid
  Call 'ClearRecent' $script:form @('unreadable') | Out-Null
  $out.cleared = Left $before
  $out.recent_after = $grid.Controls.Count

  # The Codex homes' rows, rebuilt when what they show changed: their card built as the Settings page builds it
  # (BuildHomes), into a stack of its own on the window, since the page's editors wait for the settings read.
  # Made by the constructor, not New-Object: New-Object's output is a PSObject, which Invoke cannot pass as a TableLayoutPanel.
  $stack = [Windows.Forms.TableLayoutPanel]::new()
  $script:form.Controls.Add($stack)
  $null = $stack.Handle
  Call 'BuildHomes' $script:form @(,$stack) | Out-Null
  $rows = Field 'homesRows'
  if ($null -eq $rows) { throw 'no homesRows' }
  $null = $rows.Handle
  Call 'ApplyHomesStatus' $script:form @(,(Parse 'homes-a.json')) | Out-Null
  $before = Held $rows
  Call 'ApplyHomesStatus' $script:form @(,(Parse 'homes-b.json')) | Out-Null
  $out.homes = Left $before
  $out.homes_after = $rows.Controls.Count

  $out | ConvertTo-Json -Depth 4 -Compress
} catch {
  $thrown = $_.Exception
  while ($thrown.InnerException) { $thrown = $thrown.InnerException }
  [Console]::Error.WriteLine($thrown.ToString())
  exit 3
}
"""


def homes(alias: str) -> dict:
    return {"codex_homes": {"homes": [{"key": "", "alias": "", "path": r"C:\Users\ExampleUser\.codex", "state": "watched"},
                                      {"key": "work", "alias": alias, "path": r"D:\Work\.codex", "state": "watched"}]},
            "settings": {}}


@unittest.skipUnless(CSC.is_file() and POWERSHELL.is_file(), "needs the in-box compiler and PowerShell")
class ClearedDisposedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        work = Path(cls.folder.name)
        exe = work / "CodexAutoResumeSettings.exe"
        subprocess.run([str(CSC), "/nologo", "/target:winexe", "/platform:x64", "/out:" + str(exe),
                        "/reference:System.dll", "/reference:System.Drawing.dll",
                        "/reference:System.Windows.Forms.dll", *[str(path) for path in guiscan.sources()]],
                       check=True, capture_output=True, timeout=300, creationflags=NO_WINDOW)
        (work / "strings.json").write_text(json.dumps({"strings": l10n.catalog("en")}, ensure_ascii=False),
                                           encoding="utf-8")
        history = fullest_snapshot(time.time())["history"]
        changed = copy.deepcopy(history)
        for row in changed:
            row["name"] = "Another " + str(row.get("name") or "conversation")
        (work / "history-a.json").write_text(json.dumps(history, ensure_ascii=False), encoding="utf-8")
        (work / "history-b.json").write_text(json.dumps(changed, ensure_ascii=False), encoding="utf-8")
        (work / "homes-a.json").write_text(json.dumps(homes("Work")), encoding="utf-8")
        (work / "homes-b.json").write_text(json.dumps(homes("Work again")), encoding="utf-8")
        probe = work / "probe.ps1"
        probe.write_text(PROBE, encoding="utf-8")
        cls.result = subprocess.run(
            [str(POWERSHELL), "-STA", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(probe)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600, creationflags=NO_WINDOW,
            env=dict(os.environ, CAR_EXE=str(exe), CAR_WORK=str(work)))
        cls.answer = json.loads(cls.result.stdout) if cls.result.returncode == 0 and cls.result.stdout.strip() else {}

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def setUp(self):
        if not self.answer:
            self.fail("the probe did not run: " + (self.result.stderr or self.result.stdout)[-2000:])

    def assertNoneLeft(self, part):
        handled, alive, kept = self.answer[part]
        self.assertGreater(handled, 0, "the card held controls with handles before it was rebuilt")
        self.assertEqual((alive, kept), (0, 0), "%d of %d removed controls not disposed, %d keep a handle"
                         % (alive, handled, kept))

    def test_recently_finished_rebuilt_disposes_what_it_held(self):
        """Fails with FillRecent's Clear() alone: every name and outcome label keeps its handle."""
        self.assertNoneLeft("rebuilt")

    def test_recently_finished_cleared_disposes_what_it_held(self):
        """Fails with ClearRecent's Clear() alone."""
        self.assertNoneLeft("cleared")
        self.assertEqual(self.answer["recent_after"], 0)

    def test_the_homes_rows_rebuilt_dispose_what_they_held(self):
        """Fails with ShowHomes' Clear() alone: each line, its buttons and their row keep their handles."""
        self.assertNoneLeft("homes")
        self.assertGreater(self.answer["homes_after"], 0)


class SourceTests(unittest.TestCase):
    def test_no_rebuild_here_clears_without_disposing(self):
        for member, held in (("FillRecent", "recentGrid"), ("ClearRecent", "recentGrid"), ("ShowHomes", "homesRows")):
            with self.subTest(member=member):
                body = guiscan.member_body("SettingsForm", member)
                self.assertIn("ClearDisposing(%s);" % held, body)
                self.assertNotIn("%s.Controls.Clear();" % held, body)
        clear = guiscan.member_body("SettingsForm", "ClearDisposing")
        self.assertLess(clear.index("parent.Controls.Clear();"), clear.index("control.Dispose();"))


if __name__ == "__main__":
    unittest.main()
