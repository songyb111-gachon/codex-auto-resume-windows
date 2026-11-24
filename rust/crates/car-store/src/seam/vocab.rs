//! The closed vocabularies the store reads that car-policy owns (S2.1), from `build/vocab_export.py --ref v0.6.26-beta.2`:
//! the failure categories (`failures.py`), the notice kinds (`needsyou.py`), the gates (`domain/vocabulary.py`
//! `GateName`, `GateResult`, `GateReason`, `domain/gates.py`'s `RESENDABLE` and `FORCEABLE`), the watcher's ends and
//! `ladder.EARLY_STATES`.
//!
//! SEAM, TO BE REPLACED by the vocabularies car-policy generates from `vocab.json`. The lists car-machine holds -
//! the states, the public words, the usage keys, the engine states - are car-machine's own (`crate::machine::vocab`);
//! `tests/rustdiff/diffs_store.py` (`SeamVocabularyDiff`) holds what is left here to the reference tag's own sets.

/// domain/vocabulary.py GateResult.
pub const GATE_RESULTS: &[&str] = &["PASS", "WAIT", "BLOCK", "UNKNOWN"];
/// domain/vocabulary.py GateName, in evaluation order.
pub const GATES: &[&str] = &[
    "consent",
    "engine_compatible",
    "single_owner",
    "submission_safe",
    "identity",
    "known_failure",
    "schedule",
    "chain_budget",
    "attempt_budget",
    "no_progress_budget",
    "thread_available",
    "no_newer_user_work",
    "usage",
];
/// domain/gates.py GATE_REASONS.
pub const GATE_REASONS: &[&str] = &[
    "admission_expired",
    "ambiguous_receipt",
    "app_server_unmatched",
    "app_server_unmatched:named_engine",
    "awaiting_delivery_receipt",
    "budget_restored",
    "cancel",
    "cancel_requested",
    "capacity_window",
    "category_disabled",
    "chain_cap",
    "chain_time_cap",
    "correlation_conflict",
    "daily_submission_cap",
    "desktop_app_unavailable",
    "duplicate_marker",
    "duplicate_owner",
    "engine_incompatible",
    "engine_unknown",
    "expired",
    "held",
    "held_by_other_session",
    "home_lock_unavailable",
    "home_not_watched",
    "home_removed",
    "identity_unreadable",
    "later_turn_exists",
    "latest_turn_changed",
    "loaded_recheck_failed",
    "loaded_state_unknown",
    "marker_not_turn_initiator",
    "multiple_matching_queue_items",
    "no_progress_budget",
    "no_progress_observed",
    "no_receipt_do_not_resend",
    "notLoaded",
    "not_checked",
    "not_delivered_on_open",
    "not_due",
    "not_loaded",
    "not_recoverable",
    "observe_only",
    "observe_only_unknown",
    "offline",
    "ok",
    "other_recovery_in_flight",
    "outcome_deadline",
    "owned_queue_removed",
    "parent_cancelled",
    "parent_handed_over",
    "paused",
    "paused_unknown",
    "plugged",
    "possibly_sent",
    "post_send_bookkeeping_failed",
    "postponed",
    "progress_observed",
    "progress_then_turn_cut_off",
    "progress_then_turn_failed",
    "progress_then_user_joined",
    "projection_stale",
    "projection_table_missing",
    "queue_cleanup_unconfirmed",
    "queue_launch_retry_limit",
    "queue_process_not_started",
    "queue_result_unknown_do_not_resend",
    "queued_item_edited",
    "quiet_hours",
    "recovery_budget",
    "released_after_withdrawal",
    "released_before_send",
    "resend",
    "retry_now",
    "send_now",
    "session",
    "session_ended",
    "session_expired",
    "session_kind_off",
    "stale_turn_row",
    "superseded",
    "superseded_by_user",
    "thread_disabled",
    "thread_submission_cooldown",
    "turn_failed",
    "turn_interrupted",
    "turn_without_user_item",
    "unknown_turn_status",
    "usage_available",
    "usage_never_available",
    "usage_not_restored_after_reset",
    "usage_probe_broken_answer",
    "usage_probe_broken_request",
    "usage_probe_broken_start",
    "usage_recheck_failed",
    "usage_unavailable",
    "usage_unknown",
    "user_cancelled",
    "user_input_queued",
    "user_joined",
    "user_queued_input",
    "version_newer_than_engine",
    "waiting_reset",
    "window_ended",
    "withdraw_unconfirmed",
];
/// domain/gates.py RESENDABLE.
pub const RESENDABLE: &[&str] = &[
    "no_receipt_do_not_resend",
    "queue_result_unknown_do_not_resend",
];
/// domain/gates.py FORCEABLE.
pub const FORCEABLE: &[&str] = &["not_due", "postponed"];
/// failures.py CATEGORIES (FailureCategory).
pub const CATEGORIES: &[&str] = &[
    "usage_limit",
    "network_transient",
    "timeout",
    "rate_limit_transient",
    "server_5xx",
    "stream_interrupted",
    "auth_service_transient",
    "terminal_user",
    "terminal_permission",
    "terminal_policy",
    "terminal_invalid",
    "terminal_auth",
    "terminal_failure",
    "unknown",
];
/// failures.py TRANSIENT.
pub const TRANSIENT: &[&str] = &[
    "network_transient",
    "rate_limit_transient",
    "server_5xx",
    "stream_interrupted",
    "timeout",
];
/// failures.py ADMISSIBLE.
pub const ADMISSIBLE: &[&str] = &[
    "terminal_auth",
    "terminal_failure",
    "terminal_invalid",
    "unknown",
];
/// needsyou.py NOTICE_KINDS.
pub const NOTICE_KINDS: &[&str] = &[
    "stalled_turn",
    "terminal_auth",
    "terminal_failure",
    "terminal_invalid",
    "terminal_policy",
];
/// domain/vocabulary.py WatcherEnd, in order.
pub const WATCHER_ENDS: &[&str] = &["running", "clean", "memory_guard", "unexpected"];
/// ladder.py EARLY_STATES.
pub const EARLY_STATES: &[&str] = &["waiting_reset", "waiting_poll", "waiting_for_usage"];
