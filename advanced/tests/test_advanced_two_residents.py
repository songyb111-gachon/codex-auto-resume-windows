"""local_api and telegram_remote both on share one resident courier (v0.6.23, finding R3 of the second round's audit):
both answer P8 in one tick, and each errand used to launch and count a start, so every start of the one process spent
two of the hour's 1 + RESTARTS - after one crash and restart the next was refused. Each errand now looks again just
before it launches (engine/remote._Errand.run): one launch a tick, one start counted, and the hour's cap is what the
statements say - a first start and at most three restarts.

Held against the shipped definitions, with the resident's mutex and its launch replaced (`_running`, `_launch`), as
test_advanced_telegram does: nothing is started, no network is reached.
"""
from __future__ import annotations

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_advanced_telegram as telegram_case  # noqa: E402
from codex_auto_resume_advanced.control import remote  # noqa: E402
from codex_auto_resume_advanced.engine import remote as engine_remote  # noqa: E402
from codex_auto_resume_advanced.registry import LOCAL_API, PUSH_NOTICES, TELEGRAM_REMOTE  # noqa: E402


class BothResidentsTests(telegram_case.TelegramCase):
    def setUp(self):
        super().setUp()
        self.rt = self.runtime(PUSH_NOTICES, TELEGRAM_REMOTE, LOCAL_API)
        self.rt.arming.catalogs = telegram_case.statement.CATALOGS
        self.on("push_notices", "telegram_remote", "local_api")
        self.launches = []
        for capability in engine_remote.RESIDENT:
            code = self.rt._code_of(self.rt.registry.get(capability))
            code._running = lambda paths: False                       # the resident never takes its mutex
            code._launch = (lambda name: lambda paths: self.launches.append((self.now, name)) or True)(capability)

    def tick(self):
        answer = self.rt.tick({})
        if hasattr(answer, "run"):
            answer.run(None)

    def test_one_launch_a_tick_and_the_hour_allows_a_first_start_and_three_restarts(self):
        """Fails with the look again in _Errand.run reverted: two launches a tick, and two starts an hour."""
        ticks = []
        for _ in range(8):
            before = len(self.launches)
            self.tick()
            ticks.append(len(self.launches) - before)
            self.now += engine_remote.STARTING
        self.assertLessEqual(max(ticks), 1, "one launch a tick: %r" % ticks)
        self.assertEqual(len(self.launches), 1 + engine_remote.RESTARTS)
        self.assertEqual(len(engine_remote.starts(self.rt.state.journal_times, self.now)), 1 + engine_remote.RESTARTS,
                         "one start counted for each launch")
        said = remote.pair_state(self.rt, secrets=self.secrets, running=lambda runtime: False)
        self.assertEqual(said["state"], "stopped")

    def test_a_resident_that_came_up_meanwhile_is_not_started_again(self):
        first = self.rt._code_of(self.rt.registry.get(engine_remote.RESIDENT[0]))
        errand = first.tick({})
        self.assertTrue(hasattr(errand, "run"))
        first._running = lambda paths: True                            # another errand's start took the mutex
        errand.run(None)
        self.assertEqual(self.launches, [])


if __name__ == "__main__":
    unittest.main()
