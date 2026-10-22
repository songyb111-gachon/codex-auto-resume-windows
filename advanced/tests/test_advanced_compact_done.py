"""Compact-then-continue continues only after a compaction that completed (v0.6.18, the advanced audit's M5): one still
running is waited for, and one interrupted compacted nothing - before, either let the continuation go onto a context
never compacted, to fail again and spend a unit.
"""
from __future__ import annotations

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from codex_auto_resume.domain.plug import DEFER, Alternative  # noqa: E402
from codex_auto_resume_advanced.codex import headless  # noqa: E402
import test_advanced_compact_continue as compact_tests  # noqa: E402


class CompletedOnlyTests(unittest.TestCase):
    Scoped = compact_tests.CodeTests.Scoped
    code, record = compact_tests.CodeTests.code, compact_tests.CodeTests.record
    turn = staticmethod(compact_tests.CodeTests.turn)

    def test_a_running_or_interrupted_compaction_holds_the_continuation(self):
        """Fails with the status check reverted: thread_available let it go and P16 ran the turn."""
        for status in ("inProgress", "interrupted"):
            with self.subTest(status):
                compacting = self.turn(6, {"contextCompaction": 1}, status=status)
                code = self.code(compacting)
                self.assertIs(code.gate("thread_available", self.record(), {}), Alternative.HOLD)
                route = code.unloaded(self.record())
                self.assertTrue(route is DEFER or route.mode == headless.COMPACT, "never the continuation's turn")
                self.assertIs(code.gate("known_failure", self.record(), {}), Alternative.ADMIT, "not given up")

    def test_a_completed_one_lets_it_go(self):
        done = self.code(self.turn(6, {"contextCompaction": 1}))
        self.assertIs(done.gate("thread_available", self.record(), {}), DEFER)
        self.assertEqual(done.unloaded(self.record()).mode, headless.TURN)


if __name__ == "__main__":
    unittest.main()
