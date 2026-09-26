"""The state as an older release wrote it, opened without changing its schema.

A watcher from before this schema may still be running, and what it owns is read here rather
than upgraded: an upgrade under a running older watcher would rewrite rows it is writing. From
v0.6.11 that watcher can be a v0.6.x one, whose state is schema 3, as well as a v0.5 one.
"""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import sqlite3
from typing import Any, Iterator

from .. import machine
from ..machine import TERMINAL
from .errors import StoreError
from .policy import PolicyMixin
from .schema import SchemaMixin, _TABLES_V2, _TABLES_V3
from .session import SessionMixin
from .validate import _timestamp, _uuid, _validated_record


class LegacyStore:
    """A state an older watcher still owns - schema 1 or 2 (v0.5), or 3 (v0.6.0 to v0.6.10) -
    opened without changing it.

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
            tables = SessionMixin._tables(self._connection)
        except sqlite3.Error as exc:
            raise StoreError("Cannot open valid auto-resume state") from exc
        if (version, tables) not in ((1, _TABLES_V2), (2, _TABLES_V2), (3, _TABLES_V3)):
            self.close()
            raise StoreError("Not a state an older watcher owns")
        self.version = version
        # The states that older watcher knows, and those of them that are final.
        self._states = machine.V2_STATES if version < 3 else machine.STATES
        self._terminal = self._states & TERMINAL

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
                return PolicyMixin._read_settings(connection)
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
            connection.execute("INSERT INTO threads (thread_id, enabled) VALUES (?,?) ON CONFLICT(thread_id) "
                               "DO UPDATE SET enabled=excluded.enabled", (thread_id, int(enabled)))

    def cancel_thread(self, thread_id: str, now: float, **_ignored) -> None:
        """v0.5's cancel, exactly: disable the thread, cancel what was never sent, and
        mark what may have been sent so the old watcher withdraws it. A schema-3 watcher's
        cancel does the same, and names why a record it cancelled stopped, as it does itself."""
        _uuid(thread_id, "thread_id")
        _timestamp(now, "now")
        terminal = tuple(sorted(self._terminal))
        marks = ",".join("?" for _ in terminal)
        reason = ", last_error='user_cancelled'" if self.version >= 3 else ""
        with self._transaction() as connection:
            connection.execute("INSERT INTO threads (thread_id, enabled) VALUES (?,0) "
                               "ON CONFLICT(thread_id) DO UPDATE SET enabled=0", (thread_id,))
            connection.execute("UPDATE interruptions SET cancel_requested=1 WHERE thread_id=? AND "
                               "submitted_at IS NOT NULL AND state NOT IN (%s)" % marks,
                               (thread_id, *terminal))
            connection.execute("UPDATE interruptions SET state='cancelled', cancel_requested=1%s, "
                               "next_retry_at=? WHERE thread_id=? AND submitted_at IS NULL AND "
                               "state NOT IN (%s)" % (reason, marks), (now, thread_id, *terminal))

    def status_counts(self) -> dict:
        with self._transaction() as connection:
            return {row[0]: row[1] for row in connection.execute(
                "SELECT state, count(*) FROM interruptions GROUP BY state") if row[0] in self._states}

    def thread_of(self, interruption_id: str):
        with self._transaction() as connection:
            row = connection.execute("SELECT thread_id FROM interruptions WHERE interruption_id=?",
                                     (str(interruption_id),)).fetchone()
        return row[0] if row else None

    def disabled_threads(self) -> set:
        with self._transaction() as connection:
            return {row[0] for row in connection.execute("SELECT thread_id FROM threads WHERE enabled=0")}
