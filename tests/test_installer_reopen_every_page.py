"""A Dashboard closed for a repair or an update opens again whatever page it was on and however it was started.

The v0.6.19 live acceptance (A8): a Repair from the setup program's Maintain page closed the open Dashboard -
"Closing the Dashboard so it opens again on the new version", "[ok] The Dashboard closed" - and never opened it again;
the finished page offered "Open the Dashboard" instead. The window had answered: it wrote its reopen record
(gui/WindowReopen.cs, CloseForUpdate), whose words are its own reopen's (ReopenArguments). But the installer opens a
record only in the words its rule lists (install.ps1, Open-ClosedDashboard), and that rule was made from the standard
window's pages alone. The advanced edition's window, on Advanced features or Chat, writes `--page=advanced` or
`--page=chat` (advanced/gui/AdvancedPage.cs, ReopenArgumentsWritten) - and the record was removed and refused without
a word. A window that could not leave another app's view (a Dashboard opened from the tray of a watcher Codex started,
gui/HostApp.cs) adds `--outside`, refused the same way. Update A1 reopened because that window was on Pending.

Not the cause, though it was the first guess: the watcher's stop ending a Dashboard it started. The close step runs
after the watcher has stopped and only while a Dashboard is still found (install.ps1: the hand-over waits until no
watcher runs, then `$dashboardsOpen = $upgrade -and (Get-OwnedDashboardProcess).Count -gt 0`), and the tray starts the
window with nothing that ties it to the watcher (ui/tray/dashboard.py: a plain Popen, close_fds, no job of ours).
"""
from __future__ import annotations

from pathlib import Path
import re
import unittest

import test_upgrade_handover as handover

ROOT = Path(__file__).resolve().parents[1]
ADVANCED_GUI = ROOT / "advanced" / "gui"


def constant(path, name):
    """A C# string constant's value, from its declaration."""
    found = re.search(r'const string %s = "([^"]+)";' % name, path.read_text(encoding="utf-8"))
    if not found:
        raise AssertionError("%s is not declared in %s" % (name, path.name))
    return found.group(1)


class ReopenEveryPageTests(unittest.TestCase):
    def setUp(self):
        self.text = handover.INSTALL.read_text(encoding="utf-8")

    run_reopen = handover.DashboardAfterUpdateTests.run_reopen
    end_stand_in = handover.DashboardAfterUpdateTests.end_stand_in

    def test_the_advanced_windows_own_pages_open_again(self):
        """Advanced features and Chat, read from the advanced window's own names, and the keyboard's place it writes."""
        advanced = constant(ADVANCED_GUI / "AdvancedPage.cs", "AdvancedPageName")
        chat = constant(ADVANCED_GUI / "AdvancedChat.cs", "ChatPageName")
        written = (ADVANCED_GUI / "AdvancedPage.cs").read_text(encoding="utf-8")
        written = written[written.index("static partial void ReopenArgumentsWritten("):][:600]
        for word in ('arguments.Insert(0, "--page=" + AdvancedPageName)', 'arguments.Insert(0, "--page=" + ChatPageName)',
                     'arguments.Add("--focus=" + focus)'):
            self.assertIn(word, written, "the advanced window no longer writes this; read what it writes now")
        lines = ["--page=%s --bounds=10,20,800,600 --theme=system --design=soft --reopened=1 --focus=page.%s"
                 % (advanced, advanced),
                 "--page=%s --bounds=-8,0,1200,900 --maximized --frame=8,0,8,8 --theme=dark --design=classic --reopened=2"
                 % chat]
        records = [("reopen-after-update-%d.txt" % (300 + number), line, None) for number, line in enumerate(lines)]
        said, started, left = self.run_reopen(records)
        self.assertEqual(said.count("[ok] The Dashboard was opened again on the new version"), 2, said)
        self.assertIn("--page=" + advanced, started)
        self.assertIn("--page=" + chat, started)
        self.assertEqual(left, [])

    def test_a_window_that_stayed_inside_another_apps_view_opens_again(self):
        """Its reopen adds HostApp.Outside, which every parser of the window takes and otherwise ignores."""
        outside = constant(ROOT / "gui" / "HostApp.cs", "Outside")
        reopen = (ROOT / "gui" / "WindowReopen.cs").read_text(encoding="utf-8")
        reopen = reopen[reopen.index("internal static string ReopenArguments("):][:2500]
        self.assertIn("arguments.Add(HostApp.Outside)", reopen)
        said, started, left = self.run_reopen([("reopen-after-update-401.txt",
                                                "--page=pending --reopened=1 " + outside, None)])
        self.assertEqual(said.count("[ok] The Dashboard was opened again on the new version"), 1, said)
        self.assertIn(outside, started)
        self.assertEqual(left, [])

    def test_the_rule_still_refuses_what_no_window_takes(self):
        refused = ["--page=Advanced", "--page=advancedx", "--page=chat --uninstall", "--outside=1", "--outsider",
                   "--focus=page.advanced;calc", "--page=chat  --reopened=1"]
        records = [("reopen-after-update-%d.txt" % (500 + number), line, None) for number, line in enumerate(refused)]
        said, started, left = self.run_reopen(records)
        self.assertEqual(started, [], said)
        self.assertEqual(left, [])


if __name__ == "__main__":
    unittest.main()
