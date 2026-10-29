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
            seen = self.source.turn_observation(row["thread_id"], row["recovery_turn_id"], self.proof(row))
        except Exception:
            seen = None
        deadline = (row["turn_started_at"] or now) + self.options["unknown_reconcile_window_seconds"]
        if not seen or not seen.get("found"):
            # Unreadable is unknown, never "no progress". It is retried until the deadline.
            if now >= deadline:
                self.transition(row, "outcome_unverified", "outcome_deadline")
            return
        status = seen["status"]
        if seen["foreign_user_messages"] > 0 and seen.get("progress_before_foreign") is True:
            # Our continuation worked, then a person's message entered the turn - one they had queued in the Codex
            # app, or an answer to a question Codex asked them (2026-10-22, the owner's 04:24 and 16:38): a recovery,
            # through turn_completed as every outcome goes, decided while the turn may still run. Not handed over, so
            # the turn's own next failure - a usage limit, which stops the person too - is a chain child that is
            # recovered (gates.birth_stop), not one born superseded that nobody resumes.
            if row["state"] == "turn_started":
                self.transition(row, "turn_completed", None, recovery_turn_status=status)
            else:
                self.transition(row, "recovered", "progress_then_user_joined", recovery_turn_status=status)
        elif seen["foreign_user_messages"] > 0:
            # A person joined before the turn did anything: theirs, handed over at once.
            self.transition(row, "handed_over", "user_joined", user_joined=True,
                            recovery_turn_status=status)
        elif status == "other":
            self.transition(row, "outcome_unverified", "unknown_turn_status", recovery_turn_status="other")
        elif status == "inProgress":
            if self._cut_off(row, seen):
                # The row can never finish: Codex only updates a turn row while it is the
                # one in progress, and Codex closing, or the PC going off, mid-turn leaves
                # it saying inProgress forever. Judged as a failed turn is: one that did
                # work was a recovery (`progress_then_turn_cut_off`, through turn_completed
                # as every outcome goes); one that did nothing is unverified, as it was.
                # Nothing is registered as a failure: there is no failed turn to register.
                if not seen["progress"]:
                    self.transition(row, "outcome_unverified", "stale_turn_row")
                elif row["state"] == "turn_started":
                    self.transition(row, "turn_completed", None, recovery_turn_status=status)
                else:
                    self.transition(row, "recovered", "progress_then_turn_cut_off",
                                    recovery_turn_status=status)
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

    # A Windows start this many seconds after the turn was seen starting ended it.
    CUT_OFF_BOOT_MARGIN = 5.0

    def _cut_off(self, row, seen) -> bool:
        """Whether a recovery turn whose row still says inProgress can no longer finish: a later
        turn of its conversation has started (any status - Codex runs one turn at a time), or
        Windows started after it began (the boot time the watcher's heartbeat records)."""
        if seen.get("later_started", seen.get("later_terminal")):
            return True
        started = row.get("turn_started_at")
        if not started:
            return False
        try:
            status = self.store.watcher_status() or {}
        except Exception:
            return False
        booted = status.get("booted_at")
        return machine.epoch(booted, *machine.EPOCH_STORE) and booted > started + self.CUT_OFF_BOOT_MARGIN

    def observe_all(self):
        for row in self._records(OBSERVING):
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
