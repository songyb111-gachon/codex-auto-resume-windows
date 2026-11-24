//! What the store takes from car-machine (S1.1): the domain's states, ids, public codes and usage, in the store's own
//! shapes - a `&str`, a [`Row`], an `f64` clock - over car-machine's Python-model functions.
//!
//! Nothing here is a rule: each function builds the arguments car-machine's function takes (a `Value`, the record as
//! a dict), calls it, and turns the Python exception it names into the store's [`Error::Python`]. The lists come
//! from car-machine's generated vocabularies, held to the reference's by `diffs_leaves_machine.py`. What the store
//! reads of car-policy (S2.1) - the failure categories, the gates, `is_recoverable`, `postponement_problem` and the
//! constants - is [`policy`], car-policy's own items.

use car_machine::domain::{ids as domain_ids, public, states, usage as domain_usage};
use car_machine::json::Value;

use crate::errors::{Error, Result};
use crate::value::{Row, number, string};

/// The closed lists the store reads: car-machine's, then the policy's (still a seam).
pub mod vocab {
    pub use car_machine::vocab_gen::compat_model::ENGINE_STATES;
    pub use car_machine::vocab_gen::domain_public::{
        ACTORS, EVENT_CODES, HOLDS, HOME_STATES, IMPORTANCE_TIERS, REASONS, RELEASABLE_WITHDRAWALS,
        TURN_STATUSES, WITHDRAW_REASONS,
    };
    pub use car_machine::vocab_gen::domain_states::{
        CLAIMED, EXHAUSTED, IN_FLIGHT, OBSERVING, STATES, TERMINAL, V2_STATES, WAITING, WATCHED,
    };
    pub use car_machine::vocab_gen::domain_usage::{
        BUCKETS as USAGE_BUCKETS, KEYS as USAGE_KEYS, SLOTS as USAGE_SLOTS,
    };

    pub use car_machine::vocab_gen::domain_vocabulary::WatcherEnd;
    pub use car_policy::classify::failures::CATEGORIES;
    pub use car_policy::classify::needsyou::NOTICE_KINDS;

    /// `WatcherEnd`, in order (`domain/vocabulary.py`): car-machine's enum, as words.
    pub const WATCHER_ENDS: &[&str] = &[
        WatcherEnd::Running.as_str(),
        WatcherEnd::Clean.as_str(),
        WatcherEnd::MemoryGuard.as_str(),
        WatcherEnd::Unexpected.as_str(),
    ];

    #[cfg(test)]
    mod tests {
        use super::*;

        #[test]
        fn the_watcher_ends_are_the_enum() {
            let words: Vec<&str> = WatcherEnd::ALL.iter().map(|end| end.as_str()).collect();
            assert_eq!(WATCHER_ENDS, words.as_slice());
        }
    }
}

/// What the store reads of car-policy (S2.1): car-policy's own items, by the names the store's Python reads them.
pub mod policy {
    pub use car_policy::classify::failures::{USAGE_LIMIT, is_recoverable};
    pub use car_policy::classify::gates;
    pub use car_policy::classify::needsyou::KEEP_SECONDS;
    pub use car_policy::classify::quiet::postponement_problem;
}

/// `value in words`.
pub fn has(words: &[&str], word: &str) -> bool {
    words.contains(&word)
}

/// The Python exception a car-machine function names, as the store raises it.
pub fn raised(class: &'static str) -> Error {
    let message = match class {
        "OverflowError" => "int too large to convert to float",
        "TypeError" => "unsupported operand type(s)",
        "AttributeError" => "object has no attribute 'get'",
        "ValueError" => "invalid value",
        _ => "error",
    };
    Error::Python(class, message.into())
}

fn py<T>(answer: car_machine::pyval::Py<T>) -> Result<T> {
    answer.map_err(raised)
}

/// `machine.epoch(value, *EPOCH_STORE)`: a number of seconds in the store's window, never a bool, a NaN or an
/// infinity. An `int` too large to be a float raises OverflowError there, as `math.isfinite` does.
pub fn epoch_store(value: &Value) -> Result<bool> {
    let (low, high) = states::EPOCH_STORE;
    py(states::epoch(value, low, high, false, true))
}

/// `machine.may_be_queued(state, queue_id)`.
pub fn may_be_queued(state: &Value, queue_id: &Value) -> Result<bool> {
    py(states::may_be_queued(state, queue_id))
}

/// `machine.plain_move_allowed(old, new)`.
pub fn plain_move_allowed(old: &str, new: &str) -> bool {
    // Two texts hash and compare: car-machine's only error is for a list or a dict.
    states::plain_move_allowed(&string(old), &string(new)).unwrap_or(false)
}

/// `machine.waiting_state(record, now)`.
pub fn waiting_state(record: &Row, now: f64) -> Result<&'static str> {
    py(states::waiting_state(
        &Value::Object(record.clone()),
        &Value::Float(now),
    ))
}

fn word(answer: Value) -> Option<String> {
    match answer {
        Value::Str(text) => text.as_str().map(str::to_owned),
        _ => None,
    }
}

/// `machine.event_code(value)`.
pub fn event_code(value: &str) -> String {
    word(public::event_code(&string(value))).unwrap_or_else(|| "other".into())
}

/// `machine.reason_code(value)`: None stays None; a word outside the list is "other".
pub fn reason_code(value: &Value) -> Option<String> {
    word(public::reason_code(value))
}

/// `machine.actor_code(value)`.
pub fn actor_code(value: &str) -> String {
    word(public::actor_code(&string(value))).unwrap_or_else(|| "engine".into())
}

/// `machine.turn_status(value)`.
pub fn turn_status(value: &Value) -> Option<String> {
    word(public::turn_status(value))
}

/// `machine.hold_for_tier(tier)`: Ask me first holds `ask`, Only notify me `notify_only`.
pub fn hold_for_tier(tier: &Value) -> Option<String> {
    word(public::hold_for_tier(tier))
}

/// `machine.own_postponement(record, now)`: a person's `not_before`, past the objection window, still ahead.
pub fn own_postponement(record: &Row, now: Option<f64>) -> Result<Option<f64>> {
    let now = now.map_or(Value::Null, Value::Float);
    let until = py(public::own_postponement(
        &Value::Object(record.clone()),
        &now,
    ))?;
    Ok(number(&until))
}

/// `domain/ids.py`, as the store reads it.
pub mod ids {
    use super::*;

    /// Why a value is not a UUID in canonical text (`ids.uuid_problem`).
    #[derive(Clone, Copy, Debug, PartialEq, Eq)]
    pub enum UuidProblem {
        /// `MALFORMED`: not a UUID at all.
        Malformed,
        /// `NOT_CANONICAL`: a UUID, written some other way than the canonical text.
        NotCanonical,
    }

    /// `ids.uuid_problem(value)`.
    pub fn uuid_problem(value: &Value) -> Option<UuidProblem> {
        domain_ids::uuid_problem(value, false).map(|problem| {
            if problem == car_machine::vocab_gen::domain_ids::NOT_CANONICAL {
                UuidProblem::NotCanonical
            } else {
                UuidProblem::Malformed
            }
        })
    }

    /// `ids.is_digest(value)`.
    pub fn is_digest(value: &Value) -> bool {
        domain_ids::is_digest(value)
    }

    /// `ids.is_digest` of a text.
    pub fn is_digest_text(candidate: &str) -> bool {
        domain_ids::is_digest(&string(candidate))
    }

    /// `ids.is_interruption_id(value, as_stored=...)`.
    pub fn is_interruption_id(value: &Value, as_stored: bool) -> bool {
        domain_ids::is_interruption_id(value, as_stored)
    }

    /// `ids.is_client_id(value)`.
    pub fn is_client_id(value: &Value) -> bool {
        domain_ids::is_client_id(value)
    }

    pub use domain_ids::{continuation_client_id, marker, record_markers, short_marker};
}

/// `domain/usage.py`: the last usage reading, as the watcher's heartbeat keeps it.
pub mod usage {
    use super::*;

    /// `usage.encode(windows)`: compact JSON, or None.
    pub fn encode(windows: &Value) -> Result<Option<String>> {
        py(domain_usage::encode(windows))
    }

    /// `usage.decode(text)`.
    pub fn decode(stored: &Value) -> Result<Option<Vec<Value>>> {
        py(domain_usage::decode(stored))
    }
}
