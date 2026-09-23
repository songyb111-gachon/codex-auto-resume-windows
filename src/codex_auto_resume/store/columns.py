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

_RECORD_COLUMNS = _V2_COLUMNS + tuple(name for name, _ in _SCHEMA_3_COLUMNS)

_EVENT_COLUMNS = ("event_id", "at", "interruption_id", "chain_origin_id", "code", "from_state",
                  "to_state", "reason", "actor", "turn_ref", "flags", "value")

_WATCHER_COLUMNS = ("singleton", "pid", "session_id", "started_at", "last_tick_at",
                    "last_tick_ok", "engine_state", "code_version")

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
