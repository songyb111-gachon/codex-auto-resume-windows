//! `fl`: fleet_view's tick, errand and pass over a scripted status, spawn and clock, on a scratch shared folder;
//! `fl.pure`: its pure parts and its file calls.

use std::sync::{Arc, Mutex};

use car_adv::capabilities::Raised;
use car_adv::engine::fleet::{self, Access, FleetView, Worker, Wrote};
use car_machine::json::{Map, Value};
use car_policy::plug::Errand;

use crate::common::{Case, f64_of, get, homed, list, lock, object, paths_of, text};
use crate::wake_ops::{StandView, run_errand, shown_tick};

fn access(found: Access) -> Value {
    class(match found {
        Access::NotFound => "FileNotFoundError",
        Access::Os => "OSError",
        Access::Other => "OverflowError",
    })
}

fn class(name: &str) -> Value {
    object(vec![("error", Value::Str(name.into()))])
}

fn pure(case: &Map) -> Value {
    let home = text(get(case, "home"));
    let paths = paths_of(&home);
    let arguments = list(&homed(get(case, "arguments"), &home));
    let at = |index: usize| arguments.get(index).cloned().unwrap_or(Value::Null);
    match text(get(case, "name")).as_str() {
        "alias_valid" => Value::Bool(fleet::alias_valid(&at(0))),
        "clean" => {
            let stem = match at(1) {
                Value::Str(text) => Some(text.as_str().unwrap_or_default().to_owned()),
                _ => None,
            };
            fleet::clean(&at(0), stem.as_deref()).unwrap_or_else(class)
        }
        "document" => fleet::document(&at(0), &at(1)).unwrap_or_else(class),
        "shown" => fleet::shown(&at(0), f64_of(&at(1)).unwrap_or(0.0)),
        "waiting_word" => {
            fleet::waiting_word(&at(0)).map_or(Value::Null, |word| Value::Str(word.into()))
        }
        "folder_problem" => fleet::folder_problem(&at(0), &fleet::guarded_homes(&paths))
            .map_or(Value::Null, |word| Value::Str(word.into())),
        "within" => Value::Bool(fleet::within(&text(&at(0)), &text(&at(1)))),
        "write" => match fleet::write(&text(&at(0)), &text(&at(1)), &at(2), &at(3)) {
            Wrote::Word(word) => Value::Str(word.into()),
            Wrote::Access(found) => access(found),
            Wrote::Refused(name) => class(name),
        },
        "read_peers" => {
            let steps = Mutex::new(0i64);
            let mut step = || *lock(&steps) += 1;
            match fleet::read_peers(&text(&at(0)), &at(1), &mut step) {
                Ok((kept, ignored, held)) => object(vec![
                    (
                        "found",
                        Value::Array(vec![
                            Value::Array(kept),
                            Value::Int((ignored as i64).into()),
                            Value::Int((held as i64).into()),
                        ]),
                    ),
                    ("steps", Value::Int((*lock(&steps)).into())),
                ]),
                Err(found) => access(found),
            }
        }
        "remove_old_name" => Value::Bool(fleet::remove_old_name(&text(&at(0)), &text(&at(1)))),
        "seen" => {
            let count = |value: &Value| car_adv::state::py::small(value).unwrap_or(0) as usize;
            match fleet::write_seen(
                &paths,
                f64_of(&at(0)).unwrap_or(0.0),
                &list(&at(1)),
                count(&at(2)),
                count(&at(3)),
            ) {
                Ok(()) => fleet::read_seen(&paths).unwrap_or(Value::Null),
                Err(name) => class(name),
            }
        }
        "read_seen" => fleet::read_seen(&paths).unwrap_or(Value::Null),
        other => object(vec![("unknown", Value::Str(other.into()))]),
    }
}

pub fn answer(op: &str, case: &Map) -> Option<Result<Value, String>> {
    match op {
        "fl" => Some(Ok(fl(case))),
        "fl.pure" => Some(Ok(pure(case))),
        _ => None,
    }
}

fn next_of(held: &Mutex<Vec<Value>>) -> Value {
    let mut held = lock(held);
    if held.len() > 1 {
        held.remove(0)
    } else {
        held[0].clone()
    }
}

fn fl(case: &Map) -> Value {
    let made = Case::new(case);
    let ticks = Mutex::new(match get(case, "clock") {
        Value::Array(items) if !items.is_empty() => items.clone(),
        _ => vec![Value::Float(0.0)],
    });
    let alive = Arc::new(Mutex::new(match get(case, "alive") {
        Value::Array(items) if !items.is_empty() => items.clone(),
        _ => vec![Value::Bool(false)],
    }));
    let spawn_log = made.log.clone();
    let spawn_raise = matches!(get(case, "spawn_raise"), Value::Bool(true));
    let run_pass = !matches!(get(case, "run_pass"), Value::Bool(false));
    let status_log = made.log.clone();
    let status = get(case, "status").clone();
    let code = FleetView::new(
        made.paths.clone(),
        Box::new(move |now| {
            lock(&status_log).push(Value::Array(vec![
                Value::Str("status".into()),
                Value::Float(now),
            ]));
            let Value::Object(map) = &status else {
                return Err(Raised::new("RuntimeError"));
            };
            let mut found = map.clone();
            if found.get("written_at") == Some(&Value::Str("now".into())) {
                found.insert("written_at".into(), Value::Float(now));
            }
            Ok(Value::Object(found))
        }),
        Box::new(move |run| {
            lock(&spawn_log).push(Value::Array(vec![Value::Str("spawn".into())]));
            if spawn_raise {
                return Err(Raised::new("RuntimeError"));
            }
            if run_pass {
                run();
            }
            let alive = alive.clone();
            let log = spawn_log.clone();
            Ok(Worker(Box::new(move || {
                lock(&log).push(Value::Array(vec![Value::Str("alive".into())]));
                car_machine::pyval::truthy(&next_of(&alive))
            })))
        }),
        Box::new(move || f64_of(&next_of(&ticks)).unwrap_or(0.0)),
        Box::new(fleet::guarded_homes),
    );
    if !matches!(get(case, "bind"), Value::Bool(false)) {
        code.bind_to(made.bound());
    }
    let view = StandView::new(&Value::Object(Map::new()), made.log.clone());
    let mut answers = Vec::new();
    let mut errand: Option<Box<dyn Errand>> = None;
    for step in list(get(case, "steps")) {
        let step = list(&step);
        if made.common(&step) {
            answers.push(Value::Null);
            continue;
        }
        let answer = match text(step.first().unwrap_or(&Value::Null)).as_str() {
            "tick" => shown_tick(code.ticked(), &mut errand),
            "run" => match &errand {
                Some(errand) => run_errand(errand.as_ref(), &view, &made.log),
                None => Value::Str("none".into()),
            },
            "seen" => fleet::read_seen(&made.paths).unwrap_or(Value::Null),
            other => object(vec![("unknown", Value::Str(other.into()))]),
        };
        answers.push(answer);
    }
    made.close();
    object(vec![
        ("answers", Value::Array(answers)),
        ("log", made.log()),
    ])
}
