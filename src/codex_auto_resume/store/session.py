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
from .columns import NOTICE_SELECT, RECORD_SELECT
from .schema import MARKED, SCHEMA_VERSION, _TABLES_V4, marked, readable_from
from .validate import _flag, _timestamp, _uuid, _validated_notice, _validated_record, _validated_tier


class SessionMixin:
    def __init__(self, state_dir: Path, *, migrate: bool = False, check: bool = True,
                 clock=time.time):
        self.state_dir = Path(state_dir)
        self.path = self.state_dir / "state.sqlite"
        self.clock = clock
        self._connection: sqlite3.Connection | None = None
        self.migrated_from: int | None = None
        # How a record is read: every column, so a row a later version gave a column under this one fails its check and
        # hands the watcher over (RecordSchemaMismatch) - but in a later version's state marked readable from this one
        # (READABLE_FROM), opened as that, this version's own columns by name, and what that version added passed over.
        self._record_sql = "SELECT * FROM interruptions"
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
            if version > SCHEMA_VERSION and readable_from(self._connection, version) > SCHEMA_VERSION:
                raise StateFromNewerVersion(
                    "This state was written by a newer version of codex-auto-resume")
            if 1 <= version < SCHEMA_VERSION:
                if not migrate:
                    raise UpgradePending("Upgrade pending: an older watcher still owns the state")
                self._forensic_copy(version)
            # A current state is only read at open, so it takes no write lock: an open
            # must not wait behind - or fail because of - a watcher that is writing. Only
            # creating or upgrading the schema takes the write lock - and the mark (READABLE_FROM), written once, by
            # the watcher or a caller holding its mutex, on a current state that does not carry it yet.
            marking = migrate and version == SCHEMA_VERSION and not marked(self._connection)
            writing = version < SCHEMA_VERSION or marking
            opening = self._transaction if writing else self._read
            with opening() as connection:
                version = connection.execute("PRAGMA user_version").fetchone()[0]
                tables = self._tables(connection)
                if not tables and version == 0:
                    if was_present:
                        raise StoreError("Existing state is empty or uninitialized; refusing to reset")
                    self._create_schema(connection)
                elif version > SCHEMA_VERSION:
                    # A later version's state marked readable from this one (READABLE_FROM): used as it is, every table
                    # this version knows there, nothing upgraded and its version and mark left alone.
                    if readable_from(connection, version) > SCHEMA_VERSION:
                        raise StateFromNewerVersion(
                            "This state was written by a newer version of codex-auto-resume")
                    if not _TABLES_V4 <= tables:
                        raise StoreError("Unsupported or malformed state schema")
                elif 1 <= version < SCHEMA_VERSION:
                    if not migrate:
                        raise UpgradePending("Upgrade pending: an older watcher still owns the state")
                    self._migrate(connection, version)
                elif version != SCHEMA_VERSION or tables != _TABLES_V4:
                    raise StoreError("Unsupported or malformed state schema")
                current = connection.execute("PRAGMA user_version").fetchone()[0]
                newer = current > SCHEMA_VERSION
                self._validate_schema(connection, newer=newer)
                if newer:
                    self._record_sql = RECORD_SELECT
                if writing and current == SCHEMA_VERSION and not marked(connection):
                    connection.execute(MARKED)
                self._read_settings(connection)
                if check or self.migrated_from is not None:
                    if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                        raise StoreError("State integrity check failed")
                    for row in connection.execute("SELECT thread_id, enabled, tier FROM threads"):
                        _uuid(row["thread_id"], "thread_id")
                        _flag(row["enabled"], "thread enabled")
                        _validated_tier(row["tier"])
                    for row in connection.execute(self._record_sql):
                        _validated_record(dict(row))
                    for row in connection.execute(NOTICE_SELECT if newer else "SELECT * FROM notices"):
                        _validated_notice(dict(row))
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

    def _row(self, connection, interruption_id) -> dict | None:
        value = connection.execute(self._record_sql + " WHERE interruption_id=?", (interruption_id,)).fetchone()
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
