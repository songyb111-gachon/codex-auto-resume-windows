//! The fakes of an `advturns` trace (seat S7.2e1), the Rust half of `tests/rustdiff/advturnsworld.py` (whose
//! docstring says the seams and the steps): how each capability of the scenario is made (the ported code, with the
//! scenario's fakes where it takes them) and the steps that move a fake. Every fake notes each call it is asked in
//! `asked`, in order, as `[fake, call, ...]`.

use std::collections::HashMap;
use std::sync::atomic::Ordering;
use std::sync::{Arc, Mutex, PoisonError};

use car_adv::capabilities::Code;
use car_adv::codex::headless::{AppLook, Ended, Follower, HeadlessRun, Opener, Shown};
use car_adv::codex::session::{Channel, SessionError};
use car_adv::codex::turns::Turn;
use car_adv::engine::headless::{Follows, RunWorld, TurnsReader, Unreadable};
use car_adv::registry::CapabilityDef;
use car_adv::vocabulary::RunEnd;
use car_config::Paths;
use car_machine::json::Value;

/// Every call asked of a fake (and the hooks), in order.
pub type Asked = Arc<Mutex<Vec<Value>>>;

fn text(word: &str) -> Value {
    Value::Str(word.into())
}

fn get<'a>(value: &'a Value, name: &str) -> &'a Value {
    static NULL: Value = Value::Null;
    match value {
        Value::Object(map) => map.get(name).unwrap_or(&NULL),
        _ => &NULL,
    }
}

fn is_raise(value: &Value) -> bool {
    matches!(value, Value::Str(word) if word.as_str() == Some("raise"))
}

fn number(value: &Value) -> f64 {
    match value {
        Value::Int(int) => int.as_i64().unwrap_or(0) as f64,
        Value::Float(number) => *number,
        _ => 0.0,
    }
}

struct Inner {
    seams: Value,
    asked: Asked,
    clock: Arc<Mutex<f64>>,
    calls: Mutex<HashMap<String, usize>>,
    shown: Mutex<Option<Shown>>,
    ends: Mutex<Vec<Ended>>,
    real: Arc<Follower>,
}

impl Inner {
    fn note(&self, entry: Vec<Value>) {
        self.asked
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
            .push(Value::Array(entry));
    }

    fn seam(&self, name: &str) -> &Value {
        get(&self.seams, name)
    }
}

/// The scenario's fakes, by capability.
#[derive(Clone)]
pub struct World(Arc<Inner>);

struct FakeFollower(Arc<Inner>);

impl Follows for FakeFollower {
    fn live(&self) -> Option<Shown> {
        self.0
            .shown
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
            .clone()
    }
    fn stop(&self, key: Option<&Value>, reason: RunEnd) -> bool {
        self.0.note(vec![
            text("follower"),
            text("stop"),
            key.cloned().unwrap_or(Value::Null),
            text(reason.as_str()),
        ]);
        self.live()
            .is_some_and(|shown| key.is_none_or(|key| car_machine::pyval::eq(&shown.key, key)))
    }
    fn drain(&self, capability: &str) -> Vec<Ended> {
        let mut ends = self.0.ends.lock().unwrap_or_else(PoisonError::into_inner);
        let (taken, kept): (Vec<Ended>, Vec<Ended>) =
            ends.drain(..).partition(|end| end.capability == capability);
        *ends = kept;
        taken
    }
    fn follower(&self) -> Arc<Follower> {
        self.0.real.clone()
    }
}

struct FakeTurns(Arc<Inner>);

impl TurnsReader for FakeTurns {
    fn latest(&self, thread_id: &Value) -> Result<Option<Turn>, Unreadable> {
        self.0
            .note(vec![text("turns"), text("latest"), thread_id.clone()]);
        let found = match thread_id {
            Value::Str(thread) => get(self.0.seam("turns"), thread.as_str().unwrap_or_default()),
            _ => &Value::Null,
        };
        if is_raise(found) {
            return Err(Unreadable);
        }
        if matches!(found, Value::Null) {
            return Ok(None);
        }
        let kinds = match get(found, "kinds") {
            Value::Array(pairs) => pairs
                .iter()
                .filter_map(|pair| match pair {
                    Value::Array(pair) => Some((
                        pair.first()?.as_text()?.to_owned(),
                        pair.get(1).map_or(0, |count| number(count) as i64),
                    )),
                    _ => None,
                })
                .collect(),
            _ => Vec::new(),
        };
        Ok(Some(Turn {
            turn_id: get(found, "turn_id")
                .as_text()
                .unwrap_or_default()
                .to_owned(),
            status: get(found, "status")
                .as_text()
                .unwrap_or_default()
                .to_owned(),
            errored: car_machine::pyval::truthy(get(found, "errored")),
            completed_at: match get(found, "completed_at") {
                Value::Null => None,
                other => Some(number(other) as i64),
            },
            final_agent: car_machine::pyval::truthy(get(found, "final_agent")),
            ordinal: number(get(found, "ordinal")) as i128,
            kinds,
            started_at: None,
        }))
    }

    fn turn_code(&self, thread_id: &Value, turn_id: &Value) -> Result<Value, Unreadable> {
        self.0.note(vec![
            text("turns"),
            text("turn_code"),
            thread_id.clone(),
            turn_id.clone(),
        ]);
        let name = format!("{} {}", python_str(thread_id), python_str(turn_id));
        let found = get(self.0.seam("codes"), &name);
        if is_raise(found) {
            return Err(Unreadable);
        }
        Ok(found.clone())
    }
}

/// `"%s" % value` for the values a scenario hands (a text, None, a number).
fn python_str(value: &Value) -> String {
    match value {
        Value::Str(text) => text.as_str().unwrap_or_default().to_owned(),
        Value::Null => "None".to_owned(),
        Value::Int(int) => int.to_string(),
        other => format!("{other:?}"),
    }
}

struct FakeSession(Arc<Inner>);

impl Channel for FakeSession {
    fn enter(&mut self) -> Result<(), SessionError> {
        self.0.note(vec![text("session"), text("enter")]);
        if is_raise(get(self.0.seam("session"), "enter")) {
            return Err(SessionError::Raised("RuntimeError"));
        }
        Ok(())
    }
    fn submit(&mut self, _method: &str, _params: Option<Value>) -> Result<i64, SessionError> {
        Err(SessionError::Raised("RuntimeError"))
    }
    fn receive(&mut self, _: &str, _: i64, _: Option<&Value>) -> Result<Value, SessionError> {
        Err(SessionError::Raised("RuntimeError"))
    }
    fn call(&mut self, method: &str, params: Option<Value>) -> Result<Value, SessionError> {
        self.0.note(vec![
            text("session"),
            text(method),
            params.unwrap_or(Value::Null),
        ]);
        let answers = match get(get(self.0.seam("session"), "answers"), method) {
            Value::Array(answers) if !answers.is_empty() => answers.clone(),
            _ => vec![Value::Null],
        };
        let index = {
            let mut calls = self.0.calls.lock().unwrap_or_else(PoisonError::into_inner);
            let index = calls.entry(method.to_owned()).or_insert(0);
            let found = *index;
            *index += 1;
            found
        };
        let answer = answers[index.min(answers.len() - 1)].clone();
        if is_raise(&answer) {
            return Err(SessionError::Raised("RuntimeError"));
        }
        Ok(answer)
    }
    fn drain_events(&mut self) -> Vec<Value> {
        Vec::new()
    }
    fn exit(&mut self) {
        self.0.note(vec![text("session"), text("exit")]);
    }
}

impl World {
    pub fn new(seams: Value, asked: Asked, clock: Arc<Mutex<f64>>) -> World {
        World(Arc::new(Inner {
            seams,
            asked,
            clock,
            calls: Mutex::new(HashMap::new()),
            shown: Mutex::new(None),
            ends: Mutex::new(Vec::new()),
            real: Follower::new(Arc::new(|| 0.0), 0.5),
        }))
    }

    fn opener(&self) -> Opener {
        let inner = self.0.clone();
        Box::new(move |capability: &str| -> Result<Box<dyn Channel>, ()> {
            inner.note(vec![text("session"), text("open"), text(capability)]);
            if is_raise(get(inner.seam("session"), "open")) {
                return Err(());
            }
            Ok(Box::new(FakeSession(inner.clone())))
        })
    }

    fn run_world(&self) -> RunWorld {
        let app = self.0.clone();
        let unheld = self.0.clone();
        let noted = self.0.clone();
        RunWorld {
            open: Arc::new(Mutex::new(self.opener())),
            follows: Arc::new(FakeFollower(self.0.clone())),
            app_running: Arc::new(move || -> AppLook {
                let app = app.clone();
                Box::new(move || {
                    app.note(vec![text("app"), text("running")]);
                    Ok(Value::Bool(false))
                })
            }),
            turns: Arc::new(FakeTurns(self.0.clone())),
            unheld_now: Arc::new(move |thread: &Value| {
                unheld.note(vec![text("unheld"), thread.clone()]);
                let found = unheld.seam("unheld");
                if is_raise(found) {
                    return Err(());
                }
                Ok(if matches!(found, Value::Null) {
                    Value::Bool(true)
                } else {
                    found.clone()
                })
            }),
            on_route: Some(Arc::new(move |route: &HeadlessRun| {
                noted.note(vec![
                    text("route"),
                    text(&route.capability),
                    route.key.clone(),
                    Value::Float(route.seconds),
                    text(route.mode),
                ]);
            })),
        }
    }

    /// `definition.make(paths)`: the edition's own code, with the scenario's fakes where it takes them.
    pub fn make(&self, definition: &CapabilityDef, paths: &Paths) -> Option<Box<dyn Code>> {
        use car_adv::engine;
        match definition.id.as_str() {
            "headless_run" => engine::headless::make_with(paths, self.run_world()),
            "compact_continue" => engine::compact::make_with(paths, self.run_world()),
            "model_fallback" => engine::fallback::make_with(paths, self.run_world()),
            "codex_retry_settings" => {
                let clock = self.0.clock.clone();
                engine::retries::make_with(
                    paths,
                    Arc::new(Mutex::new(self.opener())),
                    Arc::new(move || *clock.lock().unwrap_or_else(PoisonError::into_inner)),
                )
            }
            _ => car_adv::capabilities::make(definition, paths),
        }
    }

    /// A step that moves a fake: None for an op it does not know.
    pub fn step(
        &self,
        op: &str,
        args: &[Value],
        state: &car_adv::state::session::AdvancedState,
    ) -> Option<Result<Value, String>> {
        let arg = |index: usize| args.get(index).cloned().unwrap_or(Value::Null);
        match op {
            "flag" => {
                if arg(0).as_text() == Some("empty_refused") {
                    car_adv::codex::headless::EMPTY_REFUSED
                        .store(car_machine::pyval::truthy(&arg(1)), Ordering::SeqCst);
                }
                Some(Ok(Value::Null))
            }
            "live" => {
                let shown = match arg(0) {
                    Value::Null => None,
                    found => Some(Shown {
                        key: get(&found, "key").clone(),
                        capability: get(&found, "capability")
                            .as_text()
                            .unwrap_or_default()
                            .to_owned(),
                        thread_id: get(&found, "thread_id").clone(),
                        started_at: number(get(&found, "started_at")),
                        ends_by: number(get(&found, "ends_by")),
                    }),
                };
                *self.0.shown.lock().unwrap_or_else(PoisonError::into_inner) = shown;
                Some(Ok(Value::Null))
            }
            "told" => {
                let end = RunEnd::parse(arg(2).as_text().unwrap_or_default())?;
                self.0
                    .ends
                    .lock()
                    .unwrap_or_else(PoisonError::into_inner)
                    .push(Ended {
                        key: arg(0),
                        capability: arg(1).as_text().unwrap_or_default().to_owned(),
                        end,
                        model_restored: match arg(3) {
                            Value::Bool(said) => Some(said),
                            _ => None,
                        },
                    });
                Some(Ok(Value::Null))
            }
            "stop_request" => Some(
                state
                    .run_stop(&arg(0), &Value::Null)
                    .map(Value::Bool)
                    .map_err(|_| "StateError".to_owned()),
            ),
            "owe" => Some(
                state
                    .run_owed(&arg(0), &arg(1), &arg(2), &arg(3), &arg(4), &arg(5))
                    .map(|()| Value::Null)
                    .map_err(|_| "StateError".to_owned()),
            ),
            "retry_settings" => {
                let now = *self.0.clock.lock().unwrap_or_else(PoisonError::into_inner);
                Some(Ok(Value::Array(
                    car_adv::engine::retries::in_force(Some(now))
                        .into_iter()
                        .map(|(key, value)| Value::Array(vec![text(&key), text(&value)]))
                        .collect(),
                )))
            }
            _ => None,
        }
    }
}

trait AsText {
    fn as_text(&self) -> Option<&str>;
}

impl AsText for Value {
    fn as_text(&self) -> Option<&str> {
        match self {
            Value::Str(text) => text.as_str(),
            _ => None,
        }
    }
}
