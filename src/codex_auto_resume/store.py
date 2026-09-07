"""Durable, fail-closed state owned exclusively by codex-auto-resume.

This module never opens Codex's databases. A transaction reserves an interruption
*before* any external command can start. An uncertain submission must not be
retried: only the engine may clear ``submitted_at`` after proving that no command
was launched. SQLite's FULL synchronous setting makes reservations durable.
"""

from __future__ import annotations

from contextlib import contextmanager
import math
from pathlib import Path
import re
import sqlite3
from typing import Any, Iterator
from uuid import UUID

from . import failures


SCHEMA_VERSION = 2
TERMINAL = frozenset({
    "resumed", "cancelled", "superseded", "failed", "submission_unknown",
    # Added with general transient recovery. Each one is a deliberate stop.
    "superseded_by_user", "retry_budget_exhausted", "no_progress_exhausted", "terminal_failure",
})
WAITING = frozenset({
    "waiting_reset", "waiting_poll", "waiting_for_app", "waiting_for_loaded_thread",
    "waiting_for_usage", "waiting_retry",
    # Transient failures wait on a bounded backoff, never on a usage reset.
    "waiting_backoff",
})
STATES = TERMINAL | WAITING | {"submitting", "queued"}
_KEY = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")
_MUTABLE = frozenset({
    "reset_at", "limit_type", "uncertain", "state", "retry_count", "next_retry_at",
    "resumed_at", "last_error", "queue_id", "submitted_at", "attempt_count",
    "cancel_requested", "recovery_attempts", "no_progress_count",
})
_RECORD_COLUMNS = (
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


class StoreError(RuntimeError):
    """Invalid or unavailable local state; automatic resumes must stop."""


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


def _validated_record(row: dict[str, Any]) -> dict[str, Any]:
    if set(row) != set(_RECORD_COLUMNS):
        raise StoreError("Invalid record schema")
    key = row["interruption_id"]
    if not isinstance(key, str) or not _KEY.fullmatch(key):
        raise StoreError("Invalid interruption_id")
    _uuid(row["thread_id"], "thread_id")
    _uuid(row["turn_id"], "turn_id")
    for field in ("completed_at", "detected_at", "next_retry_at"):
        _timestamp(row[field], field)
    for field in ("started_at", "reset_at", "resumed_at", "submitted_at"):
        _timestamp(row[field], field, nullable=True)
    for field in ("ordinal", "retry_count", "attempt_count", "recovery_attempts", "no_progress_count"):
        _integer(row[field], field)
    if row["category"] not in failures.CATEGORIES:
        raise StoreError("Invalid failure category")
    for field in ("uncertain", "cancel_requested"):
        row[field] = _flag(row[field], field)
    _short_text(row["limit_type"], "limit_type", 160, nullable=True)
    _short_text(row["last_error"], "last_error", 240, nullable=True)
    if not isinstance(row["state"], str) or row["state"] not in STATES:
        raise StoreError("Unknown record state")
    if row["marker"] != f"[codex-auto-resume:{key}]":
        raise StoreError("Invalid record marker")
    if row["queue_id"] is not None:
        _uuid(row["queue_id"], "queue_id")
    if row["state"] in {"submitting", "queued"} and row["submitted_at"] is None:
        raise StoreError("Missing submission timestamp")
    return row


class Store:
    def __init__(self, state_dir: Path):
        self.state_dir = Path(state_dir)
        self.path = self.state_dir / "state.sqlite"
        self._connection: sqlite3.Connection | None = None
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
            with self._transaction() as connection:
                version = connection.execute("PRAGMA user_version").fetchone()[0]
                tables = {
                    row[0] for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                    )
                }
                if not tables and version == 0:
                    if was_present:
                        raise StoreError("Existing state is empty or uninitialized; refusing to reset")
                    self._create_schema(connection)
                elif tables != {"settings", "threads", "interruptions"}:
                    raise StoreError("Unsupported or malformed state schema")
                elif version == 1:
                    # In-place upgrade. Pending interruptions must survive an update of
                    # this tool, so the rows are kept and only new columns are added.
                    self._migrate_1_to_2(connection)
                elif version != SCHEMA_VERSION:
                    raise StoreError("Unsupported or malformed state schema")
                self._validate_schema(connection)
                if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                    raise StoreError("State integrity check failed")
                self._read_settings(connection)
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

    @staticmethod
    def _create_schema(connection: sqlite3.Connection) -> None:
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
        connection.execute("""CREATE TABLE interruptions (
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
        connection.execute("CREATE INDEX interruptions_thread ON interruptions(thread_id)")
        connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")

    @staticmethod
    def _migrate_1_to_2(connection: sqlite3.Connection) -> None:
        """Add the general-recovery columns to an existing schema-1 database.

        Runs inside the caller's transaction, so a crash mid-upgrade leaves the old
        schema intact rather than a half-migrated one.
        """
        found = {row[1] for row in connection.execute("PRAGMA table_info(interruptions)")}
        for name, definition in _SCHEMA_2_COLUMNS:
            if name not in found:
                connection.execute(f"ALTER TABLE interruptions ADD COLUMN {name} {definition}")
        connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")

    @staticmethod
    def _validate_schema(connection: sqlite3.Connection) -> None:
        expected = {
            "settings": {"singleton", "enabled", "armed_at", "poll_seconds"},
            "threads": {"thread_id", "enabled"},
            "interruptions": set(_RECORD_COLUMNS),
        }
        for table, columns in expected.items():
            information = list(connection.execute(f"PRAGMA table_info({table})"))
            found = {row[1] for row in information}
            if found != columns:
                raise StoreError("Malformed state schema")
            primary = {row[1] for row in information if row[5] == 1}
            primary_name = {"settings": "singleton", "threads": "thread_id", "interruptions": "interruption_id"}[table]
            if primary != {primary_name} or any(row[5] > 1 for row in information):
                raise StoreError("Malformed state primary key")
        if connection.execute("SELECT 1 FROM sqlite_master WHERE type IN ('trigger', 'view') LIMIT 1").fetchone():
            raise StoreError("Unexpected state schema objects")

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
        if self._connection is None:
            raise StoreError("Store is closed")
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
        with self._transaction() as connection:
            return self._read_settings(connection)

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
        with self._transaction() as connection:
            return self._thread_enabled(connection, thread_id)

    def set_thread_enabled(self, thread_id: str, enabled: bool) -> None:
        _uuid(thread_id, "thread_id")
        if not isinstance(enabled, bool):
            raise StoreError("enabled must be boolean")
        with self._transaction() as connection:
            connection.execute(
                "INSERT INTO threads VALUES (?,?) ON CONFLICT(thread_id) DO UPDATE SET enabled=excluded.enabled",
                (thread_id, int(enabled)),
            )

    def register(self, record: dict[str, Any], now: float, *,
                 state: str = "waiting_reset", next_retry_at: float | None = None) -> bool:
        """Create the record WITH its real schedule in one transaction.

        Writing the state/next_retry_at in a second transaction would leave a
        mis-scheduled record behind if the process died between the two commits.
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
        row = _validated_record({
            **record, "detected_at": now, "state": state, "retry_count": 0,
            "next_retry_at": now if next_retry_at is None else next_retry_at,
            "resumed_at": None, "last_error": None,
            "marker": f"[codex-auto-resume:{record['interruption_id']}]", "queue_id": None,
            "submitted_at": None, "attempt_count": 0, "cancel_requested": False,
            "recovery_attempts": 0, "no_progress_count": 0,
        })
        with self._transaction() as connection:
            existing = connection.execute(
                "SELECT * FROM interruptions WHERE interruption_id=?", (row["interruption_id"],)
            ).fetchone()
            if existing is not None:
                existing_record = _validated_record(dict(existing))
                if any(existing_record[field] != row[field] for field in
                       ("thread_id", "turn_id", "completed_at", "started_at", "ordinal")):
                    raise StoreError("Interruption identity collision")
                return False
            columns = ",".join(_RECORD_COLUMNS)
            placeholders = ",".join("?" for _ in _RECORD_COLUMNS)
            connection.execute(
                f"INSERT INTO interruptions ({columns}) VALUES ({placeholders})",
                tuple(row[field] for field in _RECORD_COLUMNS),
            )
            return True

    def get(self, interruption_id: str) -> dict[str, Any] | None:
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT * FROM interruptions WHERE interruption_id=?", (interruption_id,)
            ).fetchone()
            return None if row is None else _validated_record(dict(row))

    def all_records(self) -> list[dict[str, Any]]:
        with self._transaction() as connection:
            return [_validated_record(dict(row)) for row in connection.execute(
                "SELECT * FROM interruptions ORDER BY detected_at, interruption_id"
            )]

    def pending(self) -> list[dict[str, Any]]:
        return [row for row in self.all_records() if row["state"] not in TERMINAL]

    def update(self, interruption_id: str, **changes: Any) -> None:
        if not changes or not set(changes) <= _MUTABLE:
            raise StoreError("Invalid record update")
        with self._transaction() as connection:
            old = connection.execute(
                "SELECT * FROM interruptions WHERE interruption_id=?", (interruption_id,)
            ).fetchone()
            if old is None:
                raise StoreError("Unknown interruption")
            old_record = _validated_record(dict(old))
            row = _validated_record({**old_record, **changes})
            if old_record["state"] in TERMINAL and row["state"] != old_record["state"]:
                if not (old_record["state"] == "submission_unknown"
                        and row["state"] in {"queued", "resumed", "cancelled", "superseded", "failed"}):
                    raise StoreError("Cannot reactivate terminal interruption")
            if old_record["submitted_at"] is not None and row["submitted_at"] is None:
                if not (old_record["state"] == "submitting" and row["state"] in {"waiting_retry", "failed"}
                        and old_record["queue_id"] is None):
                    raise StoreError("Cannot clear possible submission")
            assignments = ",".join(f"{column}=?" for column in changes)
            connection.execute(
                f"UPDATE interruptions SET {assignments} WHERE interruption_id=?",
                (*[row[column] for column in changes], interruption_id),
            )

    def reserve(self, interruption_id: str, now: float) -> bool:
        _timestamp(now, "now")
        with self._transaction() as connection:
            settings = self._read_settings(connection)
            value = connection.execute(
                "SELECT * FROM interruptions WHERE interruption_id=?", (interruption_id,)
            ).fetchone()
            if value is None:
                return False
            row = _validated_record(dict(value))
            if (not settings["enabled"] or not self._thread_enabled(connection, row["thread_id"])
                    or row["state"] not in WAITING or row["cancel_requested"]
                    or row["submitted_at"] is not None or row["next_retry_at"] > now
                    or (row["reset_at"] is not None and row["reset_at"] > now)):
                return False
            connection.execute(
                "UPDATE interruptions SET state='submitting', attempt_count=attempt_count+1, submitted_at=? "
                "WHERE interruption_id=?", (now, interruption_id),
            )
            return True

    def restore_budget(self, interruption_id: str, now: float) -> bool:
        """Return an exhausted interruption to the ordinary waiting state.

        `update` refuses to reactivate a terminal record, and that guard is what stops a
        finished, cancelled or uncertainly-submitted recovery from being restarted by a
        stray write. Running out of attempts is the one stop a person is allowed to undo,
        so it gets its own operation rather than a hole in the guard: the two exhausted
        states are the only ones accepted here, and a record that was cancelled or may
        already have been sent is refused even from those.

        This clears the budget and nothing else. The record re-enters the queue as a
        candidate; every gate the watcher applies still applies.
        """
        _timestamp(now, "now")
        with self._transaction() as connection:
            value = connection.execute(
                "SELECT * FROM interruptions WHERE interruption_id=?", (interruption_id,)
            ).fetchone()
            if value is None:
                return False
            row = _validated_record(dict(value))
            if (row["state"] not in {"retry_budget_exhausted", "no_progress_exhausted"}
                    or row["cancel_requested"] or row["submitted_at"] is not None
                    or row["queue_id"] is not None):
                return False
            connection.execute(
                "UPDATE interruptions SET state='waiting_backoff', recovery_attempts=0, "
                "no_progress_count=0, last_error=NULL, next_retry_at=? WHERE interruption_id=?",
                (now, interruption_id),
            )
            return True

    def cancel(self, thread_id: str, now: float) -> None:
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
                    connection.execute(
                        "UPDATE interruptions SET cancel_requested=1 WHERE interruption_id=?", (row["interruption_id"],)
                    )
                else:
                    connection.execute(
                        "UPDATE interruptions SET state='cancelled', cancel_requested=1, next_retry_at=? "
                        "WHERE interruption_id=?", (now, row["interruption_id"]),
                    )

    def status_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for row in self.all_records():
            counts[row["state"]] = counts.get(row["state"], 0) + 1
        return counts
