# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""The tables of advanced.sqlite, as they are created today, and the steps from the first two.

Eleven tables and nothing else - the state is refused at open if it holds any other, or any
other column, exactly as core refuses its own (store/session.py). Every word a decision reads is
checked twice: by the code that writes it (state/session.py) and by a CHECK here, built from the
same closed vocabulary, so not even a hand-edited row can put a word in that the code does not
know - but for the names of `options`, which since v0.6.17 the code alone checks (below).

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

Version 5 (v0.6.16-beta.3, issue #29) makes `options` and `continuations` again with their wider lists - the usage
meter's, the wrap-up's and the pause's own choices (OptionKey), and the wrap-up's continuations (usage_wrap_up,
ContinuationKind.WRAP_UP) - every row kept, and adds one table:

    meter          the usage meter's last reading, one row for each window (a bucket and a length): how full it
                   was, when it resets and when it was read, and the reset each stage last acted for - the warning
                   shown, the pause held - so each acts once for a window, across restarts

A version-4 file is brought to it when it is opened (UPGRADE_FROM_4), after any earlier step. The way down is the
one every earlier version has: a build of version 4 or older refuses a version-5 file as newer, reads every
capability as off, and writes nothing to it (session._prepare) - the person's choices and the meter's rows wait
there, untouched, for a build that knows them, and the standard edition never opens the file at all.

Version 6 (v0.6.16-beta.4, the owner's additions to issue #29) makes `options` and `continuations` again with their
wider lists - each window on or off, the stop percentage the wrap-up's words name, Include the reset time and
Continue after the reset (OptionKey), and the continuation after the reset (ContinuationKind.AFTER_RESET) - every row
kept, and adds one table:

    wordings       a person's own wording for a capability, by its key (WordingKey): the wrap-up's Custom text for
                   each window - text of 1 to 2000 characters, as the custom continuation text is, never logged

A version-5 file is brought to it when it is opened (UPGRADE_FROM_5); the way down is as before: a build of version 5
or older refuses a version-6 file as newer, every capability reads off, and nothing is written to it.

Version 7, stage 4's (v0.6.16-beta.4; the owner's yes of 2026-10-11), adds two tables and remakes none - a version-6
file is brought to it by two CREATE TABLE statements, every row kept (UPGRADE_TO_STAGE4); an older one takes the
earlier steps first:

    headless_runs  a turn run here while it runs, a person's Stop of it, how it ended, and the model a fallback
                   turn owes the conversation back until it is put back (state/runs.py)
    chat_messages  the Dashboard's chat messages: their words only until sent (state/chat.py)

The way down is the same: an older build refuses the file as newer, every capability off.

v0.6.17 (the owner's decision of 2026-10-18) makes `options` again without the CHECK on its names, every row kept, and
marks the file with the oldest version that can read it (READABLE_FROM) - and keeps version 7. Whenever the table's
stored CREATE still names its words (names_checked), the opening makes it again (FREE_OPTIONS), after any earlier step,
in the opening's one transaction: a run cut short leaves the old table whole, and a table already free is left alone.
The tables and their columns are version 7's, which is all v0.6.16 compares, so it goes on reading the file with every
feature on, and its own writes stay checked by its code.

    options        a choice's name is checked by the code that writes it - the capability must offer it
                   (registry.Option) and the vocabulary must hold it (OptionKey) - and a name a reader does not know
                   is passed over, as every reader of the table always did (choices.options, arming, ledger); a new
                   choice no longer needs the table made again, nor a new version

    readable from  PRAGMA application_id holds MARK with, in its low 16 bits, the oldest version whose reader may use
                   the file. A version that adds only what an older reader passes over (a table, a column at the end
                   with a default, a word of a list only the code checks) keeps the older number there, and that
                   reader uses the file instead of refusing it - every table it knows holding at least its columns,
                   first - upgrading nothing and leaving the version and the mark as they are. A file marked newer than
                   the reader is still refused, and a file without the mark is readable from its own version alone,
                   as every file v0.6.16 and earlier wrote is.

The first marked file did not bump the version: v0.6.16 reads no mark, so a version 8 - however readable - would be
refused there as newer, every feature off after a pick of v0.6.16 in Install another version. Kept at 7, it is read
there as its own; the mark serves every version from v0.6.17 on, the first time a later version (v0.6.18's) moves it.

Version 8, the v0.6.19 stage's (plans/v0619-design/D-groundwork.md), fixes the stage's stored format once, before any of
its capabilities is built - nothing reads its tables until one is - and stays marked readable from 7: it adds ten tables
and a column at the end of `prompts` with a default, which a reader of version 7 from v0.6.17 on passes over, and frees
`wordings` of the CHECK on its keys, as v0.6.17 freed `options`. A version-7 file is brought to it when it is opened
(UPGRADE_TO_V019), every row kept; a file of an older version takes the earlier steps first.

    usage_samples  each usage window's share at each reading, for the burn rate (usage_analytics)
    token_days     the tokens a conversation used on a day, by kind, and its turns - never a word of it
    token_files    how far each rollout was read, under a digest of its path and never the path
    outbox         each notice to be pushed, by channel: a closed event and category, a `task N` alias, its tries
    feed           one row: what the status feed last said, of the service and of Codex
    remote         a remote channel's pairing (Telegram): when it was paired, a digest of its one-time code
    opens          each conversation opened for a message to be sent, and what came of it
    restarts       each restart of a watcher that stopped unexpectedly (crash_restart's cap counts them)
    account_seen   one row: a keyed digest of the signed-in account, never the address, and its plan word
    hook_claims    each turn the Stop hook answered, by interruption, under a digest of the turn
    prompts        + while_running: whether a queued prompt goes into Codex's queue while a turn runs, or waits
    wordings       a wording's key is checked by the code alone (WordingKey), as an option's name is

`prompts` is made again on the way, every row kept, so its reasons' CHECK takes the word version 8 added (PromptReason
turn_running): SQLite cannot change a CHECK in place, and the version-7 file's would refuse it. Every table is bounded
by the journal's pass (state/journal.py), each as the groundwork fixed it. A version-7 reader from v0.6.17 on uses the
file as it is - every table it knows holding its columns, first - and v0.6.16, which reads no mark, refuses it as newer,
every capability off and nothing written: the way down every version before had.

Version 9, v0.6.20's (issue #50, steer_send), adds one table and changes nothing else, so it stays marked readable from
7: v0.6.17 to v0.6.19 use a version-9 file as it is, every table they know holding its columns. A version-8 file is
brought to it when it is opened (UPGRADE_TO_V020), every row kept; an older file takes the earlier steps first.

    steers         each line a person asked to be added to a running turn: its conversation, the person's own words
                   (kept after the send, so History shows exactly what went in - the owner's decision of 2026-10-29), the
                   client id it carried, where it stands (SteerState) and why it was refused (SteerReason), when it was
                   asked and when it settled; 30 days and 1,000 rows (state/journal.py)
"""
from __future__ import annotations

import re

from codex_auto_resume import failures
from codex_auto_resume.domain.plug import TAKE_UP, FailureForm

from ..registry import GLOBAL_HOURLY
from ..vocabulary import (ArmingState, ChatReason, ChatState, ContinuationKind, ContinuationReason, CourierChannel,
                          CourierEvent, FeedWord, HookOutcome, KeepReason, KeepState, OpenOutcome, OutboxState,
                          OverrideKind, PlanWord, PromptEvery, PromptReason, PromptState, PromptTrigger, RecordState,
                          RuleReason, RuleState, RunEnd, SpendOutcome, SteerReason, SteerState, WhileRunning,
                          WordingKey)

# The window switches (v0.6.16 final, the owner's request of 2026-10-18): Wrap up near a limit and Stop near a limit
# offer a pair of their own, rows of `options` whose CHECK has admitted these words since version 6 - no new version.
# Until then the usage meter's pair decided for all three, so a window switched off there is carried over to the other
# two once (session.SessionMixin._carry_windows). An older build skips a choice its capability does not offer.
WINDOW_CHOICES = ("window_five_hour", "window_weekly")
WINDOW_LEADER = "usage_meter"
WINDOW_FOLLOWERS = ("usage_wrap_up", "usage_pause")
WINDOW_ON, WINDOW_OFF = 1, 2

# The v0.6.19 stage's version (the groundwork): the one place it is numbered - a literal, which the setup's version
# picker reads (tests/test_version_picker.py) - the step after stage 4's (7, v0.6.16-beta.4, which v0.6.17 and v0.6.18
# kept: `options` free of its CHECK and the mark changed no table and no column).
SCHEMA_VERSION = 9
STAGE4_VERSION = 7
V019_VERSION = 8
# v0.6.20's (steer_send): one table added to version 8's.
V020_VERSION = SCHEMA_VERSION
# The oldest version whose reader may use a file this version writes (above): 7 - version 8 only adds what a version-7
# reader from v0.6.17 on passes over. A later version raises it only where a version-7 reader cannot use its file.
READABLE_FROM = 7
# "CA" in the high half of SQLite's application id: the mark that the low half is a readable-from version.
MARK = 0x43410000
_MARK_HALF = 0xFFFF0000
FILE_NAME = "advanced.sqlite"
# The name the file is attached under on core's connection, inside the one claim (ledger.py).
ATTACHED = "advanced"

TABLES = {
    "meta": ("singleton", "generation", "global_hourly"),
    "arming": ("capability", "state", "since", "actor", "reason", "statement_revision",
               "engine_version", "warnings"),
    "spend": ("spend_id", "at", "capability", "thread_id", "interruption_id"),
    "records": ("record_id", "capability", "thread_id", "state", "created_at", "claimed_at",
                "claims", "finished_at", "queue_id", "withdraw"),
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
    # Version 4 (v0.6.15-beta): the edition's own continuations, the conversations kept going, the queued prompts.
    "continuations": ("answer_id", "capability", "kind", "thread_id", "record_id", "ordinal", "words", "chain",
                      "created_at", "finished_at", "reason", "launching_at"),
    "keep_going": ("thread_id", "count", "used", "armed_at", "state", "reason", "finished_at"),
    "prompts": ("prompt_id", "thread_id", "words", "trigger", "at", "every", "occurrences", "sent_count", "until",
                "depends", "position", "state", "reason", "record_id", "gate", "gate_reason", "created_at", "due_at",
                "launching_at", "sent_at", "finished_at",
                # Version 8 (v0.6.19, #50's send mode), at the end with a default.
                "while_running"),
    # Version 5 (v0.6.16-beta.3): the usage meter's last reading of each window, and what each stage acted for.
    "meter": ("bucket", "minutes", "used_percent", "reset_at", "read_at", "warned_reset_at", "warned_at",
              "paused_reset_at"),
    # Version 6 (v0.6.16-beta.4): a person's own wording, by capability and key.
    "wordings": ("capability", "choice", "words", "changed_at"),
    # Stage 4 (v0.6.16-beta.4): a turn run here, and the Dashboard's chat.
    "headless_runs": ("interruption_id", "capability", "thread_id", "started_at", "ends_by", "stop_requested_at",
                      "ended_at", "end", "restore_model"),
    "chat_messages": ("chat_id", "thread_id", "words", "state", "reason", "record_id", "created_at", "sent_at",
                      "finished_at"),
    # Version 8 (v0.6.19, the groundwork): the stage's ten.
    "usage_samples": ("bucket", "minutes", "at", "used_percent", "reset_at"),
    "token_days": ("day", "thread_id", "project_digest", "input", "cached", "output", "reasoning", "turns"),
    "token_files": ("file_digest", "thread_id", "size", "offset", "mtime_ns", "read_at"),
    "outbox": ("item_id", "channel", "event", "category", "alias", "at", "tries", "state", "finished_at"),
    "feed": ("singleton", "checked_at", "word", "codex_word", "incidents"),
    "remote": ("channel", "paired_at", "bad_codes", "update_offset", "code_digest", "code_expires_at"),
    "opens": ("open_id", "thread_id", "record_id", "at", "outcome"),
    "restarts": ("at", "exit_code", "restarted"),
    "account_seen": ("singleton", "identity_digest", "plan", "read_at"),
    "hook_claims": ("interruption_id", "turn_digest", "at", "outcome"),
    # Version 9 (v0.6.20, issue #50): the steers.
    "steers": ("steer_id", "thread_id", "words", "client_id", "state", "reason", "created_at", "finished_at"),
}
# Version 9's (v0.6.20).
V020_TABLES = ("steers",)
# Version 8's tables, as v0.6.19 left them: what a version-9 file holds for a version-8 reader, and the shape the step to
# version 9 is taken from.
TABLES_V8 = {name: columns for name, columns in TABLES.items() if name not in V020_TABLES}
# Version 8's (v0.6.19).
V019_TABLES = ("usage_samples", "token_days", "token_files", "outbox", "feed", "remote", "opens", "restarts",
               "account_seen", "hook_claims")
# Version 7's tables, as stage 4 left them and v0.6.17 and v0.6.18 kept them: what every older shape is taken from, and
# what a version-8 file holds for a version-7 reader (holds).
TABLES_V7 = dict({name: columns for name, columns in TABLES_V8.items() if name not in V019_TABLES},
                 prompts=TABLES["prompts"][:-1])
V4_TABLES = ("continuations", "keep_going", "prompts")
# Version 5's (v0.6.16-beta.3).
V5_TABLES = ("meter",)
# Version 6's (v0.6.16-beta.4).
V6_TABLES = ("wordings",)
# The longest wording kept: the custom continuation text's own bound (core's continuation.MAX_CUSTOM_LENGTH).
WORDING_LIMIT = 2000
# Stage 4's (v0.6.16-beta.4).
STAGE4_TABLES = ("headless_runs", "chat_messages")
# The capabilities whose turns `headless_runs` holds.
HEADLESS_CAPABILITIES = ("headless_run", "compact_continue", "model_fallback")
# A model's name at most, as Codex says it (codex/headless.py reads no longer one): what a fallback turn owes back.
MODEL_NAME = 128
# A chat message's words at most (A27's length).
CHAT_WORDS = 2000
# The reset actions' tables, the last four of version 3 (v0.6.14).
RESET_TABLES = ("windows", "readings", "reset_rules", "credit_spends")
# The buckets a usage window is kept under (core's domain/usage.BUCKETS), and the capabilities whose
# rules `reset_rules` holds (registry.RESET_CREDIT, RESET_MESSAGE).
BUCKETS = ("codex", "premium", "legacy", "other")
RESET_CAPABILITIES = ("reset_credit", "reset_message")
# The capabilities whose continuations `continuations` holds (v0.6.15-beta).
CONTINUATION_CAPABILITIES = ("empty_response", "subagent_parent", "keep_going", "usage_wrap_up",
                             # v0.6.16-beta.4 (version 6): the forced stop's continuation after the reset.
                             "usage_pause")
# The tables version 2 had: v0.6.11's and v0.6.12's file.
# `records` before version 4 added its last two columns (queue_id, withdraw).
RECORDS_V3 = TABLES["records"][:-2]
TABLES_V2 = dict({name: TABLES[name] for name in ("meta", "arming", "spend", "overrides", "journal", "sampler")},
                 records=RECORDS_V3)


def _one_of(column, words) -> str:
    return "CHECK (%s IN (%s))" % (column, ", ".join("'%s'" % word for word in words))


def readable_from(connection, version) -> int:
    """The oldest version whose reader may use the file `connection` holds, at user_version `version`: the mark's
    (READABLE_FROM), or `version` itself where the file has none - every file v0.6.16 and earlier wrote."""
    found = connection.execute("PRAGMA application_id").fetchone()[0]
    return found & ~_MARK_HALF if found & _MARK_HALF == MARK else version


def holds(tables, known) -> bool:
    """Whether `tables` (name: columns, as found) holds every table of `known` with at least its columns, first: what a
    newer file marked readable from this version must, for this version to use it."""
    return all(tables.get(name, ())[:len(columns)] == columns for name, columns in known.items())


def names_checked(connection) -> bool:
    """Whether `options` as stored still has the CHECK on its names that v0.6.16 and earlier made it with."""
    stored = connection.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='options'").fetchone()
    return stored is not None and re.search(r"CHECK\s*\(\s*choice\s+IN\b", stored[0], re.I) is not None


# The names `options` admitted while a CHECK named them (versions 3 to 7), frozen as v0.6.16 left them: what its file
# refuses, and what a test builds an older file from. OptionKey may grow; this does not.
V7_OPTION_WORDS = ("attempts", "ceiling_hours", "workers", "days", "poll_minutes", "warn_five_hour", "warn_weekly",
                   "wrap_five_hour", "wrap_weekly", "wrap_style", "pause_five_hour", "pause_weekly", "window_five_hour",
                   "window_weekly", "stop_words_five_hour", "stop_words_weekly", "wrap_reset_time", "wrap_after_reset",
                   "keep_on", "send_again")


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
    )""" % _one_of("choice", V7_OPTION_WORDS),
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

# Version 4's own columns (v0.6.15-beta): the queue item a record's send was taken as, and a person's Cancel of one
# already in Codex's queue, for core to take back (the owner's answer of 2026-10-09).
_KEY = "CHECK (%s IS NULL OR (length(%s) = 64 AND %s NOT GLOB '*[^0-9a-f]*'))"
_UUID = "CHECK (length(thread_id) = 36 AND thread_id NOT GLOB '*[^0-9a-f-]*')"
# The longest a recurring prompt's series runs, from when it was written.
PROMPT_SPAN = 30 * 86400
_STATEMENTS_V4 = (
    "ALTER TABLE records ADD COLUMN queue_id TEXT CHECK (queue_id IS NULL OR (length(queue_id) = 36 AND "
    "queue_id NOT GLOB '*[^0-9a-f-]*'))",
    "ALTER TABLE records ADD COLUMN withdraw INTEGER NOT NULL DEFAULT 0 CHECK (withdraw IN (0, 1))",
    # One row for each continuation the edition made or chose not to (an empty reply, a subagent's stop, a
    # conversation kept going), keyed by what it answers - so one turn is answered once - and its words, the
    # catalog's, kept only until it is sent.
    """CREATE TABLE continuations (
        answer_id TEXT PRIMARY KEY %s,
        capability TEXT NOT NULL %s,
        kind TEXT NOT NULL %s,
        thread_id TEXT NOT NULL %s,
        record_id TEXT %s,
        ordinal INTEGER %s,
        words TEXT CHECK (words IS NULL OR (typeof(words) = 'text' AND length(words) BETWEEN 1 AND 2000)),
        chain INTEGER NOT NULL %s,
        created_at REAL NOT NULL,
        finished_at REAL,
        reason TEXT CHECK (reason IS NULL OR reason IN (%s)),
        launching_at REAL,
        CHECK (words IS NULL OR finished_at IS NULL)
    )""" % (_KEY % ("answer_id", "answer_id", "answer_id"), _one_of("capability", CONTINUATION_CAPABILITIES),
            _one_of("kind", ContinuationKind), _UUID,
            _KEY % ("record_id", "record_id", "record_id"), _int("ordinal"), _int("chain", null=False),
            ", ".join("'%s'" % word for word in ContinuationReason)),
    "CREATE INDEX continuations_thread ON continuations(thread_id)",
    # The conversations a person picked to keep going after a turn that ended well, each with how many continuations
    # it may have, and how many it had.
    """CREATE TABLE keep_going (
        thread_id TEXT PRIMARY KEY %s,
        count INTEGER NOT NULL %s,
        used INTEGER NOT NULL %s,
        armed_at REAL NOT NULL,
        state TEXT NOT NULL %s,
        reason TEXT CHECK (reason IS NULL OR reason IN (%s)),
        finished_at REAL,
        CHECK (used <= count)
    )""" % (_UUID, _int("count", low=1, high=10, null=False), _int("used", null=False), _one_of("state", KeepState),
            ", ".join("'%s'" % word for word in KeepReason)),
    # A person's queued prompts: after the turn now running, at a time, or on a schedule - their words only while one
    # is still to go, a series 30 occurrences and 30 days at most. Its reasons are the vocabulary's (PromptReason) -
    # made again with them in version 8 (UPGRADE_TO_V019); a test builds a version-7 file with V7_PROMPT_REASONS.
    """CREATE TABLE prompts (
        prompt_id INTEGER PRIMARY KEY AUTOINCREMENT,
        thread_id TEXT NOT NULL %s,
        words TEXT,
        trigger TEXT NOT NULL %s,
        at REAL,
        every TEXT CHECK (every IS NULL OR every IN (%s)),
        occurrences INTEGER NOT NULL %s,
        sent_count INTEGER NOT NULL %s,
        until REAL,
        depends INTEGER NOT NULL %s,
        position INTEGER NOT NULL %s,
        state TEXT NOT NULL %s,
        reason TEXT CHECK (reason IS NULL OR reason IN (%s)),
        record_id TEXT %s,
        gate TEXT %s,
        gate_reason TEXT %s,
        created_at REAL NOT NULL,
        due_at REAL,
        launching_at REAL,
        sent_at REAL,
        finished_at REAL,
        CHECK (words IS NULL OR (state IN ('%s', '%s', '%s') AND typeof(words) = 'text'
                                 AND length(words) BETWEEN 1 AND 8192)),
        CHECK (occurrences = 1 OR trigger = '%s'),
        CHECK ((every IS NULL) = (trigger <> '%s')),
        CHECK (until IS NULL OR until - created_at <= %d),
        CHECK (sent_count <= occurrences)
    )""" % (_UUID, _one_of("trigger", PromptTrigger), ", ".join("'%s'" % word for word in PromptEvery),
            _int("occurrences", low=1, high=30, null=False), _int("sent_count", null=False), _flag("depends"),
            _int("position", null=False), _one_of("state", PromptState),
            ", ".join("'%s'" % word for word in PromptReason), _KEY % ("record_id", "record_id", "record_id"),
            _gate_word("gate"), _gate_word("gate_reason"), PromptState.WAITING, PromptState.READY, PromptState.HELD,
            PromptTrigger.RECURRING, PromptTrigger.RECURRING, PROMPT_SPAN),
    "CREATE INDEX prompts_thread ON prompts(thread_id, position)",
)
# Version 5's own table (v0.6.16-beta.3): the usage meter's last reading of each window. Whole seconds as Codex gives
# them for a reset; the share as Codex gives it, 0 or more.
_STATEMENTS_V5 = (
    """CREATE TABLE meter (
        bucket TEXT NOT NULL %s,
        minutes INTEGER NOT NULL %s,
        used_percent REAL NOT NULL CHECK (typeof(used_percent) IN ('real', 'integer') AND used_percent >= 0),
        reset_at INTEGER %s,
        read_at REAL NOT NULL,
        warned_reset_at INTEGER %s,
        warned_at REAL,
        paused_reset_at INTEGER %s,
        PRIMARY KEY (bucket, minutes)
    )""" % (_one_of("bucket", BUCKETS), _int("minutes", low=1, high=100800, null=False), _int("reset_at"),
            _int("warned_reset_at"), _int("paused_reset_at")),
)
# Version 6's own table (v0.6.16-beta.4): a person's own wording, text a person wrote and nothing else.
_STATEMENTS_V6 = (
    """CREATE TABLE wordings (
        capability TEXT NOT NULL,
        choice TEXT NOT NULL %s,
        words TEXT NOT NULL CHECK (typeof(words) = 'text' AND length(words) BETWEEN 1 AND %d),
        changed_at REAL NOT NULL,
        PRIMARY KEY (capability, choice)
    )""" % (_one_of("choice", WordingKey), WORDING_LIMIT),
)
# Stage 4's two tables (v0.6.16-beta.4): added, nothing remade.
_STATEMENTS_STAGE4 = (
    """CREATE TABLE headless_runs (
        interruption_id TEXT PRIMARY KEY %s,
        capability TEXT NOT NULL %s,
        thread_id TEXT NOT NULL %s,
        started_at REAL NOT NULL,
        ends_by REAL NOT NULL,
        stop_requested_at REAL,
        ended_at REAL,
        end TEXT CHECK (end IS NULL OR end IN (%s)),
        restore_model TEXT CHECK (restore_model IS NULL OR (typeof(restore_model) = 'text'
                                  AND length(restore_model) BETWEEN 1 AND %d AND capability = 'model_fallback')),
        CHECK ((end IS NULL) = (ended_at IS NULL))
    )""" % ("CHECK (length(interruption_id) = 64 AND interruption_id NOT GLOB '*[^0-9a-f]*')",
            _one_of("capability", HEADLESS_CAPABILITIES), _UUID, ", ".join("'%s'" % word for word in RunEnd),
            MODEL_NAME),
    """CREATE TABLE chat_messages (
        chat_id INTEGER PRIMARY KEY AUTOINCREMENT,
        thread_id TEXT NOT NULL %s,
        words TEXT CHECK (words IS NULL OR (typeof(words) = 'text' AND length(words) BETWEEN 1 AND %d)),
        state TEXT NOT NULL %s,
        reason TEXT CHECK (reason IS NULL OR reason IN (%s)),
        record_id TEXT NOT NULL UNIQUE %s,
        created_at REAL NOT NULL,
        sent_at REAL,
        finished_at REAL,
        CHECK (words IS NULL OR state = '%s')
    )""" % (_UUID, CHAT_WORDS, _one_of("state", ChatState), ", ".join("'%s'" % word for word in ChatReason),
            "CHECK (length(record_id) = 64 AND record_id NOT GLOB '*[^0-9a-f]*')", ChatState.WAITING),
    "CREATE INDEX chat_messages_thread ON chat_messages(thread_id, chat_id)",
)
# `options` as v0.6.17 makes it: its names the code's to check, its values still the file's too.
_OPTIONS_FREE = """CREATE TABLE options (
        capability TEXT NOT NULL,
        choice TEXT NOT NULL,
        value INTEGER NOT NULL CHECK (typeof(value) = 'integer' AND value >= 1),
        PRIMARY KEY (capability, choice)
    )"""
# `wordings` as version 8 makes it (v0.6.19): its keys the code's to check (WordingKey), its words still the file's too.
_WORDINGS_FREE = """CREATE TABLE wordings (
        capability TEXT NOT NULL,
        choice TEXT NOT NULL,
        words TEXT NOT NULL CHECK (typeof(words) = 'text' AND length(words) BETWEEN 1 AND %d),
        changed_at REAL NOT NULL,
        PRIMARY KEY (capability, choice)
    )""" % WORDING_LIMIT
# The reasons `prompts` admitted (versions 4 to 7) and the keys `wordings` did (6 and 7), frozen as v0.6.18 left them:
# what a version-7 file refuses, and what a test builds one from. PromptReason and WordingKey may grow; these do not.
V7_PROMPT_REASONS = ("delivered", "handed_over", "superseded", "expired", "missed", "dependency_failed", "by_person",
                     "turned_off", "too_long", "conversation_off", "withdrawn", "withdraw_refused", "unknown")
V7_WORDING_KEYS = ("wrap_custom_five_hour", "wrap_custom_weekly")
_PROMPTS_V4 = next(s for s in _STATEMENTS_V4 if s.lstrip().startswith("CREATE TABLE prompts"))
_PROMPTS_INDEX = "CREATE INDEX prompts_thread ON prompts(thread_id, position)"
_REASONS_NOW = "reason TEXT CHECK (reason IS NULL OR reason IN (%s))" % ", ".join("'%s'" % w for w in PromptReason)
_PROMPTS_V7 = _PROMPTS_V4.replace(_REASONS_NOW, "reason TEXT CHECK (reason IS NULL OR reason IN (%s))"
                                  % ", ".join("'%s'" % word for word in V7_PROMPT_REASONS), 1)
_WORDINGS_V7 = _STATEMENTS_V6[0].replace(_one_of("choice", WordingKey), _one_of("choice", V7_WORDING_KEYS), 1)

# Version 8's own (v0.6.19, the groundwork). Ids, enums, counts and times, each word one of the vocabulary's, each id or
# digest of its shape - never a path, a name, an address or anything a person or Codex wrote. Nothing is added to any
# of them until a capability that writes it is built.
_HEX16 = "CHECK (%s IS NULL OR (length(%s) = 16 AND %s NOT GLOB '*[^0-9a-f]*'))"
_HEX64 = "CHECK (length(%s) = 64 AND %s NOT GLOB '*[^0-9a-f]*')"
# A pushed notice names its conversation only as its place in Pending: `task 1` to `task 9999`.
_ALIAS = ("CHECK (alias IS NULL OR (length(alias) BETWEEN 6 AND 9 AND alias GLOB 'task [1-9]*' "
          "AND substr(alias, 6) NOT GLOB '*[^0-9]*'))")
# The one remote channel there is (telegram_remote), of the courier's channels.
REMOTE_CHANNELS = (CourierChannel.TELEGRAM,)
_STATEMENTS_V019 = (
    "ALTER TABLE prompts ADD COLUMN while_running TEXT NOT NULL DEFAULT '%s' %s"
    % (WhileRunning.QUEUE, _one_of("while_running", WhileRunning)),
    """CREATE TABLE usage_samples (
        bucket TEXT NOT NULL %s,
        minutes INTEGER NOT NULL %s,
        at REAL NOT NULL,
        used_percent REAL NOT NULL CHECK (typeof(used_percent) IN ('real', 'integer') AND used_percent >= 0),
        reset_at INTEGER %s,
        PRIMARY KEY (bucket, minutes, at)
    )""" % (_one_of("bucket", BUCKETS), _int("minutes", low=1, high=100800, null=False), _int("reset_at")),
    "CREATE INDEX usage_samples_at ON usage_samples(at)",
    """CREATE TABLE token_days (
        day TEXT NOT NULL CHECK (length(day) = 10 AND day GLOB '[0-9][0-9][0-9][0-9]-[01][0-9]-[0-3][0-9]'),
        thread_id TEXT NOT NULL %s,
        project_digest TEXT %s,
        input INTEGER NOT NULL %s,
        cached INTEGER NOT NULL %s,
        output INTEGER NOT NULL %s,
        reasoning INTEGER NOT NULL %s,
        turns INTEGER NOT NULL %s,
        PRIMARY KEY (day, thread_id)
    )""" % (_UUID, _HEX16 % (("project_digest",) * 3),
            *(_int(name, null=False) for name in ("input", "cached", "output", "reasoning", "turns"))),
    """CREATE TABLE token_files (
        file_digest TEXT PRIMARY KEY CHECK (length(file_digest) = 16 AND file_digest NOT GLOB '*[^0-9a-f]*'),
        thread_id TEXT NOT NULL %s,
        size INTEGER NOT NULL %s,
        offset INTEGER NOT NULL %s,
        mtime_ns INTEGER NOT NULL %s,
        read_at REAL NOT NULL
    )""" % (_UUID, _int("size", null=False), _int("offset", null=False), _int("mtime_ns", null=False)),
    """CREATE TABLE outbox (
        item_id INTEGER PRIMARY KEY AUTOINCREMENT,
        channel TEXT NOT NULL %s,
        event TEXT NOT NULL %s,
        category TEXT CHECK (category IS NULL OR category IN (%s)),
        alias TEXT %s,
        at REAL NOT NULL,
        tries INTEGER NOT NULL %s,
        state TEXT NOT NULL %s,
        finished_at REAL,
        CHECK ((state = '%s') = (finished_at IS NULL))
    )""" % (_one_of("channel", CourierChannel), _one_of("event", CourierEvent),
            ", ".join("'%s'" % word for word in sorted(failures.CATEGORIES)), _ALIAS,
            _int("tries", high=3, null=False), _one_of("state", OutboxState), OutboxState.WAITING),
    "CREATE INDEX outbox_at ON outbox(at)",
    """CREATE TABLE feed (
        singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
        checked_at REAL,
        word TEXT CHECK (word IS NULL OR word IN (%s)),
        codex_word TEXT CHECK (codex_word IS NULL OR codex_word IN (%s)),
        incidents INTEGER %s
    )""" % (", ".join("'%s'" % word for word in FeedWord), ", ".join("'%s'" % word for word in FeedWord),
            _int("incidents", high=99)),
    """CREATE TABLE remote (
        channel TEXT PRIMARY KEY %s,
        paired_at REAL,
        bad_codes INTEGER NOT NULL DEFAULT 0 %s,
        update_offset INTEGER %s,
        code_digest TEXT CHECK (code_digest IS NULL OR (length(code_digest) = 64
                                AND code_digest NOT GLOB '*[^0-9a-f]*')),
        code_expires_at REAL,
        CHECK (code_digest IS NULL OR paired_at IS NULL)
    )""" % (_one_of("channel", REMOTE_CHANNELS), _int("bad_codes", high=5, null=False), _int("update_offset")),
    """CREATE TABLE opens (
        open_id INTEGER PRIMARY KEY AUTOINCREMENT,
        thread_id TEXT NOT NULL %s,
        record_id TEXT NOT NULL %s,
        at REAL NOT NULL,
        outcome TEXT NOT NULL %s
    )""" % (_UUID, _HEX64 % ("record_id", "record_id"), _one_of("outcome", OpenOutcome)),
    "CREATE INDEX opens_at ON opens(at)",
    """CREATE TABLE restarts (
        at REAL PRIMARY KEY,
        exit_code INTEGER CHECK (exit_code IS NULL OR typeof(exit_code) = 'integer'),
        restarted INTEGER NOT NULL %s
    )""" % _flag("restarted"),
    """CREATE TABLE account_seen (
        singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
        identity_digest TEXT %s,
        plan TEXT CHECK (plan IS NULL OR plan IN (%s)),
        read_at REAL NOT NULL
    )""" % (_HEX16 % (("identity_digest",) * 3), ", ".join("'%s'" % word for word in PlanWord)),
    """CREATE TABLE hook_claims (
        interruption_id TEXT PRIMARY KEY %s,
        turn_digest TEXT NOT NULL %s,
        at REAL NOT NULL,
        outcome TEXT NOT NULL %s
    )""" % (_HEX64 % ("interruption_id", "interruption_id"), _HEX64 % ("turn_digest", "turn_digest"),
            _one_of("outcome", HookOutcome)),
    "CREATE INDEX hook_claims_at ON hook_claims(at)",
)
# Version 9's own (v0.6.20): the steers. The words are the person's own, at most a queued message's (WORDS_LIMIT in
# state/prompts.py) and never a control character but a line break or a tab; a settled steer has its time, a waiting
# one none; only a refusal has a reason.
STEER_WORDS = 8192
_STATEMENTS_V020 = (
    """CREATE TABLE steers (
        steer_id INTEGER PRIMARY KEY AUTOINCREMENT,
        thread_id TEXT NOT NULL %s,
        words TEXT NOT NULL CHECK (length(words) BETWEEN 1 AND %d),
        client_id TEXT NOT NULL CHECK (length(client_id) = 36 AND client_id NOT GLOB '*[^0-9a-f-]*'),
        state TEXT NOT NULL %s,
        reason TEXT CHECK (reason IS NULL OR reason IN (%s)),
        created_at REAL NOT NULL,
        finished_at REAL,
        CHECK ((state IN ('%s', '%s')) = (finished_at IS NULL)),
        CHECK ((state = '%s') = (reason IS NOT NULL))
    )""" % (_UUID, STEER_WORDS, _one_of("state", SteerState), ", ".join("'%s'" % word for word in SteerReason),
            SteerState.REQUESTED, SteerState.SENDING, SteerState.REFUSED),
    "CREATE INDEX steers_created ON steers(created_at)",
)
_STATEMENTS_V7 = _STATEMENTS_V2 + _STATEMENTS_V3 + _STATEMENTS_V4 + _STATEMENTS_V5 + _STATEMENTS_V6 + _STATEMENTS_STAGE4
MARKED = "PRAGMA application_id=%d" % (MARK | READABLE_FROM)
_FREED = {id(_STATEMENTS_V3[0]): _OPTIONS_FREE, id(_STATEMENTS_V6[0]): _WORDINGS_FREE}
STATEMENTS = (tuple(_FREED.get(id(statement), statement) for statement in _STATEMENTS_V7) + _STATEMENTS_V019
              + _STATEMENTS_V020 + (MARKED, "PRAGMA user_version=%d" % SCHEMA_VERSION))
# The file exactly as v0.6.16 made it - its `options` CHECK on names, no mark, and the reasons and keys version 7 knew:
# what a test builds the file before from.
STATEMENTS_V7 = (tuple(_PROMPTS_V7 if statement is _PROMPTS_V4 else _WORDINGS_V7 if statement is _STATEMENTS_V6[0]
                       else statement for statement in _STATEMENTS_V7)
                 + ("PRAGMA user_version=%d" % STAGE4_VERSION,))
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
STATEMENTS_V3 = _STATEMENTS_V2 + _STATEMENTS_V3 + ("PRAGMA user_version=3",)
# A version-3 file a pre-release build made before the reset actions' tables (v0.6.14): those four
# added, every row kept, its version unchanged.
TABLES_V3_BEFORE_RESETS = dict({name: TABLES_V7[name] for name in TABLES_V7
                                if name not in RESET_TABLES + V4_TABLES + V5_TABLES + V6_TABLES + STAGE4_TABLES},
                               records=RECORDS_V3)
ADD_RESETS = _STATEMENTS_RESETS
# Version 4 (v0.6.15-beta): the tables whose CHECKs name a closed list that grew are made again with the new list, every
# row kept - SQLite cannot change a CHECK in place - and the tables of 3c added. A version-3 file is brought to it.
TABLES_V3 = {name: columns for name, columns in dict(TABLES_V7, records=RECORDS_V3).items()
             if name not in V4_TABLES + V5_TABLES + V6_TABLES + STAGE4_TABLES}
# The choices version 4 added to `options` (OptionKey): what a version-3 file's CHECK refuses.
V4_OPTION_WORDS = ("workers", "days")
# And to `overrides`.
V4_OVERRIDE_WORDS = ("queue_for_open",)


def _remade(statement, table, columns, index=None, suffix="v4") -> tuple:
    """The statements that make `table` again from `statement`, its CREATE as this version writes it, every row kept."""
    made = (statement.replace("CREATE TABLE %s (" % table, "CREATE TABLE %s_%s (" % (table, suffix), 1),
            "INSERT INTO %s_%s (%s) SELECT %s FROM %s" % (table, suffix, ", ".join(columns), ", ".join(columns), table),
            "DROP TABLE %s" % table,
            "ALTER TABLE %s_%s RENAME TO %s" % (table, suffix, table))
    return made + ((index,) if index else ())


UPGRADE_FROM_3 = (
    _remade(_STATEMENTS_V3[0], "options", TABLES["options"])
    + _remade(next(s for s in _STATEMENTS_V2 if s.lstrip().startswith("CREATE TABLE overrides")), "overrides",
              TABLES["overrides"])
    + _remade(next(s for s in _STATEMENTS_RESETS if s.lstrip().startswith("CREATE TABLE reset_rules")), "reset_rules",
              TABLES["reset_rules"], "CREATE INDEX reset_rules_state ON reset_rules(state)")
    + _STATEMENTS_V4 + ("PRAGMA user_version=4",))

# Version 5 (v0.6.16-beta.3, issue #29): `options` and `continuations` made again with their wider lists, every row kept,
# and the meter's table added. A version-4 file is brought to it; a version-3 one takes UPGRADE_FROM_3 first.
TABLES_V4 = {name: columns for name, columns in TABLES_V7.items() if name not in V5_TABLES + V6_TABLES + STAGE4_TABLES}
# The choices version 5 added to `options` (OptionKey), and the words to `continuations`: what a version-4 file refuses.
V5_OPTION_WORDS = ("poll_minutes", "warn_five_hour", "warn_weekly", "wrap_five_hour", "wrap_weekly", "wrap_style",
                   "pause_five_hour", "pause_weekly")
V5_CONTINUATION_WORDS = ("usage_wrap_up", "wrap_up")
UPGRADE_FROM_4 = (
    _remade(_STATEMENTS_V3[0], "options", TABLES["options"], suffix="v5")
    + _remade(next(s for s in _STATEMENTS_V4 if s.lstrip().startswith("CREATE TABLE continuations")), "continuations",
              TABLES["continuations"], "CREATE INDEX continuations_thread ON continuations(thread_id)", suffix="v5")
    + _STATEMENTS_V5 + ("PRAGMA user_version=5",))

# Version 6 (v0.6.16-beta.4): `options` and `continuations` made again with their wider lists, every row kept, and the
# wordings' table added. A version-5 file is brought to it; an older one takes the earlier steps first.
TABLES_V5 = {name: columns for name, columns in TABLES_V7.items() if name not in V6_TABLES + STAGE4_TABLES}
# The choices version 6 added to `options` (OptionKey), and the kind to `continuations`: what a version-5 file refuses.
V6_OPTION_WORDS = ("window_five_hour", "window_weekly", "stop_words_five_hour", "stop_words_weekly", "wrap_reset_time",
                   "wrap_after_reset")
V6_CONTINUATION_WORDS = ("after_reset", "usage_pause")
UPGRADE_FROM_5 = (
    _remade(_STATEMENTS_V3[0], "options", TABLES["options"], suffix="v6")
    + _remade(next(s for s in _STATEMENTS_V4 if s.lstrip().startswith("CREATE TABLE continuations")), "continuations",
              TABLES["continuations"], "CREATE INDEX continuations_thread ON continuations(thread_id)", suffix="v6")
    + _STATEMENTS_V6 + ("PRAGMA user_version=6",))
# Stage 4 (v0.6.16-beta.4): the version before it, and the step from it - two tables added, every row kept.
TABLES_BEFORE_STAGE4 = {name: columns for name, columns in TABLES_V7.items() if name not in STAGE4_TABLES}
UPGRADE_TO_STAGE4 = _STATEMENTS_STAGE4 + ("PRAGMA user_version=%d" % STAGE4_VERSION,)
STATEMENTS_BEFORE_STAGE4 = (_STATEMENTS_V2 + _STATEMENTS_V3 + _STATEMENTS_V4 + _STATEMENTS_V5 + _STATEMENTS_V6
                            + ("PRAGMA user_version=%d" % (STAGE4_VERSION - 1),))
# v0.6.17: `options` made again without the CHECK on its names, every row kept, and the file marked readable from
# READABLE_FROM - its version left at 7. Taken while names_checked, in the opening's one transaction, so a run cut short
# leaves the old table whole, to be made again at the next opening.
FREE_OPTIONS = _remade(_OPTIONS_FREE, "options", TABLES["options"], suffix="free") + (MARKED,)


def wordings_checked(connection) -> bool:
    """Whether `wordings` as stored still has the CHECK on its keys that versions 6 and 7 made it with."""
    stored = connection.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='wordings'").fetchone()
    return stored is not None and re.search(r"CHECK\s*\(\s*choice\s+IN\b", stored[0], re.I) is not None


# Version 8 (v0.6.19, the groundwork): a version-7 file - v0.6.16's, v0.6.17's or v0.6.18's - is brought to it by one
# step: `prompts` made again with the reasons this version knows (PromptReason turn_running; every row kept, its index
# made again), the column at its end added with its default - so every prompt already queued goes into Codex's queue as
# it always did - and the ten tables added; nothing else is made again. `wordings` is freed after the step, as `options`
# is: while its stored CREATE still names its keys (wordings_checked), in the opening's one transaction.
UPGRADE_TO_V019 = (_remade(_PROMPTS_V4, "prompts", TABLES_V7["prompts"], _PROMPTS_INDEX, suffix="v8")
                   + _STATEMENTS_V019 + ("PRAGMA user_version=%d" % V019_VERSION,))
FREE_WORDINGS = _remade(_WORDINGS_FREE, "wordings", TABLES["wordings"], suffix="free")
# Version 9 (v0.6.20, steer_send): a version-8 file - v0.6.19's - is brought to it by one step, the steers' table added;
# nothing else is made again, and the mark stays readable from 7.
UPGRADE_TO_V020 = _STATEMENTS_V020 + ("PRAGMA user_version=%d" % V020_VERSION,)
