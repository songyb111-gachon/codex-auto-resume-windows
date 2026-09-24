"""One connection to the state, opened and closed.

The file, the transaction it is read and written in, and the moment it is opened at. Every
other part of the store asks this one for a connection.
"""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import sqlite3
import time
from typing import Any, Iterator
from .errors import StateFromNewerVersion, StoreError, UpgradePending
from .schema import SCHEMA_VERSION, _TABLES_V3
from .validate import _flag, _timestamp, _uuid, _validated_record


class SessionMixin:
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
        value = connection.execute("SELECT * FROM interruptions WHERE interruption_id=?", (interruption_id,)).fetchone()
        return None if value is None else _validated_record(dict(value))

    def _now(self, at) -> float:
        return _timestamp(self.clock() if at is None else at, "now")

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
