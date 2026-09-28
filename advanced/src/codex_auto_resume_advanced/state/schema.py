# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""The tables of advanced.sqlite, as they are created today, and the one step from the first.

Seven tables and nothing else - the state is refused at open if it holds any other, or any
other column, exactly as core refuses its own (store/session.py). Every word a decision reads is
checked twice: by the code that writes it (state/session.py) and by a CHECK here, built from the
same closed vocabulary, so not even a hand-edited row can put a word in that the code does not
know.

    meta       one row: the arming generation, and the global ceiling a person may lower
    arming     one row per capability that has ever been moved: off, shadow or armed, and for
               one that is not off, the statement's warnings the person confirmed
    spend      one row per unit a capability spent - the only thing its ceilings count
    records    the edition's own records, counted with core's in every claim (ledger.py)
    overrides  what a capability asks of one standard record, keyed by its interruption id
    journal    content-free lines of what happened, bounded like core's (state/journal.py)
    sampler    per-day counts of a capability's own codes, bounded the same way

Version 2 added `arming.warnings` (the owner's rule of 2026-09-26: a warning is confirmed, not
refused). A version-1 file - v0.6.11-alpha's, where lowering the global ceiling makes one - is
brought to version 2 when it is opened (UPGRADE_FROM_1): the column is added, every row keeps
what it held, and a row with no warnings confirmed none, which is the strictest reading.
"""
from __future__ import annotations

from ..registry import GLOBAL_HOURLY
from ..vocabulary import ArmingState, OverrideKind, RecordState

SCHEMA_VERSION = 2
FILE_NAME = "advanced.sqlite"
# The name the file is attached under on core's connection, inside the one claim (ledger.py).
ATTACHED = "advanced"

TABLES = {
    "meta": ("singleton", "generation", "global_hourly"),
    "arming": ("capability", "state", "since", "actor", "reason", "statement_revision",
               "engine_version", "warnings"),
    "spend": ("spend_id", "at", "capability", "thread_id", "interruption_id"),
    "records": ("record_id", "capability", "thread_id", "state", "created_at", "claimed_at",
                "claims", "finished_at"),
    "overrides": ("interruption_id", "capability", "kind", "created_at", "used_at"),
    "journal": ("event_id", "at", "capability", "code", "reason", "actor", "point", "answer"),
    "sampler": ("capability", "code", "day", "count"),
}


def _one_of(column, words) -> str:
    return "CHECK (%s IN (%s))" % (column, ", ".join("'%s'" % word for word in words))


# The warnings a person confirmed: ArmingWarning's words, joined by commas. The file keeps out
# anything but those letters; the code keeps out any word the vocabulary does not hold.
WARNINGS_COLUMN = "warnings TEXT CHECK (warnings IS NULL OR warnings NOT GLOB '*[^a-z_,]*')"


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
        engine_version TEXT,
        %s
    )""" % (_one_of("state", ArmingState), WARNINGS_COLUMN),
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

# Version 1's tables, and the step that makes them version 2's. A later version adds its own
# step after this one, from 2, rather than changing this.
TABLES_V1 = dict(TABLES, arming=TABLES["arming"][:-1])
UPGRADE_FROM_1 = (
    "ALTER TABLE arming ADD COLUMN %s" % WARNINGS_COLUMN,
    "PRAGMA user_version=2",
)
