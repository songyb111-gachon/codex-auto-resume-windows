"""Bringing an older state forward.

Only a caller holding the watcher's single-instance mutex may run these, and a copy of the
file is taken first (`_forensic_copy`). An upgraded database must end up indistinguishable
from a fresh one, which the schema golden holds it to.
"""
from __future__ import annotations

import sqlite3
from ..machine import STATES, TERMINAL
from .columns import (_SCHEMA_2_COLUMNS, _SCHEMA_3_COLUMNS, _SCHEMA_4_COLUMNS, _V2_COLUMNS,
                      _V3_COLUMNS)
from .errors import StoreError
from .schema import _TABLES_V2, _TABLES_V3
from .session import SessionMixin


class MigrationsMixin:
    @staticmethod
    def _migrate_1_to_2(connection: sqlite3.Connection) -> None:
        """Add the general-recovery columns to an existing schema-1 database."""
        if SessionMixin._tables(connection) != _TABLES_V2:
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

    @staticmethod
    def _add_schema_4(connection: sqlite3.Connection) -> None:
        """Schema 4's columns and its notices table. Every column is empty, or 0, on every row it
        is added to, so no record, conversation or switch means anything it did not mean in v3."""
        for table, name, definition in _SCHEMA_4_COLUMNS:
            found = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
            if name not in found:
                connection.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")
        connection.execute("""CREATE TABLE IF NOT EXISTS notices (
            interruption_id TEXT PRIMARY KEY,
            thread_id TEXT NOT NULL,
            category TEXT NOT NULL,
            raised_at REAL NOT NULL,
            seen_at REAL
        )""")

    def _migrate_3_to_4(self, connection: sqlite3.Connection) -> None:
        if self._tables(connection) != _TABLES_V3:
            raise StoreError("Unsupported or malformed state schema")
        shapes = {"interruptions": set(_V3_COLUMNS), "threads": {"thread_id", "enabled"},
                  "settings": {"singleton", "enabled", "armed_at", "poll_seconds"}}
        for table, columns in shapes.items():
            if {row[1] for row in connection.execute(f"PRAGMA table_info({table})")} != columns:
                raise StoreError("Malformed state schema")
        self._add_schema_4(connection)
        # No backfill: nothing is postponed, held, tiered or only observed until a person says so.
        # One `migrated` entry per upgrade, however many steps it took: an upgrade from schema 2
        # has written its own already (_migrate_2_to_3).
        if self.migrated_from == 3:
            count = connection.execute("SELECT count(*) FROM interruptions").fetchone()[0]
            self._event(connection, self.clock(), "migrated", value=count)
        connection.execute("PRAGMA user_version=4")

    def _migrate(self, connection, version: int) -> None:
        """A linear chain with literal targets: 1 -> 2 -> 3 -> 4, each checking its source."""
        self.migrated_from = version
        if version == 1:
            self._migrate_1_to_2(connection)
            version = 2
        if version == 2:
            self._migrate_2_to_3(connection)
            version = 3
        if version == 3:
            self._migrate_3_to_4(connection)
