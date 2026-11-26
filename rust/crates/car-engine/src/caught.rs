//! D15 inside the engine (review 6, S1): every seam wrapped so that a panic inside it - S3.3's transport, car-codex,
//! car-store, a person's words file - is the exception the reference meets at that call (`Err("Exception")`), and the
//! engine handles it exactly where the reference's `try`/`except` does: a read that fails is unknown, a send that fails
//! is `{"outcome": "unknown"}`, a record's look that fails costs that record alone. Generated from the seam traits
//! (`seam.rs`, car-scheduler's `Store`/`Source`); `Engine::new` wraps what it is handed.

use car_machine::caught::catch;
use std::collections::BTreeSet;

use car_machine::json::{Map, Str, Value};
use car_machine::pyval::Py;
use car_policy::classify::gates::Vector;

use crate::seam::{
    Backend, Claim, Claimed, Correlate, LaunchGuard, OnceWords, Register, Row, Source, Store,
    Withdrawn,
};

/// A seam whose panics are its exceptions.
pub struct Caught<T: ?Sized>(pub Box<T>);

impl car_scheduler::Store for Caught<dyn Store> {
    fn get(&self, interruption_id: &str) -> Py<Option<Row>> {
        car_scheduler::caught(|| self.0.get(interruption_id))
    }
    fn update(
        &self,
        interruption_id: &str,
        changes: &Row,
        at: Option<f64>,
        event: Option<&str>,
        flags: i64,
    ) -> Py<()> {
        car_scheduler::caught(|| self.0.update(interruption_id, changes, at, event, flags))
    }
    fn thread_enabled(&self, thread_id: &str) -> Py<bool> {
        car_scheduler::caught(|| self.0.thread_enabled(thread_id))
    }
    fn settings(&self) -> Py<Row> {
        car_scheduler::caught(|| self.0.settings())
    }
    fn correlate(
        &self,
        interruption_id: &str,
        recovery_turn_id: &str,
        now: f64,
        options: &Correlate,
    ) -> Py<bool> {
        car_scheduler::caught(|| {
            self.0
                .correlate(interruption_id, recovery_turn_id, now, options)
        })
    }
    fn release_withdrawn(&self, interruption_id: &str, now: f64, proofs: &Withdrawn) -> Py<bool> {
        car_scheduler::caught(|| self.0.release_withdrawn(interruption_id, now, proofs))
    }
    fn records_in(&self, states: &[&str], home_key: Option<&str>) -> Py<Vec<Row>> {
        car_scheduler::caught(|| self.0.records_in(states, home_key))
    }
}

impl Store for Caught<dyn Store> {
    fn errand_guard(
        &self,
        held: &mut dyn FnMut() -> Py<bool>,
        body: &mut dyn FnMut(bool) -> Value,
    ) -> Py<Value> {
        car_scheduler::caught(|| self.0.errand_guard(held, body))
    }
    fn record_gates(&self, interruption_id: &str, gates: &Vector, now: f64) -> Py<()> {
        car_scheduler::caught(|| self.0.record_gates(interruption_id, gates, now))
    }
    fn record_would_send(
        &self,
        interruption_id: &str,
        gates: &Vector,
        now: f64,
        next_retry_at: f64,
    ) -> Py<bool> {
        car_scheduler::caught(|| {
            self.0
                .record_would_send(interruption_id, gates, now, next_retry_at)
        })
    }
    fn submission_guard(
        &self,
        interruption_id: &str,
        body: &mut dyn FnMut(bool) -> Value,
    ) -> Py<Value> {
        car_scheduler::caught(|| self.0.submission_guard(interruption_id, body))
    }
    fn recent_claims(&self, thread_id: &str, since: f64) -> Py<Vec<Value>> {
        car_scheduler::caught(|| self.0.recent_claims(thread_id, since))
    }
    fn recent_claim_count(&self, thread_id: &str, since: f64) -> Py<i64> {
        car_scheduler::caught(|| self.0.recent_claim_count(thread_id, since))
    }
    fn others_in_flight(&self, thread_id: &str, exclude: &str) -> Py<i64> {
        car_scheduler::caught(|| self.0.others_in_flight(thread_id, exclude))
    }
    fn reserve_detailed(&self, interruption_id: &str, now: f64, claim: &Claim) -> Py<Claimed> {
        car_scheduler::caught(|| self.0.reserve_detailed(interruption_id, now, claim))
    }
    fn reserve_ledgered(
        &self,
        interruption_id: &str,
        now: f64,
        claim: &Claim,
        ledger: &car_policy::plug::Guarded,
    ) -> Py<Claimed> {
        car_scheduler::caught(|| self.0.reserve_ledgered(interruption_id, now, claim, ledger))
    }
    fn reserve_record(
        &self,
        record: &Map,
        now: f64,
        ledger: &car_policy::plug::Guarded,
        quiet_until: Option<f64>,
    ) -> Py<Claimed> {
        car_scheduler::caught(|| self.0.reserve_record(record, now, ledger, quiet_until))
    }
    fn record_guard(
        &self,
        record: &Map,
        ledger: &car_policy::plug::Guarded,
        now: f64,
        body: &mut dyn FnMut(bool) -> Value,
    ) -> Py<Value> {
        car_scheduler::caught(|| self.0.record_guard(record, ledger, now, body))
    }
    fn release_claim(
        &self,
        interruption_id: &str,
        target: &str,
        reason: &str,
        now: f64,
        next_retry_at: Option<f64>,
    ) -> Py<bool> {
        car_scheduler::caught(|| {
            self.0
                .release_claim(interruption_id, target, reason, now, next_retry_at)
        })
    }
    fn claimed_on_thread(&self, thread_id: &str) -> Py<Vec<Row>> {
        car_scheduler::caught(|| self.0.claimed_on_thread(thread_id))
    }
    fn chain_parent(
        &self,
        thread_id: &str,
        turn_id: &str,
        owner_id: Option<&str>,
    ) -> Py<Option<Row>> {
        car_scheduler::caught(|| self.0.chain_parent(thread_id, turn_id, owner_id))
    }
    fn register(&self, detection: &Row, now: f64, options: &Register) -> Py<bool> {
        car_scheduler::caught(|| self.0.register(detection, now, options))
    }
    fn thread_tier(&self, thread_id: &str) -> Py<Value> {
        car_scheduler::caught(|| self.0.thread_tier(thread_id))
    }
    fn enrol_conversation(&self, thread_id: &str, tier: &str, now: f64) -> Py<bool> {
        car_scheduler::caught(|| self.0.enrol_conversation(thread_id, tier, now))
    }
    fn hold_changed(&self, interruption_id: &str, task_print: &Value, now: f64) -> Py<bool> {
        car_scheduler::caught(|| self.0.hold_changed(interruption_id, task_print, now))
    }
    fn hold_waiting(&self, interruption_ids: &[String], hold: &str, now: f64) -> Py<i64> {
        car_scheduler::caught(|| self.0.hold_waiting(interruption_ids, hold, now))
    }
    fn cancel_waiting(
        &self,
        interruption_ids: &[String],
        now: f64,
        reason: &str,
    ) -> Py<Vec<Value>> {
        car_scheduler::caught(|| self.0.cancel_waiting(interruption_ids, now, reason))
    }
    fn open_objection_window(&self, interruption_id: &str, until: f64, now: f64) -> Py<bool> {
        car_scheduler::caught(|| self.0.open_objection_window(interruption_id, until, now))
    }
    fn raise_notice(&self, notice_key: &str, thread_id: &str, kind: &str, now: f64) -> Py<bool> {
        car_scheduler::caught(|| self.0.raise_notice(notice_key, thread_id, kind, now))
    }
    fn watcher_status(&self) -> Py<Option<Row>> {
        car_scheduler::caught(|| self.0.watcher_status())
    }
    fn usage_checks_asked(&self, now: f64) -> Py<Row> {
        car_scheduler::caught(|| self.0.usage_checks_asked(now))
    }
    fn usage_not_checked(&self, interruption_id: &str, now: f64, why: &str) -> Py<()> {
        car_scheduler::caught(|| self.0.usage_not_checked(interruption_id, now, why))
    }
    fn usage_check_taken(&self, interruption_id: &str) -> Py<Value> {
        car_scheduler::caught(|| self.0.usage_check_taken(interruption_id))
    }
    fn usage_checked(
        &self,
        interruption_id: &str,
        now: f64,
        read: &str,
        source: &Value,
    ) -> Py<Option<Row>> {
        car_scheduler::caught(|| self.0.usage_checked(interruption_id, now, read, source))
    }
    fn early_check_asked(&self, now: f64) -> Py<bool> {
        car_scheduler::caught(|| self.0.early_check_asked(now))
    }
    fn early_check_taken(&self) -> Py<()> {
        car_scheduler::caught(|| self.0.early_check_taken())
    }
}

impl car_scheduler::Source for Caught<dyn Source> {
    fn marker_rows(&self, thread_id: &str, marker: &str) -> Py<Vec<Map>> {
        car_scheduler::caught(|| self.0.marker_rows(thread_id, marker))
    }
    fn queued_rows(&self, thread_id: &str, marker: &str) -> Py<Vec<Map>> {
        car_scheduler::caught(|| self.0.queued_rows(thread_id, marker))
    }
    fn queue_row(&self, thread_id: &str, queue_id: &str, marker: &str) -> Py<Map> {
        car_scheduler::caught(|| self.0.queue_row(thread_id, queue_id, marker))
    }
    fn later_turns(&self, thread_id: &str, after_ordinal: &Value, marker: &str) -> Py<Vec<Map>> {
        car_scheduler::caught(|| self.0.later_turns(thread_id, after_ordinal, marker))
    }
    fn foreign_queued(&self, thread_id: &str, marker: &str) -> Py<i64> {
        car_scheduler::caught(|| self.0.foreign_queued(thread_id, marker))
    }
}

impl Source for Caught<dyn Source> {
    fn latest(&self, thread_id: &str) -> Py<Option<Map>> {
        car_scheduler::caught(|| self.0.latest(thread_id))
    }
    fn progress(&self, thread_id: &str, after_ordinal: &Value) -> Py<Map> {
        car_scheduler::caught(|| self.0.progress(thread_id, after_ordinal))
    }
    fn latest_failures(
        &self,
        since: f64,
        needs_you: &[&str],
        admissible: bool,
        shapes: bool,
    ) -> Py<Vec<Map>> {
        car_scheduler::caught(|| self.0.latest_failures(since, needs_you, admissible, shapes))
    }
    fn passed_over(&self, since: f64, before: f64, known: &BTreeSet<String>) -> Py<Map> {
        car_scheduler::caught(|| self.0.passed_over(since, before, known))
    }
    fn reset_hint(&self, thread_id: &str, turn_id: &str) -> Py<Map> {
        car_scheduler::caught(|| self.0.reset_hint(thread_id, turn_id))
    }
    fn turn_markers(&self, thread_id: &str, turn_id: &str, markers: &[String]) -> Py<Vec<String>> {
        car_scheduler::caught(|| self.0.turn_markers(thread_id, turn_id, markers))
    }
    fn turn_progress(&self, thread_id: &str, turn_id: &str) -> Py<Option<bool>> {
        car_scheduler::caught(|| self.0.turn_progress(thread_id, turn_id))
    }
    fn turn_observation(&self, thread_id: &str, turn_id: &str, marker: &str) -> Py<Map> {
        car_scheduler::caught(|| self.0.turn_observation(thread_id, turn_id, marker))
    }
    fn marker_presence(&self, thread_id: &str, marker: &str) -> Py<Map> {
        car_scheduler::caught(|| self.0.marker_presence(thread_id, marker))
    }
    fn projection(&self, thread_id: &str) -> Py<Map> {
        car_scheduler::caught(|| self.0.projection(thread_id))
    }
    fn project_key(&self, thread_id: &str) -> Py<Option<String>> {
        car_scheduler::caught(|| self.0.project_key(thread_id))
    }
    fn task_facts(&self, thread_id: &str, fingerprint: bool, tokens: bool) -> Py<Map> {
        car_scheduler::caught(|| self.0.task_facts(thread_id, fingerprint, tokens))
    }
    fn stalled_turns(&self, since: f64, quiet_seconds: f64, now: f64) -> Py<Vec<Map>> {
        car_scheduler::caught(|| self.0.stalled_turns(since, quiet_seconds, now))
    }
    fn activity(&self, threads: &[String], now: f64, booted: &Value) -> Py<Map> {
        car_scheduler::caught(|| self.0.activity(threads, now, booted))
    }
    fn newer_than_engine(
        &self,
        thread_id: &str,
        kinds: &BTreeSet<String>,
        engine_version: &Value,
    ) -> Py<bool> {
        car_scheduler::caught(|| self.0.newer_than_engine(thread_id, kinds, engine_version))
    }
    fn taken(
        &self,
        thread_id: &str,
        kinds: &BTreeSet<String>,
        widened: &BTreeSet<String>,
    ) -> Py<bool> {
        car_scheduler::caught(|| self.0.taken(thread_id, kinds, widened))
    }
    fn set_kinds(&mut self, kinds: &BTreeSet<String>, widened: &BTreeSet<String>) {
        let inner = &mut self.0;
        let _ = catch(|| inner.set_kinds(kinds, widened));
    }
}

impl Backend for Caught<dyn Backend> {
    fn app_identity(&self) -> Py<Value> {
        car_scheduler::caught(|| self.0.app_identity())
    }
    fn loaded(&self, thread_id: &str, app_identity: &Value) -> Py<Value> {
        car_scheduler::caught(|| self.0.loaded(thread_id, app_identity))
    }
    fn usage(&self) -> Py<Value> {
        car_scheduler::caught(|| self.0.usage())
    }
    fn send(&self, thread_id: &str, prompt: &Str, launch_guard: &dyn LaunchGuard) -> Py<Value> {
        car_scheduler::caught(|| self.0.send(thread_id, prompt, launch_guard))
    }
    fn delete_queue(&self, thread_id: &str, queue_id: &str) -> Py<Value> {
        car_scheduler::caught(|| self.0.delete_queue(thread_id, queue_id))
    }
    fn app_look(&self) -> Value {
        catch(|| self.0.app_look()).unwrap_or(Value::Null)
    }
    fn app_unmatched_reason(&self) -> Value {
        catch(|| self.0.app_unmatched_reason()).unwrap_or(Value::Null)
    }
    fn protocol_results(&self) -> Value {
        catch(|| self.0.protocol_results()).unwrap_or(Value::Null)
    }
    fn session_holder(&self) -> Value {
        catch(|| self.0.session_holder()).unwrap_or(Value::Null)
    }
    fn engine_version(&self) -> Value {
        catch(|| self.0.engine_version()).unwrap_or(Value::Null)
    }
    fn holder(&self, _thread_id: &str) -> Option<Py<Value>> {
        catch(|| self.0.holder(_thread_id)).unwrap_or(Some(Err("Exception")))
    }
}

impl OnceWords for Caught<dyn OnceWords> {
    fn words(&self, interruption_id: &str) -> Py<Value> {
        car_scheduler::caught(|| self.0.words(interruption_id))
    }
    fn unchanged(&self, interruption_id: &str, seen: &Value) -> Py<Value> {
        car_scheduler::caught(|| self.0.unchanged(interruption_id, seen))
    }
    fn remove(&self, interruption_id: &str) -> Py<Value> {
        car_scheduler::caught(|| self.0.remove(interruption_id))
    }
    fn restore(&self, interruption_id: &str, words: &Value) -> Py<()> {
        car_scheduler::caught(|| self.0.restore(interruption_id, words))
    }
    fn prune(&self, keep: &mut dyn FnMut(&str) -> Py<bool>) -> Py<()> {
        car_scheduler::caught(|| self.0.prune(keep))
    }
}
