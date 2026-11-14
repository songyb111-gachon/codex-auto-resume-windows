"""v0.6.23 acceptance G1: the setup program run over an older installation, with the watcher not running before it.

What the acceptance saw: the advanced setup program, run through explorer over v0.6.23-beta.2 in Korean, offered
업데이트 on its Options page, and then its progress title read "설치 중" and its Finish page "Codex Auto Resume이
설치되었습니다" - a setup program's window is Mode Install over an installation (InstallerFlow.Upgrade), and only the
Dashboard's own update is Mode Update, which the words were chosen by. The watcher, down before the update, was left
stopped by the v0.6.16 rule (setup --watcher-was-stopped), and setup said so mid-log, yet install.ps1's last word ended
"Nothing else to do." and the Finish page said nothing of it.

Held here:

* SetupSaysLeftStoppedTests - setup's EXIT_LEFT_STOPPED, only for a caller that asks for it
  (CODEX_AUTO_RESUME_SETUP_SAYS_LEFT_STOPPED); every other caller (an older install.ps1, the bootstrap's own calls)
  hears 0 as before. Run with the registry, the Start menu, the sign-in start and the watcher patched out
  (test_plugin.BridgeTests' own guards), against a scratch home.
* LastWordTests - install.ps1's setup call and last word, lifted verbatim and run with setup stubbed: the code is read
  as a success, the variable is set for that one call alone, and the last word says the watcher was left stopped and
  how to start it, not "Nothing else to do".
* WindowWordsTests - compiled into a setup program around a TEST archive (test_installer_window's) and called through
  reflection, with no window shown: the progress title and Finish headline of an update over an older installation,
  a repair, a first installation, an edition change and the Dashboard's update; and the Finish page's line for a
  watcher left stopped, in English and Korean.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import test_plugin
from test_installer import VOICE, block
from test_installer_window import CSC, POWERSHELL, NO_WINDOW, _build, _powershell

ROOT = Path(__file__).resolve().parents[1]
INSTALL = ROOT / "build" / "install" / "install.ps1"
FLOW = (ROOT / "gui" / "InstallerFlow.cs").read_text(encoding="utf-8")
LOCALES = ROOT / "src" / "codex_auto_resume" / "locales"


def left_stopped_line() -> str:
    """InstallerFlow.LeftStoppedLine, read from the window's source: the start of install.ps1's line it looks for."""
    marker = 'internal const string LeftStoppedLine = "'
    start = FLOW.index(marker) + len(marker)
    return FLOW[start:FLOW.index('";', start)]


class SetupSaysLeftStoppedTests(unittest.TestCase):
    """plugin_setup.py's answer for a watcher it left stopped, by who asks."""

    setUp = test_plugin.BridgeTests.setUp
    _close_log_handlers = staticmethod(test_plugin.BridgeTests._close_log_handlers)
    pretend_installed = test_plugin.BridgeTests.pretend_installed
    started_after_update = test_plugin.BridgeTests.started_after_update

    def run_setup(self, argv, current, asked):
        environment = {self.bridge.ENV_SAYS_LEFT_STOPPED: "1"} if asked else {}
        with patch.dict(os.environ, environment):
            if not asked:
                os.environ.pop(self.bridge.ENV_SAYS_LEFT_STOPPED, None)
            return self.started_after_update(argv, current)

    def test_a_caller_that_asks_hears_that_the_watcher_was_left_stopped(self):
        code, started, _text = self.run_setup(["setup", "--keep-state", "--watcher-was-stopped"], None, asked=True)
        self.assertEqual(code, self.bridge.EXIT_LEFT_STOPPED)
        self.assertFalse(started)
        self.assertNotIn(code, (self.bridge.EXIT_OK, self.bridge.EXIT_ERROR, self.bridge.EXIT_UNCONFIRMED,
                                self.bridge.EXIT_DESKTOP_TAKEN), "one meaning per code")

    def test_a_caller_that_does_not_ask_hears_success_as_before(self):
        """An older install.ps1, and the bootstrap's Start-CurrentWatcher and Restore-AfterFailedPick, which run
        setup --keep-state --watcher-was-stopped and read anything but 0 and 2 as a failure."""
        code, started, _text = self.run_setup(["setup", "--keep-state", "--watcher-was-stopped"], None, asked=False)
        self.assertEqual(code, self.bridge.EXIT_OK)
        self.assertFalse(started)

    def test_a_watcher_that_is_started_is_success_whoever_asks(self):
        ours = self.bridge.watcher_command(self.home)
        for argv, current in ((["setup", "--keep-state", "--watcher-was-stopped"], ours),
                              (["setup", "--keep-state"], None), (["setup"], None)):
            with self.subTest(argv=argv, sign_in=current is not None):
                code, started, _text = self.run_setup(argv, current, asked=True)
                self.assertEqual(code, self.bridge.EXIT_OK)
                self.assertTrue(started)


@unittest.skipUnless(POWERSHELL.is_file(), "Windows PowerShell")
class LastWordTests(unittest.TestCase):
    """install.ps1's setup call and its last word, lifted verbatim, setup stubbed."""

    CALL = ("    $SETUP_UNCONFIRMED = 2", "    # After the change succeeded")
    WORD = ("    Step 'Checking the installation'", "    Write-Host 'To change anything")

    def run_script(self, script):
        with tempfile.TemporaryDirectory() as folder:
            probe = Path(folder) / "probe.ps1"
            probe.write_text(VOICE + script, encoding="utf-8-sig")
            done = subprocess.run([str(POWERSHELL), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                                   "-File", str(probe)], capture_output=True, text=True, encoding="utf-8",
                                  errors="replace", timeout=120, creationflags=NO_WINDOW)
        return done

    def call(self, setup_code):
        text = INSTALL.read_text(encoding="utf-8")
        stubs = ("function Invoke-Setup { param([string[]]$Arguments)\n"
                 "    $script:heard = [string]$env:CODEX_AUTO_RESUME_SETUP_SAYS_LEFT_STOPPED\n"
                 "    $global:LASTEXITCODE = %d; return %d }\n" % (setup_code, setup_code))
        script = ("$setupArgs = @('setup', '--keep-state', '--watcher-was-stopped')\n$watcherWasRunning = $false\n"
                  + stubs + block(text, *self.CALL)
                  + "Write-Host ('LEFT ' + $watcherLeftStopped + ' UNCONFIRMED ' + $watcherUnconfirmed)\n"
                  + "Write-Host ('HEARD ' + $script:heard + ' AFTER ' + [string]$env:CODEX_AUTO_RESUME_SETUP_SAYS_LEFT_STOPPED + '.')\n")
        return self.run_script(script)

    def test_the_call_asks_for_the_answer_and_reads_it_as_a_success(self):
        done = self.call(4)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertNotIn("Setup did not complete", done.stdout)
        self.assertIn("LEFT True UNCONFIRMED False", done.stdout)
        self.assertIn("HEARD 1 AFTER .", done.stdout, "set for setup's one call, and only for it")

    def test_any_other_failure_is_still_one(self):
        done = self.call(1)
        self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
        self.assertIn("Setup did not complete", done.stdout)

    def last_word(self, left_stopped, repair=False):
        text = INSTALL.read_text(encoding="utf-8")
        stubs = ("function Invoke-Setup { param([string[]]$Arguments)\n"
                 "    $global:LASTEXITCODE = 0; return 0 }\n"
                 "function Open-ClosedDashboard { param([switch]$Updated) }\n")
        script = ("$script:Failed = $false\n$upgrade = $true\n$repair = $%s\n$watcherUnconfirmed = $false\n"
                  "$previousWatcherStillRunning = $false\n$watcherLeftStopped = $%s\n"
                  % ("true" if repair else "false", "true" if left_stopped else "false")
                  + stubs + block(text, *self.WORD))
        done = self.run_script(script)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        return done.stdout

    def test_a_watcher_left_stopped_is_the_last_word(self):
        said = self.last_word(True)
        self.assertIn("Updated. Your settings and pending recoveries were kept.", said)
        self.assertIn("The watcher was not running before this update, so it was left stopped; nothing is being watched yet.", said)
        self.assertIn("Open Start Menu > Codex Auto Resume and use Start watcher, or use Start watcher on the Dashboard.", said)
        self.assertNotIn("Nothing else to do.", said)
        # The line the setup window reads for its Finish page.
        self.assertTrue(any(line.strip().startswith(left_stopped_line()) for line in said.splitlines()))

    def test_a_repair_says_repair(self):
        said = self.last_word(True, repair=True)
        self.assertIn("Repaired. Your settings and pending recoveries were kept.", said)
        self.assertIn("The watcher was not running before this repair, so it was left stopped", said)

    def test_a_watcher_that_runs_still_ends_as_before(self):
        said = self.last_word(False)
        self.assertIn("Recommended settings are already on. Nothing else to do.", said)
        self.assertNotIn(left_stopped_line(), said)


WINDOW_PROBE = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false
$assembly = [Reflection.Assembly]::LoadFile($env:CAR_EXE)
$any = [Reflection.BindingFlags]'Static,Instance,NonPublic,Public'
function T($name) { $assembly.GetType('CodexAutoResume.' + $name, $true) }
$FlowType = T 'InstallerFlow'
$WindowType = T 'InstallerWindow'
$WordsType = T 'InstallerWords'
function Of($object, $name) { $object.GetType().GetProperty($name, $any).GetValue($object, $null) }
function CallOn($object, $name, $arguments) { $object.GetType().GetMethod($name, $any).Invoke($object, [object[]]$arguments) }
function NewFlow($mode, $edition, $installed, $from) {
    $flow = $FlowType.GetConstructors($any)[0].Invoke([object[]]@([string]$mode, 'C:\Users\ExampleUser\.codex-auto-resume',
                                                               [string]$edition, $installed, '9.9.9'))
    $FlowType.GetField('From', $any).SetValue($flow, [string]$from)
    $flow
}
function TextOf($control) {
    $notice = $control.GetType().GetField('notice', $any)
    if ($notice) { return [string]$notice.GetValue($control) }
    [string]$control.Text
}
function Rows($window) { @(@(CallOn $window 'ShownRows' @()) | ForEach-Object { TextOf $_ }) }
function LightOf($window) {
    $dot = $WindowType.GetField('light', $any).GetValue($window)
    [string]$dot.GetType().GetProperty('State', $any).GetValue($dot, $null)
}
$parse = $FlowType.GetMethod('ParseObject', $any)
$english = $WordsType.GetConstructors($any)[0].Invoke([object[]]@($null, 'en'))
$korean = $WordsType.GetConstructors($any)[0].Invoke([object[]]@(
    $parse.Invoke($null, [object[]]@([IO.File]::ReadAllText($env:CAR_KO, [Text.Encoding]::UTF8))), 'ko'))
$font = [System.Drawing.SystemFonts]::MessageBoxFont
function Window($flow, $words) { $WindowType.GetConstructors($any)[0].Invoke([object[]]@($flow, $words, $null, $null, $null, $font)) }
# Its progress title, then its Finish page's first row after `lines`, ended with 0.
function Words($flow, $lines) {
    $window = Window $flow $english
    $null = CallOn $window 'ShowPage' @('progress')
    $progress = (Rows $window)[0]
    $null = CallOn $window 'Finished' @(0, [string]$lines)
    @($progress, (Rows $window)[0])
}
$out = @{}
$ended = "  Checking the installation`nUpdated. Your settings and pending recoveries were kept."
$out.older = Words (NewFlow 'install' 'advanced' 'advanced' '9.9.8') $ended
$out.newer = Words (NewFlow 'install' 'advanced' 'advanced' '10.0.0') $ended
$out.unreadable = Words (NewFlow 'install' 'standard' 'standard' '') $ended
$out.first = Words (NewFlow 'install' 'standard' $null '') "Installed and running."
$repair = NewFlow 'install' 'standard' 'standard' '9.9.9'
$FlowType.GetField('Maintaining', $any).SetValue($repair, $true)
$out.repair = Words $repair "Repaired. Your settings and pending recoveries were kept."
$change = NewFlow 'install' 'standard' 'advanced' '9.9.8'
$FlowType.GetField('ChangeEdition', $any).SetValue($change, $true)
$out.edition_change = Words $change $ended
$out.dashboard_update = Words (NewFlow 'update' 'standard' 'standard' '9.9.8') $ended
$out.updates_installed = @{}
foreach ($name in @('older', 'first', 'repair', 'change', 'dashboard')) {
    $flow = switch ($name) { 'older' { NewFlow 'install' 'advanced' 'advanced' '9.9.8' } 'first' { NewFlow 'install' 'standard' $null '' }
                             'repair' { $repair } 'change' { $change } 'dashboard' { NewFlow 'update' 'standard' 'standard' '9.9.8' } }
    $out.updates_installed[$name] = [bool](Of $flow 'UpdatesInstalled')
}

# A watcher left stopped: install.ps1's last word, then the Finish page, in English and in Korean.
$left = "Updated. Your settings and pending recoveries were kept.`n" + $env:CAR_LEFT_LINE
foreach ($pair in @(@('left_en', $english), @('left_ko', $korean))) {
    $window = Window (NewFlow 'install' 'advanced' 'advanced' '9.9.8') $pair[1]
    $null = CallOn $window 'Finished' @(0, $left)
    $out[$pair[0]] = @{ rows = (Rows $window); light = (LightOf $window) }
}
$window = Window (NewFlow 'install' 'advanced' 'advanced' '9.9.8') $english
$null = CallOn $window 'Finished' @(0, $ended)
$out.running = @{ rows = (Rows $window); light = (LightOf $window) }
$window = Window (NewFlow 'update' 'advanced' 'advanced' '9.9.8') $english
$null = CallOn $window 'Finished' @(0, $left)
$out.dashboard_left = @{ rows = (Rows $window); light = (LightOf $window) }
$out | ConvertTo-Json -Depth 6 -Compress
"""


@unittest.skipUnless(CSC.is_file() and POWERSHELL.is_file(), "needs the in-box compiler and PowerShell")
class WindowWordsTests(unittest.TestCase):
    """The setup window's words for each way it runs, and its Finish page for a watcher left stopped."""

    @classmethod
    def setUpClass(cls):
        cls.work = Path(tempfile.mkdtemp(prefix="installer-left-stopped-"))
        exe = _build(cls.work)
        cls.left = left_stopped_line() + "update, so it was left stopped; nothing is being watched yet."
        cls.result = _powershell(WINDOW_PROBE, cls.work, 600, CAR_EXE=str(exe), CAR_KO=str(LOCALES / "ko.json"),
                                 CAR_LEFT_LINE=cls.left)
        cls.answer = json.loads(cls.result.stdout) if cls.result.returncode == 0 and cls.result.stdout.strip() else {}

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.work, ignore_errors=True)

    def setUp(self):
        if not self.answer:
            self.fail("the probe did not run: " + (self.result.stderr or self.result.stdout)[-3000:])

    def test_an_update_over_an_older_installation_says_updating_and_updated(self):
        """The acceptance's G1: v0.6.23-beta.2 -> v0.6.23 through the setup program said 설치 중 / 설치되었습니다."""
        self.assertEqual(self.answer["older"], ["Updating", "Codex Auto Resume is updated."])
        # Another version than the one there, either way, and one that cannot be read: the Options page's Update.
        self.assertEqual(self.answer["newer"], ["Updating", "Codex Auto Resume is updated."])
        self.assertEqual(self.answer["unreadable"], ["Updating", "Codex Auto Resume is updated."])

    def test_the_other_ways_keep_their_words(self):
        self.assertEqual(self.answer["first"], ["Installing", "Codex Auto Resume is installed."])
        self.assertEqual(self.answer["repair"], ["Repairing", "Codex Auto Resume is repaired."])
        self.assertEqual(self.answer["edition_change"], ["Installing", "Codex Auto Resume is installed."],
                         "an edition change installs the other edition, and says so")
        self.assertEqual(self.answer["dashboard_update"], ["Updating", "Updated to v9.9.9"])
        self.assertEqual(self.answer["updates_installed"],
                         {"older": True, "first": False, "repair": False, "change": False, "dashboard": False})

    def test_the_finish_page_says_the_watcher_was_left_stopped(self):
        english = json.loads((LOCALES / "en.json").read_text(encoding="utf-8"))["installer.done.left_stopped"]
        korean = json.loads((LOCALES / "ko.json").read_text(encoding="utf-8"))["installer.done.left_stopped"]
        rows = self.answer["left_en"]["rows"]
        self.assertEqual(rows[0], "Codex Auto Resume is updated.")
        self.assertIn(english, rows, "under the headline")
        self.assertLess(rows.index("Exit code: 0"), rows.index(english))
        self.assertEqual(self.answer["left_en"]["light"], "idle", "nothing is being watched")
        self.assertIn(korean, self.answer["left_ko"]["rows"])
        self.assertEqual(self.answer["left_ko"]["rows"][0], "Codex Auto Resume이 업데이트되었습니다.")
        # The Dashboard's own update reads install.ps1's last word alike.
        self.assertIn(english, self.answer["dashboard_left"]["rows"])
        self.assertEqual(self.answer["dashboard_left"]["light"], "idle")

    def test_a_watcher_that_runs_gets_no_such_line(self):
        english = json.loads((LOCALES / "en.json").read_text(encoding="utf-8"))["installer.done.left_stopped"]
        self.assertNotIn(english, self.answer["running"]["rows"])
        self.assertEqual(self.answer["running"]["light"], "monitoring")


if __name__ == "__main__":
    unittest.main()
