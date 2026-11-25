//! The engine as car-scheduler's watch sees it (`ReconcileMixin`'s `self`): each method is the engine's own.

use std::sync::{Arc, Mutex};

use car_machine::json::{Map, Value};
use car_machine::pyval::Py;
use car_scheduler::Host;

use crate::py::s;
use crate::{Engine, Row};

impl Host for Engine {
    fn clock(&self) -> f64 {
        self.now()
    }
    fn watch_store(&self) -> &dyn car_scheduler::Store {
        self.store.as_ref()
    }
    fn watch_source(&self) -> &dyn car_scheduler::Source {
        self.source.as_ref()
    }
    fn delete_queue(&self, thread_id: &str, queue_id: &str) -> Py<Value> {
        self.backend.delete_queue(thread_id, queue_id)
    }
    fn option(&self, name: &str) -> f64 {
        self.options.number(name)
    }
    fn dispatch_lock(&self) -> Option<Arc<Mutex<()>>> {
        self.dispatch_lock.clone()
    }
    fn watch_offset(&mut self) -> &mut u64 {
        &mut self.watch_offset
    }
    fn records(&self, states: &[&str]) -> Py<Vec<Row>> {
        Engine::records(self, states)
    }
    fn proof(&self, row: &Row) -> String {
        Engine::proof(self, row)
    }
    fn transition(
        &mut self,
        row: &Row,
        state: &str,
        reason: Option<&str>,
        delay: Option<f64>,
        event: Option<&str>,
        extra: Row,
    ) -> Py<()> {
        Engine::transition(self, row, state, reason, delay, event, extra)
    }
    fn moved(&mut self, row: &Row, state: &str) {
        Engine::moved(self, row, state)
    }
    fn log(&mut self, thread_id: Option<&str>, event: &str, detail: Value) {
        Engine::log(self, thread_id, event, detail)
    }
    fn announce(&mut self, event: &str, row: &Row, detail: Row) {
        Engine::announce(self, event, row, detail)
    }
    fn sighted(&mut self, interruption_id: &str) {
        Engine::sighted(self, interruption_id)
    }
    fn untraced(&mut self, interruption_id: &str) {
        self.no_trace.pop(interruption_id);
    }
    fn traceless(&mut self, row: &Row, now: f64) {
        Engine::traceless(self, row, now)
    }
    fn persons_turns(&mut self, thread_id: &str, turns: Vec<Map>) -> Vec<Map> {
        Engine::persons_turns(self, thread_id, turns)
    }
    fn foreign(&mut self, row: &Row, turn: &Map) -> bool {
        Engine::foreign(self, row, turn)
    }
    fn valid_interruption(&mut self, row: &Row) -> Py<bool> {
        Engine::valid_interruption(self, row)
    }
    fn loaded(&mut self, thread_id: &str) -> Py<Value> {
        Engine::loaded(self, thread_id)
    }
    fn for_open(&self, row: &Row) -> Py<bool> {
        Engine::for_open(row)
    }
    fn to_session(&self, row: &Row) -> bool {
        Engine::to_session(row)
    }
    fn open_reason(&mut self, row: &Row, loaded: &Value, now: f64) -> Py<Option<String>> {
        Engine::open_reason(self, row, loaded, now)
    }
    fn session_reason(&self, row: &Row, loaded: &Value, now: f64) -> Option<String> {
        Engine::session_reason(self, row, loaded, now)
    }
    fn projection_fresh(&mut self, thread_id: &str) -> Option<bool> {
        Engine::projection_fresh(self, thread_id)
    }
    fn projection_now(&mut self, thread_id: &str) -> Option<bool> {
        Engine::projection_now(self, thread_id)
    }
    fn fresh_throughout(&mut self, thread_id: &str, since: f64) -> bool {
        Engine::fresh_throughout(self, thread_id, since)
    }
    fn observing(&self, settings: &Row) -> bool {
        Engine::observing(self, settings)
    }
    fn waiting_state(&self, row: &Row) -> Py<String> {
        Engine::waiting_state(self, row)
    }
    fn for_open_rests(&mut self, row: &Row) -> Py<bool> {
        Engine::for_open_rests(self, row)
    }
}

impl Engine {
    /// `watch_needed()` (engine/reconcile.py): whether anything may be sitting in Codex's queue right now.
    pub fn watch_needed(&self) -> Py<bool> {
        car_scheduler::watch::watch_needed(self)
    }

    /// `watch()` (engine/reconcile.py): one pass over everything that may be in Codex's queue.
    pub fn watch(&mut self) -> Py<()> {
        car_scheduler::watch::watch(self)
    }

    /// The interruption id of a record, for the callers that name one.
    pub fn key_of(row: &Row) -> String {
        s(row, "interruption_id")
    }
}
