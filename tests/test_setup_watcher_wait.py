"""Setup waits for the watcher it started, as long as that watcher is alive (v0.6.22 final, live acceptance F3).

The advanced edition's launcher imports the engine and asks the plug whether to supervise - with a fresh check of
Codex - before it starts the watcher as a child, which imports the engine again: 10 to 15 seconds from the launcher's
start to the child's, measured. Setup waited the Dashboard's 6 seconds and ended on a Finish page saying the watcher
"could not be confirmed running" although it was running moments later.

What is held here is the three ways the wait ends - the mutex held, the process gone, the bound - with setup's
own bound (plugin_setup.WATCHER_WAIT) apart from the Dashboard's (control.WATCHER_START_TIMEOUT). Nothing sleeps for
the real bound: both are shortened, so "longer than the Dashboard waits" is a fraction of a second.
"""
from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import plugin_setup                          # noqa: E402
from codex_auto_resume import control        # noqa: E402
from codex_auto_resume.control import watcher  # noqa: E402

DASHBOARD_WAIT = 0.2      # what stands for the Dashboard's 6 seconds
SETUP_WAIT = 3.0          # what stands for setup's 45
SLOW_START = 0.6          # longer than the first, well inside the second


class Process:
    """The Popen handle: alive until `ends_after` seconds from now, if it ends at all."""

    def __init__(self, ends_after=None):
        self.born = time.monotonic()
        self.ends_after = ends_after

    def poll(self):
        if self.ends_after is None or time.monotonic() - self.born < self.ends_after:
            return None
        return 1


class WatcherWaitTests(unittest.TestCase):
    def start(self, appears_after=None, process=None):
        """`plugin_setup.start_watcher` with the mutex probe taken at `appears_after` seconds from the launch (None:
        never), and what it answered with how long it took. No process is made, and no home, registry or watcher is
        touched: the App and the launch are stand-ins."""
        born = time.monotonic()
        process = process or Process()
        probes = []

        class App:
            def __init__(self, *arguments, **keywords):
                pass

            def watcher_running(self):
                if not probes:                       # the look before the launch: nothing holds the mutex yet
                    probes.append(False)
                    return False
                probes.append(True)
                return appears_after is not None and time.monotonic() - born >= appears_after

        with tempfile.TemporaryDirectory() as folder, \
                mock.patch.object(plugin_setup, "App", App), \
                mock.patch.object(plugin_setup, "python_for_watcher", return_value=Path(folder) / "pythonw.exe"), \
                mock.patch.object(plugin_setup.subprocess, "Popen", return_value=process), \
                mock.patch.object(plugin_setup, "WATCHER_WAIT", SETUP_WAIT), \
                mock.patch.object(watcher, "WATCHER_START_TIMEOUT", DASHBOARD_WAIT), \
                mock.patch.object(watcher, "WATCHER_START_INTERVAL", 0.01):
            began = time.monotonic()
            answer = plugin_setup.start_watcher(Path(folder))
            return answer, time.monotonic() - began

    def test_a_watcher_that_starts_after_the_dashboard_s_wait_is_confirmed(self):
        """The reported case: alive, not yet holding its mutex when the Dashboard's wait would have ended."""
        answer, took = self.start(appears_after=SLOW_START)
        self.assertEqual(answer, "running")
        self.assertGreaterEqual(took, SLOW_START - 0.05)
        self.assertGreater(took, DASHBOARD_WAIT)

    def test_a_watcher_that_holds_its_mutex_at_once_returns_at_once(self):
        answer, took = self.start(appears_after=0.0)
        self.assertEqual(answer, "running")
        self.assertLess(took, DASHBOARD_WAIT, "it did not wait for any bound")

    def test_a_process_that_ends_is_exited_and_not_waited_for(self):
        answer, took = self.start(appears_after=None, process=Process(ends_after=0.05))
        self.assertEqual(answer, "exited")
        self.assertLess(took, SETUP_WAIT / 2, "the end of the process ends the wait")

    def test_a_watcher_alive_and_never_seen_is_unconfirmed_after_setup_s_wait_and_no_longer(self):
        answer, took = self.start(appears_after=None)
        self.assertEqual(answer, "unconfirmed")
        self.assertGreaterEqual(took, SETUP_WAIT - 0.05)
        self.assertLess(took, SETUP_WAIT + 2.0)

    def test_the_bounds_stand_where_they_were_decided(self):
        """Setup waits for the real start of the measured 10 to 15 seconds with room (twice the slowest at least) and
        is the only caller that does: the Dashboard's Start watcher and the bridge keep their 6 seconds, and say
        "not confirmed running yet", which is no verdict."""
        self.assertGreaterEqual(plugin_setup.WATCHER_WAIT, 30.0)
        self.assertEqual(control.WATCHER_START_TIMEOUT, 6.0)
        self.assertGreater(plugin_setup.WATCHER_WAIT, control.WATCHER_START_TIMEOUT)


if __name__ == "__main__":
    unittest.main()
