//! An uncertain continuation sent once more (v0.6.14 stage 3b), where the edition's plug asks and core proves it may
//! (`engine/resend.py`).
//!
//! Core never sends a continuation again once it may have been delivered (A6). The edition's plug may answer RESEND at
//! P7 for one a look of the watch has just found no trace of, and core carries it out itself, once, only where it
//! proves every condition; otherwise it writes nothing. The standard edition's plug never answers RESEND, and nothing
//! here runs for it: `sighted`, `traceless` and `watch_resent` return at once for NULL.

use car_machine::json::Value;
use car_machine::pyval::Py;
use car_machine::vocab_gen::domain_states::{OBSERVING, OUTCOMES};
use car_policy::classify::failures::{self, USAGE_LIMIT};
use car_policy::classify::gates::{
    PASS, RESEND, Vector, gate, gate_budgets, gate_consent, gate_schedule, resend_candidate,
    was_resent,
};
use car_policy::plug::{Alternative, Answer};

use crate::dispatch::vector_value;
use crate::options::limits_of;
use crate::py::{self, field, get, s, text_of, truthy, with};
use crate::{Engine, Row};

/// How many records the memory of sightings - and of looks that found no trace - holds before it is emptied.
pub const REMEMBERED: usize = 4096;
/// How often a resent record that ran is looked at for a second copy of its proof, at most.
pub const DUPLICATE_LOOK_SECONDS: f64 = 60.0;
/// The engine states a send may go on in.
pub const COMPATIBLE: &[&str] = &["verified", "checked", "structurally_compatible"];
const BUDGETS: &[&str] = &["chain_budget", "attempt_budget", "no_progress_budget"];

impl Engine {
    /// `resend_window()`: (after, until) - how long after its send an uncertain submission may be resent.
    pub fn resend_window(&self) -> (f64, f64) {
        (
            self.options.resend_after_seconds,
            self.options.resend_until_seconds,
        )
    }

    /// `_sighted(key)`: a record's proof was seen in Codex's queue: it is never resent after.
    pub fn sighted(&mut self, key: &str) {
        if self.plug.is_null() {
            return;
        }
        if self.seen_queued.len() >= REMEMBERED {
            self.seen_queued.clear();
            self.seen_queued_cleared_at = self.now();
        }
        self.seen_queued.insert(key.to_owned());
    }

    /// `_traceless(row, now)`: the watch found an uncertain submission's proof nowhere.
    pub fn traceless(&mut self, row: &Row, now: f64) {
        if self.plug.is_null() || !matches!(get(row, "queue_id"), Value::Null) {
            return;
        }
        if self.no_trace.0.len() >= REMEMBERED {
            self.no_trace.0.clear();
        }
        self.no_trace.insert(&s(row, "interruption_id"), now);
    }

    /// `_resendable(row, now)`: resend_candidate, and never seen in Codex's queue by this watcher since it was sent.
    pub(crate) fn resendable(&self, row: &Row, now: f64) -> bool {
        resend_candidate(row, now, self.resend_window())
            && !self.seen_queued.contains(&s(row, "interruption_id"))
            && py::arithmetic(get(row, "submitted_at"))
                .is_some_and(|sent| self.seen_queued_cleared_at < sent)
    }

    /// `_holds(name, row, vector)`: P3 at gate `name`, for a resend - nothing is written for it.
    fn holds(&self, name: &str, row: &Row, vector: &Vector) -> bool {
        self.plug
            .gate(name, &Value::Object(row.clone()), &vector_value(vector))
            == Answer::Is(Alternative::Hold)
    }

    /// `resend_uncertain()`: once a tick, after the due records, only for a plug that may ask.
    pub fn resend_uncertain(&mut self) {
        let found = std::mem::take(&mut self.no_trace.0);
        let now = self.now();
        for (key, looked) in found {
            if now - looked > self.options.conservative_poll_seconds {
                continue;
            }
            if car_scheduler::caught(|| self.resend(&key, now)).is_err() {
                self.log(None, "eligibility_check_failed_no_submission", Value::Null);
            }
        }
    }

    /// `_resend(key, now)`: every condition the module names, in order; the first that fails returns, writing nothing.
    fn resend(&mut self, key: &str, now: f64) -> Py<()> {
        let Some(row) = self.store.get(key)? else {
            return Ok(());
        };
        if !self.resendable(&row, now) {
            return Ok(());
        }
        let thread = s(&row, "thread_id");
        let sent = get(&row, "submitted_at").clone();
        let settings = self.store.settings()?;
        let mut vector = Vector::default();
        vector.set(
            "consent",
            gate_consent(
                truthy(get(&settings, "enabled")),
                self.store.thread_enabled(&thread)?,
                truthy(get(&row, "cancel_requested")),
                self.observing(&settings),
                get(&row, "hold"),
            ),
        );
        if vector.or_unknown("consent").0 != PASS {
            return Ok(());
        }
        // P7, before anything of Codex's is read.
        if self.plug.schedule(&Value::Object(row.clone()), &sent) != Answer::Is(Alternative::Resend)
        {
            return Ok(());
        }
        let unscheduled = with(&row, vec![("next_retry_at", Value::Null)]);
        let quiet = self.quiet_until(now)?;
        vector.set(
            "schedule",
            gate_schedule(&unscheduled, now, quiet, false, false),
        );
        let state = (self.engine_state)()?;
        if vector.or_unknown("schedule").0 != PASS
            || !py::text(&state).is_some_and(|state| COMPATIBLE.contains(&state))
            || !(self.home_lock)()?
            || self.store.others_in_flight(&thread, key)? != 0
        {
            return Ok(());
        }
        vector.set("engine_compatible", gate(PASS, "ok"));
        vector.set("single_owner", gate(PASS, "ok"));
        vector.set("submission_safe", gate(PASS, RESEND));
        if self.holds("submission_safe", &row, &vector) || !self.valid_interruption(&row)? {
            return Ok(());
        }
        // Fresh throughout, from before the send: a watcher started since cannot say so.
        let sent_at = py::num(&sent)?;
        if !(self.watching_since < sent_at
            && self.stale_cleared_at < sent_at
            && self.fresh_throughout(&thread, sent_at))
        {
            return Ok(());
        }
        let proof = self.proof(&row);
        let marker = s(&row, "marker");
        let mut tokens = vec![proof.clone()];
        if marker != proof {
            tokens.push(marker);
        }
        for token in tokens {
            let presence = self.source.marker_presence(&thread, &token)?;
            if truthy(get(&presence, "history")) || truthy(get(&presence, "queue")) {
                return Ok(());
            }
        }
        if !self
            .source
            .later_turns(&thread, get(&row, "ordinal"), &proof)?
            .is_empty()
            || self.source.foreign_queued(&thread, &proof)? != 0
        {
            return Ok(());
        }
        let category = s(&row, "category");
        if !(failures::is_recoverable(&category) && self.recovers(&category)) {
            return Ok(());
        }
        let limits = self.limits();
        vector.set("identity", gate(PASS, "ok"));
        vector.set("known_failure", gate(PASS, "ok"));
        for (name, found) in gate_budgets(&row, &limits_of(&limits), category == USAGE_LIMIT) {
            vector.set(name, found);
        }
        if BUDGETS.iter().any(|name| vector.or_unknown(name).0 != PASS)
            || self.holds("chain_budget", &row, &vector)
            || self.holds("no_progress_budget", &row, &vector)
        {
            return Ok(());
        }
        let app = self.backend.app_identity()?;
        if !truthy(&app) || !car_machine::pyval::is(&self.backend.loaded(&thread, &app)?, "loaded")
        {
            return Ok(());
        }
        vector.set("thread_available", gate(PASS, "ok"));
        if self.holds("thread_available", &row, &vector) {
            return Ok(());
        }
        vector.set("no_newer_user_work", gate(PASS, "ok"));
        let recent = self.store.recent_claims(&thread, now - 86400.0)?;
        let latest = match recent.is_empty() {
            true => None,
            false => {
                let refs: Vec<&Value> = recent.iter().collect();
                Some(py::num(car_machine::pyval::max(&refs)?)?)
            }
        };
        if self.store.recent_claim_count(&thread, now - 86400.0)? as f64
            >= self.options.max_submissions_per_thread_per_day
            || latest.is_some_and(|latest| now - latest < self.options.thread_cooldown_seconds)
            || self.holds("attempt_budget", &row, &vector)
            || self.offline()
            || !matches!(field(&self.usage()?, "available")?, Value::Bool(true))
        {
            return Ok(());
        }
        vector.set("usage", gate(PASS, "ok"));
        if self.holds("usage", &row, &vector) || self.guarded(&row, &mut vector, now)? {
            return Ok(());
        }
        self.dispatch(&row, &app, &mut vector, &limits, None, None, true, false)
    }

    /// `_after_resend(reserved, outcome)`: what came of a resend's send that was not accepted: an uncertain submission
    /// again, never a wait.
    pub(crate) fn after_resend(&mut self, reserved: &Row, outcome: &Value) -> Py<()> {
        let reason = if py::text(outcome) == Some("not_started") {
            "queue_process_not_started"
        } else {
            "queue_result_unknown_do_not_resend"
        };
        self.transition(
            reserved,
            "submission_unknown",
            Some(reason),
            Some(1.0),
            None,
            Row::new(),
        )
    }

    /// `watch_resent()`: once a tick, paused or not, only for a plug that may ask, at most once a minute: a resent
    /// continuation that ran whose proof Codex's history now holds twice.
    pub fn watch_resent(&mut self) -> Py<()> {
        if self.plug.is_null() {
            return Ok(());
        }
        let now = self.now();
        if self
            .resent_looked_at
            .is_some_and(|looked| (0.0..DUPLICATE_LOOK_SECONDS).contains(&(now - looked)))
        {
            return Ok(());
        }
        self.resent_looked_at = Some(now);
        let window = self.options.unknown_reconcile_window_seconds;
        let mut states: Vec<&str> = OBSERVING.to_vec();
        states.extend_from_slice(OUTCOMES);
        for row in self.records(&states)? {
            if !was_resent(&row)
                || text_of(&row, "last_error") == Some("duplicate_marker")
                || now - py::or_number(get(&row, "last_claim_at"), 0.0)? > window
            {
                continue;
            }
            let looked = (|| -> Py<()> {
                let proof = self.proof(&row);
                if self
                    .source
                    .marker_rows(&s(&row, "thread_id"), &proof)?
                    .len()
                    <= 1
                {
                    return Ok(());
                }
                if text_of(&row, "state").is_some_and(|state| OBSERVING.contains(&state)) {
                    self.transition(
                        &row,
                        "outcome_unverified",
                        Some("duplicate_marker"),
                        None,
                        None,
                        Row::new(),
                    )
                } else {
                    self.store.update(
                        &s(&row, "interruption_id"),
                        &py::row(vec![("last_error", Value::from("duplicate_marker"))]),
                        Some(now),
                        None,
                        0,
                    )
                }
            })();
            if looked.is_err() {
                self.log(
                    Some(&s(&row, "thread_id")),
                    "reconciliation_unavailable",
                    Value::Null,
                );
            }
        }
        Ok(())
    }
}
