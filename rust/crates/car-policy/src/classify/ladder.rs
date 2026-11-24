//! `ladder.py`: how long a temporary failure waits before its continuation - the ladders, and what a person is
//! shown. Pure: nothing here reads a clock, a file or Codex.

use car_machine::json::Value;
use car_machine::pytext;
use car_machine::pyval::Py;

use super::seam::{DURATION, Own, WEEK, amount};
use super::value::{dict_or_empty, get, in_tuple, python_int, text};
pub use super::vocab_gen::ladder::{
    CEILINGS, CUSTOM, DEFAULT_CEILING, DEFAULT_STEPS, DEFAULT_TIMING, EARLY_STATES, FIRST_WAITS,
    LATER_WAITS, STEP_FIELDS, TIMINGS, WAITS,
};

/// `PRESETS`, v0.6.10's own.
pub const PRESETS: &[(&str, [i64; 5])] = &[
    ("conservative", [15, 45, 120, 300, 600]),
    ("normal", [5, 15, 30, 60, 120]),
    ("aggressive", [3, 8, 20, 45, 90]),
];
/// The engine's floor for one conversation: 15 minutes between two continuations, five a day.
pub const SPACING: i64 = 900;
pub const PER_DAY: i64 = 5;
/// A rate limit's first wait is never shorter (A22).
pub const RATE_LIMIT_FIRST: i64 = 60;
/// `WAIT_SECONDS`.
pub const WAIT_SECONDS: &[(&str, i64)] = &[
    ("s5", 5),
    ("s15", 15),
    ("s30", 30),
    ("m1", 60),
    ("m2", 120),
    ("m5", 300),
    ("m10", 600),
    ("m15", 900),
    ("m30", 1800),
    ("h1", 3600),
    ("h2", 7200),
    ("h3", 10800),
    ("h6", 21600),
];
/// `CEILING_SECONDS` (`off` is none).
pub const CEILING_SECONDS: &[(&str, Option<i64>)] = &[
    ("off", None),
    ("h1", Some(3600)),
    ("h3", Some(3 * 3600)),
    ("h6", Some(6 * 3600)),
    ("h12", Some(12 * 3600)),
    ("h24", Some(24 * 3600)),
];
/// Jitter: up to this share of a wait added to it, never taken off.
pub const JITTER_SHARE: f64 = 0.2;
/// The bounds of a failure the edition's plug took up (P17).
pub const ADMITTED_WAITS: [i64; 3] = [600, 900, 1800];
pub const ADMISSION_MAX_AGE: i64 = 6 * 3600;
pub const ADMITTED_MAX_SECONDS: i64 = 86400;
/// A capacity error the plug vouches for (CAPACITY).
pub const CAPACITY_WAITS: [i64; 4] = [60, 120, 240, 300];
pub const CAPACITY_SPACING: i64 = 60;
pub const CAPACITY_PER_DAY: i64 = 96;
pub const CAPACITY_MAX_SECONDS: i64 = 24 * 3600;
/// A usage limit whose reset core recorded has passed (VERIFIED_RESET): at most this many in 24 hours.
pub const RESET_PER_DAY: i64 = 24;
/// A usage-limited record the plug looks at early (EARLY).
pub const EARLY_SPACING: i64 = 300;
pub const EARLY_WINDOW: i64 = 30;

const OWN_FIRST: Own = Own::bounded(DURATION, 5, 2 * 3600, &["s", "m", "h"]);
const OWN_LATER: Own = Own::bounded(DURATION, SPACING, 6 * 3600, &["m", "h"]);
const OWN_CEILING: Own = Own::bounded(DURATION, SPACING, WEEK, &["m", "h"]);

/// `OWN[field]`.
pub fn own(field: &str) -> Option<&'static Own> {
    if field == STEP_FIELDS[0] {
        Some(&OWN_FIRST)
    } else if STEP_FIELDS[1..].contains(&field) {
        Some(&OWN_LATER)
    } else if field == "chain_time_ceiling" {
        Some(&OWN_CEILING)
    } else {
        None
    }
}

/// `WAIT_SECONDS[RetryWait(word)]`.
pub fn wait_seconds(word: &str) -> Option<i64> {
    WAIT_SECONDS
        .iter()
        .find(|(each, _)| *each == word)
        .map(|(_, seconds)| *seconds)
}

/// `choices_for(field)`: the waits one step of the Custom ladder may be.
pub fn choices_for(field: &str) -> &'static [&'static str] {
    if field == STEP_FIELDS[0] {
        FIRST_WAITS
    } else {
        LATER_WAITS
    }
}

/// `timing(values)`: the timing chosen; anything else is Normal.
pub fn timing(values: &Value) -> &'static str {
    let chosen = get(dict_or_empty(values), "retry_timing");
    TIMINGS
        .iter()
        .copied()
        .find(|each| text(chosen) == Some(*each))
        .unwrap_or(DEFAULT_TIMING)
}

/// `custom_steps(values)`: the five Custom waits in seconds.
pub fn custom_steps(values: &Value) -> [i64; 5] {
    let values = dict_or_empty(values);
    let mut found = [0; 5];
    for (at, (field, default)) in STEP_FIELDS.iter().zip(DEFAULT_STEPS).enumerate() {
        let chosen = get(values, field);
        let spec = own(field).expect("a step has its own");
        found[at] = match amount(spec, chosen).and_then(|measured| measured.number()) {
            Some(seconds) => seconds,
            None => {
                let word = if in_tuple(chosen, choices_for(field)) {
                    text(chosen).unwrap_or(default)
                } else {
                    default
                };
                wait_seconds(word).expect("a choice is a wait")
            }
        };
    }
    found
}

/// `ladder(values)`: the five waits in effect.
pub fn ladder(values: &Value) -> [i64; 5] {
    let chosen = timing(values);
    if chosen == CUSTOM {
        return custom_steps(values);
    }
    PRESETS
        .iter()
        .find(|(name, _)| *name == chosen)
        .map(|(_, steps)| *steps)
        .expect("a timing other than Custom is a preset")
}

/// `walks(values)`: whether the n-th attempt waits the n-th wait (Custom only).
pub fn walks(values: &Value) -> bool {
    timing(values) == CUSTOM
}

/// `wait_before(values, attempt, category)`: the wait before the `attempt`-th attempt at a task (1 for its first).
pub fn wait_before(values: &Value, attempt: &Value, category: &Value) -> Py<i64> {
    let steps = ladder(values);
    let walking = walks(values);
    let index = if walking {
        let count = python_int(attempt)?.min(steps.len() as i128);
        (count - 1).max(0) as usize
    } else {
        0
    };
    let mut delay = steps[index];
    if text(category) == Some("rate_limit_transient") && (index == 0 || !walking) {
        delay = delay.max(RATE_LIMIT_FIRST);
    }
    Ok(delay)
}

/// `preview(values)`: the wait before each of five attempts at a task, if each continuation fails at once.
pub fn preview(values: &Value) -> Vec<i64> {
    let steps = ladder(values);
    if walks(values) {
        let mut found = vec![steps[0]];
        found.extend(steps[1..].iter().map(|step| (*step).max(SPACING)));
        return found;
    }
    let mut found = vec![steps[0]];
    found.extend(std::iter::repeat_n(steps[0] + SPACING, steps.len() - 1));
    found
}

/// `previews()`: every preset's preview, in the presets' order.
pub fn previews() -> Vec<(&'static str, Vec<i64>)> {
    PRESETS
        .iter()
        .map(|(name, _)| {
            let mut values = car_machine::json::Map::new();
            values.insert("retry_timing".into(), Value::from(*name));
            (*name, preview(&Value::Object(values)))
        })
        .collect()
}

/// `round(x, 6)`: correctly rounded to six places, ties to even, as CPython rounds a float.
fn round6(x: f64) -> f64 {
    if !x.is_finite() {
        return x;
    }
    format!("{x:.6}").parse().unwrap_or(x)
}

/// `jittered(delay, values, draw)`: `delay`, lengthened by up to a fifth when jitter is on.
pub fn jittered(delay: &Value, values: &Value, draw: &Value) -> Py<Value> {
    if !matches!(
        get(dict_or_empty(values), "retry_jitter"),
        Value::Bool(true)
    ) {
        return Ok(delay.clone());
    }
    let share = match draw {
        Value::Float(x) if (0.0..1.0).contains(x) => *x,
        _ => 0.0,
    };
    let base = match delay {
        Value::Bool(on) => f64::from(u8::from(*on)),
        Value::Int(number) => pytext::to_float(&Value::Int(number.clone()))?,
        Value::Float(x) => *x,
        _ => return Err("TypeError"),
    };
    let rounded = round6(base * (1.0 + JITTER_SHARE * share));
    if rounded.is_nan() {
        return Err("ValueError");
    }
    if rounded.is_infinite() {
        return Err("OverflowError");
    }
    let ceiled = rounded.ceil();
    if ceiled.abs() < 9.0e18 {
        Ok(Value::from(ceiled as i64))
    } else {
        Ok(Value::Int(
            car_machine::json::Int::parse(&format!("{ceiled:.0}")).ok_or("OverflowError")?,
        ))
    }
}

/// `ceiling(values)`: the time ceiling in seconds, or None.
pub fn ceiling(values: &Value) -> Option<i64> {
    let chosen = get(dict_or_empty(values), "chain_time_ceiling");
    if let Some(word) = text(chosen)
        && let Some((_, seconds)) = CEILING_SECONDS.iter().find(|(each, _)| *each == word)
    {
        return *seconds;
    }
    amount(&OWN_CEILING, chosen).and_then(|found| found.number())
}
