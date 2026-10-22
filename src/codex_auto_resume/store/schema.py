"""The tables, as they are created today.

`tests/fixtures/schema.json` holds what these statements produce, on every path that reaches
them, and `tests/test_schema_golden.py` fails if a column, an index or the user_version moves.
"""
from __future__ import annotations

import sqlite3
from .columns import (_EVENT_COLUMNS, _NOTICE_COLUMNS, _RECORD_COLUMNS, _SETTINGS_COLUMNS,
                      _THREAD_COLUMNS, _WATCHER_COLUMNS)
from .errors import StoreError


SCHEMA_VERSION = 5

_TABLES_V2 = {"settings", "threads", "interruptions"}

_TABLES_V3 = _TABLES_V2 | {"events", "watcher_status"}

_TABLES_V4 = _TABLES_V3 | {"notices"}

# Schema 5 (v0.6.15-beta) adds two columns and no table.
_TABLES_V5 = _TABLES_V4

# Readable from (v0.6.18, as advanced.sqlite has been since v0.6.17): PRAGMA application_id holds MARK, the schema that
# wrote the mark (bits 8-15) and the oldest version whose reader may use the state (bits 0-7). A later version that adds
# only what an older reader passes over - a table, a column at the end of a table, with a default - writes its own schema
# and keeps the older number there, and that reader uses the state instead of refusing it as newer: every table it knows
# holding at least its columns, first, nothing upgraded and the version and the mark left as they are. A state marked
# newer than the reader is refused as before, and so is one whose mark another schema wrote - a later version that moved
# the schema without writing a mark of its own - or that has no mark: it is readable from its own version alone, as
# every state v0.6.17 and earlier wrote is. Unlike advanced.sqlite's mark, the schema it was written for is in it, so a
# version bump that forgets the mark fails closed.
# The mark keeps schema 5: a release before v0.6.18 reads no mark, so a schema 6 - however readable - would be refused
# there as newer. Kept at 5, it is read there as its own; the mark serves every version from v0.6.18 on.
READABLE_FROM = 5
# "CA" in the high half of SQLite's application id - advanced.sqlite's convention.
MARK = 0x43410000
MARKED = "PRAGMA application_id=%d" % (MARK | SCHEMA_VERSION << 8 | READABLE_FROM)


def readable_from(connection, version: int) -> int:
    """The oldest version whose reader may use the state `connection` holds, at user_version `version`: the mark's,
    where the mark was written for `version`, or `version` itself."""
    found = connection.execute("PRAGMA application_id").fetchone()[0]
    return found & 0xFF if found & 0xFFFF0000 == MARK and (found >> 8) & 0xFF == version else version


def marked(connection) -> bool:
    """Whether the state carries this version's mark (MARKED) already: a current state is marked once."""
    return connection.execute("PRAGMA application_id").fetchone()[0] == MARK | SCHEMA_VERSION << 8 | READABLE_FROM


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
        # Made the way a migration makes it, so an upgraded state and a fresh one are the same
        # file (tests/test_schema_golden.py).
        cls._add_schema_4(connection)
        cls._add_schema_5(connection)
        connection.execute("PRAGMA user_version=5")

    @staticmethod
    def _validate_schema(connection: sqlite3.Connection, *, newer: bool = False) -> None:
        """Every table exactly as this version makes it - or, in a later version's state marked readable from this one
        (`newer`), holding at least this version's columns, first: what that version added after them is passed over."""
        expected = {
            "settings": (set(_SETTINGS_COLUMNS), "singleton"),
            "threads": (set(_THREAD_COLUMNS), "thread_id"),
            "interruptions": (set(_RECORD_COLUMNS), "interruption_id"),
            "events": (set(_EVENT_COLUMNS), "event_id"),
            "watcher_status": (set(_WATCHER_COLUMNS), "singleton"),
            "notices": (set(_NOTICE_COLUMNS), "interruption_id"),
        }
        for table, (columns, primary_name) in expected.items():
            information = list(connection.execute(f"PRAGMA table_info({table})"))
            found = {row[1] for row in information}
            if newer:
                found = {row[1] for row in information[:len(columns)]}
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

    def readable_from(self) -> int:
        """The oldest version whose reader may use the state on disk now (READABLE_FROM): a watcher that finds a newer
        schema stops using it only where this is newer too."""
        with self._read() as connection:
            return readable_from(connection, connection.execute("PRAGMA user_version").fetchone()[0])
