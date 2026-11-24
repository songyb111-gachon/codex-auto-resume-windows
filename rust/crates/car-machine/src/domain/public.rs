//! `domain/public.py`: one record, as every interface shows it: one code, one reason, and what is on top of it.
//!
//! A closed vocabulary throughout. A surface never reads a stored state, a category or a gate vector directly - it
//! reads `describe`. Nothing here reads settings or the clock. The word lists are generated into
//! [`crate::vocab_gen::domain_public`]; `self_check` (which reads `failures.TAG_SHAPE`) is car-policy's (cut C1).

use crate::json::{Map, Str, Value};
use crate::pytext::to_float;
use crate::pyval::{self, Py, get, in_set, in_tuple, is, text, truthy};
use crate::vocab_gen::domain_public as table;
use crate::vocab_gen::domain_reason_vocabulary::ReasonCode;
use crate::vocab_gen::domain_states as states;
use crate::vocab_gen::domain_vocabulary::{Actor, EventCode, HoldKind, ImportanceTier, TurnStatus};

pub use super::ids::{is_interruption_id, is_uuid};

pub const FLAG_AFTER_USER_WORK: i64 = 1;
pub const FLAG_USER_JOINED: i64 = 2;
pub const FLAG_WITHDRAW_DELETED: i64 = 4;
pub const FLAG_LEGACY: i64 = 8;
pub const SELF_CHECK_FORMAT: &str = "codex-auto-resume/selfcheck/1";
pub const VERSION_MAX: usize = 32;

fn word(value: &Value, known: fn(&str) -> bool, otherwise: &str) -> Value {
    match text(value) {
        Some(each) if known(each) => value.clone(),
        _ => Value::from(otherwise),
    }
}

/// `event_code(value)`.
pub fn event_code(value: &Value) -> Value {
    word(value, |each| EventCode::parse(each).is_some(), "other")
}

/// `reason_code(value)`: `None` stays none, an unknown word is `other`.
pub fn reason_code(value: &Value) -> Value {
    if matches!(value, Value::Null) {
        return Value::Null;
    }
    word(value, |each| ReasonCode::parse(each).is_some(), "other")
}

/// `actor_code(value)`.
pub fn actor_code(value: &Value) -> Value {
    word(value, |each| Actor::parse(each).is_some(), "engine")
}

/// `turn_status(value)`.
pub fn turn_status(value: &Value) -> Value {
    if matches!(value, Value::Null) {
        return Value::Null;
    }
    word(value, |each| TurnStatus::parse(each).is_some(), "other")
}

/// `hold_for_tier(tier)`: the hold a tier puts on an interruption, or none.
pub fn hold_for_tier(tier: &Value) -> Value {
    match text(tier).and_then(ImportanceTier::parse) {
        Some(ImportanceTier::AskFirst) => Value::from(HoldKind::Ask.as_str()),
        Some(ImportanceTier::NotifyOnly) => Value::from(HoldKind::NotifyOnly.as_str()),
        _ => Value::Null,
    }
}

fn direct(state: &str) -> Option<&'static str> {
    Some(match state {
        "waiting_reset" | "waiting_poll" => "waiting_reset",
        "waiting_for_usage" => "waiting_usage",
        "waiting_for_app" | "waiting_for_loaded_thread" => "waiting_thread",
        "waiting_backoff" => "scheduled",
        "queued" => "submitted",
        "withdrawn_unconfirmed" => "withdrawing",
        "turn_started" => "turn_running",
        "turn_completed" => "turn_finishing",
        "recovered" => "recovered",
        "completed_no_progress" => "no_progress",
        "handed_over" => "handed_over",
        "recovery_turn_failed" => "recovery_failed",
        "stopped_by_user" => "stopped_by_user",
        "outcome_unverified" => "outcome_unverified",
        "resumed" => "delivered_legacy",
        "cancelled" => "cancelled",
        "superseded" | "superseded_by_user" => "superseded",
        "retry_budget_exhausted" | "no_progress_exhausted" => "exhausted",
        "failed" | "terminal_failure" => "failed_terminal",
        "submission_unknown" => "submission_unknown",
        _ => return None,
    })
}

/// `public_code(record)`: the one public code for a stored record. Never reads settings.
pub fn public_code(record: &Value) -> Py<&'static str> {
    let state = get(record, "state")?;
    if is(state, "waiting_retry") {
        return Ok(
            if is(get(record, "last_error")?, "queue_process_not_started") {
                "failed_retryable"
            } else {
                "scheduled"
            },
        );
    }
    if is(state, "submitting") {
        return Ok(
            if is(get(record, "last_error")?, "awaiting_delivery_receipt")
                || truthy(get(record, "queue_id")?)
            {
                "submitted"
            } else {
                "submission_claimed"
            },
        );
    }
    pyval::hashable(state)?;
    Ok(text(state).and_then(direct).unwrap_or("outcome_unverified"))
}

/// `eligible_at(record)`: when a waiting record is next looked at, or none.
pub fn eligible_at(record: &Value) -> Py<Value> {
    if !in_set(get(record, "state")?, states::WAITING)?
        || !matches!(get(record, "hold")?, Value::Null)
    {
        return Ok(Value::Null);
    }
    let zero = Value::from(0);
    let pick = |name: &str| -> Py<Value> {
        let found = get(record, name)?;
        Ok(if truthy(found) {
            found.clone()
        } else {
            zero.clone()
        })
    };
    let (a, b, c) = (
        pick("next_retry_at")?,
        pick("reset_at")?,
        pick("not_before")?,
    );
    let biggest = pyval::max(&[&a, &b, &c])?.clone();
    Ok(if truthy(&biggest) {
        biggest
    } else {
        Value::Null
    })
}

/// `own_postponement(record, now=None)`: the time a person postponed `record` to, or none.
pub fn own_postponement(record: &Value, now: &Value) -> Py<Value> {
    let until = get(record, "not_before")?;
    if matches!(until, Value::Null) {
        return Ok(Value::Null);
    }
    let objection = get(record, "objection_until")?;
    let floor = if truthy(objection) {
        objection.clone()
    } else {
        Value::from(0)
    };
    if pyval::less_or_equal(until, &floor)? {
        return Ok(Value::Null);
    }
    if !matches!(now, Value::Null) && pyval::less_or_equal(until, now)? {
        return Ok(Value::Null);
    }
    Ok(until.clone())
}

/// `public_reason(record)`: the reason shown next to the code. A closed vocabulary; never free text.
pub fn public_reason(record: &Value) -> Py<Value> {
    if is(get(record, "state")?, "no_progress_exhausted") {
        return Ok(Value::from("no_progress_budget"));
    }
    Ok(reason_code(get(record, "last_error")?))
}

/// Whether a reason is the app's server not matched, or one of its kinds.
fn unmatched(reason: &Value) -> bool {
    let unmatched = ReasonCode::AppServerUnmatched.as_str();
    text(reason).is_some_and(|each| {
        ReasonCode::parse(each).is_some()
            && (each == unmatched || each.starts_with(&format!("{unmatched}:")))
    })
}

/// `blocked(watcher)`: the self-check word a watcher view carries, or none.
pub fn blocked(watcher: &Value) -> Value {
    let check = match watcher {
        Value::Object(map) => map.get("self_check"),
        _ => None,
    };
    let word = match check {
        Some(Value::Object(map)) => map.get("blocked"),
        _ => None,
    };
    match word {
        Some(each) if in_tuple(each, table::WORDS) => each.clone(),
        _ => Value::Null,
    }
}

/// `overlays(record, enabled=True, thread_enabled=True, watcher=None)`: circumstances that change what a record
/// will do next, without changing it.
pub fn overlays(
    record: &Value,
    enabled: &Value,
    thread_enabled: &Value,
    watcher: &Value,
) -> Py<Vec<&'static str>> {
    let mut found = Vec::new();
    let state = get(record, "state")?;
    if truthy(get(record, "cancel_requested")?) && !in_set(state, states::TERMINAL)? {
        found.push("cancel_pending");
    }
    if !in_set(state, states::WAITING)? {
        return Ok(found);
    }
    if !truthy(enabled) {
        found.push("paused");
    }
    if !truthy(thread_enabled) {
        found.push("thread_disabled");
    }
    if !matches!(get(record, "hold")?, Value::Null) {
        found.push("held");
    } else if unmatched(get(record, "last_error")?) && truthy(enabled) && truthy(thread_enabled) {
        found.push("app_server_unmatched");
    }
    let view = if truthy(watcher) {
        watcher.clone()
    } else {
        Value::Object(Map::new())
    };
    let field = |name: &str| get(&view, name);
    if is(field("engine_state")?, "incompatible") {
        found.push("compatibility_blocked");
    } else if is(field("engine_state")?, "failed_here") {
        found.push("compatibility_failed_here");
    }
    let running = field("running")?;
    if matches!(running, Value::Bool(false)) {
        found.push("engine_unavailable");
    } else if matches!(running, Value::Bool(true))
        && matches!(field("ticking")?, Value::Bool(false))
    {
        found.push("watcher_not_ticking");
    } else if matches!(running, Value::Bool(true)) && !matches!(blocked(&view), Value::Null) {
        found.push("codex_changed");
    }
    Ok(found)
}

/// `describe(record, **surroundings)`: everything an interface needs to show one record, as stable machine values.
pub fn describe(
    record: &Value,
    enabled: &Value,
    thread_enabled: &Value,
    watcher: &Value,
) -> Py<Value> {
    let mut out = Map::new();
    out.insert(Str::from("code"), Value::from(public_code(record)?));
    out.insert(Str::from("reason"), public_reason(record)?);
    out.insert(Str::from("eligible_at"), eligible_at(record)?);
    let listed = overlays(record, enabled, thread_enabled, watcher)?;
    out.insert(
        Str::from("overlays"),
        Value::Array(listed.into_iter().map(Value::from).collect()),
    );
    out.insert(
        Str::from("terminal"),
        Value::Bool(in_set(get(record, "state")?, states::TERMINAL)?),
    );
    Ok(Value::Object(out))
}

fn version_char(each: char) -> bool {
    each.is_ascii_alphanumeric() || each == '.' || each == '-'
}

/// `_VERSION.fullmatch(text)`: a letter or digit, then letters, digits, dots and hyphens, in all at most `VERSION_MAX`.
fn version_shape(candidate: &str) -> bool {
    candidate
        .chars()
        .next()
        .is_some_and(|first| first.is_ascii_alphanumeric())
        && candidate.chars().count() <= VERSION_MAX
        && candidate.chars().all(version_char)
}

/// `version_word(text)`: the version a text names, as the self-check keeps one, or none.
pub fn version_word(input: &Value) -> Option<String> {
    let candidate = text(input)?;
    if version_shape(candidate) && candidate.chars().any(|each| each.is_ascii_digit()) {
        return Some(candidate.to_owned());
    }
    let head: Vec<char> = candidate.chars().take(256).collect();
    let mut at = 0;
    while at < head.len() {
        let starts = head[at].is_ascii_digit() && (at == 0 || !version_char(head[at - 1]));
        if starts {
            let mut end = at;
            while end < head.len() && version_char(head[end]) {
                end += 1;
            }
            let found: String = head[at..end].iter().collect();
            return version_shape(&found).then_some(found);
        }
        at += 1;
    }
    None
}

/// `self_check_note(started_at, word, unknown, layout, updated_from)`: what the watcher writes beside its heartbeat.
pub fn self_check_note(
    started_at: &Value,
    word: &Value,
    unknown: &Value,
    layout: &Value,
    updated_from: &Value,
) -> Py<Value> {
    let mut note = Map::new();
    note.insert(Str::from("format"), Value::from(SELF_CHECK_FORMAT));
    note.insert(Str::from("started_at"), Value::Float(to_float(started_at)?));
    note.insert(
        Str::from("blocked"),
        if in_tuple(word, table::WORDS) {
            word.clone()
        } else {
            Value::Null
        },
    );
    note.insert(Str::from("unknown_error"), unknown.clone());
    note.insert(Str::from("layout_untested"), layout.clone());
    note.insert(Str::from("updated_from"), updated_from.clone());
    Ok(Value::Object(note))
}
