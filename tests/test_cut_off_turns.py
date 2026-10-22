"""A recovery turn cut off by a closed Codex or a PC that went off is judged by what it did.

Codex writes a turn's end only while the turn runs. When Codex closes, or the PC sleeps into a
shutdown or restarts, in the middle of a recovery turn, that turn's row says `inProgress` for good.
Two of the owner's recoveries (2026-10-20 and 2026-10-21) did real work in such a turn and were then
shown as errors: one moved to `outcome_unverified(stale_turn_row)` once a later turn finished,
without asking whether the turn did anything, and the other stayed "running" because the later
turn the person had started after the reboot was itself still running.

The rule (engine/outcome.py): a turn whose row says inProgress is cut off once a later turn of its
conversation has started, whatever that turn's status - Codex runs one turn at a time - or once
Windows started after it began. A cut-off turn is judged as a failed one is: progress makes it
`recovered(progress_then_turn_cut_off)`; none leaves it `outcome_unverified(stale_turn_row)` as
before. A person's message in it still hands it over first, and a turn really still running stays
`turn_started`. Driven through test_outcomes' World: the real Engine, Store and LocalSource over a
simulated Codex home.
"""
from __future__ import annotations

from pathlib import Path
import sys
import unittest

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from test_outcomes import World  # noqa: E402

from codex_auto_resume import machine  # noqa: E402

CUT_OFF = ("recovered", "progress_then_turn_cut_off")
STALE = ("outcome_unverified", "stale_turn_row")


class CutOffTurnTests(unittest.TestCase):
    def world(self) -> World:
        w = World(self)
        w.enable()
        return w

    def booted(self, w, at):
        """The watcher's heartbeat, saying Windows started at `at`."""
        w.store.heartbeat(w.now, pid=4242, session_id="session", started_at=w.now, ok=True,
                          engine_state="compatible", code_version="0.0.0", booted_at=at)

    def outcome(self, w, key):
        for _ in range(3):
            w.tick(30)
        row = w.get(key)
        return row, (row["state"], row["last_error"])

    def test_a_later_finished_turn_after_a_turn_that_worked_is_a_recovery(self):
        """Case A: the turn did work, the PC went off, and later turns of the person's finished."""
        w = self.world()
        thread, key, turn = w.started(progress=True)
        w.home.add_turn(thread, status="completed")
        row, judged = self.outcome(w, key)
        self.assertEqual(judged, CUT_OFF)
        self.assertEqual(machine.public_code(row), "recovered")
        self.assertEqual(machine.public_reason(row), "progress_then_turn_cut_off")
        self.assertEqual(row["recovery_turn_status"], "inProgress")
        self.assertEqual(row["recovery_turn_id"], turn)
        self.assertIsNotNone(row["outcome_at"])
        self.assertEqual(w.store.statistics()["outcomes"]["recovered"], 1)
        # No failure is registered for it: there is no failed turn to register.
        self.assertEqual(len(w.records(thread)), 1)

    def test_a_later_turn_still_running_ends_a_turn_that_worked(self):
        """Case B: after the reboot the person started a new turn that is still running."""
        w = self.world()
        thread, key, _ = w.started(progress=True)
        w.home.add_turn(thread, status="inProgress")
        _, judged = self.outcome(w, key)
        self.assertEqual(judged, CUT_OFF)

    def test_windows_starting_after_the_turn_began_ends_it(self):
        """The PC restarted and no later turn exists yet: the boot time alone tells."""
        w = self.world()
        thread, key, _ = w.started(progress=True)
        w.tick(600)
        self.booted(w, w.now - 60)
        _, judged = self.outcome(w, key)
        self.assertEqual(judged, CUT_OFF)

    def test_a_boot_before_the_turn_began_ends_nothing(self):
        w = self.world()
        thread, key, _ = w.started(progress=True)
        self.booted(w, w.get(key)["turn_started_at"] - 3600)
        row, _ = self.outcome(w, key)
        self.assertEqual(row["state"], "turn_started")

    def test_a_cut_off_turn_that_did_nothing_stays_unverified(self):
        w = self.world()
        thread, key, _ = w.started(progress=False)
        w.home.add_turn(thread, status="inProgress")
        _, judged = self.outcome(w, key)
        self.assertEqual(judged, STALE)

    def test_a_turn_really_still_running_stays_started(self):
        w = self.world()
        thread, key, _ = w.started(progress=True)
        row, _ = self.outcome(w, key)
        self.assertEqual(row["state"], "turn_started")
        self.assertEqual(row["recovery_turn_status"], "inProgress")

    def test_a_persons_message_in_the_turn_is_judged_first(self):
        """Before the cut-off: a person's message after the turn's work makes it a recovery the person joined
        (2026-10-22, tests/test_progress_then_user_joined.py); one before any work still hands it over."""
        for progress, expected in ((True, ("recovered", "progress_then_user_joined")),
                                   (False, ("handed_over", "user_joined"))):
            with self.subTest(progress=progress):
                w = self.world()
                thread, key, _ = w.started(progress=progress, steer_user=True)
                w.home.add_turn(thread, status="inProgress")
                _, judged = self.outcome(w, key)
                self.assertEqual(judged, expected)

    def test_the_reason_is_a_known_one(self):
        """Not shown as `other` anywhere a reason is shown or stored."""
        self.assertIn("progress_then_turn_cut_off", machine.REASONS)
        self.assertEqual(machine.public_reason({"state": "recovered", "last_error": "progress_then_turn_cut_off"}),
                         "progress_then_turn_cut_off")


class LaterStartedTests(unittest.TestCase):
    """history.turn_observation's `later_started`: any later turn, a running one included."""

    def test_later_started_counts_a_running_later_turn_and_later_terminal_does_not(self):
        w = World(self)
        w.enable()
        thread, key, turn = w.started(progress=True)
        seen = w.source.turn_observation(thread, turn, w.engine.proof(w.get(key)))
        self.assertEqual((seen["later_started"], seen["later_terminal"]), (False, False))
        w.home.add_turn(thread, status="inProgress")
        seen = w.source.turn_observation(thread, turn, w.engine.proof(w.get(key)))
        self.assertEqual((seen["later_started"], seen["later_terminal"]), (True, False))


if __name__ == "__main__":
    unittest.main()
