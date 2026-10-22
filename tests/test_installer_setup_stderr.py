"""A line the setup step writes to stderr does not stop install.ps1 when it runs outside another app.

Inside an MSIX app (the Codex plugin's bootstrap, an agent in Codex or Claude) install.ps1 runs itself again outside,
through the wrapper Get-OutsideSource writes: `& install.ps1 ... *>&1 | ForEach-Object { ... }`. With the script's
streams merged so, Windows PowerShell 5.1 turns each stderr line of a native program the script runs into a
NativeCommandError, and install.ps1's `$ErrorActionPreference = 'Stop'` made it terminating: setup's `error: ...` line
(a failed `install` step, a doctor warning) killed the setup child half way and failed the install past its own
"Setup did not complete" message (the v0.6.18 installer audit, R1). Setup's exit code decides, not its stderr.

Invoke-Setup and Get-OutsideSource are lifted out of install.ps1 and run as the outside run runs them, under
Set-StrictMode 2.0 as the bootstrap runs the installer; the setup step is a scratch script, run by this Python.
Nothing of the product runs and nothing is registered.
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

# The setup step as a scratch script: a line on stderr first, then what it still has to do, then its exit code.
SETUP = r'''
import sys, time
from pathlib import Path
sys.stderr.write("error: the install step failed\n")
sys.stderr.flush()
time.sleep(1)
Path(sys.argv[0]).resolve().parents[2].joinpath("finished.txt").write_text("setup ran to its end", encoding="utf-8")
print("setup incomplete")
sys.exit(1)
'''


def function_text(name: str) -> str:
    found = re.search(r"^function %s \{.*?^\}\r?$" % re.escape(name), INSTALL_PS1, re.M | re.S)
    if found is None:
        raise AssertionError("install.ps1 has no function %s" % name)
    return found.group(0)


def ps_literal(value) -> str:
    return "'" + str(value).replace("'", "''") + "'"


@unittest.skipUnless(sys.platform == "win32", "the installer is Windows PowerShell")
class SetupStderrOutsideTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        (self.folder / "app" / "scripts").mkdir(parents=True)
        (self.folder / "app" / "scripts" / "plugin_setup.py").write_text(SETUP, encoding="utf-8")

    def run_outside(self) -> tuple[str, str, subprocess.CompletedProcess]:
        inner = self.folder / "inner.ps1"
        inner.write_text(
            "Set-StrictMode -Version 2.0\n$ErrorActionPreference = 'Stop'\n"
            "$AppDir = %s\n$Python = %s\n$script:ProgressLines = $false\n%s\n"
            "$code = Invoke-Setup @('setup')\nWrite-Host ('setup code ' + $code)\nexit 7\n"
            % (ps_literal(self.folder / "app"), ps_literal(sys.executable), function_text("Invoke-Setup")),
            encoding="utf-8-sig")
        log = self.folder / "output.txt"
        code_file = self.folder / "code.txt"
        # What Resolve-OutsideRun hands the run outside: Get-OutsideSource's text, the same function.
        maker = (function_text("Get-OutsideSource") + "\n"
                 "Get-OutsideSource -Script %s -Switches @() -Values @{} -Arguments @() -Log %s -CodeFile %s"
                 % (ps_literal(inner), ps_literal(log), ps_literal(code_file)))
        made = subprocess.run([POWERSHELL, "-NoProfile", "-NonInteractive", "-Command", maker],
                              capture_output=True, text=True, timeout=120, creationflags=NO_WINDOW)
        self.assertEqual(made.returncode, 0, made.stderr)
        outer = self.folder / "outer.ps1"
        outer.write_text(made.stdout, encoding="utf-8-sig")
        done = subprocess.run([POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                               "-File", str(outer)],
                              capture_output=True, text=True, timeout=180, creationflags=NO_WINDOW)
        said = log.read_text(encoding="utf-8", errors="replace") if log.exists() else ""
        code = code_file.read_text(encoding="utf-8").strip() if code_file.exists() else ""
        return said, code, done

    def test_a_stderr_line_does_not_stop_setup_and_its_exit_code_decides(self):
        said, code, done = self.run_outside()
        self.assertTrue((self.folder / "finished.txt").is_file(),
                        "the setup step was stopped at its stderr line: " + said + done.stderr)
        self.assertIn("setup code 1", said)
        # The installer went on past the setup call to its own end, so its own exit code came out.
        self.assertEqual(code, "7", said)

    def test_the_stderr_line_still_reaches_the_log(self):
        said, _, _ = self.run_outside()
        self.assertIn("error: the install step failed", said)


if __name__ == "__main__":
    unittest.main()
