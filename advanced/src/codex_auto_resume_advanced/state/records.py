# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""The edition's own records, and what a capability asks of one of core's.

A record of this edition's - an empty response, a prompt, anything no core category describes -
never becomes a row of core's: core would have to call it something it is not, and it validates
every row it opens. It lives here, and the one claim counts it with core's rows (ledger.py), so
one continuation in flight per conversation, five claims a day and fifteen minutes between them
hold across both tables. No capability writes one yet; these are the only ways one is written.

Those caps hold both ways only if a record of this edition's is claimed where core's rows can be
seen: `claim_record`, on core's connection inside its claim, with this file attached. On this
file's own connection core's rows are not there, so `move_record` never puts a record in flight.

An override is a capability's request about one standard record - force it once, reset early,
climb the capacity ladder, resend once - keyed by that record's interruption id, so a standard
installation that finds this file finds nothing of it in its own state.
"""
from __future__ import annotations

from codex_auto_resume import machine

from ..registry import CORE_COOLDOWN_SECONDS, CORE_DAILY_CAP
from ..vocabulary import OverrideKind, RecordState
from .schema import ATTACHED
from .session import StateError, _key, _thread, _timestamp, _word

DAY = 86400
# Where `move_record` may take a record from where it is. A settled record stays settled, and
# going in flight is not a move: it is a claim (`claim_record`).
_MOVES = {RecordState.WAITING: {RecordState.CANCELLED},
          RecordState.IN_FLIGHT: {RecordState.WAITING, RecordState.FINISHED, RecordState.CANCELLED}}


class RecordsMixin:
    def _capability(self, capability):
        if self.registry.get(capability) is None:
            raise StateError("unknown capability")
        return capability

    def add_record(self, record_id, capability, thread_id, at=None) -> bool:
        """A new record, waiting. False if the id is taken."""
        _key(record_id, "record id")
        self._capability(capability)
        _thread(thread_id)
        now = self._now(at)
        with self._transaction() as connection:
            if connection.execute("SELECT 1 FROM records WHERE record_id=?", (record_id,)).fetchone():
                return False
            connection.execute("INSERT INTO records (record_id, capability, thread_id, state, "
                               "created_at, claims) VALUES (?,?,?,?,?,0)",
                               (record_id, capability, thread_id, RecordState.WAITING, now))
            return True

    def move_record(self, record_id, state, at=None) -> bool:
        """Move a record along `_MOVES`: back to waiting, finished or cancelled."""
        _key(record_id, "record id")
        state = _word(state, RecordState, "record state")
        now = self._now(at)
        with self._transaction(create=False) as connection:
            if connection is None:
                return False
            row = connection.execute("SELECT state FROM records WHERE record_id=?", (record_id,)).fetchone()
            if row is None or state not in _MOVES.get(row["state"], ()):
                return False
            connection.execute("UPDATE records SET state=?, finished_at=? WHERE record_id=?",
                               (state, now if state in (RecordState.FINISHED, RecordState.CANCELLED)
                                else None, record_id))
            return True

    def claim_record(self, connection, record_id, now) -> bool:
        """Put a waiting record of this edition's in flight: its claim, counted and timed.

        Only on core's connection, inside its claim's BEGIN IMMEDIATE, with this file attached
        (`attach`), so both tables are read and written under the one lock that claim holds; and
        only where core's rows and this edition's together allow one more on the conversation -
        nothing of either in flight, fewer than five claims in a day, fifteen minutes since the
        last. False, and nothing written, otherwise. No capability claims one yet: an advanced
        record reaches the claim only once core carries P2 out (domain/plug.py)."""
        _key(record_id, "record id")
        now = _timestamp(now, "time")
        if getattr(connection, "in_transaction", True) is False:
            raise StateError("a record is claimed only inside core's claim")
        if not self.attach(connection):
            return False
        row = connection.execute("SELECT state, thread_id FROM %s.records WHERE record_id=?" % ATTACHED,
                                 (record_id,)).fetchone()
        if row is None or row[0] != RecordState.WAITING:
            return False
        thread_id = row[1]
        if any(machine.may_be_queued(state, queue_id) for state, queue_id in connection.execute(
                "SELECT state, queue_id FROM main.interruptions WHERE thread_id=?", (thread_id,))):
            return False
        ours = connection.execute(
            "SELECT coalesce(sum(state=?), 0), "
            "coalesce(sum(CASE WHEN claimed_at > ? THEN max(claims, 1) ELSE 0 END), 0), "
            "max(claimed_at) FROM %s.records WHERE thread_id=?" % ATTACHED,
            (RecordState.IN_FLIGHT, now - DAY, thread_id)).fetchone()
        cores = connection.execute(
            "SELECT coalesce(sum(CASE WHEN coalesce(submitted_at, last_claim_at) > ? "
            "THEN max(attempt_count, 1) ELSE 0 END), 0), "
            "max(coalesce(submitted_at, last_claim_at)) FROM main.interruptions WHERE thread_id=?",
            (now - DAY, thread_id)).fetchone()
        last = max((at for at in (ours[2], cores[1]) if at is not None), default=None)
        if (ours[0] or ours[1] + cores[0] >= CORE_DAILY_CAP
                or (last is not None and now - last < CORE_COOLDOWN_SECONDS)):
            return False
        connection.execute("UPDATE %s.records SET state=?, claimed_at=?, claims=claims+1 "
                           "WHERE record_id=?" % ATTACHED, (RecordState.IN_FLIGHT, now, record_id))
        return True

    def records_on(self, thread_id) -> list:
        _thread(thread_id)
        with self._read() as connection:
            if connection is None:
                return []
            rows = connection.execute("SELECT * FROM records WHERE thread_id=? ORDER BY created_at",
                                      (thread_id,)).fetchall()
        return [dict(row) for row in rows if self.registry.get(row["capability"]) is not None]

    # ---------------------------------------------------------------- overrides
    def add_override(self, interruption_id, capability, kind, at=None) -> bool:
        """One capability's request about one standard record. False if it already has one."""
        _key(interruption_id, "interruption id")
        self._capability(capability)
        kind = _word(kind, OverrideKind, "override kind")
        now = self._now(at)
        with self._transaction() as connection:
            if connection.execute("SELECT 1 FROM overrides WHERE interruption_id=? AND capability=?",
                                  (interruption_id, capability)).fetchone():
                return False
            connection.execute("INSERT INTO overrides (interruption_id, capability, kind, created_at) "
                               "VALUES (?,?,?,?)", (interruption_id, capability, kind, now))
            return True

    def overrides_for(self, interruption_id) -> list:
        """Every unused override on one standard record, of capabilities this registry holds."""
        _key(interruption_id, "interruption id")
        with self._read() as connection:
            if connection is None:
                return []
            rows = connection.execute("SELECT * FROM overrides WHERE interruption_id=? AND used_at IS NULL "
                                      "ORDER BY created_at", (interruption_id,)).fetchall()
        return [dict(row) for row in rows if self.registry.get(row["capability"]) is not None
                and row["kind"] in tuple(OverrideKind)]

    def use_override(self, interruption_id, capability, at=None) -> bool:
        """Mark an override used, once. It is never used twice."""
        _key(interruption_id, "interruption id")
        now = self._now(at)
        with self._transaction(create=False) as connection:
            if connection is None:
                return False
            return connection.execute(
                "UPDATE overrides SET used_at=? WHERE interruption_id=? AND capability=? AND used_at IS NULL",
                (now, interruption_id, capability)).rowcount == 1
