"""The resident courier's hour of starts begins again at a setup run (v0.6.22 final, the live acceptance's re-check).

An earlier version's courier that could not start from an installed copy - every one before v0.6.22's fix - used the
hour's starts, and after the update to the fixed version the new watcher logged `gave_up` at once: the loopback API and
Telegram stayed stopped for up to an hour. A setup run (install, update, Repair) writes runtime.json; starts before it do
not count, and a crash loop after it is still bounded by RESTARTS.
"""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from codex_auto_resume_advanced.engine import remote


def journal(times):
    """A state's journal_times reading `times` for the resident's start word, whatever the capability."""
    def journal_times(capability, word, since):
        if word != remote.START_WORD or capability != remote.API:
            return []
        return [at for at in times if at >= since]
    return journal_times


class SetupFloorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.paths = SimpleNamespace(home=self.home)

    def written_at(self, when):
        record = self.home / "runtime.json"
        record.write_text("{}", encoding="utf-8")
        os.utime(record, (when, when))

    def test_starts_before_the_last_setup_run_do_not_count(self):
        now = 1_800_000_000
        failed = [now - 1500, now - 1400, now - 1300, now - 1200]      # an earlier version's four failed starts
        self.written_at(now - 600)                                       # the update's setup run, after them
        since = remote.setup_time(self.paths)
        self.assertEqual(since, now - 600)
        self.assertEqual(remote.starts(journal(failed), now, since), [])
        self.assertFalse(remote.stopped(journal(failed), now, since))
        # Without the floor the same hour reads as given up: the defect this holds.
        self.assertTrue(remote.stopped(journal(failed), now))

    def test_a_crash_loop_after_the_setup_run_is_still_bounded(self):
        now = 1_800_000_000
        self.written_at(now - 3000)
        since = remote.setup_time(self.paths)
        loop = [now - 400, now - 300, now - 200, now - 100]
        self.assertTrue(remote.stopped(journal(loop), now, since))

    def test_no_runtime_json_keeps_the_plain_hour(self):
        now = 1_800_000_000
        self.assertIsNone(remote.setup_time(self.paths))
        four = [now - 400, now - 300, now - 200, now - 100]
        self.assertEqual(remote.starts(journal(four), now, None), four)

    def test_the_errand_reads_the_floor_from_its_own_installation(self):
        now = 1_800_000_000
        self.written_at(now - 600)
        failed = [now - 1500, now - 1400, now - 1300, now - 1200]
        scoped = SimpleNamespace(now=lambda: now, journal_times=journal(failed), count=lambda word: True)
        code = remote.Resident(self.paths, remote.API, running=lambda paths: False, launch=lambda paths: True)
        code.bind(scoped)
        self.assertIsNot(code.tick(None), remote.DEFER, "a start is due: the earlier version's starts do not count")


if __name__ == "__main__":
    unittest.main()
