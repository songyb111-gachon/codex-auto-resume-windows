"""Moving a record, and saying so.

One place writes a transition and decides whether it is worth telling somebody about: a
notification is a state a person would want to know they are in, not every step between. The
same place is where a recovery turn is seen to end, so it is where the edition's plug is asked
what follows one (P6).
"""
from __future__ import annotations

from .. import machine
from ..machine import OBSERVING, OUTCOMES, TERMINAL, WAITING, WATCHED


# States worth telling a person about, and which notification setting governs each.
# Only outcomes appear here: the waiting states change constantly and announcing them
# would turn a useful signal into noise nobody reads.
NOTIFY_ON_STATE = {
    "turn_started": "result",
    "failed": "result",
    "submission_unknown": "result",
    "retry_budget_exhausted": "stopped",
    "no_progress_exhausted": "stopped",
    "terminal_failure": "stopped",
}


class AnnounceMixin:
    # ----------------------------------------------------------------- helpers
    def transition(self, row, state, reason=None, delay=None, event=None, **extra):
        values = {"state": state, "last_error": reason, **extra}
        if delay is not None:
            values["next_retry_at"] = self.clock() + delay
        if state in TERMINAL and state != row.get("state") and "outcome_at" not in extra:
            values["outcome_at"] = self.clock()
        self.store.update(row["interruption_id"], at=self.clock(), event=event, **values)
        changed = row.get("state") != state
        if changed or row.get("last_error") != reason:
            self.log(row["thread_id"], state, reason)
        # Announced from the transition itself, so the notification and the recorded
        # state can never disagree, and only on a real change - a record that keeps
        # re-entering the same state says nothing new.
        if changed and state in NOTIFY_ON_STATE:
            self.announce(NOTIFY_ON_STATE[state], row, state=state, reason=reason)
        # P6: a record that was following its recovery turn has an outcome, which is what
        # `observe` (engine/outcome.py) moves it to when that turn ends. Asked only while its
        # consent holds - recovery on, its conversation on, no cancel - and nothing that follows
        # a turn is carried out yet, so nothing is taken from the answer (domain/plug.py).
        # NULL is never asked, so it is looked at first: the consent reads are two transactions
        # on every recovery turn that settles, which the standard edition never made - and one
        # that failed would raise out of a transition whose state is already written.
        if (changed and not self.plug.null and row.get("state") in OBSERVING and state in OUTCOMES
                and self.allowed(row)):
            self.plug.outcome(dict(row, state=state, last_error=reason), state)

    def announce(self, event, row, **detail):
        """Tell the user something happened. Never affects what happens.

        Deduplicated per interruption, event and state: a late delivery after an
        unknown result is still announced, but nothing is announced twice. Any failure
        inside the notifier is swallowed here, because a toast that cannot be drawn must
        never decide whether a task is recovered.
        """
        key = (row.get("interruption_id"), event, detail.get("state"))
        if key in self._announced:
            return
        if len(self._announced) > 4096:
            self._announced.clear()
        self._announced.add(key)
        try:
            self.notify(event, {"thread_id": row.get("thread_id"),
                                "interruption_id": row.get("interruption_id"),
                                "category": row.get("category"),
                                "reset_at": row.get("reset_at"), **detail})
        except Exception:
            self.log(row.get("thread_id"), "notification_failed", event)

    def _wait(self, row, state, reason, delay, vector):
        """Park a record that was due but is not claimable, with the reason recorded."""
        self.store.record_gates(row["interruption_id"], vector, self.clock())
        extra = ({"usage_probe_at": None}
                 if row.get("usage_probe_at") and state != "waiting_for_usage" else {})
        self.transition(row, state, reason, delay=delay, **extra)
