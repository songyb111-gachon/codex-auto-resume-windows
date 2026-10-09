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

from codex_auto_resume.domain.plug import Point

from .journal import prune_every
from .schema import ATTACHED
from .session import StateError, _key, _thread, _timestamp

DAY = 86400
HOUR = 3600
SCHEMAS = ("main", ATTACHED)
# The points that make a capability a channel or a route for the send it pays for.
CHANNELS = frozenset({Point.SENDER, Point.UNLOADED})
# How far apart a unit's time and a claim's may be and still be the one claim: a unit is spent at the
# very time the claim writes, so they are equal, and this only absorbs a float's round trip.
SAME_CLAIM = 0.001


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

    def spends_since(self, capability, since) -> dict:
        """{interruption id: the times of the units a capability spent on it} since `since`, from
        the newest 500 units: what the submission_unknown tripwire looks at (arming.py). A unit is
        spent inside the claim it pays for, at the claim's own time (ledger.py), so its time says
        which of a record's sends it paid for."""
        with self._read() as connection:
            if connection is None:
                return {}
            rows = connection.execute(
                "SELECT interruption_id, at FROM spend WHERE capability=? AND at>=? AND "
                "interruption_id IS NOT NULL ORDER BY spend_id DESC LIMIT 500",
                (capability, since)).fetchall()
        spent = {}
        for key, at in rows:
            spent.setdefault(key, []).append(at)
        return {key: tuple(times) for key, times in spent.items()}

    def payers(self, interruption_id, claimed_at) -> dict:
        """{capability: the times of its units} for each capability of the registry that paid for the
        send of standard record `interruption_id` claimed at `claimed_at` - a unit spent inside that very
        claim (v0.6.14). Where the claim's time cannot be read (None), every unit on the record counts:
        the side that holds back."""
        _key(interruption_id, "interruption id")
        with self._read() as connection:
            if connection is None:
                return {}
            rows = connection.execute("SELECT capability, at FROM spend WHERE interruption_id=? "
                                      "ORDER BY spend_id DESC LIMIT 500", (interruption_id,)).fetchall()
        found = {}
        for capability, at in rows:
            if self.registry.get(capability) is not None and (
                    claimed_at is None or abs(at - claimed_at) <= SAME_CLAIM):
                found.setdefault(capability, []).append(at)
        return {capability: tuple(times) for capability, times in found.items()}

    def channel_paid(self, interruption_id, claimed_at) -> bool:
        """Whether a capability that is a channel or a route - one answering at P5 or P16 - paid for that
        send of `interruption_id` (`payers`): such a send did more than queue words, and is never sent
        once more but by that capability's own Send again (arming.py)."""
        return any(self.registry.get(capability).points & CHANNELS
                   for capability in self.payers(interruption_id, claimed_at))

