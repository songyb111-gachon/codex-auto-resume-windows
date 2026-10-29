"""The uninstall's sweep of its own leftovers prints no bare True or False.

The sweep of `*.old-*` leftovers in install.ps1's uninstall branch called Remove-OwnedItem without `$null =`, so
each removal printed a bare True or False into the uninstall's log and the setup window (the v0.6.18 installer
audit, M2).

The uninstall tail is lifted verbatim (tests/test_installer_uninstall_retry.py's harness: scratch folders, Codex and
the registry stood in for, Set-StrictMode 2.0). Nothing real is asked or changed.
"""
from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

from test_installer_uninstall_retry import STRICT, VOICE, block, ps_literal, run_probe


def tail(home: Path, folder: Path, purge: bool):
    source = STRICT + VOICE + block("function Quote-Argument", "function Invoke-Setup")
    source += block("function Remove-OwnUninstallEntry", "function Write-CopyJournal")
    source += ("\nfunction Read-UninstallEntry { param([string]$Name) return $null }\n"
               "function Remove-UninstallEntry { param([string]$Name) throw 'the registry was asked' }\n"
               "function Get-CodexCli { return $null }\nfunction Get-OwnedMcpProcess { return ,@() }\n")
    source += ("$OwnedHome = %s\n$InstallHome = $OwnedHome\n$AppDir = Join-Path $OwnedHome 'app'\n"
               "$RunDir = Join-Path $OwnedHome 'runtime'\n$Python = Join-Path $RunDir 'python.exe'\n"
               "$PluginCacheRoot = Join-Path $OwnedHome 'cache'\n$script:Failed = $false\n$Purge = $%s\n"
               "$script:ProgressLines = $false\n$script:ProgressSaid = @{}\n"
               % (ps_literal(home), "true" if purge else "false"))
    branch = block("# ----------------------------------------------------------------------- uninstall",
                   "# -------------------------------------------------------------------------- install")
    source += "if ($true) {\n" + branch[branch.index("    $codex = Get-CodexCli"):]
    return run_probe(folder, source)


@unittest.skipUnless(sys.platform == "win32", "the installer is Windows PowerShell")
class UninstallFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.home = self.folder / "home"
        for relative in ("app/scripts/plugin_setup.py", "runtime/python.exe", ".owned-by-codex-auto-resume",
                         "config/settings.json", "logs/auto-resume.log", "app.old-20261001000000/x.txt"):
            path = self.home / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("synthetic fixture", encoding="utf-8")


class SweepIsQuietTests(UninstallFixture):
    def test_the_leftover_sweep_prints_no_bare_true_or_false(self):
        done = tail(self.home, self.folder, purge=False)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertFalse((self.home / "app.old-20261001000000").exists())
        lines = [line.strip() for line in done.stdout.splitlines()]
        self.assertNotIn("True", lines, done.stdout)
        self.assertNotIn("False", lines, done.stdout)


if __name__ == "__main__":
    unittest.main()
