# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""The lines a person asked to be added to a running turn (version 9's `steers`, v0.6.20, issue #50 - steer_send).

    steers  one row a steer: its conversation, the person's own words, the client id it carries, where it stands
            (SteerState: requested, sending, then accepted, unconfirmed or refused) and why it was refused
            (SteerReason), when it was asked and when it settled

A steer is written `requested` by the Dashboard's request (control/steer.py) and taken by the watcher alone
(engine/steer.py): `claim` moves it to `sending` in one transaction, before its one write to the Codex app - so two
errands can never both write it, and a crash after the claim never writes it again (`settle_cut_short` settles it
unconfirmed). The words are kept after the send, by the owner's decision of 2026-10-29, so History shows exactly what
went in: the Codex app does not show a steered line (MSTEER2). The journal's pass bounds the table, 30 days and 1,000
rows (state/journal.py).
"""
from __future__ import annotations

from ..vocabulary import SteerReason, SteerState
from .schema import STEER_WORDS
from .session import StateError, _thread, _word

# Where a steer is still to settle.
WAITING = (SteerState.REQUESTED, SteerState.SENDING)
# The three outcomes, never collapsed into one another (#50).
SETTLED = (SteerState.ACCEPTED, SteerState.UNCONFIRMED, SteerState.REFUSED)
COLUMNS = "steer_id, thread_id, words, client_id, state, reason, created_at, finished_at"


def _client(client_id) -> str:
    if (not isinstance(client_id, str) or len(client_id) != 36
            or any(character not in "0123456789abcdef-" for character in client_id)):
        raise StateError("invalid client id")
    return client_id


class SteersMixin:
    def steers(self, since=0.0) -> list:
        """Every steer asked at `since` or later, oldest first, with its words."""
        if isinstance(since, bool) or not isinstance(since, (int, float)):
            raise StateError("invalid time")
        with self._read() as connection:
            if connection is None:
                return []
            return [dict(row) for row in connection.execute(
                "SELECT %s FROM steers WHERE created_at >= ? ORDER BY created_at, steer_id" % COLUMNS,
                (float(since),)).fetchall()]

    def waiting_steers(self) -> list:
        """The steers still to settle - requested or sending - oldest first."""
        with self._read() as connection:
            if connection is None:
                return []
            return [dict(row) for row in connection.execute(
                "SELECT %s FROM steers WHERE state IN (?, ?) ORDER BY created_at, steer_id" % COLUMNS,
                WAITING).fetchall()]

    def add_steer(self, thread_id, words, client_id, at=None) -> int:
        """A steer asked for, `requested`; its id."""
        _thread(thread_id)
        if not isinstance(words, str) or not words.strip() or len(words) > STEER_WORDS:
            raise StateError("invalid words")
        now = self._now(at)
        with self._transaction() as connection:
            return connection.execute(
                "INSERT INTO steers (thread_id, words, client_id, state, created_at) VALUES (?,?,?,?,?)",
                (thread_id, words, _client(client_id), SteerState.REQUESTED, now)).lastrowid

    def claim_steer(self, steer_id) -> bool:
        """The watcher's claim of one steer, `requested -> sending`, before its one write: True only for the one call that
        moved it - a steer claimed already, settled or gone is never claimed again."""
        if type(steer_id) is not int:
            raise StateError("invalid steer id")
        with self._transaction(create=False) as connection:
            if connection is None:
                return False
            return connection.execute("UPDATE steers SET state=? WHERE steer_id=? AND state=?",
                                      (SteerState.SENDING, steer_id, SteerState.REQUESTED)).rowcount == 1

    def settle_steer(self, steer_id, state, reason=None, at=None) -> bool:
        """What came of one steer still waiting: accepted or unconfirmed (from `sending` alone - only a claimed steer was
        written), or refused with its reason (from either). False where it had settled already, or is gone."""
        if type(steer_id) is not int:
            raise StateError("invalid steer id")
        state = _word(state, SteerState, "state")
        if state not in SETTLED:
            raise StateError("invalid state")
        if state == SteerState.REFUSED:
            reason = _word(reason, SteerReason, "reason")
            before = WAITING
        else:
            if reason is not None:
                raise StateError("only a refusal has a reason")
            before = (SteerState.SENDING, SteerState.SENDING)
        now = self._now(at)
        with self._transaction(create=False) as connection:
            if connection is None:
                return False
            return connection.execute(
                "UPDATE steers SET state=?, reason=?, finished_at=? WHERE steer_id=? AND state IN (?, ?)",
                (state, reason, now, steer_id) + tuple(before)).rowcount == 1

    def end_requested_steers(self, reason, at=None) -> int:
        """Every steer still `requested` - never one being written - refused with `reason`: what turning steer_send off
        does (arming.sweep), so nothing waits to be sent later. How many."""
        reason = _word(reason, SteerReason, "reason")
        now = self._now(at)
        with self._transaction(create=False) as connection:
            if connection is None:
                return 0
            return connection.execute("UPDATE steers SET state=?, reason=?, finished_at=? WHERE state=?",
                                      (SteerState.REFUSED, reason, now, SteerState.REQUESTED)).rowcount

    def settle_cut_short(self, at=None) -> int:
        """Every steer left `sending` - a watcher that stopped between the claim and the answer - settled unconfirmed: it
        may have been written, so it may have been delivered, and it is never written again. How many."""
        now = self._now(at)
        with self._transaction(create=False) as connection:
            if connection is None:
                return 0
            return connection.execute("UPDATE steers SET state=?, finished_at=? WHERE state=?",
                                      (SteerState.UNCONFIRMED, now, SteerState.SENDING)).rowcount


def prune(connection, now, max_age, limit) -> None:
    """The settled steers older than `max_age`, then the oldest settled beyond `limit`; never one still waiting."""
    settled = "state NOT IN ('%s', '%s')" % WAITING
    connection.execute("DELETE FROM steers WHERE %s AND created_at < ?" % settled, (now - max_age,))
    excess = connection.execute("SELECT count(*) FROM steers").fetchone()[0] - limit
    if excess > 0:
        connection.execute("DELETE FROM steers WHERE steer_id IN (SELECT steer_id FROM steers WHERE %s "
                           "ORDER BY created_at, steer_id LIMIT ?)" % settled, (excess,))


class SteersHandle:
    """What steer_send's code is given of the state (state.Scoped's `steers`): the steers, read always; claimed and settled
    only while the runtime has it on - but a refusal and the settling of a steer cut short are written whatever it
    stands at, so a steer is never left waiting by a turn off. Held in a closure, as the Scoped view is."""
    __slots__ = ("capability", "_calls")

    def __init__(self, state, capability, on):
        self.capability = capability

        def writing(call):
            def written(*arguments, **keywords):
                if on is None or on() is not True:
                    raise StateError("the capability is not on")
                return call(*arguments, **keywords)
            return written

        def settling(steer_id, state_word, reason=None, at=None):
            if str(state_word) != SteerState.REFUSED and (on is None or on() is not True):
                raise StateError("the capability is not on")
            return state.settle_steer(steer_id, state_word, reason, at)

        self._calls = {
            "on": lambda: on is not None and on() is True,
            "steers": state.steers,
            "waiting": state.waiting_steers,
            "claim": writing(state.claim_steer),
            "settle": settling,
            "cut_short": state.settle_cut_short,
        }

    def __getattr__(self, name):
        calls = object.__getattribute__(self, "_calls")
        if name in calls:
            return calls[name]
        raise AttributeError(name)
