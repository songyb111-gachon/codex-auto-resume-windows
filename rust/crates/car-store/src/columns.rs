//! The columns each schema version has, in the order they are written (store/columns.py).

/// Schema 1 and 2 columns, in their original order.
pub const V2_COLUMNS: &[&str] = &[
    "interruption_id",
    "thread_id",
    "turn_id",
    "completed_at",
    "started_at",
    "ordinal",
    "detected_at",
    "reset_at",
    "limit_type",
    "uncertain",
    "state",
    "retry_count",
    "next_retry_at",
    "resumed_at",
    "last_error",
    "marker",
    "queue_id",
    "submitted_at",
    "attempt_count",
    "cancel_requested",
    "category",
    "recovery_attempts",
    "no_progress_count",
];

/// Columns added in schema 2.
pub const SCHEMA_2_COLUMNS: &[(&str, &str)] = &[
    ("category", "TEXT NOT NULL DEFAULT 'usage_limit'"),
    ("recovery_attempts", "INTEGER NOT NULL DEFAULT 0"),
    ("no_progress_count", "INTEGER NOT NULL DEFAULT 0"),
];

/// Columns added in schema 3.
pub const SCHEMA_3_COLUMNS: &[(&str, &str)] = &[
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
];

/// Columns added in schema 4 (v0.6.11), each to the table it names.
pub const SCHEMA_4_COLUMNS: &[(&str, &str, &str)] = &[
    ("interruptions", "not_before", "REAL"),
    ("interruptions", "hold", "TEXT"),
    ("threads", "tier", "TEXT"),
    (
        "settings",
        "observe_only",
        "INTEGER NOT NULL DEFAULT 0 CHECK (observe_only IN (0, 1))",
    ),
    ("interruptions", "task_print", "TEXT"),
    ("interruptions", "context_tokens", "INTEGER"),
    ("interruptions", "objection_at", "REAL"),
    ("interruptions", "objection_until", "REAL"),
    ("watcher_status", "usage_at", "REAL"),
    ("watcher_status", "usage", "TEXT"),
    ("watcher_status", "awake_since", "REAL"),
    ("watcher_status", "memory_peak", "INTEGER"),
    ("watcher_status", "end_mark", "TEXT"),
    ("watcher_status", "ended_at", "REAL"),
    ("watcher_status", "sign_in", "TEXT"),
    ("watcher_status", "booted_at", "REAL"),
];

/// Schema 5's home key check.
pub const HOME_KEY_CHECK: &str =
    "home_key = '' OR (length(home_key) = 64 AND home_key NOT GLOB '*[^0-9a-f]*')";

/// Columns added in schema 5 (v0.6.15-beta). The home key's definition is built with [`HOME_KEY_CHECK`].
pub const SCHEMA_5_COLUMNS: &[(&str, &str, &str)] = &[
    (
        "interruptions",
        "home_key",
        "TEXT NOT NULL DEFAULT '' CHECK (home_key = '' OR (length(home_key) = 64 AND home_key NOT GLOB '*[^0-9a-f]*'))",
    ),
    ("watcher_status", "homes", "TEXT"),
];

/// The record columns of schema 3: V2 then schema 3's.
pub fn v3_columns() -> Vec<&'static str> {
    V2_COLUMNS
        .iter()
        .copied()
        .chain(SCHEMA_3_COLUMNS.iter().map(|(name, _)| *name))
        .collect()
}

/// The record columns of schema 4.
pub fn v4_record_columns() -> Vec<&'static str> {
    let mut columns = v3_columns();
    columns.extend(
        SCHEMA_4_COLUMNS
            .iter()
            .filter(|(table, ..)| *table == "interruptions")
            .map(|(_, name, _)| *name),
    );
    columns
}

/// The record columns of schema 5, in the order rows are inserted in (`_RECORD_COLUMNS`).
pub fn record_columns() -> Vec<&'static str> {
    let mut columns = v4_record_columns();
    columns.extend(
        SCHEMA_5_COLUMNS
            .iter()
            .filter(|(table, ..)| *table == "interruptions")
            .map(|(_, name, _)| *name),
    );
    columns
}

/// `RECORD_SELECT`: a record as this version reads it in a later version's state marked readable from it.
pub fn record_select() -> String {
    format!("SELECT {} FROM interruptions", record_columns().join(", "))
}

pub const SETTINGS_COLUMNS: &[&str] = &[
    "singleton",
    "enabled",
    "armed_at",
    "poll_seconds",
    "observe_only",
];

pub const THREAD_COLUMNS: &[&str] = &["thread_id", "enabled", "tier"];

pub const NOTICE_COLUMNS: &[&str] = &[
    "interruption_id",
    "thread_id",
    "category",
    "raised_at",
    "seen_at",
];

/// `NOTICE_SELECT`.
pub fn notice_select() -> String {
    format!("SELECT {} FROM notices", NOTICE_COLUMNS.join(", "))
}

pub const EVENT_COLUMNS: &[&str] = &[
    "event_id",
    "at",
    "interruption_id",
    "chain_origin_id",
    "code",
    "from_state",
    "to_state",
    "reason",
    "actor",
    "turn_ref",
    "flags",
    "value",
];

pub const V4_WATCHER_COLUMNS: &[&str] = &[
    "singleton",
    "pid",
    "session_id",
    "started_at",
    "last_tick_at",
    "last_tick_ok",
    "engine_state",
    "code_version",
    "usage_at",
    "usage",
    "awake_since",
    "memory_peak",
    "end_mark",
    "ended_at",
    "sign_in",
    "booted_at",
];

/// The watcher's columns of schema 5.
pub fn watcher_columns() -> Vec<&'static str> {
    V4_WATCHER_COLUMNS
        .iter()
        .copied()
        .chain(["homes"])
        .collect()
}

/// Fields a plain `update` may write (`_MUTABLE`).
pub const MUTABLE: &[&str] = &[
    "reset_at",
    "limit_type",
    "uncertain",
    "state",
    "retry_count",
    "next_retry_at",
    "resumed_at",
    "last_error",
    "queue_id",
    "submitted_at",
    "attempt_count",
    "cancel_requested",
    "recovery_attempts",
    "no_progress_count",
    "recovery_turn_id",
    "recovery_client_id",
    "recovery_turn_status",
    "user_joined",
    "after_user_work",
    "withdraw_reason",
    "withdrawn_at",
    "withdraw_deleted",
    "withdraw_failures",
    "turn_started_at",
    "outcome_at",
    "first_queued_at",
    "usage_unavailable_seconds",
    "usage_probe_at",
    "gate_eval",
    "gate_eval_at",
];

/// The states whose record must name its recovery turn (`_NEEDS_RECOVERY_TURN`): OBSERVING and four outcomes.
pub const NEEDS_RECOVERY_TURN: &[&str] = &[
    "turn_started",
    "turn_completed",
    "recovered",
    "completed_no_progress",
    "recovery_turn_failed",
    "stopped_by_user",
];

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn home_key_definition_is_built_from_its_check() {
        assert_eq!(
            SCHEMA_5_COLUMNS[0].2,
            format!("TEXT NOT NULL DEFAULT '' CHECK ({HOME_KEY_CHECK})")
        );
    }

    #[test]
    fn counts() {
        assert_eq!(record_columns().len(), 23 + 25 + 6 + 1);
        assert_eq!(watcher_columns().len(), 17);
    }
}
