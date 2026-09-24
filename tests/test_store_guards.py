"""Every refusal `Store.update` makes, one test each.

These are the rules that keep a record from being written into a state it must never reach:
a terminal record brought back to life, a send that may have happened rubbed out, a claimed
record slipped back to waiting without its send disproved, a recovery turn rewritten, a
cancellation withdrawn. Each one is a single `raise` inside the write transaction, and two of
them had nothing exercising them at all before this file.

They are written out here because v0.6.10-alpha turns `store.py` into a package, and a guard
that nothing calls is a guard a move can drop without a single test going red.

Each test says what somebody would have to do for the refusal to matter, so a later reader can
tell a rule that protects the user from a rule that only protects the schema.
"""
from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

_HERE = str(Path(__file__).resolve().parent)
for entry in (str(Path(_HERE).parent / "src"), _HERE):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from codex_auto_resume import machine  # noqa: E402
from codex_auto_resume.store import Store, StoreError  # noqa: E402

NOW = 1_800_000_000.0
THREAD = "0a1b2c3d-0001-7000-8000-000000000001"
TURN = "0a1b2c3d-0002-7000-8000-000000000002"
OTHER_TURN = "0a1b2c3d-0003-7000-8000-000000000003"
QUEUE = "0a1b2c3d-0004-7000-8000-000000000004"
KEY = "a" * 64
LIMITS = {"max_chain_continuations": 6, "max_recovery_attempts": 5, "max_no_progress": 3}
ALL_PASS = {name: (machine.PASS, "ok") for name in machine.GATES}


def detection(**fields) -> dict:
    row = {"thread_id": THREAD, "turn_id": TURN, "completed_at": NOW - 60, "started_at": NOW - 120,
           # The reset has passed, so the record is due and a claim reaches the rules below
           # instead of stopping at the schedule gate.
           "ordinal": 2, "interruption_id": KEY, "reset_at": NOW - 30,
           "limit_type": "codex:primary", "uncertain": False, "category": "usage_limit"}
    row.update(fields)
    return row


class GuardTestCase(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temporary.name))
        self.store.__enter__()
        # Recovery switched on, or the claim is refused at the consent gate before it reaches
        # any of the rules below.
        self.store.set_enabled(True, NOW - 3600)
        self.store.register(detection(), NOW)

    def tearDown(self):
        self.store.__exit__(None, None, None)
        self.temporary.cleanup()

    def update(self, **changes):
        return self.store.update(KEY, at=NOW, **changes)

    def claimed(self):
        """A record claimed for sending, the only way into `submitting`: the store grants the
        claim, nothing else moves a record there."""
        granted, gate, reason = self.store.reserve_detailed(KEY, NOW, limits=LIMITS, gates=ALL_PASS)
        self.assertTrue(granted, "the record could not be claimed: %s %s" % (gate, reason))
        return self.store.get(KEY)

    def refused(self, saying: str, **changes):
        with self.assertRaises(StoreError) as caught:
            self.update(**changes)
        self.assertIn(saying, str(caught.exception))
        return caught.exception


class UpdateGuardTests(GuardTestCase):
    def test_a_terminal_record_is_not_brought_back(self):
        """A record runs out of attempts; a stale retry then tries to put it back to waiting.

        It would start waiting again with its budget spent, and send a continuation the budget
        exists to prevent.
        """
        self.update(state="retry_budget_exhausted", last_error="recovery_budget")
        self.refused("Cannot reactivate terminal interruption", state="waiting_reset")

    def test_a_send_that_may_have_happened_is_not_rubbed_out(self):
        """A record was claimed and submitted; something tries to clear the submission.

        If `submitted_at` could be cleared, the same continuation could be sent twice - the one
        thing the product must never do.
        """
        self.claimed()
        self.update(state="queued", submitted_at=NOW, queue_id=QUEUE)
        # Clearing it is allowed from `submitting` alone, and only towards the two states that
        # mean the send was disproved. From `queued` the message may be in Codex's own queue.
        self.refused("Cannot clear possible submission", state="handed_over", submitted_at=None)

    def test_a_claimed_record_returns_to_waiting_only_with_its_send_disproved(self):
        """`submitting -> waiting_retry` while the send is still possible.

        The two states differ by whether a message may be sitting in Codex's queue, so this is
        the same rule as above seen from the other side: waiting again means it is known not to
        have been sent.
        """
        self.claimed()
        self.update(submitted_at=NOW, queue_id=QUEUE)
        self.refused("returns to waiting only with its send disproved",
                     state="waiting_retry", submitted_at=NOW)

    def test_a_recovery_turn_is_written_once(self):
        """The turn a recovery started is the thread of evidence for what it did.

        Rewriting it would move every outcome, every progress count and every timeline entry
        onto a turn that produced none of them.
        """
        self.claimed()
        self.update(submitted_at=NOW, queue_id=QUEUE)
        self.update(state="turn_started", recovery_turn_id=TURN, turn_started_at=NOW)
        self.refused("A recovery turn is written once", recovery_turn_id=OTHER_TURN)

    def test_a_cancellation_cannot_be_withdrawn(self):
        """A person asked for it to stop, and nothing in the engine may decide otherwise."""
        self.update(cancel_requested=True)
        self.refused("A cancellation cannot be withdrawn", cancel_requested=False)

    def test_a_field_that_is_not_the_record_s_to_change_is_refused(self):
        self.refused("Invalid record update", thread_id="something else")

    def test_an_empty_update_is_refused(self):
        with self.assertRaises(StoreError):
            self.store.update(KEY, at=NOW)

    def test_an_unknown_record_is_refused(self):
        with self.assertRaises(StoreError) as caught:
            self.store.update("b" * 64, at=NOW, state="cancelled")
        self.assertIn("Unknown interruption", str(caught.exception))


class AllowedMovesTests(GuardTestCase):
    """The other half of a guard: what it must not refuse."""

    def test_a_send_is_disproved_and_the_record_waits_again(self):
        """The one way a submission may be forgotten: it never reached Codex's queue.

        `submitting -> waiting_retry` with no queue id is a send that was begun and is known
        not to have started - so the record may wait again without risking a second one.
        """
        self.claimed()
        self.update(submitted_at=NOW)
        self.update(state="waiting_retry", submitted_at=None)
        self.assertEqual(self.store.get(KEY)["state"], "waiting_retry")

    def test_a_send_that_reached_the_queue_is_not_forgotten_even_from_submitting(self):
        """The same move, with a queue id: Codex has it, so the record cannot go back."""
        self.claimed()
        self.update(submitted_at=NOW, queue_id=QUEUE)
        with self.assertRaises(StoreError):
            self.update(state="waiting_retry", submitted_at=None, queue_id=None)

    def test_a_record_that_was_never_submitted_moves_freely(self):
        self.update(state="waiting_for_usage", last_error="usage_unavailable")
        self.assertEqual(self.store.get(KEY)["state"], "waiting_for_usage")

    def test_a_cancellation_stays_asked_for(self):
        self.update(cancel_requested=True)
        self.assertTrue(self.store.get(KEY)["cancel_requested"])
        self.store.cancel_interruption(KEY, NOW)
        self.assertEqual(self.store.get(KEY)["state"], "cancelled")


class ClaimRefusalOrderTests(GuardTestCase):
    """Which refusal a claim gives when more than one applies.

    The order is not a detail: it is the sentence the window and the panel show a person who
    asks why a recovery is waiting, and the store checks its own six in one fixed sequence
    before it looks at the engine's. Consent first, because a person's "no" outranks every
    other reason; then whether a send is safe; then whether it is due; then the three budgets.
    """

    ORDER = ("consent", "submission_safe", "schedule", "chain_budget", "attempt_budget",
             "no_progress_budget")

    def claim(self, **gates):
        vector = dict(ALL_PASS)
        vector.update(gates)
        return self.store.reserve_detailed(KEY, NOW, limits=LIMITS, gates=vector)

    def test_the_store_checks_its_own_six_in_this_order(self):
        self.assertEqual(self.ORDER, tuple(name for name in self.ORDER if name in machine.GATES),
                         "a name here is not a gate; the store and machine.GATES disagree")

    def test_consent_outranks_everything(self):
        """Paused *and* not due: the person's answer is the one shown."""
        self.store.set_enabled(False, NOW - 60)
        self.store.update(KEY, at=NOW, reset_at=NOW + 3600)
        granted, gate, reason = self.claim()
        self.assertEqual((granted, gate), (False, "consent"))
        self.assertEqual(reason, "paused")

    def test_a_record_that_is_not_due_says_so(self):
        self.store.update(KEY, at=NOW, reset_at=NOW + 3600)
        granted, gate, _reason = self.claim()
        self.assertEqual((granted, gate), (False, "schedule"))

    def test_a_budget_that_is_spent_says_which(self):
        self.store.update(KEY, at=NOW, no_progress_count=LIMITS["max_no_progress"])
        granted, gate, reason = self.claim()
        self.assertEqual((granted, gate), (False, "no_progress_budget"))
        self.assertEqual(reason, "no_progress_budget")

    def test_a_gate_the_engine_evaluated_is_only_reached_after_the_store_s_own(self):
        """The engine's word for Codex - is it there, is the thread loaded - comes after.

        The store re-checks what it owns in the claim itself, because the engine's vector was
        evaluated a moment earlier and the state may have moved since.
        """
        self.store.set_enabled(False, NOW - 60)
        granted, gate, _reason = self.claim(engine_compatible=(machine.BLOCK, "incompatible"))
        self.assertEqual((granted, gate), (False, "consent"), "the store's own come first")

        self.store.set_enabled(True, NOW - 30)
        granted, gate, reason = self.claim(engine_compatible=(machine.BLOCK, "incompatible"))
        self.assertEqual((granted, gate, reason), (False, "engine_compatible", "incompatible"))

    def test_an_unknown_record_is_refused_as_an_identity(self):
        self.assertEqual(self.store.reserve_detailed("b" * 64, NOW, limits=LIMITS, gates=ALL_PASS),
                         (False, "identity", "unknown_record"))

    def test_a_gate_vector_without_its_limits_is_refused(self):
        with self.assertRaises(StoreError):
            self.store.reserve_detailed(KEY, NOW, gates=ALL_PASS)


if __name__ == "__main__":
    unittest.main()
