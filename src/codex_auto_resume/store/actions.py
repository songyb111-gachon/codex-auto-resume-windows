"""What a person asks for: stop this, stop the conversation, try now, give the attempts back.

Each of these is a write the engine must respect rather than decide on: a cancellation cannot
be withdrawn, and a retry asked for by hand is not an extra attempt.
"""
from __future__ import annotations

from .. import machine, quiet
from ..machine import EXHAUSTED, IN_FLIGHT, OBSERVING, TERMINAL, WAITING
from .validate import _timestamp, _uuid, _validated_record


MAX_BUDGET_RESETS = 3

# How long an unresolved `submission_unknown` is still being reconciled. Clear history
# keeps such a row visible until then, because it may still change.
UNKNOWN_WINDOW = 24 * 3600


class ActionsMixin:
    # ------------------------------------------------------------ user actions
    def cancel_interruption(self, interruption_id: str, now: float, *, actor: str = "gui") -> dict | None:
        """Stop one recovery, and everything that continues it.

        Applies to the record's whole chain. A record that has not been sent is
        cancelled outright. Anything that may already be in Codex is only marked: the
        watch takes back whatever is still queued, and a turn that is already running is
        followed to its end. A finished record is marked too, so no later failure of
        that task can start a new chain from it.
        """
        _timestamp(now, "now")
        with self._transaction() as connection:
            row = self._row(connection, interruption_id)
            if row is None:
                return None
            chain = [_validated_record(dict(value)) for value in connection.execute(
                "SELECT * FROM interruptions WHERE chain_origin_id=? ORDER BY detected_at",
                (row["chain_origin_id"],))]
            effects, changed = {}, False
            for member in chain:
                key = member["interruption_id"]
                if member["state"] in WAITING and member["submitted_at"] is None:
                    connection.execute(
                        "UPDATE interruptions SET state='cancelled', cancel_requested=1, "
                        "last_error='user_cancelled', next_retry_at=? WHERE interruption_id=?",
                        (now, key))
                    self._event(connection, now, "cancel", record=member, from_state=member["state"],
                                to_state="cancelled", reason="user_cancelled", actor=actor)
                    effects[key], changed = "cancelled", True
                elif member["cancel_requested"]:
                    effects[key] = "unchanged"
                else:
                    connection.execute(
                        "UPDATE interruptions SET cancel_requested=1 WHERE interruption_id=?", (key,))
                    self._event(connection, now, "cancel_requested", record=member,
                                from_state=member["state"], to_state=member["state"], actor=actor)
                    # An uncertain submission may still be sitting in Codex's queue,
                    # and the watch takes it back on this mark: that is a real stop.
                    if member["state"] in TERMINAL and member["state"] != "submission_unknown":
                        effects[key] = "blocked_future"
                    else:
                        effects[key], changed = "cancel_requested", True
            return {"changed": changed, "effects": effects}

    def cancel_thread(self, thread_id: str, now: float, *, actor: str = "gui") -> None:
        """Turn automatic recovery off for one conversation, and stop what it has."""
        _uuid(thread_id, "thread_id")
        _timestamp(now, "now")
        with self._transaction() as connection:
            connection.execute(
                "INSERT INTO threads (thread_id, enabled) VALUES (?,0) "
                "ON CONFLICT(thread_id) DO UPDATE SET enabled=0", (thread_id,)
            )
            for value in connection.execute("SELECT * FROM interruptions WHERE thread_id=?", (thread_id,)).fetchall():
                row = _validated_record(dict(value))
                if row["state"] in TERMINAL:
                    continue
                if row["submitted_at"] is not None:
                    if not row["cancel_requested"]:
                        connection.execute(
                            "UPDATE interruptions SET cancel_requested=1 WHERE interruption_id=?",
                            (row["interruption_id"],))
                        self._event(connection, now, "cancel_requested", record=row,
                                    from_state=row["state"], to_state=row["state"], actor=actor)
                else:
                    connection.execute(
                        "UPDATE interruptions SET state='cancelled', cancel_requested=1, "
                        "last_error='user_cancelled', next_retry_at=? WHERE interruption_id=?",
                        (now, row["interruption_id"]))
                    self._event(connection, now, "cancel", record=row, from_state=row["state"],
                                to_state="cancelled", reason="user_cancelled", actor=actor)

    def restore_budget(self, interruption_id: str, now: float, **options) -> bool:
        return self.restore_budget_detailed(interruption_id, now, **options)[0]

    def restore_budget_detailed(self, interruption_id: str, now: float, *, actor: str = "gui",
                                max_resets: int = MAX_BUDGET_RESETS) -> tuple:
        """Give an exhausted interruption its budget back. Returns (restored, detail).

        `update` refuses to reactivate a terminal record, and that guard is what stops a
        finished, cancelled or uncertainly-submitted recovery from being restarted by a
        stray write. Running out of attempts is the one stop a person is allowed to undo,
        so it gets its own operation rather than a hole in the guard: the two exhausted
        states are the only ones accepted here, and a record that was cancelled or may
        already have been sent is refused even from those.

        It clears the budget and nothing else. It does not switch a conversation back
        on, it does not send, and the record returns to the wait its kind of failure
        needs, so every gate the watcher applies still applies. It can be done a few
        times per task, never without limit.
        """
        _timestamp(now, "now")
        with self._transaction() as connection:
            row = self._row(connection, interruption_id)
            if row is None:
                return False, "unknown_record"
            if row["state"] not in EXHAUSTED:
                return False, "not_exhausted"
            if row["cancel_requested"]:
                return False, "cancel_requested"
            if row["submitted_at"] is not None or row["queue_id"] is not None:
                return False, "possibly_sent"
            if row["budget_resets"] >= max_resets:
                return False, "reset_limit"
            target = machine.waiting_state(row, now)
            # Its time as well (v0.6.11): a task's time ceiling is measured from the first failure
            # of its chain, which is this one from now on. Nothing reads it while there is none.
            connection.execute(
                "UPDATE interruptions SET state=?, recovery_attempts=0, no_progress_count=0, "
                "retry_count=0, chain_continuations=0, budget_resets=budget_resets+1, "
                "chain_first_detected_at=detected_at, "
                "last_error='budget_restored', next_retry_at=? WHERE interruption_id=?",
                (target, now, interruption_id))
            self._event(connection, now, "reset_budget", record=row, from_state=row["state"],
                        to_state=target, reason="budget_restored", actor=actor)
            return True, target

    def request_retry_now(self, interruption_id: str, now: float, *, actor: str = "gui") -> tuple:
        """Bring a waiting record's next check forward to now. Returns (accepted, detail).

        A schedule change and nothing else: it never touches a stored usage reset or
        any gate, and it never sends. On refusal `detail` names why; on acceptance it is
        the earliest time the watcher can actually act, which is later than now when a
        usage reset is still ahead - or, from v0.6.11, a postponement or an objection
        window, which it never shortens: each only ever holds a record back, and ending
        one early would be a check skipped (A25) by a request not marked as one (H8).
        """
        _timestamp(now, "now")
        with self._transaction() as connection:
            row = self._row(connection, interruption_id)
            if row is None:
                return False, "unknown_record"
            if row["cancel_requested"]:
                return False, "cancel_requested"
            state = row["state"]
            if state not in WAITING:
                return False, ("finished" if state in TERMINAL else "observing" if state in OBSERVING
                               else "in_flight" if state in IN_FLIGHT else "claimed")
            connection.execute(
                "UPDATE interruptions SET next_retry_at=?, retry_now_count=retry_now_count+1 "
                "WHERE interruption_id=?", (now, interruption_id))
            self._event(connection, now, "retry_now", record=row, from_state=state, to_state=state,
                        reason="retry_now", actor=actor)
            return True, max(now, row["reset_at"] or 0, row["not_before"] or 0)

    @staticmethod
    def _not_waiting(row) -> str:
        """Why a record that is not waiting cannot be made to wait longer, in the retry's words."""
        state = row["state"]
        return ("finished" if state in TERMINAL else "observing" if state in OBSERVING
                else "in_flight" if state in IN_FLIGHT else "claimed")

    def _bound(self, connection, interruption_id: str, thread_id: str):
        """The record a row's action names, and why it cannot be acted on - (row, None) or
        (row or None, detail). Bound to both identities, as a person's switch is: a record that
        is gone, or belongs to another conversation, is refused and nothing changes."""
        row = self._row(connection, interruption_id)
        if row is None:
            return None, "unknown_record"
        if row["thread_id"] != thread_id:
            return row, "thread_mismatch"
        if row["state"] in TERMINAL:
            return row, "finished"
        if row["cancel_requested"]:
            return row, "cancel_requested"
        return row, None

    def postpone(self, interruption_id: str, thread_id: str, until, now: float, *,
                 actor: str = "gui") -> tuple:
        """Wait until `until` at the earliest (schema 4). Returns (accepted, detail).

        A person's, for one exact record, and only ever later: a time that is not later than now
        and than the postponement the record already has, or more than a week ahead, is refused
        (quiet.postponement_problem). Only a record still waiting can wait longer. It writes the
        time and nothing else - no gate is skipped, nothing is sent, the schedule it had still
        holds (domain/gates.py, gate_schedule) - and on acceptance `detail` is the time."""
        _uuid(thread_id, "thread_id")
        _timestamp(now, "now")
        with self._transaction() as connection:
            row, problem = self._bound(connection, interruption_id, thread_id)
            if problem is not None:
                return False, problem
            if row["state"] not in WAITING:
                return False, self._not_waiting(row)
            problem = quiet.postponement_problem(until, now, row["not_before"])
            if problem is not None:
                return False, problem
            connection.execute("UPDATE interruptions SET not_before=? WHERE interruption_id=?",
                               (float(until), interruption_id))
            self._event(connection, now, "postponed", record=row, from_state=row["state"],
                        to_state=row["state"], actor=actor, value=float(until))
            return True, float(until)

    def open_objection_window(self, interruption_id: str, until: float, now: float) -> bool:
        """The engine's: an objection-window tier's minutes before a record's first send.

        Opened once (`objection_at`), and only while the record waits unsent - also after a
        postponement a person made before it, which only ever held the record back and never took
        the window's place. It is written as a postponement to `until`, or kept at a later one a
        person chose in the meantime, so every check that asks about a postponement asks about it
        too. False when it was not opened."""
        _timestamp(now, "now")
        _timestamp(until, "until")
        with self._transaction() as connection:
            row = self._row(connection, interruption_id)
            if (row is None or row["state"] not in WAITING or row["objection_at"] is not None
                    or row["submitted_at"] is not None or until <= now):
                return False
            until = max(until, row["not_before"] or 0)
            connection.execute("UPDATE interruptions SET not_before=?, objection_at=? "
                               "WHERE interruption_id=?", (until, now, interruption_id))
            self._event(connection, now, "postponed", record=row, from_state=row["state"],
                        to_state=row["state"], value=until)
            return True

    def release_hold(self, interruption_id: str, thread_id: str, now: float, *,
                     actor: str = "gui") -> tuple:
        """Let one held record continue (schema 4). Returns (released, detail).

        Bound to both identities, as a person's switch is. It takes the hold away and nothing
        else: every gate still runs, nothing is sent now, and a postponement or quiet hours still
        hold. A record that is not held, finished, cancelled or another conversation's is refused
        and nothing changes. On acceptance `detail` is the record's state."""
        _uuid(thread_id, "thread_id")
        _timestamp(now, "now")
        with self._transaction() as connection:
            row, problem = self._bound(connection, interruption_id, thread_id)
            if problem is not None:
                return False, problem
            if row["hold"] is None:
                return False, "not_held"
            connection.execute("UPDATE interruptions SET hold=NULL WHERE interruption_id=?",
                               (interruption_id,))
            self._event(connection, now, "hold_released", record=row, from_state=row["state"],
                        to_state=row["state"], actor=actor)
            return True, row["state"]

    def hide_history(self, now: float, *, actor: str = "gui") -> dict:
        """Clear recovery history from view. Display only; never deletes a row.

        Hidden rows still count for every safety decision - the caps, the cooldown, the
        chain and duplicate detection - because the rows are the tombstones that stop a
        finished failure from being detected again. Anything that may still change is
        left visible: a record still running, and an unconfirmed submission that is
        still being reconciled.
        """
        _timestamp(now, "now")
        with self._transaction() as connection:
            hidden = kept = 0
            for value in connection.execute(
                    "SELECT * FROM interruptions WHERE history_hidden_at IS NULL").fetchall():
                row = _validated_record(dict(value))
                if row["state"] not in TERMINAL:
                    kept += 1
                    continue
                if row["state"] == "submission_unknown" and (
                        row["queue_id"] is not None
                        or now - (row["submitted_at"] or row["detected_at"]) < UNKNOWN_WINDOW):
                    kept += 1
                    continue
                connection.execute("UPDATE interruptions SET history_hidden_at=? WHERE interruption_id=?",
                                   (now, row["interruption_id"]))
                hidden += 1
            if hidden:
                self._event(connection, now, "hidden", actor=actor, value=hidden)
            return {"hidden": hidden, "kept": kept}
