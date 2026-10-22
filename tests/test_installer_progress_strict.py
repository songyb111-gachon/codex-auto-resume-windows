"""install.ps1's progress lines hold under Set-StrictMode 2.0, as the bootstrap runs it.

scripts/bootstrap.ps1 sets `Set-StrictMode -Version 2.0` and runs the installer it downloaded; under strict mode reading
a variable that was never set throws. v0.6.18's Progress read `$script:ProgressSaid` before anything set it, so the
first counted copy threw inside the copy's try, the update rolled back and exited 1 - every update from the Dashboard
(the v0.6.18 installer audit, found before v0.6.18 was published). The function is lifted out of install.ps1 and run
in a strict-mode parent, the way the bootstrap's own scope would run it.
"""
from __future__ import annotations

from pathlib import Path
import re
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
INSTALL_PS1 = (ROOT / "build" / "install" / "install.ps1").read_text(encoding="utf-8")
POWERSHELL = r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def function_text(name: str) -> str:
    found = re.search(r"^function %s \{.*?^\}\r?$" % re.escape(name), INSTALL_PS1, re.M | re.S)
    if found is None:
        raise AssertionError("install.ps1 has no function %s" % name)
    return found.group(0)


class StrictModeTests(unittest.TestCase):
    def run_strict(self, preamble: str) -> subprocess.CompletedProcess:
        script = ("Set-StrictMode -Version 2.0\n$ErrorActionPreference = 'Stop'\n" + preamble + "\n" +
                  function_text("Progress") + "\nProgress 'files' 1 2\nProgress 'files' 2 2\n")
        return subprocess.run([POWERSHELL, "-NoProfile", "-NonInteractive", "-Command", script],
                              capture_output=True, text=True, timeout=120, creationflags=NO_WINDOW)

    def test_a_count_prints_under_strict_mode_with_nothing_set_before(self):
        done = self.run_strict("$script:ProgressLines = $true")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("progress: files 1/2", done.stdout)
        self.assertIn("progress: files 2/2", done.stdout)

    def test_the_script_sets_its_table_where_it_reads_the_request(self):
        at = INSTALL_PS1.index("$script:ProgressLines = $env:CODEX_AUTO_RESUME_PROGRESS_LINES -ceq '1'")
        self.assertIn("$script:ProgressSaid = @{}", INSTALL_PS1[at:at + 200])

    def test_without_the_request_it_prints_nothing_under_strict_mode(self):
        done = self.run_strict("$script:ProgressLines = $false")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertNotIn("progress:", done.stdout)


if __name__ == "__main__":
    unittest.main()
