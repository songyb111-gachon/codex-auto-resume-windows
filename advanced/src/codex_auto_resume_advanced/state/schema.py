# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""The tables of advanced.sqlite, as they are created today, and the steps from the first two.

Eleven tables and nothing else - the state is refused at open if it holds any other, or any
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
    options    a capability's own choices a person made in the Dashboard (registry.Option), and
               whether they keep it on (KeepOn)
    rules      the rules a person wrote for Codex's error codes, ten at most, never pruned
    admissions which capability took up which interruption at P17, with the word it took it up
               with - and, for one that samples, the failure's shape - pruned at 90 days
    samples    failures a capability took up that nothing classified: Codex's error code, a status
               number, the error's form, item counts and times, and never a word of any message

Version 2 added `arming.warnings` (the owner's rule of 2026-09-26: a warning is confirmed, not
refused). A version-1 file - v0.6.11-alpha's, where lowering the global ceiling makes one - is
brought to version 2 when it is opened (UPGRADE_FROM_1): the column is added, every row keeps
what it held, and a row with no warnings confirmed none, which is the strictest reading.

Version 3 (v0.6.14, stage 3b) added four tables, for the capabilities that take failures up, and the
reset actions' four (v0.6.14):

    windows        the usage windows a pending rule names, and what was counted of each
    readings       one row: the last usage reading counted, and - only while reset_credit is on - the
                   count of reset credits and the soonest expiry
    reset_rules    a person's rules for a reset credit or a message of their own at a reset they chose
    credit_spends  each reset credit this edition asked Codex to spend, under its key

A version-2 file is brought to it when it is opened (UPGRADE_FROM_2), and a version-1 file takes both
steps; every table that was there keeps every row. No release wrote a version-3 file before the reset
actions joined it, but a pre-release build of this beta may have, so a version-3 file with the first four
tables and not the last four is given them (ADD_RESETS), keeping every row, its version unchanged. A
version this one does not know is refused, as before: a downgrade leaves the state unreadable, which is
every capability off.
"""
from __future__ import annotations

from codex_auto_resume import failures
from codex_auto_resume.domain.plug import TAKE_UP, FailureForm

from ..registry import GLOBAL_HOURLY
from ..vocabulary import (ArmingState, KeepOn, OptionKey, OverrideKind, RecordState, RuleReason, RuleState,
                          SpendOutcome)

SCHEMA_VERSION = 3
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
    "options": ("capability", "choice", "value"),
    "rules": ("rule_id", "tag", "status_from", "status_to", "category", "created_at"),
    "admissions": ("interruption_id", "capability", "answer", "rule_id", "tag", "status", "form",
                   "has_words", "sampled", "created_at"),
    "samples": ("sample_id", "at", "tag", "status", "form", "has_words", "items_agent",
                "items_command", "items_file", "items_tool", "items_user", "items_other", "duration"),
    "windows": ("bucket", "minutes", "open_reset_at", "open_full", "last_closed_at", "resets", "hits",
                "seen_at", "misses"),
    "readings": ("singleton", "read_at", "asked_at", "applied_at", "signal_at", "credits", "expiry_known",
                 "nearest_expiry"),
    "reset_rules": ("rule_id", "capability", "bucket", "minutes", "ordinal", "repeat", "ask_first", "record_id",
                    "words", "created_at", "adopted_at", "base", "state", "reason", "gate", "gate_reason",
                    "due_at", "launching_at", "sent_at", "finished_at"),
    "credit_spends": ("spend_id", "rule_id", "bucket", "minutes", "occasion", "attempt_id", "created_at", "tries",
                      "outcome", "finished_at"),
}
# The reset actions' tables, the last four of version 3 (v0.6.14).
RESET_TABLES = ("windows", "readings", "reset_rules", "credit_spends")
# The buckets a usage window is kept under (core's domain/usage.BUCKETS), and the capabilities whose
# rules `reset_rules` holds (registry.RESET_CREDIT, RESET_MESSAGE).
BUCKETS = ("codex", "premium", "legacy", "other")
RESET_CAPABILITIES = ("reset_credit", "reset_message")
# The tables version 2 had: v0.6.11's and v0.6.12's file.
TABLES_V2 = {name: TABLES[name] for name in ("meta", "arming", "spend", "records", "overrides",
                                             "journal", "sampler")}


def _one_of(column, words) -> str:
    return "CHECK (%s IN (%s))" % (column, ", ".join("'%s'" % word for word in words))


# The warnings a person confirmed: ArmingWarning's words, joined by commas. The file keeps out
# anything but those letters; the code keeps out any word the vocabulary does not hold.
WARNINGS_COLUMN = "warnings TEXT CHECK (warnings IS NULL OR warnings NOT GLOB '*[^a-z_,]*')"


def _tag(column, *, null=True) -> str:
    """Codex's own error code, as failures.TAG_SHAPE allows one: letters and digits, a letter first, at
    most 64 - never a space, a mark or anything a message would hold."""
    shaped = ("(length(%s) BETWEEN 1 AND 64 AND %s GLOB '[A-Za-z]*' AND %s NOT GLOB '*[^A-Za-z0-9]*')"
              % (column, column, column))
    return "CHECK (%s IS NULL OR %s)" % (column, shaped) if null else "CHECK %s" % shaped


def _status(column) -> str:
    return "CHECK (%s IS NULL OR (typeof(%s) = 'integer' AND %s BETWEEN 100 AND 599))" % (
        column, column, column)


def _flag(column, *, null=False) -> str:
    return "CHECK (%s%s IN (0, 1))" % ("%s IS NULL OR " % column if null else "", column)


def _count(column) -> str:
    return "CHECK (%s IS NULL OR (typeof(%s) = 'integer' AND %s >= 0))" % (column, column, column)


_STATEMENTS_V2 = (
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
)

# Version 3's own tables. The words a decision reads are the vocabulary's, as everywhere here: a
# choice (OptionKey, or KeepOn's), a temporary kind a rule may name (failures.TRANSIENT, never usage_limit), the
# word a capability took a failure up with (TAKE_UP), a form (FailureForm). `has_words` is whether
# the error came with a message - never the message, and no column could hold one.
_STATEMENTS_V3 = (
    """CREATE TABLE options (
        capability TEXT NOT NULL,
        choice TEXT NOT NULL %s,
        value INTEGER NOT NULL CHECK (typeof(value) = 'integer' AND value >= 1),
        PRIMARY KEY (capability, choice)
    )""" % _one_of("choice", (*OptionKey, *KeepOn)),
    """CREATE TABLE rules (
        rule_id INTEGER PRIMARY KEY AUTOINCREMENT,
        tag TEXT NOT NULL %s,
        status_from INTEGER %s,
        status_to INTEGER %s,
        category TEXT NOT NULL %s,
        created_at REAL NOT NULL,
        CHECK ((status_from IS NULL) = (status_to IS NULL)),
        CHECK (status_from IS NULL OR status_from <= status_to)
    )""" % (_tag("tag", null=False), _status("status_from"), _status("status_to"),
            _one_of("category", sorted(failures.TRANSIENT))),
    """CREATE TABLE admissions (
        interruption_id TEXT PRIMARY KEY CHECK (length(interruption_id) = 64),
        capability TEXT NOT NULL,
        answer TEXT NOT NULL %s,
        rule_id INTEGER,
        tag TEXT %s,
        status INTEGER %s,
        form TEXT CHECK (form IS NULL OR form IN (%s)),
        has_words INTEGER %s,
        sampled INTEGER NOT NULL %s,
        created_at REAL NOT NULL
    )""" % (_one_of("answer", sorted(TAKE_UP)), _tag("tag"), _status("status"),
            ", ".join("'%s'" % word for word in FailureForm), _flag("has_words", null=True),
            _flag("sampled")),
    "CREATE INDEX admissions_created ON admissions(created_at)",
    """CREATE TABLE samples (
        sample_id INTEGER PRIMARY KEY AUTOINCREMENT,
        at REAL NOT NULL,
        tag TEXT %s,
        status INTEGER %s,
        form TEXT NOT NULL %s,
        has_words INTEGER NOT NULL %s,
        items_agent INTEGER %s,
        items_command INTEGER %s,
        items_file INTEGER %s,
        items_tool INTEGER %s,
        items_user INTEGER %s,
        items_other INTEGER %s,
        duration REAL CHECK (duration IS NULL OR duration >= 0)
    )""" % (_tag("tag"), _status("status"), _one_of("form", FailureForm), _flag("has_words"),
            *(_count(name) for name in ("items_agent", "items_command", "items_file", "items_tool",
                                        "items_user", "items_other"))),
    "CREATE INDEX samples_at ON samples(at)",
)


def _int(column, *, low=0, high=None, null=True) -> str:
    shaped = "typeof(%s) = 'integer' AND %s >= %d%s" % (column, column, low,
                                                        "" if high is None else " AND %s <= %d" % (column, high))
    return "CHECK (%s IS NULL OR (%s))" % (column, shaped) if null else "CHECK (%s)" % shaped


def _gate_word(column) -> str:
    """A gate's or a reason's name as core says it: lowercase letters, digits and underscores."""
    return ("CHECK (%s IS NULL OR (length(%s) BETWEEN 1 AND 48 AND %s NOT GLOB '*[^a-zA-Z0-9_]*'))"
            % (column, column, column))


# The reset actions' four (v0.6.14). A window is a bucket and a length, never a slot; its times are
# whole seconds as Codex gives them. A rule's words are a message's alone, while it is still to act,
# and no longer than core's one send carries; a credit's spend is one for each filling of a window.
_STATEMENTS_RESETS = (
    """CREATE TABLE windows (
        bucket TEXT NOT NULL %s,
        minutes INTEGER NOT NULL %s,
        open_reset_at INTEGER %s,
        open_full INTEGER NOT NULL %s,
        last_closed_at INTEGER %s,
        resets INTEGER NOT NULL %s,
        hits INTEGER NOT NULL %s,
        seen_at REAL,
        misses INTEGER NOT NULL %s,
        PRIMARY KEY (bucket, minutes)
    )""" % (_one_of("bucket", BUCKETS), _int("minutes", low=1, high=100800, null=False), _int("open_reset_at"),
            _flag("open_full"), _int("last_closed_at"), _int("resets", null=False), _int("hits", null=False),
            _int("misses", null=False)),
    """CREATE TABLE readings (
        singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
        read_at REAL,
        asked_at REAL,
        applied_at REAL,
        signal_at REAL,
        credits INTEGER %s,
        expiry_known INTEGER %s,
        nearest_expiry INTEGER %s
    )""" % (_int("credits"), _flag("expiry_known", null=True), _int("nearest_expiry")),
    "INSERT INTO readings (singleton) VALUES (1)",
    """CREATE TABLE reset_rules (
        rule_id INTEGER PRIMARY KEY AUTOINCREMENT,
        capability TEXT NOT NULL %s,
        bucket TEXT NOT NULL %s,
        minutes INTEGER NOT NULL %s,
        ordinal INTEGER NOT NULL %s,
        repeat INTEGER NOT NULL %s,
        ask_first INTEGER NOT NULL %s,
        record_id TEXT CHECK (record_id IS NULL OR (length(record_id) = 64 AND record_id NOT GLOB '*[^0-9a-f]*')),
        words TEXT,
        created_at REAL NOT NULL,
        adopted_at REAL,
        base INTEGER %s,
        state TEXT NOT NULL %s,
        reason TEXT CHECK (reason IS NULL OR reason IN (%s)),
        gate TEXT %s,
        gate_reason TEXT %s,
        due_at REAL,
        launching_at REAL,
        sent_at REAL,
        finished_at REAL,
        CHECK (words IS NULL OR (capability = 'reset_message' AND state IN ('%s', '%s', '%s')
                                 AND typeof(words) = 'text' AND length(words) BETWEEN 1 AND 8192)),
        CHECK ((capability = 'reset_message') = (record_id IS NOT NULL)),
        CHECK (ordinal > 0 OR capability = 'reset_credit')
    )""" % (_one_of("capability", RESET_CAPABILITIES), _one_of("bucket", BUCKETS),
            _int("minutes", low=1, high=100800, null=False), _int("ordinal", high=9, null=False), _flag("repeat"),
            _flag("ask_first"), _int("base"), _one_of("state", RuleState),
            ", ".join("'%s'" % word for word in RuleReason), _gate_word("gate"), _gate_word("gate_reason"),
            RuleState.COUNTING, RuleState.READY, RuleState.HELD),
    "CREATE INDEX reset_rules_state ON reset_rules(state)",
    """CREATE TABLE credit_spends (
        spend_id INTEGER PRIMARY KEY AUTOINCREMENT,
        rule_id INTEGER NOT NULL,
        bucket TEXT NOT NULL %s,
        minutes INTEGER NOT NULL %s,
        occasion INTEGER NOT NULL %s,
        attempt_id TEXT NOT NULL CHECK (length(attempt_id) = 36 AND attempt_id NOT GLOB '*[^0-9a-f-]*'),
        created_at REAL NOT NULL,
        tries INTEGER NOT NULL %s,
        outcome TEXT CHECK (outcome IS NULL OR outcome IN (%s)),
        finished_at REAL,
        UNIQUE (bucket, minutes, occasion)
    )""" % (_one_of("bucket", BUCKETS), _int("minutes", low=1, high=100800, null=False),
            _int("occasion", null=False), _int("tries", low=1, high=2, null=False),
            ", ".join("'%s'" % word for word in SpendOutcome)),
    "CREATE INDEX credit_spends_created ON credit_spends(created_at)",
)
_STATEMENTS_V3 = _STATEMENTS_V3 + _STATEMENTS_RESETS

STATEMENTS = _STATEMENTS_V2 + _STATEMENTS_V3 + ("PRAGMA user_version=%d" % SCHEMA_VERSION,)
# Version 2's file exactly as v0.6.11 and v0.6.12 made it: what a test builds an older file from.
STATEMENTS_V2 = _STATEMENTS_V2 + ("PRAGMA user_version=2",)

# Version 1's tables and the step that makes them version 2's, then the step from 2 to 3. A later
# version adds its own step after these, from 3, rather than changing them.
TABLES_V1 = dict(TABLES_V2, arming=TABLES["arming"][:-1])
UPGRADE_FROM_1 = (
    "ALTER TABLE arming ADD COLUMN %s" % WARNINGS_COLUMN,
    "PRAGMA user_version=2",
)
UPGRADE_FROM_2 = _STATEMENTS_V3 + ("PRAGMA user_version=3",)
# A version-3 file a pre-release build made before the reset actions' tables (v0.6.14): those four
# added, every row kept, its version unchanged.
TABLES_V3_BEFORE_RESETS = {name: TABLES[name] for name in TABLES if name not in RESET_TABLES}
ADD_RESETS = _STATEMENTS_RESETS
