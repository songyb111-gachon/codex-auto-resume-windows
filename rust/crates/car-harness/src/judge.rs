//! `engine.step` {op: "judge"} (review 6, S4): car-engine's `impossible` - the watcher's judge of its own looks, pure -
//! run through the same script and cases as the reference's `engine/impossible.py` (`enginerun.judge`).
//!
//! * `script`: `["look", now, app_runs, facts]`, `["tick", app_runs, facts]`, `["word", now]` on one fresh `Judge`;
//! * `usage`: `[limits, results]` cases of `usage_reason`;
//! * `facts`: `recovery_facts`' keyword cases (`matched`, `server`, `reasons`, `lock_holders`, `database_holders`,
//!   `locks_folder`, `older_holders`).
//!
//! The reply is {words, usage, facts}, as the reference's.

use std::collections::{BTreeMap, BTreeSet};

use car_engine::impossible::{
    DETECTION_RULES, Judge, Look, RECOVERY_RULES, recovery_facts, usage_reason,
};
use car_machine::json::{Map, Value};
use car_policy::classify::value::{arithmetic, text};

use crate::object;

/// A rule's name as the judge's `'static` key, or None for a name it does not know (never judged).
fn rule(name: &str) -> Option<&'static str> {
    RECOVERY_RULES
        .iter()
        .chain(DETECTION_RULES.iter())
        .find(|each| **each == name)
        .copied()
}

fn look_facts(value: Option<&Value>) -> BTreeMap<&'static str, Option<bool>> {
    let mut found = BTreeMap::new();
    if let Some(Value::Object(map)) = value {
        for (name, fact) in map {
            if let Some(name) = name.as_str().and_then(rule) {
                found.insert(
                    name,
                    match fact {
                        Value::Bool(flag) => Some(*flag),
                        _ => None,
                    },
                );
            }
        }
    }
    found
}

fn tick_facts(value: Option<&Value>) -> BTreeMap<&'static str, bool> {
    look_facts(value)
        .into_iter()
        .filter_map(|(name, fact)| fact.map(|fact| (name, fact)))
        .collect()
}

fn number(value: Option<&Value>) -> f64 {
    value.and_then(arithmetic).unwrap_or(0.0)
}

fn ints(value: Option<&Value>) -> Vec<i64> {
    match value {
        Some(Value::Array(items)) => items
            .iter()
            .filter_map(|item| match item {
                Value::Int(number) => number.as_i64(),
                _ => None,
            })
            .collect(),
        _ => Vec::new(),
    }
}

fn cases(request: &Map, name: &str) -> Vec<Value> {
    match request.get(name) {
        Some(Value::Array(items)) => items.clone(),
        _ => Vec::new(),
    }
}

/// The judge step's reply.
pub fn run(request: &Map) -> Value {
    let mut judge = Judge::new();
    let mut words = Vec::new();
    for step in cases(request, "script") {
        let Value::Array(step) = step else { continue };
        let runs = |index: usize| matches!(step.get(index), Some(Value::Bool(true)));
        match step.first().and_then(text) {
            Some("look") => judge.look(number(step.get(1)), runs(2), &look_facts(step.get(3))),
            Some("tick") => judge.tick(runs(1), &tick_facts(step.get(2))),
            _ => words.push(
                judge
                    .word(number(step.get(1)))
                    .map_or(Value::Null, Value::from),
            ),
        }
    }
    let usage: Vec<Value> = cases(request, "usage")
        .iter()
        .map(|case| match case {
            Value::Array(pair) => Value::from(usage_reason(
                pair.first().unwrap_or(&Value::Null),
                pair.get(1).unwrap_or(&Value::Null),
            )),
            _ => Value::Null,
        })
        .collect();
    let facts: Vec<Value> = cases(request, "facts")
        .iter()
        .map(|case| {
            let Value::Object(case) = case else {
                return Value::Null;
            };
            let reasons: BTreeSet<String> = match case.get("reasons") {
                Some(Value::Array(items)) => items
                    .iter()
                    .filter_map(|item| text(item).map(str::to_owned))
                    .collect(),
                _ => BTreeSet::new(),
            };
            let lock_holders = ints(case.get("lock_holders"));
            let database_holders = match case.get("database_holders") {
                Some(Value::Array(_)) => Some(ints(case.get("database_holders"))),
                _ => None,
            };
            let older_holders: Vec<Vec<i64>> = match case.get("older_holders") {
                Some(Value::Array(items)) => items.iter().map(|item| ints(Some(item))).collect(),
                _ => Vec::new(),
            };
            let look = Look {
                matched: matches!(case.get("matched"), Some(Value::Bool(true))),
                server: match case.get("server") {
                    Some(Value::Int(number)) => number.as_i64(),
                    _ => None,
                },
                reasons: &reasons,
                lock_holders: &lock_holders,
                database_holders: database_holders.as_deref(),
                locks_folder: match case.get("locks_folder") {
                    Some(Value::Bool(flag)) => Some(*flag),
                    _ => None,
                },
                older_holders: &older_holders,
            };
            let mut map = Map::new();
            for (name, fact) in recovery_facts(&look) {
                map.insert(name.into(), fact.map_or(Value::Null, Value::Bool));
            }
            Value::Object(map)
        })
        .collect();
    object([
        ("words", Value::Array(words)),
        ("usage", Value::Array(usage)),
        ("facts", Value::Array(facts)),
    ])
}
