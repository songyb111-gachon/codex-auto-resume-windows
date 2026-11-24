//! What the store reads of the policy, before car-policy (S2.1) is ported.
//!
//! SEAM, TO BE REPLACED. What belongs to the domain is car-machine's (S1.1) and the store reads it through
//! [`crate::machine`]; what is left is each item here that Python keeps in a module car-policy owns, copied to the
//! Python's rules exactly:
//!
//! | here | Python | owner |
//! |---|---|---|
//! | [`vocab`] | the failure categories (`failures.py`), the notice kinds (`needsyou.py`), the gates' words (`domain/vocabulary.py`, `domain/gates.py`), `ladder.EARLY_STATES`, the watcher's ends | car-policy (S2.1) |
//! | this module | `failures.py` (`is_recoverable`, `reset_verified`, `USAGE_LIMIT`), `quiet.py` (`postponement_problem`), `needsyou.py` (`KEEP_SECONDS`), `ladder.py` (`CAPACITY_MAX_SECONDS`) | car-policy (S2.1) |
//! | [`gates`] | `domain/gates.py` | car-policy (S2.1) |
//! | [`python`] | CPython's own readings of a text (`str.split`, `float()`, `json.loads`, `int(_, 16)`) | the store (not a seam: it holds what Rust's readers refuse) |
//!
//! `tests/rustdiff/diffs_store.py` holds the vocabularies to the reference tag's, and the store's own diffs
//! exercise every function here through the store.

pub mod gates;
pub mod python;
pub mod vocab;

use car_machine::json::Value;

use crate::machine::has;
use crate::value::{Row, get, number, text};

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
