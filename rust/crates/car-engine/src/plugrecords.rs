//! Records of the edition's own, tried like core's (P2, v0.6.14) (`engine/plugrecords.py`; carried out from seat
//! S7.2a2).
//!
//! Once a tick, after core's own due records, the plug hands core the records of its own store that are due now, and
//! those of them in flight. Core carries each out as it carries out its own: a waiting one through core's gates in
//! A8's order, the one claim (`reserve_record`, the plug's ledger asked), the pre-send look and the one send inside
//! `record_guard`; one in flight watched - delivered once its marker is in Codex's history, handed over where a person
//! edited it, taken back where a person cancelled it or recovery is paused, unproven a day after it was last seen.
//! Every move is told at P14. The standard edition's plug hands over none, so none of this runs there.

use std::collections::{BTreeSet, HashMap};

use car_machine::json::{Map, Str, Value};
use car_machine::pyval::{self, Py};
use car_policy::classify::continuation;
use car_policy::classify::gates::{HELD, OBSERVE_ONLY, QUIET_HOURS};
use car_policy::classify::power;
use car_policy::plug::{RecordMove, RecordPurpose, Sender};

use crate::Engine;
use crate::py::{get, text_of, with};
use crate::recordchannel::Carrier;
use crate::seam::LaunchGuard;

/// How many records a would-send line, a refusal or a wrap-up is remembered for, in a process, before all are
/// forgotten (`NOTED_LIMIT`).
pub const NOTED_LIMIT: usize = 512;
/// The state of a record the plug hands over in flight.
pub const IN_FLIGHT_RECORD: &str = "in_flight";
/// A turn whose ending is known, which a continuation may follow.
const FINAL: &[&str] = &["completed", "failed", "interrupted"];

/// The moves after which a record is no longer core's to watch (`ENDED`).
fn ended(movement: RecordMove) -> bool {
    matches!(
        movement,
        RecordMove::Delivered
            | RecordMove::Unproven
            | RecordMove::HandedOver
            | RecordMove::Withdrawn
            | RecordMove::Superseded
    )
}

/// `record[name]`: KeyError where it has none.
pub(crate) fn field<'a>(record: &'a Map, name: &str) -> Py<&'a Value> {
    record.get(name).ok_or("KeyError")
}

/// `record[name]` read as text (the plug's records are validated: ids, markers and words are text).
pub(crate) fn text_field<'a>(record: &'a Map, name: &str) -> Py<&'a str> {
    pyval::text(field(record, name)?).ok_or("TypeError")
}

/// `max(first, second)`: the first unless the second is greater, each kept as it was.
pub(crate) fn later_of(first: &Value, second: &Value) -> Py<Value> {
    let number = |value: &Value| pyval::Num::of(value).ok_or("TypeError");
    let (one, other) = (number(first)?, number(second)?);
    Ok(
        if pyval::compare(other, one) == Some(std::cmp::Ordering::Greater) {
            second.clone()
        } else {
            first.clone()
        },
    )
}

/// `record["purpose"] == purpose`.
fn purpose_is(record: &Map, purpose: RecordPurpose) -> Py<bool> {
    Ok(pyval::text(field(record, "purpose")?) == Some(purpose.as_str()))
}

/// The launch guard of a record of the plug's own: `store.record_guard(record, plug, now)`, entered when the send
/// enters it.
struct RecordGuard<'a> {
    engine: &'a Engine,
    record: &'a Map,
    now: f64,
}

impl LaunchGuard for RecordGuard<'_> {
    fn enter(&self, body: &mut dyn FnMut(bool) -> Value) -> Py<Value> {
        self.engine
            .store
            .record_guard(self.record, &self.engine.plug, self.now, body)
    }
}

/// `plughands.Channel.send(thread, prompt, launch_guard=guard, client_id=client)`: the guard entered first, and the
/// plug's channel called only where it permitted the launch.
pub(crate) fn guarded_send(
    channel: &dyn car_policy::plug::Channel,
    thread_id: &str,
    words: &Str,
    client_id: Option<&str>,
    guard: &dyn LaunchGuard,
) -> Py<Value> {
    let permitted = guard.enter(&mut Value::Bool)?;
    if !matches!(permitted, Value::Bool(true)) {
        return Ok(refused_launch());
    }
    Ok(channel.send(thread_id, words, client_id))
}

/// What a channel or a route answers when its launch guard refused it.
pub(crate) fn refused_launch() -> Value {
    Value::Object(crate::py::row(vec![
        ("outcome", Value::from("not_started")),
        ("error_code", Value::from("queue_consent_refused")),
    ]))
}

impl Engine {
    /// `plug_records(view)`: P2 - every record the plug hands over, each tried, sent or watched once; one that raises
    /// costs only itself.
    pub fn plug_records(&mut self, now: f64) {
        let records = {
            let view = self.view(now);
            self.plug.records(&view)
        };
        let Ok(records) = records else {
            return;
        };
        for record in records {
            let thread = match &record {
                Value::Object(record) => text_of(record, "thread_id").map(str::to_owned),
                _ => None,
            };
            let carried = match record {
                Value::Object(record) => self.plug_record(record),
                _ => Err("TypeError"),
            };
            if carried.is_err() {
                self.log(thread.as_deref(), "plug_record_check_failed", Value::Null);
            }
        }
    }

    fn plug_record(&mut self, record: Map) -> Py<()> {
        if pyval::text(field(&record, "state")?) == Some(IN_FLIGHT_RECORD) {
            let record = self.record_queued(record)?;
            let record = self.record_carried(record, Carrier::InFlight)?;
            let id = text_field(&record, "record_id")?.to_owned();
            self.flying()
                .insert(Str::from(id.as_str()), Value::Object(record.clone()));
            self.watch_record(&record)
        } else if Engine::worded(&record) {
            self.try_record(record)
        } else {
            Ok(())
        }
    }

    /// `_worded(record)`: whether a waiting record's words are a person's own that may be sent, checked here again.
    /// Every refusal of `validate_prompt`/`validate_continuation` is a PromptError (its code is what car-policy
    /// answers), and a record with no words or purpose a KeyError: each is no, as the reference catches them.
    fn worded(record: &Map) -> bool {
        let Ok(words) = field(record, "words") else {
            return false;
        };
        let continued = purpose_is(record, RecordPurpose::Continuation).unwrap_or(false)
            || purpose_is(record, RecordPurpose::WrapUp).unwrap_or(false);
        if field(record, "purpose").is_err() {
            return false;
        }
        if continued {
            continuation::validate_continuation(words).is_ok()
        } else {
            continuation::validate_prompt(words).is_ok()
        }
    }

    /// `_not_ones_own(record)`: (move, gate, reason) for a record that may not go to its conversation now, or None.
    fn not_ones_own(&self, record: &Map) -> Py<Option<(RecordMove, &'static str, &'static str)>> {
        let thread = text_field(record, "thread_id")?;
        let Some(latest) = self.source.latest(thread)? else {
            return Ok(Some((
                RecordMove::Waiting,
                "identity",
                "not_user_conversation",
            )));
        };
        let superseded = Some((RecordMove::Superseded, "identity", "latest_turn_changed"));
        if purpose_is(record, RecordPurpose::WrapUp)? {
            if !crate::py::eq(get(&latest, "ordinal"), field(record, "ordinal")?)
                || !crate::py::eq(get(&latest, "status"), &Value::from("inProgress"))
            {
                return Ok(superseded);
            }
            return Ok(None);
        }
        if !purpose_is(record, RecordPurpose::Continuation)? {
            return Ok(None);
        }
        let ordinal = field(record, "ordinal")?;
        if !crate::py::eq(get(&latest, "ordinal"), ordinal)
            || !pyval::text(get(&latest, "status")).is_some_and(|status| FINAL.contains(&status))
            || !self
                .source
                .later_turns(thread, ordinal, text_field(record, "marker")?)?
                .is_empty()
        {
            return Ok(superseded);
        }
        Ok(None)
    }

    /// `_record_told(record, move, gate, reason)`: P14 for a record of the plug's.
    pub(crate) fn record_told(
        &mut self,
        record: &Map,
        movement: RecordMove,
        wait: Option<(&str, &str)>,
    ) -> Py<()> {
        let told = match wait {
            None => record.clone(),
            Some((gate, reason)) => with(
                record,
                vec![("gate", Value::from(gate)), ("reason", Value::from(reason))],
            ),
        };
        if ended(movement) {
            let id = text_field(record, "record_id")?.to_owned();
            self.flying().shift_remove(id.as_str());
        }
        self.plug.moved(&Value::Object(told), movement.as_str());
        Ok(())
    }

    /// `_wrap_up_markers()`: the markers of the wrap-ups delivered in each conversation in this process, by thread.
    pub(crate) fn wrap_up_markers(&mut self) -> &mut HashMap<String, BTreeSet<String>> {
        if self.wrap_ups.len() > NOTED_LIMIT {
            self.wrap_ups.clear();
        }
        &mut self.wrap_ups
    }

    /// `persons_turns(thread, turns)`: `turns` less those a wrap-up of this product's started (v0.6.16-beta.3).
    pub fn persons_turns(&mut self, thread: &str, turns: Vec<Map>) -> Vec<Map> {
        let markers: Vec<String> = self
            .wrap_up_markers()
            .get(thread)
            .map(|found| found.iter().cloned().collect())
            .unwrap_or_default();
        if markers.is_empty() {
            return turns;
        }
        turns
            .into_iter()
            .filter(|turn| {
                let ours = match text_of(turn, "turn_id") {
                    Some(turn_id) if !matches!(get(turn, "turn_id"), Value::Null) => self
                        .source
                        .turn_markers(thread, turn_id, &markers)
                        .is_ok_and(|found| !found.is_empty()),
                    _ => false,
                };
                !ours
            })
            .collect()
    }

    /// `_flying()`: the plug's records this engine watched in flight, by id, until each ends.
    pub(crate) fn flying(&mut self) -> &mut Map {
        if self.records_flying.len() > NOTED_LIMIT {
            self.records_flying.clear();
        }
        &mut self.records_flying
    }

    /// `paused_records()`: while recovery is paused, the plug's records core watched in flight, each looked at as its
    /// watch looks, with the plug asked nothing; one that raises costs only itself.
    pub fn paused_records(&mut self) {
        let records: Vec<Value> = self.flying().values().cloned().collect();
        for record in records {
            let thread = match &record {
                Value::Object(record) => text_of(record, "thread_id").map(str::to_owned),
                _ => None,
            };
            let watched = match &record {
                Value::Object(record) => self.watch_record(record),
                _ => Err("TypeError"),
            };
            if watched.is_err() {
                self.log(thread.as_deref(), "plug_record_check_failed", Value::Null);
            }
        }
    }

    fn record_waits(&mut self, record: &Map, gate: &str, reason: &str) -> Py<()> {
        let thread = text_field(record, "thread_id")?.to_owned();
        self.handed_waits
            .insert(Str::from(thread.as_str()), Value::from(reason));
        self.record_told(record, RecordMove::Waiting, Some((gate, reason)))
    }

    /// `_try_record(record)`: the gates for one waiting record, and the one dispatch where every one passes.
    fn try_record(&mut self, record: Map) -> Py<()> {
        let thread = text_field(&record, "thread_id")?.to_owned();
        let now = self.now();
        let settings = self.store.settings()?;
        if !pyval::truthy(get(&settings, "enabled")) || self.managed.disable_auto_resume {
            return self.record_waits(&record, "consent", "paused");
        }
        if !self.store.thread_enabled(&thread)? {
            return self.record_waits(&record, "consent", "thread_disabled");
        }
        if self.observing(&settings) {
            self.record_would_send(&record)?;
            return self.record_waits(&record, "consent", OBSERVE_ONLY);
        }
        if self.quiet_until(now)?.is_some() {
            return self.record_waits(&record, "schedule", QUIET_HOURS);
        }
        let compatibility = (self.engine_state)()?;
        let compatibility = pyval::text(&compatibility);
        if !matches!(
            compatibility,
            Some("verified" | "checked" | "structurally_compatible")
        ) {
            let reason = if matches!(compatibility, Some("incompatible" | "failed_here")) {
                "engine_incompatible"
            } else {
                "engine_unknown"
            };
            return self.record_waits(&record, "engine_compatible", reason);
        }
        if !(self.home_lock)()? {
            return self.record_waits(&record, "single_owner", "home_lock_unavailable");
        }
        let id = text_field(&record, "record_id")?.to_owned();
        if self.store.others_in_flight(&thread, &id)? != 0 {
            return self.record_waits(&record, "submission_safe", "other_recovery_in_flight");
        }
        match self.projection_now(&thread) {
            Some(true) => {}
            Some(false) => return self.record_waits(&record, "identity", "projection_stale"),
            None => return self.record_waits(&record, "identity", "projection_table_missing"),
        }
        if let Some((movement, gate, reason)) = self.not_ones_own(&record)? {
            return self.record_told(&record, movement, Some((gate, reason)));
        }
        let app = self.backend.app_identity()?;
        if !pyval::truthy(&app) {
            let reason = self.no_app_reason();
            return self.record_waits(&record, "thread_available", &reason);
        }
        let loaded = self.backend.loaded(&thread, &app)?;
        if pyval::text(&loaded) != Some("loaded") {
            let reason = if pyval::text(&loaded) == Some("notLoaded") {
                "notLoaded"
            } else {
                "loaded_state_unknown"
            };
            return self.record_waits(&record, "thread_available", reason);
        }
        if self
            .source
            .foreign_queued(&thread, &Engine::record_proof(&record)?)?
            != 0
        {
            return self.record_waits(&record, "no_newer_user_work", "user_input_queued");
        }
        if self.offline() {
            return self.record_waits(&record, "usage", power::OFFLINE);
        }
        let available = available_of(&self.usage()?)?;
        if !matches!(available, Value::Bool(true)) {
            let reason = if matches!(available, Value::Bool(false)) {
                "usage_unavailable"
            } else {
                "usage_unknown"
            };
            return self.record_waits(&record, "usage", reason);
        }
        self.dispatch_record(record, &app)
    }

    /// `_record_would_send(record)`: observe only - the line that says one would have been sent now, once a process.
    fn record_would_send(&mut self, record: &Map) -> Py<()> {
        let id = text_field(record, "record_id")?.to_owned();
        if self.records_noted.contains(&id) {
            return Ok(());
        }
        if self.records_noted.len() >= NOTED_LIMIT {
            self.records_noted.clear();
        }
        self.records_noted.insert(id);
        let thread = text_field(record, "thread_id")?.to_owned();
        self.log(Some(&thread), "plug_record_would_send", Value::Null);
        Ok(())
    }

    /// `dispatch(record, app, None, None, record=True)`: P5 asked, the record carried marker-free or not, its own claim
    /// and pre-send look, and the one send inside `record_guard`. Never on a worker (P12 pools core's own alone).
    fn dispatch_record(&mut self, record: Map, app: &Value) -> Py<()> {
        let lock = self.dispatch_lock.clone();
        let _held = lock.as_ref().map(|lock| lock.lock());
        let sender = self.plug.sender(&Value::Object(record.clone()));
        let carrier = match sender {
            Sender::Backend => Carrier::Backend,
            Sender::Channel { .. } => Carrier::Channel,
        };
        let current = self.record_carried(record, carrier)?;
        let Some((thread, words, now)) = self.record_claim(&current, carrier, app)? else {
            return Ok(());
        };
        let client = Engine::record_client(&current)?;
        let response = {
            let guard = RecordGuard {
                engine: self,
                record: &current,
                now,
            };
            let words = Str::from(words.as_str());
            let sent = car_scheduler::caught(|| match &sender {
                Sender::Backend => self.backend.send(&thread, &words, &guard),
                Sender::Channel { channel, .. } => {
                    guarded_send(channel.as_ref(), &thread, &words, client.as_deref(), &guard)
                }
            });
            match sent {
                Ok(Value::Object(response)) => response,
                _ => crate::py::row(vec![("outcome", Value::from("unknown"))]),
            }
        };
        if self.record_sent(&current, &response).is_err() {
            self.log(Some(&thread), "post_send_bookkeeping_failed", Value::Null);
        }
        Ok(())
    }

    /// `_record_claim(record, sender, app)`: (conversation, words, the guard's time) for the one send, or None where
    /// it waits, was handed back or was sent already.
    fn record_claim(
        &mut self,
        record: &Map,
        carrier: Carrier,
        app: &Value,
    ) -> Py<Option<(String, String, f64)>> {
        if (carrier == Carrier::Backend) != Engine::record_client(record)?.is_none() {
            // A channel the plug named carries only a person's message marker-free, and that message only through it.
            self.record_waits(record, "submission_safe", HELD)?;
            return Ok(None);
        }
        let now = self.now();
        let quiet = self.quiet_until(now)?;
        let (claimed, gate, reason) = self.store.reserve_record(record, now, &self.plug, quiet)?;
        if !claimed {
            self.record_waits(
                record,
                gate.as_deref().unwrap_or_default(),
                reason.as_deref().unwrap_or_default(),
            )?;
            return Ok(None);
        }
        // A look that could not be made is one that failed: the claim is handed back.
        let problem = self.record_problem(record, app).unwrap_or(Some((
            RecordMove::Released,
            "submission_safe",
            "released_before_send",
        )));
        let thread = text_field(record, "thread_id")?.to_owned();
        if let Some((movement, gate, reason)) = problem {
            self.record_told(record, movement, Some((gate, reason)))?;
            self.log(Some(&thread), "plug_record_released", Value::Null);
            return Ok(None);
        }
        self.log(Some(&thread), "plug_record_send_started", Value::Null);
        let words = Engine::record_words(record)?;
        Ok(Some((thread, words, self.now())))
    }

    /// `_record_problem(record, app)`: the last look before the one send - (move, gate, reason) to tell, or None.
    fn record_problem(
        &mut self,
        record: &Map,
        app: &Value,
    ) -> Py<Option<(RecordMove, &'static str, &'static str)>> {
        let thread = text_field(record, "thread_id")?.to_owned();
        let now = self.now();
        let settings = self.store.settings()?;
        if !pyval::truthy(get(&settings, "enabled"))
            || self.managed.disable_auto_resume
            || self.observing(&settings)
            || !self.store.thread_enabled(&thread)?
            || self.quiet_until(now)?.is_some()
        {
            return Ok(Some((
                RecordMove::Released,
                "consent",
                "released_before_send",
            )));
        }
        if !crate::py::eq(&self.backend.app_identity()?, app)
            || pyval::text(&self.backend.loaded(&thread, app)?) != Some("loaded")
        {
            return Ok(Some((
                RecordMove::Released,
                "thread_available",
                "loaded_recheck_failed",
            )));
        }
        if !matches!(available_of(&self.usage()?)?, Value::Bool(true)) {
            return Ok(Some((
                RecordMove::Released,
                "usage",
                "usage_recheck_failed",
            )));
        }
        if self.projection_now(&thread) != Some(true) {
            return Ok(Some((RecordMove::Released, "identity", "projection_stale")));
        }
        if let Some((movement, gate, reason)) = self.not_ones_own(record)? {
            let movement = if movement == RecordMove::Waiting {
                RecordMove::Released
            } else {
                movement
            };
            return Ok(Some((movement, gate, reason)));
        }
        let proof = Engine::record_proof(record)?;
        if self.source.foreign_queued(&thread, &proof)? != 0 {
            return Ok(Some((
                RecordMove::Released,
                "no_newer_user_work",
                "user_input_queued",
            )));
        }
        let presence = self.source.marker_presence(&thread, &proof)?;
        if pyval::truthy(get(&presence, "history")) || pyval::truthy(get(&presence, "queue")) {
            return Ok(Some((
                RecordMove::Sent,
                "submission_safe",
                "duplicate_owner",
            )));
        }
        if !(self.home_lock)()? {
            return Ok(Some((
                RecordMove::Released,
                "single_owner",
                "home_lock_unavailable",
            )));
        }
        Ok(None)
    }

    /// `_record_sent(record, response)`: a launch the guard refused hands it back (RELEASED), a process that never
    /// started waits again (NOT_STARTED), anything else is sent (SENT), never sent again.
    fn record_sent(&mut self, record: &Map, response: &Map) -> Py<()> {
        let movement = if pyval::text(get(response, "outcome")) == Some("not_started") {
            if pyval::text(get(response, "error_code")) == Some("queue_consent_refused") {
                RecordMove::Released
            } else {
                RecordMove::NotStarted
            }
        } else {
            RecordMove::Sent
        };
        let queue_id = match (movement, get(response, "queue_id")) {
            (RecordMove::Sent, Value::Str(queue)) => Value::Str(queue.clone()),
            _ => Value::Null,
        };
        let sent = with(record, vec![("queue_id", queue_id)]);
        self.record_told(&sent, movement, None)?;
        if movement == RecordMove::Sent {
            // Remembered from its send, so a Pause before the next tick that watches it takes it back too (H4).
            let at = self.now();
            let flying = with(
                &sent,
                vec![
                    ("state", Value::from(IN_FLIGHT_RECORD)),
                    ("words", Value::Null),
                    ("sent_at", Value::Float(at)),
                    ("withdraw", Value::Bool(false)),
                ],
            );
            let id = text_field(record, "record_id")?.to_owned();
            self.flying()
                .insert(Str::from(id.as_str()), Value::Object(flying));
        }
        let line = match movement {
            RecordMove::Released => "plug_record_released",
            RecordMove::NotStarted => "plug_record_not_started",
            _ => "plug_record_sent",
        };
        let thread = text_field(record, "thread_id")?.to_owned();
        self.log(Some(&thread), line, Value::Null);
        Ok(())
    }

    /// `_watch_record(record)`: a record of the plug's in flight - delivered, handed over, taken back, kept while Codex
    /// holds it, or unproven a day after it was sent or last seen in Codex's queue.
    fn watch_record(&mut self, record: &Map) -> Py<()> {
        let thread = text_field(record, "thread_id")?.to_owned();
        let proof = Engine::record_proof(record)?;
        if !self.source.marker_rows(&thread, &proof)?.is_empty() {
            if record.get("purpose").and_then(pyval::text) == Some(RecordPurpose::WrapUp.as_str()) {
                let marker = text_field(record, "marker")?.to_owned();
                self.wrap_up_markers()
                    .entry(thread.clone())
                    .or_default()
                    .insert(marker);
            }
            return self.record_told(record, RecordMove::Delivered, None);
        }
        let queue_id = field(record, "queue_id")?.clone();
        let queued = match &queue_id {
            Value::Null => None,
            other => {
                let queue = pyval::text(other).ok_or("TypeError")?;
                Some(self.source.queue_row(&thread, queue, &proof)?)
            }
        };
        let exists = match &queued {
            Some(found) if !found.is_empty() => pyval::truthy(field(found, "exists")?),
            _ => false,
        };
        if exists && !pyval::truthy(field(queued.as_ref().ok_or("KeyError")?, "has_marker")?) {
            // Somebody edited it in Codex's queue: it is theirs now.
            return self.record_told(record, RecordMove::HandedOver, None);
        }
        if exists && self.take_back(record)? {
            return Ok(());
        }
        if exists
            || (matches!(queue_id, Value::Null)
                && !self.source.queued_rows(&thread, &proof)?.is_empty())
        {
            // Codex holds it with its marker: watched, never sent again, and never unproven while it is there.
            let at = self.now();
            let id = text_field(record, "record_id")?.to_owned();
            let kept = with(record, vec![("seen_at", Value::Float(at))]);
            self.flying()
                .insert(Str::from(id.as_str()), Value::Object(kept));
            return Ok(());
        }
        let sent = field(record, "sent_at")?.clone();
        if !matches!(sent, Value::Null) {
            let seen = match record.get("seen_at") {
                Some(seen) if pyval::truthy(seen) => seen.clone(),
                _ => sent.clone(),
            };
            let since = pyval::Num::of(&later_of(&sent, &seen)?)
                .ok_or("TypeError")?
                .as_f64();
            if self.now() - since >= self.options.unknown_reconcile_window_seconds {
                return self.record_told(record, RecordMove::Unproven, None);
            }
        }
        Ok(())
    }
}

/// `usage.get("available")`: AttributeError where usage is not a mapping.
fn available_of(usage: &Value) -> Py<Value> {
    match usage {
        Value::Object(usage) => Ok(get(usage, "available").clone()),
        _ => Err("AttributeError"),
    }
}
