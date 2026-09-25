# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""The spend ledger: one row for every unit a capability spent, and the counts its ceilings read.

A unit is spent before the send it pays for - inside core's one claim, on the claim's own
connection with this file attached (ledger.py) - so it commits with the claim or not at all, and
a crash after it can only have spent too much, never too little. It is never given back, not
even when the claim is, since nothing can prove the send it paid for never reached Codex.

The same statements serve both connections: this file's own, where its tables are `main`, and
core's, where it is attached as `advanced`. The schema name is one of those two constants and is
never taken from anything else.
"""
from __future__ import annotations

from .journal import prune_every
from .schema import ATTACHED
from .session import StateError, _key, _thread, _timestamp

DAY = 86400
HOUR = 3600
SCHEMAS = ("main", ATTACHED)


def _schema(name) -> str:
    if name not in SCHEMAS:
        raise StateError("unknown schema")
    return name


class SpendMixin:
    @staticmethod
    def counts(connection, schema, capability, thread_id, now) -> dict:
        """What this capability has spent in the last day, overall and in this conversation, and
        what every capability together has spent in the last hour."""
        schema = _schema(schema)
        day, hour = now - DAY, now - HOUR
        row = connection.execute(
            "SELECT coalesce(sum(capability=? AND at>?), 0) AS capability_day, "
            "coalesce(sum(capability=? AND thread_id=? AND at>?), 0) AS conversation_day, "
            "coalesce(sum(at>?), 0) AS global_hour FROM %s.spend WHERE at>?" % schema,
            (capability, day, capability, thread_id, day, hour, min(day, hour))).fetchone()
        return {name: int(row[name]) for name in ("capability_day", "conversation_day", "global_hour")}

    def spent(self, capability, thread_id, now=None) -> dict:
        """`counts` on this file's own connection, for a look before the claim. No file, no spend."""
        now = self._now(now)
        with self._read() as connection:
            if connection is None:
                return {"capability_day": 0, "conversation_day": 0, "global_hour": 0}
            return self.counts(connection, "main", capability, thread_id, now)

    def record_spend(self, connection, schema, capability, thread_id, interruption_id, now) -> None:
        """One unit, inside the caller's transaction. Pruned now and then, never inside a day."""
        schema = _schema(schema)
        if self.registry.get(capability) is None:
            raise StateError("unknown capability")
        _thread(thread_id)
        if interruption_id is not None:
            _key(interruption_id, "interruption id")
        now = _timestamp(now, "time")
        connection.execute("INSERT INTO %s.spend (at, capability, thread_id, interruption_id) "
                           "VALUES (?,?,?,?)" % schema, (now, capability, thread_id, interruption_id))
        if prune_every(connection.execute("SELECT last_insert_rowid()").fetchone()[0]):
            self._prune_spend(connection, schema, now)

    def spends_since(self, capability, since) -> list:
        """The interruption ids a capability spent a unit on since `since`, newest first: what
        the submission_unknown tripwire looks at (arming.py)."""
        with self._read() as connection:
            if connection is None:
                return []
            rows = connection.execute(
                "SELECT DISTINCT interruption_id FROM spend WHERE capability=? AND at>=? AND "
                "interruption_id IS NOT NULL ORDER BY spend_id DESC LIMIT 500",
                (capability, since)).fetchall()
        return [row[0] for row in rows]
