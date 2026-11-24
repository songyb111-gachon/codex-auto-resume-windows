//! `power.py`: sleep, keeping this PC awake, and the network, as a waiting recovery meets them. Each is off by
//! default, and none of them sends anything or makes a recovery sooner. Pure: settings, records and times in.

use car_machine::domain::public::eligible_at;
use car_machine::json::{Str, Value};
use car_machine::pytext;
use car_machine::pyval::{self, Py};

use super::value::{dict_get, dict_or_empty, get, in_tuple, text, truthy};
pub use super::vocab_gen::power::{HOLD, OFFLINE};
use crate::settings::ownvalues::{Own, OwnKind, WEEK, amount};

pub const KEEP_AWAKE_FIELD: &str = "keep_awake";
pub const AWAKE_CAP_FIELD: &str = "keep_awake_hours";
pub const SLEEP_FIELD: &str = "ask_after_sleep_minutes";
pub const NETWORK_FIELD: &str = "wait_for_network";
/// `KEEP_AWAKE_MODES`, `AWAKE_CAPS` and `SLEEP_WAITS`: `tuple(KeepAwake)`, `tuple(AwakeCap)`, `tuple(SleepWait)`.
pub const KEEP_AWAKE_MODES: &[&str] = &["off", "on_ac", "always"];
pub const AWAKE_CAPS: &[&str] = &["h1", "h2", "h3", "h6", "h12", "h24", "unlimited"];
pub const SLEEP_WAITS: &[&str] = &["off", "m30", "h1", "h2", "h3", "h6", "h12"];
pub const DEFAULT_KEEP_AWAKE: &str = "off";
pub const DEFAULT_AWAKE_CAP: &str = "h6";
pub const DEFAULT_SLEEP: &str = "off";
/// Less than this between the two clocks is no sleep.
pub const MIN_SLEEP_SECONDS: f64 = 60.0;
pub const OWN_SLEEP: Own = Own::new(OwnKind::Duration, 5 * 60, WEEK, &["m", "h"]);
pub const OWN_AWAKE_CAP: Own = Own::new(OwnKind::Duration, 15 * 60, WEEK, &["m", "h"]);

/// `keep_awake(values)`: off, on_ac or always.
pub fn keep_awake(values: &Value) -> &'static str {
    let chosen = get(dict_or_empty(values), KEEP_AWAKE_FIELD);
    KEEP_AWAKE_MODES
        .iter()
        .copied()
        .find(|mode| in_tuple(chosen, &[mode]))
        .unwrap_or(DEFAULT_KEEP_AWAKE)
}

/// `awake_cap(values)`: for how many seconds, at most, the PC is kept awake - None for Unlimited.
pub fn awake_cap(values: &Value) -> Option<i64> {
    let chosen = get(dict_or_empty(values), AWAKE_CAP_FIELD);
    if text(chosen) == Some("unlimited") {
        return None;
    }
    amount(&OWN_AWAKE_CAP, chosen)
        .or_else(|| amount(&OWN_AWAKE_CAP, &Value::from(DEFAULT_AWAKE_CAP)))
        .and_then(|found| found.number())
}

/// `sleep_threshold(values)`: how long a sleep must last before what fell due during it waits for a person.
pub fn sleep_threshold(values: &Value) -> Option<i64> {
    amount(&OWN_SLEEP, get(dict_or_empty(values), SLEEP_FIELD)).and_then(|found| found.number())
}

/// `waits_for_network(values)`.
pub fn waits_for_network(values: &Value) -> bool {
    matches!(get(dict_or_empty(values), NETWORK_FIELD), Value::Bool(true))
}

/// `listens(values)`: whether the watcher listens for this PC waking.
pub fn listens(values: &Value) -> bool {
    sleep_threshold(values).is_some() || keep_awake(values) != "off"
}

/// `reading[index]` of a reading: a list's item, a text's character; a dict raises KeyError, anything else TypeError
/// (an IndexError past the end).
fn item(reading: &Value, index: usize) -> Py<Value> {
    match reading {
        Value::Array(items) => items.get(index).cloned().ok_or("IndexError"),
        Value::Str(said) => said
            .code_points()
            .nth(index)
            .map(|point| Value::Str(Str::from_code_points([point]).expect("a code point")))
            .ok_or("IndexError"),
        Value::Object(_) => Err("KeyError"),
        _ => Err("TypeError"),
    }
}

/// `asleep(before, after)`: seconds this PC spent asleep between two readings, each (wall clock, time awake).
pub fn asleep(before: &Value, after: &Value) -> Py<f64> {
    let caught = |error: &'static str| match error {
        "TypeError" | "ValueError" | "IndexError" => Ok(0.0),
        other => Err(other),
    };
    let read =
        |reading: &Value, index: usize| -> Py<f64> { pytext::to_float(&item(reading, index)?) };
    let slept = (|| -> Py<f64> {
        let wall = read(after, 0)? - read(before, 0)?;
        let awake = read(after, 1)? - read(before, 1)?;
        Ok(wall - awake)
    })();
    match slept {
        Ok(slept) if slept.is_finite() && slept >= MIN_SLEEP_SECONDS => Ok(slept),
        Ok(_) => Ok(0.0),
        Err(error) => caught(error),
    }
}

/// `fell_due(row, since, until)`: whether a waiting record fell due in (since, until].
pub fn fell_due(row: &Value, since: &Value, until: &Value) -> Py<bool> {
    let due = eligible_at(row)?;
    if matches!(due, Value::Null) {
        return Ok(false);
    }
    Ok(pyval::less(since, &due)? && pyval::less_or_equal(&due, until)?)
}

/// `waiting(rows)`: how many of these records a PC kept awake would be kept awake for.
pub fn waiting(rows: &Value) -> Py<i64> {
    let Value::Array(rows) = rows else {
        return Err("TypeError");
    };
    let mut count = 0;
    for row in rows {
        if !matches!(eligible_at(row)?, Value::Null) && !truthy(dict_get(row, "cancel_requested")?)
        {
            count += 1;
        }
    }
    Ok(count)
}

/// `wants_awake(mode, count, mains)`: whether this PC is to be kept awake now, its hours aside.
pub fn wants_awake(mode: &Value, count: &Value, mains: &Value) -> Py<bool> {
    if !in_tuple(mode, &["on_ac", "always"]) || pyval::less_or_equal(count, &Value::from(0))? {
        return Ok(false);
    }
    Ok(pyval::is(mode, "always") || matches!(mains, Value::Bool(true)))
}

#[cfg(test)]
mod tests {
    use super::*;
    use car_machine::vocab_gen::domain_vocabulary as v;

    fn words<T: Copy>(all: &[T], as_str: fn(T) -> &'static str) -> Vec<&'static str> {
        all.iter().map(|each| as_str(*each)).collect()
    }

    /// The lists `power.py` takes of the vocabulary (`tuple(KeepAwake)` and the two more) are car-machine's words.
    #[test]
    fn the_modules_lists_are_the_vocabularys() {
        assert_eq!(
            KEEP_AWAKE_MODES,
            words(v::KeepAwake::ALL, v::KeepAwake::as_str)
        );
        assert_eq!(AWAKE_CAPS, words(v::AwakeCap::ALL, v::AwakeCap::as_str));
        assert_eq!(SLEEP_WAITS, words(v::SleepWait::ALL, v::SleepWait::as_str));
    }
}
