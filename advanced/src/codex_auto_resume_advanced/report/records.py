# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""This PC's own records, read for a compatibility report - and never written, migrated or locked.

The same files codex-compat-reporter 1.5.0 reads, read the same way (its state_rows, paid_claims,
log_lines, installed_codex and progress_items), so that the two write the same report of the same
records (advanced/tests/test_advanced_report_records.py holds them to what 1.5.0 wrote):

    config/state.sqlite           the 17 columns the report needs, the count of records hidden
                                  with Clear history, and the recovery switch (a pause)
    config/advanced/advanced.sqlite
                                  the spend ledger's interruption_id and at, its count, its oldest
                                  unit and how many units SQLite ever gave it (sqlite_sequence)
    logs/auto-resume.log and its five rotated copies
                                  the engine lines and their local times
    config/compatibility.json     the watcher's own report, through compatio.reader_view only
    Codex's history               how many items of four kinds a recovered turn made, through core's
                                  read-only opener (codex/schema.py `_db`): counts, never text

Never through the Store, which makes its directory and opens the file writable: each database is
opened `mode=ro`, with query_only on, trusted_schema off and a three-second timeout, so nothing is
written beside it - no -journal, no folder - and nothing is migrated. A link, a reparse point or a
path out of the home is refused. A schema newer than this reads is refused, not read as today's.

A refusal is one closed code (`ReadRefusal`) and nothing else: never an id, a path, a login or
text. What the records say is evidence.py's, which is pure. The one import of the rest of the
advanced package is the ledger's own schema and bounds, taken where they are written (state/),
not copied, and only when the ledger is read.
"""
from __future__ import annotations

from contextlib import contextmanager
from enum import StrEnum
from pathlib import Path
import sqlite3
import time

from codex_auto_resume import config
from codex_auto_resume.domain import ids
from codex_auto_resume.logbook import BACKUP_COUNT

from . import evidence

# The state database's user_versions read, and no others: 3 (v0.6.0 to v0.6.11-alpha) and 4 (from
# v0.6.11-beta; store/schema.py SCHEMA_VERSION). Schema 4 added columns and changed none of these.
STATE_SCHEMAS = (3, 4)
# The columns read from the state, in schema 3 and 4 alike, and nothing else. thread_id and
# recovery_turn_id key only the progress count; history_hidden_at only leaves hidden records out;
# interruption_id, recovery_client_id and last_claim_at only tell a record another route carried.
COLUMNS = ("thread_id", "category", "state", "last_error", "detected_at", "resumed_at", "outcome_at",
           "submitted_at", "recovery_turn_id", "recovery_turn_status", "gate_eval", "reset_at",
           "limit_type", "history_hidden_at", "interruption_id", "recovery_client_id", "last_claim_at")
SPEND = ("interruption_id", "at")                # the spend ledger's columns read, and nothing else
TIMEOUT = 3                                      # seconds a database may be busy before it is refused
# The product rotates its log at 1 MB (logbook.py MAX_BYTES); a file many times that is not one it wrote.
MAX_LOG_BYTES = 8 * 1024 * 1024
# The one question asked of Codex's history: how many items of each kind one turn made.
PROGRESS_SQL = ("SELECT item_type, count(*) FROM thread_items WHERE thread_id=? AND turn_id=? "
                "GROUP BY item_type")
_BUSY = frozenset({sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED})


class ReadRefusal(StrEnum):
    """Why no report could be read from this PC's records."""
    NO_STATE = "no_state"                        # the watcher has written no records yet
    STATE_NEWER = "state_newer"                  # a newer version wrote them
    STATE_OLDER = "state_older"                  # a schema before v0.6.0's, or none
    STATE_UNREADABLE = "state_unreadable"        # damaged, a link, out of the home, or a column gone
    STATE_BUSY = "state_busy"                    # locked longer than TIMEOUT
    LEDGER_NEWER = "ledger_newer"
    LEDGER_UNREADABLE = "ledger_unreadable"      # so another route's records could not be told apart
    NO_ENGINE_VERSION = "no_engine_version"      # neither the watcher's report nor the log names one
    VERSION_INVALID = "version_invalid"          # not a Codex version in the product's one spelling
    TOO_MANY_RECORDS = "too_many_records"        # more on that version than a report holds


class HistoryRead(StrEnum):
    """What became of Codex's history, which only the progress counts need."""
    READ = "read"
    ABSENT = "absent"
    UNREADABLE = "unreadable"


class EngineSource(StrEnum):
    """Where the Codex version in use now was read."""
    WATCHER_REPORT = "watcher_report"            # the watcher's own report, valid and fresh
    LOG = "log"                                  # the last engine line of the log


class ReadRefused(Exception):
    """No report: `code` says why, and nothing else does."""

    def __init__(self, code):
        self.code = ReadRefusal(code)
        super().__init__(str(self.code))


# ------------------------------------------------------------------------------ opening
@contextmanager
def readonly(path: Path):
    """A SQLite file opened so that nothing can be written to it, as core opens Codex's. The URI
    comes from Path.as_uri(), which escapes '#', '%' and '?' in a folder name; a hand-built one
    lets a '#' cut off `?mode=ro`, and SQLite then makes a file there."""
    connection = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True, timeout=TIMEOUT)
    try:
        connection.execute("PRAGMA query_only = ON")
        connection.execute("PRAGMA trusted_schema = OFF")
        yield connection
    finally:
        connection.close()


def _busy(error) -> bool:
    return (getattr(error, "sqlite_errorcode", 0) & 0xFF) in _BUSY or "locked" in str(error)


def _present(paths, path: Path, unreadable) -> bool:
    """Whether one of the home's own databases is there: False when it is not; True for a plain
    file inside the home. A link or a reparse point - the file's or its folder's - or a path out
    of the home is refused with `unreadable`, never followed."""
    try:
        if config.is_link(path) or config.is_link(path.parent):
            raise ReadRefused(unreadable)
        if not path.exists():
            return False
        if not path.is_file() or not paths.confined(path):
            raise ReadRefused(unreadable)
    except OSError:
        raise ReadRefused(unreadable) from None
    return True


# ------------------------------------------------------------------------------ the state
def _paused(db):
    """Whether recovery is paused - the switch off, as control/codexstart.py reads it - or None
    when the switch cannot be read."""
    try:
        row = db.execute("SELECT enabled FROM settings WHERE singleton = 1").fetchone()
    except sqlite3.Error:
        return None
    if row is None or isinstance(row[0], bool) or row[0] not in (0, 1):
        return None
    return not row[0]


def state(paths):
    """(schema, rows, hidden, paused): the records not hidden with Clear history that have a time
    they were found at, as dicts of COLUMNS; how many are hidden; and whether recovery is paused."""
    path = paths.state_dir / "state.sqlite"
    if not _present(paths, path, ReadRefusal.STATE_UNREADABLE):
        raise ReadRefused(ReadRefusal.NO_STATE)
    try:
        with readonly(path) as db:
            found = db.execute("PRAGMA user_version").fetchone()[0]
            if found > max(STATE_SCHEMAS):
                raise ReadRefused(ReadRefusal.STATE_NEWER)
            if found not in STATE_SCHEMAS:
                raise ReadRefused(ReadRefusal.STATE_OLDER)
            present = {row[1] for row in db.execute("PRAGMA table_info(interruptions)")}
            if not set(COLUMNS) <= present:
                raise ReadRefused(ReadRefusal.STATE_UNREADABLE)
            rows = [dict(zip(COLUMNS, row)) for row in db.execute(
                "SELECT %s FROM interruptions WHERE history_hidden_at IS NULL" % ", ".join(COLUMNS))]
            hidden = db.execute("SELECT count(*) FROM interruptions "
                                "WHERE history_hidden_at IS NOT NULL").fetchone()[0]
            paused = _paused(db)
    except sqlite3.Error as error:
        raise ReadRefused(ReadRefusal.STATE_BUSY if _busy(error) else ReadRefusal.STATE_UNREADABLE) from None
    return found, [row for row in rows if evidence.moment(row["detected_at"])], hidden, paused


def paused(paths):
    """Whether recovery is paused now - the state's switch off, as control/codexstart.py reads it - or
    None where that cannot be told: no state, a link, a damaged file or a switch that is not 0 or 1.
    Read as the rest is, so nothing is written; asked before a report asks GitHub anything (K5)."""
    path = paths.state_dir / "state.sqlite"
    try:
        if not _present(paths, path, ReadRefusal.STATE_UNREADABLE):
            return None
        with readonly(path) as db:
            return _paused(db)
    except (ReadRefused, sqlite3.Error, OSError):
        return None


# ------------------------------------------------------------------------------ the spend ledger
def ledger(paths, now):
    """(schema or None, paid, reach): paid is {interruption id: the claim times a feature paid a
    unit at}, and reach the earliest claim the ledger can still tell, or None when it tells every
    one. (None, {}, None) where there is no ledger - every installation nothing was ever armed on."""
    from ..state.journal import EVENT_LIMIT, EVENT_MAX_AGE
    from ..state.schema import FILE_NAME, SCHEMA_VERSION
    path = paths.advanced_dir / FILE_NAME
    if not _present(paths, path, ReadRefusal.LEDGER_UNREADABLE):
        return None, {}, None
    paid = {}
    try:
        with readonly(path) as db:
            found = db.execute("PRAGMA user_version").fetchone()[0]
            if found > SCHEMA_VERSION:
                raise ReadRefused(ReadRefusal.LEDGER_NEWER)
            if found < 1:
                raise ReadRefused(ReadRefusal.LEDGER_UNREADABLE)
            present = {row[1] for row in db.execute("PRAGMA table_info(spend)")}
            if not set(SPEND) <= present:
                raise ReadRefused(ReadRefusal.LEDGER_UNREADABLE)
            for key, at in db.execute("SELECT %s FROM spend WHERE interruption_id IS NOT NULL" % ", ".join(SPEND)):
                if isinstance(key, str) and evidence.moment(at):
                    paid.setdefault(key, set()).add(evidence.moment(at))
            units, oldest = db.execute("SELECT count(*), min(at) FROM spend").fetchone()
            given = None                # how many units SQLite ever gave the table; None when it keeps no count
            if db.execute("SELECT count(*) FROM sqlite_master WHERE type = 'table' AND name = 'sqlite_sequence'"
                          ).fetchone()[0]:
                given = db.execute("SELECT max(seq) FROM sqlite_sequence WHERE name = 'spend'").fetchone()[0] or 0
    except sqlite3.Error as error:
        raise ReadRefused(ReadRefusal.STATE_BUSY if _busy(error) else ReadRefusal.LEDGER_UNREADABLE) from None
    return found, paid, evidence.ledger_reach(units, oldest, given, now, max_age=EVENT_MAX_AGE, limit=EVENT_LIMIT)


# ------------------------------------------------------------------------------ the logs
def log_names(paths) -> tuple:
    """The log and its rotated copies (logbook.py, BACKUP_COUNT), oldest first."""
    name = paths.log_file.name
    return tuple("%s.%d" % (name, number) for number in range(BACKUP_COUNT, 0, -1)) + (name,)


def log_lines(paths) -> list:
    """(time, text) for every line of the logs, oldest first. A copy that is missing, a link, out
    of the home, unreadable or far larger than the product writes is passed over."""
    texts = []
    for name in log_names(paths):
        path = paths.logs_dir / name
        try:
            if (config.is_link(path) or not path.is_file() or not paths.confined(path)
                    or path.stat().st_size > MAX_LOG_BYTES):
                continue
            texts.append(path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
    return evidence.log_lines(texts)


# ------------------------------------------------------------------------------ the engine
def watcher_view(paths):
    """The watcher's own report as every reader takes it (compatio.reader_view): validated, bound
    to the engine on disk and fresh - or a view that says why not. None if it could not be had."""
    from codex_auto_resume import compatio, settings
    try:
        return compatio.reader_view(paths, settings=settings.load(paths.settings_file))
    except Exception:           # no view is a view that cannot be used: the log is read instead
        return None


def current_engine(view, lines):
    """(version, source, capabilities): the Codex version in use now and where it was read, with
    the watcher's capabilities when its report says it. A report that is not usable - absent,
    damaged, stale or about a binary that changed - says nothing, and the last engine line of the
    log is the version (G7)."""
    if isinstance(view, dict) and view.get("status") == "ok":
        engine = view.get("engine") if isinstance(view.get("engine"), dict) else {}
        version = engine.get("version")
        if isinstance(version, str) and version.strip() and evidence.VERSION.match(evidence.full(version)):
            capabilities = view.get("capabilities")
            return (evidence.full(version), EngineSource.WATCHER_REPORT,
                    capabilities if isinstance(capabilities, dict) else {})
    version = evidence.latest_engine(lines)
    if version is None:
        raise ReadRefused(ReadRefusal.NO_ENGINE_VERSION)
    return version, EngineSource.LOG, None


# ------------------------------------------------------------------------------ Codex's history
def _counts(db, row):
    thread, turn = row["thread_id"], row["recovery_turn_id"]
    if not ids.is_uuid(thread) or not ids.is_uuid(turn):
        return None
    try:
        found = {kind: many for kind, many in db.execute(PROGRESS_SQL, (thread, turn)).fetchall()}
    except sqlite3.Error:
        return None
    return {kind: found.get(kind, 0) for kind in evidence.PROGRESS}


def progress(codex_home, rows):
    """(what became of the history, each row's counts or None): how many items of each of the four
    kinds the row's recovered turn made, read through core's read-only opener, which reads the
    newest generation only and refuses one whose schema moved. This is the one question that
    passes over a conversation: SQLite reads that turn's rows to count them, and only the counts
    come back."""
    from codex_auto_resume.codex import LocalSource, SourceError
    from codex_auto_resume.codex.paths import newest_generation
    nothing = [None] * len(rows)
    try:
        source = LocalSource(codex_home)
        if newest_generation(source.home, "history") is None:
            return HistoryRead.ABSENT, nothing
    except FileNotFoundError:
        return HistoryRead.ABSENT, nothing
    except (OSError, ValueError):
        return HistoryRead.UNREADABLE, nothing
    try:
        with source._db("history") as db:
            return HistoryRead.READ, [_counts(db, row) for row in rows]
    except (SourceError, sqlite3.Error, OSError, ValueError):
        return HistoryRead.UNREADABLE, nothing


# ------------------------------------------------------------------------------ all of it
def read(paths, codex_home, codex_version=None, *, now=None, view=None) -> dict:
    """What this PC's own records show for one Codex version - `codex_version`, or the one in use
    now - or ReadRefused.

        {"read":     {"state_schema", "ledger_schema", "history", "paused"},
         "engine":   {"current", "from"},
         "left_out": {"hidden", "another_route", "beyond_reach", "elsewhere", "unplaced": {code: n}},
         "body":     {"codex_version", "verdict", "local_checks", "records", "capabilities"}}

    `body` is what codex-compat-reporter's `build` puts under those keys. `now` is the clock the
    ledger's reach is read at; `view`, which returns the watcher's report as a reader takes it,
    is a seam for the tests."""
    now = time.time() if now is None else now
    asked = None
    if codex_version is not None:
        asked = evidence.canonical_version(codex_version)
        if asked is None:
            raise ReadRefused(ReadRefusal.VERSION_INVALID)
    state_schema, rows, hidden, paused = state(paths)
    ledger_schema, paid, reach = ledger(paths, now)
    rows, routed, unknown = evidence.by_route(rows, paid, reach)
    lines = log_lines(paths)
    current, source, capabilities = current_engine(watcher_view(paths) if view is None else view(), lines)
    version = asked or evidence.canonical_version(current)
    if version is None:
        raise ReadRefused(ReadRefusal.VERSION_INVALID)
    placed, elsewhere, unplaced = evidence.place(rows, evidence.engine_timeline(lines), current, version)
    if len(placed) > evidence.MAX_RECORDS:
        raise ReadRefused(ReadRefusal.TOO_MANY_RECORDS)
    history, counts = progress(codex_home, placed)
    return {
        "read": {"state_schema": state_schema, "ledger_schema": ledger_schema, "history": str(history),
                 "paused": paused},
        "engine": {"current": current, "from": str(source)},
        "left_out": {"hidden": hidden, "another_route": routed, "beyond_reach": unknown, "elsewhere": elsewhere,
                     "unplaced": {str(code): unplaced.get(code, 0) for code in evidence.Unplaced}},
        "body": evidence.body(version, placed, lines, capabilities if version == current else None, counts),
    }
