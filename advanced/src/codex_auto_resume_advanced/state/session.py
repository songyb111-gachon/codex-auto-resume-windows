# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""advanced.sqlite: where it is, opening it, and the transaction everything is written in.

It lives in config/advanced/ (config.Paths.advanced_dir), a directory of its own with the same
provenance marker config/ carries, because the core state cannot hold any of it: the core store
refuses a state.sqlite with one table more than its own (store/session.py), and settings.json
drops every key it does not define on the next save (settings.py). The marker is what lets core
purge the directory without knowing a single file in it (config.owned_advanced_files).

The same rules as core's store: no link anywhere on the way, nothing outside the home, one
connection per process opened the first time it is needed, BEGIN IMMEDIATE for every write and
synchronous=FULL, and a file whose tables, columns or version are not exactly these is refused
rather than repaired - but for a file of an earlier version, exactly as that version made it, which
is brought to this version when it is opened (schema.UPGRADE_FROM_1, UPGRADE_FROM_2, ADD_RESETS, ... and from v0.6.19
UPGRADE_TO_V019), a read's
opening too: it is the one write a read makes, and it adds a column and tables and changes no row - and for a file of
a later version marked readable from this one (schema.READABLE_FROM, v0.6.17), which is used as it is, nothing
upgraded and nothing taken away. Reading never creates the file: an
installation where nothing was ever turned on has none, and every question about it has the
answer "off".

The one connection serves every thread of its process - the MCP server asks P9 on a thread of
its own, the watcher's tray popup calls the plug its engine thread holds - so it is not bound to
the thread that opened it, and a lock gives each transaction the connection whole. Bound, it was
whichever thread's opened it first, and every other thread's disarm and badge failed.
"""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import sqlite3
import threading
import time

from codex_auto_resume import config, machine
from codex_auto_resume.domain import ids

from .schema import (ADD_RESETS, ATTACHED, FILE_NAME, SCHEMA_VERSION, STATEMENTS, TABLES, TABLES_V1,
                     TABLES_V2, TABLES_V3, TABLES_V3_BEFORE_RESETS, TABLES_V4, TABLES_V5, UPGRADE_FROM_1,
                     UPGRADE_FROM_2, UPGRADE_FROM_3, UPGRADE_FROM_4, UPGRADE_FROM_5, STAGE4_VERSION,
                     TABLES_BEFORE_STAGE4, UPGRADE_TO_STAGE4, WINDOW_CHOICES, WINDOW_FOLLOWERS, WINDOW_LEADER,
                     WINDOW_OFF, WINDOW_ON, FREE_OPTIONS, MARKED, READABLE_FROM, holds, names_checked,
                     readable_from, TABLES_V7, UPGRADE_TO_V019, FREE_WORDINGS, wordings_checked)


class StateError(RuntimeError):
    """The advanced state cannot be used. A static reason only, never a path or a value."""


class StaleGeneration(StateError):
    """An arming request made against a generation that is no longer the current one."""


def _timestamp(value, name):
    if not machine.epoch(value, *machine.EPOCH_STORE):
        raise StateError("invalid %s" % name)
    return float(value)


def _thread(value):
    if ids.uuid_problem(value) is not None:
        raise StateError("invalid thread id")
    return value


def _key(value, name):
    """An interruption id, or a record id in the same shape: 64 hex digits."""
    if not ids.is_interruption_id(value):
        raise StateError("invalid %s" % name)
    return value


def _word(value, words, name):
    """`value` if it is one of `words` (a StrEnum), else a refusal: a decision never stores a
    word it does not know."""
    try:
        return words(value)
    except ValueError:
        raise StateError("invalid %s" % name) from None


class SessionMixin:
    def __init__(self, paths, *, registry, clock=time.time):
        self.paths = paths
        self.registry = registry
        self.directory = Path(paths.advanced_dir)
        self.path = self.directory / FILE_NAME
        self.clock = clock
        self._connection = None
        # Held for the whole of a transaction, and while the connection is opened or closed.
        # Re-entrant, since a transaction opens the connection it runs on.
        self._lock = threading.RLock()

    # ------------------------------------------------------------------ the file
    def exists(self) -> bool:
        """Whether the file is there. False for a link or a junction - `is_symlink` is False for a
        junction (config.is_link) - since that is never ours to open."""
        try:
            return (self.path.is_file() and not config.is_link(self.path)
                    and not config.is_link(self.directory))
        except OSError:
            return False

    def _directory(self) -> None:
        """config/advanced/, made and marked as ours, or a refusal. The marker is written before
        anything else is, so the directory is never ours without saying so."""
        self.paths.ensure()
        directory = self.directory
        if config.is_link(directory) or (directory.exists() and not self.paths.confined(directory)):
            raise StateError("the advanced state directory is a link or escapes the home")
        directory.mkdir(exist_ok=True)
        marker = directory / config.OWNER_MARKER
        self._checked()
        if not marker.exists():
            marker.write_text(config.OWNER_TEXT, encoding="utf-8")

    def _checked(self) -> None:
        """The refusals `_directory` makes, and nothing it writes: what a read looks at."""
        if config.is_link(self.directory) or not self.paths.confined(self.directory):
            raise StateError("the advanced state directory is a link or escapes the home")
        if config.is_link(self.path):
            raise StateError("the advanced state is a link")

    def _open(self, *, create: bool):
        """The connection, opened and checked the first time. None when the file is not there
        and `create` is False."""
        connection = self._connection
        if connection is not None:
            # Read without the lock: the claim attaches the file from core's transaction, which
            # must not wait for a transaction of this connection's on another thread.
            return connection
        with self._lock:
            if self._connection is not None:
                return self._connection
            return self._opened(create)

    def _opened(self, create):
        if not create and not self.exists():
            return None
        try:
            # A read makes nothing: not the directory, not its marker, not the schema.
            self._directory() if create else self._checked()
            was_present = self.path.exists()
            connection = sqlite3.connect(self.path, timeout=10, isolation_level=None,
                                         check_same_thread=False)
        except (OSError, sqlite3.Error) as exc:
            raise StateError("cannot open the advanced state") from exc
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA trusted_schema=OFF")
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA synchronous=FULL")
            connection.execute("BEGIN IMMEDIATE" if create else "BEGIN")
            try:
                prepared = self._prepare(connection, was_present, create)
                connection.execute("COMMIT")
            except BaseException:
                connection.execute("ROLLBACK")
                raise
        except (sqlite3.Error, StateError) as exc:
            connection.close()
            if isinstance(exc, StateError):
                raise
            raise StateError("cannot open the advanced state") from exc
        if not prepared:
            connection.close()
            return None
        self._connection = connection
        return connection

    @staticmethod
    def _tables(connection) -> dict:
        names = [row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        return {name: tuple(row[1] for row in connection.execute("PRAGMA table_info(%s)" % name))
                for name in names}

    def _prepare(self, connection, was_present, create) -> bool:
        """Whether the file is this schema, made now if `create` and there is none. False for a
        file with no schema that a read found: an empty one - what a crash between making the
        file and writing its schema leaves - is nothing turned on, and a read does not finish
        making it, as core's store does not initialise an empty state.sqlite it opens."""
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        tables = self._tables(connection)
        if version == 0 and not tables:
            if not create:
                return False
            if was_present and self.path.stat().st_size:
                raise StateError("the advanced state is empty or uninitialized; refusing to reset it")
            for statement in STATEMENTS:
                connection.execute(statement)
            tables = self._tables(connection)
            version = SCHEMA_VERSION
        if version > SCHEMA_VERSION:
            # A later version's file (v0.6.17): used where it is marked readable from this version - every table this
            # version knows holding its columns, first - with nothing upgraded and its version and mark left as they
            # are; refused as newer otherwise, every capability off and nothing written (schema.READABLE_FROM).
            if readable_from(connection, version) > SCHEMA_VERSION:
                raise StateError("the advanced state was written by a newer version")
            if not holds(tables, TABLES):
                raise StateError("unsupported or malformed advanced state")
        else:
            for old, shape, steps in ((1, TABLES_V1, UPGRADE_FROM_1), (2, TABLES_V2, UPGRADE_FROM_2),
                                      (3, TABLES_V3_BEFORE_RESETS, ADD_RESETS), (3, TABLES_V3, UPGRADE_FROM_3),
                                      (4, TABLES_V4, UPGRADE_FROM_4), (5, TABLES_V5, UPGRADE_FROM_5),
                                      (STAGE4_VERSION - 1, TABLES_BEFORE_STAGE4, UPGRADE_TO_STAGE4),
                                      # v0.6.19 (the groundwork): version 8, readable from 7.
                                      (STAGE4_VERSION, TABLES_V7, UPGRADE_TO_V019)):
                if version == old and tables == shape:
                    for statement in steps:
                        connection.execute(statement)
                    tables = self._tables(connection)
                    version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version != SCHEMA_VERSION or tables != TABLES:
                raise StateError("unsupported or malformed advanced state")
            # v0.6.17: `options` freed of the CHECK on its names, and the file marked, its version kept - so v0.6.16,
            # which compares columns alone, reads it as before. Each only while it is still to do.
            if names_checked(connection):
                for statement in FREE_OPTIONS:
                    connection.execute(statement)
            elif readable_from(connection, version) != READABLE_FROM:
                connection.execute(MARKED)
            # v0.6.19: `wordings` freed of the CHECK on its keys the same way, once (schema.FREE_WORDINGS).
            if wordings_checked(connection):
                for statement in FREE_WORDINGS:
                    connection.execute(statement)
        if connection.execute("SELECT count(*) FROM meta").fetchone()[0] != 1:
            raise StateError("malformed advanced state")
        self._carry_windows(connection)
        return True

    def _carry_windows(self, connection) -> None:
        """The window switches carried over, once (v0.6.16 final): before it, the usage meter's pair decided whether
        anything warned, wrapped up or stopped for a window; now Wrap up near a limit and Stop near a limit each have a
        pair of their own. Each of their switches with no row yet is written as the meter's switch for that window stands
        - off where the person had it off, on otherwise - so nothing acts after the update on a window that was off
        before it. Once written, a row is never written here again, so the meter's switch decides only its warnings from
        then on; a new file gets the four rows as it is made. Only a switch this registry's capability offers, in the
        opening's own transaction - the one write a read makes, as an upgrade is - with no generation moved: what any
        capability does is unchanged by it."""
        wanted = []
        for capability in WINDOW_FOLLOWERS:
            definition = self.registry.get(capability)
            wanted += [(capability, choice) for choice in WINDOW_CHOICES
                       if definition is not None and definition.option(choice) is not None]
        if not wanted:
            return
        held = {(row[0], row[1]): row[2] for row in connection.execute(
            "SELECT capability, choice, value FROM options WHERE choice IN (?, ?)", WINDOW_CHOICES)}
        for capability, choice in wanted:
            if (capability, choice) in held:
                continue
            value = held.get((WINDOW_LEADER, choice), WINDOW_ON)
            connection.execute("INSERT INTO options (capability, choice, value) VALUES (?,?,?)",
                               (capability, choice, value if value in (WINDOW_ON, WINDOW_OFF) else WINDOW_ON))

    def close(self) -> None:
        with self._lock:
            if self._connection is not None:
                self._connection.close()
                self._connection = None

    # ---------------------------------------------------------------- transactions
    @contextmanager
    def _transaction(self, *, create: bool = True):
        """A write transaction, or None when the file is not there and nothing asked to make it."""
        with self._lock:
            connection = self._open(create=create)
            if connection is None:
                yield None
                return
            with self._begin(connection, "BEGIN IMMEDIATE"):
                yield connection

    @contextmanager
    def _read(self):
        """One consistent snapshot, or None when there is no file to read."""
        with self._lock:
            connection = self._open(create=False)
            if connection is None:
                yield None
                return
            with self._begin(connection, "BEGIN"):
                yield connection

    @staticmethod
    @contextmanager
    def _begin(connection, statement):
        try:
            connection.execute(statement)
            yield
            connection.execute("COMMIT")
        except BaseException as exc:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            if isinstance(exc, sqlite3.Error):
                raise StateError("advanced state transaction failed") from exc
            raise

    def _now(self, at) -> float:
        return _timestamp(self.clock() if at is None else at, "time")

    # ---------------------------------------------------------------- the one claim
    def attach(self, connection) -> bool:
        """Attach this file to `connection` - core's, inside its one claim - as ATTACHED.

        Once per connection: SQLite takes an ATTACH inside a transaction, but not the DETACH of
        a file the transaction has used, so it stays attached for the connection's life, and
        from then on every write transaction core begins on it holds this file's lock too.
        The file is opened and checked on its own connection first, so a file that would be
        refused is never attached; one that is not there is not made, and False says so.

        The statement names the file rather than binding it: core's claim lets an ATTACH on
        only once it has read which file it is (store/ledger.py, `_attachable`), and a bound
        name is not there to read."""
        if self._open(create=False) is None:
            return False
        if ATTACHED not in [row[1] for row in connection.execute("PRAGMA database_list")]:
            connection.execute("ATTACH DATABASE '%s' AS %s" % (str(self.path).replace("'", "''"), ATTACHED))
        return True
