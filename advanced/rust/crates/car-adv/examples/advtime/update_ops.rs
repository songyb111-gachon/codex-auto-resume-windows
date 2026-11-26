//! `uc`: idle_update_check's tick, errand and check over a scripted run, policy, thread start, installed version
//! and log; `uc.pure`: `offer`, `said`, `english`, `encode`, `decode`. No PowerShell is ever started.

use std::sync::Arc;

use car_adv::capabilities::{Code, Raised};
use car_adv::engine::updatecheck::{self, Answered, IdleUpdateCheck};
use car_machine::json::{Map, Value};
use car_policy::plug::Errand;

use crate::common::{Case, Script, get, list, lock, object, text};
use crate::wake_ops::{StandView, run_errand, shown_tick};

fn answered_of(value: &Value) -> Answered {
    match value {
        Value::Array(items) if items.len() == 2 => {
            let printed = match &items[1] {
                Value::Str(text) => text.as_str().unwrap_or_default().to_owned(),
                _ => String::new(),
            };
            Some((items[0].clone(), printed))
        }
        _ => None,
    }
}

fn offered(found: Option<(String, bool)>) -> Value {
    found.map_or(Value::Null, |(version, prerelease)| {
        Value::Array(vec![Value::Str(version.as_str().into()), Value::Bool(prerelease)])
    })
}

fn pure(name: &str, arguments: &[Value]) -> Result<Value, String> {
    let at = |index: usize| arguments.get(index).cloned().unwrap_or(Value::Null);
    Ok(match name {
        "offer" => offered(updatecheck::offer(&at(0), &text(&at(1)))),
        "said" => {
            let why = text(&at(1));
            let why = if matches!(at(1), Value::Null) { None } else { Some(why.as_str()) };
            Value::Str(updatecheck::said(&answered_of(&at(0)), why).as_str().into())
        }
        "english" => Value::Str(updatecheck::english(&text(&at(0))).as_str().into()),
        "encode" => updatecheck::encode(&at(0)).map_or(Value::Null, |n| Value::Int(n.into())),
        "decode" => offered(updatecheck::decode(&at(0))),
        other => return Err(format!("unknown function {other}")),
    })
}

pub fn answer(op: &str, case: &Map) -> Option<Result<Value, String>> {
    match op {
        "uc" => Some(Ok(uc(case))),
        "uc.pure" => Some(pure(&text(get(case, "name")), &list(get(case, "arguments")))),
        _ => None,
    }
}

fn uc(case: &Map) -> Value {
    let made = Case::new(case);
    let script = Arc::new(Script::new(get(case, "script"), made.log.clone()));
    let home = made.paths.home.clone();
    let runs = script.clone();
    let run_log = made.log.clone();
    let policy = script.clone();
    let starts = script.clone();
    let start_runs = !matches!(get(case, "start_runs"), Value::Bool(false));
    let installs = script.clone();
    let line_log = made.log.clone();
    let mut code = IdleUpdateCheck::new(
        made.paths.clone(),
        Some(Box::new(move |place: &std::path::Path, given: &str| {
            let name = place.file_name().map(|n| n.to_string_lossy().into_owned()).unwrap_or_default();
            lock(&run_log).push(Value::Array(vec![
                Value::Str("run".into()),
                Value::Str(name.as_str().into()),
                Value::Bool(given == home),
            ]));
            Ok(answered_of(&runs.answer("answer", Value::Null, vec![])?))
        })),
        Box::new(move || policy.answer("managed", Value::Bool(false), vec![])),
        Box::new(move |target| {
            starts.answer("start", Value::Null, vec![])?;
            if start_runs {
                target();
            }
            Ok(())
        }),
        Box::new(move || installs.answer("installed", Value::Null, vec![])),
        Box::new(move |line: &str| {
            lock(&line_log).push(Value::Array(vec![Value::Str("log".into()), Value::Str(line.into())]));
            Ok::<(), Raised>(())
        }),
    );
    if !matches!(get(case, "bind"), Value::Bool(false)) {
        code.bind_to(made.bound());
    }
    let view = StandView::new(get(case, "view"), made.log.clone());
    let mut answers = Vec::new();
    let mut errand: Option<Box<dyn Errand>> = None;
    for step in list(get(case, "steps")) {
        let step = list(&step);
        if made.common(&step) {
            answers.push(Value::Null);
            continue;
        }
        let answer = match text(step.first().unwrap_or(&Value::Null)).as_str() {
            "tick" => shown_tick(code.tick(&view), &mut errand),
            "run" => match &errand {
                Some(errand) => run_errand(errand.as_ref(), &view, &made.log),
                None => Value::Str("none".into()),
            },
            "offered" => offered(code.offered()),
            "script" => {
                let folder = std::path::Path::new(&made.paths.home).join("app").join("scripts");
                let _ = std::fs::create_dir_all(&folder);
                let _ = std::fs::write(folder.join("bootstrap.ps1"), "# stand-in");
                Value::Null
            }
            other => object(vec![("unknown", Value::Str(other.into()))]),
        };
        answers.push(answer);
    }
    made.close();
    object(vec![("answers", Value::Array(answers)), ("log", made.log())])
}
