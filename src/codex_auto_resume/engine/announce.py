"""Moving a record, and saying so.

One place writes a transition and decides whether it is worth telling somebody about: a
notification is a state a person would want to know they are in, not every step between. The
same place is where a recovery turn is seen to end, so it is where the edition's plug is asked
what follows one (P6), and where it is told of every move the engine writes (P14).

The waits a dispatch ends in are here too: a claim the store refused, a record parked in quiet
hours, and (v0.6.11) the objection window's minutes and the card that says so.
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
        self.moved(row, state)
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

    def moved(self, row, state):
        """P14: tell the plug that `row`, as core held it, has just moved to `state`.

        Called once the move is written, wherever the engine writes one: here for every
        `transition`, and beside each store call that moves a record itself - the claim, giving
        a claim back, a withdrawal, a correlation (tests/test_plug_points.py finds them all).
        Only a real move is told, and told whether or not recovery is paused: this decides
        nothing, and a plug that heard of a move only while consent held would not know what
        core did. NULL is never told, as P6 never asks it, so the standard edition makes no
        call and copies no record it did not."""
        if not self.plug.null and row.get("state") != state:
            self.plug.moved(row, state)

    def _release(self, key, claim, target, reason, delay):
        """Give back the claim on record `key` whose send never started, and tell the plug."""
        if self.store.release_claim(key, target, reason, self.clock(),
                                    next_retry_at=self.clock() + delay):
            self.moved(claim, target)

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

    def _objection(self, row, vector, now) -> bool:
        """The objection-window tier (v0.6.11): before a record is first sent, its minutes for a
        person to stop it. True if the record waits instead of being sent now.

        Asked once every gate has passed - when it would otherwise be sent now - so the minutes
        are the last before a send, not minutes spent waiting for a reset or for the conversation
        to be opened. Opened once per record (`objection_at`): one whose window has passed goes
        when every gate passes again, and one a person postponed before it opened has it once the
        postponement is over - a postponement only ever holds a record back, and never makes one
        go sooner than it would have. One made while it is open is later than its end, and goes at
        the time chosen. The card it raises offers what an interruption's card offers: Don't
        resume, and the Dashboard. No tier asks this at the defaults, where every conversation is
        resumed automatically."""
        if row.get("objection_at") is not None or self.tier(row["thread_id"]) != "objection_window":
            return False
        until = now + 60 * self.policy_values["objection_minutes"]
        if self.store.open_objection_window(row["interruption_id"], until, now):
            vector["schedule"] = machine.gate(machine.WAIT, machine.POSTPONED)
            self._wait(row, row["state"], row.get("last_error"), until - now, vector)
            self.announce("objection", dict(row, not_before=until), until=until)
        # A window that could not be opened - the record moved, or a person postponed it in the
        # meantime - sends nothing on this tick either; the next one looks again from the top.
        return True

    def _refused(self, row, gate, reason):
        """A claim the store refused. Recorded as a wait or a stop, never silently."""
        if self._early_look == row["interruption_id"] and gate not in (
                "chain_budget", "attempt_budget", "no_progress_budget"):
            return                     # looked at early: the claim kept its vector, nothing else moves
        if reason == "capacity_window":
            # Past a capacity error's twelve hours (v0.6.13): no stop of its own - at its next look
            # the plug's CAPACITY is not taken, and the standard edition's budgets decide.
            self.transition(row, row["state"], row.get("last_error"),
                            delay=self.options["state_poll_seconds"])
        elif gate in ("chain_budget", "attempt_budget", "no_progress_budget"):
            self._stop_for_budget(row, gate, reason)
        elif gate == "schedule" and reason == "waiting_reset" and row.get("reset_at"):
            self.transition(row, "waiting_reset", "waiting_reset",
                            delay=max(30, row["reset_at"] + self.options["reset_grace_seconds"] - self.clock()))
        elif gate == "submission_safe" and reason == "other_recovery_in_flight":
            self.transition(row, "waiting_retry", "other_recovery_in_flight",
                            delay=self.options["state_poll_seconds"])
        elif gate == "submission_safe" and reason == machine.HELD:
            # The plug's ledger held the claim (P11): the record keeps its state and its reason
            # for one more poll, as a gate the plug holds does.
            self.transition(row, row["state"], row.get("last_error"),
                            delay=self.options["state_poll_seconds"])

    def _quiet(self, row, vector, delay):
        """A record that fell due in quiet hours (v0.6.11), parked until they end, keeping its state
        and its reason. The time counts toward nothing: a usage limit's seven days count only the
        time between two reads that both found no usage (engine/outcome.py), and forgetting the
        last read here makes the first one after the quiet hours start that count again."""
        if not self._parked(row, vector):
            self.store.record_gates(row["interruption_id"], vector, self.clock())
            self.transition(row, row["state"], row.get("last_error"), delay=delay, usage_probe_at=None)

    def _would_send(self, row, vector, now):
        """Observe only (v0.6.11): every gate but consent passed, so this record would have been sent
        now. Nothing is claimed and nothing is sent: it is parked at the conservative poll with the
        vector that says so, and journaled (would_send) the first time it comes to this each time it
        comes due, never on every poll it spends here."""
        if self.store.record_would_send(row["interruption_id"], vector, now,
                                        now + self.options["conservative_poll_seconds"]):
            self.log(row["thread_id"], "would_send", None)

    def _wait(self, row, state, reason, delay, vector):
        """Park a record that was due but is not claimable, with the reason recorded."""
        if self._parked(row, vector):
            return
        self.store.record_gates(row["interruption_id"], vector, self.clock())
        extra = ({"usage_probe_at": None}
                 if row.get("usage_probe_at") and state != "waiting_for_usage" else {})
        self.transition(row, state, reason, delay=delay, **extra)
