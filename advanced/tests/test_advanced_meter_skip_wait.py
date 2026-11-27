"""v0.6.26 final: a usage meter look that did not read spaces the next one by SKIP_WAIT, and keeps its checked backend.

Until now a look that skipped (the app closed, unmatched, or no engine) left nothing to space the next look by, so the
meter looked on every core tick - every 30 seconds - and each look made a new Backend, which ran the engine checks'
codex.exe children again, and read a process list: about 2,880 looks a day on a PC where the app is simply closed. Now
the next look after a skip waits SKIP_WAIT (a minute, not the poll spacing: the meter still reads within about a minute
of the app opening or of core taking up the engine it serves from), and the backend made for the engine the watcher
told is kept until it tells another, so its checks probe the engine again only where its file changed.

The same stubs as test_advanced_meter_engine_elsewhere: nothing real is read, and no real codex.exe starts.

    CODEX_AR_EDITION=advanced PYTHONPATH="src;advanced/src;advanced/tests;tests" python -m unittest test_advanced_meter_skip_wait
"""
from __future__ import annotations

from pathlib import Path
import sys
import unittest

for _entry in (Path(__file__).resolve().parents[2] / "tests", Path(__file__).resolve().parent):
    if str(_entry) not in sys.path:
        sys.path.insert(0, str(_entry))

from test_advanced_meter_engine_elsewhere import NOW, MeterCase  # noqa: E402
from test_engine_moved import key  # noqa: E402
from codex_auto_resume.domain.plug import DEFER  # noqa: E402
from codex_auto_resume_advanced.engine import usage  # noqa: E402


class SpacedCase(MeterCase):
    def setUp(self):
        super().setUp()
        self.at = 0
        self.scoped.now = lambda: float(NOW + self.at)

    def meter_tick(self, at):
        """The meter's P8 answer `at` seconds in, its errand run where it gives one; whether it looked."""
        self.at = at
        answer = self.meter.tick(None)
        if answer is DEFER:
            return False
        answer.run(None)
        return True

    def probes(self):
        return self.codex.calls.count(("--version",))


class SkipWaitTests(SpacedCase):
    def test_skipped_looks_are_spaced(self):
        """Fails with the fix reverted: every tick looks again."""
        self.rows = []
        self.assertTrue(self.meter_tick(0))
        listed = self.listings
        for at in (5, 30, usage.SKIP_WAIT - 1):
            self.assertFalse(self.meter_tick(at), "looked again %d s after a skip" % at)
        self.assertEqual(self.listings, listed, "a process list read between looks")
        self.assertTrue(self.meter_tick(usage.SKIP_WAIT))
        self.assertEqual(self.scoped.counted, ["app_closed"])

    def test_a_skipped_look_runs_no_engine_check_of_its_own_again(self):
        """Fails with the fix reverted: each look's new backend runs `codex --version` again."""
        self.rows = []
        self.meter_tick(0)
        probed = self.probes()
        self.meter_tick(usage.SKIP_WAIT)
        self.meter_tick(2 * usage.SKIP_WAIT)
        self.assertEqual(self.probes(), probed)
        self.fixture.exe.write_bytes(b"MZ-a-longer-replaced-build")       # another file there now
        self.meter_tick(3 * usage.SKIP_WAIT)
        self.assertGreater(self.probes(), probed, "a replaced engine was not checked again")

    def test_a_read_comes_within_a_wait_of_the_app_opening_then_the_spacing_holds(self):
        self.rows = []
        self.meter_tick(0)
        self.serve(self.first.codex_exe)
        self.assertFalse(self.meter_tick(30))
        self.assertTrue(self.meter_tick(usage.SKIP_WAIT))
        self.assertEqual(self.scoped.counted, ["app_closed", "read"])
        self.assertEqual(self.opened, [self.first.codex_exe])
        self.assertFalse(self.meter_tick(usage.SKIP_WAIT + 2 * usage.SKIP_WAIT), "a read did not keep its spacing")

    def test_the_live_case_reads_within_a_wait_of_core_moving_the_engine(self):
        self.serve(self.package)
        self.assertTrue(self.meter_tick(0))
        self.assertTrue(self.tick(0), "core did not look for its engine again")
        self.assertEqual(self.told(), self.package)
        self.assertFalse(self.meter_tick(30))
        self.assertTrue(self.meter_tick(usage.SKIP_WAIT + 1))
        self.assertEqual(self.scoped.counted, ["unmatched", "read"])
        self.assertEqual(self.opened, [self.package])
        self.assertIn(key(self.package), {key(path) for path in self.codex.builds})


if __name__ == "__main__":
    unittest.main()
