//! `watcher.batch`'s checkup and rescan cases (S6.1): the Diagnostics check's words and verdicts, and Rescan's judge
//! over a scripted engine.
//!
//! * `["check_lines", result, now, locale]`, `["check_summary", rows, running, cloud]`, `["check_usage", status, now]`,
//!   `["check_ago", seconds, locale]`, `["check_within", seconds, locale]`, `["check_reason", code, kind, locale]`.
//! * `["rescan_proofs", kin]`; `["rescan_judge", row, kin, script, deadline, monotonic]`: the engine's answers the
//!   script's (`{"raise": class}` for one that raises), every call it was asked recorded.

use car_machine::json::{Map, Value};
use car_watcher::fail::{Failed, Res};
use car_watcher::rescan::RescanEngine;

use super::AsStr;

fn number(value: Option<&Value>) -> f64 {
    value.map_or(0.0, |found| {
        car_machine::pytext::to_float(found).unwrap_or(0.0)
    })
}

fn text(value: Option<&Value>) -> String {
    value
        .and_then(AsStr::as_str_value)
        .unwrap_or_default()
        .to_owned()
}

fn map(value: Option<&Value>) -> Map {
    match value {
        Some(Value::Object(found)) => found.clone(),
        _ => Map::new(),
    }
}

fn maps(value: Option<&Value>) -> Vec<Map> {
    match value {
        Some(Value::Array(items)) => items
            .iter()
            .filter_map(|each| match each {
                Value::Object(found) => Some(found.clone()),
                _ => None,
            })
            .collect(),
        _ => Vec::new(),
    }
}

struct ScriptEngine {
    script: Map,
    calls: Vec<Value>,
}

impl ScriptEngine {
    /// The next answer for `name`: a list's next item (its last once spent), or the value itself.
    fn answer(&mut self, name: &str, args: Vec<Value>) -> Res<Value> {
        let mut call = vec![Value::from(name)];
        call.extend(args);
        self.calls.push(Value::Array(call));
        let found = match self.script.get_mut(name) {
            Some(Value::Object(spec)) if spec.contains_key("each") => match spec.get_mut("each") {
                Some(Value::Array(items)) if items.len() > 1 => items.remove(0),
                Some(Value::Array(items)) => items.first().cloned().unwrap_or(Value::Null),
                _ => Value::Null,
            },
            Some(found) => found.clone(),
            None => Value::Null,
        };
        if let Value::Object(spec) = &found
            && let Some(Value::Str(class)) = spec.get("raise")
        {
            return Err(Failed::new(class.as_str().unwrap_or("Exception"), ""));
        }
        Ok(found)
    }
}

impl RescanEngine for ScriptEngine {
    fn proof(&mut self, row: &Map) -> Res<Value> {
        self.answer(
            "proof",
            vec![row.get("interruption_id").cloned().unwrap_or(Value::Null)],
        )
    }
    fn turn_observation(&mut self, thread: &Value, turn_id: &Value, proof: &Value) -> Res<Value> {
        self.answer(
            "turn_observation",
            vec![thread.clone(), turn_id.clone(), proof.clone()],
        )
    }
    fn later_turns(&mut self, thread: &Value, ordinal: &Value, proof: &Value) -> Res<Value> {
        self.answer(
            "later_turns",
            vec![thread.clone(), ordinal.clone(), proof.clone()],
        )
    }
    fn persons_turns(&mut self, thread: &Value, turns: &Value) -> Res<Vec<Value>> {
        match self.answer("persons_turns", vec![thread.clone(), turns.clone()])? {
            Value::Array(items) => Ok(items),
            Value::Null => Ok(match turns {
                Value::Array(items) => items.clone(),
                _ => Vec::new(),
            }),
            _ => Ok(Vec::new()),
        }
    }
    fn foreign(&mut self, _row: &Map, turn: &Value) -> Res<bool> {
        let id = match turn {
            Value::Object(found) => found.get("turn_id").cloned().unwrap_or(Value::Null),
            _ => Value::Null,
        };
        let found = self.answer("foreign", vec![id])?;
        Ok(!matches!(found, Value::Bool(false)))
    }
    fn turn_markers(&mut self, thread: &Value, turn_id: &Value, ours: &[String]) -> Res<bool> {
        let ours = Value::Array(ours.iter().map(|each| Value::from(each.as_str())).collect());
        let found = self.answer("turn_markers", vec![thread.clone(), turn_id.clone(), ours])?;
        Ok(car_machine::pyval::truthy(&found))
    }
    fn clock(&mut self) -> f64 {
        number(self.script.get("clock"))
    }
    fn fresh_throughout(&mut self, thread: &Value, now: f64) -> Res<bool> {
        let found = self.answer("fresh_throughout", vec![thread.clone(), Value::Float(now)])?;
        Ok(car_machine::pyval::truthy(&found))
    }
    fn valid_interruption(&mut self, row: &Map) -> Res<bool> {
        let found = self.answer(
            "valid_interruption",
            vec![row.get("interruption_id").cloned().unwrap_or(Value::Null)],
        )?;
        Ok(car_machine::pyval::truthy(&found))
    }
    fn rescan_evidence(&mut self, thread: &Value, turn_id: &Value) -> Res<Value> {
        self.answer("rescan_evidence", vec![thread.clone(), turn_id.clone()])
    }
}

/// One checkup or rescan case; None for a name of another family.
pub fn case(name: &str, args: &[Value]) -> Option<Result<Value, String>> {
    use car_watcher::checkup;
    Some(Ok(match name {
        "check_lines" => Value::Array(
            checkup::lines(
                args.first().unwrap_or(&Value::Null),
                number(args.get(1)),
                &text(args.get(2)),
            )
            .into_iter()
            .map(Value::from)
            .collect(),
        ),
        "check_summary" => {
            let rows = match args.first() {
                Some(Value::Array(items)) => items.clone(),
                _ => Vec::new(),
            };
            Value::from(checkup::summary(
                &rows,
                args.get(1).is_some_and(car_machine::pyval::truthy),
                args.get(2).unwrap_or(&Value::Null),
            ))
        }
        "check_usage" => checkup::usage(args.first().unwrap_or(&Value::Null), number(args.get(1))),
        "check_ago" => Value::from(checkup::ago(
            match args.first() {
                None | Some(Value::Null) => None,
                found => Some(number(found)),
            },
            &text(args.get(1)),
        )),
        "check_within" => Value::from(checkup::within(number(args.first()), &text(args.get(1)))),
        "check_reason" => Value::from(checkup::reason(
            &text(args.first()),
            args.get(1).and_then(AsStr::as_str_value),
            &text(args.get(2)),
        )),
        "rescan_proofs" => {
            let (found, free) = car_watcher::rescan::proofs(&maps(args.first()));
            Value::Array(vec![
                Value::Array(found.into_iter().map(Value::from).collect()),
                Value::Bool(free),
            ])
        }
        "rescan_judge" => {
            let row = map(args.first());
            let kin = maps(args.get(1));
            let mut engine = ScriptEngine {
                script: map(args.get(2)),
                calls: Vec::new(),
            };
            let deadline = match args.get(3) {
                None | Some(Value::Null) => None,
                found => Some(number(found)),
            };
            let (outcome, reason) = match car_watcher::rescan::judge(
                &mut engine,
                &row,
                &kin,
                deadline,
                number(args.get(4)),
            ) {
                Ok(found) => found,
                Err(failed) => return Some(Err(failed.class)),
            };
            Value::Array(vec![
                Value::from(outcome),
                reason.map_or(Value::Null, Value::from),
                Value::Array(engine.calls),
            ])
        }
        _ => return None,
    }))
}
