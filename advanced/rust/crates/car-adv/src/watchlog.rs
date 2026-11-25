//! What a watched capability would have done: the journal's first reader, and its only one (`watchlog.py`).
//!
//! Read-only: the stored arming rows and the journal, never anything that can carry out a trip; content-free - per
//! capability one entry per answer word, every time in whole seconds rounded down to the minute.

use car_machine::json::{Str, Value};
use car_policy::plug::vocab_gen::domain_plug::POINTS;

use crate::state::ask::RegistryAsked;
use crate::state::errors::Result;
use crate::state::py;
use crate::state::session::AdvancedState;
use crate::state::sql::{self, Row, int, string};
use crate::state::{EVENT_LIMIT, WATCH_LIMIT};
use crate::vocabulary::{ArmingState, JournalCode, Refusal};

pub const WINDOW_DAYS: i64 = crate::state::choices::RECENT_DAYS;
const DAY: f64 = 86400.0;
/// The points whose answer is a value, not a word (`VALUE_POINTS`).
pub const VALUE_POINTS: &[&str] = &[
    "text",
    "sender",
    "tick",
    "start_route",
    "unloaded",
    "concurrency",
    "records",
    "notice",
    "power",
];

/// `WORDS`: every alternative, and the value points.
fn is_word(answer: &Value) -> bool {
    py::is_word(answer, &py::alternatives()) || py::is_word(answer, VALUE_POINTS)
}

/// `minute(at)`: `at` in whole seconds rounded down to the minute; None for anything that is not a time.
pub fn minute(at: &Value) -> Value {
    if !py::is_number(at) {
        return Value::Null;
    }
    match car_machine::pyval::is_finite(at) {
        Ok(true) => {}
        _ => return Value::Null,
    }
    match at {
        Value::Int(number) => match number.as_i64() {
            Some(whole) => int(whole.div_euclid(60) * 60),
            None => Value::Null,
        },
        Value::Float(seconds) => int(py::floordiv(*seconds, 60.0) as i64 * 60),
        _ => Value::Null,
    }
}

/// `entries(lines)`: lines grouped by answer word, the most counted first.
pub fn entries(lines: &[Row]) -> Vec<Row> {
    struct Entry {
        answer: Value,
        points: Vec<String>,
        count: i64,
        first: Value,
        last: Value,
    }
    let mut grouped: Vec<Entry> = Vec::new();
    for line in lines {
        let answer = sql::get(line, "answer");
        let word = if is_word(answer) {
            string(py::text(answer).unwrap_or_default())
        } else {
            Value::Null
        };
        let index = match grouped
            .iter()
            .position(|entry| sql::py_eq(&entry.answer, &word))
        {
            Some(index) => index,
            None => {
                grouped.push(Entry {
                    answer: word,
                    points: Vec::new(),
                    count: 0,
                    first: Value::Null,
                    last: Value::Null,
                });
                grouped.len() - 1
            }
        };
        let entry = &mut grouped[index];
        let point = sql::get(line, "point");
        if let Some(point) = py::text(point).filter(|point| POINTS.contains(point))
            && !entry.points.iter().any(|each| each == point)
        {
            entry.points.push(point.to_string());
        }
        entry.count += 1;
        let at = minute(sql::get(line, "at"));
        if let Some(at) = py::small(&at) {
            entry.first = int(py::small(&entry.first).map_or(at, |first| first.min(at)));
            entry.last = int(py::small(&entry.last).map_or(at, |last| last.max(at)));
        }
    }
    let mut shown: Vec<Row> = grouped
        .into_iter()
        .map(|mut entry| {
            entry.points.sort();
            let mut row = Row::new();
            row.insert(sql::key("answer"), entry.answer);
            row.insert(
                sql::key("points"),
                Value::Array(entry.points.iter().map(|point| string(point)).collect()),
            );
            row.insert(sql::key("count"), int(entry.count));
            row.insert(sql::key("first"), entry.first);
            row.insert(sql::key("last"), entry.last);
            row
        })
        .collect();
    shown.sort_by_key(|entry| {
        let count = py::small(sql::get(entry, "count")).unwrap_or(0);
        let answer = py::text(sql::get(entry, "answer"))
            .unwrap_or("~")
            .to_string();
        (-count, answer)
    });
    shown
}

/// `_of(row, lines, now)`: one capability's log from its stored row and its journal lines, oldest first.
fn of(row: Option<&Row>, lines: &[Row], now: f64) -> Row {
    let watched: Vec<&Row> = lines
        .iter()
        .filter(|line| py::is_word(sql::get(line, "code"), &[JournalCode::WouldHave.as_str()]))
        .collect();
    let limit = WATCH_LIMIT as usize;
    let counted = &watched[watched.len().saturating_sub(limit)..];
    let start = now - (WINDOW_DAYS as f64) * DAY;
    let recent: Vec<Row> = counted
        .iter()
        .filter(|line| py::as_f64(sql::get(line, "at")).is_some_and(|at| at >= start))
        .map(|line| (*line).clone())
        .collect();
    let full = watched.len() >= limit && recent.len() == counted.len();
    let since = match row {
        Some(row) if py::is_word(sql::get(row, "state"), &[ArmingState::Shadow.as_str()]) => {
            sql::get(row, "since").clone()
        }
        _ => Value::Null,
    };
    let mut found = Row::new();
    found.insert(sql::key("watched_since"), minute(&since));
    found.insert(
        sql::key("entries"),
        Value::Array(entries(&recent).into_iter().map(Value::Object).collect()),
    );
    found.insert(
        sql::key("from"),
        recent
            .first()
            .map_or(Value::Null, |line| minute(sql::get(line, "at"))),
    );
    found.insert(sql::key("full"), Value::Bool(full));
    found
}

fn arming_row(rows: &Row, capability: &str) -> Option<Row> {
    match rows.get(capability) {
        Some(Value::Object(row)) => Some(row.clone()),
        _ => None,
    }
}

fn refused(word: &str) -> Row {
    let mut found = Row::new();
    found.insert(sql::key("done"), Value::Bool(false));
    found.insert(sql::key("refusal"), string(word));
    found
}

/// `view(runtime, capability)`: the Dashboard's `advanced-watch-log`.
pub fn view(state: &AdvancedState, capability: &Value, now: f64) -> Result<Row> {
    let Some(definition) = state.registry.get_value(capability).cloned() else {
        return Ok(refused(Refusal::UnknownCapability.as_str()));
    };
    let id = string(&definition.id);
    let read = (|| -> Result<(Row, Vec<Row>)> {
        let rows = state.arming()?;
        let lines = state.journal(&id, &int(EVENT_LIMIT))?;
        Ok((rows, lines))
    })();
    let (rows, lines) = match read {
        Ok(found) => found,
        Err(error) if error.is_state() => return Ok(refused(Refusal::StateUnavailable.as_str())),
        Err(error) => return Err(error),
    };
    let mut found = of(arming_row(&rows, &definition.id).as_ref(), &lines, now);
    found.insert(sql::key("done"), Value::Bool(true));
    found.insert(sql::key("capability"), id);
    found.insert(sql::key("days"), int(WINDOW_DAYS));
    Ok(found)
}

/// `exported(runtime)`: every capability stored as watched or with answers in the window, in the registry's order.
pub fn exported(state: &AdvancedState, now: f64) -> Result<Vec<Row>> {
    let read = (|| -> Result<(Row, Vec<Row>)> {
        let rows = state.arming()?;
        let lines = state.journal(&Value::Null, &int(EVENT_LIMIT))?;
        Ok((rows, lines))
    })();
    let (rows, lines) = match read {
        Ok(found) => found,
        Err(error) if error.is_state() => return Ok(Vec::new()),
        Err(error) => return Err(error),
    };
    let mut shown = Vec::new();
    for definition in state.registry.definitions.iter() {
        let own: Vec<Row> = lines
            .iter()
            .filter(|line| py::is_word(sql::get(line, "capability"), &[definition.id.as_str()]))
            .cloned()
            .collect();
        let found = of(arming_row(&rows, &definition.id).as_ref(), &own, now);
        let has_entries =
            matches!(found.get("entries"), Some(Value::Array(items)) if !items.is_empty());
        if !matches!(sql::get(&found, "watched_since"), Value::Null) || has_entries {
            let mut entry = Row::new();
            entry.insert(Str::new("capability"), string(&definition.id));
            for (key, value) in found {
                entry.insert(key, value);
            }
            shown.push(entry);
        }
    }
    Ok(shown)
}
