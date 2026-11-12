"""Uninstall -Purge takes the watchers' lock files in %LOCALAPPDATA% too, except one another installation holds.

A watcher holds an exclusive lock on one Codex home for its whole life (src/codex_auto_resume/win/homelock.py): an
empty file %LOCALAPPDATA%\\codex-auto-resume\\homes\\<sha256 of the home's path>.lock, and id-<volume>-<file
index>.lock beside it. Nothing removed them: after "Uninstall, delete settings too" a codex-auto-resume folder stayed
in AppData\\Local (the 2026-11-12 standards audit, S5 - F3). The purge now deletes those files and the two folders
once empty; a lock another installation's watcher holds open cannot be deleted, so it stays, with its folders, and
the uninstall goes on, saying so in one line. A plain uninstall keeps them, as it keeps the settings.

Remove-HomeLocks is lifted from install.ps1 and run over a scratch LOCALAPPDATA, and the uninstall branch's tail runs
as tests/test_installer_uninstall_sweep.py runs it, with LOCALAPPDATA a scratch folder (its harness gives every
probe one). A held lock is held the way the watcher holds it: os.open and msvcrt.locking on its first byte. Nothing
of the real LOCALAPPDATA is read or changed.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

from test_installer_uninstall_retry import INSTALL_PS1, STRICT, VOICE, ps_literal
from test_installer_uninstall_sweep import UninstallFixture, tail

POWERSHELL = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
FREE = "0" * 63 + "a.lock"
HELD = "f" * 64 + ".lock"
IDENTITY = "id-0123abcd-00000000000004d2.lock"


def function_text(name: str) -> str:
    found = re.search(r"^function %s \{.*?^\}\r?$" % re.escape(name), INSTALL_PS1, re.M | re.S)
    if found is None:
        raise AssertionError("install.ps1 has no function %s" % name)
    return found.group(0)


def hold(path: Path) -> int:
    """The watcher's hold (HomeLock._take): open, and its first byte locked."""
    import msvcrt
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    os.lseek(fd, 0, 0)
    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
    return fd


def let_go(fd: int) -> None:
    import msvcrt
    os.lseek(fd, 0, 0)
    msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    os.close(fd)


@unittest.skipUnless(sys.platform == "win32", "the installer is Windows PowerShell")
class RemoveHomeLocksTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.work = Path(temp.name)
        self.local = self.work / "local"
        self.top = self.local / "codex-auto-resume"
        self.homes = self.top / "homes"
        self.homes.mkdir(parents=True)
        for name in (FREE, IDENTITY):
            (self.homes / name).write_bytes(b"")

    def run_it(self) -> subprocess.CompletedProcess:
        probe = self.work / "probe.ps1"
        probe.write_text(STRICT + VOICE + function_text("Remove-HomeLocks") + "\n"
                         "Remove-HomeLocks -Local %s\nWrite-Host 'went on'\n" % ps_literal(self.local),
                         encoding="utf-8-sig")
        done = subprocess.run([str(POWERSHELL), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                               "-File", str(probe)], capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=120, creationflags=NO_WINDOW)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("went on", done.stdout)
        return done

    def said(self, done) -> list:
        return [line for line in done.stdout.splitlines() if line.strip() and line != "went on"]

    def test_free_locks_go_with_both_folders_and_it_says_so_once(self):
        done = self.run_it()
        self.assertFalse(self.top.exists(), done.stdout)
        self.assertTrue(self.local.is_dir(), "LOCALAPPDATA itself stays")
        said = self.said(done)
        self.assertEqual(len(said), 1, done.stdout)
        self.assertIn(str(self.homes), said[0])

    def test_a_lock_another_installation_holds_stays_with_its_folders_and_nothing_fails(self):
        fd = hold(self.homes / HELD)
        try:
            done = self.run_it()
            self.assertEqual(sorted(path.name for path in self.homes.iterdir()), [HELD], done.stdout)
        finally:
            let_go(fd)
        said = self.said(done)
        self.assertEqual(len(said), 1, done.stdout)
        self.assertIn("in use", said[0])
        self.assertNotIn("[x]", done.stdout)
        # Once it is let go, a later purge takes it.
        done = self.run_it()
        self.assertFalse(self.top.exists(), done.stdout)

    def test_only_lock_files_go_and_a_folder_with_anything_else_stays(self):
        (self.homes / "notes.txt").write_text("somebody's", encoding="utf-8")
        (self.top / "other").mkdir()
        done = self.run_it()
        self.assertEqual(sorted(path.name for path in self.homes.iterdir()), ["notes.txt"])
        self.assertTrue((self.top / "other").is_dir())
        self.assertEqual(len(self.said(done)), 1, done.stdout)

    def test_a_junction_at_the_folder_is_never_followed(self):
        import _winapi
        outside = self.work / "outside"
        outside.mkdir()
        (outside / FREE).write_bytes(b"")
        for name in (FREE, IDENTITY):
            (self.homes / name).unlink()
        self.homes.rmdir()
        _winapi.CreateJunction(str(outside), str(self.homes))
        self.addCleanup(lambda: os.path.lexists(self.homes) and os.rmdir(self.homes))
        self.run_it()
        self.assertTrue((outside / FREE).is_file(), "a file through the junction was deleted")

    def test_no_folder_is_nothing_said(self):
        for name in (FREE, IDENTITY):
            (self.homes / name).unlink()
        self.homes.rmdir()
        self.top.rmdir()
        done = self.run_it()
        self.assertEqual(self.said(done), [])


class PurgeBranchTests(UninstallFixture):
    """The uninstall's tail, lifted whole, over a scratch LOCALAPPDATA."""

    def locks(self) -> Path:
        homes = self.folder / "local" / "codex-auto-resume" / "homes"
        homes.mkdir(parents=True)
        (homes / FREE).write_bytes(b"")
        (homes / IDENTITY).write_bytes(b"")
        return homes

    def test_a_purge_takes_them(self):
        homes = self.locks()
        done = tail(self.home, self.folder, purge=True)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertFalse(homes.parent.exists(), done.stdout)
        self.assertIn("Removed, including settings and recovery history.", done.stdout)

    def test_a_held_lock_never_fails_the_purge(self):
        homes = self.locks()
        fd = hold(homes / HELD)
        try:
            done = tail(self.home, self.folder, purge=True)
        finally:
            let_go(fd)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(sorted(path.name for path in homes.iterdir()), [HELD])
        self.assertIn("Removed, including settings and recovery history.", done.stdout)
        self.assertNotIn("[x]", done.stdout)

    def test_a_plain_uninstall_keeps_them(self):
        homes = self.locks()
        done = tail(self.home, self.folder, purge=False)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(sorted(path.name for path in homes.iterdir()), sorted([FREE, IDENTITY]))

    def test_the_call_is_in_the_purge_and_nowhere_else(self):
        self.assertEqual(INSTALL_PS1.count("Remove-HomeLocks -Local $env:LOCALAPPDATA"), 1)
        purge = INSTALL_PS1.index("    if ($Purge) {", INSTALL_PS1.index("$kept = Join-Path $OwnedHome 'uninstall'"))
        plain = INSTALL_PS1.index("Write-Host 'Removed. Settings and pending recoveries were kept.'", purge)
        self.assertLess(purge, INSTALL_PS1.index("Remove-HomeLocks -Local $env:LOCALAPPDATA"))
        self.assertLess(INSTALL_PS1.index("Remove-HomeLocks -Local $env:LOCALAPPDATA"), plain)


if __name__ == "__main__":
    unittest.main()
