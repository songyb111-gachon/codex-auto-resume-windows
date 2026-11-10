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


class UiFaultTests(unittest.TestCase):
    """X1: an exception in a UI callback is logged, never .NET's English dialog, and at worst the bridge is stopped."""

    def test_the_handler_is_on_before_anything_runs(self):
        main = block(gui("SettingsApp.cs"), "internal static int Main(string[] argv)")
        self.assertIn("Application.ThreadException += UiFaults.Caught;", main)
        self.assertLess(main.index("UiFaults.Caught"), main.index("SettingsRemove.IsAsked(argv)"))
        self.assertLess(main.index("UiFaults.Follow(root, persistent);"), main.index("new SettingsForm(persistent)"))

    def test_it_writes_and_keeps_the_window_until_they_keep_coming(self):
        caught = guiscan.member_body("UiFaults", "Caught")
        self.assertLess(caught.index("Write(e.Exception);"), caught.index("if (++seen < MostInAMinute) return;"))
        self.assertLess(caught.index("if (++seen < MostInAMinute) return;"), caught.index("bridge.Stop()"))
        self.assertLess(caught.index("bridge.Stop()"), caught.index("Environment.Exit(1);"))
        self.assertIn('"errors.log"', guiscan.member_body("UiFaults", "Write"))
        self.assertNotIn("MessageBox", guiscan.type_body("UiFaults"))


class StateLightNameTests(unittest.TestCase):
    """H1: a screen reader reaching the Dashboard's light hears the state, the headline beside it."""

    def test_the_light_is_named_by_every_write_of_the_headline(self):
        window = guiscan.settings()
        said = "headline.TextChanged += delegate { stateDot.AccessibleName = headline.Text; };"
        self.assertEqual(window.count(said), 1)
        self.assertLess(window.index(said), window.index('headline.Text = S("status.loading", "Loading...");'),
                        "the first words must reach it too")


if __name__ == "__main__":
    unittest.main()
