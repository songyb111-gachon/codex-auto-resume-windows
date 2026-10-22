"""An update that stops before its own setup starts the watcher it stopped for the hand-over again.

install.ps1 asks a running watcher to stop before it replaces the program files. A copy that failed was put back and
the run ended "The existing installation was put back; nothing was changed." - with the watcher still stopped, so
nothing was recovered until the next sign-in (the v0.6.18 installer audit, R2). Every way out before the setup step
now runs the installation's own `setup --keep-state` again (Start-StoppedWatcher, from the install branch's
`finally`), and a failed setup says when the watcher it stopped is not running.

The copy and its rollback are lifted out of install.ps1 verbatim, with the real `finally` behind them, and run against
scratch folders under Set-StrictMode 2.0, as the bootstrap runs the installer. The setup step is a stand-in that only
records how it was called: nothing of the product runs, nothing is registered, no watcher is touched.
"""
from __future__ import annotations

from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
INSTALL_PS1 = (ROOT / "build" / "install" / "install.ps1").read_text(encoding="utf-8")
POWERSHELL = r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

VOICE = ("function Step { param([string]$m) Write-Host ('  ' + $m) }\n"
         "function Ok   { param([string]$m) Write-Host ('  [ok] ' + $m) }\n"
         "function Warn { param([string]$m) Write-Host ('  [!]  ' + $m) }\n"
         "function Fail { param([string]$m) Write-Host ('  [x]  ' + $m); $script:Failed = $true }\n")

# The setup step, stood in for: every call written down, and the exit code the test asks for.
STAND_IN = ("function Invoke-Setup { param([string[]]$Arguments)\n"
            "    Add-Content -LiteralPath $calls -Value (@($Arguments) -join ' ')\n"
            "    return $setupCode }\n")


def block(start: str, end: str) -> str:
    first = INSTALL_PS1.index(start)
    return INSTALL_PS1[first:INSTALL_PS1.index(end, first)]


def function_text(name: str) -> str:
    found = re.search(r"^function %s \{.*?^\}\r?$" % re.escape(name), INSTALL_PS1, re.M | re.S)
    if found is None:
        raise AssertionError("install.ps1 has no function %s" % name)
    return found.group(0)


def ps_literal(value) -> str:
    return "'" + str(value).replace("'", "''") + "'"


@unittest.skipUnless(sys.platform == "win32", "the installer is Windows PowerShell")
class WatcherStartedAgainTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.home = self.folder / "home"
        (self.home / "app" / "scripts").mkdir(parents=True)
        (self.home / "app" / "scripts" / "plugin_setup.py").write_text("previous version", encoding="utf-8")
        (self.home / "runtime").mkdir()
        (self.home / "runtime" / "python.exe").write_text("synthetic runtime fixture", encoding="utf-8")
        self.calls = self.folder / "calls.txt"

    def run_script(self, body: str, setup_code: int = 0) -> subprocess.CompletedProcess:
        source = ("Set-StrictMode -Version 2.0\n$ErrorActionPreference = 'Stop'\n" + VOICE +
                  block("function Quote-Argument", "function Invoke-Setup") + "\n" +
                  block("function Write-CopyJournal", "function Restore-InterruptedCopy") + "\n" +
                  function_text("Open-ClosedDashboard") + "\n" + function_text("Start-StoppedWatcher") + "\n" +
                  STAND_IN +
                  "$calls = %s\n$setupCode = %d\n$script:ProgressLines = $false\n$script:Failed = $false\n"
                  "$SkipStartup = $false\n$InstallHome = %s\n$OwnedHome = $InstallHome\n"
                  "$AppDir = Join-Path $InstallHome 'app'\n$RunDir = Join-Path $InstallHome 'runtime'\n"
                  "$Python = Join-Path $RunDir 'python.exe'\n"
                  "$Journal = Join-Path $InstallHome '.codex-auto-resume-install-journal.json'\n"
                  % (ps_literal(self.calls), setup_code, ps_literal(self.home)) + body)
        path = self.folder / "probe.ps1"
        path.write_text(source, encoding="utf-8-sig")
        return subprocess.run([POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                               "-File", str(path)],
                              capture_output=True, text=True, timeout=180, creationflags=NO_WINDOW)

    def copy_that_fails(self, stopped: bool) -> str:
        # A payload without its app tree: the copy throws after both trees were moved aside, and is put back.
        payload = self.folder / "payload"
        (payload / "runtime").mkdir(parents=True)
        return ("$Payload = %s\n$script:WatcherStoppedForUpdate = $%s\n"
                "$script:DashboardsAskedAt = $null\n$script:DashboardsReopened = $false\n"
                "$script:DashboardsFallback = @()\n"
                "try {\n$pairs = @(@{ src = 'app'; dst = $AppDir }, @{ src = 'runtime'; dst = $RunDir })\n"
                % (ps_literal(payload), "true" if stopped else "false") +
                block("    $stamp = Get-Date -Format 'yyyyMMddHHmmss'", "    # Both trees are in place") +
                "    exit 0\n" +
                block("} finally {\n    # Every way out before the setup step", "\n}") + "\n}\n")

    def calls_made(self) -> list[str]:
        return self.calls.read_text(encoding="utf-8").splitlines() if self.calls.exists() else []

    def test_a_copy_put_back_starts_the_stopped_watcher_again(self):
        done = self.run_script(self.copy_that_fails(stopped=True))
        self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
        self.assertIn("put back", done.stdout)
        self.assertTrue((self.home / "app" / "scripts" / "plugin_setup.py").is_file(), done.stdout)
        self.assertEqual(self.calls_made(), ["setup --keep-state"], done.stdout + done.stderr)
        self.assertIn("The watcher was started again", done.stdout)

    def test_no_watcher_is_started_where_none_was_stopped(self):
        done = self.run_script(self.copy_that_fails(stopped=False))
        self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
        self.assertEqual(self.calls_made(), [])

    def test_a_watcher_setup_cannot_confirm_is_said_with_how_to_start_it(self):
        done = self.run_script("$script:WatcherStoppedForUpdate = $true\nStart-StoppedWatcher\nStart-StoppedWatcher\n",
                               setup_code=1)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.calls_made(), ["setup --keep-state"], "once, however many ways out pass it")
        self.assertIn("nothing is being recovered now", done.stdout)
        self.assertIn("Start watcher", done.stdout)

    def test_the_new_setup_takes_over_from_the_flag_before_it_runs(self):
        at = INSTALL_PS1.index("    Step 'Setting up the watcher'")
        self.assertIn("$script:WatcherStoppedForUpdate = $false", INSTALL_PS1[at:at + 300])
        stop = INSTALL_PS1.index("Ok 'The previous watcher stopped'")
        self.assertIn("$script:WatcherStoppedForUpdate = $true", INSTALL_PS1[stop:stop + 300])

    def test_a_failed_setup_says_when_the_stopped_watcher_is_not_running(self):
        at = INSTALL_PS1.index("Fail 'Setup did not complete.")
        tail = INSTALL_PS1[at:INSTALL_PS1.index("exit 1", at)]
        self.assertIn("Invoke-Setup @('watcher-running')", tail)
        self.assertIn("nothing is being recovered now", tail)


if __name__ == "__main__":
    unittest.main()
