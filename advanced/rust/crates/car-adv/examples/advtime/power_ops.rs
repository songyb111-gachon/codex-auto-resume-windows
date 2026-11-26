//! `pt.*`: power_after_tasks' list, one task's end, the judge and P21 over scripted records and turn history.

use std::sync::{Arc, Mutex};

use car_adv::capabilities::{Code, Raised};
use car_adv::engine::powertasks::{self, PowerAfterTasks, TurnHistory};
use car_machine::json::{Map, Value};

use crate::common::{error, get, list, lock, object, paths_of, text};

pub fn answer(op: &str, case: &Map) -> Option<Result<Value, String>> {
    let home = text(get(case, "home"));
    Some(Ok(match op {
        "pt.valid" => Value::Bool(powertasks::valid(get(case, "document"))),
        "pt.read" => powertasks::read(&paths_of(&home)).unwrap_or(Value::Null),
        "pt.write" => {
            let paths = paths_of(&home);
            let done = powertasks::write(&paths, get(case, "document"));
            if matches!(get(case, "remove"), Value::Bool(true)) {
                powertasks::remove(&paths);
            }
            Value::Bool(done)
        }
        "pt.end_of" => {
            let log = Arc::new(Mutex::new(Vec::new()));
            let mut turns = History::new(case, log.clone());
            let records = list(get(case, "records"));
            let has = turns.has_latest();
            let history = std::cell::RefCell::new(&mut turns);
            let mut status_of =
                |thread: &Value, turn: &Value| history.borrow_mut().status(thread, turn);
            let mut latest_of = |thread: &Value| history.borrow_mut().latest(thread);
            let end = if has {
                powertasks::end_of(
                    get(case, "task"),
                    &records,
                    &mut status_of,
                    Some(&mut latest_of),
                )
            } else {
                powertasks::end_of(get(case, "task"), &records, &mut status_of, None)
            };
            object(vec![
                ("end", Value::Str(end.into())),
                ("log", Value::Array(lock(&log).clone())),
            ])
        }
        "pt.judge" => {
            let flag = |name: &str| matches!(get(case, name), Value::Bool(true));
            Value::Str(
                powertasks::judge(
                    &list(get(case, "ends")),
                    flag("failed"),
                    flag("interrupted"),
                )
                .into(),
            )
        }
        "pt.power" => {
            let log = Arc::new(Mutex::new(Vec::new()));
            let records = get(case, "records").clone();
            let reading = log.clone();
            let made = case.clone();
            let turning = log.clone();
            let mut code = PowerAfterTasks::new(
                paths_of(&home),
                Box::new(move || {
                    lock(&reading).push(Value::Array(vec![Value::Str("records".into())]));
                    match &records {
                        Value::Str(word) if word.as_str() == Some("raise") => {
                            Err(Raised::new("RuntimeError"))
                        }
                        Value::Array(items) => Ok(items.clone()),
                        _ => Ok(Vec::new()),
                    }
                }),
                Box::new(move || {
                    Ok(Box::new(History::new(&made, turning.clone())) as Box<dyn TurnHistory>)
                }),
            );
            let answer = match code.power(get(case, "facts")) {
                Ok(said) => said.to_value().unwrap_or(Value::Null),
                Err(raised) => error(&raised),
            };
            object(vec![
                ("answer", answer),
                ("log", Value::Array(lock(&log).clone())),
            ])
        }
        _ => return None,
    }))
}

/// The reference's scripted `Turns`: `status` by "thread|turn", `latest` (where the case has it) by thread.
struct History {
    script: Map,
    log: Arc<Mutex<Vec<Value>>>,
}

impl History {
    fn new(case: &Map, log: Arc<Mutex<Vec<Value>>>) -> History {
        History {
            script: match get(case, "turns") {
                Value::Object(map) => map.clone(),
                _ => Map::new(),
            },
            log,
        }
    }

    fn found(&self, table: &str, key: &str) -> Result<Value, Raised> {
        let found = match get(&self.script, table) {
            Value::Object(map) => get(map, key).clone(),
            _ => Value::Null,
        };
        if let Value::Object(map) = &found
            && map.contains_key("raise")
        {
            return Err(Raised::new(&text(get(map, "raise"))));
        }
        Ok(found)
    }
}

impl TurnHistory for History {
    fn status(&mut self, thread: &Value, turn: &Value) -> Result<Value, Raised> {
        lock(&self.log).push(Value::Array(vec![
            Value::Str("status".into()),
            thread.clone(),
            turn.clone(),
        ]));
        self.found(
            "status",
            &format!(
                "{}|{}",
                car_adv::state::py::py_str(thread),
                car_adv::state::py::py_str(turn)
            ),
        )
    }
    fn has_latest(&self) -> bool {
        self.script.contains_key("latest")
    }
    fn latest(&mut self, thread: &Value) -> Result<Value, Raised> {
        lock(&self.log).push(Value::Array(vec![
            Value::Str("latest".into()),
            thread.clone(),
        ]));
        self.found("latest", &car_adv::state::py::py_str(thread))
    }
}
