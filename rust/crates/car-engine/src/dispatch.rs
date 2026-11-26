//! Sending one continuation, and everything checked at the last moment (`engine/dispatch.py`).
//!
//! `attempt` gathers the facts and evaluates the gates, and `dispatch` claims the right to send and starts the queue
//! process, after `presend_problem` (engine/delivery.rs), the look taken after the claim and before the process - the
//! only moment where giving the claim back is still provably safe. The edition's plug is asked at its points, every one
//! of them after the consent gate; whatever it answers, the send is still this module's one call, made after the one
//! claim, the pre-send look and inside the launch guard.

use std::collections::BTreeSet;

use car_machine::domain::public::eligible_at;
use car_machine::json::{Str, Value};
use car_machine::pyval::{self, Py};
use car_policy::classify::continuation::{self, Settings};
use car_policy::classify::failures::{USAGE_LIMIT, reset_carried};
use car_policy::classify::gates::{
    BLOCK, PASS, POSTPONED, QUIET_HOURS, UNKNOWN, Vector, WAIT, decode_gates, gate, gate_budgets,
    gate_consent, gate_submission_safe,
};
use car_policy::plug::{Alternative, Answer, Point, QUEUED, Sender};

use crate::options::{LimitsMap, limits_of};
use crate::py::{self, field, get, s, text_of, truthy};
use crate::seam::{Claim, LaunchGuard};
use crate::{Engine, Row, UNSENT};

/// What the app said of a conversation it does not hold, and the reason a record waits with (else UNKNOWN).
const WAITS: &[(&str, &str)] = &[
    ("notLoaded", "notLoaded"),
    ("elsewhere", "held_by_other_session"),
];

/// A route P16 named: one of the two queued answers core carries out as its ordinary send, or the plug's own.
pub enum Route {
    Queued(Alternative),
    Plugged {
        route: Box<dyn car_policy::plug::Route>,
        words: bool,
    },
}

impl Route {
    /// `route in QUEUED`.
    pub fn queued(&self) -> bool {
        matches!(self, Route::Queued(word) if QUEUED.contains(word))
    }

    /// `route is word`.
    pub fn is(&self, word: Alternative) -> bool {
        matches!(self, Route::Queued(found) if *found == word)
    }
}

/// What `_known_failure` answers: stopped here (`False`), or go on - as core (`None`) or relaxed.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Known {
    Stopped,
    Go(Option<&'static str>),
}

/// The vector as a `dict` value of (result, reason) pairs, as a plug is handed `dict(vector)`.
pub fn vector_value(vector: &Vector) -> Value {
    let mut map = car_machine::json::Map::new();
    for (name, (result, reason)) in &vector.0 {
        map.insert(
            Str::from(name.as_str()),
            Value::Array(vec![
                Value::from(result.as_str()),
                Value::from(reason.as_str()),
            ]),
        );
    }
    Value::Object(map)
}

fn is_pass(vector: &Vector, name: &str) -> bool {
    vector.get(name).is_some_and(|gate| gate.0 == PASS)
}

fn reason_of(vector: &Vector, name: &str) -> String {
    vector
        .get(name)
        .map(|gate| gate.1.clone())
        .unwrap_or_default()
}

/// The launch guard of one record: `store.submission_guard(key)`, entered when the send enters it.
pub struct SubmissionGuard<'a> {
    pub store: &'a dyn crate::Store,
    pub key: String,
}

impl LaunchGuard for SubmissionGuard<'_> {
    fn enter(&self, body: &mut dyn FnMut(bool) -> Value) -> Py<Value> {
        self.store.submission_guard(&self.key, body)
    }
    fn key(&self) -> Option<&str> {
        Some(&self.key)
    }
}

impl Engine {
    /// `attempt(row)`: look at one record - every gate, and the send if all pass.
    pub fn attempt(&mut self, row: &Row) -> Py<()> {
        self.early_look = None;
        self.schedule_said = None;
        let result = self.attempt_once(row.clone());
        self.early_look = None;
        self.schedule_said = None;
        result
    }

    fn attempt_once(&mut self, row: Row) -> Py<()> {
        let now = self.now();
        let poll = self.options.state_poll_seconds;
        let key = s(&row, "interruption_id");
        let thread = s(&row, "thread_id");
        let settings = self.store.settings()?;
        let consent = gate_consent(
            truthy(get(&settings, "enabled")),
            self.store.thread_enabled(&thread)?,
            truthy(get(&row, "cancel_requested")),
            self.observing(&settings),
            get(&row, "hold"),
        );
        let mut vector = Vector::default();
        vector.set("consent", consent.clone());
        // Observe only goes on through every other gate, asking no plug, to where a send would begin.
        if consent.0 != PASS && !Engine::observes(&row, &consent) {
            // No transition - the overlays already say why it waits - but a due record still records the refusing
            // gate, once, so every interface can show it.
            let recorded = decode_gates(get(&row, "gate_eval")).get("consent").cloned();
            if py::or_zero(get(&row, "next_retry_at")) <= now && recorded.as_ref() != Some(&consent)
            {
                self.store.record_gates(&key, &vector, now)?;
            }
            return Ok(());
        }
        let quiet_until = self.quiet_until(now)?; // v0.6.11; None with no quiet hours, the default
        // v0.6.19 (#50): Retry now's read.
        let (schedule, row) = self.schedule_gate(row, &vector, now, quiet_until)?;
        vector.set("schedule", schedule);
        let early =
            !is_pass(&vector, "schedule") && self.early(&row, &mut vector, now, quiet_until)?;
        // SEND_NOW (v0.6.14): a person's request passes the retry's wait and a postponement only.
        let mut forced =
            !is_pass(&vector, "schedule") && self.send_now(&row, &mut vector, now, quiet_until);
        if !is_pass(&vector, "schedule") {
            let due = py::or_zero(get(&row, "next_retry_at")) <= now;
            let said = reason_of(&vector, "schedule");
            if said == "waiting_reset" && due {
                // A usage reset still ahead is a wait with a reason, never a record that is due every poll.
                let wait = py::num(get(&row, "reset_at"))? + self.options.reset_grace_seconds - now;
                self.wait(
                    &row,
                    "waiting_reset",
                    Some("waiting_reset"),
                    wait,
                    &mut vector,
                )?;
            } else if said == POSTPONED && due {
                let wait = py::num(get(&row, "not_before"))? - now;
                let (state, last) = (s(&row, "state"), py::opt(&row, "last_error"));
                self.wait(&row, &state, last.as_deref(), wait, &mut vector)?;
            } else if said == QUIET_HOURS {
                let wait = quiet_until.ok_or("TypeError")? - now;
                self.quiet(&row, &mut vector, wait)?;
            }
            return Ok(());
        }
        // P7: due by core's schedule, and the plug may say not yet; SEND_NOW here passes the spacing and the attempt
        // budget.
        if !(early || forced) && consent.0 == PASS {
            let said = self.plug.schedule(
                &Value::Object(row.clone()),
                &eligible_at(&Value::Object(row.clone()))?,
            );
            forced = said == Answer::Is(Alternative::SendNow);
            if self.held("schedule", &row, &mut vector, &said)? {
                return Ok(());
            }
        }
        if matches!(
            text_of(&row, "state"),
            Some("waiting_reset" | "waiting_poll")
        ) {
            self.log(Some(&thread), "checking_eligibility", Value::Null);
        }
        let compatibility = (self.engine_state)()?;
        let compatibility = py::text(&compatibility).unwrap_or_default();
        vector.set(
            "engine_compatible",
            if matches!(
                compatibility,
                "verified" | "checked" | "structurally_compatible"
            ) {
                gate(PASS, "ok")
            } else if matches!(compatibility, "incompatible" | "failed_here") {
                gate(BLOCK, "engine_incompatible")
            } else {
                gate(UNKNOWN, "engine_unknown")
            },
        );
        vector.set(
            "single_owner",
            if (self.home_lock)()? {
                gate(PASS, "ok")
            } else {
                gate(BLOCK, "home_lock_unavailable")
            },
        );
        let others = self.store.others_in_flight(&thread, &key)?;
        vector.set("submission_safe", gate_submission_safe(&row, others));
        if !is_pass(&vector, "engine_compatible") {
            let reason = reason_of(&vector, "engine_compatible");
            return self.wait(&row, "waiting_for_app", Some(&reason), poll, &mut vector);
        }
        if !is_pass(&vector, "single_owner") {
            return self.wait(
                &row,
                "waiting_for_app",
                Some("home_lock_unavailable"),
                poll,
                &mut vector,
            );
        }
        if !is_pass(&vector, "submission_safe") {
            return self.wait(
                &row,
                "waiting_retry",
                Some("other_recovery_in_flight"),
                poll,
                &mut vector,
            );
        }
        if self.plugged("submission_safe", &row, &mut vector)? {
            return Ok(());
        }
        if !self.valid_interruption(&row)? {
            let (state, reason) = self.supersede_reason(&row);
            return self.transition(&row, &state, Some(&reason), None, None, Row::new());
        }
        // Even a brief lag can hide a newer user turn. The grace period never authorizes a new send.
        let Some(fresh) = self.projection_now(&thread) else {
            vector.set("engine_compatible", gate(BLOCK, "projection_table_missing"));
            return self.wait(
                &row,
                "waiting_for_app",
                Some("projection_table_missing"),
                poll,
                &mut vector,
            );
        };
        if self.identity_waits(&row, &mut vector, fresh, poll)? {
            return Ok(());
        }
        let Known::Go(relaxed) = self.known_failure(&row, &mut vector, now)? else {
            return Ok(());
        };
        // CAPACITY counts against core's capacity bounds: budgets, its day and its spacing (ladder.py).
        let limits = if relaxed == Some("capacity") {
            self.capacity_limits()
        } else {
            self.limits()
        };
        let usage_category = text_of(&row, "category") == Some(USAGE_LIMIT);
        for (name, found) in gate_budgets(&row, &limits_of(&limits), usage_category) {
            vector.set(name, found);
        }
        if forced {
            self.own_budget(&row, &mut vector);
        }
        for name in ["chain_budget", "attempt_budget", "no_progress_budget"] {
            if !is_pass(&vector, name) {
                self.store.record_gates(&key, &vector, now)?;
                let reason = reason_of(&vector, name);
                return self.stop_for_budget(&row, name, &reason);
            }
        }
        // The attempt budget is put to the plug with the pacing below, so the plug hears each gate once.
        for name in ["chain_budget", "no_progress_budget"] {
            if self.plugged(name, &row, &mut vector)? {
                return Ok(());
            }
        }
        let app = self.backend.app_identity()?;
        // P16: a conversation the app does not hold waits for it to be opened (A11) - and, with no app, for the app -
        // unless the plug names a route that continues it otherwise, which core carries out (engine/routes.rs).
        let (route, loaded) = self.route(&row, &app, &mut vector)?;
        if !truthy(&app) && route.is_none() {
            let reason = self.no_app_reason();
            vector.set("thread_available", gate(WAIT, &reason));
            let reason = reason_of(&vector, "thread_available");
            return self.wait(&row, "waiting_for_app", Some(&reason), poll, &mut vector);
        }
        if route.is_none() && !pyval::is(&loaded, "loaded") {
            // v0.6.16-beta.4: one another Codex session holds waits with a reason of its own.
            let waits =
                py::text(&loaded).and_then(|word| WAITS.iter().find(|(key, _)| *key == word));
            let reason = waits.map_or("loaded_state_unknown", |(_, reason)| reason);
            vector.set(
                "thread_available",
                gate(if waits.is_some() { WAIT } else { UNKNOWN }, reason),
            );
            return self.wait(
                &row,
                "waiting_for_loaded_thread",
                Some(reason),
                poll,
                &mut vector,
            );
        }
        if route.is_none() {
            vector.set("thread_available", gate(PASS, "ok"));
            if self.plugged("thread_available", &row, &mut vector)? {
                return Ok(());
            }
            if text_of(&row, "state") != Some("waiting_for_usage") {
                self.log(Some(&thread), "loaded", Value::Null);
            }
        }
        if self.source.foreign_queued(&thread, &s(&row, "marker"))? != 0 {
            // Somebody already queued something for this conversation. It goes first.
            vector.set("no_newer_user_work", gate(WAIT, "user_input_queued"));
            return self.wait(
                &row,
                "waiting_retry",
                Some("user_input_queued"),
                poll,
                &mut vector,
            );
        }
        vector.set("no_newer_user_work", gate(PASS, "ok"));
        let recent = self.store.recent_claims(&thread, now - 86400.0)?;
        let (per_day, cooldown) = self.caps(relaxed);
        if (self.store.recent_claim_count(&thread, now - 86400.0)? as f64) >= per_day {
            // Defer until the oldest claim rolls out of the 24h window. Bounded to N/day per thread.
            vector.set("attempt_budget", gate(WAIT, "daily_submission_cap"));
            let oldest = least(&recent)?;
            let wait = 60.0_f64.max(oldest + 86400.0 - now + 5.0);
            return self.wait(
                &row,
                "waiting_retry",
                Some("daily_submission_cap"),
                wait,
                &mut vector,
            );
        }
        if !recent.is_empty() && now - greatest(&recent)? < cooldown && !forced {
            vector.set("attempt_budget", gate(WAIT, "thread_submission_cooldown"));
            return self.wait(
                &row,
                "waiting_retry",
                Some("thread_submission_cooldown"),
                cooldown,
                &mut vector,
            );
        }
        if self.plugged("attempt_budget", &row, &mut vector)?
            || self.offline_wait(&row, &mut vector, now)?
        {
            return Ok(());
        }
        let usage = self.usage()?;
        let available = field(&usage, "available")?.clone();
        if !matches!(available, Value::Bool(true)) {
            let unavailable = matches!(available, Value::Bool(false));
            vector.set(
                "usage",
                gate(
                    if unavailable { WAIT } else { UNKNOWN },
                    if unavailable {
                        "usage_unavailable"
                    } else {
                        "usage_unknown"
                    },
                ),
            );
            self.store.record_gates(&key, &vector, now)?;
            if !early {
                // a look early that finds none changes nothing
                self.usage_wait(&row, &usage, now)?;
            }
            return Ok(());
        }
        vector.set("usage", gate(PASS, "ok"));
        if self.plugged("usage", &row, &mut vector)? {
            return Ok(());
        }
        if consent.0 != PASS {
            return self.would_send(&row, &vector, now); // observe only: every other gate passed
        }
        // v0.6.11: the task-changed guard, which reads nothing at the defaults (engine/guard.rs).
        if self.guarded(&row, &mut vector, now)?
            || (!forced && self.objection(&row, &mut vector, now)?)
        {
            return Ok(());
        }
        let relaxed = relaxed.or(if early { Some("early") } else { None });
        self.dispatch(
            &row,
            &app,
            &mut vector,
            &limits,
            route.as_ref(),
            relaxed,
            false,
            forced,
        )
    }

    /// `_plugged(name, row, vector)`: P3 - gate `name`, which core has just passed, put to the plug. True if it held.
    pub(crate) fn plugged(&mut self, name: &str, row: &Row, vector: &mut Vector) -> Py<bool> {
        if vector.or_unknown("consent").0 != PASS {
            return Ok(false);
        }
        let said = self
            .plug
            .gate(name, &Value::Object(row.clone()), &vector_value(vector));
        self.held(name, row, vector, &said)
    }

    /// `dispatch(row, app, vector, limits, route, relaxed, resend, forced)`: claim, re-check, send. The only method
    /// that sends. A record of the plug's own (`record`, P2) is not ported (engine/plugrecords.rs).
    #[allow(clippy::too_many_arguments)]
    pub fn dispatch(
        &mut self,
        row: &Row,
        app: &Value,
        vector: &mut Vector,
        limits: &LimitsMap,
        route: Option<&Route>,
        relaxed: Option<&'static str>,
        resend: bool,
        forced: bool,
    ) -> Py<()> {
        let lock = self.dispatch_lock.clone();
        let _held = lock.as_ref().map(|lock| lock.lock());
        let key = s(row, "interruption_id");
        let Some(current) = self.store.get(&key)? else {
            return Ok(());
        };
        if !self.allowed(&current)? {
            return Ok(());
        }
        let sendable = if resend {
            self.resendable(&current, self.now())
        } else {
            text_of(&current, "state").is_some_and(|state| UNSENT.contains(&state))
        };
        if !sendable {
            return Ok(());
        }
        if !self.valid_interruption(&current)? {
            if !resend {
                let (state, reason) = self.supersede_reason(&current);
                self.transition(&current, &state, Some(&reason), None, None, Row::new())?;
            }
            return Ok(());
        }
        let thread = s(&current, "thread_id");
        // A fresh process identity prevents a prior app's status authorizing a new app; a route only while the
        // conversation is still not held (engine/routes.rs).
        if !self.still_where(&thread, app, route)? {
            if !resend && !self.parked(&current, vector)? {
                self.transition(
                    &current,
                    "waiting_for_loaded_thread",
                    Some("loaded_recheck_failed"),
                    Some(60.0),
                    None,
                    Row::new(),
                )?;
            }
            return Ok(());
        }
        let usage = self.usage()?;
        if !matches!(field(&usage, "available")?, Value::Bool(true)) {
            if !resend && !self.parked(&current, vector)? {
                self.transition(
                    &current,
                    "waiting_for_usage",
                    Some("usage_recheck_failed"),
                    Some(900.0),
                    None,
                    Row::new(),
                )?;
            }
            return Ok(());
        }
        if let Some(Route::Plugged { words: false, .. }) = route {
            return self
                .resume_unloaded(&current, vector, limits, route, app, relaxed, forced, None);
        }
        // The text is decided before the claim, not after it: a failure building it has to happen while the record is
        // still merely waiting. Nothing about the text can change what is allowed.
        let message = match self.continuation_for(&current, &self.values(), limits) {
            Ok(message) => message,
            Err(_) => {
                self.log(Some(&thread), "continuation_text_fallback", Value::Null);
                continuation::build(
                    get(&current, "category"),
                    car_words::l10n::DEFAULT,
                    &Value::from(continuation::DEFAULT_STYLE),
                    &Value::Null,
                    &Value::Null,
                )?
            }
        };
        let (message, worded) = self.plugged_text(&current, message, limits);
        let plain = message.clone(); // v0.6.16-beta.3: the words for this time, after it (engine/delivery.rs)
        let (message, once) = if resend {
            (message, None)
        } else {
            self.once_words_for(&current, message, limits)
        };
        if let Some(Route::Plugged { .. }) = route {
            // A route that takes words (v0.6.16-beta.4) carries these in a send's place (engine/routes.rs).
            return self.resume_unloaded(
                &current,
                vector,
                limits,
                route,
                app,
                relaxed,
                forced,
                Some((message, worded, once, plain)),
            );
        }
        // P5, decided before the claim like the words: core's own backend, unless the plug names a channel.
        let sender = self.plug.sender(&Value::Object(current.clone()));
        let channel = matches!(sender, Sender::Channel { .. });
        let relaxed = py::text(&reset_carried(
            &relaxed.map_or(Value::Null, Value::from),
            &Value::Bool(channel),
        ))
        .map(static_word);
        // P15, decided like them before the claim, and written into the record before it.
        let Some(client) = self.delivery(&current, channel, resend)? else {
            return Ok(()); // a resend that would not carry the proof its first send did
        };
        if self.not_for_open(&current, route, channel, client.as_deref(), vector)? {
            return Ok(());
        }
        let mut carried: BTreeSet<Point> = BTreeSet::new();
        if worded {
            carried.insert(Point::Text);
        }
        if channel {
            carried.insert(Point::Sender);
        }
        if client.is_some() {
            carried.insert(Point::Delivery);
        }
        carried.extend(Engine::relaxed_points(if resend {
            Some("resend")
        } else {
            relaxed
        }));
        carried.extend(Engine::relaxed_points(if forced {
            Some("forced")
        } else {
            None
        }));
        if route.is_some_and(Route::queued) {
            carried.insert(Point::Unloaded);
        }
        let at = self.now();
        let claim = Claim {
            plugged: !self.plug.is_null(),
            limits: limits_of(&if forced {
                self.forced_limits(limits)
            } else {
                limits.clone()
            }),
            gates: vector.clone(),
            carried,
            quiet_until: self.quiet_until(at)?,
            relaxed: relaxed.map(str::to_owned),
            resend: resend.then(|| self.resend_window()),
            forced,
            caps: if resend {
                self.caps(None)
            } else {
                self.caps(relaxed)
            },
        };
        let (claimed, refusing, reason) =
            self.store.reserve_ledgered(&key, at, &claim, &self.plug)?;
        if !claimed {
            if !resend {
                // a resend refused stays as it was
                self.refused(&current, refusing.as_deref(), reason.as_deref())?;
            }
            return Ok(());
        }
        self.moved(&current, "submitting");
        let claim = self.store.get(&key)?;
        let mut problem = self.presend_problem(claim.as_ref(), forced)?;
        if problem.is_none()
            && let (Some(client), Some(claim)) = (&client, &claim)
            && self.proof(claim) != *client
        {
            // Never sent under an id the watch would not look for (engine/delivery.rs).
            problem = Some((
                "waiting_retry".into(),
                "released_before_send".into(),
                self.options.state_poll_seconds,
            ));
        }
        if let Some((mut target, mut why, delay)) = problem {
            if resend {
                // never given back to a wait: its first send is still uncertain
                target = "submission_unknown".into();
                why = "released_before_send".into();
                let claim = claim.as_ref().ok_or("TypeError")?;
                self.transition(claim, &target, Some(&why), Some(1.0), None, Row::new())?;
            } else {
                self.release(&key, claim.as_ref(), &target, &why, delay)?;
            }
            self.log(Some(&thread), &target, Value::from(why.as_str()));
            return Ok(());
        }
        let claim = claim.ok_or("TypeError")?;
        if !resend && self.once_words_moved(&claim)? {
            return Ok(()); // given back (engine/delivery.rs)
        }
        let mut message = message;
        if let Some(once) = &once
            && !self.spend_once_words(&claim, once)
        {
            message = plain; // v0.6.16-beta.3: never sent twice
        }
        self.log(Some(&thread), "queue_submission_started", Value::Null);
        // Reservation is durable before any external process can accept the message. The conversation and the marker
        // are the claimed row's, read back after the claim.
        let words = match &client {
            Some(_) => message,
            None => format!("{message}\n\n{}", s(&claim, "marker")),
        };
        let claimed_thread = s(&claim, "thread_id");
        let response = {
            let guard = SubmissionGuard {
                store: self.store.as_ref(),
                key: key.clone(),
            };
            let words = Str::from(words.as_str());
            // `try: response = sender.send(...) except Exception: response = {"outcome": "unknown"}`: a panic too.
            let sent = car_scheduler::caught(|| match &sender {
                Sender::Backend => self.backend.send(&claimed_thread, &words, &guard),
                Sender::Channel { channel, .. } => {
                    Ok(channel.send(&claimed_thread, &words, client.as_deref()))
                }
            });
            match sent {
                Ok(Value::Object(response)) => response,
                _ => py::row(vec![("outcome", Value::from("unknown"))]),
            }
        };
        if self.after_send(&current, &response, resend).is_err() {
            // The send happened or may have; the record stays claimed and the watch resolves it.
            self.log(Some(&thread), "post_send_bookkeeping_failed", Value::Null);
        }
        Ok(())
    }

    /// `continuation.for_settings(category, values, row=row, limits=limits)`.
    pub(crate) fn continuation_for(
        &self,
        row: &Row,
        values: &Value,
        limits: &LimitsMap,
    ) -> Py<String> {
        let environ = continuation::Environ {
            variable: &|name: &str| (self.environ)(name),
            windows: &|| (self.windows_languages)(),
        };
        let at = Settings {
            values,
            row: &Value::Object(row.clone()),
            limits: &Value::Object(limits.clone()),
            environ: &environ,
            clock: self.local.as_ref(),
        };
        continuation::for_settings(get(row, "category"), &at)
    }

    /// `_stop_for_budget(row, gate, reason)`.
    pub(crate) fn stop_for_budget(&mut self, row: &Row, gate: &str, reason: &str) -> Py<()> {
        let state = if gate == "no_progress_budget" {
            "no_progress_exhausted"
        } else {
            "retry_budget_exhausted"
        };
        self.transition(row, state, Some(reason), None, None, Row::new())
    }
}

/// The words `relaxed` may hold, as `'static` text.
fn static_word(word: &str) -> &'static str {
    match word {
        "admitted" => "admitted",
        "capacity" => "capacity",
        "reset" => "reset",
        "early" => "early",
        "resend" => "resend",
        "forced" => "forced",
        _ => "other",
    }
}

/// `min(values)` of the stored times.
fn least(values: &[Value]) -> Py<f64> {
    let first = values.first().ok_or("ValueError")?;
    let mut best = first;
    for value in &values[1..] {
        if pyval::less(value, best)? {
            best = value;
        }
    }
    py::num(best)
}

/// `max(values)` of the stored times.
fn greatest(values: &[Value]) -> Py<f64> {
    let refs: Vec<&Value> = values.iter().collect();
    if refs.is_empty() {
        return Err("ValueError");
    }
    py::num(pyval::max(&refs)?)
}
