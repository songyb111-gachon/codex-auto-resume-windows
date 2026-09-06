"""General transient recovery: separate policy, bounded budgets, and stopping rules.

Usage-limit recovery has its own policy and its own tests; nothing here may change it.
"""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from codex_auto_resume import failures
from codex_auto_resume.engine import TRANSIENT_BACKOFF, transient_delay
from test_engine import BASE, RESET, T1, T2, TURN_A, TURN_B, Harness


class Base(unittest.TestCase):
    def harness(self, **options):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        harness = Harness(Path(temp.name), options=options or None)
        self.addCleanup(harness.store.close)
        harness.backend.loaded_map[T1] = "loaded"
        harness.backend.loaded_map[T2] = "loaded"
        return harness


class PolicySeparationTests(Base):
    def test_a_transient_failure_waits_on_backoff_not_on_a_reset(self):
        harness = self.harness()
        harness.source.fail_transient(T1)
        harness.enable()
        harness.tick()
        row = harness.record(T1)
        self.assertEqual(row["category"], "server_5xx")
        self.assertEqual(row["state"], "waiting_backoff")
        self.assertIsNone(row["reset_at"])
        self.assertAlmostEqual(row["next_retry_at"], harness.now + TRANSIENT_BACKOFF[0], delta=1)

    def test_a_usage_limit_still_waits_for_its_reset(self):
        harness = self.harness()
        harness.source.fail_usage(T1)
        harness.enable()
        harness.tick()
        row = harness.record(T1)
        self.assertEqual(row["category"], failures.USAGE_LIMIT)
        self.assertEqual(row["state"], "waiting_reset")
        self.assertEqual(row["reset_at"], RESET)

    def test_the_backoff_ladder_is_bounded(self):
        self.assertEqual([transient_delay(n) for n in range(1, 6)], list(TRANSIENT_BACKOFF))
        # Beyond the ladder it stays at the cap instead of growing without limit.
        self.assertEqual(transient_delay(50), TRANSIENT_BACKOFF[-1])
        self.assertEqual(transient_delay(0), TRANSIENT_BACKOFF[0])

    def test_threads_recover_independently(self):
        harness = self.harness()
        harness.source.fail_transient(T1)
        harness.source.fail_usage(T2, turn_id=TURN_B)
        harness.enable()
        harness.tick()
        self.assertEqual(harness.record(T1)["state"], "waiting_backoff")
        self.assertEqual(harness.record(T2)["state"], "waiting_reset")
        self.assertNotEqual(harness.record(T1)["interruption_id"], harness.record(T2)["interruption_id"])


class BudgetTests(Base):
    def exhaust(self, harness, limit):
        """Drive repeated reservations by making every launch fail provably."""
        harness.backend.default_outcome = "not_started"
        for _ in range(limit + 3):
            harness.tick(advance=3600)
            if harness.record(T1)["state"] in ("retry_budget_exhausted", "failed"):
                break
        return harness.record(T1)

    def test_a_transient_chain_stops_at_the_recovery_budget(self):
        harness = self.harness(max_recovery_attempts=2, max_queue_retries=99)
        harness.source.fail_transient(T1)
        harness.enable()
        harness.tick()
        row = self.exhaust(harness, 2)
        self.assertEqual(row["state"], "retry_budget_exhausted")
        self.assertLessEqual(row["recovery_attempts"], 2)

    def test_the_budget_does_not_apply_to_a_usage_limit(self):
        # A usage limit keeps the policy it already had: the daily cap and the
        # per-thread cooldown bound it, not an attempt ladder.
        harness = self.harness(max_recovery_attempts=1, max_queue_retries=3)
        harness.source.fail_usage(T1)
        harness.enable()
        harness.tick()
        row = self.exhaust(harness, 1)
        self.assertNotEqual(row["state"], "retry_budget_exhausted")

    def test_attempts_persist_across_a_restart(self):
        harness = self.harness(max_recovery_attempts=3)
        harness.source.fail_transient(T1)
        harness.enable()
        harness.tick()
        harness.backend.default_outcome = "not_started"
        harness.tick(advance=3600)
        attempts = harness.record(T1)["recovery_attempts"]
        self.assertGreaterEqual(attempts, 1)
        reopened = harness.store.get(harness.record(T1)["interruption_id"])
        self.assertEqual(reopened["recovery_attempts"], attempts)


class NoProgressTests(Base):
    def prepare(self, harness):
        """A first interruption that was recovered, then a second one on the same thread."""
        harness.source.fail_transient(T1, turn_id=TURN_A, ordinal=5)
        harness.enable()
        harness.tick()
        first = harness.record(T1)
        harness.store.update(first["interruption_id"], state="resumed", no_progress_count=0)
        return first

    def second_failure(self, harness, *, completed_turn=False, reply=False):
        if completed_turn:
            harness.source.add_turn(T1, TURN_B, "completed", 6, completed=BASE + 10,
                                    final_agent_item_id="item-1" if reply else None)
        harness.source.fail_transient(T1, turn_id=TURN_B if not completed_turn else TURN_A,
                                      ordinal=7, completed=BASE + 20)
        harness.tick()
        return [row for row in harness.store.all_records() if row["ordinal"] == 7][0]

    def test_no_progress_since_the_last_recovery_increments_the_count(self):
        harness = self.harness()
        self.prepare(harness)
        row = self.second_failure(harness)
        self.assertEqual(row["no_progress_count"], 1)

    def test_visible_progress_resets_the_chain(self):
        harness = self.harness()
        first = self.prepare(harness)
        harness.store.update(first["interruption_id"], no_progress_count=2)
        row = self.second_failure(harness, completed_turn=True, reply=True)
        self.assertEqual(row["no_progress_count"], 0)

    def test_an_exhausted_chain_stops_instead_of_recovering_again(self):
        harness = self.harness(max_no_progress=2)
        first = self.prepare(harness)
        harness.store.update(first["interruption_id"], no_progress_count=1)
        row = self.second_failure(harness)
        self.assertEqual(row["state"], "no_progress_exhausted")
        self.assertEqual(row["no_progress_count"], 2)

    def test_progress_is_decided_without_reading_any_content(self):
        harness = self.harness()
        recorded = []
        original = harness.source.progress
        harness.source.progress = lambda thread_id, after: recorded.append((thread_id, after)) or original(thread_id, after)
        self.prepare(harness)
        self.second_failure(harness)
        self.assertTrue(recorded)
        for _thread, after in recorded:
            self.assertIsInstance(after, int)      # an ordinal, never a message body


class SupersedeTests(Base):
    def test_a_later_turn_by_the_user_stops_the_old_recovery(self):
        harness = self.harness()
        harness.source.fail_transient(T1, ordinal=5)
        harness.enable()
        harness.tick()
        self.assertEqual(harness.record(T1)["state"], "waiting_backoff")
        # The user carries on in that exact thread before the backoff elapses.
        harness.source.add_turn(T1, TURN_B, "completed", 6, completed=BASE + 5,
                                final_agent_item_id="item-1")
        harness.tick(advance=3600)
        self.assertEqual(harness.record(T1)["state"], "superseded_by_user")
        self.assertEqual(harness.backend.send_calls, [])

    def test_a_stale_interruption_is_never_retried_afterwards(self):
        harness = self.harness()
        harness.source.fail_transient(T1, ordinal=5)
        harness.enable()
        harness.tick()
        harness.source.add_turn(T1, TURN_B, "completed", 6, completed=BASE + 5)
        harness.tick(advance=3600)
        state = harness.record(T1)["state"]
        for _ in range(3):
            harness.tick(advance=3600)
        self.assertEqual(harness.record(T1)["state"], state)
        self.assertEqual(harness.backend.send_calls, [])


class UnknownNeverRetriedTests(Base):
    def test_an_unclassified_failure_is_never_registered(self):
        harness = self.harness()
        harness.source.add_turn(T1, TURN_A, "failed", 5, completed=BASE,
                                error_json=json.dumps({"codexErrorInfo": "brandNewVariant"}))
        harness.enable()
        for _ in range(3):
            harness.tick(advance=3600)
        self.assertEqual(harness.store.all_records(), [])
        self.assertEqual(harness.backend.send_calls, [])

    def test_a_terminal_failure_is_never_registered(self):
        harness = self.harness()
        for code in ("unauthorized", "badRequest", "contextWindowExceeded", "cyberPolicy"):
            with self.subTest(code=code):
                harness.source.turns.clear()
                harness.source.add_turn(T1, TURN_A, "failed", 5, completed=BASE,
                                        error_json=json.dumps({"codexErrorInfo": code}))
                harness.enable()
                harness.tick(advance=60)
                self.assertEqual(harness.store.all_records(), [])
        self.assertEqual(harness.backend.send_calls, [])


if __name__ == "__main__":
    unittest.main()
