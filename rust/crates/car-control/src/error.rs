//! `control/errors.py`: every way this layer refuses, and the two ways it reads an identity.
//!
//! A [`ControlError`] is the reference's `ControlError`: the English sentence a command line prints and a
//! stable code a front end puts in its own language. Everything else that goes wrong in a call - a Python
//! exception of any other class, as the reference lets one through - is [`Failure::Other`], which `dispatch`
//! answers with the generic refusal and no detail (`controlcli.GENERIC_ERROR`).

use car_machine::domain::ids;
use car_machine::json::{Str, Value};

/// The code for a refusal with nothing more specific to say (`FALLBACK_CODE`).
pub const FALLBACK_CODE: &str = "request_failed";
/// The most a budget may be given back (`store.MAX_BUDGET_RESETS`).
pub const MAX_BUDGET_RESETS: i64 = car_store::actions::MAX_BUDGET_RESETS;

/// `ControlError(message, code=...)`.
#[derive(Clone, Debug, PartialEq)]
pub struct ControlError {
    /// `str(exc)`: a Python `str`, so a settings sentence that carries a setting's name keeps it whole.
    pub message: Str,
    pub code: String,
}

impl ControlError {
    pub fn new(message: impl Into<Str>, code: &str) -> ControlError {
        ControlError {
            message: message.into(),
            code: if code.is_empty() {
                FALLBACK_CODE.to_owned()
            } else {
                code.to_owned()
            },
        }
    }

    /// `ControlError(message)`: the fallback code.
    pub fn plain(message: impl Into<Str>) -> ControlError {
        ControlError::new(message, FALLBACK_CODE)
    }
}

/// What leaves a call of this layer: its own refusal, or another exception by class.
#[derive(Clone, Debug, PartialEq)]
pub enum Failure {
    Control(ControlError),
    /// Any other Python exception (its class): the bridge answers it with the generic refusal.
    Other(String),
}

impl From<ControlError> for Failure {
    fn from(error: ControlError) -> Failure {
        Failure::Control(error)
    }
}

pub type Res<T> = Result<T, Failure>;

/// `raise ControlError(message, code=code)`.
pub fn refuse<T>(message: impl Into<Str>, code: &str) -> Res<T> {
    Err(Failure::Control(ControlError::new(message, code)))
}

/// What the store says when it refuses, as the sentence and the code (`_REFUSALS_*`): `(detail, sentence, code)`.
pub type Refusals = &'static [(Option<&'static str>, &'static str, &'static str)];

/// `_REFUSALS_RESTORE`.
pub const REFUSALS_RESTORE: Refusals = &[
    (
        Some("not_exhausted"),
        "that recovery has not been exhausted",
        "not_exhausted",
    ),
    (
        Some("finished"),
        "that recovery has already finished",
        "already_finished",
    ),
    (
        Some("cancel_requested"),
        "that recovery was cancelled",
        "cancel_requested",
    ),
    (
        Some("possibly_sent"),
        "that recovery may already have been sent",
        "possibly_sent",
    ),
    (
        Some("reset_limit"),
        "its budget was already reset %d times; continue this task in Codex yourself",
        "reset_limit",
    ),
    (
        Some("unknown_record"),
        "no such interruption",
        "no_such_interruption",
    ),
    (None, "that recovery cannot be continued", "cannot_continue"),
];

/// `_REFUSALS_RETRY`.
pub const REFUSALS_RETRY: Refusals = &[
    (
        Some("finished"),
        "that recovery has already finished",
        "already_finished",
    ),
    (
        Some("cancel_requested"),
        "that recovery was cancelled",
        "cancel_requested",
    ),
    (
        Some("claimed"),
        "that recovery is being sent now",
        "being_sent",
    ),
    (
        Some("in_flight"),
        "that recovery is already in Codex",
        "in_flight",
    ),
    (
        Some("observing"),
        "that recovery is already running in Codex",
        "observing",
    ),
    (
        Some("unknown_record"),
        "no such interruption",
        "no_such_interruption",
    ),
    (
        None,
        "that recovery cannot be checked now",
        "cannot_check_now",
    ),
];

/// `_REFUSALS_POSTPONE`: `_BOUND` and its own.
pub const REFUSALS_POSTPONE: Refusals = &[
    (
        Some("unknown_record"),
        "no such interruption",
        "no_such_interruption",
    ),
    (
        Some("thread_mismatch"),
        "that recovery belongs to a different conversation",
        "thread_mismatch",
    ),
    (
        Some("finished"),
        "that recovery has already finished",
        "already_finished",
    ),
    (
        Some("cancel_requested"),
        "that recovery was cancelled",
        "cancel_requested",
    ),
    (
        Some("claimed"),
        "that recovery is being sent now",
        "being_sent",
    ),
    (
        Some("in_flight"),
        "that recovery is already in Codex",
        "in_flight",
    ),
    (
        Some("observing"),
        "that recovery is already running in Codex",
        "observing",
    ),
    (
        Some("invalid_time"),
        "that is not a time to postpone a recovery to",
        "invalid_time",
    ),
    (
        Some("not_later"),
        "a recovery can only be postponed to a later time",
        "not_later",
    ),
    (
        Some("too_far"),
        "a recovery can be postponed by a week at most",
        "too_far",
    ),
    (None, "the request could not be completed", "request_failed"),
];

/// `_REFUSALS_RELEASE`.
pub const REFUSALS_RELEASE: Refusals = &[
    (
        Some("unknown_record"),
        "no such interruption",
        "no_such_interruption",
    ),
    (
        Some("thread_mismatch"),
        "that recovery belongs to a different conversation",
        "thread_mismatch",
    ),
    (
        Some("finished"),
        "that recovery has already finished",
        "already_finished",
    ),
    (
        Some("cancel_requested"),
        "that recovery was cancelled",
        "cancel_requested",
    ),
    (
        Some("not_held"),
        "that recovery is not waiting for you",
        "not_held",
    ),
    (None, "that recovery cannot be continued", "cannot_continue"),
];

/// `_REFUSALS_UNPOSTPONE`.
pub const REFUSALS_UNPOSTPONE: Refusals = &[
    (
        Some("unknown_record"),
        "no such interruption",
        "no_such_interruption",
    ),
    (
        Some("thread_mismatch"),
        "that recovery belongs to a different conversation",
        "thread_mismatch",
    ),
    (
        Some("finished"),
        "that recovery has already finished",
        "already_finished",
    ),
    (
        Some("cancel_requested"),
        "that recovery was cancelled",
        "cancel_requested",
    ),
    (
        Some("claimed"),
        "that recovery is being sent now",
        "being_sent",
    ),
    (
        Some("in_flight"),
        "that recovery is already in Codex",
        "in_flight",
    ),
    (
        Some("observing"),
        "that recovery is already running in Codex",
        "observing",
    ),
    (
        Some("not_postponed"),
        "that recovery has no postponement of yours to take away",
        "not_postponed",
    ),
    (None, "the request could not be completed", "request_failed"),
];

/// `_refusal(table, detail)`: the sentence and the code for what the store refused, or the table's last resort.
pub fn refusal(table: Refusals, detail: Option<&str>) -> (String, &'static str) {
    let (_, message, code) = table
        .iter()
        .find(|entry| detail.is_some() && entry.0 == detail)
        .or_else(|| table.iter().find(|entry| entry.0.is_none()))
        .expect("every table ends in its last resort");
    (message.replace("%d", &MAX_BUDGET_RESETS.to_string()), code)
}

/// `_identifier(value, name)`: interruption ids are opaque lowercase hex; nothing else addresses a record.
/// `str(value or "")` is the value's text, so a missing or empty one is the empty text.
pub fn identifier(value: &Value, name: &str) -> Res<String> {
    let text = if car_machine::pyval::truthy(value) {
        car_machine::pytext::py_str(value)
    } else {
        String::new()
    };
    match ids::read_interruption_id(&text) {
        Some(key) => Ok(key),
        None => refuse(format!("invalid {name}"), "invalid_id"),
    }
}

/// `_identifier(value)` with its default name.
pub fn interruption_id(value: &Value) -> Res<String> {
    identifier(value, "interruption id")
}

/// `_thread_id(value)`: any value, read as its text, that is a thread id; a UUID written another way is refused
/// with a sentence saying so.
pub fn thread_id(value: &Value) -> Res<String> {
    match ids::uuid_problem(value, true) {
        Some(problem) if problem == car_machine::vocab_gen::domain_ids::MALFORMED => {
            refuse("thread id must be a canonical UUID", "invalid_thread_id")
        }
        Some(_) => refuse(
            "thread id must be lowercase canonical UUID text",
            "invalid_thread_id",
        ),
        None => Ok(car_machine::pytext::py_str(value)),
    }
}
