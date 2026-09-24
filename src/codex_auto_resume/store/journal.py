"""What happened to a record, written down as it happens.

The events a timeline is drawn from, and the pruning that keeps them from growing without end.
"""
from __future__ import annotations

from .. import machine
from ..domain import ids
from ..machine import STATES, TERMINAL
from .validate import _finite


# The journal is bounded both ways, and never loses the story of a record still running.
EVENT_LIMIT = 5000

EVENT_MAX_AGE = 90 * 86400

_PRUNE_EVERY = 256


class JournalMixin:
    # ---------------------------------------------------------------- journal
    def _event(self, connection, at, code, *, record=None, from_state=None, to_state=None,
               reason=None, actor="engine", turn_ref=None, flags=0, value=None) -> None:
        """Append one content-free journal entry inside the caller's transaction.

        Unknown codes and reasons are stored as "other" rather than refused: a journal
        entry is never allowed to be the reason a state change fails to commit. The
        journal is also never an input to any decision.
        """
        connection.execute(
            "INSERT INTO events (at, interruption_id, chain_origin_id, code, from_state, "
            "to_state, reason, actor, turn_ref, flags, value) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (_finite(at, 0.0),
             record["interruption_id"] if record else None,
             record["chain_origin_id"] if record else None,
             machine.event_code(code),
             from_state if from_state in STATES else None,
             to_state if to_state in STATES else None,
             machine.reason_code(reason),
             machine.actor_code(actor),
             turn_ref if turn_ref in ("recovery", "failed") else None,
             flags if isinstance(flags, int) and not isinstance(flags, bool) and 0 <= flags < 2**31 else 0,
             _finite(value)))
        event_id = connection.execute("SELECT last_insert_rowid()").fetchone()[0]
        if event_id % _PRUNE_EVERY == 0:
            self._prune(connection, at)

    @staticmethod
    def _prune(connection, now) -> None:
        running = tuple(sorted(STATES - TERMINAL))
        keep = ("interruption_id IS NOT NULL AND interruption_id IN (SELECT interruption_id "
                "FROM interruptions WHERE state IN (%s))" % ",".join("?" for _ in running))
        connection.execute("DELETE FROM events WHERE at < ? AND NOT (%s)" % keep,
                           (_finite(now, 0.0) - EVENT_MAX_AGE, *running))
        excess = connection.execute("SELECT count(*) FROM events").fetchone()[0] - EVENT_LIMIT
        if excess > 0:
            connection.execute(
                "DELETE FROM events WHERE event_id IN (SELECT event_id FROM events WHERE NOT (%s) "
                "ORDER BY event_id LIMIT ?)" % keep, (*running, excess))

    def events(self, interruption_id=None, *, chain_origin_id=None, limit=500) -> list:
        """Journal entries, oldest first. Rows are coerced, never trusted: an entry
        that does not fit the vocabulary is shown as "other", and never fails a read."""
        limit = max(1, min(int(limit), EVENT_LIMIT))
        where, arguments = "", ()
        if interruption_id is not None:
            where, arguments = "WHERE interruption_id=?", (interruption_id,)
        elif chain_origin_id is not None:
            where, arguments = "WHERE chain_origin_id=?", (chain_origin_id,)
        with self._read() as connection:
            rows = connection.execute(
                "SELECT * FROM (SELECT * FROM events %s ORDER BY event_id DESC LIMIT ?) "
                "ORDER BY event_id" % where, (*arguments, limit)).fetchall()
        result = []
        for row in rows:
            row = dict(row)
            key = row["interruption_id"]
            flags = row["flags"]
            result.append({
                "event_id": row["event_id"] if isinstance(row["event_id"], int) else None,
                "at": _finite(row["at"], 0.0),
                "interruption_id": key if ids.is_interruption_id(key, as_stored=True) else None,
                "code": machine.event_code(row["code"]),
                "from_state": row["from_state"] if row["from_state"] in STATES else None,
                "to_state": row["to_state"] if row["to_state"] in STATES else None,
                "reason": machine.reason_code(row["reason"]),
                "actor": machine.actor_code(row["actor"]),
                "turn_ref": row["turn_ref"] if row["turn_ref"] in ("recovery", "failed") else None,
                "flags": flags if isinstance(flags, int) and not isinstance(flags, bool) else 0,
                "value": _finite(row["value"]),
            })
        return result
