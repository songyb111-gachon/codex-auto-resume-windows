"""A rollback that cannot clear the half-copied tree leaves the previous one aside, never inside it.

When the copy of the program files fails, install.ps1 removes what it had copied and moves the previous tree back. If
part of the new tree could not be removed, `Move-Item aside -> target` moved the previous tree INTO it
(app\\app.old-<stamp>), the journal still found its target there, and a later run swept the previous tree with the
rest - and the run said "nothing was changed" (the v0.6.18 installer audit, M5). Now a tree is moved back only where
its target is gone; otherwise it stays aside under its own name, which the journal keeps from the sweep, and the run
says it could not put everything back.

The copy and its rollback are lifted verbatim (tests/test_installer_watcher_restart.py's harness), with the removal of
the half-copied app tree made to fail, and run against scratch folders under Set-StrictMode 2.0.
"""
from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from test_installer_watcher_restart import NO_WINDOW, POWERSHELL, VOICE, block, ps_literal

# Remove-OwnedItem as lifted, but the half-copied app tree cannot be removed - as when a file in it is held.
STUCK = """
$liftedRemove = ${function:Remove-OwnedItem}
function Remove-OwnedItem { param([string]$Path)
    if ($Path -eq $AppDir) { return $false }
    return (& $liftedRemove $Path) }
"""


@unittest.skipUnless(sys.platform == "win32", "the installer is Windows PowerShell")
class PartialRollbackTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.home = self.folder / "home"
        (self.home / "app").mkdir(parents=True)
        (self.home / "app" / "previous.txt").write_text("the previous program", encoding="utf-8")
        (self.home / "runtime").mkdir()
        (self.home / "runtime" / "python.exe").write_text("previous runtime", encoding="utf-8")
        # A payload without its app tree: the copy throws after both trees were moved aside.
        (self.folder / "payload" / "runtime").mkdir(parents=True)

    def rollback(self) -> subprocess.CompletedProcess:
        source = ("Set-StrictMode -Version 2.0\n$ErrorActionPreference = 'Stop'\n" + VOICE +
                  block("function Quote-Argument", "function Invoke-Setup") + "\n" +
                  block("function Write-CopyJournal", "function Restore-InterruptedCopy") + "\n" +
                  "$script:ProgressLines = $false\n$script:Failed = $false\n$InstallHome = %s\n$OwnedHome = $InstallHome\n"
                  "$Payload = %s\n$AppDir = Join-Path $InstallHome 'app'\n$RunDir = Join-Path $InstallHome 'runtime'\n"
                  "$Journal = Join-Path $InstallHome '.codex-auto-resume-install-journal.json'\n"
                  % (ps_literal(self.home), ps_literal(self.folder / "payload")) + STUCK +
                  "$pairs = @(@{ src = 'app'; dst = $AppDir }, @{ src = 'runtime'; dst = $RunDir })\n" +
                  block("    $stamp = Get-Date -Format 'yyyyMMddHHmmss'", "    # Both trees are in place") +
                  "exit 0\n")
        path = self.folder / "probe.ps1"
        path.write_text(source, encoding="utf-8-sig")
        return subprocess.run([POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                               "-File", str(path)],
                              capture_output=True, text=True, timeout=180, creationflags=NO_WINDOW)

    def test_the_previous_tree_is_never_moved_into_the_half_copied_one(self):
        done = self.rollback()
        self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
        self.assertEqual([p.name for p in (self.home / "app").iterdir() if ".old-" in p.name], [],
                         "the previous tree was moved inside the half-copied one")
        aside = [p for p in self.home.iterdir() if p.name.startswith("app.old-")]
        self.assertEqual(len(aside), 1, done.stdout)
        self.assertEqual((aside[0] / "previous.txt").read_text(encoding="utf-8"), "the previous program")

    def test_it_says_what_it_could_not_put_back_and_keeps_the_journal(self):
        done = self.rollback()
        self.assertNotIn("nothing was changed", done.stdout)
        self.assertIn("could not be put back", done.stdout)
        self.assertTrue((self.home / ".codex-auto-resume-install-journal.json").is_file())
        # The tree whose target was free still went back.
        self.assertEqual((self.home / "runtime" / "python.exe").read_text(encoding="utf-8"), "previous runtime")


if __name__ == "__main__":
    unittest.main()
