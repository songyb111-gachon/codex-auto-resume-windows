"""Records: registering one, reading them back, and the rules a change must obey.

`update` is where a record may be refused - a terminal record brought back, a send that may
have happened rubbed out, a recovery turn rewritten, a cancellation withdrawn. Each of those
is one line here and one test in `tests/test_store_guards.py`.
"""
from __future__ import annotations

import sqlite3
from typing import Any
from .. import failures, machine
from ..domain import ids
from ..machine import STATES, TERMINAL, WAITING
from .columns import _MUTABLE, _NEEDS_RECOVERY_TURN, _RECORD_COLUMNS
from .errors import StoreError
from .validate import _finite, _sql, _timestamp, _uuid, _validated_record, is_usage


class RecordsMixin:
    # ---------------------------------------------------------------- records
    def register(self, record: dict[str, Any], now: float, *,
                 state: str = "waiting_reset", next_retry_at: float | None = None,
                 owner_id: str | None = None, failed_turn_progress: bool | None = None,
                 legacy_carry: int | None = None, limits: dict | None = None,
                 hold: str | None = None, task_print: str | None = None,
                 context_tokens: int | None = None) -> bool:
        """Create the record WITH its real schedule and its chain, in one transaction.

        Writing the schedule, or the counters inherited from the record whose own
        continuation just failed, in a second transaction would leave a mis-scheduled or
        under-counted record behind if the process died between the two commits.

        A failure of a turn our own continuation started is the same task failing
        again, so the new record continues its parent's chain: it inherits every
        counter, and it is created already stopped when the parent was cancelled, was
        taken over by a person, or has used up a budget. None of that waits for the
        parent's own outcome to be evaluated first.

        Returns False, without raising, when this failure is already known - including
        the same turn seen under a different identity, which is journaled instead.

        `hold` (schema 4) is the hold its conversation's tier puts on it (machine.hold_for_tier):
        None at the defaults, where every conversation is resumed automatically. `task_print` and
        `context_tokens` are what the two guards keep of it (guards.py): None while they are off.
        """
        _timestamp(now, "now")
        required = {"thread_id", "turn_id", "completed_at", "started_at", "ordinal",
                    "interruption_id", "reset_at", "limit_type", "uncertain"}
        if not isinstance(record, dict) or not required <= set(record) <= required | {"category"}:
            raise StoreError("Invalid detection record")
        # Schema 1 could only ever record a usage limit, so that is the safe default
        # for a caller that predates categories.
        record = {"category": failures.USAGE_LIMIT, **record}
        if state not in WAITING:
            raise StoreError("A new interruption must start in a waiting state")
        key = record["interruption_id"]
        row = {
            **record, "detected_at": now, "state": state, "retry_count": 0,
            "next_retry_at": now if next_retry_at is None else next_retry_at,
            "resumed_at": None, "last_error": None,
            "marker": ids.short_marker(key), "queue_id": None,
            "submitted_at": None, "attempt_count": 0, "cancel_requested": False,
            "recovery_attempts": 0, "no_progress_count": 0,
            "recovery_turn_id": None, "recovery_client_id": None, "recovery_turn_status": None,
            "user_joined": False, "after_user_work": False, "legacy": False,
            "withdraw_reason": None, "withdrawn_at": None, "withdraw_deleted": False,
            "withdraw_failures": 0, "turn_started_at": None, "outcome_at": None,
            "first_queued_at": None, "last_claim_at": None, "parent_interruption_id": None,
            "chain_origin_id": key, "chain_first_detected_at": now, "chain_continuations": 0,
            "budget_resets": 0, "retry_now_count": 0, "usage_unavailable_seconds": 0.0,
            "usage_probe_at": None, "gate_eval": None, "gate_eval_at": None,
            "history_hidden_at": None, "not_before": None, "hold": hold,
            "task_print": task_print, "context_tokens": context_tokens, "objection_at": None,
            "objection_until": None,
        }
        _validated_record(dict(row))
        with self._transaction() as connection:
            existing = self._row(connection, key)
            if existing is not None:
                if any(existing[field] != row[field] for field in
                       ("thread_id", "turn_id", "completed_at", "started_at", "ordinal")):
                    raise StoreError("Interruption identity collision")
                return False
            # One marker per interruption in its conversation (A4), by construction rather than by
            # the odds of 16 hex digits: a record whose short marker another record of the same
            # conversation already carries is given the marker of its whole id instead.
            if connection.execute("SELECT 1 FROM interruptions WHERE thread_id=? AND marker=? LIMIT 1",
                                  (row["thread_id"], row["marker"])).fetchone() is not None:
                row["marker"] = ids.marker(key)
            drift = connection.execute(
                "SELECT interruption_id FROM interruptions WHERE thread_id=? AND turn_id=? "
                "AND interruption_id<>? LIMIT 1", (row["thread_id"], row["turn_id"], key)).fetchone()
            if drift is not None:
                # The same Codex turn under a new identity (its completion time or
                # position changed). Recovering it again would be a second recovery of
                # one failure, so it is refused - and journaled rather than raised,
                # since a raise here would stop every other detection in the same pass.
                self._event(connection, now, "identity_drift", record=self._row(connection, drift[0]))
                return False
            parent = self._parent(connection, row, owner_id)
            # The counters of the task it continues - or, for a predecessor from before chains
            # existed, the v0.5 carry rule, applied in the same transaction instead of a second
            # write - and the stop it is born in, if its task cannot go on (domain/gates.py).
            row.update(machine.inherited(parent, failed_turn_progress, legacy_carry))
            stop = machine.birth_stop(parent, failed_turn_progress, limits, is_usage(row), now=now,
                              legacy_carry=legacy_carry)
            reason = None
            if stop is not None:
                row["state"], reason = stop
                if reason == "parent_cancelled":
                    row["cancel_requested"] = True
            row["last_error"] = reason
            row = _validated_record(row)
            columns = ",".join(_RECORD_COLUMNS)
            placeholders = ",".join("?" for _ in _RECORD_COLUMNS)
            connection.execute(
                f"INSERT INTO interruptions ({columns}) VALUES ({placeholders})",
                tuple(_sql(row[field]) for field in _RECORD_COLUMNS),
            )
            self._event(connection, now, "detected", record=row, to_state=row["state"],
                        reason=reason, turn_ref="failed")
            return True

    def claimed_on_thread(self, thread_id: str) -> list[dict[str, Any]]:
        """Records that may have put a continuation into this thread."""
        _uuid(thread_id, "thread_id")
        with self._read() as connection:
            return [_validated_record(dict(row)) for row in connection.execute(
                "SELECT * FROM interruptions WHERE thread_id=? AND (last_claim_at IS NOT NULL "
                "OR submitted_at IS NOT NULL OR legacy=1) ORDER BY detected_at", (thread_id,))]

    def chain_parent(self, thread_id: str, turn_id: str, owner_id: str | None = None):
        """The record whose own continuation started the failed turn `turn_id`, as `register` would
        find it, and nothing written (v0.6.13): the engine reads it before it asks the edition's plug
        about a failure (engine/detect.py), so the two cannot disagree about a chain."""
        with self._read() as connection:
            return self._find_parent(connection, thread_id, turn_id, owner_id)

    def _find_parent(self, connection, thread_id, turn_id, owner_id):
        """The record whose recovery turn is `turn_id`, else the owner of the marker in it on the
        same conversation - the one the watch has not correlated yet - or None."""
        found = connection.execute(
            "SELECT * FROM interruptions WHERE thread_id=? AND recovery_turn_id=?",
            (thread_id, turn_id)).fetchone()
        if found is not None:
            return _validated_record(dict(found))
        if owner_id is None:
            return None
        owner = self._row(connection, owner_id)
        if owner is None or owner["thread_id"] != thread_id:
            return None
        return owner

    def _parent(self, connection, row, owner_id):
        """The record whose own continuation started the turn that just failed."""
        owner = self._find_parent(connection, row["thread_id"], row["turn_id"], owner_id)
        if owner is None or owner["interruption_id"] != owner_id:
            return owner
        if owner["recovery_turn_id"] is None:
            # Link a record the watch has not correlated yet, or a record from before
            # correlation existed, to the turn its marker is in. The index still
            # refuses a second owner.
            try:
                connection.execute(
                    "UPDATE interruptions SET recovery_turn_id=? WHERE interruption_id=? "
                    "AND recovery_turn_id IS NULL", (row["turn_id"], owner_id))
                owner["recovery_turn_id"] = row["turn_id"]
            except sqlite3.IntegrityError:
                pass
        return owner

    def get(self, interruption_id: str) -> dict[str, Any] | None:
        with self._read() as connection:
            return self._row(connection, interruption_id)

    def all_records(self) -> list[dict[str, Any]]:
        with self._read() as connection:
            return [_validated_record(dict(row)) for row in connection.execute(
                "SELECT * FROM interruptions ORDER BY detected_at, interruption_id"
            )]

    def records_in(self, states) -> list[dict[str, Any]]:
        wanted = tuple(sorted(set(states) & STATES))
        if not wanted:
            return []
        with self._read() as connection:
            return [_validated_record(dict(row)) for row in connection.execute(
                "SELECT * FROM interruptions WHERE state IN (%s) ORDER BY detected_at, interruption_id"
                % ",".join("?" for _ in wanted), wanted)]

    def pending(self) -> list[dict[str, Any]]:
        return self.records_in(STATES - TERMINAL)

    def failure_marks(self) -> dict[str, Any]:
        """Two times for the icon's "a recovery failed" (v0.6.8): the newest certain failure - a `failed` record's
        outcome_at, which it is given once as it ends and never again - and the newest moment a recovery was on its
        way: a claim still held (submitted_at, which a claim handed back unsent clears), a continuation queued
        (first_queued_at) or a recovery turn seen starting (turn_started_at). Not last_claim_at: a claim released before
        anything was sent keeps it, and sent nothing. Read from the records, never the journal. A failure hidden by
        Clear history counts for nothing, and neither does a row migrated from schema 2, which has no outcome_at."""
        with self._read() as connection:
            failed = connection.execute(
                "SELECT max(outcome_at) FROM interruptions WHERE state='failed' AND outcome_at IS NOT NULL "
                "AND history_hidden_at IS NULL").fetchone()[0]
            started = connection.execute(
                "SELECT max(max(coalesce(submitted_at, 0), coalesce(first_queued_at, 0), "
                "coalesce(turn_started_at, 0))) FROM interruptions").fetchone()[0]
        started = _finite(started)
        return {"failed_at": _finite(failed), "started_at": started if started else None}

    def history(self, *, include_hidden: bool = False, limit: int = 500) -> list[dict[str, Any]]:
        """Records for display, newest first. With failure_marks, the readers that honour Clear history."""
        limit = max(1, min(int(limit), 10000))
        where = "" if include_hidden else "WHERE history_hidden_at IS NULL"
        with self._read() as connection:
            return [_validated_record(dict(row)) for row in connection.execute(
                "SELECT * FROM interruptions %s ORDER BY detected_at DESC, interruption_id LIMIT ?"
                % where, (limit,))]

    def update(self, interruption_id: str, *, at: float | None = None, actor: str = "engine",
               event: str | None = None, flags: int = 0, **changes: Any) -> None:
        """Change a record, within the transition table.

        A state event is journaled only when the state or its reason actually changed,
        so a record that re-enters the same wait every poll writes one line, not one per
        poll.
        """
        if not changes or not set(changes) <= _MUTABLE:
            raise StoreError("Invalid record update")
        with self._transaction() as connection:
            old = self._row(connection, interruption_id)
            if old is None:
                raise StoreError("Unknown interruption")
            row = _validated_record({**old, **changes})
            if not machine.plain_move_allowed(old["state"], row["state"]):
                if old["state"] in TERMINAL:
                    raise StoreError("Cannot reactivate terminal interruption")
                raise StoreError("Illegal state transition %s -> %s" % (old["state"], row["state"]))
            if old["submitted_at"] is not None and row["submitted_at"] is None:
                # Only a send proven never to have started may forget that it happened.
                if not (old["state"] == "submitting" and row["state"] in {"waiting_retry", "failed"}
                        and old["queue_id"] is None):
                    raise StoreError("Cannot clear possible submission")
            elif old["state"] == "submitting" and row["state"] == "waiting_retry":
                raise StoreError("A claimed record returns to waiting only with its send disproved")
            if old["recovery_turn_id"] is not None and row["recovery_turn_id"] != old["recovery_turn_id"]:
                raise StoreError("A recovery turn is written once")
            if old["cancel_requested"] and not row["cancel_requested"]:
                raise StoreError("A cancellation cannot be withdrawn")
            assignments = ",".join(f"{column}=?" for column in changes)
            connection.execute(
                f"UPDATE interruptions SET {assignments} WHERE interruption_id=?",
                (*[_sql(row[column]) for column in changes], interruption_id),
            )
            if event is not None:
                self._event(connection, self._now(at), event, record=row, from_state=old["state"],
                            to_state=row["state"], reason=row["last_error"], actor=actor, flags=flags)
            elif (old["state"], old["last_error"]) != (row["state"], row["last_error"]):
                self._event(connection, self._now(at), "state", record=row, from_state=old["state"],
                            to_state=row["state"], reason=row["last_error"], actor=actor, flags=flags)
