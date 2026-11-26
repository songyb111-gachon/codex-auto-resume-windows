//! What the engine is handed: its store, its reader of Codex, its backend, and the few things of the watcher's it asks.
//!
//! The reference engine is handed duck-typed objects (`Engine(store, source, backend, ...)`) and imports none of
//! their modules (`tests/test_stack.py` EDGES: engine reaches codex, machine, policy, scheduler and words only). Here
//! each is a trait, keyword for keyword the methods the engine calls, so that:
//!
//! * [`Store`] - car-store's `Store` is implemented over it by whoever holds both (the harness's `EngineStore` today,
//!   car-watcher at its seat): cargo gives car-engine no edge to car-store, as the reference has none.
//! * [`Source`] - implemented here for car-codex's [`LocalSource`] (an edge the graph allows), and by any stand-in.
//! * [`Backend`] - the S3.3 seam: `codex/transport.py`, `appserver.py` and `pairing.py` are being ported beside this
//!   seat (car-v0627-appserver). Every call and attribute the engine reads of the reference's `Backend` is a method
//!   here, an attribute the reference reads with `getattr(backend, name, default)` a method whose default is that
//!   default. The integration seat implements it over S3.3's types.
//! * [`OnceWords`] - `control/oncewords.py`'s file of a person's words for this time (car-control's, later).
//!
//! Every method answers `Py`: the class of the exception the reference would raise, caught where it catches one.

use std::collections::BTreeSet;

use car_codex::source::LocalSource;
use car_machine::json::{Map, Str, Value};
use car_machine::pyval::Py;
use car_policy::classify::gates::{Limits, Vector};
use car_policy::plug::Point;

pub use car_scheduler::{Correlate, Row, Withdrawn};

/// `store.reserve_detailed(...)`'s keywords. `ledger` is the engine's plug - here `plugged`, whether it is not NULL's
/// (`not ledger.null`), which decides every plug branch of the claim - and `carried` what the send carries of its
/// answers, which its ledger pays for (P11, which car-store does not ask: S7.2's).
#[derive(Clone, Debug)]
pub struct Claim {
    pub plugged: bool,
    pub limits: Limits,
    pub gates: Vector,
    pub carried: BTreeSet<Point>,
    pub quiet_until: Option<f64>,
    pub relaxed: Option<String>,
    pub resend: Option<(f64, f64)>,
    pub forced: bool,
    pub caps: (f64, f64),
}

/// `store.register(detection, now, ...)`'s keywords.
#[derive(Clone, Debug)]
pub struct Register {
    pub state: String,
    pub next_retry_at: f64,
    pub owner_id: Option<String>,
    pub failed_turn_progress: Value,
    pub legacy_carry: Value,
    pub limits: Limits,
    pub hold: Value,
    pub home_key: String,
    pub task_print: Value,
    pub context_tokens: Value,
}

/// (claimed, refusing gate, reason).
pub type Claimed = (bool, Option<String>, Option<String>);

/// The engine's store: the reference's `Store` methods the engine calls, beyond the watch's.
pub trait Store: car_scheduler::Store {
    fn record_gates(&self, interruption_id: &str, gates: &Vector, now: f64) -> Py<()>;
    fn record_would_send(
        &self,
        interruption_id: &str,
        gates: &Vector,
        now: f64,
        next_retry_at: f64,
    ) -> Py<bool>;
    /// `with store.submission_guard(key) as permitted:` - `body` runs inside the write lock.
    fn submission_guard(
        &self,
        interruption_id: &str,
        body: &mut dyn FnMut(bool) -> Value,
    ) -> Py<Value>;
    fn recent_claims(&self, thread_id: &str, since: f64) -> Py<Vec<Value>>;
    fn recent_claim_count(&self, thread_id: &str, since: f64) -> Py<i64>;
    fn others_in_flight(&self, thread_id: &str, exclude: &str) -> Py<i64>;
    fn reserve_detailed(&self, interruption_id: &str, now: f64, claim: &Claim) -> Py<Claimed>;
    fn release_claim(
        &self,
        interruption_id: &str,
        target: &str,
        reason: &str,
        now: f64,
        next_retry_at: Option<f64>,
    ) -> Py<bool>;
    fn claimed_on_thread(&self, thread_id: &str) -> Py<Vec<Row>>;
    fn chain_parent(
        &self,
        thread_id: &str,
        turn_id: &str,
        owner_id: Option<&str>,
    ) -> Py<Option<Row>>;
    fn register(&self, detection: &Row, now: f64, options: &Register) -> Py<bool>;
    fn thread_tier(&self, thread_id: &str) -> Py<Value>;
    fn enrol_conversation(&self, thread_id: &str, tier: &str, now: f64) -> Py<bool>;
    fn hold_changed(&self, interruption_id: &str, task_print: &Value, now: f64) -> Py<bool>;
    fn hold_waiting(&self, interruption_ids: &[String], hold: &str, now: f64) -> Py<i64>;
    fn cancel_waiting(&self, interruption_ids: &[String], now: f64, reason: &str)
    -> Py<Vec<Value>>;
    fn open_objection_window(&self, interruption_id: &str, until: f64, now: f64) -> Py<bool>;
    fn raise_notice(&self, notice_key: &str, thread_id: &str, kind: &str, now: f64) -> Py<bool>;
    fn watcher_status(&self) -> Py<Option<Row>>;
    fn usage_checks_asked(&self, now: f64) -> Py<Row>;
    fn usage_not_checked(&self, interruption_id: &str, now: f64, why: &str) -> Py<()>;
    fn usage_check_taken(&self, interruption_id: &str) -> Py<Value>;
    fn usage_checked(
        &self,
        interruption_id: &str,
        now: f64,
        read: &str,
        source: &Value,
    ) -> Py<Option<Row>>;
    fn early_check_asked(&self, now: f64) -> Py<bool>;
    fn early_check_taken(&self) -> Py<()>;
}

/// The engine's reader of Codex: `LocalSource`'s methods the engine calls, beyond the watch's.
pub trait Source: car_scheduler::Source {
    fn latest(&self, thread_id: &str) -> Py<Option<Map>>;
    fn progress(&self, thread_id: &str, after_ordinal: &Value) -> Py<Map>;
    /// `latest_failures(since, needs_you=..., admissible=..., shapes=...)`.
    fn latest_failures(
        &self,
        since: f64,
        needs_you: &[&str],
        admissible: bool,
        shapes: bool,
    ) -> Py<Vec<Map>>;
    fn passed_over(&self, since: f64, before: f64, known: &BTreeSet<String>) -> Py<Map>;
    fn reset_hint(&self, thread_id: &str, turn_id: &str) -> Py<Map>;
    fn turn_markers(&self, thread_id: &str, turn_id: &str, markers: &[String]) -> Py<Vec<String>>;
    fn turn_progress(&self, thread_id: &str, turn_id: &str) -> Py<Option<bool>>;
    fn turn_observation(&self, thread_id: &str, turn_id: &str, marker: &str) -> Py<Map>;
    fn marker_presence(&self, thread_id: &str, marker: &str) -> Py<Map>;
    fn projection(&self, thread_id: &str) -> Py<Map>;
    fn project_key(&self, thread_id: &str) -> Py<Option<String>>;
    fn task_facts(&self, thread_id: &str, fingerprint: bool, tokens: bool) -> Py<Map>;
    fn stalled_turns(&self, since: f64, quiet_seconds: f64, now: f64) -> Py<Vec<Map>>;
    fn activity(&self, threads: &[String], now: f64, booted: &Value) -> Py<Map>;
    fn newer_than_engine(
        &self,
        thread_id: &str,
        kinds: &BTreeSet<String>,
        engine_version: &Value,
    ) -> Py<bool>;
    fn taken(
        &self,
        thread_id: &str,
        kinds: &BTreeSet<String>,
        widened: &BTreeSet<String>,
    ) -> Py<bool>;
    /// `source.session_kinds = kinds; source.widened = widened` (engine/kinds.py).
    fn set_kinds(&mut self, kinds: &BTreeSet<String>, widened: &BTreeSet<String>);
}

/// The launch guard a send is handed (`store.submission_guard(key)`): entered once, `body` run with whether the
/// launch is permitted, inside the store's write lock. The launch itself is the body: a backend starts `codex queue`
/// inside it, as codex/transport.py does inside `with launch_guard as permitted:`, so a Cancel, a Pause or a
/// conversation switched off that commits a moment before cannot be launched past. A backend that reads the permission
/// and launches after `enter` returns sends under a doubt the reference holds.
pub trait LaunchGuard {
    fn enter(&self, body: &mut dyn FnMut(bool) -> Value) -> Py<Value>;
    /// The record whose `store.submission_guard(key)` this is, where there is one: what a backend that is handed the
    /// reference's own guard object (the scenario proxy's, asked back over a pipe) builds it from.
    fn key(&self) -> Option<&str> {
        None
    }
}

/// The Codex processes: `codex queue`, the App Server's queue delete, the loaded-thread inventory and the usage probe
/// (`codex/transport.py` `Backend`, S3.3's). The defaults are what `getattr(backend, name, default)` reads of a backend
/// without that attribute.
pub trait Backend {
    /// `app_identity()`: the app's process identity, or `None` (`Value::Null`).
    fn app_identity(&self) -> Py<Value>;
    /// `loaded(thread_id, app_identity)`: "loaded", "notLoaded", "elsewhere" or "unknown".
    fn loaded(&self, thread_id: &str, app_identity: &Value) -> Py<Value>;
    /// `usage()`: `{"available", "reset_at", "limit_type", "reason"}`.
    fn usage(&self) -> Py<Value>;
    /// `send(thread_id, prompt, launch_guard=...)`: `{"outcome", ...}` (anything else is unknown).
    fn send(&self, thread_id: &str, prompt: &Str, launch_guard: &dyn LaunchGuard) -> Py<Value>;
    /// `delete_queue(thread_id, queue_id)`: only `True` is a delete.
    fn delete_queue(&self, thread_id: &str, queue_id: &str) -> Py<Value>;
    /// `app_look` (#58's follow-up): "unmatched" where the last look found the app's process and no server.
    fn app_look(&self) -> Value {
        Value::Null
    }
    /// `app_unmatched_reason` (v0.6.26).
    fn app_unmatched_reason(&self) -> Value {
        Value::Null
    }
    /// `protocol_results` (v0.6.26): method -> (result, time) of the helper's last answers.
    fn protocol_results(&self) -> Value {
        Value::Null
    }
    /// `session_holder` (v0.6.16-beta.4): the pid and creation time of the session `loaded` found holding a
    /// conversation elsewhere.
    fn session_holder(&self) -> Value {
        Value::Null
    }
    /// `engine_version`: the engine's `codex --version`.
    fn engine_version(&self) -> Value {
        Value::Null
    }
    /// `holder(thread_id)`, or `None` for a backend with no such call (then "unknown").
    fn holder(&self, _thread_id: &str) -> Option<Py<Value>> {
        None
    }
}

/// One backend held by the engine and by whoever built it (the watcher's App keeps `self._backend` beside the engine
/// that drives it: the evaluator, the layout watch and `engine_moved` read the same object).
impl<T: Backend + ?Sized> Backend for std::sync::Arc<T> {
    fn app_identity(&self) -> Py<Value> {
        (**self).app_identity()
    }
    fn loaded(&self, thread_id: &str, app_identity: &Value) -> Py<Value> {
        (**self).loaded(thread_id, app_identity)
    }
    fn usage(&self) -> Py<Value> {
        (**self).usage()
    }
    fn send(&self, thread_id: &str, prompt: &Str, launch_guard: &dyn LaunchGuard) -> Py<Value> {
        (**self).send(thread_id, prompt, launch_guard)
    }
    fn delete_queue(&self, thread_id: &str, queue_id: &str) -> Py<Value> {
        (**self).delete_queue(thread_id, queue_id)
    }
    fn app_look(&self) -> Value {
        (**self).app_look()
    }
    fn app_unmatched_reason(&self) -> Value {
        (**self).app_unmatched_reason()
    }
    fn protocol_results(&self) -> Value {
        (**self).protocol_results()
    }
    fn session_holder(&self) -> Value {
        (**self).session_holder()
    }
    fn engine_version(&self) -> Value {
        (**self).engine_version()
    }
    fn holder(&self, thread_id: &str) -> Option<Py<Value>> {
        (**self).holder(thread_id)
    }
}

/// A person's words for this time (`control/oncewords.py`'s `OnceWords`).
pub trait OnceWords {
    fn words(&self, interruption_id: &str) -> Py<Value>;
    /// True, False, or None for a file that cannot be had.
    fn unchanged(&self, interruption_id: &str, seen: &Value) -> Py<Value>;
    fn remove(&self, interruption_id: &str) -> Py<Value>;
    fn restore(&self, interruption_id: &str, words: &Value) -> Py<()>;
    /// `prune(keep)`: every entry `keep` refuses is deleted; an error of `keep` ends the prune with it.
    fn prune(&self, keep: &mut dyn FnMut(&str) -> Py<bool>) -> Py<()>;
}

fn codex<T>(found: car_codex::errors::Result<T>) -> Py<T> {
    found.map_err(|error| error.class())
}

fn set(words: &[&str]) -> BTreeSet<String> {
    words.iter().map(|word| (*word).to_owned()).collect()
}

/// car-codex's reader as the engine holds it (a type of this crate, so both traits may be implemented for it).
pub struct Codex(pub LocalSource);

impl car_scheduler::Source for Codex {
    fn marker_rows(&self, thread_id: &str, marker: &str) -> Py<Vec<Map>> {
        codex(LocalSource::marker_rows(&self.0, thread_id, marker))
    }
    fn queued_rows(&self, thread_id: &str, marker: &str) -> Py<Vec<Map>> {
        codex(LocalSource::queued_rows(&self.0, thread_id, marker))
    }
    fn queue_row(&self, thread_id: &str, queue_id: &str, marker: &str) -> Py<Map> {
        codex(LocalSource::queue_row(&self.0, thread_id, queue_id, marker))
    }
    fn later_turns(&self, thread_id: &str, after_ordinal: &Value, marker: &str) -> Py<Vec<Map>> {
        codex(LocalSource::later_turns(
            &self.0,
            thread_id,
            after_ordinal,
            marker,
        ))
    }
    fn foreign_queued(&self, thread_id: &str, marker: &str) -> Py<i64> {
        codex(LocalSource::foreign_queued(&self.0, thread_id, marker))
    }
}

impl Source for Codex {
    fn latest(&self, thread_id: &str) -> Py<Option<Map>> {
        codex(LocalSource::latest(&self.0, thread_id))
    }
    fn progress(&self, thread_id: &str, after_ordinal: &Value) -> Py<Map> {
        codex(LocalSource::progress(&self.0, thread_id, after_ordinal))
    }
    fn latest_failures(
        &self,
        since: f64,
        needs_you: &[&str],
        admissible: bool,
        shapes: bool,
    ) -> Py<Vec<Map>> {
        codex(LocalSource::latest_failures(
            &self.0,
            &Value::Float(since),
            &set(needs_you),
            admissible,
            shapes,
        ))
    }
    fn passed_over(&self, since: f64, before: f64, known: &BTreeSet<String>) -> Py<Map> {
        codex(LocalSource::passed_over(
            &self.0,
            &Value::Float(since),
            &Value::Float(before),
            false,
            known,
            None,
            None,
        ))
    }
    fn reset_hint(&self, thread_id: &str, turn_id: &str) -> Py<Map> {
        codex(LocalSource::reset_hint(&self.0, thread_id, turn_id))
    }
    fn turn_markers(&self, thread_id: &str, turn_id: &str, markers: &[String]) -> Py<Vec<String>> {
        codex(LocalSource::turn_markers(
            &self.0, thread_id, turn_id, markers,
        ))
    }
    fn turn_progress(&self, thread_id: &str, turn_id: &str) -> Py<Option<bool>> {
        codex(LocalSource::turn_progress(&self.0, thread_id, turn_id))
    }
    fn turn_observation(&self, thread_id: &str, turn_id: &str, marker: &str) -> Py<Map> {
        codex(LocalSource::turn_observation(
            &self.0, thread_id, turn_id, marker,
        ))
    }
    fn marker_presence(&self, thread_id: &str, marker: &str) -> Py<Map> {
        codex(LocalSource::marker_presence(&self.0, thread_id, marker))
    }
    fn projection(&self, thread_id: &str) -> Py<Map> {
        codex(LocalSource::projection(&self.0, thread_id))
    }
    fn project_key(&self, thread_id: &str) -> Py<Option<String>> {
        codex(LocalSource::project_key(&self.0, thread_id))
    }
    fn task_facts(&self, thread_id: &str, fingerprint: bool, tokens: bool) -> Py<Map> {
        codex(LocalSource::task_facts(
            &self.0,
            thread_id,
            fingerprint,
            tokens,
        ))
    }
    fn stalled_turns(&self, since: f64, quiet_seconds: f64, now: f64) -> Py<Vec<Map>> {
        codex(LocalSource::stalled_turns(
            &self.0,
            &Value::Float(since),
            &Value::Float(quiet_seconds),
            &Value::Float(now),
        ))
    }
    fn activity(&self, threads: &[String], now: f64, booted: &Value) -> Py<Map> {
        codex(LocalSource::activity(
            &self.0,
            threads,
            &Value::Float(now),
            &Value::Float(3600.0),
            booted,
        ))
    }
    fn newer_than_engine(
        &self,
        thread_id: &str,
        kinds: &BTreeSet<String>,
        engine_version: &Value,
    ) -> Py<bool> {
        codex(LocalSource::newer_than_engine(
            &self.0,
            thread_id,
            kinds,
            engine_version,
        ))
    }
    fn taken(
        &self,
        thread_id: &str,
        kinds: &BTreeSet<String>,
        widened: &BTreeSet<String>,
    ) -> Py<bool> {
        codex(LocalSource::taken(&self.0, thread_id, kinds, Some(widened)))
    }
    fn set_kinds(&mut self, kinds: &BTreeSet<String>, widened: &BTreeSet<String>) {
        self.0.session_kinds = kinds.clone();
        self.0.widened = widened.clone();
    }
}
