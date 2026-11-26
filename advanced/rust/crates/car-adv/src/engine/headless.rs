//! `headless_run`'s code (seat S7.2e1; `engine/headless.py`): a conversation nothing holds is run here while Codex is
//! closed (P16), and the bookkeeping every run kind shares at P8 (`follow_up`: headless_run, compact_continue,
//! model_fallback).
//!
//! The route is S7.2c's `codex::headless::HeadlessRun`, handed to core as a [`SharedRoute`]. The seams are the
//! tests' (the reference's keywords): [`RunWorld`] opens the sessions, follows the one run ([`Follows`]), looks at the
//! app and reads the latest turns ([`TurnsReader`]). `make(paths)` gives the world a code made from `paths` alone has
//! (no session of Codex's until the entry points hand one: S7.3d); `make_with` takes a test's or an entry point's own.

use std::collections::BTreeMap;
use std::sync::{Arc, Mutex, PoisonError};

use car_config::Paths;
use car_machine::json::{Str, Value};
use car_policy::plug::{HookFailed, Route, View};

use crate::capabilities::{Binding, Code, Raised, Said, Spoke};
use crate::codex::headless::{AppLook, Ended, Follower, HeadlessRun, Opener, Shown};
use crate::codex::turns::Turn;
use crate::state::scoped::Scoped;
use crate::state::sql::{self, Row};
use crate::vocabulary::{OptionKey, RunEnd};

pub const CAPABILITY: &str = "headless_run";
/// A full context window is compact_continue's to continue, never this one's.
pub const TERMINAL_INVALID: &str = "terminal_invalid";
pub const HOURS: [i64; 8] = [1, 2, 3, 4, 5, 6, 8, 12];
pub const DEFAULT_HOURS: i64 = 1;
pub const HOUR: f64 = 3600.0;
/// How long an ended run's row is kept for the Dashboard to show how it ended.
pub const KEEP_ENDED: f64 = 86400.0;

pub(crate) fn field<'a>(record: &'a Value, name: &str) -> &'a Value {
    static NULL: Value = Value::Null;
    match record {
        Value::Object(map) => map.get(name).unwrap_or(&NULL),
        _ => &NULL,
    }
}

pub(crate) fn is_text(value: &Value, word: &str) -> bool {
    car_machine::pyval::eq(value, &Value::Str(word.into()))
}

/// `unheld(record)`: whether core asked P16 with the Codex app closed (`app is False`) and nothing holding the
/// conversation (`holder == "none"`).
pub fn unheld(record: &Value) -> bool {
    matches!(record, Value::Object(_))
        && matches!(field(record, "app"), Value::Bool(false))
        && is_text(field(record, "holder"), "none")
}

/// `record.get("interruption_id") if isinstance(record, dict) else None`, and whether it is one (`ids`).
pub fn interruption_key(record: &Value) -> (Value, bool) {
    let key = field(record, "interruption_id").clone();
    let valid = car_machine::domain::ids::is_interruption_id(&key, false);
    (key, valid)
}

/// What a run kind is told of the one run: `live`, `stop`, `drain` (`codex/headless.Follower`, or a test's), and the
/// real follower a route is made with.
pub trait Follows: Send + Sync {
    fn live(&self) -> Option<Shown>;
    fn stop(&self, key: Option<&Value>, reason: RunEnd) -> bool;
    fn drain(&self, capability: &str) -> Vec<Ended>;
    fn follower(&self) -> Arc<Follower>;
}

impl Follows for Arc<Follower> {
    fn live(&self) -> Option<Shown> {
        Follower::live(self)
    }
    fn stop(&self, key: Option<&Value>, reason: RunEnd) -> bool {
        Follower::stop(self, key, reason)
    }
    fn drain(&self, capability: &str) -> Vec<Ended> {
        Follower::drain(self, capability)
    }
    fn follower(&self) -> Arc<Follower> {
        self.clone()
    }
}

/// The reads of a conversation's turns a run kind makes (`codex/turns.Turns` over the Codex home): Err where the
/// reference raises.
pub trait TurnsReader: Send + Sync {
    fn latest(&self, thread_id: &Value) -> Result<Option<Turn>, ()>;
    fn turn_code(&self, thread_id: &Value, turn_id: &Value) -> Result<Value, ()>;
}

/// The Codex home of a code made from `paths` alone is not known here: every read raises.
struct NoTurns;

impl TurnsReader for NoTurns {
    fn latest(&self, _thread_id: &Value) -> Result<Option<Turn>, ()> {
        Err(())
    }
    fn turn_code(&self, _thread_id: &Value, _turn_id: &Value) -> Result<Value, ()> {
        Err(())
    }
}

/// `_unheld_now(paths)(thread_id)`: Ok(the answer) or Err (it raised).
pub type UnheldNow = Arc<dyn Fn(&Value) -> Result<Value, ()> + Send + Sync>;

/// The seams a run kind's code is made with (the reference's `session`, `follower`, `app_running`, `turns`,
/// `unheld_now`), and `on_route`: told of every route as it is made (a test's look at what was handed core).
#[derive(Clone)]
pub struct RunWorld {
    pub open: Arc<Mutex<Opener>>,
    pub follows: Arc<dyn Follows>,
    pub app_running: Arc<dyn Fn() -> AppLook + Send + Sync>,
    pub turns: Arc<dyn TurnsReader>,
    pub unheld_now: UnheldNow,
    pub on_route: Option<Arc<dyn Fn(&HeadlessRun) + Send + Sync>>,
}

impl RunWorld {
    /// The world a code made from `paths` alone has: the process's one follower, no session (each open fails), an app
    /// look and an unheld look that raise, and no turns.
    pub fn bare() -> RunWorld {
        RunWorld {
            open: Arc::new(Mutex::new(Box::new(|_: &str| Err(())))),
            follows: Arc::new(crate::codex::headless::follower().clone()),
            app_running: Arc::new(|| -> AppLook { Box::new(|| Err(())) }),
            turns: Arc::new(NoTurns),
            unheld_now: Arc::new(|_: &Value| Err(())),
            on_route: None,
        }
    }

    /// `HeadlessRun(capability, key=key, session=self._open, follower=self.follower, seconds=..., mode=...,
    /// app_running=self._app)`.
    pub fn route(
        &self,
        capability: &str,
        key: Value,
        seconds: f64,
        mode: &'static str,
    ) -> HeadlessRun {
        let open = self.open.clone();
        let opener: Opener = Box::new(move |asking: &str| {
            let mut held = open.lock().unwrap_or_else(PoisonError::into_inner);
            (held)(asking)
        });
        let mut route = HeadlessRun::new(capability, key, opener, self.follows.follower());
        route.seconds = seconds;
        route.mode = mode;
        let app = self.app_running.clone();
        route.app_running = Some(Box::new(move || app()));
        route
    }

    /// Tell `on_route` of a route made.
    pub fn made(&self, route: &HeadlessRun) {
        if let Some(on_route) = &self.on_route {
            on_route(route);
        }
    }
}

/// A route as core holds it, the code keeping it too (to read what it came to: `refused`, `on_default`).
#[derive(Clone)]
pub struct SharedRoute(pub Arc<Mutex<HeadlessRun>>);

impl SharedRoute {
    pub fn new(route: HeadlessRun) -> SharedRoute {
        SharedRoute(Arc::new(Mutex::new(route)))
    }

    pub fn held(&self) -> std::sync::MutexGuard<'_, HeadlessRun> {
        self.0.lock().unwrap_or_else(PoisonError::into_inner)
    }
}

impl Route for SharedRoute {
    /// Core has entered its launch guard before it calls this (S7.2a2's `routes.rs`), so the route is handed none.
    fn resume(
        &self,
        thread_id: &str,
        still_unloaded: Option<&dyn Fn() -> bool>,
        words: Option<&Str>,
        client_id: Option<&str>,
    ) -> Value {
        let mut still =
            still_unloaded.map(|look| move || -> Result<Value, ()> { Ok(Value::Bool(look())) });
        let words = words.map_or(Value::Null, |words| Value::Str(words.clone()));
        let client = client_id.map_or(Value::Null, |client| Value::Str(client.into()));
        let answer = self.held().resume(
            &Value::Str(thread_id.into()),
            None,
            still
                .as_mut()
                .map(|look| look as &mut dyn FnMut() -> Result<Value, ()>),
            &words,
            &client,
        );
        Value::Object(answer)
    }

    fn takes_words(&self) -> Result<bool, HookFailed> {
        Ok(HeadlessRun::TAKES_WORDS)
    }
}

/// A number of the reference's as seconds (`hours * HOUR`).
pub(crate) fn seconds_of(value: &Value, unit: f64) -> f64 {
    match value {
        Value::Int(int) => int.as_i64().unwrap_or(0) as f64 * unit,
        Value::Float(number) => number * unit,
        Value::Bool(true) => unit,
        _ => 0.0,
    }
}

/// `HeadlessRunCode(paths, session=..., follower=..., app_running=...)`.
pub struct HeadlessRunCode {
    pub paths: Paths,
    binding: Option<Binding>,
    world: RunWorld,
    routes: BTreeMap<String, SharedRoute>,
}

impl HeadlessRunCode {
    pub fn new(paths: Paths, world: RunWorld) -> HeadlessRunCode {
        HeadlessRunCode {
            paths,
            binding: None,
            world,
            routes: BTreeMap::new(),
        }
    }

    fn follow(&mut self) -> Spoke {
        let routes: Vec<SharedRoute> = self.routes.values().cloned().collect();
        follow_up(
            self.binding.as_ref(),
            self.world.follows.as_ref(),
            CAPABILITY,
            &routes,
            None,
        );
        Ok(Said::Defer)
    }
}

impl Code for HeadlessRunCode {
    fn bind(&mut self, binding: Binding) -> Option<Result<(), Raised>> {
        self.binding = Some(binding);
        Some(Ok(()))
    }

    /// P16: the route, for a record asked with no app and no holder, of a kind this runs, while no run is live.
    fn unloaded(&mut self, record: &Value) -> Spoke {
        let (key, valid) = interruption_key(record);
        if !unheld(record) || !valid {
            return Ok(Said::Defer);
        }
        let Some(binding) = &self.binding else {
            return Ok(Said::Defer);
        };
        if is_text(field(record, "category"), TERMINAL_INVALID)
            || self.world.follows.live().is_some()
        {
            return Ok(Said::Defer);
        }
        let hours = binding
            .with(|scoped| {
                super::parallel::option_in(
                    scoped.options().map_err(|_| ()),
                    OptionKey::CeilingHours,
                    &HOURS,
                    DEFAULT_HOURS,
                )
            })
            .unwrap_or(Value::from(DEFAULT_HOURS));
        let route = self.world.route(
            CAPABILITY,
            key.clone(),
            seconds_of(&hours, HOUR),
            crate::codex::headless::TURN,
        );
        self.world.made(&route);
        let shared = SharedRoute::new(route);
        self.routes = BTreeMap::from([(key_text(&key), shared.clone())]);
        Ok(Said::Route(Box::new(shared)))
    }

    /// P8: the bookkeeping every run kind shares (`follow_up`).
    fn tick(&mut self, _view: &dyn View) -> Spoke {
        self.follow()
    }

    /// Turned off or watched, the same bookkeeping (`tend = tick`).
    fn tend(&mut self, _view: &dyn View) -> Option<Spoke> {
        Some(self.follow())
    }
}

pub(crate) fn key_text(key: &Value) -> String {
    match key {
        Value::Str(text) => format!("{text:?}"),
        other => format!("{other:?}"),
    }
}

/// What `follow_up` tells its caller of each run's end (`on_end`): Err where it raised (the rest is not done).
pub type OnEnd<'a> = Option<&'a mut dyn FnMut(&Scoped<'_>, &Ended) -> Result<(), ()>>;

/// `follow_up(scoped, follower, capability, routes, on_end)`: P8 of each run kind, the one path - the live run's row
/// written; a person's Stop handed to the follower; a refusal and how each run ended journalled, `on_end` told of each
/// end; every row no thread follows ended LOST; ended rows older than KEEP_ENDED pruned. Whatever raises stops the rest
/// (the next tick writes what this one could not). Never an errand.
pub fn follow_up(
    binding: Option<&Binding>,
    follows: &dyn Follows,
    capability: &str,
    routes: &[SharedRoute],
    mut on_end: OnEnd<'_>,
) {
    let Some(binding) = binding else {
        return;
    };
    let _ = binding.with(|scoped| -> Result<(), ()> {
        let state = scoped.state;
        let own = Value::Str(capability.into());
        let runs_live = || -> Result<Vec<Row>, ()> {
            Ok(state
                .runs(&Value::Bool(true), &Value::from(20))
                .map_err(|_| ())?
                .into_iter()
                .filter(|row| sql::py_eq(sql::get(row, "capability"), &own))
                .collect())
        };
        let live = follows.live().filter(|live| live.capability == capability);
        if let Some(live) = &live {
            let rows = runs_live()?;
            let row = rows
                .iter()
                .rev()
                .find(|row| car_machine::pyval::eq(sql::get(row, "interruption_id"), &live.key));
            match row {
                None => state
                    .run_started(
                        &live.key,
                        &own,
                        &live.thread_id,
                        &Value::Float(live.started_at),
                        &Value::Float(live.ends_by),
                    )
                    .map_err(|_| ())?,
                Some(row) => {
                    if !matches!(sql::get(row, "stop_requested_at"), Value::Null) {
                        follows.stop(Some(&live.key), RunEnd::Interrupted);
                    }
                }
            }
        }
        for route in routes {
            let refused = route.held().refused;
            if let Some(refused) = refused {
                scoped
                    .count(&Value::Str(refused.as_str().into()))
                    .map_err(|_| ())?;
                route.held().refused = None;
            }
        }
        for ended in follows.drain(capability) {
            let end = Value::Str(ended.end.as_str().into());
            state
                .run_ended(&ended.key, &end, &Value::Null)
                .map_err(|_| ())?;
            scoped.count(&end).map_err(|_| ())?;
            if let Some(on_end) = on_end.as_mut() {
                on_end(scoped, &ended)?;
            }
        }
        for row in runs_live()? {
            let key = sql::get(&row, "interruption_id").clone();
            if live
                .as_ref()
                .is_none_or(|live| !car_machine::pyval::eq(&key, &live.key))
            {
                state
                    .run_ended(
                        &key,
                        &Value::Str(RunEnd::Lost.as_str().into()),
                        &Value::Null,
                    )
                    .map_err(|_| ())?;
            }
        }
        state
            .prune_runs(&Value::Float(scoped.now() - KEEP_ENDED), &own)
            .map_err(|_| ())?;
        Ok(())
    });
}

/// `make(paths)`: the capability's code with the world a code made from `paths` alone has ([`RunWorld::bare`]).
pub fn make(paths: &Paths) -> Option<Box<dyn Code>> {
    make_with(paths, RunWorld::bare())
}

/// `HeadlessRunCode(paths, ...)` with an entry point's or a test's own world.
pub fn make_with(paths: &Paths, world: RunWorld) -> Option<Box<dyn Code>> {
    Some(Box::new(HeadlessRunCode::new(paths.clone(), world)))
}
