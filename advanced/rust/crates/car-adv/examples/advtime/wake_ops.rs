//! `wk`: wake_for_reset's P8 errand and its watch over a scripted timer, view and thread start; `ua`, `ua.pace`,
//! `ua.route`: usage_analytics' pass over a scratch home's rollouts, with a scripted clock and project source.

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
        // The reference's stand-in raises before it forgets its time.
        let found = self.script.answer("cancel", had, vec![])?;
        self.due = None;
        Ok(car_machine::pyval::truthy(&found))
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
        match self
            .0
            .answer("records_in", Value::Array(Vec::new()), vec![])
        {
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
        "ua" => Some(Ok(ua(case))),
        "ua.pace" => Some(
            car_adv::engine::analytics::pace(
                &list(get(case, "samples")),
                get(case, "row"),
                f64_of(get(case, "now")).unwrap_or(0.0),
            )
            .map_err(str::to_owned),
        ),
        "ua.route" => Some(Ok(Value::Str(
            car_adv::engine::analytics::route(get(case, "verdict")).into(),
        ))),
        _ => None,
    }
}

/// What a tick answered, shown as the reference's `said` shows it; the errand kept for `run`.
pub fn shown_tick(found: Result<Said, Raised>, errand: &mut Option<Box<dyn Errand>>) -> Value {
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
    object(vec![
        ("answers", Value::Array(answers)),
        ("log", made.log()),
    ])
}

struct StandSource {
    keys: Map,
    log: Log,
}

impl car_adv::engine::analytics::ProjectSource for StandSource {
    fn project_key(&mut self, thread: &str) -> Result<Value, Raised> {
        crate::common::lock(&self.log).push(Value::Array(vec![
            Value::Str("project_key".into()),
            Value::Str(thread.into()),
        ]));
        let found = get(&self.keys, thread).clone();
        if let Value::Object(map) = &found
            && map.contains_key("raise")
        {
            return Err(Raised::new("RuntimeError"));
        }
        Ok(found)
    }
}

fn ua(case: &Map) -> Value {
    use car_adv::engine::analytics::UsageAnalytics;
    let made = Case::new(case);
    let home = std::path::PathBuf::from(text(get(case, "home")));
    let homes: Vec<String> = list(get(case, "homes"))
        .iter()
        .map(|each| car_platform::paths::pathlib_text(&home.join(text(each)).to_string_lossy()))
        .collect();
    let ticks = std::sync::Mutex::new(match get(case, "clock") {
        Value::Array(items) if !items.is_empty() => items.clone(),
        _ => vec![Value::Float(0.0)],
    });
    let clock_log = made.log.clone();
    let keys = match get(case, "keys") {
        Value::Object(map) => map.clone(),
        _ => Map::new(),
    };
    let source_log = made.log.clone();
    let source_raise = matches!(get(case, "source_raise"), Value::Bool(true));
    let code = UsageAnalytics::new(
        Box::new(move || Ok(homes.clone())),
        Box::new(move |place: &str| {
            let name = std::path::Path::new(place)
                .file_name()
                .map(|name| name.to_string_lossy().into_owned())
                .unwrap_or_default();
            crate::common::lock(&source_log).push(Value::Array(vec![
                Value::Str("source".into()),
                Value::Str(name.as_str().into()),
            ]));
            if source_raise {
                return Err(Raised::new("RuntimeError"));
            }
            Ok(Box::new(StandSource {
                keys: keys.clone(),
                log: source_log.clone(),
            })
                as Box<dyn car_adv::engine::analytics::ProjectSource>)
        }),
        Box::new(move || {
            crate::common::lock(&clock_log).push(Value::Array(vec![Value::Str("clock".into())]));
            let mut held = crate::common::lock(&ticks);
            let value = if held.len() > 1 {
                held.remove(0)
            } else {
                held[0].clone()
            };
            f64_of(&value).unwrap_or(0.0)
        }),
        Box::new(car_platform::localclock::Crt),
        std::sync::Arc::new(car_codex::system::PolicyOs),
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
