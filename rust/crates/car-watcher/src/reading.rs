//! The engines Diagnostics' check and Rescan ask (S6.2b4): `Engine(store, source, None, clock=lambda: now)` for
//! `checkup.run`, `Engine(None, source, None, clock=lambda: now, home_key=key)` for `rescan.judge_for` - engines that
//! read and do nothing else.
//!
//! The reference hands those engines `None` for what they must not have: any call of it is an `AttributeError`
//! (`'NoneType' object has no attribute ...`), which the check and the judge meet as they meet any other exception of
//! that call. [`NoStore`] and [`NoBackend`] are that `None`: every call answers `AttributeError`.

use std::rc::Rc;
use std::sync::Arc;

use car_codex::source::LocalSource;
use car_control::host::Host;
use car_engine::seam::{Claimed, Correlate, LaunchGuard, Withdrawn};
use car_engine::{Claim, Engine, Given, Register, Row};
use car_machine::json::{Map, Str, Value};
use car_machine::pyval::Py;
use car_policy::classify::gates::Vector;
use car_policy::plug::Guarded;

use crate::fail::{Failed, Res};
use crate::rescan::RescanEngine;

const NONE: &str = "AttributeError";

/// `None` as an engine's store.
pub struct NoStore;

impl car_scheduler::Store for NoStore {
    fn get(&self, _: &str) -> Py<Option<Row>> {
        Err(NONE)
    }
    fn update(&self, _: &str, _: &Row, _: Option<f64>, _: Option<&str>, _: i64) -> Py<()> {
        Err(NONE)
    }
    fn thread_enabled(&self, _: &str) -> Py<bool> {
        Err(NONE)
    }
    fn settings(&self) -> Py<Row> {
        Err(NONE)
    }
    fn correlate(&self, _: &str, _: &str, _: f64, _: &Correlate) -> Py<bool> {
        Err(NONE)
    }
    fn release_withdrawn(&self, _: &str, _: f64, _: &Withdrawn) -> Py<bool> {
        Err(NONE)
    }
    fn records_in(&self, _: &[&str], _: Option<&str>) -> Py<Vec<Row>> {
        Err(NONE)
    }
}

impl car_engine::Store for NoStore {
    fn record_gates(&self, _: &str, _: &Vector, _: f64) -> Py<()> {
        Err(NONE)
    }
    fn record_would_send(&self, _: &str, _: &Vector, _: f64, _: f64) -> Py<bool> {
        Err(NONE)
    }
    fn submission_guard(&self, _: &str, _: &mut dyn FnMut(bool) -> Value) -> Py<Value> {
        Err(NONE)
    }
    fn recent_claims(&self, _: &str, _: f64) -> Py<Vec<Value>> {
        Err(NONE)
    }
    fn recent_claim_count(&self, _: &str, _: f64) -> Py<i64> {
        Err(NONE)
    }
    fn others_in_flight(&self, _: &str, _: &str) -> Py<i64> {
        Err(NONE)
    }
    fn reserve_detailed(&self, _: &str, _: f64, _: &Claim) -> Py<Claimed> {
        Err(NONE)
    }
    fn release_claim(&self, _: &str, _: &str, _: &str, _: f64, _: Option<f64>) -> Py<bool> {
        Err(NONE)
    }
    fn claimed_on_thread(&self, _: &str) -> Py<Vec<Row>> {
        Err(NONE)
    }
    fn chain_parent(&self, _: &str, _: &str, _: Option<&str>) -> Py<Option<Row>> {
        Err(NONE)
    }
    fn register(&self, _: &Row, _: f64, _: &Register) -> Py<bool> {
        Err(NONE)
    }
    fn thread_tier(&self, _: &str) -> Py<Value> {
        Err(NONE)
    }
    fn enrol_conversation(&self, _: &str, _: &str, _: f64) -> Py<bool> {
        Err(NONE)
    }
    fn hold_changed(&self, _: &str, _: &Value, _: f64) -> Py<bool> {
        Err(NONE)
    }
    fn hold_waiting(&self, _: &[String], _: &str, _: f64) -> Py<i64> {
        Err(NONE)
    }
    fn cancel_waiting(&self, _: &[String], _: f64, _: &str) -> Py<Vec<Value>> {
        Err(NONE)
    }
    fn open_objection_window(&self, _: &str, _: f64, _: f64) -> Py<bool> {
        Err(NONE)
    }
    fn raise_notice(&self, _: &str, _: &str, _: &str, _: f64) -> Py<bool> {
        Err(NONE)
    }
    fn watcher_status(&self) -> Py<Option<Row>> {
        Err(NONE)
    }
    fn usage_checks_asked(&self, _: f64) -> Py<Row> {
        Err(NONE)
    }
    fn usage_not_checked(&self, _: &str, _: f64, _: &str) -> Py<()> {
        Err(NONE)
    }
    fn usage_check_taken(&self, _: &str) -> Py<Value> {
        Err(NONE)
    }
    fn usage_checked(&self, _: &str, _: f64, _: &str, _: &Value) -> Py<Option<Row>> {
        Err(NONE)
    }
    fn early_check_asked(&self, _: f64) -> Py<bool> {
        Err(NONE)
    }
    fn early_check_taken(&self) -> Py<()> {
        Err(NONE)
    }
}

/// `None` as an engine's backend.
pub struct NoBackend;

impl car_engine::Backend for NoBackend {
    fn app_identity(&self) -> Py<Value> {
        Err(NONE)
    }
    fn loaded(&self, _: &str, _: &Value) -> Py<Value> {
        Err(NONE)
    }
    fn usage(&self) -> Py<Value> {
        Err(NONE)
    }
    fn send(&self, _: &str, _: &Str, _: &dyn LaunchGuard) -> Py<Value> {
        Err(NONE)
    }
    fn delete_queue(&self, _: &str, _: &str) -> Py<Value> {
        Err(NONE)
    }
}

/// The reader of one Codex home as the check and Rescan make it: the watcher's split ids, read only
/// (`chain_memory(control.paths.split_chains_file, writable=False)`).
pub fn source(host: &Arc<dyn Host>, chains_file: &str, home: &str) -> Res<LocalSource> {
    let chains = car_codex::chains::memory(Some(std::path::Path::new(chains_file)), false);
    LocalSource::new(host.os(), home, Some(chains))
        .map_err(|error| Failed::new(error.class(), error.message()))
}

/// `Engine(store, source, None, clock=lambda: now, home_key=key)`, every other keyword the reference's default.
pub fn engine(
    host: &Arc<dyn Host>,
    store: Option<Rc<car_store::Store>>,
    source: LocalSource,
    now: f64,
    home_key: &str,
) -> Engine {
    let environ = Arc::clone(host);
    let languages = Arc::clone(host);
    let given = Given {
        dispatch_lock: None,
        clock: Box::new(move || now),
        log: None,
        options: Map::new(),
        notify: None,
        language: None,
        home_lock: None,
        engine_state: None,
        plug: Arc::new(Guarded::null()),
        connectivity: None,
        home_key: home_key.to_owned(),
        open_store: false,
        once_words: None,
        draw: Box::new(|| 0.0),
        local: host.local_clock(),
        environ: Box::new(move |name| environ.environ(name)),
        windows_languages: Box::new(move || languages.windows_languages()),
        os: host.os(),
    };
    let store: Box<dyn car_engine::Store> = match store {
        Some(store) => Box::new(crate::join::store::EngineStore(store, None)),
        None => Box::new(NoStore),
    };
    Engine::new(
        store,
        Box::new(car_engine::seam::Codex(source)),
        Box::new(NoBackend),
        given,
    )
}

fn py(class: &'static str) -> Failed {
    Failed::new(class, "")
}

fn text(value: &Value) -> Res<&str> {
    match value {
        Value::Str(found) => found.as_str().ok_or_else(|| py("UnicodeEncodeError")),
        _ => Err(py("TypeError")),
    }
}

/// What `rescan.judge` asks of one home's engine (`engine` and `engine.source`); `evidence` is `engine.source` for
/// the one call the engine's reader trait does not carry (`rescan_evidence`), a reader of the same home.
pub struct Reading {
    pub engine: Engine,
    pub evidence: LocalSource,
}

impl RescanEngine for Reading {
    fn proof(&mut self, row: &Map) -> Res<Value> {
        Ok(Value::from(self.engine.proof(row)))
    }
    fn turn_observation(&mut self, thread: &Value, turn_id: &Value, proof: &Value) -> Res<Value> {
        self.engine
            .source
            .turn_observation(text(thread)?, text(turn_id)?, text(proof)?)
            .map(Value::Object)
            .map_err(py)
    }
    fn later_turns(&mut self, thread: &Value, ordinal: &Value, proof: &Value) -> Res<Value> {
        self.engine
            .source
            .later_turns(text(thread)?, ordinal, text(proof)?)
            .map(|turns| Value::Array(turns.into_iter().map(Value::Object).collect()))
            .map_err(py)
    }
    fn persons_turns(&mut self, thread: &Value, turns: &Value) -> Res<Vec<Value>> {
        let Value::Array(items) = turns else {
            return Err(py("TypeError"));
        };
        let mut maps = Vec::with_capacity(items.len());
        for item in items {
            match item {
                Value::Object(map) => maps.push(map.clone()),
                _ => return Err(py("AttributeError")),
            }
        }
        Ok(self
            .engine
            .persons_turns(text(thread)?, maps)
            .into_iter()
            .map(Value::Object)
            .collect())
    }
    fn foreign(&mut self, row: &Map, turn: &Value) -> Res<bool> {
        match turn {
            Value::Object(turn) => Ok(self.engine.foreign(row, turn)),
            _ => Err(py("AttributeError")),
        }
    }
    fn turn_markers(&mut self, thread: &Value, turn_id: &Value, ours: &[String]) -> Res<bool> {
        self.engine
            .source
            .turn_markers(text(thread)?, text(turn_id)?, ours)
            .map(|found| !found.is_empty())
            .map_err(py)
    }
    fn clock(&mut self) -> f64 {
        self.engine.now()
    }
    fn fresh_throughout(&mut self, thread: &Value, now: f64) -> Res<bool> {
        Ok(self.engine.fresh_throughout(text(thread)?, now))
    }
    fn valid_interruption(&mut self, row: &Map) -> Res<bool> {
        self.engine.valid_interruption(row).map_err(py)
    }
    fn rescan_evidence(&mut self, thread: &Value, turn_id: &Value) -> Res<Value> {
        let thread = text(thread)?;
        let turn_id = match turn_id {
            Value::Str(found) => found.as_str().unwrap_or_default(),
            _ => "",
        };
        Ok(Value::from(self.evidence.rescan_evidence(thread, turn_id)))
    }
}
