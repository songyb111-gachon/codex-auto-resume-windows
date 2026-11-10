"""The C# window's small open findings (v0.6.23, windows-and-tooling audit area A), each held where its fix is.

Source reads through tests/guiscan.py: every behaviour here is a window's, or a wait of half an hour.

    PYTHONPATH="src;tests" python -m unittest test_window_open_findings
"""
from __future__ import annotations

from pathlib import Path
import unittest

import guiscan

ROOT = Path(__file__).resolve().parents[1]
SETUP = (ROOT / "build" / "setup" / "Setup.cs").read_text(encoding="utf-8")


def block(text: str, signature: str) -> str:
    """The method of `text` that `signature` starts, by its braces."""
    return guiscan._block(text, text.index(signature))


def gui(name: str) -> str:
    return (ROOT / "gui" / name).read_text(encoding="utf-8")


class ScriptWaitTests(unittest.TestCase):
    """U1: the setup and uninstall windows cannot be closed while their script runs, so the wait has an end."""

    def test_the_limit_is_generous(self):
        self.assertIn("internal const int ScriptMilliseconds = 1800000;", guiscan.type_body("InstallerFlow"))

    def test_the_uninstall_says_still_running_and_leaves_the_script_alone(self):
        body = block(gui("SettingsRemove.cs"), "private static int Uninstall(")
        self.assertIn("if (!run.WaitForExit(InstallerFlow.ScriptMilliseconds)) return InstallerFlow.StillRunning;", body)
        self.assertNotIn("run.WaitForExit()", body, "an unbounded wait; it also waits for the pipes' end, for ever")
        self.assertNotIn(".Kill(", body)

    def test_the_setup_window_says_still_running_and_a_console_waits_as_it_did(self):
        body = block(SETUP, "static int Install(string folder")
        self.assertIn("heard != null && waited.ElapsedMilliseconds >= CodexAutoResume.InstallerFlow.ScriptMilliseconds", body)
        self.assertIn("return CodexAutoResume.InstallerFlow.StillRunning;", body)
        self.assertNotIn(".Kill(", body)

    def test_the_folder_a_script_still_runs_from_is_not_removed(self):
        body = block(SETUP, "static int InstallFrom(byte[] archive")
        self.assertIn("stillRunning = code == CodexAutoResume.InstallerFlow.StillRunning;", body)
        self.assertIn("bool removed = stillRunning || folder.Remove();", body)


if __name__ == "__main__":
    unittest.main()
