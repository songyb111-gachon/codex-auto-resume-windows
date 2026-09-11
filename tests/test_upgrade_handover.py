"""An upgrade replaces the running watcher, and the launchers run only system binaries.

Both came out of the security review for v0.5.7.

Upgrading used to rename app\\ and runtime\\ under a live watcher - which Windows allows -
and leave the old process running the old code from the renamed copy, while setup saw
the watcher mutex held and started nothing. For an ordinary release that delays the new
version until the next sign-in. For a security fix it means the fix is installed and not
in effect, so "upgrade" would not have been the remedy the changelog says it is. The
installer now asks the watcher to stop through its own stop event and waits for it.

Measured on real Windows with the exact block from install.ps1 run against a staged
installation: a running watcher is handed over in under two seconds; a stand-in that
ignores the request is left running after sixty seconds, never killed, and the installer
says so instead of claiming the new version is running.

Install.cmd and Uninstall.cmd called `chcp` and `powershell.exe` by bare name, and
cmd.exe searches the current directory first. Extracted into a Downloads folder that
already held a planted chcp.bat, the verified installer ran the planted file before its
own script. Reproduced before the fix.
"""
from __future__ import annotations

from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
INSTALL = ROOT / "install" / "install.ps1"
LAUNCHERS = [ROOT / "install" / "Install.cmd", ROOT / "install" / "Uninstall.cmd"]


class LauncherPathTests(unittest.TestCase):
    def test_system_binaries_are_called_by_absolute_path(self):
        for launcher in LAUNCHERS:
            text = launcher.read_text(encoding="utf-8")
            with self.subTest(launcher.name):
                self.assertIn(r'"%SystemRoot%\System32\chcp.com"', text)
                self.assertIn(r'"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"', text)

    def test_no_command_is_resolved_through_the_current_directory(self):
        """Every line that runs something names it by absolute path, or is a cmd builtin."""
        builtins = {"@echo", "setlocal", "title", "set", "echo.", "echo", "if", "pause", "exit"}
        for launcher in LAUNCHERS:
            for number, line in enumerate(launcher.read_text(encoding="utf-8").splitlines(), 1):
                stripped = line.strip()
                if not stripped:
                    continue
                first = stripped.split()[0].lower()
                with self.subTest("%s:%d" % (launcher.name, number)):
                    if first.startswith('"%systemroot%'):
                        continue
                    self.assertIn(first, builtins, "run by bare name: %r" % stripped)

    def test_no_stray_control_characters(self):
        """A mangled backslash once became a vertical tab inside one of these paths."""
        for launcher in LAUNCHERS:
            with self.subTest(launcher.name):
                self.assertFalse(re.search(rb"[\x00-\x08\x0b\x0c\x0e-\x1f]", launcher.read_bytes()))


class UpgradeHandoverTests(unittest.TestCase):
    def setUp(self):
        self.source = INSTALL.read_text(encoding="utf-8")
        self.handover = self.source[self.source.index("$previousWatcherStillRunning = $false"):
                                    self.source.index("# Replace only the program directories.")]

    def test_the_watcher_is_handed_over_before_the_files_are_replaced(self):
        handover = self.source.index("$previousWatcherStillRunning = $false")
        swap = self.source.index("Move-Item -Path $pair.dst -Destination $aside")
        setup = self.source.index("$setupArgs = @('setup')")
        self.assertLess(handover, swap)
        self.assertLess(swap, setup)

    def test_it_asks_through_the_stop_event_and_never_kills(self):
        self.assertIn("Invoke-Setup @('stop')", self.handover)
        self.assertNotIn("Stop-Process", self.handover,
                         "a watcher killed mid-submission cannot prove what it sent")

    def test_the_wait_is_bounded(self):
        self.assertRegex(self.handover, r"AddSeconds\(\d+\)")
        self.assertIn("while ((Get-Date) -lt $deadline", self.handover)

    def test_only_this_installations_watcher_counts(self):
        start = self.source.index("function Get-OwnedWatcherProcess")
        body = self.source[start:self.source.index("function Invoke-Codex", start)]
        self.assertIn("Test-PathInside $exe $RunDir", body)
        self.assertIn("watcher-launcher", body)

    def test_the_count_is_not_wrapped_into_a_constant(self):
        """`@(f).Count` of a function returning `,$array` is always 1."""
        self.assertNotIn("@(Get-OwnedWatcherProcess)", self.source)

    def test_a_watcher_left_running_is_reported_not_hidden(self):
        tail = self.source[self.source.index("Step 'Checking the installation'"):]
        self.assertIn("$previousWatcherStillRunning", tail)
        branch = tail[tail.index("elseif ($previousWatcherStillRunning)"):]
        branch = branch[:branch.index("} else {")]
        self.assertNotIn("Installed and running", branch)
        self.assertIn("Stop watcher", branch)


if __name__ == "__main__":
    unittest.main()
