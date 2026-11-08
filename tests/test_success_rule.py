"""What the success rate counts, and the groups the Statistics chart colours by: one rule (the owner, 2026-11-08).

"복구 성공 기준으로": a recovery, a conversation that moved on before a send (superseded, by Codex or by the person) and a
legacy delivery are successes; a person's own decision - handed over, stopped, cancelled - is left out of the rate; every
other outcome is not succeeded. The rate is the successes over successes and not-succeeded, shown from five outcomes on
(J8), and outcome_groups in the same answer says each bucket's group, so the window colours by the rule the rate is summed
by. The power action's "every recovery succeeded" is a different question and stays the recovered state alone.
"""
from __future__ import annotations

import unittest

from codex_auto_resume import poweraction
from codex_auto_resume.domain.vocabulary import RecordState

from test_store import _StoreCase

SUCCESS = {"recovered", "superseded", "delivered_legacy"}
LEFT_OUT = {"handed_over", "stopped_by_user", "cancelled"}
NOT_SUCCEEDED = {"no_progress", "recovery_failed", "exhausted", "failed_terminal", "outcome_unverified",
                 "submission_unknown"}
# One stored state for each bucket.
STATE_OF = {"recovered": "recovered", "superseded": "superseded", "delivered_legacy": "resumed",
            "handed_over": "handed_over", "stopped_by_user": "stopped_by_user", "cancelled": "cancelled",
            "no_progress": "completed_no_progress", "recovery_failed": "recovery_turn_failed",
            "exhausted": "retry_budget_exhausted", "failed_terminal": "failed",
            "outcome_unverified": "outcome_unverified", "submission_unknown": "submission_unknown"}


class SuccessRuleTests(_StoreCase):
    def test_every_bucket_has_its_group(self):
        groups = self.store.statistics()["outcome_groups"]
        self.assertEqual(set(groups), SUCCESS | LEFT_OUT | NOT_SUCCEEDED)
        self.assertEqual({name for name, group in groups.items() if group == "success"}, SUCCESS)
        self.assertEqual({name for name, group in groups.items() if group == "other"}, LEFT_OUT)
        self.assertEqual({name for name, group in groups.items() if group == "failure"}, NOT_SUCCEEDED)

    def test_the_rate_counts_moved_on_and_legacy_as_success_and_leaves_a_person_s_decision_out(self):
        for bucket in sorted(SUCCESS | LEFT_OUT | NOT_SUCCEEDED):
            self.make(STATE_OF[bucket])
        stats = self.store.statistics()
        self.assertEqual(stats["success_denominator"], len(SUCCESS) + len(NOT_SUCCEEDED))
        self.assertAlmostEqual(stats["success_rate"], len(SUCCESS) / (len(SUCCESS) + len(NOT_SUCCEEDED)))

    def test_the_rate_is_the_groups_own_sum(self):
        for bucket, count in (("recovered", 2), ("superseded", 1), ("delivered_legacy", 1), ("cancelled", 4),
                              ("no_progress", 1), ("submission_unknown", 1)):
            for _ in range(count):
                self.make(STATE_OF[bucket])
        stats = self.store.statistics()
        groups, buckets = stats["outcome_groups"], stats["outcomes"]
        succeeded = sum(n for name, n in buckets.items() if groups[name] == "success")
        counted = sum(n for name, n in buckets.items() if groups[name] != "other")
        self.assertEqual((succeeded, counted), (4, 6))
        self.assertEqual(stats["success_denominator"], counted)
        self.assertAlmostEqual(stats["success_rate"], succeeded / counted)

    def test_no_rate_below_five_counted_outcomes(self):
        """J8, unchanged: four counted (and any number left out) show no rate."""
        for state in ("recovered", "superseded", "resumed", "completed_no_progress", "cancelled", "handed_over"):
            self.make(state)
        self.assertIsNone(self.store.statistics()["success_rate"])
        self.make("superseded_by_user")
        self.assertAlmostEqual(self.store.statistics()["success_rate"], 4 / 5)

    def test_the_power_action_s_success_stays_the_recovered_state_alone(self):
        self.assertEqual(poweraction.SUCCESS_STATES, frozenset({RecordState.RECOVERED}))


if __name__ == "__main__":
    unittest.main()
