//! Moving a record, and saying so (`engine/announce.py`).
//!
//! One place writes a transition and decides whether it is worth telling somebody about: a notification is a state a
//! person would want to know they are in, not every step between. It is also where the edition's plug is asked what
//! follows a recovery turn (P6), and told of every move the engine writes (P14). The waits a dispatch ends in are here
//! too: a claim the store refused, a record parked in quiet hours, and the objection window.

use car_machine::json::{Map, Str, Value};
use car_machine::pyval::{self, Py};
use car_machine::vocab_gen::domain_states::{OBSERVING, OUTCOMES, TERMINAL};
use car_policy::classify::gates::{HELD, POSTPONED, Vector, WAIT, gate};

use crate::py::{self, get, opt, s, text, text_of, truthy, with};
use crate::{Engine, Row};

/// States worth telling a person about, and which notification setting governs each.
pub const NOTIFY_ON_STATE: &[(&str, &str)] = &[
    ("turn_started", "result"),
    ("failed", "result"),
    ("submission_unknown", "result"),
    ("retry_budget_exhausted", "stopped"),
    ("no_progress_exhausted", "stopped"),
    ("terminal_failure", "stopped"),
];

/// The two refusals of a claim that read the conversation's day and spacing again (v0.6.15-beta).
pub const CAP_WAITS: &[&str] = &["daily_submission_cap", "thread_submission_cooldown"];

const BUDGETS: &[&str] = &["chain_budget", "attempt_budget", "no_progress_budget"];

fn notify_on(state: &str) -> Option<&'static str> {
    NOTIFY_ON_STATE
        .iter()
        .find(|(each, _)| *each == state)
        .map(|(_, event)| *event)
}

impl Engine {
    // ----------------------------------------------------------------- helpers
    /// `transition(row, state, reason, delay=..., event=..., **extra)`.
    pub fn transition(
        &mut self,
        row: &Row,
        state: &str,
        reason: Option<&str>,
        delay: Option<f64>,
        event: Option<&str>,
        extra: Row,
    ) -> Py<()> {
        let mut values = py::row(vec![
            ("state", Value::from(state)),
            ("last_error", py::word(reason)),
        ]);
        let outcome_given = extra.contains_key("outcome_at");
        for (key, value) in extra {
            values.insert(key, value);
        }
        if let Some(delay) = delay {
            values.insert(Str::from("next_retry_at"), Value::Float(self.now() + delay));
        }
        let before = get(row, "state").clone();
        let changed = text(&before) != Some(state);
        if TERMINAL.contains(&state) && changed && !outcome_given {
            values.insert(Str::from("outcome_at"), Value::Float(self.now()));
        }
        let at = self.now();
        self.store
            .update(&s(row, "interruption_id"), &values, Some(at), event, 0)?;
        self.moved(row, state);
        let thread = opt(row, "thread_id");
        let reason_changed = !pyval::eq(get(row, "last_error"), &py::word(reason));
        if changed || reason_changed {
            self.log(thread.as_deref(), state, py::word(reason));
        }
        // Announced from the transition itself, so the notification and the recorded state never disagree.
        if changed && let Some(event) = notify_on(state) {
            let detail = py::row(vec![
                ("state", Value::from(state)),
                ("reason", py::word(reason)),
            ]);
            self.announce(event, row, detail);
        }
        // P6: a record that was following its recovery turn has an outcome. NULL is never asked.
        if changed
            && !self.plug.is_null()
            && text(&before).is_some_and(|before| OBSERVING.contains(&before))
            && OUTCOMES.contains(&state)
            && self.allowed(row)?
        {
            let told = with(
                row,
                vec![
                    ("state", Value::from(state)),
                    ("last_error", py::word(reason)),
                ],
            );
            let _ = self.plug.outcome(&Value::Object(told), state);
        }
        Ok(())
    }

    /// `moved(row, state)`: P14 - tell the plug that `row` has just moved to `state`. NULL is never told.
    pub fn moved(&mut self, row: &Row, state: &str) {
        if !self.plug.is_null() && text_of(row, "state") != Some(state) {
            self.plug.moved(&Value::Object(row.clone()), state);
        }
    }

    /// `_release(key, claim, target, reason, delay)`: give back the claim whose send never started, and tell the plug.
    pub(crate) fn release(
        &mut self,
        key: &str,
        claim: Option<&Row>,
        target: &str,
        reason: &str,
        delay: f64,
    ) -> Py<()> {
        let now = self.now();
        let next = self.now() + delay;
        if self
            .store
            .release_claim(key, target, reason, now, Some(next))?
        {
            match claim {
                Some(claim) => self.moved(claim, target),
                None if !self.plug.is_null() => return Err("AttributeError"),
                None => {}
            }
        }
        Ok(())
    }

    /// `announce(event, row, **detail)`: tell the user something happened. Never affects what happens. Deduplicated
    /// per interruption, event and state; a notifier that fails is logged.
    pub fn announce(&mut self, event: &str, row: &Row, detail: Map) {
        let key = format!(
            "{:?}|{event}|{:?}",
            get(row, "interruption_id"),
            get(&detail, "state")
        );
        if self.announced.contains(&key) {
            return;
        }
        if self.announced.len() > 4096 {
            self.announced.clear();
        }
        self.announced.insert(key);
        let mut payload = py::row(vec![
            ("thread_id", get(row, "thread_id").clone()),
            ("interruption_id", get(row, "interruption_id").clone()),
            ("category", get(row, "category").clone()),
            ("reset_at", get(row, "reset_at").clone()),
        ]);
        for (key, value) in detail {
            payload.insert(key, value);
        }
        if (self.notify_sink)(event, &payload).is_err() {
            let thread = opt(row, "thread_id");
            self.log(thread.as_deref(), "notification_failed", Value::from(event));
        }
    }

    /// `_objection(row, vector, now)`: the objection-window tier (v0.6.11): before a record is first sent, its minutes
    /// for a person to stop it. True if the record waits instead of being sent now.
    pub(crate) fn objection(&mut self, row: &Row, vector: &mut Vector, now: f64) -> Py<bool> {
        if !matches!(get(row, "objection_at"), Value::Null) {
            return Ok(false);
        }
        if text(&self.tier(&s(row, "thread_id"))?) != Some("objection_window") {
            return Ok(false);
        }
        let minutes = py::num(get(&self.policy_values, "objection_minutes"))?;
        let until = now + 60.0 * minutes;
        if self
            .store
            .open_objection_window(&s(row, "interruption_id"), until, now)?
        {
            vector.set("schedule", gate(WAIT, POSTPONED));
            let (state, last) = (s(row, "state"), opt(row, "last_error"));
            self.wait(row, &state, last.as_deref(), until - now, vector)?;
            let told = with(row, vec![("not_before", Value::Float(until))]);
            self.announce(
                "objection",
                &told,
                py::row(vec![("until", Value::Float(until))]),
            );
        }
        // A window that could not be opened sends nothing on this tick either.
        Ok(true)
    }

    /// `_refused(row, gate, reason)`: a claim the store refused. Recorded as a wait or a stop, never silently.
    pub(crate) fn refused(
        &mut self,
        row: &Row,
        refusing: Option<&str>,
        reason: Option<&str>,
    ) -> Py<()> {
        let key = s(row, "interruption_id");
        let early = self.early_look.as_deref() == Some(key.as_str());
        let refusing = refusing.unwrap_or_default();
        let reason_text = reason.unwrap_or_default();
        if refusing == "attempt_budget" && CAP_WAITS.contains(&reason_text) {
            // The conversation's day or spacing, counted again inside the claim: a wait, never a stop.
            if !early {
                let delay = self.cap_delay(row, reason_text)?;
                self.transition(row, "waiting_retry", reason, Some(delay), None, Row::new())?;
            }
            return Ok(());
        }
        if early && !BUDGETS.contains(&refusing) {
            return Ok(()); // looked at early: the claim kept its vector, nothing else moves
        }
        let poll = self.options.state_poll_seconds;
        let (state, last) = (s(row, "state"), opt(row, "last_error"));
        if reason_text == "capacity_window" {
            // Past a capacity error's 24 hours (v0.6.14): no stop of its own.
            self.transition(row, &state, last.as_deref(), Some(poll), None, Row::new())
        } else if BUDGETS.contains(&refusing) {
            self.stop_for_budget(row, refusing, reason_text)
        } else if refusing == "schedule"
            && reason_text == "waiting_reset"
            && truthy(get(row, "reset_at"))
        {
            let delay = 30.0_f64.max(
                py::num(get(row, "reset_at"))? + self.options.reset_grace_seconds - self.now(),
            );
            self.transition(
                row,
                "waiting_reset",
                Some("waiting_reset"),
                Some(delay),
                None,
                Row::new(),
            )
        } else if refusing == "submission_safe" && reason_text == "other_recovery_in_flight" {
            self.transition(
                row,
                "waiting_retry",
                Some("other_recovery_in_flight"),
                Some(poll),
                None,
                Row::new(),
            )
        } else if refusing == "submission_safe" && reason_text == HELD {
            // The plug's ledger held the claim (P11): one more poll, its state and reason kept.
            self.transition(row, &state, last.as_deref(), Some(poll), None, Row::new())
        } else {
            Ok(())
        }
    }

    /// `_cap_delay(row, reason)`: how long a record waits that the claim found over its day or within its spacing.
    fn cap_delay(&mut self, row: &Row, reason: &str) -> Py<f64> {
        let now = self.now();
        if reason == "daily_submission_cap" {
            let recent = self
                .store
                .recent_claims(&s(row, "thread_id"), now - 86400.0)?;
            let Some(first) = recent.first() else {
                return Ok(60.0);
            };
            let mut oldest = first;
            for value in &recent[1..] {
                if pyval::less(value, oldest)? {
                    oldest = value;
                }
            }
            return Ok(60.0_f64.max(py::num(oldest)? + 86400.0 - now + 5.0));
        }
        Ok(self.caps(None).1)
    }

    /// `_quiet(row, vector, delay)`: a record that fell due in quiet hours, parked until they end.
    pub(crate) fn quiet(&mut self, row: &Row, vector: &mut Vector, delay: f64) -> Py<()> {
        if !self.parked(row, vector)? {
            let now = self.now();
            self.store
                .record_gates(&s(row, "interruption_id"), vector, now)?;
            let (state, last) = (s(row, "state"), opt(row, "last_error"));
            self.transition(
                row,
                &state,
                last.as_deref(),
                Some(delay),
                None,
                py::row(vec![("usage_probe_at", Value::Null)]),
            )?;
        }
        Ok(())
    }

    /// `_would_send(row, vector, now)`: Observe only - every gate but consent passed; nothing is claimed or sent.
    pub(crate) fn would_send(&mut self, row: &Row, vector: &Vector, now: f64) -> Py<()> {
        let next = now + self.options.conservative_poll_seconds;
        if self
            .store
            .record_would_send(&s(row, "interruption_id"), vector, now, next)?
        {
            self.log(Some(&s(row, "thread_id")), "would_send", Value::Null);
        }
        Ok(())
    }

    /// `_wait(row, state, reason, delay, vector)`: park a record that was due but is not claimable.
    pub(crate) fn wait(
        &mut self,
        row: &Row,
        state: &str,
        reason: Option<&str>,
        delay: f64,
        vector: &mut Vector,
    ) -> Py<()> {
        if self.parked(row, vector)? {
            return Ok(());
        }
        let now = self.now();
        self.store
            .record_gates(&s(row, "interruption_id"), vector, now)?;
        let extra = if truthy(get(row, "usage_probe_at")) && state != "waiting_for_usage" {
            py::row(vec![("usage_probe_at", Value::Null)])
        } else {
            Row::new()
        };
        self.transition(row, state, reason, Some(delay), None, extra)
    }
}
