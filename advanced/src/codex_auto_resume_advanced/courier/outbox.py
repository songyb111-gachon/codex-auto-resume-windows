# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""The pushed notices waiting to go (state `outbox`, advanced state version 8) - written, tried and dropped through the
advanced state's own file and transaction; no sqlite of its own, no network.

One row a notice a channel: a closed event, core's category word or none, the record's place in Pending as `task N`
or none, when it was raised, how many tries it had, and whether it waits, went or was dropped. Never a title, a path,
an id, an address or a word of a conversation: no column could hold one.

Bounds, all channels together: at most HOURLY rows raised in any hour - a notice past it is not written (the
PLAN-v0.6.12 limit); TRIES tries each, the next not before AFTER[tries] seconds from when it was raised; dropped after
the last, or at MAX_AGE however many it had (a paused PC's notices wait, then go). The journal's pass prunes the table
to 7 days and 500 rows besides (state/journal.py).

The journal says what came of each try in push_notices' own codes (`codes`): `sent_<channel>`,
`refused_<channel>_<status class>` and `dropped_<channel>` - the channel and how it failed, never the address - and
`off_<channel>` where TRIPWIRE refusals (4xx or TLS) in one day turned that channel off.
"""
from __future__ import annotations

from ..vocabulary import CourierChannel, CourierEvent, OutboxState

CAPABILITY = "push_notices"
HOURLY = 30
TRIES = 3
# Seconds after a notice was raised before its first, second and third try: at once, then 10 s, then 70 s (10 and 60
# between). The courier runs at most once a minute, so in practice a try waits for the next run.
AFTER = (0, 10, 70)
MAX_AGE = 7 * 86400
TRIPWIRE = 20
DAY = 86400
# How a try failed, as the journal keeps it (http.STATUS_CLASSES less 2xx); the two a channel's tripwire counts.
FAILED = ("4xx", "5xx", "timeout", "tls")
REFUSING = ("4xx", "tls")


def codes() -> tuple:
    """push_notices' journal codes, every channel's, in a stable order."""
    found = []
    for channel in CourierChannel:
        found += ["sent_%s" % channel] + ["refused_%s_%s" % (channel, word) for word in FAILED]
        found += ["dropped_%s" % channel, "off_%s" % channel]
    return tuple(found)


def alias(index) -> str | None:
    """A record's 1-based place in Pending as a push names it, `task N`, or None."""
    return "task %d" % index if type(index) is int and 1 <= index <= 9999 else None


def enqueue(state, channels, event, category, task, at) -> int:
    """One row for each of `channels` for `event`, in one transaction, as far as the hour's HOURLY leaves room - those
    past it are not written. How many were."""
    event = CourierEvent(event)
    channels = [CourierChannel(channel) for channel in channels]
    with state._transaction() as connection:
        used = connection.execute("SELECT count(*) FROM outbox WHERE at > ?", (at - 3600,)).fetchone()[0]
        room = max(0, HOURLY - used)
        for channel in channels[:room]:
            connection.execute("INSERT INTO outbox (channel, event, category, alias, at, tries, state, finished_at) "
                               "VALUES (?,?,?,?,?,0,?,NULL)",
                               (str(channel), str(event), category, task, float(at), str(OutboxState.WAITING)))
        return min(room, len(channels))


def due(state, now) -> list:
    """The rows waiting whose next try is due at `now`, oldest first, as dicts. Empty with no file."""
    with state._read() as connection:
        if connection is None:
            return []
        rows = connection.execute("SELECT item_id, channel, event, category, alias, at, tries FROM outbox "
                                  "WHERE state = ? ORDER BY item_id", (str(OutboxState.WAITING),)).fetchall()
    return [dict(row) for row in rows
            if row["tries"] < TRIES and now - row["at"] < MAX_AGE and now >= row["at"] + AFTER[row["tries"]]]


def waiting(state, now) -> bool:
    """Whether a row waits whose try is due, or one has grown too old to wait: either is work for a courier."""
    with state._read() as connection:
        if connection is None:
            return False
        rows = connection.execute("SELECT at, tries FROM outbox WHERE state = ?",
                                  (str(OutboxState.WAITING),)).fetchall()
    return any(now - row["at"] >= MAX_AGE or now >= row["at"] + AFTER[min(row["tries"], TRIES - 1)] for row in rows)


def settle(state, item_id, sent, now) -> str:
    """What a try of row `item_id` came to: `sent` - it went - or a failure, one try more, dropped at the last. The
    row's state after (OutboxState)."""
    with state._transaction() as connection:
        row = connection.execute("SELECT tries FROM outbox WHERE item_id = ? AND state = ?",
                                 (item_id, str(OutboxState.WAITING))).fetchone()
        if row is None:
            return str(OutboxState.DROPPED)
        if sent:
            connection.execute("UPDATE outbox SET tries = ?, state = ?, finished_at = ? WHERE item_id = ?",
                               (min(row["tries"] + 1, TRIES), str(OutboxState.SENT), float(now), item_id))
            return str(OutboxState.SENT)
        tries = row["tries"] + 1
        if tries >= TRIES:
            connection.execute("UPDATE outbox SET tries = ?, state = ?, finished_at = ? WHERE item_id = ?",
                               (TRIES, str(OutboxState.DROPPED), float(now), item_id))
            return str(OutboxState.DROPPED)
        connection.execute("UPDATE outbox SET tries = ? WHERE item_id = ?", (tries, item_id))
        return str(OutboxState.WAITING)


def expire(state, now) -> list:
    """Every row waiting MAX_AGE or longer, dropped; their channels, one for each."""
    with state._transaction() as connection:
        rows = connection.execute("SELECT item_id, channel FROM outbox WHERE state = ? AND at <= ?",
                                  (str(OutboxState.WAITING), now - MAX_AGE)).fetchall()
        for row in rows:
            connection.execute("UPDATE outbox SET state = ?, finished_at = ? WHERE item_id = ?",
                               (str(OutboxState.DROPPED), float(now), row["item_id"]))
    return [row["channel"] for row in rows]


def refusals_today(state, channel, now) -> int:
    """How many tries `channel` had refused today (4xx or TLS), as the sampler counted them."""
    names = ["refused_%s_%s" % (CourierChannel(channel), word) for word in REFUSING]
    with state._read() as connection:
        if connection is None:
            return 0
        found = connection.execute("SELECT sum(count) FROM sampler WHERE capability = ? AND day = ? AND code IN (?, ?)",
                                   (CAPABILITY, int(now // DAY), *names)).fetchone()[0]
    return int(found or 0)


class OutboxHandle:
    """push_notices' view of the outbox, as its code is given it (state.Scoped): rows written only while it stands on
    (`on`) and only by push_notices; whether one waits, read always."""
    __slots__ = ("_enqueue", "_waiting")

    def __init__(self, state, capability, on):
        def enqueue(channels, event, category, task, at):
            if capability != CAPABILITY or on is None or on() is not True:
                return 0
            return enqueue_rows(state, channels, event, category, task, at)
        self._enqueue = enqueue
        self._waiting = lambda now: capability == CAPABILITY and waiting(state, now)

    def enqueue(self, channels, event, category, task, at) -> int:
        return self._enqueue(channels, event, category, task, at)

    def waiting(self, now) -> bool:
        return self._waiting(now)


enqueue_rows = enqueue
