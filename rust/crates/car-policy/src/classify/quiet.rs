//! `quiet.py`: quiet hours, and the times a postponement may name - local clock time, worked out in one place.
//!
//! Both are local wall-clock time, read through the clock the caller hands in ([`LocalClock`]): Windows' own
//! conversion in the product (car-platform), a zone of a test's own in the tests, as the Python takes `localtime=`
//! and `mktime=`.

use std::collections::BTreeSet;

use car_machine::json::Value;
use car_machine::pytext;
use car_machine::pyval::{self, Py};

use super::clock::LocalClock;
use super::value::{dict_or_empty, get};
pub use super::vocab_gen::quiet::{DAYS as DAY_CHOICES, MORNING, OFF, PRESETS, STARTS, TIMES};
use crate::settings::ownvalues::{Measured, Own, OwnKind, amount};

pub const DEFAULT_START: &str = OFF;
pub const DEFAULT_END: &str = "07:00";
pub const DEFAULT_DAYS: &str = "every_day";
/// The furthest ahead a postponement may be: a week.
pub const MAX_POSTPONE_SECONDS: i64 = 7 * 86400;
/// `_AHEAD`.
const AHEAD: &[(&str, i64)] = &[
    ("30_minutes", 1800),
    ("1_hour", 3600),
    ("3_hours", 3 * 3600),
];

/// `OWN_CLOCK` and `OWN_DAYS`: a time of the day and a set of weekdays, neither bounded.
pub const OWN_CLOCK: Own = Own::new(OwnKind::Clock, 0, 0, &[]);
pub const OWN_DAYS: Own = Own::new(OwnKind::Days, 0, 0, &[]);

/// `window(values)`: (start, end, weekdays) in minutes of the day, or None.
pub fn window(values: &Value) -> Option<(i64, i64, BTreeSet<i64>)> {
    let values = dict_or_empty(values);
    let start =
        amount(&OWN_CLOCK, get(values, "quiet_hours_start")).and_then(|found| found.number());
    let end = amount(&OWN_CLOCK, get(values, "quiet_hours_end")).and_then(|found| found.number());
    let days_value = values
        .get("quiet_hours_days")
        .cloned()
        .unwrap_or_else(|| Value::from(DEFAULT_DAYS));
    let days = match amount(&OWN_DAYS, &days_value) {
        Some(found @ Measured::Days(_)) => found.days(),
        _ => BTreeSet::new(),
    };
    let (start, end) = (start?, end?);
    if start == end || days.is_empty() {
        return None;
    }
    Some((start, end, days))
}

/// `_local(day, minute)`: the moment `minute` of the day falls on `day` (which may run past the month's end).
fn local(clock: &dyn LocalClock, day: (i64, i64, i64), minute: i64) -> Py<f64> {
    clock.mktime(
        day.0,
        day.1,
        day.2,
        minute.div_euclid(60),
        minute.rem_euclid(60),
        0,
    )
}

/// `float(now)` of a number Python's `time` functions take.
fn seconds(now: &Value) -> Py<f64> {
    match now {
        Value::Bool(_) | Value::Int(_) | Value::Float(_) => pytext::to_float(now),
        _ => Err("TypeError"),
    }
}

/// `quiet_until(now, values)`: the end of the quiet hours `now` falls in, or None.
pub fn quiet_until(now: &Value, values: &Value, clock: &dyn LocalClock) -> Py<Option<f64>> {
    let Some((start, end, weekdays)) = window(values) else {
        return Ok(None);
    };
    if !matches!(now, Value::Bool(_) | Value::Int(_) | Value::Float(_)) || !pyval::is_finite(now)? {
        return Ok(None);
    }
    let moment = seconds(now)?;
    let today = clock.localtime(moment)?;
    for back in [1, 0] {
        let day = (today.year, today.mon, today.mday - back);
        if !weekdays.contains(&clock.localtime(local(clock, day, 12 * 60)?)?.wday) {
            continue;
        }
        let begins = local(clock, day, start)?;
        let ends = local(
            clock,
            (day.0, day.1, day.2 + if end > start { 0 } else { 1 }),
            end,
        )?;
        let begun = pyval::less_or_equal(&Value::Float(begins), now)?;
        if begun && pyval::less(now, &Value::Float(ends))? {
            return Ok(Some(ends));
        }
    }
    Ok(None)
}

/// `postpone_time(now, preset)`: when one of PRESETS lands from `now`, or None.
pub fn postpone_time(now: &Value, preset: &Value, clock: &dyn LocalClock) -> Py<Option<f64>> {
    pyval::hashable(preset)?;
    let word = pyval::text(preset);
    if let Some((_, ahead)) = AHEAD.iter().find(|(each, _)| Some(*each) == word) {
        return Ok(Some(pytext::to_float(now)? + *ahead as f64));
    }
    if word == Some("tomorrow_morning") {
        let today = clock.localtime(seconds(now)?)?;
        return local(clock, (today.year, today.mon, today.mday + 1), 9 * 60).map(Some);
    }
    Ok(None)
}

/// `postponement_problem(until, now, not_before)`: why `until` cannot be a record's postponement, or None.
pub fn postponement_problem(
    until: &Value,
    now: &Value,
    not_before: &Value,
) -> Py<Option<&'static str>> {
    if !matches!(until, Value::Int(_) | Value::Float(_)) || !pyval::is_finite(until)? {
        return Ok(Some("invalid_time"));
    }
    if pyval::less_or_equal(until, now)?
        || (!matches!(not_before, Value::Null) && pyval::less_or_equal(until, not_before)?)
    {
        return Ok(Some("not_later"));
    }
    let latest = match pyval::Num::of(now) {
        Some(pyval::Num::Whole(n)) => Value::from(n as i64 + MAX_POSTPONE_SECONDS),
        Some(other) => Value::Float(other.as_f64() + MAX_POSTPONE_SECONDS as f64),
        None => return Err("TypeError"),
    };
    if pyval::greater(until, &latest)? {
        return Ok(Some("too_far"));
    }
    Ok(None)
}
