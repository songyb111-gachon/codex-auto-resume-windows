"""Counts and the last seven days, for the Overview and the Statistics page."""
from __future__ import annotations

import math
import statistics as _statistics
from ..machine import STATES, TERMINAL


class ReportingMixin:
    # ------------------------------------------------------------- reporting
    def status_counts(self) -> dict[str, int]:
        with self._read() as connection:
            return {row[0]: row[1] for row in connection.execute(
                "SELECT state, count(*) FROM interruptions GROUP BY state") if row[0] in STATES}

    def statistics(self, since: float = 0.0, until: float | None = None) -> dict:
        """Exact, content-free counts over records detected in a period.

        One final outcome per record, so a late receipt moves a record from "unknown"
        to what really happened instead of counting twice. Hidden records are included:
        clearing history changes what is shown, not what happened.
        """
        until = float("inf") if until is None else until
        rows = [row for row in self.all_records() if since <= row["detected_at"] < until]
        outcome = {
            "recovered": "recovered", "completed_no_progress": "no_progress",
            "recovery_turn_failed": "recovery_failed", "outcome_unverified": "outcome_unverified",
            "handed_over": "handed_over", "stopped_by_user": "stopped_by_user",
            "cancelled": "cancelled", "superseded": "superseded", "superseded_by_user": "superseded",
            "retry_budget_exhausted": "exhausted", "no_progress_exhausted": "exhausted",
            "failed": "failed_terminal", "terminal_failure": "failed_terminal",
            "submission_unknown": "submission_unknown", "resumed": "delivered_legacy",
        }
        buckets = {name: 0 for name in sorted(set(outcome.values()))}
        by_category: dict[str, int] = {}
        for row in rows:
            bucket = outcome.get(row["state"])
            if bucket is not None:
                buckets[bucket] += 1
            by_category[row["category"]] = by_category.get(row["category"], 0) + 1
        denominator = sum(buckets[name] for name in (
            "recovered", "no_progress", "recovery_failed", "outcome_unverified", "exhausted",
            "failed_terminal", "submission_unknown"))
        waits = [row["first_queued_at"] - row["detected_at"] for row in rows
                 if row["first_queued_at"] is not None and row["first_queued_at"] >= row["detected_at"]]
        latencies = [row["outcome_at"] - row["first_queued_at"] for row in rows
                     if row["state"] == "recovered" and row["outcome_at"] is not None
                     and row["first_queued_at"] is not None and row["outcome_at"] >= row["first_queued_at"]]
        return {
            "interruptions_detected": len(rows),
            "continuations_submitted": sum(1 for row in rows if row["first_queued_at"] is not None),
            "pending": sum(1 for row in rows if row["state"] not in TERMINAL),
            "outcomes": buckets,
            "success_rate": (buckets["recovered"] / denominator) if denominator >= 5 else None,
            "success_denominator": denominator,
            "median_wait_seconds": _statistics.median(waits) if waits else None,
            "median_recovery_seconds": _statistics.median(latencies) if latencies else None,
            "by_category": by_category,
            "retry_now_requests": sum(row["retry_now_count"] for row in rows),
        }
