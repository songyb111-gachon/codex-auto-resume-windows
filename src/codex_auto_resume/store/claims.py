"""Claiming the right to send, and letting it go again.

A claim is the only way into `submitting`, and it re-checks every store-side gate inside the
transaction that grants it - because the engine's view was taken a moment earlier. The order
the refusals come in is the sentence a person reads when they ask why a recovery is waiting.

The edition's plug has one point in here, its claim ledger (P11): asked last, inside the same
transaction, it can refuse a claim every check of core's has granted, and nothing else. The
standard edition's plug is not asked at all, so its claim is the one there always was.
"""
from __future__ import annotations

from contextlib import contextmanager
import os
import sqlite3
from typing import Any
from .. import machine
from ..domain import ids
from ..domain.plug import Alternative, guard
from ..machine import WAITING, WATCHED
from .errors import StoreError
from .validate import (_claim_cost, _finite, _timestamp, _uuid, _validated_record,
                       is_usage)

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


class ClaimsMixin:
    def recent_claims(self, thread_id: str, since: float) -> list[float]:
        """The most recent claim of each record, for cooldown and next-check timing."""
        _uuid(thread_id, "thread_id")
        with self._read() as connection:
            rows = connection.execute(
                "SELECT coalesce(submitted_at, last_claim_at) AS at FROM interruptions "
                "WHERE thread_id=? AND coalesce(submitted_at, last_claim_at) > ? ORDER BY at DESC",
                (thread_id, since)).fetchall()
        return [row[0] for row in rows if _finite(row[0]) is not None]

    def recent_claim_count(self, thread_id: str, since: float) -> int:
        """Conservative attempt count, including repeated claims of one record.

        Schema 3 durably retains only each record's latest claim time and total
        attempts. Count all of its attempts until that latest time leaves the window;
        this can delay an old record, but cannot undercount or depend on a pruned
        journal. Legacy records with a timestamp count at least once.
        """
        _uuid(thread_id, "thread_id")
        with self._read() as connection:
            return int(connection.execute(
                "SELECT coalesce(sum(max(attempt_count, 1)), 0) FROM interruptions "
                "WHERE thread_id=? AND coalesce(submitted_at, last_claim_at)>?",
                (thread_id, since)).fetchone()[0])

    def claimed_on_thread(self, thread_id: str) -> list[dict[str, Any]]:
        """Records that may have put a continuation into this thread."""
        _uuid(thread_id, "thread_id")
        with self._read() as connection:
            return [_validated_record(dict(row)) for row in connection.execute(
                "SELECT * FROM interruptions WHERE thread_id=? AND (last_claim_at IS NOT NULL "
                "OR submitted_at IS NOT NULL OR legacy=1) ORDER BY detected_at", (thread_id,))]

    @staticmethod
    def _others_in_flight(connection, thread_id, exclude) -> int:
        return sum(machine.may_be_queued(state, queue_id) for state, queue_id in connection.execute(
            "SELECT state, queue_id FROM interruptions WHERE thread_id=? AND interruption_id<>?",
            (thread_id, exclude)))

    def others_in_flight(self, thread_id: str, exclude: str) -> int:
        with self._read() as connection:
            return self._others_in_flight(connection, thread_id, exclude)

    # --------------------------------------------------------------- claiming
    @contextmanager
    def submission_guard(self, interruption_id: str):
        """Serialize final consent with the queue process launch, and only launch.

        Cancel, Pause and thread-disable use the same SQLite write lock. Once one
        of those actions commits, a subsequent process launch cannot use its old
        consent. The transport releases this before waiting for a receipt.
        """
        with self._transaction() as connection:
            row = self._row(connection, interruption_id)
            permitted = bool(
                row is not None and row["state"] == "submitting"
                and row["submitted_at"] is not None and row["queue_id"] is None
                and not row["cancel_requested"]
                and self._read_settings(connection)["enabled"]
                and self._thread_enabled(connection, row["thread_id"]))
            yield permitted

    def reserve(self, interruption_id: str, now: float, **options) -> bool:
        return self.reserve_detailed(interruption_id, now, **options)[0]

    def reserve_detailed(self, interruption_id: str, now: float, *, limits: dict | None = None,
                         gates: dict | None = None, ledger=None, carried=frozenset()) -> tuple:
        """Claim a record for sending, re-checking every store-side gate in the claim.

        Returns (claimed, refusing_gate, reason). The gate vector - the engine's view of
        Codex plus the store's own checks made here - is persisted whether the claim is
        granted or refused, so an interface can show exactly why a record is waiting.
        `ledger` is the engine's plug (domain/plug.py), asked last (P11); None is NULL's.
        `carried` is the points whose answers of the plug's the send this claim leads to
        carries - Point.TEXT for its words, Point.SENDER for its channel - which its ledger pays
        for (`_ledger_holds`).
        """
        _timestamp(now, "now")
        if gates is not None and limits is None:
            raise StoreError("A gate vector needs the budget limits it was evaluated with")
        ledger, carried = guard(ledger), frozenset(carried)   # the ledger's to read, not to change
        with self._transaction() as connection:
            settings = self._read_settings(connection)
            row = self._row(connection, interruption_id)
            if row is None:
                return False, "identity", "unknown_record"
            vector = dict(gates or {})
            vector["consent"] = machine.gate_consent(
                settings["enabled"], self._thread_enabled(connection, row["thread_id"]),
                row["cancel_requested"])
            vector["submission_safe"] = machine.gate_submission_safe(
                row, self._others_in_flight(connection, row["thread_id"], interruption_id))
            vector["schedule"] = machine.gate_schedule(row, now)
            if limits is not None:
                vector.update(machine.gate_budgets(row, limits, is_usage(row)))
            refusal = None
            for name in ("consent", "submission_safe", "schedule", "chain_budget",
                         "attempt_budget", "no_progress_budget"):
                if name in vector and vector[name][0] != machine.PASS:
                    refusal = (name, vector[name][1])
                    break
            if gates is not None and refusal is None:
                found = machine.first_refusal(vector)
                if found is not None:
                    refusal = (found[0], found[1][1])
            if (refusal is None and not ledger.null
                    and self._ledger_holds(connection, ledger, row, now, carried)):
                # The edition counts a claim of its own on this conversation - one in flight, or
                # the day's or the cooldown's - and the record waits, as behind one of core's.
                vector["submission_safe"] = machine.gate(machine.WAIT, machine.HELD)
                refusal = ("submission_safe", machine.HELD)
            encoded = machine.encode_gates(vector) if gates is not None else None
            if refusal is not None:
                if encoded is not None and row["state"] in WAITING:
                    connection.execute(
                        "UPDATE interruptions SET gate_eval=?, gate_eval_at=? WHERE interruption_id=?",
                        (encoded, now, interruption_id))
                return False, refusal[0], refusal[1]
            connection.execute(
                "UPDATE interruptions SET state='submitting', attempt_count=attempt_count+1, %s, "
                "submitted_at=?, last_claim_at=?, last_error=NULL, gate_eval=coalesce(?, gate_eval), "
                "gate_eval_at=coalesce(?, gate_eval_at) WHERE interruption_id=?" % _claim_cost(row),
                (now, now, encoded, now if encoded is not None else None, interruption_id))
            self._event(connection, now, "claim", record=row, from_state=row["state"],
                        to_state="submitting")
            return True, None, None

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

    def record_gates(self, interruption_id: str, gates: dict, now: float) -> None:
        """Persist a gate vector for a waiting record that was due but not claimable."""
        _timestamp(now, "now")
        encoded = machine.encode_gates(gates)
        with self._transaction() as connection:
            connection.execute(
                "UPDATE interruptions SET gate_eval=?, gate_eval_at=? WHERE interruption_id=? "
                "AND state IN (%s)" % ",".join("?" for _ in WAITING),
                (encoded, now, interruption_id, *sorted(WAITING)))

    def release_claim(self, interruption_id: str, target: str, reason: str, now: float, *,
                      next_retry_at: float | None = None, actor: str = "engine") -> bool:
        """Undo a claim whose send never started.

        Only the engine calls this, and only between the claim and starting the queue
        process, so nothing can have reached Codex. The claim time is kept - the daily
        cap and cooldown still count it - but the attempt counters are given back,
        because no attempt happened.
        """
        _timestamp(now, "now")
        if target not in WAITING | {"cancelled", "superseded", "superseded_by_user"}:
            raise StoreError("Invalid release target")
        with self._transaction() as connection:
            row = self._row(connection, interruption_id)
            if (row is None or row["state"] != "submitting" or row["queue_id"] is not None
                    or row["submitted_at"] is None):
                return False
            connection.execute(
                "UPDATE interruptions SET state=?, submitted_at=NULL, last_error=?, next_retry_at=?, %s, "
                "cancel_requested=CASE WHEN ?='cancelled' THEN 1 ELSE cancel_requested END "
                "WHERE interruption_id=?" % _claim_cost(row, refund=True),
                (target, reason, now if next_retry_at is None else next_retry_at, target, interruption_id))
            self._event(connection, now, "release_claim", record=row, from_state="submitting",
                        to_state=target, reason=reason, actor=actor)
            return True

    def correlate(self, interruption_id: str, recovery_turn_id: str, now: float, *,
                  client_id=None, status=None, state: str = "turn_started", reason=None,
                  after_user_work: bool = False, user_joined: bool = False,
                  extra_event: str | None = None) -> bool:
        """Record the exact Codex turn our continuation started.

        Written once. The unique index refuses a turn another record already owns, and
        that refusal is returned as False for the engine to treat as ambiguous.
        """
        _timestamp(now, "now")
        _uuid(recovery_turn_id, "recovery_turn_id")
        if state not in ("turn_started", "handed_over"):
            raise StoreError("Invalid correlation state")
        client = client_id if ids.is_client_id(client_id) else None
        with self._transaction() as connection:
            row = self._row(connection, interruption_id)
            if row is None or row["state"] not in WATCHED:
                return False
            if row["recovery_turn_id"] not in (None, recovery_turn_id):
                return False
            updated = {**row, "state": state, "recovery_turn_id": recovery_turn_id,
                       "recovery_client_id": client, "recovery_turn_status": machine.turn_status(status),
                       "resumed_at": now, "turn_started_at": now, "last_error": reason,
                       "first_queued_at": row["first_queued_at"] or row["submitted_at"],
                       "after_user_work": bool(row["after_user_work"] or after_user_work),
                       "user_joined": bool(row["user_joined"] or user_joined),
                       "outcome_at": now if state == "handed_over" else None}
            updated = _validated_record(updated)
            try:
                connection.execute(
                    "UPDATE interruptions SET state=?, recovery_turn_id=?, recovery_client_id=?, "
                    "recovery_turn_status=?, resumed_at=?, turn_started_at=?, last_error=?, "
                    "first_queued_at=?, after_user_work=?, user_joined=?, outcome_at=? "
                    "WHERE interruption_id=?",
                    (updated["state"], recovery_turn_id, client, updated["recovery_turn_status"],
                     now, now, reason, updated["first_queued_at"], int(updated["after_user_work"]),
                     int(updated["user_joined"]), updated["outcome_at"], interruption_id))
            except sqlite3.IntegrityError:
                return False
            flags = ((machine.FLAG_AFTER_USER_WORK if updated["after_user_work"] else 0)
                     | (machine.FLAG_USER_JOINED if updated["user_joined"] else 0))
            self._event(connection, now, "correlated", record=updated, from_state=row["state"],
                        to_state=state, reason=reason, turn_ref="recovery", flags=flags)
            if extra_event:
                self._event(connection, now, extra_event, record=updated, turn_ref="recovery",
                            flags=flags)
            return True

    def release_withdrawn(self, interruption_id: str, now: float, *, window: float,
                          later_turn: bool, marker_rows: int, row_present: bool, fresh: bool,
                          target: str, next_retry_at: float | None = None) -> bool:
        """Return a continuation withdrawn because of a Pause to its waiting state.

        The one way back from "sent" to "waiting", so every condition is re-checked here
        rather than trusted: our own delete succeeded, the settle window has passed, no
        copy of our marker exists anywhere, and - with Codex's history known to be
        current - no turn at all has started on the thread since the failure. A
        dispatched item would have created that turn.
        """
        _timestamp(now, "now")
        if target not in WAITING:
            raise StoreError("Invalid release target")
        with self._transaction() as connection:
            row = self._row(connection, interruption_id)
            if (row is None or row["state"] != "withdrawn_unconfirmed"
                    or row["withdraw_reason"] != "paused" or not row["withdraw_deleted"]
                    or now - row["withdrawn_at"] < window or later_turn or marker_rows
                    or row_present or not fresh or row["cancel_requested"]):
                return False
            connection.execute(
                "UPDATE interruptions SET state=?, submitted_at=NULL, queue_id=NULL, "
                "withdraw_reason=NULL, withdrawn_at=NULL, withdraw_deleted=0, withdraw_failures=0, "
                "last_error='released_after_withdrawal', next_retry_at=?, %s WHERE interruption_id=?"
                % _claim_cost(row, refund=True), (target, now if next_retry_at is None else next_retry_at,
                                                  interruption_id))
            self._event(connection, now, "release_withdrawn", record=row,
                        from_state="withdrawn_unconfirmed", to_state=target, reason="paused",
                        flags=machine.FLAG_WITHDRAW_DELETED)
            return True
