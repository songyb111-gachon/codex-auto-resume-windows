r"""An unchanged snapshot costs the window nothing (v0.6.9).

The watcher's snapshot arrives every five seconds whether or not anything in it moved, and the window
used to do the same work each time: rewrite every cell of both lists, invalidate them, measure up to
200 rows by 6 columns of text for each - on pages nobody was looking at, because `ApplySnapshot`
writes to every page that has been built - and rebuild the thirteen safety checks of the Pending
page's explain card, handing its parent a full layout. That is the lag the user reported, and none of
it draws anything different: the same rows, the same words, the same checks.

So a fill now happens only when what would be drawn has changed. `FillList` compares a signature of
every row - its cells, the colour its state is drawn in, and its Auto-resume switch - with the one it
filled from last, and `GateList.SetRows` compares the rows it is handed with the ones it holds. This
probe builds the real compiled window off-screen, hands it the same snapshot twice, and reads the two
counters the window keeps of how often it actually filled. Nothing of the real installation is read:
the bridge is rooted where nothing is, and the window is built the way LayoutAudit builds it.

The design is untouched by this: what is drawn is the same, and the pictures in assets/ are
regenerated and compared as always. Speed comes from doing the work once, never from drawing less.
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
GUI = ROOT / "gui"
CSC = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe"
POWERSHELL = (Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
              / "WindowsPowerShell" / "v1.0" / "powershell.exe")

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
$gate = $assembly.GetType('CodexAutoResume.GateList', $true)
$bridgeType = $assembly.GetType('CodexAutoResume.Bridge', $true)
$persistentType = $assembly.GetType('CodexAutoResume.PersistentBridge', $true)
$parse = $assembly.GetType('CodexAutoResume.Json', $true).GetMethod('Parse', $static)
$work = [string]$env:CAR_WORK
$utf8 = New-Object Text.UTF8Encoding $false
function Read-Json([string]$name) { return $parse.Invoke($null, [object[]]@([IO.File]::ReadAllText((Join-Path $work $name), $utf8))) }
function Invoke-Window($target, [string]$name, [object[]]$arguments) {
    $method = @($form.GetMethods($instance) | Where-Object { $_.Name -eq $name -and $_.GetParameters().Count -eq $arguments.Count })[0]
    return $method.Invoke($target, $arguments)
}
function Fills { return ,@([int]$form.GetField('ListFills', $static).GetValue($null), [int]$gate.GetField('GateFills', $static).GetValue($null)) }

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
# Both lists and the explain card exist only once their pages are built, as a person visiting them builds them.
foreach ($page in @('pending', 'history', 'overview')) { $null = Invoke-Window $window 'ShowPage' @($page) }

$snapshot = Read-Json 'snapshot.json'
$out = @{}
$null = Invoke-Window $window 'ApplySnapshot' @($snapshot)
$out.first = Fills
$null = Invoke-Window $window 'ApplySnapshot' @((Read-Json 'snapshot.json'))
$out.again = Fills
$null = Invoke-Window $window 'ApplySnapshot' @((Read-Json 'snapshot.json'))
$out.third = Fills
# A row that moved: the same records with one state changed, which must be drawn again.
$null = Invoke-Window $window 'ApplySnapshot' @((Read-Json 'moved.json'))
$out.moved = Fills
# And the same one twice more, which must not.
$null = Invoke-Window $window 'ApplySnapshot' @((Read-Json 'moved.json'))
$out.settled = Fills
$window.Dispose()
[IO.File]::WriteAllText((Join-Path $work 'result.json'), (ConvertTo-Json $out -Compress -Depth 6), $utf8)
"""


class IdleSnapshotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        work = Path(cls.folder.name)
        exe = work / "CodexAutoResumeSettings.exe"
        subprocess.run([str(CSC), "/nologo", "/target:winexe", "/platform:x64", "/out:" + str(exe),
                        "/reference:System.dll", "/reference:System.Drawing.dll", "/reference:System.Windows.Forms.dll",
                        *[str(path) for path in guiscan.sources()]],
                       check=True, capture_output=True, timeout=300)
        reply = {"ok": True, "language": "en", "strings": l10n.catalog("en"), "endonyms": dict(l10n.ENDONYMS),
                 "preference": "en", "system_language": "en"}
        (work / "strings-en.json").write_text(json.dumps(reply, ensure_ascii=False), encoding="utf-8")
        now = time.time()
        snapshot = fullest_snapshot(now)
        (work / "snapshot.json").write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")
        moved = json.loads(json.dumps(snapshot))
        moved["pending"][0]["code"] = ("waiting_thread" if moved["pending"][0].get("code") != "waiting_thread"
                                       else "waiting_reset")
        (work / "moved.json").write_text(json.dumps(moved, ensure_ascii=False), encoding="utf-8")
        probe = work / "idle.ps1"
        probe.write_text(PROBE, encoding="utf-8")
        cls.result = subprocess.run(
            [str(POWERSHELL), "-STA", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(probe)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600,
            env=dict(os.environ, CAR_EXE=str(exe), CAR_WORK=str(work)))
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

    def test_the_first_snapshot_fills_both_lists_and_the_checks(self):
        lists, gates = self.answer["first"]
        self.assertGreaterEqual(lists, 2, "Pending and History are both filled from the first snapshot")
        self.assertGreaterEqual(gates, 1, "and the safety checks are shown")

    def test_the_same_snapshot_again_fills_nothing(self):
        """Every five seconds, for as long as the window is open, on every page that has been built."""
        self.assertEqual(self.answer["again"], self.answer["first"],
                         "an unchanged snapshot filled a list or rebuilt the checks")
        self.assertEqual(self.answer["third"], self.answer["first"], "and did it again on the next tick")

    def test_a_record_that_changed_is_drawn_again(self):
        lists, gates = self.answer["moved"]
        first_lists, first_gates = self.answer["first"]
        self.assertGreater(lists, first_lists, "a changed state never reached the list")
        self.assertGreaterEqual(gates, first_gates)

    def test_and_then_settles_again(self):
        self.assertEqual(self.answer["settled"], self.answer["moved"],
                         "the window kept filling after the change had been drawn")
