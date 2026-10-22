"""An uninstall that cannot remove one program file keeps what its own retry needs.

The uninstall removed every entry of app\\ and runtime\\ whatever failed, then said "run this again". One file held
open under app\\ (an MCP child, an antivirus scan) left runtime\\ deleted, and the retry - from the Apps entry's kept
uninstaller or from Uninstall.cmd - stopped at "No installed runtime found here" every time after (the v0.6.18
installer audit, R3). Now app\\ goes first, its scripts\\ and src\\ (what verify-home runs) last and only while nothing
before them stuck, and runtime\\ only once app\\ is gone; the refusal waits until the payload's interpreter was looked
for too.

The uninstall tail is lifted verbatim from install.ps1 and run against scratch folders under Set-StrictMode 2.0, with
the Codex calls and the registry stood in for as tests/test_installer.py's UninstallRegistrationFailureTests does: no
real registration, process or installation is asked or changed.
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
         "function Ok   { param([string]$m) Write-Host ('  [ok] ' + $m) }\n"
         "function Warn { param([string]$m) Write-Host ('  [!]  ' + $m) }\n"
         "function Fail { param([string]$m) $script:Failed = $true; Write-Host ('  [x]  ' + $m) }\n")


def block(start: str, end: str) -> str:
    first = INSTALL_PS1.index(start)
    return INSTALL_PS1[first:INSTALL_PS1.index(end, first)]


def ps_literal(value) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def run_probe(folder: Path, source: str) -> subprocess.CompletedProcess:
    path = folder / "probe.ps1"
    path.write_text(source, encoding="utf-8-sig")
    return subprocess.run([POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(path)],
                          capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180,
                          creationflags=NO_WINDOW)


@unittest.skipUnless(sys.platform == "win32", "the installer is Windows PowerShell")
class HeldFileKeepsTheRetryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.home = self.folder / "home"
        (self.home / "app" / "scripts").mkdir(parents=True)
        (self.home / "app" / "src").mkdir()
        self.verifier = self.home / "app" / "scripts" / "plugin_setup.py"
        self.verifier.write_text("synthetic verifier fixture", encoding="utf-8")
        (self.home / "app" / "src" / "engine.py").write_text("synthetic engine fixture", encoding="utf-8")
        self.held = self.home / "app" / "held.bin"
        self.held.write_text("a file something holds open", encoding="utf-8")
        (self.home / "app" / "other.txt").write_text("another program file", encoding="utf-8")
        (self.home / "runtime").mkdir()
        self.runtime = self.home / "runtime" / "python.exe"
        self.runtime.write_text("synthetic runtime fixture", encoding="utf-8")
        (self.home / "runtime" / "python313.dll").write_text("synthetic library fixture", encoding="utf-8")
        self.marker = self.home / ".owned-by-codex-auto-resume"
        self.marker.write_text("synthetic ownership fixture", encoding="utf-8")

    def uninstall_tail(self) -> subprocess.CompletedProcess:
        source = STRICT + VOICE + block("function Quote-Argument", "function Invoke-Setup")
        source += block("function Remove-OwnUninstallEntry", "function Write-CopyJournal")
        source += ("\nfunction Read-UninstallEntry { param([string]$Name) return $null }\n"
                   "function Remove-UninstallEntry { param([string]$Name) throw 'the registry was asked' }\n"
                   "function Get-CodexCli { return $null }\nfunction Get-OwnedMcpProcess { return ,@() }\n")
        source += ("$OwnedHome = %s\n$InstallHome = $OwnedHome\n$AppDir = Join-Path $OwnedHome 'app'\n"
                   "$RunDir = Join-Path $OwnedHome 'runtime'\n$Python = Join-Path $RunDir 'python.exe'\n"
                   "$PluginCacheRoot = Join-Path $OwnedHome 'cache'\n$script:Failed = $false\n$Purge = $false\n"
                   "$script:ProgressLines = $false\n$script:ProgressSaid = @{}\n" % ps_literal(self.home))
        branch = block("# ----------------------------------------------------------------------- uninstall",
                       "# -------------------------------------------------------------------------- install")
        source += "if ($true) {\n" + branch[branch.index("    $codex = Get-CodexCli"):]
        return run_probe(self.folder, source)

    def test_a_held_file_under_app_keeps_the_runtime_and_the_verifier(self):
        # Windows refuses to delete a file while this handle is open, as it does for a file a program holds.
        with self.held.open("rb"):
            done = self.uninstall_tail()
        self.assertNotEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("still in use", done.stdout)
        self.assertTrue(self.runtime.is_file(), "the retry needs the installed interpreter: " + done.stdout)
        self.assertTrue((self.home / "runtime" / "python313.dll").is_file(), "runtime\\ went while app\\ stayed")
        self.assertTrue(self.verifier.is_file(), "the retry needs verify-home's script: " + done.stdout)
        self.assertTrue((self.home / "app" / "src" / "engine.py").is_file(), "the retry needs the engine")
        self.assertTrue(self.marker.is_file(), "the retry needs the ownership proof")
        self.assertIn("runtime was kept", done.stdout)
        self.assertNotIn("Removed.", done.stdout)

    def test_once_the_file_is_free_the_retry_removes_everything(self):
        with self.held.open("rb"):
            self.uninstall_tail()
        done = self.uninstall_tail()
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertFalse((self.home / "app").exists())
        self.assertFalse((self.home / "runtime").exists())
        self.assertFalse(self.marker.exists())


@unittest.skipUnless(sys.platform == "win32", "the installer is Windows PowerShell")
class RefusalWaitsForThePayloadTests(unittest.TestCase):
    """The branch's head up to its verify-home call, lifted: which interpreter it asks, or its refusal."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.home = self.folder / "home"
        (self.home / "app" / "scripts").mkdir(parents=True)
        self.payload = self.folder / "payload"
        (self.payload / "app" / "scripts").mkdir(parents=True)
        (self.payload / "app" / "scripts" / "plugin_setup.py").write_text("payload verifier", encoding="utf-8")

    def head(self) -> subprocess.CompletedProcess:
        start = "if ($Uninstall) {"
        head = block(start, "    $verify = & $interpreter")
        source = (STRICT + VOICE + "$Uninstall = $true\n$InstallHome = %s\n$AppDir = Join-Path $InstallHome 'app'\n"
                  "$RunDir = Join-Path $InstallHome 'runtime'\n$Python = Join-Path $RunDir 'python.exe'\n"
                  "$Payload = %s\n" % (ps_literal(self.home), ps_literal(self.payload)) +
                  head + "    Write-Host ('asks ' + $interpreter)\n    exit 0\n}\n")
        return run_probe(self.folder, source)

    def test_without_an_installed_runtime_the_payloads_is_asked(self):
        (self.payload / "runtime").mkdir()
        (self.payload / "runtime" / "python.exe").write_text("payload runtime fixture", encoding="utf-8")
        done = self.head()
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("asks " + str(self.payload / "runtime" / "python.exe"), done.stdout)
        self.assertNotIn("No installed runtime", done.stdout)

    def test_with_neither_runtime_it_still_refuses(self):
        done = self.head()
        self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
        self.assertIn("No installed runtime found here", done.stdout)


if __name__ == "__main__":
    unittest.main()
