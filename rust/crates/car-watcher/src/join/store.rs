//! car-store's `Store` as car-engine and car-scheduler hold it (moved here from car-harness by S6.2b2: the product's
//! engine is built over it now, and the harness re-exports it).

use std::rc::Rc;

use car_engine::seam::{Claimed, Correlate, Withdrawn};
use car_engine::{Claim, Register};
use car_machine::json::{Map, Value};
use car_machine::pyval::Py;
use car_policy::classify::gates::Vector;
use car_store::Store;
use car_store::records::Update;

fn py<T>(found: car_store::Result<T>) -> Py<T> {
    found.map_err(|error| error.class())
}

/// car-store's `Store` as the engine holds it, shared with the loop (the reference hands the engine the loop's own
/// `Store`). The second field is a test's hook: every claim told to it first (the harness's scripted plug says what
/// it was told of the plug's answers, `note.claim`, which nothing else of a trace shows); the product passes None.
pub struct EngineStore(pub Rc<Store>, pub Option<fn(&Claim)>);

impl car_scheduler::Store for EngineStore {
    fn get(&self, interruption_id: &str) -> Py<Option<Map>> {
        py(self.0.get(interruption_id))
    }
    fn update(
        &self,
        interruption_id: &str,
        changes: &Map,
        at: Option<f64>,
        event: Option<&str>,
        flags: i64,
    ) -> Py<()> {
        let options = Update {
            at,
            actor: "engine".into(),
            event: event.map(str::to_owned),
            flags,
        };
        py(self.0.update(interruption_id, changes, &options))
    }
    fn thread_enabled(&self, thread_id: &str) -> Py<bool> {
        py(self.0.thread_enabled(thread_id))
    }
    fn settings(&self) -> Py<Map> {
        py(self.0.settings())
    }
    fn correlate(
        &self,
        interruption_id: &str,
        recovery_turn_id: &str,
        now: f64,
        options: &Correlate,
    ) -> Py<bool> {
        let options = car_store::claims::Correlate {
            client_id: options.client_id.clone(),
            status: options.status.clone(),
            state: options.state.clone(),
            reason: options.reason.clone(),
            after_user_work: options.after_user_work,
            user_joined: options.user_joined,
            extra_event: options.extra_event.clone(),
        };
        py(self
            .0
            .correlate(interruption_id, recovery_turn_id, now, &options))
    }
    fn release_withdrawn(&self, interruption_id: &str, now: f64, proofs: &Withdrawn) -> Py<bool> {
        let proofs = car_store::claims::Withdrawn {
            window: proofs.window,
            later_turn: proofs.later_turn,
            marker_rows: proofs.marker_rows,
            row_present: proofs.row_present,
            fresh: proofs.fresh,
            target: proofs.target.clone(),
            next_retry_at: proofs.next_retry_at,
        };
        py(self.0.release_withdrawn(interruption_id, now, &proofs))
    }
    fn records_in(&self, states: &[&str], home_key: Option<&str>) -> Py<Vec<Map>> {
        let states: Vec<String> = states.iter().map(|state| (*state).to_owned()).collect();
        py(self.0.records_in(&states, home_key))
    }
}

impl car_engine::Store for EngineStore {
    fn record_gates(&self, interruption_id: &str, gates: &Vector, now: f64) -> Py<()> {
        py(self.0.record_gates(interruption_id, gates, now))
    }
    fn record_would_send(
        &self,
        interruption_id: &str,
        gates: &Vector,
        now: f64,
        next_retry_at: f64,
    ) -> Py<bool> {
        py(self
            .0
            .record_would_send(interruption_id, gates, now, next_retry_at))
    }
    fn submission_guard(
        &self,
        interruption_id: &str,
        body: &mut dyn FnMut(bool) -> Value,
    ) -> Py<Value> {
        py(self.0.submission_guard(interruption_id, body))
    }
    fn recent_claims(&self, thread_id: &str, since: f64) -> Py<Vec<Value>> {
        py(self.0.recent_claims(thread_id, since))
    }
    fn recent_claim_count(&self, thread_id: &str, since: f64) -> Py<i64> {
        py(self.0.recent_claim_count(thread_id, since))
    }
    fn others_in_flight(&self, thread_id: &str, exclude: &str) -> Py<i64> {
        py(self.0.others_in_flight(thread_id, exclude))
    }
    fn reserve_detailed(&self, interruption_id: &str, now: f64, claim: &Claim) -> Py<Claimed> {
        if let Some(note) = self.1 {
            note(claim);
        }
        let options = car_store::claims::Claim {
            plugged: claim.plugged,
            carried: claim.carried.clone(),
            limits: Some(claim.limits.clone()),
            gates: Some(claim.gates.clone()),
            quiet_until: claim.quiet_until,
            relaxed: claim.relaxed.clone(),
            resend: claim.resend,
            forced: claim.forced,
            caps: Some(claim.caps),
        };
        py(self.0.reserve_detailed(interruption_id, now, &options))
    }
    fn release_claim(
        &self,
        interruption_id: &str,
        target: &str,
        reason: &str,
        now: f64,
        next_retry_at: Option<f64>,
    ) -> Py<bool> {
        py(self.0.release_claim(
            interruption_id,
            target,
            reason,
            now,
            next_retry_at,
            "engine",
        ))
    }
    fn claimed_on_thread(&self, thread_id: &str) -> Py<Vec<Map>> {
        py(self.0.claimed_on_thread(thread_id))
    }
    fn chain_parent(
        &self,
        thread_id: &str,
        turn_id: &str,
        owner_id: Option<&str>,
    ) -> Py<Option<Map>> {
        py(self.0.chain_parent(thread_id, turn_id, owner_id))
    }
    fn register(&self, detection: &Map, now: f64, options: &Register) -> Py<bool> {
        let options = car_store::records::Register {
            state: options.state.clone(),
            next_retry_at: Some(options.next_retry_at),
            owner_id: options.owner_id.clone(),
            failed_turn_progress: options.failed_turn_progress.clone(),
            legacy_carry: options.legacy_carry.clone(),
            limits: Some(options.limits.clone()),
            hold: options.hold.clone(),
            task_print: options.task_print.clone(),
            context_tokens: options.context_tokens.clone(),
            home_key: Value::from(options.home_key.as_str()),
        };
        py(self.0.register(detection, now, &options))
    }
    fn thread_tier(&self, thread_id: &str) -> Py<Value> {
        py(self.0.thread_tier(thread_id))
    }
    fn enrol_conversation(&self, thread_id: &str, tier: &str, now: f64) -> Py<bool> {
        py(self
            .0
            .enrol_conversation(thread_id, &Value::from(tier), now))
    }
    fn hold_changed(&self, interruption_id: &str, task_print: &Value, now: f64) -> Py<bool> {
        py(self
            .0
            .hold_changed(interruption_id, task_print, now, "engine"))
    }
    fn hold_waiting(&self, interruption_ids: &[String], hold: &str, now: f64) -> Py<i64> {
        py(self.0.hold_waiting(interruption_ids, hold, now, "engine"))
    }
    fn cancel_waiting(
        &self,
        interruption_ids: &[String],
        now: f64,
        reason: &str,
    ) -> Py<Vec<Value>> {
        let keys: Vec<Value> = interruption_ids
            .iter()
            .map(|key| Value::from(key.as_str()))
            .collect();
        py(self.0.cancel_waiting(&keys, now, reason))
    }
    fn open_objection_window(&self, interruption_id: &str, until: f64, now: f64) -> Py<bool> {
        py(self.0.open_objection_window(interruption_id, until, now))
    }
    fn raise_notice(&self, notice_key: &str, thread_id: &str, kind: &str, now: f64) -> Py<bool> {
        py(self.0.raise_notice(notice_key, thread_id, kind, now))
    }
    fn watcher_status(&self) -> Py<Option<Map>> {
        py(self.0.watcher_status())
    }
    fn usage_checks_asked(&self, now: f64) -> Py<Map> {
        py(self.0.usage_checks_asked(now))
    }
    fn usage_not_checked(&self, interruption_id: &str, now: f64, why: &str) -> Py<()> {
        py(self.0.usage_not_checked(interruption_id, now, why))
    }
    fn usage_check_taken(&self, interruption_id: &str) -> Py<Value> {
        Ok(self
            .0
            .usage_check_taken(interruption_id)
            .map_or(Value::Null, |source| Value::from(source.as_str())))
    }
    fn usage_checked(
        &self,
        interruption_id: &str,
        now: f64,
        read: &str,
        source: &Value,
    ) -> Py<Option<Map>> {
        let source = car_policy::classify::value::text(source).unwrap_or_default();
        py(self.0.usage_checked(interruption_id, now, read, source))
    }
    fn early_check_asked(&self, now: f64) -> Py<bool> {
        Ok(self.0.early_check_asked(now))
    }
    fn early_check_taken(&self) -> Py<()> {
        self.0.early_check_taken();
        Ok(())
    }
}
