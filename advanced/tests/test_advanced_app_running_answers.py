"""Whether the Codex app runs: one look at the processes, and what each caller makes of "could not tell".

The sign-in swap writes nothing under an app it cannot rule out; opening a conversation needs the app known to run; the
usage meter asks another question through the backend - is there a main it can pair with - and reads only on a yes.
"""
from __future__ import annotations

import types
import unittest
from unittest.mock import patch

from codex_auto_resume.codex import pairing
from codex_auto_resume_advanced.codex import swap
from codex_auto_resume_advanced.engine import opentarget, usage


class TheAnswers(unittest.TestCase):
    def test_could_not_tell(self):
        with patch.object(pairing, "inventory", side_effect=ValueError("no list")):
            self.assertIsNone(pairing.app_running_now())
            self.assertIs(swap._app_running(), True)
            self.assertIsNone(opentarget.app_running())

    def test_not_running(self):
        with patch.object(pairing, "inventory", return_value=[]):
            self.assertIs(pairing.app_running_now(), False)
            self.assertIs(swap._app_running(), False)
            self.assertIs(opentarget.app_running(), False)

    def test_the_meter_reads_only_on_a_yes_from_its_backend(self):
        meter = types.SimpleNamespace(_app_running=None, paths="paths")
        with patch.object(usage.inuse, "backend", side_effect=OSError("no backend")):
            self.assertIs(usage.UsageMeter._running(meter), False)


if __name__ == "__main__":
    unittest.main()
