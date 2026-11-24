//! `needsyou.py`: a conversation that needs a person, said once - a failure the classifier knows and will not retry,
//! or a turn that has recorded nothing new for a while. Off by default. Pure: settings in, words out.

use car_machine::json::Value;
use car_machine::pyval::Py;

use super::value::{get, python_int};
pub use super::vocab_gen::needsyou::{
    DEFAULT_STALL, EVENT, EVENT_FIELD, KINDS, NOTICE_KINDS, SOUND_FIELD, STALL_FIELD, STALL_WAITS,
    STALLED,
};
use crate::settings::ownvalues::{Own, OwnKind, WEEK, amount};

/// A failure or a stopped turn older than this is never told: a week.
pub const WINDOW_SECONDS: i64 = WEEK;
/// A notice kept past a day more than the window may be let go.
pub const KEEP_SECONDS: i64 = WINDOW_SECONDS + 86400;
/// `OWN[STALL_FIELD]`: a stall of the person's own, in whole minutes, from 5 of them to a week.
pub const OWN_STALL: Own = Own::new(OwnKind::Duration, 5 * 60, WINDOW_SECONDS, &["m", "h"]);

/// `KIND_FIELDS[kind]`: the setting that switches a kind.
pub fn kind_field(kind: &str) -> Option<String> {
    kind.strip_prefix("terminal_")
        .filter(|_| KINDS.contains(&kind))
        .map(|rest| format!("notify_needs_you_{rest}"))
}

/// `NEXT_STEPS[kind]`: the catalog sentence each kind is told with.
pub fn next_step(kind: &str) -> Option<String> {
    if kind == STALLED {
        return Some("msg.needs_you_stalled".to_owned());
    }
    kind.strip_prefix("terminal_")
        .filter(|_| KINDS.contains(&kind))
        .map(|rest| format!("msg.needs_you_{rest}"))
}

fn on(values: &Value, name: &str) -> bool {
    match values {
        Value::Object(map) => matches!(get(map, name), Value::Bool(true)),
        _ => false,
    }
}

/// `told(values)`: notifications on, and this one of them.
pub fn told(values: &Value) -> bool {
    on(values, "notifications") && on(values, EVENT_FIELD)
}

/// `kinds(values)`: the failure categories a notice is raised for now, in KINDS' order.
pub fn kinds(values: &Value) -> Vec<&'static str> {
    if !told(values) {
        return Vec::new();
    }
    KINDS
        .iter()
        .copied()
        .filter(|kind| on(values, &kind_field(kind).expect("a kind has a field")))
        .collect()
}

/// `stall_seconds(values)`: how long a turn may record nothing new before it is told, or None.
pub fn stall_seconds(values: &Value) -> Option<i64> {
    let Value::Object(map) = values else {
        return None;
    };
    if !told(values) {
        return None;
    }
    amount(&OWN_STALL, get(map, STALL_FIELD)).and_then(|found| found.number())
}

/// `minutes(seconds)`: a stall's length in whole minutes, as the notice says it.
pub fn minutes(seconds: &Value) -> Py<i128> {
    Ok(python_int(seconds)?.div_euclid(60).max(1))
}
