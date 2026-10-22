"""A Dashboard program that cannot be replaced is said, and the update goes on to set up the watcher.

install.ps1 copies the Dashboard and its icon to the installation's root after the program trees. Where the copy
failed (the Dashboard is open) it moved the old file aside and copied again - with no -ErrorAction and no try, so a
second failure threw after app\\ and runtime\\ were replaced and before setup ran: the watcher stopped, no last word
(the v0.6.18 installer audit, M6). Now the second failure is a Fail line, and the run carries on to its setup and ends
"Finished with problems".

The root-file copy is lifted verbatim and run under Set-StrictMode 2.0 against scratch folders, with Copy-Item stood in
for by a function that always fails - as a held file makes it. Nothing of the product runs.
"""
from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from test_installer_watcher_restart import INSTALL_PS1, NO_WINDOW, POWERSHELL, VOICE, ps_literal

FAILING_COPY = """
function Copy-Item { param([string]$Path, [string]$LiteralPath, [string]$Destination, [switch]$Force, $ErrorAction)
    throw 'The process cannot access the file because it is being used by another process.' }
"""


def root_copy() -> str:
    start = INSTALL_PS1.index("    foreach ($name in $rootFiles) {\n        $source = Join-Path $Payload $name")
    return INSTALL_PS1[start:INSTALL_PS1.index("    foreach ($stale in (Get-ChildItem", start)]


@unittest.skipUnless(sys.platform == "win32", "the installer is Windows PowerShell")
class RootFileCopyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.home = self.folder / "home"
        self.home.mkdir()
        (self.home / "CodexAutoResumeSettings.exe").write_text("previous window", encoding="utf-8")
        payload = self.folder / "payload"
        payload.mkdir()
        for name in ("CodexAutoResumeSettings.exe", "codex-auto-resume.ico"):
            (payload / name).write_text("new " + name, encoding="utf-8")

    def test_a_second_failure_is_said_and_the_run_goes_on(self):
        source = ("Set-StrictMode -Version 2.0\n$ErrorActionPreference = 'Stop'\n" + VOICE + FAILING_COPY +
                  "$script:Failed = $false\n$InstallHome = %s\n$Payload = %s\n"
                  "$rootFiles = @('CodexAutoResumeSettings.exe', 'codex-auto-resume.ico')\n"
                  % (ps_literal(self.home), ps_literal(self.folder / "payload")) + root_copy() +
                  "Write-Host ('went on, failed ' + $script:Failed)\nexit 0\n")
        path = self.folder / "probe.ps1"
        path.write_text(source, encoding="utf-8-sig")
        done = subprocess.run([POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                               "-File", str(path)],
                              capture_output=True, text=True, timeout=120, creationflags=NO_WINDOW)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("went on, failed True", done.stdout)
        self.assertIn("CodexAutoResumeSettings.exe", done.stdout)
        self.assertIn("could not be replaced", done.stdout)


if __name__ == "__main__":
    unittest.main()
