# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""The tables of advanced.sqlite, as they are created today.

Seven tables and nothing else - the state is refused at open if it holds any other, or any
other column, exactly as core refuses its own (store/session.py). Every word a decision reads is
checked twice: by the code that writes it (state/session.py) and by a CHECK here, built from the
same closed vocabulary, so not even a hand-edited row can put a word in that the code does not
know.

    meta       one row: the arming generation, and the global ceiling a person may lower
    arming     one row per capability that has ever been moved: off, shadow or armed
    spend      one row per unit a capability spent - the only thing its ceilings count
    records    the edition's own records, counted with core's in every claim (ledger.py)
    overrides  what a capability asks of one standard record, keyed by its interruption id
    journal    content-free lines of what happened, bounded like core's (state/journal.py)
    sampler    per-day counts of a capability's own codes, bounded the same way
"""
from __future__ import annotations

from ..registry import GLOBAL_HOURLY
from ..vocabulary import ArmingState, OverrideKind, RecordState

SCHEMA_VERSION = 1
FILE_NAME = "advanced.sqlite"
# The name the file is attached under on core's connection, inside the one claim (ledger.py).
ATTACHED = "advanced"

TABLES = {
    "meta": ("singleton", "generation", "global_hourly"),
    "arming": ("capability", "state", "since", "actor", "reason", "statement_revision",
               "engine_version"),
    "spend": ("spend_id", "at", "capability", "thread_id", "interruption_id"),
    "records": ("record_id", "capability", "thread_id", "state", "created_at", "claimed_at",
                "claims", "finished_at"),
    "overrides": ("interruption_id", "capability", "kind", "created_at", "used_at"),
    "journal": ("event_id", "at", "capability", "code", "reason", "actor", "point", "answer"),
    "sampler": ("capability", "code", "day", "count"),
}


def _one_of(column, words) -> str:
    return "CHECK (%s IN (%s))" % (column, ", ".join("'%s'" % word for word in words))


STATEMENTS = (
    """CREATE TABLE meta (
        singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
        generation INTEGER NOT NULL CHECK (generation >= 0),
        global_hourly INTEGER NOT NULL CHECK (global_hourly BETWEEN 1 AND %d)
    )""" % GLOBAL_HOURLY,
    "INSERT INTO meta VALUES (1, 0, %d)" % GLOBAL_HOURLY,
    """CREATE TABLE arming (
        capability TEXT PRIMARY KEY,
        state TEXT NOT NULL %s,
        since REAL NOT NULL,
        actor TEXT NOT NULL,
        reason TEXT,
        statement_revision INTEGER,
        engine_version TEXT
    )""" % _one_of("state", ArmingState),
    """CREATE TABLE spend (
        spend_id INTEGER PRIMARY KEY AUTOINCREMENT,
        at REAL NOT NULL,
        capability TEXT NOT NULL,
        thread_id TEXT NOT NULL,
        interruption_id TEXT
    )""",
    "CREATE INDEX spend_at ON spend(at)",
    """CREATE TABLE records (
        record_id TEXT PRIMARY KEY,
        capability TEXT NOT NULL,
        thread_id TEXT NOT NULL,
        state TEXT NOT NULL %s,
        created_at REAL NOT NULL,
        claimed_at REAL,
        claims INTEGER NOT NULL CHECK (claims >= 0),
        finished_at REAL
    )""" % _one_of("state", RecordState),
    "CREATE INDEX records_thread ON records(thread_id)",
    """CREATE TABLE overrides (
        interruption_id TEXT NOT NULL,
        capability TEXT NOT NULL,
        kind TEXT NOT NULL %s,
        created_at REAL NOT NULL,
        used_at REAL,
        PRIMARY KEY (interruption_id, capability)
    )""" % _one_of("kind", OverrideKind),
    """CREATE TABLE journal (
        event_id INTEGER PRIMARY KEY AUTOINCREMENT,
        at REAL NOT NULL,
        capability TEXT,
        code TEXT NOT NULL,
        reason TEXT,
        actor TEXT,
        point TEXT,
        answer TEXT
    )""",
    """CREATE TABLE sampler (
        capability TEXT NOT NULL,
        code TEXT NOT NULL,
        day INTEGER NOT NULL,
        count INTEGER NOT NULL CHECK (count >= 0),
        PRIMARY KEY (capability, code, day)
    )""",
    "PRAGMA user_version=%d" % SCHEMA_VERSION,
)
