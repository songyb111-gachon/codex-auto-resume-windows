"""The claim's ledger (P11): the edition's plug asked inside a claim, and what it may do there.

A claim (claims.py) asks the plug's ledger last, once every check of core's has granted it, on
the claim's own connection and inside its transaction - so what the ledger counts is counted
under the same lock as core's rows. Here is how it is asked: under a savepoint that takes back
whatever it wrote if it holds the claim, through a handle that can `execute` and nothing else,
and under an authorizer that keeps core's schemas and the claim's transaction out of its reach.
The standard edition's plug is never asked, so none of this runs there.
"""
from __future__ import annotations

import os
import sqlite3

from ..domain.plug import Alternative

# What a ledger may do on the claim's connection while it is asked (P11): read anything, attach
# a database of its own, and write, create and drop there. Core's schemas - main, and temp,
# where a trigger on core's tables could be left behind - are never written, and no transaction
# or savepoint is begun, ended or rolled back: those are the claim's. A statement with no schema
# to judge it by, other than the reads below, is refused.
_CORE_SCHEMAS = (None, "main", "temp")
_LEDGER_READS = frozenset({sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION,
                           sqlite3.SQLITE_RECURSIVE})
# A pragma is read and never set, whatever schema it names. Most are settings of the whole
# connection - query_only, busy_timeout, trusted_schema, writable_schema - which a schema's name
# in front of them does not confine, and core's connection lives as long as the watcher: one
# set through the ledger's own schema outlived the claim, and query_only left every later write
# of core's failing until a restart. These are read with no argument, which would set them...
_LEDGER_PRAGMAS = frozenset({"database_list", "user_version", "schema_version", "data_version",
                             "application_id"})
# ...and these take one that names the table or index they read.
_LEDGER_NAMED_PRAGMAS = frozenset({"table_info", "table_xinfo", "index_list", "index_info",
                                   "index_xinfo", "foreign_key_list"})


def _ledger_authorizer(attached):
    """What a ledger may do while it is asked. `attached` is every file the claim's connection
    has attached, main's first; a file an ATTACH lets on is added to it."""
    def authorize(action, first, second, schema, _trigger):
        if action in _LEDGER_READS:
            return sqlite3.SQLITE_OK
        if action == sqlite3.SQLITE_ATTACH:
            if not _attachable(first, attached):
                return sqlite3.SQLITE_DENY
            attached.append(first)
            return sqlite3.SQLITE_OK
        if action == sqlite3.SQLITE_PRAGMA:
            read = first in _LEDGER_NAMED_PRAGMAS or (first in _LEDGER_PRAGMAS and second is None)
            return sqlite3.SQLITE_OK if read else sqlite3.SQLITE_DENY
        if action in (sqlite3.SQLITE_TRANSACTION, sqlite3.SQLITE_SAVEPOINT, sqlite3.SQLITE_DETACH):
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_DENY if schema in _CORE_SCHEMAS else sqlite3.SQLITE_OK
    return authorize


def _attachable(name, attached) -> bool:
    """Whether a ledger may attach the file `name` to the claim's connection.

    Nothing a ledger attaches can be detached - it stays for the life of core's connection - so
    a second name for a file already there stays too: under it, core's own state.sqlite needed a
    second write lock on its own file, and every write transaction core began afterwards waited
    ten seconds and failed, from the claim just granted onwards. So the file is one not attached
    already, under any spelling, a link or another path to it included, and the statement names
    it: a bound or computed name reaches this as None, and says nothing of which file it is."""
    if not isinstance(name, str) or name[:5].lower() == "file:":
        return False
    if name in ("", ":memory:"):
        return True                                  # a database of its own, with no file
    try:
        return not any(_same_file(name, other) for other in attached)
    except ValueError:                               # a NUL, say: no file anyone can name
        return False


def _same_file(first, second) -> bool:
    try:
        return os.path.samefile(first, second)
    except OSError:                                  # one is not there yet: compare the paths
        return os.path.normcase(os.path.abspath(first)) == os.path.normcase(os.path.abspath(second))


class _Rows:
    """A statement's rows, read out whole: no cursor, and so no way back to the connection."""
    __slots__ = ("_rows",)

    def __init__(self, rows):
        self._rows = list(rows)

    def fetchone(self):
        return self._rows.pop(0) if self._rows else None

    def fetchall(self):
        rows, self._rows = self._rows, []
        return rows

    def __iter__(self):
        return iter(self.fetchall())


class _LedgerConnection:
    """The claim's connection as a ledger is handed it: `execute`, and nothing else.

    Not the connection itself, whose authorizer, row factory and transaction are the claim's to
    set: a ledger holding it could have taken the authorizer off before it wrote. What ends it
    is the claim's own (`_ledger_holds`), and nothing on this object: its `close` was an
    attribute a ledger could set to a no-op, and the handle it kept then wrote core's tables
    after the authorizer was gone. Nothing can be set on it at all.

    Like the tick's view of the store (engine/options.py, StoreView), this guards against a
    ledger's mistakes, not its intent: the ledger runs in core's process, where the handle's
    closure, a failed statement's traceback and state.sqlite itself all reach the connection
    for code that goes looking."""
    __slots__ = ("_execute",)

    def __init__(self, execute):
        object.__setattr__(self, "_execute", execute)

    def __setattr__(self, name, value):
        raise AttributeError("the claim's connection has nothing to set")

    def __delattr__(self, name):
        raise AttributeError("the claim's connection has nothing to delete")

    def execute(self, statement, parameters=()):
        return self._execute(statement, parameters)


class LedgerMixin:
    @staticmethod
    def _ledger_holds(connection, ledger, row, now, carried=frozenset()) -> bool:
        """P11: whether the plug's ledger holds a claim every check of core's has granted.

        Asked inside the claim's transaction and on its connection, so what the plug counts -
        in a database of its own it attaches here - is counted under the same lock as core's
        rows. What it writes there commits with the claim and nothing else: a savepoint takes
        it back if it holds the claim, which then spends nothing, or if its hook raised.
        HOLD is all it can say; it can refuse, never grant - so it is handed `execute` alone,
        under an authorizer that refuses every write to core's schemas and every transaction
        statement (`_ledger_authorizer`). A ledger that deferred after switching a conversation
        back on would otherwise have granted what the person had refused.

        The ledger is told which of the plug's answers the send carries (`carried`), as core
        decided them, so it pays for those and for nothing core dropped. A hook that raised
        costs its own answer, and on a claim of core's own that is all: the claim is granted as
        with no plug. On a claim that `carried` an answer of the plug's, the failure is what
        that answer was to be paid with, so the claim is held and nothing the plug chose goes
        out unpaid and uncounted. Whether this call raised is asked of this
        call (`claim_ledger_checked`), not read from `failures`, which every thread holding the
        plug adds to.
        """
        connection.execute("SAVEPOINT claim_ledger")
        # The handle's one way to the connection. Emptied here once the ledger has answered, so
        # a handle it kept is no way into a later transaction.
        live = [connection]

        def execute(statement, parameters=()):
            if not live:
                raise sqlite3.ProgrammingError("the claim this connection was handed for is over")
            return _Rows(live[0].execute(statement, parameters).fetchall())
        attached = [listed[2] for listed in connection.execute("PRAGMA database_list") if listed[2]]
        connection.set_authorizer(_ledger_authorizer(attached))
        try:
            answer, broke = ledger.claim_ledger_checked(_LedgerConnection(execute), row, now,
                                                        carried)
        finally:
            connection.set_authorizer(None)
            live.clear()
        held = answer is Alternative.HOLD or (broke and bool(carried))
        if held or broke:
            connection.execute("ROLLBACK TO claim_ledger")
        connection.execute("RELEASE claim_ledger")
        return held
