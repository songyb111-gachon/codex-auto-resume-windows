"""v0.6.26 final: setup's log says the watcher runs on the chosen Python, beside the bundled one.

The 2026-11-24 acceptance read "[ok] Bundled Python 3.14 (no system Python needed)" in an update's log while the watcher
ran on the python.org 3.15.2 the person had chosen in the advanced edition (runtimes\\3.15.2). The bundled line stays as
it was - it still runs setup and the launcher, and the setup window's step reads its start (gui/InstallerFlow.cs) - and
a line after it names the chosen Python where the program's own rule (chosen_runtime.chosen: the record and every file
chosen_runtime.required names) would have every launcher take it - asked of the program just copied, never a second
copy of the rule in PowerShell. The edition may still take the choice back at the watcher's start (its switch off), so
the line says the Python is in place and that the watcher uses it while that choice is on.
The standard edition, and an advanced one with nothing chosen, log exactly what they logged.

The installer's own functions and lines are run, cut from build/install/install.ps1, against a scratch folder: no
real installation, no real runtimes folder.

    PYTHONPATH=src;tests python -m unittest test_installer_chosen_python_line
"""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from codex_auto_resume import chosen_runtime

ROOT = Path(__file__).resolve().parents[1]
INSTALL_PS1 = (ROOT / "build" / "install" / "install.ps1").read_text(encoding="utf-8")
SYSTEM = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
POWERSHELL = SYSTEM / "WindowsPowerShell" / "v1.0" / "powershell.exe"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
SRC = ROOT / "src"
LINE = "[ok] Chosen Python 3.15.2 in place; the watcher uses it while that choice is on"
BUNDLED_LINE = "    Ok ('Bundled Python ' + $runtimeVersion + ' (no system Python needed)')"


def cut(start, end):
    first = INSTALL_PS1.index(start)
    return INSTALL_PS1[first:INSTALL_PS1.index(end, first)]


@unittest.skipUnless(os.name == "nt" and POWERSHELL.is_file(), "the installer is PowerShell on Windows")
class ChosenPythonLineTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.runtimes = self.root / "runtimes"
        # The Python that asks the program's rule: this test's own interpreter stands in for the bundled one.
        self.bundled = Path(sys.executable)

    def choose(self, version, *, leave_out=()):
        """A chosen runtime as the advanced edition leaves it: the record and every file its version requires, but
        those in `leave_out`."""
        folder = self.runtimes / version
        folder.mkdir(parents=True)
        for name in chosen_runtime.required(version):
            if name not in leave_out:
                (folder / name).write_bytes(b"")
        (self.runtimes / "chosen.json").write_text('{"version": "%s"}' % version, encoding="utf-8")

    def log(self, edition):
        functions = cut("function Get-ChosenPython {", "function Invoke-Precompile {")
        start = INSTALL_PS1.index(BUNDLED_LINE)
        lines = INSTALL_PS1[start:INSTALL_PS1.index("\n\n", start)]

        def quoted(value):
            return "'" + str(value).replace("'", "''") + "'"
        script = ("Set-StrictMode -Version 2.0\n$ErrorActionPreference = 'Stop'\n"
                  "function Ok { param([string]$m) Write-Host ('  [ok] ' + $m) }\n" + functions +
                  "\n$ChosenRuntimes = %s\n$InstallHome = %s\n$compileSource = %s\n$Python = %s\n$edition = %s\n"
                  "$runtimeVersion = '3.14'\n"
                  % (quoted(self.runtimes), quoted(self.root), quoted(SRC), quoted(self.bundled), quoted(edition))
                  + lines + "\nWrite-Host 'went on'\n")
        path = self.root / "probe.ps1"
        path.write_text(script, encoding="utf-8-sig")
        done = subprocess.run([str(POWERSHELL), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
                               str(path)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                              encoding="utf-8", errors="replace", timeout=120, creationflags=NO_WINDOW)
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertIn("went on", done.stdout)
        return [line.strip() for line in done.stdout.splitlines() if line.strip().startswith("[ok]")]

    def test_a_chosen_python_in_place_is_named_beside_the_bundled_one(self):
        self.choose("3.15.2")
        self.assertEqual(chosen_runtime.chosen(self.root), "3.15.2", "the fixture is a choice the launchers take")
        self.assertEqual(self.log("advanced"), ["[ok] Bundled Python 3.14 (no system Python needed)", LINE])

    def test_a_chosen_python_missing_a_file_it_needs_is_not_named(self):
        """The launchers run the bundled Python where any file chosen_runtime.required names is gone, so the log says
        nothing of the chosen one - a python.exe alone is not a runtime."""
        for name in chosen_runtime.required("3.15.2"):
            with self.subTest(name):
                shutil.rmtree(self.runtimes, ignore_errors=True)
                self.choose("3.15.2", leave_out=(name,))
                self.assertIsNone(chosen_runtime.chosen(self.root))
                self.assertEqual(self.log("advanced"), ["[ok] Bundled Python 3.14 (no system Python needed)"])

    def test_nothing_chosen_logs_what_it_logged(self):
        self.assertEqual(self.log("advanced"), ["[ok] Bundled Python 3.14 (no system Python needed)"])

    def test_the_standard_edition_logs_what_it_logged_whatever_a_record_says(self):
        self.choose("3.15.2")
        self.assertEqual(self.log("standard"), ["[ok] Bundled Python 3.14 (no system Python needed)"])

    def test_the_setup_windows_step_still_reads_the_bundled_line_first(self):
        flow = (ROOT / "gui" / "InstallerFlow.cs").read_text(encoding="utf-8")
        self.assertEqual(flow.count('new Milestone("[ok] Bundled Python"'), 2)
        self.assertNotIn("Chosen Python", flow)


if __name__ == "__main__":
    unittest.main()
