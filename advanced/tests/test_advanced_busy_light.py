# ADVANCED-EDITION-CODE: in the advanced edition's tree, never the standard one's.
r"""v0.6.20 (the owner's decision of 2026-10-28): an advanced call with an action lights the header while it is pending.

The advanced edition's actions (Turn on, Keep it on, ...) go through AdvancedCall, which counts them in `busy` as the
core's own are, so the header shows the working light, "checking", for as long as the call is in flight and gives the
watcher's light back when it returns (tests/test_gui_busy_light.py holds the rule itself). Driven through the advanced
window's own AdvancedCall, held in flight by the stand-in `python.exe` of tests/busycase.py. Nothing real is touched.

GUI test module: compiles real executables, so it runs on its own (gui_lock.sh, one module at a time).

    PYTHONPATH=src;advanced/src;tests python -m unittest advanced/tests/test_advanced_busy_light.py
"""
from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

# This folder for pagecase, and tests/ for busycase - the release lane's path has neither (advancedcase.py does the same).
for entry in (Path(__file__).resolve().parents[2] / "tests", Path(__file__).resolve().parent):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from busycase import BusyCase  # noqa: E402
from pagecase import CSC, POWERSHELL, compile_window  # noqa: E402

CASES = [{"name": "keep_on", "snapshot": "running", "command": "advanced-keep-on"},
         {"name": "arm_stopped", "snapshot": "stopped", "command": "advanced-arm"}]


@unittest.skipUnless(CSC.is_file() and POWERSHELL.is_file(), "needs the in-box compiler and PowerShell")
class BusyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        work = Path(cls.folder.name).resolve()
        cls.case = BusyCase(compile_window(work), work, CASES, hold="advanced-keep-on,advanced-arm")
        cls.answer = cls.case.run()

    @classmethod
    def tearDownClass(cls):
        cls.case.stop()
        cls.folder.cleanup()

    def setUp(self):
        self.assertTrue(self.answer, self.case.failure()[-3000:] or "the probe wrote no result")

    def test_an_advanced_action_lights_the_working_light_while_it_is_pending_and_gives_it_back(self):
        """Fails with the rule gone (BusyLight not applied in Hero): the light stays "recovering" throughout."""
        found = self.answer["keep_on"]
        self.assertEqual(found["before"], "recovering")
        self.assertEqual((found["busy_while"], found["during"], found["during_tick"]), (1, "checking", "checking"))
        self.assertEqual((found["busy_after"], found["after"]), (0, "recovering"))

    def test_a_watcher_not_running_keeps_its_grey_light_through_an_advanced_action(self):
        found = self.answer["arm_stopped"]
        self.assertEqual((found["before"], found["during"], found["after"]), ("idle", "idle", "idle"))
        self.assertEqual((found["busy_while"], found["busy_after"]), (1, 0))


if __name__ == "__main__":
    unittest.main()
