"""A failed Install another version... leaves the version that was installed as it was.

The bootstrap's -Pick converts the state for an older version (downgrade-state, which stops the watcher) and takes the
entry in Add or remove programs and its kept uninstaller away (remove-entry) before the older version's installer
runs. When that installer then stopped - Codex not found, another installation running, a copy it put back - the
current version was still installed, but on a state converted for the older one, with its watcher stopped and no
entry in Settings > Apps until a Repair (the v0.6.18 installer audit, R4). Restore-AfterFailedPick puts back the
state from the copy the conversion took, the kept uninstaller from the copy saved before remove-entry, and runs the
installed version's `setup --keep-state`, which writes the entry again and starts the watcher.

The functions are lifted from scripts/bootstrap.ps1 and run under its Set-StrictMode 2.0 against scratch folders; the
installed version's setup is a stand-in that records each call. No registry, watcher or installation is touched.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP = (ROOT / "scripts" / "bootstrap.ps1").read_text(encoding="utf-8")
POWERSHELL = r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

VOICE = ("function Step { param([string]$Text) Write-Host ('  ' + $Text) }\n"
         "function Ok   { param([string]$Text) Write-Host ('  [ok] ' + $Text) }\n"
         "function Fail { param([string]$Text) Write-Host ('  [!] ' + $Text) }\n")

STAND_IN = """
function Invoke-InstalledSetup {
    param([string]$Home_, [string[]]$Arguments, [switch]$Outside)
    Add-Content -LiteralPath $calls -Value (@($Arguments) -join ' ')
    $code = 0
    if (@($Arguments)[0] -ceq 'watcher-running') { $code = $watcherCode }
    return [pscustomobject]@{ Printed = @(); Code = $code }
}
"""


def function_text(name: str) -> str:
    found = re.search(r"^function %s \{.*?^\}\r?$" % re.escape(name), BOOTSTRAP, re.M | re.S)
    if found is None:
        raise AssertionError("bootstrap.ps1 has no function %s" % name)
    return found.group(0)


def ps_literal(value) -> str:
    return "'" + str(value).replace("'", "''") + "'"


@unittest.skipUnless(sys.platform == "win32", "the bootstrap is Windows PowerShell")
class RestoreAfterFailedPickTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.home = self.folder / "home"
        (self.home / "app" / ".codex-plugin").mkdir(parents=True)
        self.manifest = self.home / "app" / ".codex-plugin" / "plugin.json"
        self.manifest.write_text('{"version": "0.6.20"}', encoding="utf-8")
        (self.home / "runtime").mkdir()
        (self.home / "runtime" / "python.exe").write_text("synthetic runtime fixture", encoding="utf-8")
        self.config = self.home / "config"
        self.config.mkdir()
        self.state = self.config / "state.sqlite"
        self.calls = self.folder / "calls.txt"
        self.kept_copy = self.folder / "kept-uninstaller.ps1"
        self.kept_copy.write_text("# the kept uninstaller", encoding="utf-8")
        self.since = time.time()
        # What downgrade-state leaves: its copy of the state as it was, then the state rewritten for the older version.
        stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        self.backup = self.config / ("state.v5-backup-%s.sqlite" % stamp)
        self.backup.write_text("the state as it was", encoding="utf-8")
        self.state.write_text("the state converted for v0.6.10", encoding="utf-8")

    def restore(self, converted="converted 3 0 0 0 0", watcher_code=1, was_stopped=False) -> subprocess.CompletedProcess:
        source = ("Set-StrictMode -Version 2.0\n$ErrorActionPreference = 'Stop'\n" +
                  VOICE + "\n".join(function_text(name) for name in ("Get-InstalledVersion",
                                                               "Start-CurrentWatcher", "Test-CurrentWatcherStopped",
                                                               "Restore-AfterFailedPick")) +
                  STAND_IN +
                  "$calls = %s\n$watcherCode = %d\n"
                  "$since = [DateTimeOffset]::FromUnixTimeMilliseconds(%d).LocalDateTime\n"
                  "$answer = Restore-AfterFailedPick -Home_ %s -Installed '0.6.20' -Converted %s -Since $since "
                  "-KeptCopy %s -WasStopped:$%s\nWrite-Host ('answer ' + $answer)\n"
                  % (ps_literal(self.calls), watcher_code, int(self.since * 1000) - 1000, ps_literal(self.home),
                     ps_literal(converted), ps_literal(self.kept_copy), "true" if was_stopped else "false"))
        path = self.folder / "probe.ps1"
        path.write_text(source, encoding="utf-8-sig")
        return subprocess.run([POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                               "-File", str(path)],
                              capture_output=True, text=True, timeout=180, creationflags=NO_WINDOW)

    def calls_made(self) -> list[str]:
        return self.calls.read_text(encoding="utf-8").splitlines() if self.calls.exists() else []

    def test_the_state_the_entry_and_the_watcher_are_put_back(self):
        done = self.restore()
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("answer restored", done.stdout)
        self.assertEqual(self.state.read_text(encoding="utf-8"), "the state as it was", done.stdout)
        self.assertEqual((self.home / "uninstall" / "install.ps1").read_text(encoding="utf-8"), "# the kept uninstaller")
        self.assertIn("setup --keep-state", self.calls_made())
        # The kept uninstaller is back before setup runs: setup writes the entry only where it is there to name.
        self.assertEqual(self.calls_made()[-1], "setup --keep-state")

    def test_a_watcher_that_did_not_run_before_is_started_only_where_it_runs_at_sign_in(self):
        done = self.restore(was_stopped=True)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("setup --keep-state --watcher-was-stopped", self.calls_made())

    def test_a_running_watcher_keeps_the_state_from_being_replaced_under_it(self):
        done = self.restore(watcher_code=0)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(self.state.read_text(encoding="utf-8"), "the state converted for v0.6.10")
        self.assertIn("stays converted", done.stdout)

    def test_an_older_copy_than_this_pick_is_never_taken(self):
        old = time.time() - 3600
        os.utime(self.backup, (old, old))
        done = self.restore()
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(self.state.read_text(encoding="utf-8"), "the state converted for v0.6.10")

    def test_nothing_converted_leaves_the_state_alone(self):
        done = self.restore(converted="nothing")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(self.state.read_text(encoding="utf-8"), "the state converted for v0.6.10")
        self.assertIn("setup --keep-state", self.calls_made())

    def test_an_installer_that_replaced_the_files_is_left_to_its_version(self):
        self.manifest.write_text('{"version": "0.6.10"}', encoding="utf-8")
        done = self.restore()
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("answer replaced", done.stdout)
        self.assertEqual(self.calls_made(), [])
        self.assertEqual(self.state.read_text(encoding="utf-8"), "the state converted for v0.6.10")
        self.assertFalse((self.home / "uninstall").exists())


class PickRouteCallsItTests(unittest.TestCase):
    def test_the_kept_uninstaller_is_saved_before_remove_entry(self):
        saved = BOOTSTRAP.index("$pickKeptCopy = Join-Path $work 'kept-uninstaller.ps1'")
        removed = BOOTSTRAP.index("$entry = Remove-EntryBeforeOlder")
        converted = BOOTSTRAP.index("$converted = Convert-StateForOlder")
        self.assertLess(saved, converted)
        self.assertLess(saved, removed)

    def test_a_non_zero_installer_code_on_a_pick_restores(self):
        at = BOOTSTRAP.index("    & $installer @arguments")
        tail = BOOTSTRAP[at:BOOTSTRAP.index("    exit $code", at)]
        self.assertIn("if ($Pick -and $code -ne 0)", tail)
        self.assertIn("Restore-AfterFailedPick", tail)


if __name__ == "__main__":
    unittest.main()
