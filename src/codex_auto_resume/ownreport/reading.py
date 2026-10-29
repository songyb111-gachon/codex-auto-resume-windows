"""This PC's own records, read for a compatibility report - and never written, migrated or locked.

The files codex-compat-reporter 1.5.0 reads, read the same way (its state_rows, log_lines and
installed_codex), so that every report this product writes of them is the one that program writes:

    config/state.sqlite           the 17 columns the report needs, the count of records hidden
                                  with Clear history, and the recovery switch (a pause)
    logs/auto-resume.log and its five rotated copies
                                  the engine lines and their local times
    config/compatibility.json     the watcher's own report, through compatio.reader_view only

Never through the Store, which makes its directory and opens the file writable: the database is
opened `mode=ro`, with query_only on, trusted_schema off and a three-second timeout, so nothing is
written beside it - no -journal, no folder - and nothing is migrated. A link, a reparse point or a
path out of the home is refused. A schema newer than this reads is refused, not read as today's.
Codex's own files are not read here at all (B17: the Dashboard never imports Codex's readers).

A refusal is one closed code (`ReadRefusal`) and nothing else: never an id, a path, a login or
text. What the records say is evidence.py's, which is pure.
"""
from __future__ import annotations

import collections
from contextlib import contextmanager
from enum import StrEnum
import math
from pathlib import Path
import sqlite3

from codex_auto_resume import config
from codex_auto_resume.logbook import BACKUP_COUNT

from . import evidence

# The state database's user_versions read, and no others: 3 (v0.6.0 to v0.6.11-alpha), 4 (v0.6.11-beta
# to v0.6.14) and 5 (from v0.6.15-beta; store/schema.py SCHEMA_VERSION). Schemas 4 and 5 added
# columns and changed none of these.
STATE_SCHEMAS = (3, 4, 5)
# The columns read from the state, in schema 3, 4 and 5 alike, and nothing else. thread_id and
# recovery_turn_id key only a progress count; history_hidden_at only leaves hidden records out;
# interruption_id, recovery_client_id and last_claim_at only tell a record another route carried.
COLUMNS = ("thread_id", "category", "state", "last_error", "detected_at", "resumed_at", "outcome_at",
           "submitted_at", "recovery_turn_id", "recovery_turn_status", "gate_eval", "reset_at",
           "limit_type", "history_hidden_at", "interruption_id", "recovery_client_id", "last_claim_at")
TIMEOUT = 3                                      # seconds a database may be busy before it is refused
# The product rotates its log at 1 MB (logbook.py MAX_BYTES); a file many times that is not one it wrote.
MAX_LOG_BYTES = 8 * 1024 * 1024
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
    Read as the rest is, so nothing is written."""
    path = paths.state_dir / "state.sqlite"
    try:
        if not _present(paths, path, ReadRefusal.STATE_UNREADABLE):
            return None
        with readonly(path) as db:
            return _paused(db)
    except (ReadRefused, sqlite3.Error, OSError):
        return None


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


# ------------------------------------------------------------------------------ every version (the Dashboard's report)
MAX_VERSIONS = 64                                # the newest kept; a report names at most this many


def _order(version):
    found = evidence.GRAMMAR.match(version)
    return tuple(int(part or 0) for part in found.groups()) if found else ()


def read_all(paths, *, view=None) -> dict:
    """What this PC's own records show for every Codex version the product's own log names, and the
    one in use now, newest first - or ReadRefused, as `state` and `current_engine` refuse.

        {"engine":   {"current", "from"},
         "left_out": {"hidden", "another_route", "beyond_reach", "unplaced": {code: n}},
         "versions": [{"codex_version", "body"} or {"codex_version", "refusal"}]}

    Each body is what codex-compat-reporter's `build` writes for that version (evidence.body), with
    `progress_items` null: Codex's history is not read here. Another route is told by the state's own
    marks (evidence.another_route). The advanced edition's spend ledger is not read, so where this
    home holds that edition's state (config.Paths.owned_advanced_files) a claimed record no mark tells
    apart is left out as beyond reach, never counted for the standard route; a home that never held it
    has no ledger, and every record is told. `view` is a seam for the tests, as in the reader's `read`."""
    _schema, rows, hidden, _paused = state(paths)
    reach = math.inf if paths.owned_advanced_files() else None
    rows, routed, unknown = evidence.by_route(rows, {}, reach)
    lines = log_lines(paths)
    current, source, capabilities = current_engine(watcher_view(paths) if view is None else view(), lines)
    timeline = evidence.engine_timeline(lines)
    named = {evidence.canonical_version(version) for _when, version in timeline}
    named.add(evidence.canonical_version(current))
    named.discard(None)
    versions = sorted(named, key=_order, reverse=True)[:MAX_VERSIONS]
    found, unplaced = [], collections.Counter()
    for version in versions:
        placed, _elsewhere, unplaced = evidence.place(rows, timeline, current, version)
        if len(placed) > evidence.MAX_RECORDS:
            found.append({"codex_version": version, "refusal": str(ReadRefusal.TOO_MANY_RECORDS)})
            continue
        found.append({"codex_version": version,
                      "body": evidence.body(version, placed, lines, capabilities if version == current else None,
                                            [None] * len(placed))})
    return {"engine": {"current": current, "from": str(source)},
            "left_out": {"hidden": hidden, "another_route": routed, "beyond_reach": unknown,
                         "unplaced": {str(code): unplaced.get(code, 0) for code in evidence.Unplaced}},
            "versions": found}
