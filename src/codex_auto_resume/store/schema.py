"""The tables, as they are created today.

`tests/fixtures/schema.json` holds what these statements produce, on every path that reaches
them, and `tests/test_schema_golden.py` fails if a column, an index or the user_version moves.
"""
from __future__ import annotations

import sqlite3
from .columns import _EVENT_COLUMNS, _RECORD_COLUMNS, _WATCHER_COLUMNS
from .errors import StoreError


SCHEMA_VERSION = 3

_TABLES_V2 = {"settings", "threads", "interruptions"}

_TABLES_V3 = _TABLES_V2 | {"events", "watcher_status"}


class SchemaMixin:
    @staticmethod
    def _create_interruptions(connection) -> None:
        SchemaMixin._create_interruptions_named(connection, "interruptions")
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

    def schema_version(self) -> int:
        """The schema on disk now. A watcher that finds a newer one stops using it."""
        with self._read() as connection:
            return connection.execute("PRAGMA user_version").fetchone()[0]
