//! The fakes of an `advturns` trace (seat S7.2e1), the Rust half of `tests/rustdiff/advturnsworld.py` (whose
//! docstring says the seams and the steps): how each capability of the scenario is made (the ported code, with the
//! scenario's fakes where it takes them) and the steps that move a fake. Every fake notes each call it is asked in
//! `asked`, in order, as `[fake, call, ...]`.

use std::collections::HashMap;
use std::sync::atomic::Ordering;
use std::sync::{Arc, Mutex, PoisonError};

use car_adv::capabilities::Code;
use car_adv::codex::headless::{AppLook, Ended, Follower, HeadlessRun, Opener, Shown};
use car_adv::codex::lineage::Child;
use car_adv::codex::session::{Channel, SessionError};
use car_adv::codex::turns::Turn;
use car_adv::engine::emptyreply::{LookWorld, Looks, Unreadable as LookUnreadable, Words};
use car_adv::engine::goal::{GoalSeen, GoalWorld, m2b_passed};
use car_adv::engine::headless::{Follows, RunWorld, TurnsReader, Unreadable};
use car_adv::registry::CapabilityDef;
use car_adv::statement::Catalogs;
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
    seams: Mutex<Value>,
    asked: Asked,
    clock: Arc<Mutex<f64>>,
    calls: Mutex<HashMap<String, usize>>,
    shown: Mutex<Option<Shown>>,
    ends: Mutex<Vec<Ended>>,
    real: Arc<Follower>,
    catalogs: Arc<Catalogs>,
    measured: Value,
}

impl Inner {
    fn note(&self, entry: Vec<Value>) {
        self.asked
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
            .push(Value::Array(entry));
    }

    fn seam(&self, name: &str) -> Value {
        get(
            &self.seams.lock().unwrap_or_else(PoisonError::into_inner),
            name,
        )
        .clone()
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
            Value::Str(thread) => {
                get(&self.0.seam("turns"), thread.as_str().unwrap_or_default()).clone()
            }
            _ => Value::Null,
        };
        if is_raise(&found) {
            return Err(Unreadable);
        }
        if matches!(found, Value::Null) {
            return Ok(None);
        }
        Ok(Some(turn_of(&found)))
    }

    fn turn_code(&self, thread_id: &Value, turn_id: &Value) -> Result<Value, Unreadable> {
        self.0.note(vec![
            text("turns"),
            text("turn_code"),
            thread_id.clone(),
            turn_id.clone(),
        ]);
        let name = format!("{} {}", python_str(thread_id), python_str(turn_id));
        let found = get(&self.0.seam("codes"), &name).clone();
        if is_raise(&found) {
            return Err(Unreadable);
        }
        Ok(found.clone())
    }
}

/// A turn of the scenario's (`turns`), as the reference's fake makes it.
fn turn_of(found: &Value) -> Turn {
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
    Turn {
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

/// The continuation family's looks of the scenario's (`recent`, `between`, `plans`, `goals`, `own`, `children`).
struct FakeLooks(Arc<Inner>);

fn raise_or<T>(found: &Value, then: impl FnOnce(&Value) -> T) -> Result<T, LookUnreadable> {
    if is_raise(found) {
        Err(LookUnreadable)
    } else {
        Ok(then(found))
    }
}

fn of_thread(map: &Value, thread: &Value) -> Option<Value> {
    match (map, thread) {
        (Value::Object(map), Value::Str(thread)) => {
            map.get(thread.as_str().unwrap_or_default()).cloned()
        }
        _ => None,
    }
}

impl Looks for FakeLooks {
    fn recent(&self, since: f64) -> Result<Vec<Value>, LookUnreadable> {
        self.0
            .note(vec![text("turns"), text("recent"), Value::Float(since)]);
        raise_or(&self.0.seam("recent"), |found| match found {
            Value::Array(items) => items.clone(),
            _ => Vec::new(),
        })
    }
    fn latest(&self, thread_id: &Value) -> Result<Option<Turn>, LookUnreadable> {
        FakeTurns(self.0.clone())
            .latest(thread_id)
            .map_err(|_| LookUnreadable)
    }
    fn between(
        &self,
        thread_id: &Value,
        after: &Value,
        before: &Value,
    ) -> Result<i64, LookUnreadable> {
        self.0.note(vec![
            text("turns"),
            text("between"),
            thread_id.clone(),
            after.clone(),
            before.clone(),
        ]);
        let found = of_thread(&self.0.seam("between"), thread_id).unwrap_or(Value::from(0));
        raise_or(&found, |found| number(found) as i64)
    }
    fn plan_statuses(&self, thread_id: &Value) -> Result<Option<Vec<String>>, LookUnreadable> {
        self.0.note(vec![
            text("turns"),
            text("plan_statuses"),
            thread_id.clone(),
        ]);
        let found = of_thread(&self.0.seam("plans"), thread_id).unwrap_or(Value::Null);
        raise_or(&found, |found| match found {
            Value::Array(items) => Some(
                items
                    .iter()
                    .map(|item| item.as_text().unwrap_or_default().to_owned())
                    .collect(),
            ),
            _ => None,
        })
    }
    fn goal(&self, thread_id: &Value) -> Result<Option<String>, LookUnreadable> {
        self.0
            .note(vec![text("goals"), text("read"), thread_id.clone()]);
        let found = of_thread(&self.0.seam("goals"), thread_id).unwrap_or(Value::Null);
        raise_or(&found, |found| match found {
            Value::Object(_) => get(found, "status").as_text().map(str::to_owned),
            other => other.as_text().map(str::to_owned),
        })
    }
    fn own(&self, thread_id: &Value, widened: bool) -> Result<bool, LookUnreadable> {
        let words = if widened {
            vec![text("every_desktop")]
        } else {
            Vec::new()
        };
        self.0.note(vec![
            text("source"),
            text("latest"),
            thread_id.clone(),
            Value::Array(words),
        ]);
        let found = of_thread(&self.0.seam("own"), thread_id).unwrap_or(Value::Bool(true));
        raise_or(&found, car_machine::pyval::truthy)
    }
    fn children(&self, parent: &Value) -> Result<Vec<Child>, LookUnreadable> {
        self.0
            .note(vec![text("lineage"), text("children"), parent.clone()]);
        let found = of_thread(&self.0.seam("children"), parent).unwrap_or(Value::Array(Vec::new()));
        raise_or(&found, |found| match found {
            Value::Array(items) => items
                .iter()
                .map(|child| Child {
                    thread_id: get(child, "thread_id")
                        .as_text()
                        .unwrap_or_default()
                        .to_owned(),
                    turn_id: get(child, "turn_id").clone(),
                    status: get(child, "status").clone(),
                    category: get(child, "category").clone(),
                })
                .collect(),
            _ => Vec::new(),
        })
    }
}

/// A session of the scenario's: `call` answers from `session.answers`; a session with no `submit` of its own is called
/// whole at once in the reference (`protocol.submitted`), so `submit` calls and `receive` hands back what it got.
struct FakeSession(Arc<Inner>, Option<Result<Value, SessionError>>);

impl Channel for FakeSession {
    fn enter(&mut self) -> Result<(), SessionError> {
        self.0.note(vec![text("session"), text("enter")]);
        if is_raise(get(&self.0.seam("session"), "enter")) {
            return Err(SessionError::Raised("RuntimeError"));
        }
        Ok(())
    }
    fn submit(&mut self, method: &str, params: Option<Value>) -> Result<i64, SessionError> {
        let got = self.call(method, params);
        self.1 = Some(got);
        Ok(0)
    }
    fn receive(&mut self, _: &str, _: i64, _: Option<&Value>) -> Result<Value, SessionError> {
        self.1
            .take()
            .unwrap_or(Err(SessionError::Raised("RuntimeError")))
    }
    fn call(&mut self, method: &str, params: Option<Value>) -> Result<Value, SessionError> {
        self.0.note(vec![
            text("session"),
            text(method),
            params.unwrap_or(Value::Null),
        ]);
        let answers = match get(get(&self.0.seam("session"), "answers"), method) {
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
        match answer.as_text() {
            Some("timeout") => return Err(SessionError::Adapter("protocol_timeout")),
            Some("refused") => return Err(SessionError::Refused),
            Some("no") => {
                return Err(SessionError::ByCodex {
                    method: method.to_owned(),
                    code: Some(-32600),
                });
            }
            _ => {}
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
    pub fn new(
        seams: Value,
        asked: Asked,
        clock: Arc<Mutex<f64>>,
        catalogs: &str,
        measured: Value,
    ) -> World {
        World(Arc::new(Inner {
            seams: Mutex::new(seams),
            asked,
            clock,
            calls: Mutex::new(HashMap::new()),
            shown: Mutex::new(None),
            ends: Mutex::new(Vec::new()),
            real: Follower::new(Arc::new(|| 0.0), 0.5),
            catalogs: Arc::new(Catalogs::new(catalogs, Box::new(|| "en".to_owned()))),
            measured,
        }))
    }

    fn opener(&self) -> Opener {
        let inner = self.0.clone();
        Box::new(move |capability: &str| -> Result<Box<dyn Channel>, ()> {
            inner.note(vec![text("session"), text("open"), text(capability)]);
            if is_raise(get(&inner.seam("session"), "open")) {
                return Err(());
            }
            Ok(Box::new(FakeSession(inner.clone(), None)))
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
                if is_raise(&found) {
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

    /// The continuation family's world: the scenario's looks and the shipped catalogs' words (in English).
    pub fn look_world(&self) -> LookWorld {
        let catalogs = self.0.catalogs.clone();
        let words: Words = Arc::new(
            move |key: &str, locale: Option<&str>, fields: &[(&str, String)]| {
                catalogs.text(key, locale, fields).ok().flatten()
            },
        );
        LookWorld {
            looks: Arc::new(FakeLooks(self.0.clone())),
            words,
        }
    }

    /// goal_continuation's world: the scenario's session and goals, M2b from its measurements, its clock.
    pub fn goal_world(&self) -> GoalWorld {
        let goals = self.0.clone();
        let clock = self.0.clock.clone();
        let entry = match get(&self.0.measured, "m2b") {
            Value::Array(pair) if pair.len() == 2 => Some((
                pair[0].as_text().unwrap_or_default().to_owned(),
                pair[1].as_text().unwrap_or_default().to_owned(),
            )),
            _ => None,
        };
        let passed = m2b_passed(
            Some("0.155.0"),
            entry
                .as_ref()
                .map(|(verdict, on)| (verdict.as_str(), on.as_str())),
        );
        GoalWorld {
            open: Arc::new(Mutex::new(self.opener())),
            goal: Arc::new(move |thread: &Value| {
                goals.note(vec![text("goals"), text("read"), thread.clone()]);
                let mut found = of_thread(&goals.seam("goals"), thread).unwrap_or(Value::Null);
                if let Value::Array(list) = &found {
                    let name = format!("goals {}", python_str(thread));
                    let index = {
                        let mut calls = goals.calls.lock().unwrap_or_else(PoisonError::into_inner);
                        let index = calls.entry(name).or_insert(0);
                        let held = *index;
                        *index += 1;
                        held
                    };
                    found = match list.len() {
                        0 => Value::Null,
                        count => list[index.min(count - 1)].clone(),
                    };
                }
                match &found {
                    Value::Str(status) if status.as_str() != Some("raise") => Some(GoalSeen {
                        goal_id: "g".to_owned(),
                        status: status.as_str().unwrap_or_default().to_owned(),
                    }),
                    Value::Object(_) => Some(GoalSeen {
                        goal_id: get(&found, "goal_id")
                            .as_text()
                            .unwrap_or_default()
                            .to_owned(),
                        status: get(&found, "status")
                            .as_text()
                            .unwrap_or_default()
                            .to_owned(),
                    }),
                    _ => None,
                }
            }),
            m2b: Arc::new(move || passed),
            clock: Arc::new(move || *clock.lock().unwrap_or_else(PoisonError::into_inner)),
        }
    }

    /// `definition.make(paths)`: the edition's own code, with the scenario's fakes where it takes them.
    pub fn make(&self, definition: &CapabilityDef, paths: &Paths) -> Option<Box<dyn Code>> {
        use car_adv::engine;
        match definition.id.as_str() {
            "headless_run" => engine::headless::make_with(paths, self.run_world()),
            "empty_response" => engine::emptyreply::make_with(paths, self.look_world()),
            "keep_going" => engine::keepgoing::make_with(paths, self.look_world()),
            "subagent_parent" => engine::subagent::make_with(paths, self.look_world()),
            "goal_continuation" => engine::goal::make_with(paths, self.goal_world()),
            "marker_free_continuation" => {
                engine::markerfree::make_with(paths, Arc::new(Mutex::new(self.opener())))
            }
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
            "seam" => {
                let name = arg(0).as_text().unwrap_or_default().to_owned();
                let mut seams = self.0.seams.lock().unwrap_or_else(PoisonError::into_inner);
                if !matches!(*seams, Value::Object(_)) {
                    *seams = Value::Object(car_machine::json::Map::new());
                }
                if let Value::Object(map) = &mut *seams {
                    map.insert(name.as_str().into(), arg(1));
                }
                Some(Ok(Value::Null))
            }
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
            "keep" => Some(
                state
                    .set_keep_going(&arg(0), &arg(1), &Value::Null)
                    .map(|()| Value::Null)
                    .map_err(|error| error.class().to_owned()),
            ),
            "kept_used" => Some(
                state
                    .keep_going_used(&arg(0), &Value::Null)
                    .map(Value::Bool)
                    .map_err(|error| error.class().to_owned()),
            ),
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
