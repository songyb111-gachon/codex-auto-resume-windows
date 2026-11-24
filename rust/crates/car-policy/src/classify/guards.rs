//! `guards.py`: two guards a waiting recovery may be held by - its task changed, or its conversation grew costly.
//! Only a digest and a count are ever kept, never a path, a branch name or a model's name; both guards can only hold
//! a record back or add words to a notice.

use car_machine::domain::ids;
use car_machine::hash;
use car_machine::json::Value;
use car_machine::pyval::Py;

use super::seam::{COUNT, Own, amount, coerce};
use super::value::{dict_or_empty, get, in_tuple, text};
pub use super::vocab_gen::guards::{
    CONTEXT_GUARDS, CONTEXT_HOLD, DEFAULT_CONTEXT_GUARD, DEFAULT_TASK_GUARD, TASK_GUARDS,
    TASK_HOLD, UNREADABLE,
};

/// `OWN["context_guard"]`: a count of the person's own, in whole thousands from 10,000 to 10,000,000.
pub const OWN_CONTEXT: Own = Own {
    kind: COUNT,
    low: 10_000,
    high: 10_000_000,
    units: &["k", "m"],
    prefix: "above_",
};
/// `MAX_TOKENS`: the largest count kept.
pub const MAX_TOKENS: i64 = 1 << 53;

/// `task_mode(values)`.
pub fn task_mode(values: &Value) -> String {
    let chosen = get(dict_or_empty(values), "task_changed_guard");
    if in_tuple(chosen, TASK_GUARDS) {
        text(chosen).unwrap_or(DEFAULT_TASK_GUARD).to_owned()
    } else {
        DEFAULT_TASK_GUARD.to_owned()
    }
}

/// `watches_task(values)`: whether anything of a task's workspace is read.
pub fn watches_task(values: &Value) -> bool {
    task_mode(values) != "off"
}

/// `context_mode(values)`: off, show, a limit's choice or a limit of the person's own.
pub fn context_mode(values: &Value) -> String {
    let chosen = get(dict_or_empty(values), "context_guard");
    coerce(chosen, DEFAULT_CONTEXT_GUARD, CONTEXT_GUARDS, &OWN_CONTEXT)
}

/// `counts_tokens(values)`.
pub fn counts_tokens(values: &Value) -> bool {
    context_mode(values) != "off"
}

/// `context_limit(values)`: the count above which a recovery is held, or None.
pub fn context_limit(values: &Value) -> Option<i64> {
    amount(&OWN_CONTEXT, &Value::from(context_mode(values))).and_then(|found| found.number())
}

/// `fingerprint(model, approval, head)`: the digest of what a task was working with. A text with a lone surrogate
/// cannot be encoded (UnicodeEncodeError), as in Python.
pub fn fingerprint(model: &Value, approval: &Value, head: &Value) -> Py<String> {
    let mut parts = Vec::new();
    for (name, value) in [("model", model), ("approval", approval), ("head", head)] {
        let said = match value {
            Value::Str(word) if !word.code_points().any(|point| point == 0) => {
                word.as_str().ok_or("UnicodeEncodeError")?.to_owned()
            }
            Value::Null => "-".to_owned(),
            _ => "?".to_owned(),
        };
        parts.push(format!("{name}={said}"));
    }
    Ok(hash::hex(&hash::sha256(parts.join("\n").as_bytes())))
}

/// `is_print(value)`: a task's digest (a SHA-256).
pub fn is_print(value: &Value) -> bool {
    ids::is_digest(value)
}

/// `changed(recorded, now)`: whether a task changed between its detection and now.
pub fn changed(recorded: &Value, now: &Value) -> bool {
    if matches!(recorded, Value::Null) {
        return false;
    }
    let found = if is_print(now) {
        text(now).unwrap_or_default()
    } else {
        UNREADABLE
    };
    text(recorded) != Some(found)
}

/// `tokens(value)`: a whole number from 0 up to MAX_TOKENS, or None.
pub fn tokens(value: &Value) -> Option<i64> {
    match value {
        Value::Int(number) => number
            .as_i64()
            .filter(|count| (0..=MAX_TOKENS).contains(count)),
        _ => None,
    }
}

/// `over(values, count)`: whether a conversation's count is above the limit set; an unknown count never is.
pub fn over(values: &Value, count: &Value) -> bool {
    match (context_limit(values), tokens(count)) {
        (Some(limit), Some(count)) => count > limit,
        _ => false,
    }
}
