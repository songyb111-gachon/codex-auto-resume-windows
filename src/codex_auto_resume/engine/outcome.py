"""Reading how a recovered turn ended, and what that costs the budgets.

Progress is the measure: a turn that ran and produced nothing is not a success, and a usage
limit met again is a wait rather than a failure.
"""
from __future__ import annotations

from .. import failures, machine
from ..machine import OBSERVING, TERMINAL, WAITING, WATCHED


class OutcomeMixin:
    # ----------------------------------------------------------- the outcome
    def observe(self, row):
        """Follow our own recovery turn to its end, reading that turn only."""
        now = self.clock()
        try:
            seen = self.source.turn_observation(row["thread_id"], row["recovery_turn_id"], row["marker"])
        except Exception:
            seen = None
        deadline = (row["turn_started_at"] or now) + self.options["unknown_reconcile_window_seconds"]
        if not seen or not seen.get("found"):
            # Unreadable is unknown, never "no progress". It is retried until the deadline.
            if now >= deadline:
                self.transition(row, "outcome_unverified", "outcome_deadline")
            return
        status = seen["status"]
        if seen["foreign_user_messages"] > 0:
            self.transition(row, "handed_over", "user_joined", user_joined=True,
                            recovery_turn_status=status)
        elif status == "other":
            self.transition(row, "outcome_unverified", "unknown_turn_status", recovery_turn_status="other")
        elif status == "inProgress":
            if seen["later_terminal"]:
                # The row can never finish: Codex only updates a turn row while it is
                # the one in progress, so a later finished turn means this one is stale.
                self.transition(row, "outcome_unverified", "stale_turn_row")
            elif now >= deadline:
                self.transition(row, "outcome_unverified", "outcome_deadline")
            elif row["recovery_turn_status"] != "inProgress":
                self.store.update(row["interruption_id"], at=now, recovery_turn_status="inProgress")
        elif row["state"] == "turn_started":
            self.transition(row, "turn_completed", None, recovery_turn_status=status)
        else:
            completed = seen["completed_at"] or row["turn_started_at"] or now
            if now < completed + self.options["settle_seconds"]:
                return
            if status == "completed":
                if seen["progress"]:
                    self.transition(row, "recovered", "progress_observed", recovery_turn_status=status)
                else:
                    self.transition(row, "completed_no_progress", "no_progress_observed",
                                    recovery_turn_status=status)
            elif status == "failed":
                # A recovery turn that ran and then failed is not a failed recovery. The
                # commonest way for one to end is the next usage limit: the continuation
                # was delivered, the task moved, and Codex records the turn the limit
                # interrupted as failed. Reading that status alone called three real
                # recoveries in a row a failure, which is what the first live acceptance
                # found. So ask the question the completed branch asks - did this turn do
                # anything? - and keep the raw status on the row for whoever looks.
                # The failure itself is registered by detection, as this record's child.
                if seen["progress"]:
                    self.transition(row, "recovered", "progress_then_turn_failed",
                                    recovery_turn_status=status)
                else:
                    self.transition(row, "recovery_turn_failed", "turn_failed",
                                    recovery_turn_status=status)
            elif status == "interrupted":
                self.transition(row, "stopped_by_user", "turn_interrupted", recovery_turn_status=status)

    def observe_all(self):
        for row in self.store.records_in(OBSERVING):
            try:
                self.observe(row)
            except Exception:
                self.log(row["thread_id"], "outcome_check_unavailable", None)

    # --------------------------------------------------------------- attempt
    def _stop_for_budget(self, row, gate, reason):
        state = "no_progress_exhausted" if gate == "no_progress_budget" else "retry_budget_exhausted"
        self.transition(row, state, reason)

    def _usage_wait(self, row, limits, now):
        """Wait for usage, and give up on a limit that is never going to lift.

        Only time between two probes that both said "unavailable, no reset known" is
        counted, capped per interval, so time the app was closed, the watcher was not
        running or the probe itself failed never counts.
        """
        available = limits.get("available")
        probe_reset = limits.get("reset_at")
        reset = max([value for value in (row.get("reset_at"), probe_reset) if value], default=None)
        extra = {}
        if available is False and reset is None:
            gap = 0.0
            if row.get("usage_probe_at"):
                gap = min(max(0.0, now - row["usage_probe_at"]),
                          1.5 * self.options["conservative_poll_seconds"])
            total = row["usage_unavailable_seconds"] + gap
            if total >= self.options["usage_never_available_seconds"]:
                self.transition(row, "terminal_failure", "usage_never_available",
                                usage_unavailable_seconds=total, usage_probe_at=None)
                return
            extra = {"usage_unavailable_seconds": total, "usage_probe_at": now}
        else:
            extra = {"usage_probe_at": None} if row.get("usage_probe_at") else {}
            if (available is False and reset is not None
                    and now >= reset + self.options["usage_after_reset_seconds"]):
                self.transition(row, "terminal_failure", "usage_not_restored_after_reset", **extra)
                return
        wait = (max(60, probe_reset + self.options["reset_grace_seconds"] - now) if probe_reset
                else self.options["conservative_poll_seconds"])
        self.transition(row, "waiting_for_usage",
                        "usage_unavailable" if available is False else "usage_unknown",
                        delay=wait, **extra)
