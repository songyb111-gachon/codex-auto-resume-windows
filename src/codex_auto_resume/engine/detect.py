"""Turning what Codex recorded into records this product owns.

Detection registers a failure once, under an id derived from the failure itself, so the same
interruption seen twice is the same record - and a record whose turn is no longer the thread's
latest is superseded rather than recovered.
"""
from __future__ import annotations

from .. import failures, machine
from ..machine import OBSERVING, TERMINAL, WAITING, WATCHED
from ..source import detect


class DetectMixin:
    def waiting_state(self, row) -> str:
        """The wait a record returns to when it goes back to waiting now."""
        return machine.waiting_state(row, self.clock())

    def valid_interruption(self, row):
        latest = self.source.latest(row["thread_id"])
        found = detect(latest) if latest else None
        return found is not None and found["interruption_id"] == row["interruption_id"]

    def supersede_reason(self, row):
        """Why this interruption is no longer the one to recover.

        A later turn on the exact thread means work continued without us - by the user,
        or by Codex itself - so the old failure must not be resumed on top of it.
        """
        try:
            progress = self.source.progress(row["thread_id"], row["ordinal"])
        except Exception:
            progress = {}
        if progress.get("later_turn"):
            return "superseded_by_user", "later_turn_exists"
        return "superseded", "latest_turn_changed"

    # --------------------------------------------------------------- collect
    def _owner(self, thread_id, turn_id):
        """Which of our records put its continuation into this turn, if any."""
        candidates = [row for row in self.store.claimed_on_thread(thread_id)
                      if row["recovery_turn_id"] is None]
        if not candidates:
            return None
        try:
            present = set(self.source.turn_markers(thread_id, turn_id, [row["marker"] for row in candidates]))
        except Exception:
            return None
        for row in candidates:
            if row["marker"] in present:
                return row["interruption_id"]
        return None

    def _legacy_carry(self, detection):
        """The v0.5 no-progress carry, for a predecessor recorded before chains existed.

        When the previous delivered interruption on this thread produced no completed
        turn and no assistant reply, the count carries forward; visible progress resets
        it. Only lifecycle booleans are consulted - no message text.
        """
        previous = [row for row in self.store.claimed_on_thread(detection["thread_id"])
                    if row["state"] == "resumed" and row["interruption_id"] != detection["interruption_id"]]
        if not previous:
            return None
        last = max(previous, key=lambda row: row["ordinal"])
        try:
            progress = self.source.progress(detection["thread_id"], last["ordinal"])
        except Exception:
            return None                     # unreadable progress is not evidence of failure
        if progress.get("assistant_reply") or progress.get("later_completed"):
            return None                     # something happened; the chain starts over
        return last["no_progress_count"] + 1

    def collect(self):
        settings = self.store.settings()
        if not settings["enabled"]:
            return
        since = max(0.0, settings["armed_at"] - self.options["detection_lookback_seconds"])
        for raw in self.source.latest_failures(since):
            record = detect(raw)
            if record is None or not self.store.thread_enabled(record["thread_id"]):
                continue
            if self.store.get(record["interruption_id"]) is not None:
                continue
            category = record["category"]
            if not self.recovers(category):
                # Logged once per interruption: the user switched this off deliberately,
                # so it is a fact worth being able to find, not a repeating complaint.
                if record["interruption_id"] not in self._declined:
                    if len(self._declined) > 512:
                        self._declined.clear()
                    self._declined.add(record["interruption_id"])
                    self.log(record["thread_id"], "category_recovery_disabled", category)
                continue
            usage = category == failures.USAGE_LIMIT
            # A reset timestamp only exists for a usage limit; a transient failure has
            # nothing to wait for but time, so the two schedules are computed separately.
            hint = (self.source.reset_hint(record["thread_id"], record["turn_id"]) if usage
                    else {"reset_at": None, "limit_type": category, "uncertain": False})
            # store.register accepts only these exact detection fields; detect() also
            # returns status/category which must not be forwarded as-is.
            detection = {
                "thread_id": record["thread_id"], "turn_id": record["turn_id"],
                "completed_at": record["completed_at"], "started_at": record["started_at"],
                "ordinal": record["ordinal"], "interruption_id": record["interruption_id"],
                "reset_at": hint["reset_at"], "limit_type": hint["limit_type"],
                "uncertain": bool(hint["uncertain"]), "category": category,
            }
            now = self.clock()
            reset = detection["reset_at"]
            if usage:
                state = "waiting_reset" if reset else "waiting_poll"
                when = (max(now + 30, reset + self.options["reset_grace_seconds"]) if reset
                        else now + self.options["conservative_poll_seconds"])
            else:
                state = "waiting_backoff"
                when = now + self.first_delay(category)
            owner = self._owner(detection["thread_id"], detection["turn_id"])
            progress = self.source.turn_progress(detection["thread_id"], detection["turn_id"])
            carry = None if owner else self._legacy_carry(detection)
            # One transaction: the record can never exist without its real schedule and
            # the counters of the task it continues.
            if not self.store.register(detection, now, state=state, next_retry_at=when,
                                       owner_id=owner, failed_turn_progress=progress,
                                       legacy_carry=carry, limits=self.limits()):
                continue
            registered = self.store.get(detection["interruption_id"])
            self.log(detection["thread_id"],
                     "usageLimitExceeded_detected" if usage else "transient_failure_detected",
                     detection["interruption_id"] if usage else category)
            if registered["state"] in TERMINAL:
                # Created already stopped: the task it continues was cancelled, taken
                # over, or is out of budget. Said once, and never as "will resume".
                self.log(detection["thread_id"], registered["state"], registered["last_error"])
                self.announce("stopped", registered, state=registered["state"],
                              reason=registered["last_error"])
                continue
            if usage and reset:
                self.log(detection["thread_id"], "reset_expected", str(int(reset)))
            elif usage:
                self.log(detection["thread_id"], "reset_unknown_conservative_poll",
                         str(int(self.options["conservative_poll_seconds"])))
            if detection["uncertain"]:
                self.log(detection["thread_id"], "blocking_limit_uncertain", None)
            # The only moment a control can be offered at the time it matters: the
            # Codex turn has already failed, so nothing can be added to the app's
            # own notice, but the watcher is running right now.
            self.announce("interruption", registered)
