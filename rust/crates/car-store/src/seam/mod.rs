//! What the store reads of the domain and the policy, before the crates that own it are ported.
//!
//! SEAM, TO BE REPLACED. Every item here is a minimal local copy, kept to the Python's rules exactly:
//!
//! | here | Python | owner |
//! |---|---|---|
//! | [`vocab`] | the closed vocabularies (`domain/vocabulary.py`, `domain/reason_vocabulary.py`, `domain/states.py`, `domain/public.py`, `domain/gates.py`, `failures.py`, `needsyou.py`, `domain/usage.py`, `ladder.py`) | car-machine (S1.1), car-policy (S2.1) |
//! | [`ids`] | `domain/ids.py` | car-machine (S1.1) |
//! | this module | `domain/states.py` (`epoch`, `may_be_queued`, `plain_move_allowed`, `waiting_state`), `domain/public.py` (`event_code`, `reason_code`, `actor_code`, `turn_status`, `hold_for_tier`, `own_postponement`), `failures.py` (`is_recoverable`, `reset_verified`), `quiet.py` (`postponement_problem`), `needsyou.py` (`KEEP_SECONDS`), `ladder.py` (`CAPACITY_MAX_SECONDS`) | car-machine (S1.1), car-policy (S2.1) |
//! | [`gates`] | `domain/gates.py` | car-policy (S2.1) |
//! | [`usage`] | `domain/usage.py` | car-machine (S1.1) |
//!
//! `tests/rustdiff/diffs_store.py` holds the vocabularies to the reference tag's, and the store's own diffs
//! exercise every function here through the store.

pub mod gates;
pub mod ids;
pub mod links;
pub mod python;
pub mod usage;
pub mod vocab;

use car_machine::json::Value;

use crate::errors::{Error, Result};
use crate::value::{Row, get, number, or_zero, text};

/// `value in words`.
pub fn has(words: &[&str], word: &str) -> bool {
    words.contains(&word)
}

/// The store's window of a plausible time (`EPOCH_STORE`): the epoch to the last second of 9999.
pub const EPOCH_STORE: (f64, f64) = (0.0, 253_402_300_799.0);
/// The App Server's usage windows (`EPOCH_USAGE`): to 2100.
pub const EPOCH_USAGE: (f64, f64) = (1.0, 4_102_444_800.0);

/// `machine.epoch(value, *EPOCH_STORE)`: a number of seconds in the store's window, never a bool, a
/// NaN or an infinity. An `int` too large to be a float raises OverflowError there, as `math.isfinite` does.
pub fn epoch_store(value: &Value) -> Result<bool> {
    let Some(seconds) = number(value) else {
        return Ok(false);
    };
    if matches!(value, Value::Int(_)) && !seconds.is_finite() {
        return Err(Error::Python(
            "OverflowError",
            "int too large to convert to float".into(),
        ));
    }
    Ok(seconds.is_finite() && EPOCH_STORE.0 <= seconds && seconds <= EPOCH_STORE.1)
}

/// `machine.may_be_queued(state, queue_id)`.
pub fn may_be_queued(state: &Value, queue_id: &Value) -> bool {
    match text(state) {
        Some(state) => {
            has(vocab::CLAIMED, state)
                || has(vocab::IN_FLIGHT, state)
                || (state == "submission_unknown" && !matches!(queue_id, Value::Null))
        }
        None => false,
    }
}

/// `machine.plain_move_allowed(old, new)`.
pub fn plain_move_allowed(old: &str, new: &str) -> bool {
    if old == new {
        return true;
    }
    vocab::PLAIN_MOVES
        .iter()
        .find(|(from, _)| *from == old)
        .is_some_and(|(_, to)| to.contains(&new))
}

/// `machine.waiting_state(record, now)`: a usage limit waits for a reset still ahead and polls after it;
/// every other failure backs off.
pub fn waiting_state(record: &Row, now: f64) -> &'static str {
    if text(get(record, "category")) == Some(USAGE_LIMIT) {
        let reset = get(record, "reset_at");
        if !matches!(reset, Value::Null) && number(reset).is_some_and(|reset| reset > now) {
            return "waiting_reset";
        }
        return "waiting_poll";
    }
    "waiting_backoff"
}

/// `failures.USAGE_LIMIT`.
pub const USAGE_LIMIT: &str = "usage_limit";

/// `failures.is_recoverable(category)`.
pub fn is_recoverable(category: &str) -> bool {
    category == USAGE_LIMIT || has(vocab::TRANSIENT, category)
}

/// `failures.reset_verified(row, now)`: a usage limit whose recorded reset is behind `now`.
pub fn reset_verified(row: &Row, now: f64) -> bool {
    text(get(row, "category")) == Some(USAGE_LIMIT)
        && matches!(get(row, "reset_at"), Value::Int(_) | Value::Float(_))
        && number(get(row, "reset_at")).is_some_and(|reset| reset <= now)
}

/// `machine.event_code(value)`.
pub fn event_code(value: &str) -> &str {
    if has(vocab::EVENT_CODES, value) {
        value
    } else {
        "other"
    }
}

/// `machine.reason_code(value)`: None stays None; a word outside the list is "other".
pub fn reason_code(value: &Value) -> Option<String> {
    match value {
        Value::Null => None,
        other => Some(match text(other) {
            Some(word) if has(vocab::REASONS, word) => word.to_string(),
            _ => "other".to_string(),
        }),
    }
}

/// `machine.actor_code(value)`.
pub fn actor_code(value: &str) -> &str {
    if has(vocab::ACTORS, value) {
        value
    } else {
        "engine"
    }
}

/// `machine.turn_status(value)`.
pub fn turn_status(value: &Value) -> Option<String> {
    match value {
        Value::Null => None,
        other => Some(match text(other) {
            Some(word) if has(vocab::TURN_STATUSES, word) => word.to_string(),
            _ => "other".to_string(),
        }),
    }
}

/// `machine.hold_for_tier(tier)`: Ask me first holds `ask`, Only notify me `notify_only`.
pub fn hold_for_tier(tier: &Value) -> Option<&'static str> {
    match text(tier) {
        Some("ask_first") => Some("ask"),
        Some("notify_only") => Some("notify_only"),
        _ => None,
    }
}

/// `machine.own_postponement(record, now)`: a person's `not_before`, past the objection window, still ahead.
pub fn own_postponement(record: &Row, now: Option<f64>) -> Option<f64> {
    let until = get(record, "not_before");
    if matches!(until, Value::Null) {
        return None;
    }
    let until = number(until)?;
    if until <= or_zero(get(record, "objection_until")) {
        return None;
    }
    match now {
        Some(now) if until <= now => None,
        _ => Some(until),
    }
}

/// `quiet.MAX_POSTPONE_SECONDS`.
pub const MAX_POSTPONE_SECONDS: f64 = 7.0 * 86400.0;

/// `quiet.postponement_problem(until, now, not_before)`.
pub fn postponement_problem(until: &Value, now: f64, not_before: &Value) -> Option<&'static str> {
    let until = match until {
        Value::Int(_) | Value::Float(_) => number(until).filter(|until| until.is_finite()),
        _ => None,
    };
    let Some(until) = until else {
        return Some("invalid_time");
    };
    let before = number(not_before);
    if until <= now || before.is_some_and(|before| until <= before) {
        return Some("not_later");
    }
    if until > now + MAX_POSTPONE_SECONDS {
        return Some("too_far");
    }
    None
}

/// `needsyou.KEEP_SECONDS`: a week's window and a day.
pub const KEEP_SECONDS: f64 = 7.0 * 86400.0 + 86400.0;

/// `ladder.CAPACITY_MAX_SECONDS`.
pub const CAPACITY_MAX_SECONDS: f64 = 24.0 * 3600.0;
