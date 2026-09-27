"""The columns each schema version has, in the order they are written.

`RECORD_COLUMNS` is the order rows are inserted in and `MUTABLE` is what `update` may change;
both are read by the validator and by the golden, so a column added here shows up in the diff
of `tests/fixtures/schema.json` in the same commit.
"""
from __future__ import annotations

from ..machine import OBSERVING


# Schema 1 and 2 columns, in their original order.
_V2_COLUMNS = (
    "interruption_id", "thread_id", "turn_id", "completed_at", "started_at", "ordinal",
    "detected_at", "reset_at", "limit_type", "uncertain", "state", "retry_count",
    "next_retry_at", "resumed_at", "last_error", "marker", "queue_id", "submitted_at",
    "attempt_count", "cancel_requested", "category", "recovery_attempts", "no_progress_count",
)

# Columns added in schema 2. Existing rows are usage-limit records by definition,
# because that was the only thing schema 1 could ever record.
_SCHEMA_2_COLUMNS = (
    ("category", "TEXT NOT NULL DEFAULT 'usage_limit'"),
    ("recovery_attempts", "INTEGER NOT NULL DEFAULT 0"),
    ("no_progress_count", "INTEGER NOT NULL DEFAULT 0"),
)

# Columns added in schema 3. All content-free: ids, enums, counters and times.
_SCHEMA_3_COLUMNS = (
    ("recovery_turn_id", "TEXT"),
    ("recovery_client_id", "TEXT"),
    ("recovery_turn_status", "TEXT"),
    ("user_joined", "INTEGER NOT NULL DEFAULT 0"),
    ("after_user_work", "INTEGER NOT NULL DEFAULT 0"),
    ("legacy", "INTEGER NOT NULL DEFAULT 0"),
    ("withdraw_reason", "TEXT"),
    ("withdrawn_at", "REAL"),
    ("withdraw_deleted", "INTEGER NOT NULL DEFAULT 0"),
    ("withdraw_failures", "INTEGER NOT NULL DEFAULT 0"),
    ("turn_started_at", "REAL"),
    ("outcome_at", "REAL"),
    ("first_queued_at", "REAL"),
    ("last_claim_at", "REAL"),
    ("parent_interruption_id", "TEXT"),
    ("chain_origin_id", "TEXT NOT NULL DEFAULT ''"),
    ("chain_first_detected_at", "REAL NOT NULL DEFAULT 0"),
    ("chain_continuations", "INTEGER NOT NULL DEFAULT 0"),
    ("budget_resets", "INTEGER NOT NULL DEFAULT 0"),
    ("retry_now_count", "INTEGER NOT NULL DEFAULT 0"),
    ("usage_unavailable_seconds", "REAL NOT NULL DEFAULT 0"),
    ("usage_probe_at", "REAL"),
    ("gate_eval", "TEXT"),
    ("gate_eval_at", "REAL"),
    ("history_hidden_at", "REAL"),
)

_V3_COLUMNS = _V2_COLUMNS + tuple(name for name, _ in _SCHEMA_3_COLUMNS)

# Columns added in schema 4 (v0.6.11), each to the table it names. Content-free like the rest: a
# time, a word from a closed list, a flag. Every one is empty - or 0 - on a record, a conversation
# and a state that nobody has postponed, held, given a tier or put in observe-only, which is every
# one at the defaults: the state v0.6.10 kept, with nothing added to it (tests/test_schema_v4.py).
_SCHEMA_4_COLUMNS = (
    ("interruptions", "not_before", "REAL"),
    ("interruptions", "hold", "TEXT"),
    ("threads", "tier", "TEXT"),
    ("settings", "observe_only", "INTEGER NOT NULL DEFAULT 0 CHECK (observe_only IN (0, 1))"),
    # What the two guards keep of a record (guards.py): a digest of what its task was working with,
    # and its conversation's token count. Empty unless a guard was on when it was detected.
    ("interruptions", "task_print", "TEXT"),
    ("interruptions", "context_tokens", "INTEGER"),
    # When a record's objection window opened (engine/announce.py), which happens once, before its
    # first send: a postponement made before then only holds it back, and the window still opens
    # after it. Empty unless its conversation's tier is the objection window.
    ("interruptions", "objection_at", "REAL"),
    # The last usage reading the watcher made (domain/usage.py): when, and its allowlisted windows as
    # compact JSON - numbers, times and two closed words. Empty until a recovery was due and usage was
    # read for it, which is the only time it ever is (C4, C9).
    ("watcher_status", "usage_at", "REAL"),
    ("watcher_status", "usage", "TEXT"),
)

_RECORD_COLUMNS = _V3_COLUMNS + tuple(name for table, name, _ in _SCHEMA_4_COLUMNS
                                      if table == "interruptions")

_SETTINGS_COLUMNS = ("singleton", "enabled", "armed_at", "poll_seconds", "observe_only")

_THREAD_COLUMNS = ("thread_id", "enabled", "tier")

# Schema 4's needs-you notices: one row per failure that needs a person, or turn that stopped moving,
# raised once. Ids, its kind (needsyou.NOTICE_KINDS), times - and nothing the engine's dispatch ever
# reads (tests/test_schema_v4.py).
_NOTICE_COLUMNS = ("interruption_id", "thread_id", "category", "raised_at", "seen_at")

# Core's tables that nothing deciding a send may read: the claim refuses its ledger any read of
# them (store/ledger.py), and core's own dispatch reads none (tests/test_schema_v4.py).
_UNREAD_BY_DISPATCH = frozenset({"notices"})

_EVENT_COLUMNS = ("event_id", "at", "interruption_id", "chain_origin_id", "code", "from_state",
                  "to_state", "reason", "actor", "turn_ref", "flags", "value")

_WATCHER_COLUMNS = ("singleton", "pid", "session_id", "started_at", "last_tick_at",
                    "last_tick_ok", "engine_state", "code_version", "usage_at", "usage")

# Fields a plain `update` may write. Chain linkage, the claim time and the history
# flag are written only by the operations that own them.
_MUTABLE = frozenset({
    "reset_at", "limit_type", "uncertain", "state", "retry_count", "next_retry_at",
    "resumed_at", "last_error", "queue_id", "submitted_at", "attempt_count",
    "cancel_requested", "recovery_attempts", "no_progress_count",
    "recovery_turn_id", "recovery_client_id", "recovery_turn_status", "user_joined",
    "after_user_work", "withdraw_reason", "withdrawn_at", "withdraw_deleted",
    "withdraw_failures", "turn_started_at", "outcome_at", "first_queued_at",
    "usage_unavailable_seconds", "usage_probe_at", "gate_eval", "gate_eval_at",
})

_NEEDS_RECOVERY_TURN = OBSERVING | {"recovered", "completed_no_progress",
                                    "recovery_turn_failed", "stopped_by_user"}
