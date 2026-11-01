"""The edition's list of conversations running now leaves out a crash's leftover (v0.6.20 final, the owner's decision).

A conversation whose latest turn still says inProgress though it began before Windows last started can no longer run
(states.ended_by_boot, the rule core's power action reads since the same day). codex/turns.Turns.running feeds the
wrap-up's candidates (engine/usage.py), the forced stop (engine/usagestop.py) and the conversations the power action
after tasks offers to watch (control/powertasks._offered): before this, a leftover 18 or 30 days old was offered and
counted as running there for good.

    PYTHONPATH=src python -m unittest discover -s advanced/tests
"""
from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_engine import T1, T2, Harness  # noqa: E402
from codex_auto_resume.config import Paths  # noqa: E402
from codex_auto_resume.store import Store  # noqa: E402
from codex_auto_resume_advanced.codex.turns import Turns, booted_of  # noqa: E402


class RunningSinceBootTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.h = Harness(Path(temp.name) / "state")
        self.addCleanup(self.h.close)
        self.now = int(self.h.now)

    def going(self, thread, started):
        self.h.home.add_thread(thread)
        return self.h.home.add_turn(thread, status="inProgress", started=started, user_text=None, progress=False)

    def test_a_turn_begun_before_windows_started_is_not_running(self):
        """Fails with the boot rule reverted: the leftover is listed as running."""
        self.going(T1, self.now - 30 * 86400)
        self.assertEqual(Turns(self.h.home.root).running(booted=self.now - 3600), [])

    def test_a_turn_begun_since_windows_started_still_runs_beside_a_leftover(self):
        self.going(T1, self.now - 30 * 86400)
        self.going(T2, self.now - 60)
        self.assertEqual(Turns(self.h.home.root).running(booted=self.now - 3600), [T2])

    def test_the_callers_read_the_boot_time_the_heartbeat_records(self):
        """Fails with booted_of reverted to nothing: the wrap-up, the forced stop and the tasks card would count the
        leftover. The same time core's power action reads (store.watcher_status's booted_at)."""
        with tempfile.TemporaryDirectory() as root:
            paths = Paths(Path(root))
            self.assertIsNone(booted_of(paths), "no heartbeat yet: no boot time")
            with Store(paths.state_dir) as store:
                store.heartbeat(self.now, pid=1, session_id="s", started_at=self.now, ok=True, engine_state="idle",
                                code_version="t", booted_at=self.now - 3600)
            self.assertEqual(booted_of(paths), self.now - 3600)
            self.going(T1, self.now - 30 * 86400)
            self.assertEqual(Turns(self.h.home.root).running(booted=booted_of(paths)), [])

    def test_with_no_boot_time_every_turn_in_progress_counts_as_before(self):
        self.going(T1, self.now - 30 * 86400)
        self.assertEqual(Turns(self.h.home.root).running(booted="unknown"), [T1])


if __name__ == "__main__":
    unittest.main()
