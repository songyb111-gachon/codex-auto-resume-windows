# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""The conversations opened in Codex for a waiting message to be sent (version 8's `opens`, v0.6.19, issue #50).

    opens   one row an open: its conversation, the record it was opened for (the edition's own record id, or a digest
            of core's interruption id - engine/opentarget.record_key), when, and what came of it (OpenOutcome): opened,
            then loaded (the next look found the conversation loaded) or not_loaded (still not after two looks) - or
            refused, where the open was never made

A row is written before the link is opened - the claim before the transport - so an open a crash cut short still counts.
The caps open_to_send keeps are read from these rows (engine/opentarget.py), so they hold across a restart; the journal's
pass bounds the table, seven days and 1,000 rows (state/journal.py). Nothing here names what a conversation says.
"""
from __future__ import annotations

from ..vocabulary import OpenOutcome
from .session import StateError, _key, _thread, _word

# What an open may settle as, from `opened`.
SETTLED = (OpenOutcome.LOADED, OpenOutcome.NOT_LOADED, OpenOutcome.REFUSED)


class OpensMixin:
    def opens(self, since) -> list:
        """The opens at `since` or later, oldest first: {open_id, thread_id, record_key, at, outcome}."""
        if isinstance(since, bool) or not isinstance(since, (int, float)):
            raise StateError("invalid time")
        with self._read() as connection:
            if connection is None:
                return []
            return [dict(row) for row in connection.execute(
                "SELECT open_id, thread_id, record_key, at, outcome FROM opens WHERE at >= ? ORDER BY at, open_id",
                (float(since),)).fetchall()]

    def add_open(self, thread_id, record_key, at=None) -> int:
        """An open about to be made, written first: `opened`; its id."""
        _thread(thread_id)
        _key(record_key, "record key")
        now = self._now(at)
        with self._transaction() as connection:
            return connection.execute("INSERT INTO opens (thread_id, record_key, at, outcome) VALUES (?,?,?,?)",
                                      (thread_id, record_key, now, OpenOutcome.OPENED)).lastrowid

    def settle_open(self, open_id, outcome) -> bool:
        """What came of an open still `opened`: loaded, not_loaded, or refused (never made). False where it had settled
        already, or is gone."""
        if type(open_id) is not int:
            raise StateError("invalid open id")
        outcome = _word(outcome, OpenOutcome, "outcome")
        if outcome not in SETTLED:
            raise StateError("invalid outcome")
        with self._transaction(create=False) as connection:
            if connection is None:
                return False
            return connection.execute("UPDATE opens SET outcome=? WHERE open_id=? AND outcome=?",
                                      (outcome, open_id, OpenOutcome.OPENED)).rowcount == 1


class OpensHandle:
    """What open_to_send's code is given of the state (state.Scoped's `opens`): the opens, read always; written only while
    the runtime has it on. Held in a closure, as the Scoped view is."""
    __slots__ = ("capability", "_calls")

    def __init__(self, state, capability, on):
        self.capability = capability

        def writing(call):
            def written(*arguments, **keywords):
                if on is None or on() is not True:
                    raise StateError("the capability is not on")
                return call(*arguments, **keywords)
            return written

        self._calls = {
            "on": lambda: on is not None and on() is True,
            "opens": state.opens,
            "add_open": writing(state.add_open),
            "settle_open": writing(state.settle_open),
        }

    def __getattr__(self, name):
        calls = object.__getattribute__(self, "_calls")
        if name in calls:
            return calls[name]
        raise AttributeError(name)
