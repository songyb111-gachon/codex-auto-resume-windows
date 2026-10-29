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
text. What the records say is core's ownreport/evidence.py, which is pure. The one import of the rest of the
advanced package is the ledger's own schema and bounds, taken where they are written (state/),
not copied, and only when the ledger is read.
"""
from __future__ import annotations

from enum import StrEnum
import sqlite3
import time

from codex_auto_resume.domain import ids
from codex_auto_resume.ownreport import evidence
# What every report of this PC's records reads the same way, in either edition (v0.6.19: core's since the
# Dashboard's own report): the state, the logs and the engine in use, and the closed codes a read is refused by.
from codex_auto_resume.ownreport.reading import (COLUMNS, STATE_SCHEMAS, EngineSource, ReadRefusal,  # noqa: F401
                                                 ReadRefused, _busy, _present, current_engine, log_lines,
                                                 log_names, paused, readonly, state, watcher_view)

SPEND = ("interruption_id", "at")                # the spend ledger's columns read, and nothing else
# The one question asked of Codex's history: how many items of each kind one turn made.
PROGRESS_SQL = ("SELECT item_type, count(*) FROM thread_items WHERE thread_id=? AND turn_id=? "
                "GROUP BY item_type")


class HistoryRead(StrEnum):
    """What became of Codex's history, which only the progress counts need."""
    READ = "read"
    ABSENT = "absent"
    UNREADABLE = "unreadable"


# ------------------------------------------------------------------------------ the spend ledger
def ledger(paths, now):
    """(schema or None, paid, reach): paid is {interruption id: the claim times a feature paid a
    unit at}, and reach the earliest claim the ledger can still tell, or None when it tells every
    one. (None, {}, None) where there is no ledger - every installation nothing was ever armed on."""
    from ..state.journal import EVENT_LIMIT, EVENT_MAX_AGE
    from ..state.schema import FILE_NAME, SCHEMA_VERSION, readable_from
    path = paths.advanced_dir / FILE_NAME
    if not _present(paths, path, ReadRefusal.LEDGER_UNREADABLE):
        return None, {}, None
    paid = {}
    try:
        with readonly(path) as db:
            found = db.execute("PRAGMA user_version").fetchone()[0]
            # A newer ledger is read where it is marked readable from this version (v0.6.17): its spend columns are
            # checked below either way.
            if found > SCHEMA_VERSION and readable_from(db, found) > SCHEMA_VERSION:
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
    is a seam for the tests. The ledger is read only when there are records for it to tell apart,
    as 1.5.0 reads it; `ledger_schema` is None where it was not read."""
    now = time.time() if now is None else now
    asked = None
    if codex_version is not None:
        asked = evidence.canonical_version(codex_version)
        if asked is None:
            raise ReadRefused(ReadRefusal.VERSION_INVALID)
    state_schema, rows, hidden, paused = state(paths)
    # As 1.5.0's by_route: with no record to tell apart, the ledger is not read, nor refused.
    ledger_schema, paid, reach = ledger(paths, now) if rows else (None, {}, None)
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
