"""Durable, fail-closed state owned exclusively by codex-auto-resume.

This module never opens Codex's databases. A transaction reserves an interruption
*before* any external command can start. An uncertain submission must not be
retried: only a dedicated operation that proves nothing was sent may clear
``submitted_at``. SQLite's FULL synchronous setting makes reservations durable.

Schema 3 adds what the engine needs to follow its own continuation exactly: the turn
that continuation started, how that turn ended, the chain a record belongs to, and a
content-free journal. Every row is still owned by this tool alone, and nothing in it
is a prompt, a reply or an error message.
"""

from __future__ import annotations

from contextlib import contextmanager
import math
from pathlib import Path
import re
import sqlite3
import statistics as _statistics
import time
from typing import Any, Iterator
from uuid import UUID

from . import failures, machine
from .machine import CLAIMED, EXHAUSTED, IN_FLIGHT, OBSERVING, STATES, TERMINAL, WAITING


SCHEMA_VERSION = 3
_KEY = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")
_CLIENT_ID = re.compile(r"[A-Za-z0-9-]{1,64}\Z")

# Schema 1 and 2 columns, in their original order.
_V2_COLUMNS = (
    "interruption_id", "thread_id", "turn_id", "completed_at", "started_at", "ordinal",
    "detected_at", "reset_at", "limit_type", "uncertain", "state", "retry_count",
    "next_retry_at", "resumed_at", "last_error", "marker", "queue_id", "submitted_at",
    "attempt_count", "cancel_requested", "category", "recovery_attempts", "no_progress_count",
)
# Columns added in schema 2. Existing rows are usage-limit records by definition,
# because that was the only thing schema 1 could ever record.
_SCHEMA_2_COLUMNS = (
    ("category", "TEXT NOT NULL DEFAULT 'usage_limit'"),
    ("recovery_attempts", "INTEGER NOT NULL DEFAULT 0"),
    ("no_progress_count", "INTEGER NOT NULL DEFAULT 0"),
)
# Columns added in schema 3. All content-free: ids, enums, counters and times.
_SCHEMA_3_COLUMNS = (
    ("recovery_turn_id", "TEXT"),
    ("recovery_client_id", "TEXT"),
    ("recovery_turn_status", "TEXT"),
    ("user_joined", "INTEGER NOT NULL DEFAULT 0"),
    ("after_user_work", "INTEGER NOT NULL DEFAULT 0"),
    ("legacy", "INTEGER NOT NULL DEFAULT 0"),
    ("withdraw_reason", "TEXT"),
    ("withdrawn_at", "REAL"),
    ("withdraw_deleted", "INTEGER NOT NULL DEFAULT 0"),
    ("withdraw_failures", "INTEGER NOT NULL DEFAULT 0"),
    ("turn_started_at", "REAL"),
    ("outcome_at", "REAL"),
    ("first_queued_at", "REAL"),
    ("last_claim_at", "REAL"),
    ("parent_interruption_id", "TEXT"),
    ("chain_origin_id", "TEXT NOT NULL DEFAULT ''"),
    ("chain_first_detected_at", "REAL NOT NULL DEFAULT 0"),
    ("chain_continuations", "INTEGER NOT NULL DEFAULT 0"),
    ("budget_resets", "INTEGER NOT NULL DEFAULT 0"),
    ("retry_now_count", "INTEGER NOT NULL DEFAULT 0"),
    ("usage_unavailable_seconds", "REAL NOT NULL DEFAULT 0"),
    ("usage_probe_at", "REAL"),
    ("gate_eval", "TEXT"),
    ("gate_eval_at", "REAL"),
    ("history_hidden_at", "REAL"),
)
_RECORD_COLUMNS = _V2_COLUMNS + tuple(name for name, _ in _SCHEMA_3_COLUMNS)
_EVENT_COLUMNS = ("event_id", "at", "interruption_id", "chain_origin_id", "code", "from_state",
                  "to_state", "reason", "actor", "turn_ref", "flags", "value")
_WATCHER_COLUMNS = ("singleton", "pid", "session_id", "started_at", "last_tick_at",
                    "last_tick_ok", "engine_state", "code_version")
_TABLES_V2 = {"settings", "threads", "interruptions"}
_TABLES_V3 = _TABLES_V2 | {"events", "watcher_status"}

# Fields a plain `update` may write. Chain linkage, the claim time and the history
# flag are written only by the operations that own them.
_MUTABLE = frozenset({
    "reset_at", "limit_type", "uncertain", "state", "retry_count", "next_retry_at",
    "resumed_at", "last_error", "queue_id", "submitted_at", "attempt_count",
    "cancel_requested", "recovery_attempts", "no_progress_count",
    "recovery_turn_id", "recovery_client_id", "recovery_turn_status", "user_joined",
    "after_user_work", "withdraw_reason", "withdrawn_at", "withdraw_deleted",
    "withdraw_failures", "turn_started_at", "outcome_at", "first_queued_at",
    "usage_unavailable_seconds", "usage_probe_at", "gate_eval", "gate_eval_at",
})
_NEEDS_RECOVERY_TURN = OBSERVING | {"recovered", "completed_no_progress",
                                    "recovery_turn_failed", "stopped_by_user"}
ENGINE_STATES = frozenset({"verified", "structurally_compatible", "incompatible", "unknown"})

# The journal is bounded both ways, and never loses the story of a record still running.
EVENT_LIMIT = 5000
EVENT_MAX_AGE = 90 * 86400
_PRUNE_EVERY = 256
# How long an unresolved `submission_unknown` is still being reconciled. Clear history
# keeps such a row visible until then, because it may still change.
UNKNOWN_WINDOW = 24 * 3600
MAX_BUDGET_RESETS = 3


class StoreError(RuntimeError):
    """Invalid or unavailable local state; automatic resumes must stop."""


class UpgradePending(StoreError):
    """The state is an older schema and this caller may not migrate it."""


class StateFromNewerVersion(StoreError):
    """The state was written by a newer version of this tool. Never a corruption."""


# ------------------------------------------------------------------------- validators
def _uuid(value: Any, name: str) -> str:
    if not isinstance(value, str):
        raise StoreError(f"Invalid {name}")
    try:
        parsed = UUID(value)
    except ValueError as exc:
        raise StoreError(f"Invalid {name}") from exc
    if str(parsed) != value:
        raise StoreError(f"Invalid {name}: canonical UUID required")
    return value


def _timestamp(value: Any, name: str, *, nullable: bool = False) -> Any:
    if value is None and nullable:
        return None
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) or value < 0 or value > 253402300799):
        raise StoreError(f"Invalid {name}")
    return value


def _integer(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0 or value > 2**63 - 1:
        raise StoreError(f"Invalid {name}")
    return value


def _flag(value: Any, name: str) -> bool:
    if not isinstance(value, (int, bool)) or value not in (0, 1):
        raise StoreError(f"Invalid {name}")
    return bool(value)


def _short_text(value: Any, name: str, maximum: int, *, nullable: bool = False) -> Any:
    if value is None and nullable:
        return None
    if (not isinstance(value, str) or len(value) > maximum
            or any(ord(character) < 32 or ord(character) == 127 for character in value)):
        raise StoreError(f"Invalid {name}")
    return value


def _choice(value: Any, name: str, allowed) -> Any:
    if value is not None and value not in allowed:
        raise StoreError(f"Invalid {name}")
    return value


def _validated_record(row: dict[str, Any]) -> dict[str, Any]:
    if set(row) != set(_RECORD_COLUMNS):
        raise StoreError("Invalid record schema")
    key = row["interruption_id"]
    if not isinstance(key, str) or not _KEY.fullmatch(key):
        raise StoreError("Invalid interruption_id")
    _uuid(row["thread_id"], "thread_id")
    _uuid(row["turn_id"], "turn_id")
    for field in ("completed_at", "detected_at", "next_retry_at", "chain_first_detected_at",
                  "usage_unavailable_seconds"):
        _timestamp(row[field], field)
    for field in ("started_at", "reset_at", "resumed_at", "submitted_at", "withdrawn_at",
                  "turn_started_at", "outcome_at", "first_queued_at", "last_claim_at",
                  "usage_probe_at", "gate_eval_at", "history_hidden_at"):
        _timestamp(row[field], field, nullable=True)
    for field in ("ordinal", "retry_count", "attempt_count", "recovery_attempts",
                  "no_progress_count", "withdraw_failures", "chain_continuations",
                  "budget_resets", "retry_now_count"):
        _integer(row[field], field)
    if row["category"] not in failures.CATEGORIES:
        raise StoreError("Invalid failure category")
    for field in ("uncertain", "cancel_requested", "user_joined", "after_user_work", "legacy",
                  "withdraw_deleted"):
        row[field] = _flag(row[field], field)
    _short_text(row["limit_type"], "limit_type", 160, nullable=True)
    _short_text(row["last_error"], "last_error", 240, nullable=True)
    _short_text(row["gate_eval"], "gate_eval", 4000, nullable=True)
    if not isinstance(row["state"], str) or row["state"] not in STATES:
        raise StoreError("Unknown record state")
    if row["marker"] != f"[codex-auto-resume:{key}]":
        raise StoreError("Invalid record marker")
    for field in ("queue_id", "recovery_turn_id"):
        if row[field] is not None:
            _uuid(row[field], field)
    if row["recovery_client_id"] is not None and (
            not isinstance(row["recovery_client_id"], str)
            or not _CLIENT_ID.fullmatch(row["recovery_client_id"])):
        raise StoreError("Invalid recovery_client_id")
    _choice(row["recovery_turn_status"], "recovery_turn_status", machine.TURN_STATUSES)
    _choice(row["withdraw_reason"], "withdraw_reason", machine.WITHDRAW_REASONS)
    parent = row["parent_interruption_id"]
    if parent is not None and (not isinstance(parent, str) or not _KEY.fullmatch(parent)):
        raise StoreError("Invalid parent_interruption_id")
    if not isinstance(row["chain_origin_id"], str) or not _KEY.fullmatch(row["chain_origin_id"]):
        raise StoreError("Invalid chain_origin_id")
    state = row["state"]
    if state in CLAIMED | IN_FLIGHT | OBSERVING and row["submitted_at"] is None:
        raise StoreError("Missing submission timestamp")
    if state in _NEEDS_RECOVERY_TURN and row["recovery_turn_id"] is None:
        raise StoreError("Missing recovery turn")
    if state == "withdrawn_unconfirmed" and (row["withdraw_reason"] is None or row["withdrawn_at"] is None):
        raise StoreError("Missing withdrawal details")
    return row


def _finite(value, default=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return default
    return float(value)


def _sql(value):
    return int(value) if isinstance(value, bool) else value


def is_usage(row: dict) -> bool:
    return row.get("category") == failures.USAGE_LIMIT


# What each schema-3 state means to a schema-2 reader. "resumed" meant "our message was
# delivered", which is true of every state a correlated turn can be in.
_DOWNGRADE_STATES = {
    "turn_started": "resumed", "turn_completed": "resumed", "recovered": "resumed",
    "completed_no_progress": "resumed", "recovery_turn_failed": "resumed",
    "stopped_by_user": "resumed", "outcome_unverified": "resumed",
    "handed_over": "superseded_by_user",
    "withdrawn_unconfirmed": "submission_unknown",
}


def downgrade_to_v2(state_dir: Path) -> dict:
    """Rewrite a schema-3 state as schema 2, for going back to a v0.5 release.

    The caller must hold the watcher's mutex. Every row is kept - cancelled, exhausted,
    unknown and hidden ones included - because those rows are what stop an old failure
    from being detected and recovered again, and disabled conversations stay disabled.
    Deleting the state instead would undo all of that, which is why this exists. A
    forensic copy is taken first; it is not a restore path.
    """
    path = Path(state_dir) / "state.sqlite"
    if Path(state_dir).is_symlink() or path.is_symlink() or not path.is_file():
        raise StoreError("Cannot open valid auto-resume state")
    connection = sqlite3.connect(path, timeout=10, isolation_level=None)
    try:
        connection.execute("PRAGMA trusted_schema=OFF")
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if version == 2:
            return {"changed": False, "rows": None}
        if version != SCHEMA_VERSION:
            raise StoreError("Only a schema-3 state can be downgraded")
        stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        connection.execute("VACUUM INTO ?", (str(Path(state_dir) / ("state.v3-backup-%s.sqlite" % stamp)),))
        mapping = " ".join("WHEN '%s' THEN '%s'" % item for item in sorted(_DOWNGRADE_STATES.items()))
        columns = ",".join(_V2_COLUMNS)
        selected = ",".join("CASE state %s ELSE state END" % mapping if name == "state" else name
                            for name in _V2_COLUMNS)
        connection.execute("BEGIN IMMEDIATE")
        try:
            if connection.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
                raise StoreError("The state changed while it was being downgraded")
            Store._create_interruptions_named(connection, "interruptions_v2")
            connection.execute("INSERT INTO interruptions_v2 (%s) SELECT %s FROM interruptions"
                               % (columns, selected))
            rows = connection.execute("SELECT count(*) FROM interruptions_v2").fetchone()[0]
            connection.execute("DROP TABLE interruptions")
            connection.execute("DROP TABLE events")
            connection.execute("DROP TABLE watcher_status")
            connection.execute("ALTER TABLE interruptions_v2 RENAME TO interruptions")
            connection.execute("CREATE INDEX interruptions_thread ON interruptions(thread_id)")
            v2 = tuple(sorted(machine.V2_STATES))
            if connection.execute("SELECT count(*) FROM interruptions WHERE state NOT IN (%s)"
                                  % ",".join("?" for _ in v2), v2).fetchone()[0]:
                raise StoreError("A state has no schema-2 meaning")
            connection.execute("PRAGMA user_version=2")
            connection.execute("COMMIT")
        except Exception:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        return {"changed": True, "rows": rows}
    except sqlite3.Error as exc:
        raise StoreError("The state could not be downgraded") from exc
    finally:
        connection.close()


class LegacyStore:
    """A schema-2 state that an older watcher still owns, opened without changing it.

    Between an upgrade and the moment the old watcher exits, the new interfaces must
    still be able to do the things that only ever reduce automation: pause, switch a
    conversation off, and cancel a conversation's recoveries the way v0.5 did - thread
    wide. Nothing else is offered, no schema change is made, and every write here is
    one the old watcher already understands.
    """

    def __init__(self, state_dir: Path):
        self.path = Path(state_dir) / "state.sqlite"
        if Path(state_dir).is_symlink() or self.path.is_symlink() or not self.path.is_file():
            raise StoreError("Cannot open valid auto-resume state")
        try:
            self._connection = sqlite3.connect(self.path, timeout=10, isolation_level=None)
            self._connection.execute("PRAGMA trusted_schema=OFF")
            version = self._connection.execute("PRAGMA user_version").fetchone()[0]
            tables = Store._tables(self._connection)
        except sqlite3.Error as exc:
            raise StoreError("Cannot open valid auto-resume state") from exc
        if version not in (1, 2) or tables != _TABLES_V2:
            self.close()
            raise StoreError("Not a state an older watcher owns")

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()

    @contextmanager
    def _transaction(self):
        connection = self._connection
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.execute("COMMIT")
        except Exception as exc:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            if isinstance(exc, sqlite3.Error):
                raise StoreError("State transaction failed") from exc
            raise

    def settings(self) -> dict:
        with self._transaction() as connection:
            connection.row_factory = sqlite3.Row
            try:
                return Store._read_settings(connection)
            finally:
                connection.row_factory = None

    def set_enabled(self, enabled: bool, now: float) -> None:
        if not isinstance(enabled, bool):
            raise StoreError("enabled must be boolean")
        _timestamp(now, "now")
        with self._transaction() as connection:
            row = connection.execute("SELECT enabled, armed_at FROM settings WHERE singleton=1").fetchone()
            armed = now if enabled and not row[0] else row[1]
            connection.execute("UPDATE settings SET enabled=?, armed_at=? WHERE singleton=1",
                               (int(enabled), armed))

    def thread_enabled(self, thread_id: str) -> bool:
        _uuid(thread_id, "thread_id")
        with self._transaction() as connection:
            row = connection.execute("SELECT enabled FROM threads WHERE thread_id=?", (thread_id,)).fetchone()
        return True if row is None else bool(row[0])

    def set_thread_enabled(self, thread_id: str, enabled: bool, **_ignored) -> None:
        _uuid(thread_id, "thread_id")
        if not isinstance(enabled, bool):
            raise StoreError("enabled must be boolean")
        with self._transaction() as connection:
            connection.execute("INSERT INTO threads VALUES (?,?) ON CONFLICT(thread_id) "
                               "DO UPDATE SET enabled=excluded.enabled", (thread_id, int(enabled)))

    def cancel_thread(self, thread_id: str, now: float, **_ignored) -> None:
        """v0.5's cancel, exactly: disable the thread, cancel what was never sent, and
        mark what may have been sent so the old watcher withdraws it."""
        _uuid(thread_id, "thread_id")
        _timestamp(now, "now")
        v2_terminal = tuple(sorted(machine.V2_STATES & TERMINAL))
        marks = ",".join("?" for _ in v2_terminal)
        with self._transaction() as connection:
            connection.execute("INSERT INTO threads VALUES (?,0) ON CONFLICT(thread_id) DO UPDATE SET enabled=0",
                               (thread_id,))
            connection.execute("UPDATE interruptions SET cancel_requested=1 WHERE thread_id=? AND "
                               "submitted_at IS NOT NULL AND state NOT IN (%s)" % marks,
                               (thread_id, *v2_terminal))
            connection.execute("UPDATE interruptions SET state='cancelled', cancel_requested=1, "
                               "next_retry_at=? WHERE thread_id=? AND submitted_at IS NULL AND "
                               "state NOT IN (%s)" % marks, (now, thread_id, *v2_terminal))

    def status_counts(self) -> dict:
        with self._transaction() as connection:
            return {row[0]: row[1] for row in connection.execute(
                "SELECT state, count(*) FROM interruptions GROUP BY state") if row[0] in machine.V2_STATES}

    def thread_of(self, interruption_id: str):
        with self._transaction() as connection:
            row = connection.execute("SELECT thread_id FROM interruptions WHERE interruption_id=?",
                                     (str(interruption_id),)).fetchone()
        return row[0] if row else None

    def disabled_threads(self) -> set:
        with self._transaction() as connection:
            return {row[0] for row in connection.execute("SELECT thread_id FROM threads WHERE enabled=0")}


# ------------------------------------------------------------------------------ store
class Store:
    """One connection to our own state database.

    ``migrate`` must be passed explicitly: only the watcher, or a caller holding the
    watcher's single-instance mutex, may upgrade an older schema. Anyone else gets
    ``UpgradePending``. ``check`` runs the full integrity check and validates every row
    at open; per-call openers skip it and validate only the rows they read.
    """

    def __init__(self, state_dir: Path, *, migrate: bool = False, check: bool = True,
                 clock=time.time):
        self.state_dir = Path(state_dir)
        self.path = self.state_dir / "state.sqlite"
        self.clock = clock
        self._connection: sqlite3.Connection | None = None
        self.migrated_from: int | None = None
        try:
            if self.state_dir.is_symlink() or self.path.is_symlink():
                raise StoreError("State paths must not be symbolic links")
            self.state_dir.mkdir(parents=True, exist_ok=True)
            was_present = self.path.exists()
            self._connection = sqlite3.connect(self.path, timeout=10, isolation_level=None)
            self._connection.row_factory = sqlite3.Row
            self._connection.execute("PRAGMA trusted_schema=OFF")
            self._connection.execute("PRAGMA foreign_keys=ON")
            self._connection.execute("PRAGMA synchronous=FULL")
            version = self._connection.execute("PRAGMA user_version").fetchone()[0]
            if version > SCHEMA_VERSION:
                raise StateFromNewerVersion(
                    "This state was written by a newer version of codex-auto-resume")
            if version in (1, 2):
                if not migrate:
                    raise UpgradePending("Upgrade pending: an older watcher still owns the state")
                self._forensic_copy(version)
            # A current state is only read at open, so it takes no write lock: an open
            # must not wait behind - or fail because of - a watcher that is writing. Only
            # creating or upgrading the schema takes the write lock.
            opening = self._read if version == SCHEMA_VERSION else self._transaction
            with opening() as connection:
                version = connection.execute("PRAGMA user_version").fetchone()[0]
                tables = self._tables(connection)
                if not tables and version == 0:
                    if was_present:
                        raise StoreError("Existing state is empty or uninitialized; refusing to reset")
                    self._create_schema(connection)
                elif version > SCHEMA_VERSION:
                    raise StateFromNewerVersion(
                        "This state was written by a newer version of codex-auto-resume")
                elif version in (1, 2):
                    if not migrate:
                        raise UpgradePending("Upgrade pending: an older watcher still owns the state")
                    self._migrate(connection, version)
                elif version != SCHEMA_VERSION or tables != _TABLES_V3:
                    raise StoreError("Unsupported or malformed state schema")
                self._validate_schema(connection)
                self._read_settings(connection)
                if check or self.migrated_from is not None:
                    if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                        raise StoreError("State integrity check failed")
                    for row in connection.execute("SELECT thread_id, enabled FROM threads"):
                        _uuid(row["thread_id"], "thread_id")
                        _flag(row["enabled"], "thread enabled")
                    for row in connection.execute("SELECT * FROM interruptions"):
                        _validated_record(dict(row))
        except (sqlite3.Error, OSError, StoreError) as exc:
            self.close()
            if isinstance(exc, StoreError):
                raise
            raise StoreError("Cannot open valid auto-resume state") from exc

    # ---------------------------------------------------------------- schema
    @staticmethod
    def _tables(connection) -> set:
        return {row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}

    def _forensic_copy(self, version: int) -> None:
        """A copy of the old state taken before any schema change.

        Forensic only, and documented as such: restoring it would bring back records
        that have since been cancelled or finished, so it is never a restore path.
        """
        stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        target = self.state_dir / ("state.v%d-backup-%s.sqlite" % (version, stamp))
        if target.exists():
            return
        try:
            self._connection.execute("VACUUM INTO ?", (str(target),))
        except sqlite3.Error as exc:
            raise StoreError("Cannot take a copy of the state before upgrading it") from exc

    @staticmethod
    def _create_interruptions(connection) -> None:
        Store._create_interruptions_named(connection, "interruptions")
        connection.execute("CREATE INDEX interruptions_thread ON interruptions(thread_id)")

    @staticmethod
    def _create_interruptions_named(connection, name: str) -> None:
        """The schema-2 interruptions table, as v0.5 created it."""
        if name not in ("interruptions", "interruptions_v2"):
            raise StoreError("Invalid table name")
        connection.execute("""CREATE TABLE %s (""" % name + """
            interruption_id TEXT PRIMARY KEY,
            thread_id TEXT NOT NULL,
            turn_id TEXT NOT NULL,
            completed_at REAL NOT NULL,
            started_at REAL,
            ordinal INTEGER NOT NULL,
            detected_at REAL NOT NULL,
            reset_at REAL,
            limit_type TEXT,
            uncertain INTEGER NOT NULL CHECK (uncertain IN (0, 1)),
            state TEXT NOT NULL,
            retry_count INTEGER NOT NULL,
            next_retry_at REAL NOT NULL,
            resumed_at REAL,
            last_error TEXT,
            marker TEXT NOT NULL,
            queue_id TEXT,
            submitted_at REAL,
            attempt_count INTEGER NOT NULL,
            cancel_requested INTEGER NOT NULL CHECK (cancel_requested IN (0, 1)),
            category TEXT NOT NULL DEFAULT 'usage_limit',
            recovery_attempts INTEGER NOT NULL DEFAULT 0,
            no_progress_count INTEGER NOT NULL DEFAULT 0
        )""")

    @classmethod
    def _create_schema(cls, connection: sqlite3.Connection) -> None:
        connection.execute("""CREATE TABLE settings (
            singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
            enabled INTEGER NOT NULL CHECK (enabled IN (0, 1)),
            armed_at REAL NOT NULL,
            poll_seconds INTEGER NOT NULL
        )""")
        connection.execute("INSERT INTO settings VALUES (1, 0, 0, 30)")
        connection.execute("""CREATE TABLE threads (
            thread_id TEXT PRIMARY KEY,
            enabled INTEGER NOT NULL CHECK (enabled IN (0, 1))
        )""")
        cls._create_interruptions(connection)
        cls._add_schema_3(connection)
        connection.execute("PRAGMA user_version=3")

    @staticmethod
    def _migrate_1_to_2(connection: sqlite3.Connection) -> None:
        """Add the general-recovery columns to an existing schema-1 database."""
        if Store._tables(connection) != _TABLES_V2:
            raise StoreError("Unsupported or malformed state schema")
        found = {row[1] for row in connection.execute("PRAGMA table_info(interruptions)")}
        for name, definition in _SCHEMA_2_COLUMNS:
            if name not in found:
                connection.execute(f"ALTER TABLE interruptions ADD COLUMN {name} {definition}")
        # A literal, never SCHEMA_VERSION: this step produces schema 2 and nothing else.
        connection.execute("PRAGMA user_version=2")

    @staticmethod
    def _add_schema_3(connection: sqlite3.Connection) -> None:
        found = {row[1] for row in connection.execute("PRAGMA table_info(interruptions)")}
        for name, definition in _SCHEMA_3_COLUMNS:
            if name not in found:
                connection.execute(f"ALTER TABLE interruptions ADD COLUMN {name} {definition}")
        connection.execute("""CREATE TABLE IF NOT EXISTS events (
            event_id INTEGER PRIMARY KEY AUTOINCREMENT,
            at REAL NOT NULL,
            interruption_id TEXT,
            chain_origin_id TEXT,
            code TEXT NOT NULL,
            from_state TEXT,
            to_state TEXT,
            reason TEXT,
            actor TEXT,
            turn_ref TEXT,
            flags INTEGER NOT NULL DEFAULT 0,
            value REAL
        )""")
        connection.execute("CREATE INDEX IF NOT EXISTS events_record ON events(interruption_id, at)")
        connection.execute("""CREATE TABLE IF NOT EXISTS watcher_status (
            singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
            pid INTEGER,
            session_id TEXT,
            started_at REAL,
            last_tick_at REAL,
            last_tick_ok INTEGER,
            engine_state TEXT,
            code_version TEXT
        )""")
        # Deliberately not unique: an old database that already holds a duplicate must
        # still migrate. `register` refuses a new duplicate instead.
        connection.execute("CREATE INDEX IF NOT EXISTS interruptions_thread_turn "
                           "ON interruptions(thread_id, turn_id)")
        # No two records may ever own the same Codex turn.
        connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS interruptions_recovery_turn "
                           "ON interruptions(recovery_turn_id) WHERE recovery_turn_id IS NOT NULL")
        connection.execute("CREATE INDEX IF NOT EXISTS interruptions_claims "
                           "ON interruptions(thread_id, last_claim_at)")
        connection.execute("CREATE INDEX IF NOT EXISTS interruptions_chain "
                           "ON interruptions(chain_origin_id)")

    def _migrate_2_to_3(self, connection: sqlite3.Connection) -> None:
        if self._tables(connection) != _TABLES_V2:
            raise StoreError("Unsupported or malformed state schema")
        found = {row[1] for row in connection.execute("PRAGMA table_info(interruptions)")}
        if found != set(_V2_COLUMNS):
            raise StoreError("Malformed state schema")
        self._add_schema_3(connection)
        # Backfills. No row changes state: an in-flight v2 record is picked up by the
        # new watch exactly where it was.
        connection.execute(
            "UPDATE interruptions SET chain_origin_id=interruption_id, "
            "chain_first_detected_at=detected_at, "
            "legacy=CASE WHEN state='resumed' THEN 1 ELSE 0 END, "
            # Every earlier claim still counts towards the daily cap and the cooldown.
            "last_claim_at=submitted_at, "
            "first_queued_at=CASE WHEN state IN ('queued','resumed') THEN submitted_at END")
        now = self.clock()
        count = connection.execute("SELECT count(*) FROM interruptions").fetchone()[0]
        self._event(connection, now, "migrated", value=count)
        pending = tuple(sorted(STATES - TERMINAL))
        disabled = connection.execute(
            "SELECT count(DISTINCT t.thread_id) FROM threads t JOIN interruptions i "
            "ON i.thread_id=t.thread_id WHERE t.enabled=0 AND i.state IN (%s)"
            % ",".join("?" for _ in pending), pending).fetchone()[0]
        if disabled:
            self._event(connection, now, "disabled_threads_with_pending", value=disabled)
        connection.execute("PRAGMA user_version=3")

    def _migrate(self, connection, version: int) -> None:
        """A linear chain with literal targets: 1 -> 2 -> 3, each checking its source."""
        self.migrated_from = version
        if version == 1:
            self._migrate_1_to_2(connection)
            version = 2
        if version == 2:
            self._migrate_2_to_3(connection)

    @staticmethod
    def _validate_schema(connection: sqlite3.Connection) -> None:
        expected = {
            "settings": ({"singleton", "enabled", "armed_at", "poll_seconds"}, "singleton"),
            "threads": ({"thread_id", "enabled"}, "thread_id"),
            "interruptions": (set(_RECORD_COLUMNS), "interruption_id"),
            "events": (set(_EVENT_COLUMNS), "event_id"),
            "watcher_status": (set(_WATCHER_COLUMNS), "singleton"),
        }
        for table, (columns, primary_name) in expected.items():
            information = list(connection.execute(f"PRAGMA table_info({table})"))
            found = {row[1] for row in information}
            if found != columns:
                raise StoreError("Malformed state schema")
            primary = {row[1] for row in information if row[5] == 1}
            if primary != {primary_name} or any(row[5] > 1 for row in information):
                raise StoreError("Malformed state primary key")
        if connection.execute("SELECT 1 FROM sqlite_master WHERE type IN ('trigger', 'view') LIMIT 1").fetchone():
            raise StoreError("Unexpected state schema objects")

    # ------------------------------------------------------------ plumbing
    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, *_args: Any) -> None:
        self.close()

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        """A write transaction. Taken before anything that might change a row."""
        with self._begin("BEGIN IMMEDIATE") as connection:
            yield connection

    @contextmanager
    def _read(self) -> Iterator[sqlite3.Connection]:
        """A read transaction: one consistent snapshot, without blocking writers."""
        with self._begin("BEGIN") as connection:
            yield connection

    @contextmanager
    def _begin(self, statement: str) -> Iterator[sqlite3.Connection]:
        if self._connection is None:
            raise StoreError("Store is closed")
        connection = self._connection
        try:
            connection.execute(statement)
            yield connection
            connection.execute("COMMIT")
        except Exception as exc:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            if isinstance(exc, sqlite3.Error):
                raise StoreError("State transaction failed") from exc
            raise

    @staticmethod
    def _row(connection, interruption_id) -> dict | None:
        value = connection.execute(
            "SELECT * FROM interruptions WHERE interruption_id=?", (interruption_id,)).fetchone()
        return None if value is None else _validated_record(dict(value))

    def _now(self, at) -> float:
        return _timestamp(self.clock() if at is None else at, "now")

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
                "interruption_id": key if isinstance(key, str) and _KEY.fullmatch(key) else None,
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

    # ---------------------------------------------------------------- settings
    @staticmethod
    def _read_settings(connection: sqlite3.Connection) -> dict[str, Any]:
        rows = connection.execute("SELECT * FROM settings").fetchall()
        if len(rows) != 1 or rows[0]["singleton"] != 1:
            raise StoreError("Invalid settings")
        row = dict(rows[0])
        enabled = _flag(row["enabled"], "enabled")
        armed_at = _timestamp(row["armed_at"], "armed_at")
        poll = _integer(row["poll_seconds"], "poll_seconds")
        if not 5 <= poll <= 3600 or (enabled and armed_at == 0):
            raise StoreError("Invalid settings")
        return {"enabled": enabled, "armed_at": armed_at, "poll_seconds": poll}

    def settings(self) -> dict[str, Any]:
        with self._read() as connection:
            return self._read_settings(connection)

    def schema_version(self) -> int:
        """The schema on disk now. A watcher that finds a newer one stops using it."""
        with self._read() as connection:
            return connection.execute("PRAGMA user_version").fetchone()[0]

    def set_enabled(self, enabled: bool, now: float) -> None:
        if not isinstance(enabled, bool):
            raise StoreError("enabled must be boolean")
        _timestamp(now, "now")
        if enabled and now == 0:
            raise StoreError("Cannot arm with zero timestamp")
        with self._transaction() as connection:
            settings = self._read_settings(connection)
            # A new enable period excludes failures that happened while disabled.
            # Existing pending records remain eligible; collection applies this cutoff.
            armed_at = now if enabled and not settings["enabled"] else settings["armed_at"]
            connection.execute(
                "UPDATE settings SET enabled=?, armed_at=? WHERE singleton=1", (int(enabled), armed_at)
            )

    @staticmethod
    def _thread_enabled(connection: sqlite3.Connection, thread_id: str) -> bool:
        row = connection.execute("SELECT enabled FROM threads WHERE thread_id=?", (thread_id,)).fetchone()
        return True if row is None else _flag(row[0], "thread enabled")

    def thread_enabled(self, thread_id: str) -> bool:
        _uuid(thread_id, "thread_id")
        with self._read() as connection:
            return self._thread_enabled(connection, thread_id)

    def disabled_threads(self) -> set:
        with self._read() as connection:
            return {row[0] for row in connection.execute("SELECT thread_id FROM threads WHERE enabled=0")}

    def set_thread_enabled(self, thread_id: str, enabled: bool, *, actor: str = "engine",
                           at: float | None = None) -> None:
        _uuid(thread_id, "thread_id")
        if not isinstance(enabled, bool):
            raise StoreError("enabled must be boolean")
        with self._transaction() as connection:
            before = self._thread_enabled(connection, thread_id)
            connection.execute(
                "INSERT INTO threads VALUES (?,?) ON CONFLICT(thread_id) DO UPDATE SET enabled=excluded.enabled",
                (thread_id, int(enabled)),
            )
            if enabled and not before:
                self._event(connection, self._now(at), "thread_enabled", actor=actor)

    # ---------------------------------------------------------------- records
    def register(self, record: dict[str, Any], now: float, *,
                 state: str = "waiting_reset", next_retry_at: float | None = None,
                 owner_id: str | None = None, failed_turn_progress: bool | None = None,
                 legacy_carry: int | None = None, limits: dict | None = None) -> bool:
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
            "marker": f"[codex-auto-resume:{key}]", "queue_id": None,
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
            "history_hidden_at": None,
        }
        _validated_record(dict(row))
        with self._transaction() as connection:
            existing = self._row(connection, key)
            if existing is not None:
                if any(existing[field] != row[field] for field in
                       ("thread_id", "turn_id", "completed_at", "started_at", "ordinal")):
                    raise StoreError("Interruption identity collision")
                return False
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
            reason = None
            if parent is not None:
                for field in ("chain_origin_id", "chain_first_detected_at", "chain_continuations",
                              "recovery_attempts", "usage_unavailable_seconds", "budget_resets"):
                    row[field] = parent[field]
                row["parent_interruption_id"] = parent["interruption_id"]
                row["no_progress_count"] = parent["no_progress_count"] + (0 if failed_turn_progress is True else 1)
                if parent["cancel_requested"]:
                    row["state"], reason = "cancelled", "parent_cancelled"
                    row["cancel_requested"] = True
                elif (parent["user_joined"] or parent["after_user_work"]
                        or parent["state"] in ("handed_over", "stopped_by_user")):
                    row["state"], reason = "superseded", "parent_handed_over"
            elif isinstance(legacy_carry, int) and not isinstance(legacy_carry, bool) and legacy_carry > 0:
                # A predecessor from before chains existed: the v0.5 carry rule, now
                # applied in the same transaction instead of a second write.
                row["no_progress_count"] = legacy_carry
            if reason is None and limits is not None:
                if row["no_progress_count"] >= limits["max_no_progress"]:
                    row["state"], reason = "no_progress_exhausted", "no_progress_budget"
                elif row["chain_continuations"] >= limits["max_chain_continuations"]:
                    row["state"], reason = "retry_budget_exhausted", "chain_cap"
                elif (not is_usage(row)
                        and row["recovery_attempts"] >= limits["max_recovery_attempts"]):
                    row["state"], reason = "retry_budget_exhausted", "recovery_budget"
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

    def _parent(self, connection, row, owner_id):
        """The record whose own continuation started the turn that just failed."""
        found = connection.execute(
            "SELECT * FROM interruptions WHERE thread_id=? AND recovery_turn_id=?",
            (row["thread_id"], row["turn_id"])).fetchone()
        if found is not None:
            return _validated_record(dict(found))
        if owner_id is None:
            return None
        owner = self._row(connection, owner_id)
        if owner is None or owner["thread_id"] != row["thread_id"]:
            return None
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

    def history(self, *, include_hidden: bool = False, limit: int = 500) -> list[dict[str, Any]]:
        """Records for display, newest first. The only reader that honours Clear history."""
        limit = max(1, min(int(limit), 10000))
        where = "" if include_hidden else "WHERE history_hidden_at IS NULL"
        with self._read() as connection:
            return [_validated_record(dict(row)) for row in connection.execute(
                "SELECT * FROM interruptions %s ORDER BY detected_at DESC, interruption_id LIMIT ?"
                % where, (limit,))]

    def recent_claims(self, thread_id: str, since: float) -> list[float]:
        """When this thread's records were claimed, newest first. A claim released
        before its send still counts: the cap bounds how often we try, not how often
        Codex received something."""
        _uuid(thread_id, "thread_id")
        with self._read() as connection:
            rows = connection.execute(
                "SELECT coalesce(submitted_at, last_claim_at) AS at FROM interruptions "
                "WHERE thread_id=? AND coalesce(submitted_at, last_claim_at) > ? ORDER BY at DESC",
                (thread_id, since)).fetchall()
        return [row[0] for row in rows if _finite(row[0]) is not None]

    def claimed_on_thread(self, thread_id: str) -> list[dict[str, Any]]:
        """Records that may have put a continuation into this thread."""
        _uuid(thread_id, "thread_id")
        with self._read() as connection:
            return [_validated_record(dict(row)) for row in connection.execute(
                "SELECT * FROM interruptions WHERE thread_id=? AND (last_claim_at IS NOT NULL "
                "OR submitted_at IS NOT NULL OR legacy=1) ORDER BY detected_at", (thread_id,))]

    @staticmethod
    def _others_in_flight(connection, thread_id, exclude) -> int:
        return connection.execute(
            "SELECT count(*) FROM interruptions WHERE thread_id=? AND interruption_id<>? AND "
            "(state IN ('submitting','queued','withdrawn_unconfirmed') OR "
            "(state='submission_unknown' AND queue_id IS NOT NULL))",
            (thread_id, exclude)).fetchone()[0]

    def others_in_flight(self, thread_id: str, exclude: str) -> int:
        with self._read() as connection:
            return self._others_in_flight(connection, thread_id, exclude)

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

    # --------------------------------------------------------------- claiming
    def reserve(self, interruption_id: str, now: float, **options) -> bool:
        return self.reserve_detailed(interruption_id, now, **options)[0]

    def reserve_detailed(self, interruption_id: str, now: float, *, limits: dict | None = None,
                         gates: dict | None = None) -> tuple:
        """Claim a record for sending, re-checking every store-side gate in the claim.

        Returns (claimed, refusing_gate, reason). The gate vector - the engine's view of
        Codex plus the store's own checks made here - is persisted whether the claim is
        granted or refused, so an interface can show exactly why a record is waiting.
        """
        _timestamp(now, "now")
        if gates is not None and limits is None:
            raise StoreError("A gate vector needs the budget limits it was evaluated with")
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
            encoded = machine.encode_gates(vector) if gates is not None else None
            if refusal is not None:
                if encoded is not None and row["state"] in WAITING:
                    connection.execute(
                        "UPDATE interruptions SET gate_eval=?, gate_eval_at=? WHERE interruption_id=?",
                        (encoded, now, interruption_id))
                return False, refusal[0], refusal[1]
            connection.execute(
                "UPDATE interruptions SET state='submitting', attempt_count=attempt_count+1, "
                "recovery_attempts=recovery_attempts+?, chain_continuations=chain_continuations+1, "
                "submitted_at=?, last_claim_at=?, last_error=NULL, "
                "gate_eval=coalesce(?, gate_eval), gate_eval_at=coalesce(?, gate_eval_at) "
                "WHERE interruption_id=?",
                (0 if is_usage(row) else 1, now, now, encoded,
                 now if encoded is not None else None, interruption_id))
            self._event(connection, now, "claim", record=row, from_state=row["state"],
                        to_state="submitting")
            return True, None, None

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
                "UPDATE interruptions SET state=?, submitted_at=NULL, last_error=?, next_retry_at=?, "
                "recovery_attempts=max(0, recovery_attempts-?), "
                "chain_continuations=max(0, chain_continuations-1), "
                "cancel_requested=CASE WHEN ?='cancelled' THEN 1 ELSE cancel_requested END "
                "WHERE interruption_id=?",
                (target, reason, now if next_retry_at is None else next_retry_at,
                 0 if is_usage(row) else 1, target, interruption_id))
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
        client = client_id if isinstance(client_id, str) and _CLIENT_ID.fullmatch(client_id) else None
        with self._transaction() as connection:
            row = self._row(connection, interruption_id)
            if row is None or row["state"] not in {"submitting", "queued", "withdrawn_unconfirmed",
                                                   "submission_unknown"}:
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
                "last_error='released_after_withdrawal', next_retry_at=?, "
                "recovery_attempts=max(0, recovery_attempts-?), "
                "chain_continuations=max(0, chain_continuations-1) WHERE interruption_id=?",
                (target, now if next_retry_at is None else next_retry_at,
                 0 if is_usage(row) else 1, interruption_id))
            self._event(connection, now, "release_withdrawn", record=row,
                        from_state="withdrawn_unconfirmed", to_state=target, reason="paused",
                        flags=machine.FLAG_WITHDRAW_DELETED)
            return True

    # ------------------------------------------------------------ user actions
    def cancel_interruption(self, interruption_id: str, now: float, *, actor: str = "gui") -> dict | None:
        """Stop one recovery, and everything that continues it.

        Applies to the record's whole chain. A record that has not been sent is
        cancelled outright. Anything that may already be in Codex is only marked: the
        watch takes back whatever is still queued, and a turn that is already running is
        followed to its end. A finished record is marked too, so no later failure of
        that task can start a new chain from it.
        """
        _timestamp(now, "now")
        with self._transaction() as connection:
            row = self._row(connection, interruption_id)
            if row is None:
                return None
            chain = [_validated_record(dict(value)) for value in connection.execute(
                "SELECT * FROM interruptions WHERE chain_origin_id=? ORDER BY detected_at",
                (row["chain_origin_id"],))]
            effects, changed = {}, False
            for member in chain:
                key = member["interruption_id"]
                if member["state"] in WAITING and member["submitted_at"] is None:
                    connection.execute(
                        "UPDATE interruptions SET state='cancelled', cancel_requested=1, "
                        "last_error='user_cancelled', next_retry_at=? WHERE interruption_id=?",
                        (now, key))
                    self._event(connection, now, "cancel", record=member, from_state=member["state"],
                                to_state="cancelled", reason="user_cancelled", actor=actor)
                    effects[key], changed = "cancelled", True
                elif member["cancel_requested"]:
                    effects[key] = "unchanged"
                else:
                    connection.execute(
                        "UPDATE interruptions SET cancel_requested=1 WHERE interruption_id=?", (key,))
                    self._event(connection, now, "cancel_requested", record=member,
                                from_state=member["state"], to_state=member["state"], actor=actor)
                    # An uncertain submission may still be sitting in Codex's queue,
                    # and the watch takes it back on this mark: that is a real stop.
                    if member["state"] in TERMINAL and member["state"] != "submission_unknown":
                        effects[key] = "blocked_future"
                    else:
                        effects[key], changed = "cancel_requested", True
            return {"changed": changed, "effects": effects}

    def cancel_thread(self, thread_id: str, now: float, *, actor: str = "gui") -> None:
        """Turn automatic recovery off for one conversation, and stop what it has."""
        _uuid(thread_id, "thread_id")
        _timestamp(now, "now")
        with self._transaction() as connection:
            connection.execute(
                "INSERT INTO threads VALUES (?,0) ON CONFLICT(thread_id) DO UPDATE SET enabled=0", (thread_id,)
            )
            for value in connection.execute("SELECT * FROM interruptions WHERE thread_id=?", (thread_id,)).fetchall():
                row = _validated_record(dict(value))
                if row["state"] in TERMINAL:
                    continue
                if row["submitted_at"] is not None:
                    if not row["cancel_requested"]:
                        connection.execute(
                            "UPDATE interruptions SET cancel_requested=1 WHERE interruption_id=?",
                            (row["interruption_id"],))
                        self._event(connection, now, "cancel_requested", record=row,
                                    from_state=row["state"], to_state=row["state"], actor=actor)
                else:
                    connection.execute(
                        "UPDATE interruptions SET state='cancelled', cancel_requested=1, "
                        "last_error='user_cancelled', next_retry_at=? WHERE interruption_id=?",
                        (now, row["interruption_id"]))
                    self._event(connection, now, "cancel", record=row, from_state=row["state"],
                                to_state="cancelled", reason="user_cancelled", actor=actor)

    # v0.5 name: the thread-wide cancel.
    cancel = cancel_thread

    def restore_budget(self, interruption_id: str, now: float, **options) -> bool:
        return self.restore_budget_detailed(interruption_id, now, **options)[0]

    def restore_budget_detailed(self, interruption_id: str, now: float, *, actor: str = "gui",
                                max_resets: int = MAX_BUDGET_RESETS) -> tuple:
        """Give an exhausted interruption its budget back. Returns (restored, detail).

        `update` refuses to reactivate a terminal record, and that guard is what stops a
        finished, cancelled or uncertainly-submitted recovery from being restarted by a
        stray write. Running out of attempts is the one stop a person is allowed to undo,
        so it gets its own operation rather than a hole in the guard: the two exhausted
        states are the only ones accepted here, and a record that was cancelled or may
        already have been sent is refused even from those.

        It clears the budget and nothing else. It does not switch a conversation back
        on, it does not send, and the record returns to the wait its kind of failure
        needs, so every gate the watcher applies still applies. It can be done a few
        times per task, never without limit.
        """
        _timestamp(now, "now")
        with self._transaction() as connection:
            row = self._row(connection, interruption_id)
            if row is None:
                return False, "unknown_record"
            if row["state"] not in EXHAUSTED:
                return False, "not_exhausted"
            if row["cancel_requested"]:
                return False, "cancel_requested"
            if row["submitted_at"] is not None or row["queue_id"] is not None:
                return False, "possibly_sent"
            if row["budget_resets"] >= max_resets:
                return False, "reset_limit"
            if is_usage(row):
                target = "waiting_reset" if row["reset_at"] is not None and row["reset_at"] > now else "waiting_poll"
            else:
                target = "waiting_backoff"
            connection.execute(
                "UPDATE interruptions SET state=?, recovery_attempts=0, no_progress_count=0, "
                "retry_count=0, chain_continuations=0, budget_resets=budget_resets+1, "
                "last_error='budget_restored', next_retry_at=? WHERE interruption_id=?",
                (target, now, interruption_id))
            self._event(connection, now, "reset_budget", record=row, from_state=row["state"],
                        to_state=target, reason="budget_restored", actor=actor)
            return True, target

    def request_retry_now(self, interruption_id: str, now: float, *, actor: str = "gui") -> tuple:
        """Bring a waiting record's next check forward to now. Returns (accepted, detail).

        A schedule change and nothing else: it never touches a stored usage reset or
        any gate, and it never sends. On refusal `detail` names why; on acceptance it is
        the earliest time the watcher can actually act, which is later than now when a
        usage reset is still ahead.
        """
        _timestamp(now, "now")
        with self._transaction() as connection:
            row = self._row(connection, interruption_id)
            if row is None:
                return False, "unknown_record"
            if row["cancel_requested"]:
                return False, "cancel_requested"
            state = row["state"]
            if state not in WAITING:
                return False, ("finished" if state in TERMINAL else "observing" if state in OBSERVING
                               else "in_flight" if state in IN_FLIGHT else "claimed")
            connection.execute(
                "UPDATE interruptions SET next_retry_at=?, retry_now_count=retry_now_count+1 "
                "WHERE interruption_id=?", (now, interruption_id))
            self._event(connection, now, "retry_now", record=row, from_state=state, to_state=state,
                        reason="retry_now", actor=actor)
            return True, max(now, row["reset_at"] or 0)

    def hide_history(self, now: float, *, actor: str = "gui") -> dict:
        """Clear recovery history from view. Display only; never deletes a row.

        Hidden rows still count for every safety decision - the caps, the cooldown, the
        chain and duplicate detection - because the rows are the tombstones that stop a
        finished failure from being detected again. Anything that may still change is
        left visible: a record still running, and an unconfirmed submission that is
        still being reconciled.
        """
        _timestamp(now, "now")
        with self._transaction() as connection:
            hidden = kept = 0
            for value in connection.execute(
                    "SELECT * FROM interruptions WHERE history_hidden_at IS NULL").fetchall():
                row = _validated_record(dict(value))
                if row["state"] not in TERMINAL:
                    kept += 1
                    continue
                if row["state"] == "submission_unknown" and (
                        row["queue_id"] is not None
                        or now - (row["submitted_at"] or row["detected_at"]) < UNKNOWN_WINDOW):
                    kept += 1
                    continue
                connection.execute("UPDATE interruptions SET history_hidden_at=? WHERE interruption_id=?",
                                   (now, row["interruption_id"]))
                hidden += 1
            if hidden:
                self._event(connection, now, "hidden", actor=actor, value=hidden)
            return {"hidden": hidden, "kept": kept}

    # ------------------------------------------------------------ the watcher
    def heartbeat(self, now: float, *, pid: int, session_id: str, started_at: float, ok: bool,
                  engine_state: str, code_version: str) -> None:
        """The watcher's proof of life, written every tick."""
        _timestamp(now, "now")
        state = engine_state if engine_state in ENGINE_STATES else "unknown"
        with self._transaction() as connection:
            connection.execute(
                "INSERT INTO watcher_status VALUES (1,?,?,?,?,?,?,?) ON CONFLICT(singleton) DO UPDATE SET "
                "pid=excluded.pid, session_id=excluded.session_id, started_at=excluded.started_at, "
                "last_tick_at=excluded.last_tick_at, last_tick_ok=excluded.last_tick_ok, "
                "engine_state=excluded.engine_state, code_version=excluded.code_version",
                (int(pid), _short_text(str(session_id)[:64], "session_id", 64), _finite(started_at),
                 now, int(bool(ok)), state, _short_text(str(code_version)[:32], "code_version", 32)))

    def watcher_status(self) -> dict | None:
        with self._read() as connection:
            row = connection.execute("SELECT * FROM watcher_status WHERE singleton=1").fetchone()
        if row is None:
            return None
        row = dict(row)
        return {
            "pid": row["pid"] if isinstance(row["pid"], int) else None,
            "started_at": _finite(row["started_at"]),
            "last_tick_at": _finite(row["last_tick_at"]),
            "last_tick_ok": bool(row["last_tick_ok"]),
            "engine_state": row["engine_state"] if row["engine_state"] in ENGINE_STATES else "unknown",
            "code_version": row["code_version"] if isinstance(row["code_version"], str) else None,
        }

    # ------------------------------------------------------------- reporting
    def status_counts(self) -> dict[str, int]:
        with self._read() as connection:
            return {row[0]: row[1] for row in connection.execute(
                "SELECT state, count(*) FROM interruptions GROUP BY state") if row[0] in STATES}

    def statistics(self, since: float = 0.0, until: float | None = None) -> dict:
        """Exact, content-free counts over records detected in a period.

        One final outcome per record, so a late receipt moves a record from "unknown"
        to what really happened instead of counting twice. Hidden records are included:
        clearing history changes what is shown, not what happened.
        """
        until = float("inf") if until is None else until
        rows = [row for row in self.all_records() if since <= row["detected_at"] < until]
        outcome = {
            "recovered": "recovered", "completed_no_progress": "no_progress",
            "recovery_turn_failed": "recovery_failed", "outcome_unverified": "outcome_unverified",
            "handed_over": "handed_over", "stopped_by_user": "stopped_by_user",
            "cancelled": "cancelled", "superseded": "superseded", "superseded_by_user": "superseded",
            "retry_budget_exhausted": "exhausted", "no_progress_exhausted": "exhausted",
            "failed": "failed_terminal", "terminal_failure": "failed_terminal",
            "submission_unknown": "submission_unknown", "resumed": "delivered_legacy",
        }
        buckets = {name: 0 for name in sorted(set(outcome.values()))}
        by_category: dict[str, int] = {}
        for row in rows:
            bucket = outcome.get(row["state"])
            if bucket is not None:
                buckets[bucket] += 1
            by_category[row["category"]] = by_category.get(row["category"], 0) + 1
        denominator = sum(buckets[name] for name in (
            "recovered", "no_progress", "recovery_failed", "outcome_unverified", "exhausted",
            "failed_terminal", "submission_unknown"))
        waits = [row["first_queued_at"] - row["detected_at"] for row in rows
                 if row["first_queued_at"] is not None and row["first_queued_at"] >= row["detected_at"]]
        latencies = [row["outcome_at"] - row["first_queued_at"] for row in rows
                     if row["state"] == "recovered" and row["outcome_at"] is not None
                     and row["first_queued_at"] is not None and row["outcome_at"] >= row["first_queued_at"]]
        return {
            "interruptions_detected": len(rows),
            "continuations_submitted": sum(1 for row in rows if row["first_queued_at"] is not None),
            "pending": sum(1 for row in rows if row["state"] not in TERMINAL),
            "outcomes": buckets,
            "success_rate": (buckets["recovered"] / denominator) if denominator >= 5 else None,
            "success_denominator": denominator,
            "median_wait_seconds": _statistics.median(waits) if waits else None,
            "median_recovery_seconds": _statistics.median(latencies) if latencies else None,
            "by_category": by_category,
            "retry_now_requests": sum(row["retry_now_count"] for row in rows),
        }
