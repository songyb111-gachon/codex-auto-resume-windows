//! `model_fallback`'s code (seat S7.2e1; `engine/fallback.py`): another model when one is at capacity (P16 and P8;
//! headless only).
//!
//! P16 answers the headless route in fallback mode for a server error Codex coded `serverOverloaded`, once its task had
//! the person's Attempts of continuations, only where nothing holds the conversation while Codex is closed, and not for
//! a conversation a route of its own found on Codex's default model within ON_DEFAULT_FOR. P8 journals how each run
//! ended (a model put back cleared from the debt, one Codex would not put back journalled), then, while a debt is left
//! and no run is live, hands the errand that puts it back - the one write inside core's errand guard, read back.

use std::collections::BTreeMap;
use std::sync::{Arc, Mutex, PoisonError};

use car_config::Paths;
use car_machine::json::{Map, Value};
use car_policy::plug::{Errand, Guards, HookFailed, View};

use super::headless::{
    HOUR, RunWorld, SharedRoute, field, follow_up, interruption_key, is_text, key_text, unheld,
};
use crate::capabilities::{Binding, Code, Raised, Said, Spoke};
use crate::codex::headless::{FALLBACK, Owe};
use crate::state::sql::{self, Row};
use crate::vocabulary::OptionKey;

pub const CAPABILITY: &str = "model_fallback";
pub const KIND: &str = "server_5xx";
pub const CODE: &str = "serverOverloaded";
pub const ATTEMPTS: [i64; 5] = [1, 2, 3, 4, 5];
pub const DEFAULT_ATTEMPTS: i64 = 2;
pub const NOT_RESTORED: &str = "model_not_restored";
/// How often a model still owed back is tried again, in seconds.
pub const RESTORE_EVERY: f64 = 600.0;
/// How long a conversation found on Codex's default model already is left to the others at P16, in seconds.
pub const ON_DEFAULT_FOR: f64 = 86400.0;

/// A second hold of the same binding (for the route's `owe` and the errand, which outlive the hook).
fn rebind(binding: &Binding) -> Binding {
    Binding {
        runtime: binding.runtime.clone(),
        capability: binding.capability.clone(),
    }
}

/// `ModelFallback(paths, turns=..., session=..., follower=..., app_running=..., unheld_now=...)`.
pub struct ModelFallback {
    pub paths: Paths,
    binding: Option<Binding>,
    world: RunWorld,
    routes: BTreeMap<String, SharedRoute>,
    tried: Arc<Mutex<BTreeMap<String, f64>>>,
    /// `_on_default`: thread -> when; in the order first met, as a dict keeps it.
    on_default: Vec<(Value, f64)>,
}

impl ModelFallback {
    pub fn new(paths: Paths, world: RunWorld) -> ModelFallback {
        ModelFallback {
            paths,
            binding: None,
            world,
            routes: BTreeMap::new(),
            tried: Arc::new(Mutex::new(BTreeMap::new())),
            on_default: Vec::new(),
        }
    }

    /// `_overloaded(record)`: whether the failed turn is Codex's capacity code (a KeyError or a failed read is no).
    fn overloaded(&self, record: &Value) -> bool {
        let Value::Object(map) = record else {
            return false;
        };
        let (Some(thread), Some(turn)) = (map.get("thread_id"), map.get("turn_id")) else {
            return false;
        };
        matches!(self.world.turns.turn_code(thread, turn), Ok(code) if is_text(&code, CODE))
    }

    /// `_defaulted(record)`: whether the conversation was found on Codex's default model within ON_DEFAULT_FOR - what a
    /// route of its own found taken in first, once. Err: the thread id cannot be a dict's key (TypeError).
    fn defaulted(&mut self, record: &Value) -> Result<bool, Raised> {
        let Some(now) = self
            .binding
            .as_ref()
            .and_then(|binding| binding.with(|scoped| scoped.now()))
        else {
            return Ok(false);
        };
        for route in self.routes.values() {
            let thread = route.held().on_default.take();
            if let Some(thread) = thread {
                match self
                    .on_default
                    .iter_mut()
                    .find(|(known, _)| car_machine::pyval::eq(known, &thread))
                {
                    Some(entry) => entry.1 = now,
                    None => self.on_default.push((thread, now)),
                }
            }
        }
        self.on_default
            .retain(|(_, at)| 0.0 <= now - at && now - at < ON_DEFAULT_FOR);
        let thread = field(record, "thread_id");
        car_machine::pyval::hashable(thread).map_err(Raised::new)?;
        Ok(self
            .on_default
            .iter()
            .any(|(known, _)| car_machine::pyval::eq(known, thread)))
    }
}

impl Code for ModelFallback {
    fn bind(&mut self, binding: Binding) -> Option<Result<(), Raised>> {
        self.binding = Some(binding);
        Some(Ok(()))
    }

    /// P16: the fallback route, for an unheld conversation at capacity after the Attempts chosen.
    fn unloaded(&mut self, record: &Value) -> Spoke {
        let (key, valid) = interruption_key(record);
        if !unheld(record) || !is_text(field(record, "category"), KIND) || !valid {
            return Ok(Said::Defer);
        }
        let Some(binding) = self.binding.as_ref().map(rebind) else {
            return Ok(Said::Defer);
        };
        if self.world.follows.live().is_some() {
            return Ok(Said::Defer);
        }
        let attempts = binding
            .with(|scoped| {
                super::parallel::option_in(
                    scoped.options().map_err(|_| ()),
                    OptionKey::Attempts,
                    &ATTEMPTS,
                    DEFAULT_ATTEMPTS,
                )
            })
            .unwrap_or(Value::from(DEFAULT_ATTEMPTS));
        let chain = field(record, "chain_continuations");
        let chain = if car_machine::pyval::truthy(chain) {
            chain.clone()
        } else {
            Value::from(0)
        };
        if car_machine::pyval::less(&chain, &attempts).map_err(Raised::new)?
            || self.defaulted(record)?
            || !self.overloaded(record)
        {
            return Ok(Said::Defer);
        }
        let mut route = self.world.route(CAPABILITY, key.clone(), HOUR, FALLBACK);
        let owed_key = key.clone();
        let owe: Owe = Box::new(move |thread_id: &Value, model: &str, seconds: f64| {
            binding
                .with(|scoped| -> Result<Value, ()> {
                    let now = scoped.now();
                    scoped
                        .state
                        .run_owed(
                            &owed_key,
                            &Value::Str(CAPABILITY.into()),
                            thread_id,
                            &Value::Str(model.into()),
                            &Value::Float(now),
                            &Value::Float(now + seconds),
                        )
                        .map_err(|_| ())?;
                    Ok(Value::Bool(true))
                })
                .unwrap_or(Err(()))
        });
        route.owe = Some(owe);
        self.world.made(&route);
        let shared = SharedRoute::new(route);
        self.routes = BTreeMap::from([(key_text(&key), shared.clone())]);
        Ok(Said::Route(Box::new(shared)))
    }

    /// P8: the run kinds' one path, a model put back cleared from the debt, one Codex would not put back journalled;
    /// then, while a debt is left and no run is live, the errand that puts it back.
    fn tick(&mut self, _view: &dyn View) -> Spoke {
        let routes: Vec<SharedRoute> = self.routes.values().cloned().collect();
        let mut told = |scoped: &crate::state::scoped::Scoped<'_>,
                        ended: &crate::codex::headless::Ended|
         -> Result<(), ()> {
            match ended.model_restored {
                Some(true) => {
                    scoped.state.run_restored(&ended.key).map_err(|_| ())?;
                }
                Some(false) => {
                    scoped
                        .count(&Value::Str(NOT_RESTORED.into()))
                        .map_err(|_| ())?;
                }
                None => {}
            }
            Ok(())
        };
        follow_up(
            self.binding.as_ref(),
            self.world.follows.as_ref(),
            CAPABILITY,
            &routes,
            Some(&mut told),
        );
        let Some(binding) = &self.binding else {
            return Ok(Said::Defer);
        };
        if self.world.follows.live().is_some() {
            return Ok(Said::Defer);
        }
        let tried = self
            .tried
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
            .clone();
        let owed = binding
            .with(|scoped| -> Result<Vec<Row>, ()> {
                let rows = scoped
                    .state
                    .runs_owed(&Value::Str(CAPABILITY.into()))
                    .map_err(|_| ())?;
                let now = scoped.now();
                Ok(rows
                    .into_iter()
                    .filter(|row| {
                        let at = tried
                            .get(&key_text(sql::get(row, "interruption_id")))
                            .copied()
                            .unwrap_or(f64::NEG_INFINITY);
                        now - at >= RESTORE_EVERY
                    })
                    .collect())
            })
            .unwrap_or(Err(()))
            .unwrap_or_default();
        let Some(row) = owed.into_iter().next() else {
            return Ok(Said::Defer);
        };
        Ok(Said::Errand(Box::new(Restore {
            binding: rebind(binding),
            world: self.world.clone(),
            tried: self.tried.clone(),
            row,
        })))
    }

    /// Turned off or watched, a model still owed back is put back all the same (`tend = tick`).
    fn tend(&mut self, view: &dyn View) -> Option<Spoke> {
        Some(self.tick(view))
    }
}

/// `_Restore`: P8's errand - the model a fallback turn still owes its conversation put back, only while no run is live,
/// Codex is closed and nothing holds the conversation; the one write inside core's errand guard, read back outside it.
pub struct Restore {
    binding: Binding,
    world: RunWorld,
    tried: Arc<Mutex<BTreeMap<String, f64>>>,
    row: Row,
}

impl Restore {
    fn params(thread: &Value, more: (&str, Value)) -> Option<Value> {
        let mut map = Map::new();
        map.insert("threadId".into(), thread.clone());
        map.insert(more.0.into(), more.1);
        Some(Value::Object(map))
    }
}

impl Errand for Restore {
    fn run(&self, _view: &dyn View, guards: &mut Guards<'_>) -> Result<Value, HookFailed> {
        let thread = sql::get(&self.row, "thread_id").clone();
        let model = sql::get(&self.row, "restore_model").clone();
        let key = sql::get(&self.row, "interruption_id").clone();
        if self.world.follows.live().is_some()
            || !matches!((self.world.unheld_now)(&thread), Ok(Value::Bool(true)))
        {
            return Ok(Value::Null);
        }
        let Some(now) = self.binding.with(|scoped| scoped.now()) else {
            return Ok(Value::Null);
        };
        self.tried
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
            .insert(key_text(&key), now);
        let opened = {
            let mut open = self
                .world
                .open
                .lock()
                .unwrap_or_else(PoisonError::into_inner);
            (open)(CAPABILITY)
        };
        let Ok(mut session) = opened else {
            return Ok(Value::Null);
        };
        if session.enter().is_err() {
            return Ok(Value::Null);
        }
        let resume = || Self::params(&thread, ("excludeTurns", Value::Bool(true)));
        let mut restored = false;
        let mut asked = false;
        if session.call("thread/resume", resume()).is_ok() {
            // None: the guard said no (the errand returns at once); Some(the update's outcome) otherwise.
            let mut outcome: Option<bool> = None;
            let guarded = guards(&mut |permitted: bool| {
                if permitted {
                    asked = true;
                    outcome = Some(
                        session
                            .call(
                                "thread/settings/update",
                                Self::params(&thread, ("model", model.clone())),
                            )
                            .is_ok(),
                    );
                }
                Value::Null
            });
            match (guarded, outcome) {
                (Ok(_), None) => {
                    session.exit();
                    return Ok(Value::Null);
                }
                (Ok(_), Some(true)) => {
                    if let Ok(resumed) = session.call("thread/resume", resume()) {
                        restored =
                            crate::codex::headless::model_of(&resumed).is_some_and(|found| {
                                car_machine::pyval::eq(&Value::Str(found.as_str().into()), &model)
                            });
                    }
                }
                _ => {}
            }
        }
        session.exit();
        // Outside the reference's try: a write that raises here is the errand's own failure.
        let written = if restored {
            self.binding
                .with(|scoped| scoped.state.run_restored(&key).map(|_| ()))
        } else if asked {
            self.binding
                .with(|scoped| scoped.count(&Value::Str(NOT_RESTORED.into())).map(|_| ()))
        } else {
            Some(Ok(()))
        };
        match written {
            Some(Ok(())) => Ok(Value::Null),
            _ => Err(HookFailed),
        }
    }
}

/// `make(paths)`: the capability's code with the world a code made from `paths` alone has.
pub fn make(paths: &Paths) -> Option<Box<dyn Code>> {
    make_with(paths, RunWorld::bare())
}

/// `ModelFallback(paths, ...)` with an entry point's or a test's own world.
pub fn make_with(paths: &Paths, world: RunWorld) -> Option<Box<dyn Code>> {
    Some(Box::new(ModelFallback::new(paths.clone(), world)))
}
