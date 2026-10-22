"""A `[` or `]` in the installation's home or in an archive's path is a character, never a wildcard.

install.ps1 and the bootstrap tested and moved paths built from CODEX_AUTO_RESUME_PLUGIN_HOME or -ArchivePath with
`-Path` or a bare Test-Path, which read `[1]` as a character class. Over an installation in `...\\inst[1]`, `$upgrade`
came out false and the move-aside failed, so the copy stopped half way; the bootstrap read no installed version there
(the v0.6.18 installer audit, M4). Windows user names cannot hold brackets, so only a chosen home or file path met it.

The copy is lifted verbatim from install.ps1 (tests/test_installer_watcher_restart.py's harness) and run over a
scratch home with brackets in its name, under Set-StrictMode 2.0; Get-InstalledVersion is lifted from the bootstrap.
Nothing of the product runs.
"""
from __future__ import annotations

from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

from test_installer_watcher_restart import (INSTALL_PS1, NO_WINDOW, POWERSHELL, STAND_IN, VOICE, block,
                                            function_text, ps_literal)

BOOTSTRAP = (Path(__file__).resolve().parents[1] / "scripts" / "bootstrap.ps1").read_text(encoding="utf-8")


def run(folder: Path, source: str) -> subprocess.CompletedProcess:
    path = folder / "probe.ps1"
    path.write_text("Set-StrictMode -Version 2.0\n$ErrorActionPreference = 'Stop'\n" + source, encoding="utf-8-sig")
    return subprocess.run([POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(path)],
                          capture_output=True, text=True, timeout=180, creationflags=NO_WINDOW)


@unittest.skipUnless(sys.platform == "win32", "the installer is Windows PowerShell")
class BracketHomeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.home = self.folder / "inst[1]"
        for relative, text in (("app/x.txt", "previous"), ("runtime/python.exe", "previous runtime"),
                               ("CodexAutoResumeSettings.exe", "previous window")):
            path = self.home / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        self.payload = self.folder / "pay[2]" / "payload"
        for relative, text in (("app/x.txt", "new"), ("runtime/python.exe", "new runtime"),
                               ("CodexAutoResumeSettings.exe", "new window"), ("codex-auto-resume.ico", "icon")):
            path = self.payload / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")

    def test_an_update_over_a_home_with_brackets_moves_aside_and_copies(self):
        source = (VOICE + block("function Quote-Argument", "function Invoke-Setup") + "\n" +
                  block("function Write-CopyJournal", "function Restore-InterruptedCopy") + "\n" +
                  "$script:ProgressLines = $false\n$InstallHome = %s\n$OwnedHome = $InstallHome\n$Payload = %s\n"
                  "$AppDir = Join-Path $InstallHome 'app'\n$RunDir = Join-Path $InstallHome 'runtime'\n"
                  "$Journal = Join-Path $InstallHome '.codex-auto-resume-install-journal.json'\n"
                  "$Python = Join-Path $RunDir 'python.exe'\n"
                  % (ps_literal(self.home), ps_literal(self.payload)) +
                  block("    $upgrade = Test-Path", "\n") + "\nWrite-Host ('upgrade ' + $upgrade)\n"
                  "$pairs = @(@{ src = 'app'; dst = $AppDir }, @{ src = 'runtime'; dst = $RunDir })\n"
                  "$rootFiles = @('CodexAutoResumeSettings.exe', 'codex-auto-resume.ico')\n" +
                  block("    $stamp = Get-Date -Format 'yyyyMMddHHmmss'", "    $runtimeVersion = ") +
                  "Write-Host 'copied'\nexit 0\n")
        done = run(self.folder, source)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("upgrade True", done.stdout)
        self.assertIn("copied", done.stdout)
        self.assertEqual((self.home / "app" / "x.txt").read_text(encoding="utf-8"), "new")
        self.assertEqual((self.home / "runtime" / "python.exe").read_text(encoding="utf-8"), "new runtime")
        self.assertEqual((self.home / "CodexAutoResumeSettings.exe").read_text(encoding="utf-8"), "new window")
        self.assertEqual([p.name for p in self.home.iterdir() if ".old-" in p.name], [])

    def test_the_bootstrap_reads_the_version_installed_in_a_home_with_brackets(self):
        (self.home / "app" / ".codex-plugin").mkdir()
        (self.home / "app" / ".codex-plugin" / "plugin.json").write_text('{"version": "0.6.20"}', encoding="utf-8")
        found = re.search(r"^function Get-InstalledVersion \{.*?^\}\r?$", BOOTSTRAP, re.M | re.S).group(0)
        done = run(self.folder, found + "\nWrite-Host ('version ' + (Get-InstalledVersion -Home_ %s))\n"
                   % ps_literal(self.home))
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("version 0.6.20", done.stdout)


class LiteralEverywhereTests(unittest.TestCase):
    def test_the_bootstraps_archive_path_is_literal(self):
        at = BOOTSTRAP.index("    if ($ArchivePath) {\n        if (-not (Test-Path")
        region = BOOTSTRAP[at:BOOTSTRAP.index("    } else {", at)]
        self.assertIn("Test-Path -LiteralPath $ArchivePath", region)
        self.assertIn("Copy-Item -LiteralPath $ArchivePath", region)


if __name__ == "__main__":
    unittest.main()
