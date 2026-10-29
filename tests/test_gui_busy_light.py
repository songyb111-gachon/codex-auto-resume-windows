r"""v0.6.20 (the owner's decision of 2026-10-28): the header's light shows an action in flight.

A light that does not move while work runs reads as broken or idle. While an action the window counts in `busy` is
pending - Retry now, Rescan, and the advanced edition's calls - the header shows the working light, "checking" (the arc
the installer shows for its run), over the light the watcher's state gives, and it goes back at once when the call has
returned (SetBusy, Hero, BusyLight). A watcher not known to be running (idle) and one that needs a person (attention)
keep their lights: those are true whatever the window is doing. The headline is not touched.

Driven through the real window: Retry now and Rescan are the window's own methods, held in flight by a stand-in
`python.exe` that answers them only when the test lets it (tests/busycase.py). Nothing of the real installation is read
or written; nothing is shown. The advanced edition's call is test_advanced_busy_light's.

GUI test module: compiles real executables, so it runs on its own (gui_lock.sh, one module at a time).
"""
from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import guiscan
from busycase import BusyCase
from test_gui_v0611_access import CSC, POWERSHELL, compile_window

CASES = [{"name": "retry", "snapshot": "running", "action": "retry"},
         {"name": "rescan", "snapshot": "running", "action": "rescan"},
         {"name": "retry_stopped", "snapshot": "stopped", "action": "retry"},
         {"name": "rescan_attention", "snapshot": "attention", "action": "rescan"}]


@unittest.skipUnless(CSC.is_file() and POWERSHELL.is_file(), "needs the in-box compiler and PowerShell")
class WindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        work = Path(cls.folder.name).resolve()
        cls.case = BusyCase(compile_window(work), work, CASES, hold="retry-now,rescan")
        cls.answer = cls.case.run()

    @classmethod
    def tearDownClass(cls):
        cls.case.stop()
        cls.folder.cleanup()

    def setUp(self):
        self.assertTrue(self.answer, self.case.failure()[-3000:] or "the probe wrote no result")

    def test_retry_now_lights_the_working_light_while_it_is_pending_and_gives_it_back(self):
        """Fails with the rule gone (BusyLight not applied in Hero): the light stays "recovering" throughout."""
        found = self.answer["retry"]
        self.assertEqual(found["before"], "recovering")
        self.assertEqual(found["busy_while"], 1)
        self.assertEqual(found["during"], "checking", "at once, not at the next second's tick")
        self.assertEqual(found["during_tick"], "checking", "and the tick keeps it")
        self.assertEqual((found["busy_after"], found["after"]), (0, "recovering"))

    def test_rescan_lights_the_working_light_while_it_is_pending_and_gives_it_back(self):
        found = self.answer["rescan"]
        self.assertEqual(found["before"], "recovering")
        self.assertEqual((found["busy_while"], found["during"], found["during_tick"]), (1, "checking", "checking"))
        self.assertEqual((found["busy_after"], found["after"]), (0, "recovering"))

    def test_a_watcher_not_running_keeps_its_grey_light(self):
        found = self.answer["retry_stopped"]
        self.assertEqual((found["before"], found["during"], found["during_tick"], found["after"]),
                         ("idle", "idle", "idle", "idle"))

    def test_a_watcher_that_needs_a_person_keeps_its_amber_light(self):
        found = self.answer["rescan_attention"]
        self.assertEqual((found["before"], found["during"], found["during_tick"], found["after"]),
                         ("attention", "attention", "attention", "attention"))


class SourceTests(unittest.TestCase):
    """The rule is one: SetBusy tells the header, Hero applies BusyLight, and every action goes through SetBusy."""

    @staticmethod
    def body(member):
        return guiscan.member_body("SettingsForm", member)

    def test_the_header_is_told_when_the_count_changes_and_the_rule_is_applied_where_the_light_is_set(self):
        self.assertIn("UpdateCountdowns();", self.body("SetBusy"))
        self.assertIn("BusyLight(HeaderLight(status, pending, word), busy > 0)", self.body("Hero"))

    def test_retry_now_and_rescan_are_counted_in_busy(self):
        self.assertIn("SetBusy(true)", self.body("CallAsync"))
        self.assertIn('CallAsync("retry-now"', self.body("RetryNow"))
        self.assertIn('CallAsync("rescan"', self.body("Rescan"))


if __name__ == "__main__":
    unittest.main()
