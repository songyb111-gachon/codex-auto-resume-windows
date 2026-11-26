//! `wk`: wake_for_reset's P8 errand and its watch over a scripted timer, view and thread start.

use std::sync::Arc;

use car_adv::capabilities::{Code, Raised, Said};
use car_adv::engine::wake::{Timer, WakeForReset};
use car_machine::json::{Map, Value};
use car_policy::plug::{Errand, ReadFailed, View};

use crate::common::{Case, Log, Script, error, f64_of, get, list, object, said, text};

/// The reference's scripted `Timer`: `due` follows what it was told.
pub struct StandTimer {
    script: Arc<Script>,
    due: Option<f64>,
}

impl Timer for StandTimer {
    fn due(&self) -> Option<f64> {
        self.due
    }
    fn set(&mut self, at: f64) -> Result<bool, Raised> {
        let done = car_machine::pyval::truthy(&self.script.answer(
            "set",
            Value::Bool(true),
            vec![Value::Float(at)],
        )?);
        if done {
            self.due = Some(at);
        }
        Ok(done)
    }
    fn cancel(&mut self) -> Result<bool, Raised> {
        let had = Value::Bool(self.due.is_some());
        let found = self.script.answer("cancel", had, vec![]);
        self.due = None;
        Ok(car_machine::pyval::truthy(&found?))
    }
    fn allowed(&mut self) -> Result<bool, Raised> {
        Ok(matches!(
            self.script.answer("allowed", Value::Bool(true), vec![])?,
            Value::Bool(true)
        ))
    }
}

/// The class of a stand-in's raise, as a view's read names it.
pub fn static_class(class: &str) -> &'static str {
    match class {
        "ValueError" => "ValueError",
        "TypeError" => "TypeError",
        "KeyError" => "KeyError",
        "OSError" => "OSError",
        "LookupError" => "LookupError",
        _ => "RuntimeError",
    }
}

/// Core's view as a tick is handed it: `settings()` and `records_in(states)`, scripted and logged.
pub struct StandView(pub Script);

impl StandView {
    pub fn new(script: &Value, log: Log) -> StandView {
        StandView(Script::new(script, log))
    }
}

impl View for StandView {
    fn settings(&self) -> Result<Value, ReadFailed> {
        let mut default = Map::new();
        default.insert("enabled".into(), Value::Bool(true));
        self.0
            .answer("settings", Value::Object(default), vec![])
            .map_err(|raised| ReadFailed(static_class(&raised.class)))
    }
    fn records_in(&self, _states: &[&str]) -> Result<Vec<Value>, ReadFailed> {
        match self.0.answer("records_in", Value::Array(Vec::new()), vec![]) {
            Ok(Value::Array(items)) => Ok(items),
            Ok(_) => Ok(Vec::new()),
            Err(raised) => Err(ReadFailed(static_class(&raised.class))),
        }
    }
}

/// Runs an errand with a guard that is always permitted, logging each guard taken.
pub fn run_errand(errand: &dyn Errand, view: &dyn View, log: &Log) -> Value {
    let guard_log = log.clone();
    let mut guards = move |body: &mut dyn FnMut(bool) -> Value| {
        crate::common::lock(&guard_log).push(Value::Array(vec![
            Value::Str("guard".into()),
            Value::Bool(true),
        ]));
        Ok(body(true))
    };
    match errand.run(view, &mut guards) {
        Ok(value) => value,
        Err(_) => error(&Raised::new("raised")),
    }
}

pub fn answer(op: &str, case: &Map) -> Option<Result<Value, String>> {
    match op {
        "wk" => Some(Ok(wk(case))),
        _ => None,
    }
}

/// What a tick answered, shown as the reference's `said` shows it; the errand kept for `run`.
pub fn shown_tick(
    found: Result<Said, Raised>,
    errand: &mut Option<Box<dyn Errand>>,
) -> Value {
    match found {
        Ok(Said::Errand(made)) => {
            *errand = Some(made);
            object(vec![("object", Value::Str("errand".into()))])
        }
        other => {
            *errand = None;
            said(other)
        }
    }
}

fn wk(case: &Map) -> Value {
    let made = Case::new(case);
    let timer_script = Arc::new(Script::new(get(case, "timer"), made.log.clone()));
    let starts = {
        let mut script = Map::new();
        script.insert(
            "start".into(),
            match get(case, "start") {
                Value::Null => Value::Array(vec![Value::Null]),
                other => other.clone(),
            },
        );
        Arc::new(Script::new(&Value::Object(script), made.log.clone()))
    };
    let mut code = WakeForReset::new(
        made.paths.clone(),
        Some(Box::new(StandTimer {
            script: timer_script,
            due: None,
        })),
        Some(Box::new(move |_target| {
            starts.answer("start", Value::Null, vec![]).map(|_| ())
        })),
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
        let at = |index: usize| step.get(index).cloned().unwrap_or(Value::Null);
        let number = |found: Option<f64>| found.map_or(Value::Null, Value::Float);
        let answer = match text(&at(0)).as_str() {
            "tick" => shown_tick(code.tick(&view), &mut errand),
            "run" => match &errand {
                Some(errand) => run_errand(errand.as_ref(), &view, &made.log),
                None => Value::Str("none".into()),
            },
            "look" => match code.look() {
                Ok(going) => Value::Bool(going),
                Err(raised) => error(&raised),
            },
            "earliest" => match code.earliest(&view) {
                Ok(found) => number(found),
                Err(raised) => error(&raised),
            },
            "apply" => match code.apply(f64_of(&at(1))) {
                Ok(()) => Value::Null,
                Err(raised) => error(&raised),
            },
            "lead" => match code.lead() {
                Ok(lead) if lead.fract() == 0.0 => Value::Int((lead as i64).into()),
                Ok(lead) => Value::Float(lead),
                Err(raised) => error(&raised),
            },
            "due" => number(code.due()),
            other => object(vec![("unknown", Value::Str(other.into()))]),
        };
        answers.push(answer);
    }
    made.close();
    object(vec![("answers", Value::Array(answers)), ("log", made.log())])
}
