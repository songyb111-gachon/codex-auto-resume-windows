//! `engine/resetmessage.py` (seat S7.2d): a message of a person's own, sent to the conversation they picked when the
//! window they picked resets (v0.6.14) - reset_message, at P8, P2 and P3.
//!
//! * P8, the errand: the usage windows counted and the rules adopted ([`super::resetwatch`]).
//! * P2: the windows closed by time first, then every message due handed core with its words, every one in flight to
//!   be watched; one whose conversation is off is cancelled, one unsent eight days after it was written or a day after
//!   it fell due (counted on from the claim's pace, `waiting_since`) has expired. From v0.6.26 one due in a conversation
//!   usage_pause stopped, whose continuation after the reset waits there, is the stop's turn to carry
//!   ([`carried_by_stop`]); while the stop holds it, it does not expire.
//! * P3 `usage`: a core record of the same conversation is held while one of its messages is due or in flight, and
//!   while one counts for the very reset that record waits for - at most HOLD_FOR after it fell due.

use std::sync::{Arc, Mutex, PoisonError};

use car_config::Paths;
use car_machine::json::Value;
use car_policy::plug::{Alternative, Errand, Guards, HookFailed, View};

use super::credits::Opener;
use super::resetwatch::{self, Failed, Family, Resets, Row, TOL, Watch, num};
use super::usage::{Bound, cell, is_time, is_word};
use crate::capabilities::{Binding, Code, Raised, Said, Spoke};
use crate::codex::credits;
use crate::codex::session::Channel;

pub const CAPABILITY: &str = "reset_message";
pub const LONG: &str = "long_reset_message";
/// A message's words, at most: A27's 2,000 characters, unless Longer reset messages is on.
pub const SHORT_LIMIT: usize = 2000;
/// How long one waits to be sent, at most: eight days from when it was written, a day from when it fell due.
pub const KEEP_FOR: f64 = 8.0 * 86400.0;
pub const DUE_FOR: f64 = 86400.0;
/// How long a core record of its conversation is held for one due or being sent, at most.
pub const HOLD_FOR: f64 = 1800.0;
pub const USAGE: &str = "usage";
pub const PAUSE: &str = "usage_pause";

fn field<'a>(row: &'a Row, name: &str) -> &'a Value {
    cell(row, name)
}

fn eq(one: &Value, other: &Value) -> bool {
    car_machine::pyval::eq(one, other)
}

/// `isinstance(value, (int, float))` (a bool among them).
fn numeric(value: &Value) -> bool {
    matches!(value, Value::Int(_) | Value::Float(_) | Value::Bool(_))
}

/// `carried_by_stop(rule, stops)`: whether a message due is the forced stop's turn to carry - usage_pause stopped its
/// conversation and that stop's continuation after the reset still waits there, made before the message fell due.
pub fn carried_by_stop(rule: &Row, stops: &[Row]) -> Result<bool, Raised> {
    let due = field(rule, "due_at");
    if !is_time(due) {
        return Ok(false);
    }
    for stop in stops {
        let created = field(stop, "created_at");
        if is_word(field(stop, "capability"), PAUSE)
            && is_word(field(stop, "kind"), "after_reset")
            && eq(field(stop, "thread_id"), field(rule, "thread_id"))
            && matches!(field(stop, "finished_at"), Value::Null)
            && is_word(field(stop, "record_state"), "waiting")
            && numeric(created)
            && num(due)? >= num(created)?
        {
            return Ok(true);
        }
    }
    Ok(false)
}

/// `handed(rule)`: what core is handed of one message, or None.
pub fn handed(rule: &Row) -> Option<Value> {
    crate::seam_p7::reset_message_handed(&Value::Object(rule.clone()))
}

/// `ResetMessage._same_reset(rule, row, record, now)`: whether a counting message falls due at the reset a usage-limit
/// record of core's waits for - its next reset is its occasion, the window open now resets when the record's reset is,
/// not yet HOLD_FOR past.
pub fn same_reset(rule: &Row, row: Option<&Row>, record: &Value, now: f64) -> Result<bool, Raised> {
    let reset_at = super::usage::get_of(record, "reset_at")?;
    let Some(row) = row else { return Ok(false) };
    if !is_word(field(rule, "state"), "counting")
        || matches!(field(rule, "base"), Value::Null)
        || !is_word(super::usage::field(record, "category"), "usage_limit")
        || !numeric(reset_at)
        || matches!(field(row, "open_reset_at"), Value::Null)
    {
        return Ok(false);
    }
    let opened = num(field(row, "open_reset_at"))?;
    Ok(
        num(field(row, "resets"))? + 1.0
            >= num(field(rule, "base"))? + num(field(rule, "ordinal"))?
            && (num(reset_at)? - opened).abs() <= TOL as f64
            && now < opened + HOLD_FOR,
    )
}

fn failed(error: Failed) -> Raised {
    error.raised()
}

/// What the code keeps: its turn of the waiting messages.
pub struct Inner {
    pub paths: Paths,
    bound: Option<Bound>,
    open: Opener,
    pub turn: usize,
}

/// `ResetMessage(paths, session=None)`.
pub struct ResetMessage {
    inner: Arc<Mutex<Inner>>,
}

struct MessageErrand {
    inner: Arc<Mutex<Inner>>,
}

impl Errand for MessageErrand {
    fn run(&self, view: &dyn View, _guards: &mut Guards<'_>) -> Result<Value, HookFailed> {
        let inner = self.inner.lock().unwrap_or_else(PoisonError::into_inner);
        inner.look(view).map_err(|_| HookFailed)
    }
}

impl ResetMessage {
    pub fn new(paths: Paths, open: Opener) -> ResetMessage {
        ResetMessage {
            inner: Arc::new(Mutex::new(Inner {
                paths,
                bound: None,
                open,
                turn: 0,
            })),
        }
    }

    pub fn bind_to(&mut self, bound: Bound) {
        self.lock().bound = Some(bound);
    }

    fn lock(&self) -> std::sync::MutexGuard<'_, Inner> {
        self.inner.lock().unwrap_or_else(PoisonError::into_inner)
    }

    /// The errand's look, as a probe runs it.
    pub fn look(&self, view: &dyn View) -> Result<Value, Raised> {
        self.lock().look(view)
    }
}

impl Inner {
    fn resets(&self) -> Option<Resets> {
        self.bound.clone().map(|bound| Resets { bound })
    }

    fn count(&self, code: &str) {
        if let Some(bound) = &self.bound {
            bound.count(code);
        }
    }

    fn measured(&self, measurement: &str, passed: bool) -> bool {
        self.bound
            .as_ref()
            .and_then(|bound| {
                bound.with(|scoped| {
                    let word = Value::from(measurement);
                    if passed {
                        scoped.passed(&word)
                    } else {
                        scoped.failed(&word)
                    }
                })
            })
            .unwrap_or(false)
    }

    fn armed(&self, other: &str) -> bool {
        self.bound.as_ref().is_some_and(|bound| bound.armed(other))
    }

    /// `look(view)`: one look of the tracker's, this edition's own reading made where it is due, each reading in a
    /// session of its own closed at the look's end.
    pub fn look(&self, view: &dyn View) -> Result<Value, Raised> {
        let Some(handle) = self.resets() else {
            return Err(Raised::new("AttributeError"));
        };
        if !handle.on() {
            return Ok(Value::Null);
        }
        let mut opened: Vec<Box<dyn Channel>> = Vec::new();
        let early = !self.measured("mu", false);
        let light = self.measured("mu", true);
        let looked = {
            let open = self.open.clone();
            let paths = self.paths.clone();
            let opened = &mut opened;
            let mut reader = move |params: &Value| -> Result<Value, Raised> {
                let mut session =
                    open(&paths, CAPABILITY).map_err(|error| Raised::new(error.class()))?;
                session
                    .enter()
                    .map_err(|error| Raised::new(error.class()))?;
                let reply = session.call(credits::READ, Some(params.clone()));
                opened.push(session);
                reply.map_err(|error| Raised::new(error.class()))
            };
            let mut watch = Watch {
                resets: &handle,
                reader: Some(&mut reader),
                early,
                light,
                keep_credits: false,
            };
            watch.step(Some(view), false)
        };
        for mut session in opened {
            session.exit();
        }
        let looked = looked?;
        for (_, events) in &looked.events {
            for event in events {
                if *event == "gap" || *event == "gone" {
                    self.count(event);
                }
            }
        }
        Ok(Value::Null)
    }

    /// `_ended(rule, view, now)`: (state, reason) a message not yet sent ends with now, or None.
    fn ended(
        &self,
        rule: &Row,
        view: &dyn View,
        now: f64,
    ) -> Result<Option<(&'static str, &'static str)>, Raised> {
        let thread = car_machine::pytext::py_str(field(rule, "thread_id"));
        let on = view.thread_enabled(&thread).unwrap_or(true);
        if !on {
            return Ok(Some(("cancelled", "conversation_off")));
        }
        let created = num(field(rule, "created_at"))?;
        let due = field(rule, "due_at");
        let waited = if now - created >= KEEP_FOR || matches!(due, Value::Null) {
            false
        } else {
            let since = field(rule, "waiting_since");
            let since = if car_machine::pyval::truthy(since) {
                since.clone()
            } else {
                Value::from(0)
            };
            let latest = if car_machine::pyval::greater(&since, due)
                .map_err(|_| Raised::new("TypeError"))?
            {
                since
            } else {
                due.clone()
            };
            now - num(&latest)? >= DUE_FOR
        };
        if (now - created >= KEEP_FOR || waited) && !self.held_by_stop(rule, now)? {
            return Ok(Some(("done", "expired")));
        }
        if let Value::Str(words) = field(rule, "words")
            && words.len() > SHORT_LIMIT
            && !self.armed(LONG)
        {
            return Ok(Some(("cancelled", "turned_off")));
        }
        Ok(None)
    }

    /// `_stop_carries(rule)`: whether a message due waits for the forced stop's turn after the reset to carry it,
    /// usage_pause on; held that look where usage_pause's continuations cannot be read.
    fn stop_carries(&self, rule: &Row) -> bool {
        if !is_word(field(rule, "state"), "ready")
            || !is_word(field(rule, "record_state"), "waiting")
            || !car_machine::pyval::truthy(field(rule, "words"))
        {
            return false;
        }
        if !self.armed(PAUSE) {
            return false;
        }
        let Some(bound) = &self.bound else {
            return true;
        };
        match bound.call(|scoped| {
            scoped.continuations_of(
                &Value::from(PAUSE),
                field(rule, "thread_id"),
                &Value::Bool(true),
            )
        }) {
            Ok(stops) => carried_by_stop(rule, &stops).unwrap_or(true),
            Err(_) => true,
        }
    }

    /// `_held_by_stop(rule, now)`: whether a message that would expire is held by the forced stop instead.
    fn held_by_stop(&self, rule: &Row, now: f64) -> Result<bool, Raised> {
        let state = field(rule, "state");
        if !(is_word(state, "ready") || is_word(state, "counting"))
            || !is_word(field(rule, "record_state"), "waiting")
            || !car_machine::pyval::truthy(field(rule, "words"))
        {
            return Ok(false);
        }
        if self.stop_carries(rule) {
            return Ok(true);
        }
        let due = field(rule, "due_at");
        let due = if is_time(due) {
            Some(due.clone())
        } else {
            None
        };
        let Some(bound) = &self.bound else {
            return Ok(false);
        };
        let armed = bound.armed(PAUSE);
        let stops = match bound.call(|scoped| {
            scoped.continuations_of(&Value::from(PAUSE), field(rule, "thread_id"), &Value::Null)
        }) {
            Ok(stops) => stops,
            Err(_) => return Ok(false),
        };
        let stops: Vec<Row> = stops
            .into_iter()
            .filter(|stop| {
                is_word(field(stop, "kind"), "after_reset") && numeric(field(stop, "created_at"))
            })
            .collect();
        if armed
            && stops.iter().any(|stop| {
                matches!(field(stop, "finished_at"), Value::Null)
                    && is_word(field(stop, "record_state"), "waiting")
            })
        {
            return Ok(true);
        }
        let since = match &due {
            Some(due) => num(due)?,
            None => num(field(rule, "created_at"))?,
        };
        for stop in &stops {
            let finished = field(stop, "finished_at");
            if !numeric(finished) {
                continue;
            }
            let finished = num(finished)?;
            if finished >= since
                && due.as_ref().map_or(Ok(true), |due| {
                    Ok::<bool, Raised>(num(field(stop, "created_at"))? <= num(due)?)
                })?
                && now - finished < DUE_FOR
            {
                return Ok(true);
            }
        }
        Ok(false)
    }

    fn watch<'a>(&self, resets: &'a Resets) -> Watch<'a> {
        Watch {
            resets,
            reader: None,
            early: !self.measured("mu", false),
            light: self.measured("mu", true),
            keep_credits: false,
        }
    }

    fn records(&mut self, view: &dyn View) -> Spoke {
        let Some(handle) = self.resets() else {
            return Ok(Said::Defer);
        };
        let rows = self.watch(&handle).by_time()?;
        let now = handle.now();
        let mut found = Vec::new();
        let mut waiting = Vec::new();
        for rule in handle
            .reset_rules(Some(CAPABILITY), &Value::Bool(true))
            .map_err(failed)?
        {
            let mut rule = rule;
            if is_word(field(&rule, "record_state"), "in_flight") {
                if !matches!(field(&rule, "words"), Value::Null)
                    && !matches!(field(&rule, "launching_at"), Value::Null)
                {
                    let launching = field(&rule, "launching_at").clone();
                    handle
                        .change_rule(
                            field(&rule, "rule_id"),
                            &Value::from("ready"),
                            &[("sent_at", launching.clone())],
                        )
                        .map_err(failed)?;
                    rule = resetwatch::with(&rule, &[("sent_at", launching)]);
                }
                if let Some(record) = handed(&rule) {
                    found.push(record);
                }
                continue;
            }
            if let Some((state, reason)) = self.ended(&rule, view, now)? {
                handle
                    .end_rule(field(&rule, "rule_id"), state, reason)
                    .map_err(failed)?;
                if reason == "expired" {
                    self.count("expired");
                }
                continue;
            }
            let family: Family = (
                field(&rule, "bucket").clone(),
                field(&rule, "minutes").clone(),
            );
            if resetwatch::due(&rule, resetwatch::find(&rows, &family))? {
                handle
                    .change_rule(
                        field(&rule, "rule_id"),
                        &Value::from("counting"),
                        &[
                            ("state", Value::from("ready")),
                            ("due_at", Value::from(now)),
                        ],
                    )
                    .map_err(failed)?;
                rule = resetwatch::with(
                    &rule,
                    &[
                        ("state", Value::from("ready")),
                        ("due_at", Value::from(now)),
                    ],
                );
                self.count("due");
            }
            if self.stop_carries(&rule) {
                continue;
            }
            if let Some(record) = handed(&rule) {
                waiting.push(record);
            }
        }
        if !waiting.is_empty() {
            let start = (self.turn * car_policy::plug::hands::RECORDS_LIMIT) % waiting.len();
            waiting.rotate_left(start);
            self.turn += 1;
        }
        found.extend(waiting);
        if found.is_empty() {
            return Ok(Said::Defer);
        }
        Ok(Said::Value(Value::Array(found)))
    }

    fn watched_due(&self, view: &dyn View) -> Spoke {
        let Some(handle) = self.resets() else {
            return Ok(Said::Value(Value::Array(Vec::new())));
        };
        let now = Value::from(handle.now());
        let mut rows: Vec<(Family, Row)> = Vec::new();
        for (family, row) in handle.windows().map_err(failed)? {
            rows.push((family, resetwatch::by_time(&row, &now)?.0));
        }
        let mut found = Vec::new();
        for rule in handle
            .reset_rules(Some(CAPABILITY), &Value::Bool(true))
            .map_err(failed)?
        {
            if is_word(field(&rule, "record_state"), "in_flight")
                || matches!(field(&rule, "words"), Value::Null)
            {
                continue;
            }
            let thread = car_machine::pytext::py_str(field(&rule, "thread_id"));
            if !view.thread_enabled(&thread).unwrap_or(true) {
                continue;
            }
            let family: Family = (
                field(&rule, "bucket").clone(),
                field(&rule, "minutes").clone(),
            );
            if is_word(field(&rule, "state"), "ready")
                || resetwatch::due(&rule, resetwatch::find(&rows, &family))?
            {
                let id = field(&rule, "rule_id");
                let Value::Int(id) = id else {
                    return Err(Raised::new("TypeError"));
                };
                found.push(Value::from(format!("rule:{id}")));
            }
        }
        Ok(Said::Value(Value::Array(found)))
    }

    fn gate(&self, name: &Value, record: &Value) -> Spoke {
        let Some(handle) = self.resets() else {
            return Ok(Said::Defer);
        };
        if !is_word(name, USAGE) || !matches!(record, Value::Object(_)) {
            return Ok(Said::Defer);
        }
        let thread = super::usage::field(record, "thread_id");
        let read = (|| -> Result<(Vec<Row>, Vec<(Family, Row)>, f64), Failed> {
            let rules: Vec<Row> = handle
                .reset_rules(Some(CAPABILITY), &Value::Bool(true))?
                .into_iter()
                .filter(|rule| eq(field(rule, "thread_id"), thread))
                .collect();
            let rows = if rules.is_empty() {
                Vec::new()
            } else {
                handle.windows()?
            };
            Ok((rules, rows, handle.now()))
        })();
        let Ok((rules, rows, now)) = read else {
            return Ok(Said::Defer);
        };
        for rule in &rules {
            if is_word(field(rule, "state"), "ready")
                || is_word(field(rule, "record_state"), "in_flight")
            {
                let due = field(rule, "due_at");
                if !matches!(due, Value::Null) && (0.0..HOLD_FOR).contains(&(now - num(due)?)) {
                    return Ok(Said::Word(Alternative::Hold));
                }
                continue;
            }
            let family: Family = (
                field(rule, "bucket").clone(),
                field(rule, "minutes").clone(),
            );
            if same_reset(rule, resetwatch::find(&rows, &family), record, now)? {
                return Ok(Said::Word(Alternative::Hold));
            }
        }
        Ok(Said::Defer)
    }
}

impl Code for ResetMessage {
    fn bind(&mut self, binding: Binding) -> Option<Result<(), Raised>> {
        self.lock().bound = Some(Bound::of(binding));
        Some(Ok(()))
    }

    /// P8: an errand while a rule of this capability waits.
    fn tick(&mut self, _view: &dyn View) -> Spoke {
        {
            let inner = self.lock();
            let Some(handle) = inner.resets() else {
                return Ok(Said::Defer);
            };
            match handle.reset_rules(Some(CAPABILITY), &Value::Bool(true)) {
                Ok(found) if !found.is_empty() => {}
                _ => return Ok(Said::Defer),
            }
        }
        Ok(Said::Errand(Box::new(MessageErrand {
            inner: self.inner.clone(),
        })))
    }

    /// P2: the windows closed by time first, then every message due, with its words, and every one in flight.
    fn records(&mut self, view: &dyn View) -> Spoke {
        self.lock().records(view)
    }

    /// While watched: the id of each message whose reset has come by the windows as last stored, or that is due.
    fn watched_due(&mut self, view: &dyn View) -> Option<Spoke> {
        Some(self.lock().watched_due(view))
    }

    /// P3 `usage`: HOLD a core record of a conversation one of these messages is due or in flight in, or one that
    /// counts for the very reset that record waits for.
    fn gate(&mut self, name: &Value, record: &Value, _facts: &Value) -> Spoke {
        self.lock().gate(name, record)
    }
}

/// `make(paths)`: the capability's code for one installation, its session the product's own.
pub fn make(paths: &Paths) -> Option<Box<dyn Code>> {
    Some(Box::new(ResetMessage::new(
        paths.clone(),
        super::usage::World::installed().open,
    )))
}

/// `LongMessages(paths)`: Longer reset messages, an action - nothing of it runs.
pub struct LongMessages {
    pub paths: Paths,
}

impl Code for LongMessages {}

/// `make_long(paths)`.
pub fn make_long(paths: &Paths) -> Option<Box<dyn Code>> {
    Some(Box::new(LongMessages {
        paths: paths.clone(),
    }))
}
