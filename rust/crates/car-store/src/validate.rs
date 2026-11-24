//! Every value checked before it is written, and the record as a whole (store/validate.py).
//!
//! Nothing reaches a table without passing through here: a row this release cannot write is a row the
//! next one cannot read.

use car_machine::json::Value;

use crate::columns::{NEEDS_RECOVERY_TURN, NOTICE_COLUMNS, record_columns};
use crate::errors::{Error, Kind, Result};
use crate::machine::ids::{self, UuidProblem};
use crate::machine::policy::USAGE_LIMIT;
use crate::machine::vocab::{
    CATEGORIES, CLAIMED, HOLDS, IMPORTANCE_TIERS, IN_FLIGHT, NOTICE_KINDS, OBSERVING, STATES,
    TURN_STATUSES, WITHDRAW_REASONS,
};
use crate::machine::{epoch_store, has};
use crate::value::{Row, get, is_in, set, text, text_of};

/// `_uuid(value, name)`.
pub fn uuid(value: &Value, name: &str) -> Result<()> {
    match ids::uuid_problem(value) {
        None => Ok(()),
        Some(UuidProblem::NotCanonical) => Err(Error::store(format!(
            "Invalid {name}: canonical UUID required"
        ))),
        Some(UuidProblem::Malformed) => Err(Error::store(format!("Invalid {name}"))),
    }
}

/// `_uuid` of a text.
pub fn uuid_text(value: &str, name: &str) -> Result<()> {
    uuid(&crate::value::string(value), name)
}

/// `_timestamp(value, name, nullable=...)`.
pub fn timestamp(value: &Value, name: &str, nullable: bool) -> Result<()> {
    if nullable && matches!(value, Value::Null) {
        return Ok(());
    }
    if !epoch_store(value)? {
        return Err(Error::store(format!("Invalid {name}")));
    }
    Ok(())
}

/// `_timestamp(now, "now")` of a float.
pub fn now(value: f64) -> Result<()> {
    timestamp(&Value::Float(value), "now", false)
}

/// `_integer(value, name)`: a whole number from 0 to 2**63 - 1, never a bool.
pub fn integer(value: &Value, name: &str) -> Result<i64> {
    match value {
        Value::Int(number) => match number.as_i64() {
            Some(number) if number >= 0 => Ok(number),
            _ => Err(Error::store(format!("Invalid {name}"))),
        },
        _ => Err(Error::store(format!("Invalid {name}"))),
    }
}

/// `_flag(value, name)`: 0, 1 or a bool.
pub fn flag(value: &Value, name: &str) -> Result<bool> {
    match value {
        Value::Bool(on) => Ok(*on),
        Value::Int(number) if number.as_i64() == Some(0) => Ok(false),
        Value::Int(number) if number.as_i64() == Some(1) => Ok(true),
        _ => Err(Error::store(format!("Invalid {name}"))),
    }
}

/// `_short_text(value, name, maximum, nullable=...)`.
pub fn short_text(value: &Value, name: &str, maximum: usize, nullable: bool) -> Result<()> {
    if nullable && matches!(value, Value::Null) {
        return Ok(());
    }
    let ok = match value {
        Value::Str(found) => {
            let points: Vec<u32> = found.code_points().collect();
            points.len() <= maximum && points.iter().all(|point| *point >= 32 && *point != 127)
        }
        _ => false,
    };
    if ok {
        Ok(())
    } else {
        Err(Error::store(format!("Invalid {name}")))
    }
}

/// `_choice(value, name, allowed)`.
pub fn choice(value: &Value, name: &str, allowed: &[&str]) -> Result<()> {
    if !matches!(value, Value::Null) && !is_in(value, allowed) {
        return Err(Error::store(format!("Invalid {name}")));
    }
    Ok(())
}

/// `is_home_key(value)`: '' for the default home, or 64 lowercase hex digits.
pub fn is_home_key(value: &Value) -> bool {
    text(value) == Some("") || ids::is_digest(value)
}

/// `_validated_tier(value)`.
pub fn validated_tier(value: &Value) -> Result<()> {
    choice(value, "tier", IMPORTANCE_TIERS)
}

/// `_validated_record(row)`: the whole record checked, its six flags made bools.
pub fn validated_record(mut row: Row) -> Result<Row> {
    let columns = record_columns();
    if row.len() != columns.len() || !columns.iter().all(|name| row.contains_key(*name)) {
        return Err(Error::Store(
            Kind::RecordSchemaMismatch,
            "Invalid record schema".into(),
        ));
    }
    let key = get(&row, "interruption_id").clone();
    if !ids::is_interruption_id(&key, true) {
        return Err(Error::store("Invalid interruption_id"));
    }
    uuid(get(&row, "thread_id"), "thread_id")?;
    uuid(get(&row, "turn_id"), "turn_id")?;
    for field in [
        "completed_at",
        "detected_at",
        "next_retry_at",
        "chain_first_detected_at",
        "usage_unavailable_seconds",
    ] {
        timestamp(get(&row, field), field, false)?;
    }
    for field in [
        "started_at",
        "reset_at",
        "resumed_at",
        "submitted_at",
        "withdrawn_at",
        "turn_started_at",
        "outcome_at",
        "first_queued_at",
        "last_claim_at",
        "usage_probe_at",
        "gate_eval_at",
        "history_hidden_at",
        "not_before",
        "objection_at",
        "objection_until",
    ] {
        timestamp(get(&row, field), field, true)?;
    }
    for field in [
        "ordinal",
        "retry_count",
        "attempt_count",
        "recovery_attempts",
        "no_progress_count",
        "withdraw_failures",
        "chain_continuations",
        "budget_resets",
        "retry_now_count",
    ] {
        integer(get(&row, field), field)?;
    }
    if !is_in(get(&row, "category"), CATEGORIES) {
        return Err(Error::store("Invalid failure category"));
    }
    for field in [
        "uncertain",
        "cancel_requested",
        "user_joined",
        "after_user_work",
        "legacy",
        "withdraw_deleted",
    ] {
        let on = flag(get(&row, field), field)?;
        set(&mut row, field, Value::Bool(on));
    }
    short_text(get(&row, "limit_type"), "limit_type", 160, true)?;
    short_text(get(&row, "last_error"), "last_error", 240, true)?;
    short_text(get(&row, "gate_eval"), "gate_eval", 4000, true)?;
    if !is_in(get(&row, "state"), STATES) {
        return Err(Error::store("Unknown record state"));
    }
    let key = text(&key).expect("checked above");
    let marker = get(&row, "marker");
    if !ids::record_markers(key)
        .iter()
        .any(|own| text(marker) == Some(own.as_str()))
    {
        return Err(Error::store("Invalid record marker"));
    }
    choice(get(&row, "hold"), "hold", HOLDS)?;
    let task_print = get(&row, "task_print");
    if !matches!(task_print, Value::Null) && !ids::is_digest(task_print) {
        return Err(Error::store("Invalid task_print"));
    }
    let tokens = get(&row, "context_tokens");
    if !matches!(tokens, Value::Null) && integer(tokens, "context_tokens")? > 1 << 53 {
        return Err(Error::store("Invalid context_tokens"));
    }
    for field in ["queue_id", "recovery_turn_id"] {
        if !matches!(get(&row, field), Value::Null) {
            uuid(get(&row, field), field)?;
        }
    }
    let client = get(&row, "recovery_client_id");
    if !matches!(client, Value::Null) && !ids::is_client_id(client) {
        return Err(Error::store("Invalid recovery_client_id"));
    }
    choice(
        get(&row, "recovery_turn_status"),
        "recovery_turn_status",
        TURN_STATUSES,
    )?;
    choice(
        get(&row, "withdraw_reason"),
        "withdraw_reason",
        WITHDRAW_REASONS,
    )?;
    if !is_home_key(get(&row, "home_key")) {
        return Err(Error::store("Invalid home_key"));
    }
    let parent = get(&row, "parent_interruption_id");
    if !matches!(parent, Value::Null) && !ids::is_interruption_id(parent, true) {
        return Err(Error::store("Invalid parent_interruption_id"));
    }
    if !ids::is_interruption_id(get(&row, "chain_origin_id"), true) {
        return Err(Error::store("Invalid chain_origin_id"));
    }
    let state = text_of(&row, "state").expect("checked above");
    if (has(CLAIMED, state) || has(IN_FLIGHT, state) || has(OBSERVING, state))
        && matches!(get(&row, "submitted_at"), Value::Null)
    {
        return Err(Error::store("Missing submission timestamp"));
    }
    if has(NEEDS_RECOVERY_TURN, state) && matches!(get(&row, "recovery_turn_id"), Value::Null) {
        return Err(Error::store("Missing recovery turn"));
    }
    if state == "withdrawn_unconfirmed"
        && (matches!(get(&row, "withdraw_reason"), Value::Null)
            || matches!(get(&row, "withdrawn_at"), Value::Null))
    {
        return Err(Error::store("Missing withdrawal details"));
    }
    Ok(row)
}

/// `_validated_notice(row)`.
pub fn validated_notice(row: Row) -> Result<Row> {
    if row.len() != NOTICE_COLUMNS.len()
        || !NOTICE_COLUMNS.iter().all(|name| row.contains_key(*name))
    {
        return Err(Error::Store(
            Kind::RecordSchemaMismatch,
            "Invalid notice schema".into(),
        ));
    }
    if !ids::is_interruption_id(get(&row, "interruption_id"), true) {
        return Err(Error::store("Invalid notice interruption_id"));
    }
    uuid(get(&row, "thread_id"), "notice thread_id")?;
    if !is_in(get(&row, "category"), NOTICE_KINDS) {
        return Err(Error::store("Invalid notice category"));
    }
    timestamp(get(&row, "raised_at"), "raised_at", false)?;
    timestamp(get(&row, "seen_at"), "seen_at", true)?;
    Ok(row)
}

/// `is_usage(row)`.
pub fn is_usage(row: &Row) -> bool {
    text_of(row, "category") == Some(USAGE_LIMIT)
}

/// `_claim_cost(row, refund)`: what one claim costs a record's budgets, as a SET clause.
pub fn claim_cost(row: &Row, refund: bool) -> String {
    let cost = [
        ("recovery_attempts", if is_usage(row) { 0 } else { 1 }),
        ("chain_continuations", 1),
    ];
    cost.iter()
        .map(|(column, amount)| {
            if refund {
                format!("{column}=max(0, {column}-{amount})")
            } else {
                format!("{column}={column}+{amount}")
            }
        })
        .collect::<Vec<_>>()
        .join(", ")
}
