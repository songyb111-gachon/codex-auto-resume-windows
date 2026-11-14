"""What a starting watcher says of the one before it, and whose pid a refusal is (v0.6.23 final, M1 and M2 of the owner's
logs of 2026-11-13).

M1: the first heartbeat of a new watcher writes over the row the one before it left, and with it the only trace that the
one before ended without stopping. The new one now reads that row first and, where the Dashboard's own reading
(control/watcher.how_it_ended) says UNEXPECTED, logs one line: that watcher's pid and when it was last seen. M2: the line of
a watcher that lost the single-instance mutex, and the "refusing to run" lines beside it, name the pid that is ending, so
the log no longer reads as if the watcher that started had exited.

Temporary state folders only; no mutex, stop event or watcher of this PC is touched.

    PYTHONPATH="src;tests" python -m unittest test_watcher_before_this_one
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from codex_auto_resume.domain.vocabulary import WatcherEnd  # noqa: E402
from codex_auto_resume.runtime import loop  # noqa: E402
from codex_auto_resume.store import Store  # noqa: E402
from codex_auto_resume.windows import AdapterError  # noqa: E402

NOW = 1_800_000_000.0
SIGN_IN = "00000000001a2b3c"
BOOTED = NOW - 3600


class Said:
    """A logger that keeps each line as it would be written."""

    def __init__(self):
        self.lines = []

    def info(self, text, *arguments):
        self.lines.append(text % arguments if arguments else text)


class Health:
    def __init__(self, sign_in=SIGN_IN, booted_at=BOOTED):
        self.sign_in, self.booted_at = sign_in, booted_at


class Loop(loop.WatchLoop):
    def __init__(self):
        self.logger = Said()


class BeforeThisOneTests(unittest.TestCase):
    def setUp(self):
        made = tempfile.TemporaryDirectory()
        self.addCleanup(made.cleanup)
        self.store = Store(Path(made.name) / "state")
        self.addCleanup(self.store.close)
        self.loop = Loop()

    def beat(self, *, pid=31512, sign_in=SIGN_IN, booted_at=BOOTED, at=NOW - 120):
        self.store.heartbeat(at, pid=pid, session_id="s", started_at=at - 600, ok=True, engine_state="verified",
                             code_version="0.6.23", sign_in=sign_in, booted_at=booted_at)

    def lines(self, health=None):
        self.loop._predecessor(self.store, health or Health())
        return [line for line in self.loop.logger.lines if "the watcher before this one" in line]

    def test_one_that_ended_without_stopping_in_this_start_of_windows_is_said_with_its_pid_and_last_sight(self):
        """Fails with the reading reverted: the next heartbeat erases the only trace of that end."""
        self.beat()
        (line,) = self.lines()
        seen = time.strftime("%H:%M:%S", time.localtime(NOW - 120))
        self.assertEqual(line, "the watcher before this one (pid 31512, last seen %s) ended without stopping, in this "
                               "start of Windows" % seen)

    def test_it_is_read_before_this_watcher_s_own_first_heartbeat(self):
        """The order in _loop: the line comes from the row the one before left, not from this watcher's own beat."""
        source = (ROOT / "src" / "codex_auto_resume" / "runtime" / "loop.py").read_text(encoding="utf-8")
        body = source[source.index("    def _loop("):]
        self.assertLess(body.index("self._predecessor(store, health)"), body.index("self._heartbeat("))

    def test_nothing_is_said_of_one_that_stopped_on_purpose_or_ran_in_another_start_or_sign_in(self):
        for case, marked, health in (
                ("clean", True, Health()),
                ("another start of Windows", False, Health(booted_at=BOOTED + 7200)),
                ("another sign-in", False, Health(sign_in="0000000000000999")),
                ("nothing read of this process", False, Health(sign_in=None, booted_at=None))):
            with self.subTest(case):
                self.loop.logger.lines = []
                self.beat()
                if marked:
                    self.assertTrue(self.store.watcher_ended(NOW - 100, WatcherEnd.CLEAN.value))
                self.assertEqual(self.lines(health), [])

    def test_nothing_is_said_with_no_row_and_a_reading_that_fails_costs_only_the_line(self):
        self.assertEqual(self.lines(), [])

        class Broken:
            def watcher_status(self):
                raise OSError("busy")
        self.loop._predecessor(Broken(), Health())
        self.assertEqual(self.loop.logger.lines, [])

    def test_the_line_holds_nothing_personal(self):
        """A pid and a time of day: no path, no user name, no sign-in id."""
        self.beat()
        (line,) = self.lines()
        self.assertNotIn(SIGN_IN, line)
        self.assertNotIn("\\", line)
        self.assertNotIn(os.environ.get("USERNAME", "ExampleUser"), line)
        self.assertRegex(line, r"^the watcher before this one \(pid [0-9]+, last seen [0-9]{2}:[0-9]{2}:[0-9]{2}\)")


class Refusals(loop.WatchLoop):
    """A watcher whose named objects answer as each case says; nothing real is opened."""

    def __init__(self, mutex=None, stop=None):
        self.logger = Said()
        self._mutex_error, self._stop_error = mutex, stop

    def mutex(self, timeout=None):
        raise AdapterError(self._mutex_error)

    def stop_event(self):
        raise AdapterError(self._stop_error)


class Taken:
    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


class RefusalPidTests(unittest.TestCase):
    def pid_in(self, line):
        self.assertIn("(pid %d)" % os.getpid(), line)

    def test_the_watcher_that_lost_the_mutex_names_its_own_pid(self):
        """Fails with M2 reverted: "watcher started (pid A)" then "another watcher ... exiting" read as A had exited."""
        watcher = Refusals(mutex="mutex_busy")
        with patch.object(loop.time, "sleep"):
            self.assertEqual(watcher.run(), loop.EXIT_BUSY)
        (line,) = watcher.logger.lines
        self.assertTrue(line.startswith("another watcher already holds the single-instance mutex; exiting"), line)
        self.pid_in(line)

    def test_the_refusing_to_run_lines_name_the_pid(self):
        watcher = Refusals(mutex="mutex_denied")
        self.assertEqual(watcher.run(), loop.EXIT_ERROR)
        self.assertIn("refusing to run", watcher.logger.lines[-1])
        self.pid_in(watcher.logger.lines[-1])
        watcher = Refusals(stop="stop_event_foreign")
        watcher.mutex = lambda timeout=None: Taken()
        self.assertEqual(watcher.run(), loop.EXIT_ERROR)
        self.assertIn("stop event unavailable", watcher.logger.lines[-1])
        self.pid_in(watcher.logger.lines[-1])

    def test_the_home_lock_refusal_names_the_pid(self):
        source = (ROOT / "src" / "codex_auto_resume" / "runtime" / "loop.py").read_text(encoding="utf-8")
        self.assertRegex(source, re.compile(r'"refusing to run \(pid %d\)", exc, os\.getpid\(\)\)'))
        self.assertEqual(source.count("refusing to run (pid %d)"), 3, "every refusing-to-run line")


if __name__ == "__main__":
    unittest.main()
