"""window_anchor never raises in its errand over a state it cannot read or write, and a hook that raises is said.

The owner's journal (2026-10-31 10:08:17): window_anchor 'kept', reason hook_exception, actor tripwire - about 70 s after
a reset it had seen (AFTER_RESET 60 s), while core was mid-recovery on another conversation. Its usage reads already
answer None for a session that cannot be made or answers partially, and its readings are core's validated windows, so
the calls in its errand that could raise were its own stamps (Scoped.stamped/stamp: StateError, the advanced state busy
past its 10 s timeout) and core's errand guard (StoreError, core's store busy). Each now skips with its word
(`anchor.skip_state`), or keeps nothing and goes on, in place of raising into its tripwire. And whatever hook raises,
the watcher's log now says which capability, the exception's type and where in this edition's code (runtime
`_said_raised`) - the journal's reason alone left no traceback anywhere.

Every usage read is a fake session and every request a stub process; every home is a temporary folder.

    CODEX_AR_EDITION=advanced PYTHONPATH="src;advanced/src" python -m unittest discover -s advanced/tests
"""
from __future__ import annotations

from contextlib import contextmanager, nullcontext
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

from codex_auto_resume.domain.plug import DEFER  # noqa: E402
from codex_auto_resume.logbook import LOGGER_NAME  # noqa: E402
from codex_auto_resume_advanced.engine import anchor  # noqa: E402
from codex_auto_resume_advanced.registry import WINDOW_ANCHOR  # noqa: E402
from codex_auto_resume_advanced.state import StateError  # noqa: E402
from codex_auto_resume_advanced.vocabulary import ArmingState, OptionKey  # noqa: E402
from test_advanced_window_anchor import CAP, FIVE, AnchorCase  # noqa: E402


class BusyStateTests(AnchorCase):
    """Its own stamps unreadable or unwritable, key by key, as a busy advanced.sqlite answers them."""

    def fail(self, *, reads=(), writes=()):
        """The state's stamped/stamp raising StateError for the keys named (every key for `all`), as SQLite busy past
        the connection's timeout raises through state/session._begin."""
        state = self.rt.state
        stamped, stamp, unstamp = state.stamped, state.stamp, state.unstamp

        def failing(keys, real):
            def call(capability, key, *rest):
                if keys == "all" or str(key) in {str(each) for each in keys}:
                    raise StateError("advanced state transaction failed")
                return real(capability, key, *rest)
            return call
        for name, keys, real in (("stamped", reads, stamped), ("stamp", writes, stamp), ("unstamp", writes, unstamp)):
            patched = patch.object(state, name, failing(keys, real))
            patched.start()
            self.addCleanup(patched.stop)

    def stays_on(self):
        row = self.rt.state.arming()[CAP]
        self.assertEqual((row["state"], row["reason"]), (ArmingState.ARMED, None), "its tripwire caught a raise")
        self.assertEqual(self.rt.states(fresh=True).get(CAP), ArmingState.ARMED)

    def test_the_owner_s_case_a_reset_seen_then_core_s_turn_between_the_reads_and_the_state_busy(self):
        """Fails with the fix reverted: the second read finds the window core's recovery just started, and keeping its
        reset (`_remember`) raises."""
        self.on()
        self.world.running_until, self.world.used = int(self.now) + 600, 30.0
        self.look()
        self.now = float(self.world.running_until + anchor.AFTER_RESET)
        self.look(0)                                           # the occasion's first read: idle
        self.world.running_until, self.world.used = int(self.now) + FIVE - 5, 0.0     # core's turn starts the window
        self.fail(writes="all")
        self.look(anchor.STEADY_GAP)
        self.assertEqual(self.world.started, [])
        self.assertEqual(self.codes()[-1], "anchor.skip_running")
        self.stays_on()

    def test_one_start_a_window_unreadable_is_skipped_before_anything_is_read(self):
        """Fails with the fix reverted: `_before` reads its start's stamp and raises."""
        self.on(anchor_at_1=anchor.encode_time(7, 0), anchor_after_reset=2)
        self.fail(reads=(OptionKey.ANCHOR_STARTED_AT,))
        self.run_through()
        self.assertEqual((self.world.calls, self.world.started), ([], []))
        self.assertEqual(self.codes()[0], "anchor.skip_state")
        self.stays_on()

    def test_an_occasion_that_cannot_be_read_in_the_errand_is_left_for_the_next_look(self):
        """Fails with the fix reverted: the errand's own look at what is due reads the stamps and raises (the tick's
        look already answered DEFER for that; between the two the state became busy)."""
        self.on(anchor_at_1=anchor.encode_time(7, 0), anchor_after_reset=2)
        self.now += 30
        answer = self.rt.tick(self.view)
        self.assertIsNot(answer, DEFER, "07:00: a time picked is due")
        self.fail(reads="all")
        answer.run(lambda: nullcontext(True))
        self.assertEqual((self.world.calls, self.world.started, self.codes()), ([], [], []))
        self.stays_on()

    def test_the_start_s_stamp_unwritable_inside_core_s_guard_starts_nothing(self):
        """Fails with the fix reverted: the stamp written inside core's errand guard raises out of the guard."""
        self.on(anchor_at_1=anchor.encode_time(7, 0), anchor_after_reset=2)
        self.fail(writes=(OptionKey.ANCHOR_STARTED_AT,))
        self.run_through()
        self.assertEqual(self.world.started, [])
        self.assertEqual(self.codes(), ["anchor.skip_state"])
        self.stays_on()

    def test_what_a_request_left_unwritable_is_still_counted_and_said(self):
        """Fails with the fix reverted: `_settle` keeps the token counts and raises."""
        self.on(anchor_at_1=anchor.encode_time(7, 0), anchor_after_reset=2)
        self.fail(writes=(OptionKey.ANCHOR_INPUT_TOKENS, OptionKey.ANCHOR_OUTPUT_TOKENS, OptionKey.ANCHOR_FIXED_AT,
                          OptionKey.ANCHOR_SEEN_RESET))
        self.run_through()
        self.assertEqual(len(self.world.started), 1)
        self.assertEqual(self.codes(), ["anchor.started", "anchor.fixed"])
        self.assertIn("next reset is fixed at", self.lines[-1])
        self.stays_on()


class GuardTests(AnchorCase):
    def test_core_s_guard_that_cannot_be_taken_starts_nothing(self):
        """Fails with the fix reverted: core's errand guard raises (its store busy) and the errand with it."""
        @contextmanager
        def busy():
            raise RuntimeError("State transaction failed")
            yield  # pragma: no cover

        self.on(anchor_at_1=anchor.encode_time(7, 0), anchor_after_reset=2)
        for _look in range(8):
            self.now += anchor.STEADY_GAP
            answer = self.rt.tick(self.view)
            if answer is not DEFER:
                answer.run(busy)
        self.assertEqual(self.world.started, [])
        self.assertEqual(self.codes(), ["anchor.skip_state"])
        self.assertIsNone(self.stamped(OptionKey.ANCHOR_STARTED_AT))
        row = self.rt.state.arming()[CAP]
        self.assertEqual((row["state"], row["reason"]), (ArmingState.ARMED, None))


class SaidTests(AnchorCase):
    def test_a_hook_that_raises_is_said_in_the_watcher_s_log_with_its_type_and_where(self):
        """Fails with the runtime's line reverted: nothing is logged, and the journal's hook_exception is all there is."""
        self.on(anchor_at_1=anchor.encode_time(7, 0), anchor_after_reset=2)
        self.now += 30
        answer = self.rt.tick(self.view)
        self.assertIsNot(answer, DEFER)
        self.code._scoped = None                                # a fault of the capability's own, inside its errand
        with self.assertLogs(LOGGER_NAME, "INFO") as said:
            answer.run(lambda: nullcontext(True))
        line, = [record.getMessage() for record in said.records]
        self.assertTrue(line.startswith("advanced window_anchor: a hook raised AttributeError at anchor.py:"), line)
        self.assertIn(" look", line)
        self.assertNotIn(str(self.home), line)
        self.assertNotIn("\\", line)
        self.assertNotIn("NoneType", line, "never the exception's message")
        row = self.rt.state.arming()[CAP]
        self.assertEqual((row["state"], row["reason"]), (ArmingState.OFF, "hook_exception"), "it still trips")

    def test_the_type_it_was_raised_from_is_said_too(self):
        from codex_auto_resume_advanced import runtime
        try:
            try:
                raise OSError("C:\\Users\\Someone\\secret")
            except OSError as exc:
                raise StateError("cannot open the advanced state") from exc
        except StateError:
            with self.assertLogs(LOGGER_NAME, "INFO") as said:
                runtime._said_raised(WINDOW_ANCHOR)
        line, = [record.getMessage() for record in said.records]
        self.assertEqual(line, "advanced window_anchor: a hook raised StateError (from OSError)")


if __name__ == "__main__":
    unittest.main()
