r"""v0.6.19 (the owner, 2026-10-23: "대기중에서 우클릭 말고도 더블좌클릭도 되게 하는건 어떨까?"): a double left-click on a
Pending row opens the same row menu a right click opens - the same items, for the row double-clicked, which becomes the
chosen one - and a double-click on empty space opens nothing. Right click, Shift+F10, the menu key and Space keep what
they did: the menu opened from the keyboard is still the chosen row's.

The window is built and never shown (its own `auditing`, a bridge rooted where nothing is): OpenRowMenu then fills the
menu as it opens and shows nothing, so this reads exactly what a person would be offered.

GUI test module: compiles the window, so it runs on its own (gui_lock.sh).
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

CSC = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe"
POWERSHELL = (Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
              / "WindowsPowerShell" / "v1.0" / "powershell.exe")

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
function Parse($name) { return ,$J.GetMethod('Parse', $script:flags).Invoke($null, [object[]]@([IO.File]::ReadAllText((Join-Path $env:CAR_WORK $name), $utf8))) }
function Call($name, $target, $arguments) {
  $m = $script:F.GetMethod($name, $script:flags)
  if (-not $m) { throw ('no ' + $name) }
  $given = New-Object 'object[]' $arguments.Count
  for ($i = 0; $i -lt $arguments.Count; $i++) {
    $value = $arguments[$i]
    if ($null -ne $value -and $value -is [psobject]) { $value = $value.PSObject.BaseObject }
    $given[$i] = $value
  }
  return $m.Invoke($target, $given)
}
function Field($name) { return $script:F.GetField($name, $script:flags).GetValue($script:form) }
function Offered() {
  $texts = New-Object 'System.Collections.Generic.List[object]'
  foreach ($item in (Field 'pendingMenu').Items) { if ($item -is [Windows.Forms.ToolStripMenuItem]) { $texts.Add([string]$item.Text) } }
  return ,$texts
}
function Chosen() {
  $list = Field 'pendingList'
  $found = New-Object 'System.Collections.Generic.List[object]'
  for ($i = 0; $i -lt $list.Items.Count; $i++) { if ($list.Items[$i].Selected) { $found.Add([double]$i) } }
  return ,$found
}
try {
  [string]$nowhere = Join-Path $env:CAR_WORK 'nowhere'
  $bridge = $BT.GetConstructor($script:flags, $null, [type[]]@([string]), $null).Invoke([object[]]@($nowhere))
  $persistent = $PB.GetConstructor($script:flags, $null, [type[]]@([string], $BT), $null).Invoke([object[]]@($nowhere, $bridge))
  $catalog = (Parse 'strings.json')['strings']
  $make = $script:F.GetConstructor($script:flags, $null, [type[]]@($PB, [Collections.Generic.Dictionary[string,object]], [Drawing.Font]), $null)
  $script:form = $make.Invoke([object[]]@($persistent, $catalog, [Drawing.SystemFonts]::MessageBoxFont))
  $script:F.GetField('auditing', $script:flags).SetValue($script:form, $true)
  $script:form.TopLevel = $false
  Call 'ShowPage' $script:form @('pending') | Out-Null
  Call 'ApplySnapshot' $script:form @((Parse 'snapshot.json')) | Out-Null
  $list = Field 'pendingList'
  $out = @{ rows = [double]$list.Items.Count }
  $at = New-Object Drawing.Point 8, 8

  # What a right click on row 1 is offered, the menu filled for that row as the right button fills it.
  $out.right = @{ filled = [bool](Call 'FillRowMenu' $script:form @($list.Items[1].Tag)); items = (Offered) }
  (Field 'pendingMenu').Items.Clear()

  # A double left-click on row 1.
  $opened = [bool](Call 'OpenRowMenu' $script:form @($list.Items[1], $at))
  $out.double = @{ opened = $opened; items = (Offered); chosen = (Chosen); left = ($null -eq (Field 'menuRow')) }

  # On empty space: nothing opens, and the menu is left as it was.
  $before = (Offered)
  $out.empty = @{ opened = [bool](Call 'OpenRowMenu' $script:form @($null, $at)); same = ((Offered).Count -eq $before.Count) }

  # From the keyboard, afterwards: the chosen row's, as it always was.
  $list.Items[1].Selected = $false
  $list.Items[2].Selected = $true
  $out.keyboard = @{ filled = [bool](Call 'PrepareRowMenu' $script:form @()); items = (Offered) }
  $out.keyboard_expected = @{ filled = [bool](Call 'FillRowMenu' $script:form @($list.Items[2].Tag)); items = (Offered) }
  $out | ConvertTo-Json -Depth 6 -Compress
} catch {
  $thrown = $_.Exception
  while ($thrown.InnerException) { $thrown = $thrown.InnerException }
  [Console]::Error.WriteLine($thrown.ToString())
  exit 3
}
"""


@unittest.skipUnless(CSC.is_file() and POWERSHELL.is_file(), "needs the in-box compiler and PowerShell")
class DoubleClickTests(unittest.TestCase):
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
        (work / "snapshot.json").write_text(json.dumps(fullest_snapshot(time.time()), ensure_ascii=False),
                                            encoding="utf-8")
        probe = work / "probe.ps1"
        probe.write_text(PROBE, encoding="utf-8")
        result = subprocess.run(
            [str(POWERSHELL), "-STA", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(probe)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            env=dict(os.environ, CAR_EXE=str(exe), CAR_WORK=str(work)))
        cls.result = result
        cls.answer = json.loads(result.stdout) if result.returncode == 0 and result.stdout.strip() else {}

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def setUp(self):
        if not self.answer:
            self.fail("the probe did not run: " + (self.result.stderr or self.result.stdout)[-2000:])

    def test_a_double_click_offers_what_a_right_click_offers_for_that_row(self):
        """Fails with the double-click reverted: the window has no OpenRowMenu, and a double-click opens nothing."""
        answer = self.answer
        self.assertGreaterEqual(answer["rows"], 3)
        self.assertTrue(answer["right"]["filled"])
        self.assertTrue(answer["double"]["opened"])
        self.assertEqual(answer["double"]["items"], answer["right"]["items"])
        self.assertIn(l10n.text("menu.postpone", "en"), answer["double"]["items"])

    def test_the_row_double_clicked_becomes_the_chosen_one_and_is_read_once(self):
        answer = self.answer
        self.assertEqual(answer["double"]["chosen"], [1])
        self.assertTrue(answer["double"]["left"], "the menu read the row it was opened on, and let it go")

    def test_empty_space_opens_nothing(self):
        self.assertEqual(self.answer["empty"], {"opened": False, "same": True})

    def test_the_keyboard_still_opens_the_chosen_rows_menu(self):
        answer = self.answer
        self.assertEqual(answer["keyboard"], answer["keyboard_expected"])


if __name__ == "__main__":
    unittest.main()
