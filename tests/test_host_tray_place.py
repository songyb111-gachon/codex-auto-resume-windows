"""Where Windows keeps the icon, held of the C# host (S6.4, P6-DESIGN 3.4 "window behaviour").

The twins of tests/test_tray_icon_motion.py's `PlacementTests` and tests/test_tray_overflow_open.py's `OverflowOpenTests`,
which hold `tray_place.IconPlacement` and `overflow_open` to what Windows says. Here the host's own code (gui/TrayPlace.cs:
`IconPlacement`, `TrayPlace.OverflowOpen`) answers, in the host's probe (tests/rustdiff/HostProbe.cs, compiled with the
surfaces and never shown): a registry and a list of windows the tests make, a clock they move, and every read the placement
made reported back. Each test is its Python original's body: the same keys, the same clock readings, the same asserted
answers and the same counts of reads.

Only a made-up registry is read, never this machine's; nothing is drawn and no window is made.
"""
from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "tests" / "rustdiff"))

import surfacehost  # noqa: E402

if not surfacehost.CSC.is_file():
    raise unittest.SkipTest("needs the in-box C# compiler")

NOTIFY_ICON_SETTINGS = r"Control Panel\NotifyIconSettings"
TRAY_NOTIFY = r"Software\Classes\Local Settings\Software\Microsoft\Windows\CurrentVersion\TrayNotify"
LOOK_AGAIN_S = 30.0
WIN11, WIN10 = "TopLevelWindowForOverflowXamlIsland", "NotifyIconOverflowWindow"


def asked(steps, *, executable, fail=None, folders=None):
    """IconPlacement in the host over `steps`, [(clock, the registry's keys as it stands)]: [(answer, the reads)]."""
    done = surfacehost.call("placement", executable=executable, uid=1, folders=folders or {}, fail=fail,
                            steps=[{"clock": clock, "keys": keys} for clock, keys in steps])
    return [(step["answer"], step["reads"]) for step in done]


def searches(reads):
    return len([step for step in reads if step[0] == "subkeys"])


class PlacementTests(unittest.TestCase):
    """Whether Windows keeps this icon in the overflow flyout, read from Windows' own setting for it."""

    EXE = r"C:\Users\ExampleUser\.codex-auto-resume\runtime\pythonw.exe"
    SETTINGS, CHEVRON = NOTIFY_ICON_SETTINGS, TRAY_NOTIFY

    def entry(self, promoted=None, path=None, uid=1, **extra):
        value = {"ExecutablePath": self.EXE if path is None else path, "UID": uid}
        if promoted is not None:
            value["IsPromoted"] = promoted
        value.update(extra)
        return value

    def once(self, keys, executable=None, fail=None, folders=None):
        (answer, reads), = asked([(0.0, keys)], executable=executable or self.EXE, fail=fail, folders=folders)
        return answer, reads

    def test_the_host_reads_the_keys_the_reference_does(self):
        from codex_auto_resume import tray_place as place
        self.assertEqual((self.SETTINGS, self.CHEVRON, LOOK_AGAIN_S),
                         (place.NOTIFY_ICON_SETTINGS, place.TRAY_NOTIFY, place.IconPlacement.LOOK_AGAIN_S))
        text = (ROOT / "gui" / "TrayPlace.cs").read_text(encoding="utf-8")
        self.assertIn('NotifyIconSettings = @"Control Panel\\NotifyIconSettings"', text)
        self.assertIn("LookAgainS = 30.0", text)

    def test_an_icon_windows_shows_on_the_taskbar_is_not_in_the_overflow_area(self):
        answer, _ = self.once({self.SETTINGS + r"\17": self.entry(1)})
        self.assertIs(answer, False)

    def test_an_icon_windows_has_not_promoted_is(self):
        for promoted in (0, None):
            with self.subTest(promoted=promoted):
                answer, _ = self.once({self.SETTINGS + r"\17": self.entry(promoted)})
                self.assertIs(answer, True)

    def test_an_icon_windows_says_nothing_about_leaves_the_rule_as_it_was(self):
        for keys in ({}, {self.SETTINGS + r"\17": self.entry(0, path=r"C:\Python313\pythonw.exe")},
                     {self.SETTINGS + r"\17": self.entry(0, uid=2)},
                     {self.SETTINGS + r"\17": self.entry(0, IconGuid="{1a2b}")}):
            with self.subTest(keys=sorted(keys.values(), key=repr)):
                answer, _ = self.once(keys)
                self.assertIsNone(answer)

    def test_a_registry_that_cannot_be_read_leaves_the_rule_as_it_was(self):
        for fail in ("subkeys", "value"):
            with self.subTest(fail=fail):
                answer, _ = self.once({self.SETTINGS + r"\17": self.entry(0)}, fail=fail)
                self.assertIsNone(answer)

    def test_the_path_is_read_as_windows_writes_it(self):
        """Windows writes a path under a known folder as that folder's GUID; case and separators are its own."""
        guid = "{deadbeef-0000-4000-8000-000000000017}"
        keys = {self.SETTINGS + r"\17": self.entry(0, path=guid + r"\Python313\pythonw.exe")}
        folders = {guid: r"C:\Program Files"}
        answer, _ = self.once(keys, executable=r"C:\PROGRAM FILES\Python313\pythonw.exe", folders=folders)
        self.assertIs(answer, True)
        answer, _ = self.once(keys, executable=r"C:\Program Files (x86)\Python313\pythonw.exe", folders=folders)
        self.assertIsNone(answer, "another folder's Python is another icon")
        answer, _ = self.once(keys, executable=r"C:\Program Files\Python313\pythonw.exe", folders={})
        self.assertIsNone(answer, "a folder Windows will not name is nothing to go on")

    def test_with_the_overflow_flyout_turned_off_every_icon_is_on_the_taskbar(self):
        keys = {self.SETTINGS + r"\17": self.entry(0), self.CHEVRON: {"SystemTrayChevronVisibility": 0}}
        answer, reads = self.once(keys)
        self.assertIs(answer, False)
        self.assertEqual([step for step in reads if step[0] == "subkeys"], [])
        keys[self.CHEVRON] = {"SystemTrayChevronVisibility": 1}
        answer, _ = self.once(keys)
        self.assertIs(answer, True)

    def test_the_entry_is_found_once_and_read_again_every_tick(self):
        keys = {self.SETTINGS + r"\17": self.entry(0)}
        changed = {self.SETTINGS + r"\17": dict(self.entry(0), IsPromoted=1)}
        steps = asked([(0.0, keys)] * 6 + [(0.0, changed)], executable=self.EXE)
        self.assertIs(steps[0][0], True)
        self.assertEqual(searches(steps[0][1]), 1)
        for answer, reads in steps[1:6]:
            self.assertIs(answer, True)
            self.assertEqual(searches(reads), 0, "the entry is found once")
        # The setting changed under it - somebody dragged the icon onto the taskbar - and the next tick sees it.
        self.assertIs(steps[6][0], False)

    def test_an_icon_windows_has_not_written_yet_is_looked_for_again_but_not_every_tick(self):
        written = {self.SETTINGS + r"\17": self.entry(0)}            # the shell wrote the icon's settings
        steps = asked([(1000.0, {}), (1000.0, {}), (1000.0 + LOOK_AGAIN_S, written)], executable=self.EXE)
        self.assertIsNone(steps[0][0])
        self.assertIsNone(steps[1][0])
        self.assertEqual(searches(steps[0][1]) + searches(steps[1][1]), 1)
        self.assertIs(steps[2][0], True)
        self.assertEqual(sum(searches(reads) for _, reads in steps), 2)

    def test_an_entry_that_goes_is_looked_for_again(self):
        first = {self.SETTINGS + r"\17": self.entry(0)}
        again = {self.SETTINGS + r"\21": self.entry(1)}            # written again, and promoted this time
        steps = asked([(1000.0, first), (1000.0 + LOOK_AGAIN_S, {}), (1000.0 + 2 * LOOK_AGAIN_S, again)],
                      executable=self.EXE)
        self.assertEqual([answer for answer, _ in steps], [True, None, False])

    def test_one_promoted_entry_among_this_icon_s_is_enough(self):
        answer, _ = self.once({self.SETTINGS + r"\17": self.entry(0), self.SETTINGS + r"\21": self.entry(1)})
        self.assertIs(answer, False)


class OverflowOpenTests(unittest.TestCase):
    """Whether the flyout is open: its own window shown and not cloaked, on Windows 11 or 10."""

    def open(self, windows, fail=False):
        return surfacehost.call("overflow", windows=[list(window) for window in windows], fail=fail)

    def test_the_shown_flyout_is_open(self):
        self.assertTrue(self.open([(WIN11, True, False)]))
        self.assertTrue(self.open([(WIN10, True, False)]))

    def test_a_hidden_or_cloaked_flyout_is_closed(self):
        self.assertFalse(self.open([(WIN11, False, False)]))
        self.assertFalse(self.open([(WIN11, True, True)]))

    def test_any_taskbar_s_open_flyout_counts(self):
        """One flyout window per taskbar: a closed one first does not hide an open one after it."""
        self.assertTrue(self.open([(WIN11, False, False), ("Other", True, False), (WIN11, True, False)]))
        self.assertFalse(self.open([(WIN11, False, False), ("Other", True, False), (WIN11, True, True)]))

    def test_no_flyout_or_no_answer_is_closed(self):
        self.assertFalse(self.open([]))
        self.assertFalse(self.open([("Other", True, False)]))
        self.assertFalse(self.open([(WIN11, True, False)], fail=True))

    def test_the_two_class_names_are_windows_own(self):
        from codex_auto_resume import tray_place as place
        self.assertEqual(place.OVERFLOW_WINDOWS, (WIN11, WIN10))
        text = (ROOT / "gui" / "TrayPlace.cs").read_text(encoding="utf-8")
        self.assertIn('OverflowWindows = { "%s", "%s" }' % (WIN11, WIN10), text)


if __name__ == "__main__":
    unittest.main()
