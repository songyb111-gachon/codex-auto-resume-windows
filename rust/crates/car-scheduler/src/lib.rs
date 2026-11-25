//! car-scheduler: what became of a continuation that was sent (`engine/reconcile.py`, PLAN 1.2 row 9, seat S4.1).
//!
//! The watch loop, the marker that says a message of ours is in Codex's queue, taking one back, and matching a turn
//! that started to the record that asked for it. This is where a send that may have happened is settled one way or the
//! other - never guessed at.
//!
//! In the reference `ReconcileMixin` is one of the engine's mixins: its methods read `self.store`, `self.source`,
//! `self.backend` and the engine's own helpers. Here it is the trait [`Host`]: what the engine gives the watch is its
//! required methods (car-engine's `Engine` implements them), and the watch itself is its provided methods, written as
//! the reference's are ([`watch`]). The store and the reader are reached through the two small traits below, the part
//! of car-engine's seams this crate reads (cargo's graph gives car-scheduler only car-machine and car-policy).
//!
//! Errors are Python's: an `Err` is the class of the exception the reference would raise, and is caught exactly
//! where the reference catches one.

pub mod watch;

use car_machine::json::{Map, Value};
use car_machine::pyval::Py;

pub use watch::{Reason, SETTLED, Undetermined, settled};

/// `try: body() except Exception: ...` for a panic as well as an error (D15): where the reference catches every
/// exception - one record's look, one send - a panic is caught too and answers as the exception the reference meets
/// there would (`Err("Exception")`), so it costs that record alone and never the tick. car-machine's one catcher.
pub fn caught<T>(body: impl FnOnce() -> Py<T>) -> Py<T> {
    car_machine::caught::caught(body, |_| "Exception")
}

/// A record or a row: a `dict` of Python values.
pub type Row = Map;

/// `store.correlate(...)`'s keywords.
#[derive(Clone, Debug)]
pub struct Correlate {
    pub client_id: Value,
    pub status: Value,
    pub state: String,
    pub reason: Value,
    pub after_user_work: bool,
    pub user_joined: bool,
    pub extra_event: Option<String>,
}

impl Default for Correlate {
    fn default() -> Self {
        Correlate {
            client_id: Value::Null,
            status: Value::Null,
            state: "turn_started".into(),
            reason: Value::Null,
            after_user_work: false,
            user_joined: false,
            extra_event: None,
        }
    }
}

/// `store.release_withdrawn(...)`'s proofs.
#[derive(Clone, Debug)]
pub struct Withdrawn {
    pub window: f64,
    pub later_turn: bool,
    pub marker_rows: i64,
    pub row_present: bool,
    pub fresh: bool,
    pub target: String,
    pub next_retry_at: Option<f64>,
}

/// What the watch reads and writes of the engine's store (the reference's `Store` methods, keyword for keyword).
pub trait Store {
    fn get(&self, interruption_id: &str) -> Py<Option<Row>>;
    /// `update(interruption_id, at=at, actor="engine", event=event, flags=flags, **changes)`.
    fn update(
        &self,
        interruption_id: &str,
        changes: &Row,
        at: Option<f64>,
        event: Option<&str>,
        flags: i64,
    ) -> Py<()>;
    fn thread_enabled(&self, thread_id: &str) -> Py<bool>;
    fn settings(&self) -> Py<Row>;
    fn correlate(
        &self,
        interruption_id: &str,
        recovery_turn_id: &str,
        now: f64,
        options: &Correlate,
    ) -> Py<bool>;
    fn release_withdrawn(&self, interruption_id: &str, now: f64, proofs: &Withdrawn) -> Py<bool>;
    /// `records_in(states, home_key=...)`: `None` is every home's.
    fn records_in(&self, states: &[&str], home_key: Option<&str>) -> Py<Vec<Row>>;
}

/// What the watch reads of Codex (`LocalSource`'s methods).
pub trait Source {
    fn marker_rows(&self, thread_id: &str, marker: &str) -> Py<Vec<Map>>;
    fn queued_rows(&self, thread_id: &str, marker: &str) -> Py<Vec<Map>>;
    fn queue_row(&self, thread_id: &str, queue_id: &str, marker: &str) -> Py<Map>;
    fn later_turns(&self, thread_id: &str, after_ordinal: &Value, marker: &str) -> Py<Vec<Map>>;
    fn foreign_queued(&self, thread_id: &str, marker: &str) -> Py<i64>;
}

/// The engine as the watch sees it: its collaborators, its options, and the helpers of its other mixins.
pub trait Host {
    fn clock(&self) -> f64;
    fn watch_store(&self) -> &dyn Store;
    fn watch_source(&self) -> &dyn Source;
    /// `self.backend.delete_queue(thread, queue_id)`: what it returned (only `True` is a delete).
    fn delete_queue(&self, thread_id: &str, queue_id: &str) -> Py<Value>;
    /// `self.options[name]` for the watch's numbers.
    fn option(&self, name: &str) -> f64;
    /// `with self.dispatch_lock():` - the lock the watcher hands its engines, or none.
    fn dispatch_lock(&self) -> Option<std::sync::Arc<std::sync::Mutex<()>>>;
    /// `_watch_offset`, which each pass moves one record on.
    fn watch_offset(&mut self) -> &mut u64;

    /// `_records(states)`: this engine's own home's records in `states`.
    fn records(&self, states: &[&str]) -> Py<Vec<Row>>;
    /// `proof(row)`: the client id a marker-free continuation was queued under, or its marker.
    fn proof(&self, row: &Row) -> String;
    /// `transition(row, state, reason, delay=..., event=..., **extra)`.
    fn transition(
        &mut self,
        row: &Row,
        state: &str,
        reason: Option<&str>,
        delay: Option<f64>,
        event: Option<&str>,
        extra: Row,
    ) -> Py<()>;
    /// `moved(row, state)` (P14).
    fn moved(&mut self, row: &Row, state: &str);
    /// `log(thread_id, event, detail)`.
    fn log(&mut self, thread_id: Option<&str>, event: &str, detail: Value);
    /// `announce(event, row, **detail)`.
    fn announce(&mut self, event: &str, row: &Row, detail: Row);
    /// `_sighted(key)` (engine/resend.py).
    fn sighted(&mut self, interruption_id: &str);
    /// `self._no_trace.pop(key, None)` (engine/resend.py): a look is being made again.
    fn untraced(&mut self, interruption_id: &str);
    /// `_traceless(row, now)` (engine/resend.py).
    fn traceless(&mut self, row: &Row, now: f64);
    /// `persons_turns(thread, turns)` (engine/plugrecords.py).
    fn persons_turns(&mut self, thread_id: &str, turns: Vec<Map>) -> Vec<Map>;
    /// `foreign(row, turn)` (engine/compaction.py).
    fn foreign(&mut self, row: &Row, turn: &Map) -> bool;
    /// `valid_interruption(row)` (engine/detect.py).
    fn valid_interruption(&mut self, row: &Row) -> Py<bool>;
    /// `loaded(thread_id)` (engine/freshness.py).
    fn loaded(&mut self, thread_id: &str) -> Py<Value>;
    /// `for_open(row)` (engine/foropen.py).
    fn for_open(&self, row: &Row) -> Py<bool>;
    /// `to_session(row)` (engine/tosession.py).
    fn to_session(&self, row: &Row) -> bool;
    /// `_open_reason(row, loaded, now)` (engine/foropen.py).
    fn open_reason(&mut self, row: &Row, loaded: &Value, now: f64) -> Py<Option<String>>;
    /// `_session_reason(row, loaded, now)` (engine/tosession.py).
    fn session_reason(&self, row: &Row, loaded: &Value, now: f64) -> Option<String>;
    /// `projection_fresh(thread_id)` (engine/freshness.py).
    fn projection_fresh(&mut self, thread_id: &str) -> Option<bool>;
    /// `_projection_now(thread_id)` (engine/freshness.py).
    fn projection_now(&mut self, thread_id: &str) -> Option<bool>;
    /// `fresh_throughout(thread_id, since)` (engine/freshness.py).
    fn fresh_throughout(&mut self, thread_id: &str, since: f64) -> bool;
    /// `observing(settings)` (engine/options.py).
    fn observing(&self, settings: &Row) -> bool;
    /// `waiting_state(row)` (engine/detect.py).
    fn waiting_state(&self, row: &Row) -> Py<String>;
    /// `_for_open_rests(row)` (engine/foropen.py).
    fn for_open_rests(&mut self, row: &Row) -> Py<bool>;
}
