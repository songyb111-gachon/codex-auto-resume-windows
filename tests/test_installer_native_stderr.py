"""verify-home and claim-home answer with their exit code, even when they write to stderr.

install.ps1 runs both with `2>$null` under `$ErrorActionPreference = 'Stop'`. In Windows PowerShell 5.1 a native
program's stderr line still becomes a NativeCommandError there, and 'Stop' made it terminating: a traceback from
either replaced the installer's own refusal ("not a Codex Auto Resume installation", "holds files no installation of
ours has claimed") with a raw PowerShell error (the v0.6.18 installer audit, M1). Both calls run with 'Continue' now,
and the exit code alone decides.

The two regions are lifted verbatim and run under Set-StrictMode 2.0 against scratch folders; the engine's command is
a scratch script that writes to stderr and fails, run by this Python. Nothing of the product runs.
"""
from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
INSTALL_PS1 = (ROOT / "build" / "install" / "install.ps1").read_text(encoding="utf-8")
POWERSHELL = r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
STRICT = "Set-StrictMode -Version 2.0\n$ErrorActionPreference = 'Stop'\n"
VOICE = ("function Step { param([string]$m) Write-Host ('  ' + $m) }\n"
         "function Warn { param([string]$m) Write-Host ('  [!]  ' + $m) }\n"
         "function Fail { param([string]$m) Write-Host ('  [x]  ' + $m) }\n"
         "function Resolve-Canonical { param([string]$Path) return $Path }\n"
         "function Test-PathInside { param([string]$Path, [string]$Root) return $true }\n")
FAILING = "import sys\nsys.stderr.write('Traceback (most recent call last):\\n')\nsys.exit(1)\n"


def block(start: str, end: str) -> str:
    first = INSTALL_PS1.index(start)
    return INSTALL_PS1[first:INSTALL_PS1.index(end, first)]


def ps_literal(value) -> str:
    return "'" + str(value).replace("'", "''") + "'"


@unittest.skipUnless(sys.platform == "win32", "the installer is Windows PowerShell")
class NativeStderrTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.payload = self.folder / "payload"
        (self.payload / "app" / "scripts").mkdir(parents=True)
        (self.payload / "app" / "scripts" / "plugin_setup.py").write_text(FAILING, encoding="utf-8")
        self.home = self.folder / "home"
        self.home.mkdir()

    def run_lifted(self, body: str) -> subprocess.CompletedProcess:
        source = (STRICT + VOICE + "$Payload = %s\n$InstallHome = %s\n$AppDir = Join-Path $InstallHome 'app'\n"
                  "$Python = %s\n" % (ps_literal(self.payload), ps_literal(self.home), ps_literal(sys.executable)) +
                  body + "\nWrite-Host 'went on'\nexit 0\n")
        path = self.folder / "probe.ps1"
        path.write_text(source, encoding="utf-8-sig")
        return subprocess.run([POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                               "-File", str(path)],
                              capture_output=True, text=True, timeout=120, creationflags=NO_WINDOW)

    def test_claim_home_failing_with_stderr_gives_the_installers_refusal(self):
        done = self.run_lifted(block("$claimer = Join-Path $Payload", "$OwnedHome = Resolve-Canonical (@($claim)[1])"))
        self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
        self.assertIn("holds files no installation of ours has claimed", done.stdout, done.stderr)
        self.assertNotIn("NativeCommandError", done.stderr)

    def test_verify_home_failing_with_stderr_gives_the_installers_refusal(self):
        done = self.run_lifted(block("    $verifier = Join-Path $Payload", "    $OwnedHome = Resolve-Canonical"))
        self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
        self.assertIn("is not a Codex Auto Resume installation", done.stdout, done.stderr)
        self.assertNotIn("NativeCommandError", done.stderr)

    def test_a_stderr_line_with_success_still_goes_on(self):
        (self.payload / "app" / "scripts" / "plugin_setup.py").write_text(
            "import sys\nsys.stderr.write('a warning\\n')\nprint('claimed')\nprint(r'%s')\n" % self.home,
            encoding="utf-8")
        done = self.run_lifted(block("$claimer = Join-Path $Payload", "$OwnedHome = Resolve-Canonical (@($claim)[1])"))
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("went on", done.stdout)


if __name__ == "__main__":
    unittest.main()
