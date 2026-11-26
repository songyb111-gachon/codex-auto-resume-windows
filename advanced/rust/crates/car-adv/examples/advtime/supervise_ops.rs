//! `sv`: crash_restart's P13 over a scripted stop flag and notice; `sv.view`: its line for the Advanced page.

use std::path::PathBuf;
use std::sync::{Arc, Mutex};

use car_adv::capabilities::{Code, Raised};
use car_adv::engine::supervise::{self, CrashRestart, Flag};
use car_machine::json::{Map, Value};

use crate::common::{Case, Script, get, list, object, said, text};

struct Stand(Arc<Script>);

impl Flag for Stand {
    fn hold(&mut self) -> Result<(), Raised> {
        self.0.answer("hold", Value::Bool(true), vec![]).map(|_| ())
    }
    fn signalled(&mut self) -> Result<bool, Raised> {
        self.0
            .answer("signalled", Value::Bool(false), vec![])
            .map(|value| car_machine::pyval::truthy(&value))
    }
    fn wait(&mut self, seconds: f64) -> Result<bool, Raised> {
        self.0
            .answer("wait", Value::Bool(false), vec![Value::Int((seconds as i64).into())])
            .map(|value| car_machine::pyval::truthy(&value))
    }
}

pub fn answer(op: &str, case: &Map) -> Option<Result<Value, String>> {
    match op {
        "sv" => Some(Ok(sv(case))),
        "sv.view" => Some(Ok(view(case))),
        _ => None,
    }
}

fn sv(case: &Map) -> Value {
    let made = Case::new(case);
    let flag = Arc::new(Script::new(get(case, "flag"), made.log.clone()));
    let notices = {
        let mut script = Map::new();
        script.insert(
            "notify".into(),
            match get(case, "notify") {
                Value::Null => Value::Array(vec![Value::Bool(false)]),
                other => other.clone(),
            },
        );
        Arc::new(Script::new(&Value::Object(script), made.log.clone()))
    };
    let told = notices.clone();
    let mut code = CrashRestart::new(
        made.paths.clone(),
        Some(Box::new(Stand(flag))),
        Some(Box::new(move |_paths| {
            told.answer("notify", Value::Bool(false), vec![])
                .map(|value| car_machine::pyval::truthy(&value))
        })),
    );
    if !matches!(get(case, "bind"), Value::Bool(false)) {
        code.bind_to(made.bound());
    }
    let mut answers = Vec::new();
    for step in list(get(case, "steps")) {
        let step = list(&step);
        if made.common(&step) {
            answers.push(Value::Null);
            continue;
        }
        answers.push(said(code.supervise(step.get(1).unwrap_or(&Value::Null))));
    }
    made.close();
    object(vec![("answers", Value::Array(answers)), ("log", made.log())])
}

fn view(case: &Map) -> Value {
    let home = text(get(case, "home"));
    let paths = crate::common::paths_of(&home);
    let armed = text(get(case, "state")) == "armed";
    let running: Vec<i64> = list(get(case, "running"))
        .iter()
        .filter_map(|value| match value {
            Value::Int(number) => number.as_i64(),
            _ => None,
        })
        .collect();
    let asked = Mutex::new(Vec::new());
    let there = |pid: i64| {
        crate::common::lock(&asked).push(Value::Int(pid.into()));
        running.contains(&pid)
    };
    let found = supervise::view(armed, &PathBuf::from(&paths.logs_dir), &there);
    object(vec![
        ("view", found),
        ("asked", Value::Array(crate::common::lock(&asked).clone())),
    ])
}
