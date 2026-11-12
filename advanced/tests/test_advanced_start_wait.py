"""v0.6.23 (second-round limits audit R3): the restart of a choice of Python and core's Start and setup count one launch
by one clock. Core's longer start wait (control.CHOSEN_START_TIMEOUT) and the Python card's restart wait
(control/pythons.RESTART_SECONDS) both begin at the launch and carry the launcher's question before its child; the
restart's is the longer, since it takes the choice back when it ends, and core's only reports.

    CODEX_AR_EDITION=advanced PYTHONPATH="src;advanced/src" python -m unittest discover -s advanced/tests -p test_advanced_start_wait.py
"""
from __future__ import annotations

import unittest

from codex_auto_resume import control
from codex_auto_resume.control import watcher
from codex_auto_resume_advanced.control import pythons


class OneLaunchOneClock(unittest.TestCase):
    def test_the_question_is_the_same_number(self):
        self.assertEqual(watcher.CHOSEN_ASK_SECONDS, pythons.LAUNCHER_ASKS_SEEN)
        self.assertEqual(watcher.WATCHER_START_TIMEOUT, pythons.WATCHER_WAIT)

    def test_the_restart_waits_at_least_as_long_as_a_start(self):
        self.assertGreaterEqual(pythons.RESTART_SECONDS, control.CHOSEN_START_TIMEOUT)


if __name__ == "__main__":
    unittest.main()
