//! `prompt_queue`'s code (seat S7.2e1b; `engine/promptqueue.py`): a person's queued messages go after the current turn,
//! at a time or on a schedule, in order, each once - at P2; a message with pictures goes by its own channel (P5, P15).
//!
//! At P2, each conversation's first prompt still to go alone is eligible: cancelled where its conversation is off or its
//! words would not go; held where the one it depends on ended undelivered; made due (an occurrence, a record of its own)
//! and handed with its words; a series' missed occurrences caught up once; one not sent a day after it could go used as
//! expired; one that waits while a turn runs not handed while the conversation's latest turn is in progress.
//!
//! Its seams: the session of the picture channel ([`super::markerfree::Open`]) and [`TurnRunning`]
//! (`turn_in_progress(paths, thread)`, `codex/turns.py` of the watcher's home). The pictures are the product's own copies
//! in `paths.advanced_dir` (`crate::images`).

use std::path::PathBuf;
use std::sync::Arc;

use car_config::Paths;
use car_machine::json::{Map, Str, Value};
use car_policy::plug::{Alternative, Channel, HookFailed, View};

use super::emptyreply::{enabled, thread_key, word};
use super::markerfree::{Open, no_session, send, text_input};
use crate::capabilities::{Binding, Code, Raised, Said, Spoke};
use crate::state::errors::Result as StateResult;
use crate::state::scoped::Scoped;
use crate::state::sql::{self, Row};
use crate::vocabulary::{
    ArmingWarning, Measurement, PromptEvery, PromptReason, PromptState, PromptTrigger, RecordState,
    WhileRunning,
};

pub const CAPABILITY: &str = "prompt_queue";
pub const LONG: &str = "long_reset_message";
pub const SHORT_LIMIT: usize = 2000;
pub const DUE_FOR: f64 = 86400.0;

/// `PERIODS[every]`: how far apart a series' occurrences fall.
pub fn period(every: &Value) -> Option<i64> {
    match every {
        Value::Str(text) if text.as_str() == Some(PromptEvery::Day.as_str()) => Some(86400),
        Value::Str(text) if text.as_str() == Some(PromptEvery::Week.as_str()) => Some(7 * 86400),
        _ => None,
    }
}

/// `turn_in_progress(paths, thread_id)`: True, False, or None where that cannot be read.
pub type TurnRunning = Arc<dyn Fn(&Value) -> Option<bool> + Send + Sync>;

fn get<'a>(row: &'a Value, name: &str) -> Option<&'a Value> {
    match row {
        Value::Object(map) => map.get(name),
        _ => None,
    }
}

fn or_null(value: Option<&Value>) -> Value {
    value.cloned().unwrap_or(Value::Null)
}

fn is(value: Option<&Value>, text: &str) -> bool {
    matches!(value, Some(Value::Str(held)) if held.as_str() == Some(text))
}

fn with(own: &[(&str, Value)], more: Vec<(&str, Value)>) -> Value {
    let mut map = Map::new();
    for (name, value) in own.iter().cloned().chain(more) {
        map.insert(name.into(), value);
    }
    Value::Object(map)
}

/// `handed(row)`: what core is handed of one prompt's occurrence, or None (moved here from `seam_p7`).
pub fn handed(row: &Value) -> Option<Value> {
    let key = get(row, "record_id")?;
    if matches!(key, Value::Null) || !is(get(row, "state"), PromptState::Ready.as_str()) {
        return None;
    }
    let marker = match key {
        Value::Str(text) => Value::Str(
            car_machine::domain::ids::short_marker(text.as_str().unwrap_or_default()).into(),
        ),
        _ => Value::Null,
    };
    let own = [
        ("record_id", key.clone()),
        ("thread_id", or_null(get(row, "thread_id"))),
        ("marker", marker),
        ("purpose", word("message")),
        ("ordinal", Value::Null),
    ];
    if is(get(row, "record_state"), RecordState::InFlight.as_str()) {
        let sent_at = match get(row, "sent_at") {
            Some(found) if car_machine::pyval::truthy(found) => found.clone(),
            _ => or_null(get(row, "launching_at")),
        };
        return Some(with(
            &own,
            vec![
                ("state", word("in_flight")),
                ("words", Value::Null),
                ("sent_at", sent_at),
                ("queue_id", or_null(get(row, "queue_id"))),
                (
                    "withdraw",
                    Value::Bool(get(row, "withdraw").is_some_and(car_machine::pyval::truthy)),
                ),
            ],
        ));
    }
    if is(get(row, "record_state"), RecordState::Waiting.as_str())
        && get(row, "words").is_some_and(car_machine::pyval::truthy)
    {
        return Some(with(
            &own,
            vec![
                ("state", word("waiting")),
                ("words", or_null(get(row, "words"))),
                ("sent_at", Value::Null),
                ("queue_id", Value::Null),
                ("withdraw", Value::Bool(false)),
            ],
        ));
    }
    None
}

fn number(value: &Value) -> Result<f64, ()> {
    match value {
        Value::Int(int) => int.as_i64().map(|int| int as f64).ok_or(()),
        Value::Float(number) => Ok(*number),
        Value::Bool(flag) => Ok(f64::from(u8::from(*flag))),
        _ => Err(()),
    }
}

/// `a + b` of two numbers as Python adds them: two ints an int, anything else a float.
fn plus(a: &Value, b: i64) -> Result<Value, ()> {
    match a {
        Value::Int(int) => int
            .as_i64()
            .and_then(|int| int.checked_add(b))
            .map(Value::from)
            .ok_or(()),
        Value::Bool(flag) => Ok(Value::from(i64::from(*flag) + b)),
        Value::Float(number) => Ok(Value::Float(number + b as f64)),
        _ => Err(()),
    }
}

/// `could_go(row, queue)`: when a ready occurrence could first go.
pub fn could_go(row: &Row, queue: &[Row]) -> Result<f64, ()> {
    let due = number(sql::get(row, "due_at"))?;
    let waiting = match sql::get(row, "waiting_since") {
        found if car_machine::pyval::truthy(found) => number(found)?,
        _ => due,
    };
    let position = sql::get(row, "position");
    let mut latest = due.max(waiting);
    for other in queue {
        let before = matches!(
            car_machine::pyval::order(sql::get(other, "position"), position),
            Ok(Some(std::cmp::Ordering::Less))
        );
        if before && !matches!(sql::get(other, "finished_at"), Value::Null) {
            latest = latest.max(number(sql::get(other, "finished_at"))?);
        }
    }
    Ok(latest)
}

/// `words_problem(words, long_on)`: words that are no message of a person's that core sends.
pub fn words_problem(words: &Value, long_on: bool) -> bool {
    if car_policy::classify::continuation::validate_prompt(words).is_err() {
        return true;
    }
    !long_on && matches!(words, Value::Str(text) if text.len() > SHORT_LIMIT)
}

fn state_in(row: &Row, states: &[PromptState]) -> bool {
    states
        .iter()
        .any(|state| sql::py_eq(sql::get(row, "state"), &word(state.as_str())))
}

const STILL_TO_GO: [PromptState; 3] = [PromptState::Waiting, PromptState::Ready, PromptState::Held];

/// The picture channel: thread/queue/add with the words, then each copy as a localImage, under its client id.
pub struct ImageChannel {
    images: Vec<String>,
    open: Open,
}

impl Channel for ImageChannel {
    fn send(&self, thread_id: &str, prompt: &Str, client_id: Option<&str>) -> Value {
        let images = self.images.clone();
        send(
            &self.open,
            CAPABILITY,
            thread_id,
            prompt,
            client_id,
            move |prompt| {
                let Value::Array(mut items) = text_input(prompt) else {
                    return Value::Array(Vec::new());
                };
                for path in &images {
                    let mut item = Map::new();
                    item.insert("type".into(), word("localImage"));
                    item.insert("path".into(), word(path));
                    items.push(Value::Object(item));
                }
                Value::Array(items)
            },
        )
    }
    // A picture channel is made fresh, never bound: its `pools()` is MarkerFreeContinuation's with no view - why not.
    fn pools(&self) -> Result<bool, HookFailed> {
        Ok(false)
    }
    fn pools_said(&self) -> Option<Result<Value, HookFailed>> {
        Some(Ok(word(ArmingWarning::Unmeasured.as_str())))
    }
}

/// `PromptQueue(paths, session=None)`.
pub struct PromptQueue {
    pub paths: Paths,
    binding: Option<Binding>,
    open: Open,
    running: TurnRunning,
}

impl PromptQueue {
    pub fn new(paths: Paths, open: Open, running: TurnRunning) -> PromptQueue {
        PromptQueue {
            paths,
            binding: None,
            open,
            running,
        }
    }

    fn folder(&self) -> PathBuf {
        PathBuf::from(&self.paths.advanced_dir)
    }

    fn change(
        &self,
        scoped: &Scoped<'_>,
        prompt_id: &Value,
        fields: &[(&str, Value)],
    ) -> StateResult<()> {
        scoped.handle().prompts_writing()?;
        let changes: Vec<(String, Value)> = fields
            .iter()
            .map(|(name, value)| ((*name).to_owned(), value.clone()))
            .collect();
        scoped.state.change_prompt(prompt_id, &changes)
    }

    /// `holds_for_turn(paths, row)`: a prompt that waits while a turn runs, held now (unknown holds).
    fn holds_for_turn(&self, row: &Row) -> bool {
        if !sql::py_eq(
            sql::get(row, "while_running"),
            &word(WhileRunning::Wait.as_str()),
        ) {
            return false;
        }
        (self.running)(sql::get(row, "thread_id")) != Some(false)
    }

    /// `_held_for_turn(handle, row)`: as `holds_for_turn`, its reason saying so where the turn is known to run.
    fn held_for_turn(&self, scoped: &Scoped<'_>, row: &Row) -> StateResult<bool> {
        if !sql::py_eq(
            sql::get(row, "while_running"),
            &word(WhileRunning::Wait.as_str()),
        ) {
            return Ok(false);
        }
        let running = (self.running)(sql::get(row, "thread_id"));
        if running == Some(true)
            && !sql::py_eq(
                sql::get(row, "reason"),
                &word(PromptReason::TurnRunning.as_str()),
            )
        {
            self.change(
                scoped,
                sql::get(row, "prompt_id"),
                &[("reason", word(PromptReason::TurnRunning.as_str()))],
            )?;
        }
        Ok(running != Some(false))
    }

    /// `_images_held(row)`: a copy no longer sendable, or MIMG failed; False for a message with none.
    fn images_held(&self, scoped: &Scoped<'_>, row: &Row) -> bool {
        let prompt = thread_key(sql::get(row, "prompt_id"));
        if crate::images::of(&self.folder(), &prompt).is_empty() {
            return false;
        }
        scoped.failed(&word(Measurement::Mimg.as_str()))
            || crate::images::problem(&self.folder(), &prompt)
    }

    /// `_sweep(rows)`: every copy whose prompt is no longer still to go removed.
    fn sweep(&self, rows: &[Row]) {
        let pending: Vec<String> = rows
            .iter()
            .filter(|row| state_in(row, &STILL_TO_GO))
            .map(|row| thread_key(sql::get(row, "prompt_id")))
            .collect();
        crate::images::sweep(&self.folder(), &pending);
    }

    /// `_first(handle, view, thread, queue, now, long_on)`: Err is a raise (the conversation is passed over).
    fn first(
        &self,
        scoped: &Scoped<'_>,
        view: &dyn View,
        thread: &Value,
        queue: &[Row],
        now: f64,
        long_on: bool,
    ) -> Result<Option<Value>, ()> {
        let Some(row) = queue.iter().find(|row| state_in(row, &STILL_TO_GO)) else {
            return Ok(None);
        };
        let prompt_id = sql::get(row, "prompt_id").clone();
        if state_in(row, &[PromptState::Held])
            || sql::py_eq(
                sql::get(row, "record_state"),
                &word(RecordState::InFlight.as_str()),
            )
        {
            return Ok(None);
        }
        match enabled(view, thread) {
            None => return Err(()),
            Some(false) => {
                scoped.handle().prompts_writing().map_err(|_| ())?;
                scoped
                    .state
                    .end_prompts(
                        &word(PromptReason::ConversationOff.as_str()),
                        thread,
                        &Value::Null,
                    )
                    .map_err(|_| ())?;
                return Ok(None);
            }
            Some(true) => {}
        }
        let words = sql::get(row, "words");
        if matches!(words, Value::Null) || words_problem(words, long_on) {
            self.change(
                scoped,
                &prompt_id,
                &[
                    ("state", word(PromptState::Cancelled.as_str())),
                    ("reason", word(PromptReason::TooLong.as_str())),
                    ("finished_at", Value::Float(now)),
                ],
            )
            .map_err(|_| ())?;
            return Ok(None);
        }
        if state_in(row, &[PromptState::Ready]) {
            if !matches!(sql::get(row, "due_at"), Value::Null)
                && now - could_go(row, queue)? >= DUE_FOR
            {
                return self.expired(scoped, row, now);
            }
            if self.held_for_turn(scoped, row).map_err(|_| ())? || self.images_held(scoped, row) {
                return Ok(None);
            }
            return Ok(handed(&Value::Object(row.clone())));
        }
        if car_machine::pyval::truthy(sql::get(row, "depends")) {
            let position = sql::get(row, "position");
            let last = queue
                .iter()
                .filter(|other| {
                    matches!(
                        car_machine::pyval::order(sql::get(other, "position"), position),
                        Ok(Some(std::cmp::Ordering::Less))
                    )
                })
                .last();
            if let Some(last) = last {
                if state_in(last, &STILL_TO_GO) {
                    return Ok(None);
                }
                if !sql::py_eq(
                    sql::get(last, "reason"),
                    &word(PromptReason::Delivered.as_str()),
                ) {
                    self.change(
                        scoped,
                        &prompt_id,
                        &[
                            ("state", word(PromptState::Held.as_str())),
                            ("reason", word(PromptReason::DependencyFailed.as_str())),
                        ],
                    )
                    .map_err(|_| ())?;
                    let _ = scoped.count(&word("held"));
                    return Ok(None);
                }
            }
        }
        let mut due = match sql::get(row, "due_at") {
            Value::Null => Value::Float(now),
            found => found.clone(),
        };
        let due_at = number(&due)?;
        if now < due_at {
            return Ok(None);
        }
        let turn = self.held_for_turn(scoped, row).map_err(|_| ())?;
        if turn || self.images_held(scoped, row) {
            let recurring = sql::py_eq(
                sql::get(row, "trigger"),
                &word(PromptTrigger::Recurring.as_str()),
            );
            if (!turn || !recurring) && now - due_at >= DUE_FOR {
                return self.expired(scoped, row, now);
            }
            return Ok(None);
        }
        if sql::py_eq(
            sql::get(row, "trigger"),
            &word(PromptTrigger::Recurring.as_str()),
        ) {
            match self.catch_up(scoped, row, &due, now)? {
                Some(latest) => due = latest,
                None => return Ok(None),
            }
        }
        let key = word(&scoped.state.tokens.hex(32));
        if !scoped
            .handle()
            .prompts_occur(&prompt_id, &key, thread, &due)
            .map_err(|_| ())?
        {
            return Ok(None);
        }
        let _ = scoped.count(&word("due"));
        let fresh = scoped.state.prompt(&prompt_id).map_err(|_| ())?;
        Ok(fresh.and_then(|fresh| handed(&Value::Object(fresh))))
    }

    /// `_catch_up(handle, row, due, now)`: the latest occurrence that fell, the earlier counted as used; None where the
    /// series ended.
    fn catch_up(
        &self,
        scoped: &Scoped<'_>,
        row: &Row,
        due: &Value,
        now: f64,
    ) -> Result<Option<Value>, ()> {
        let period = period(sql::get(row, "every")).ok_or(())?;
        let late = ((now - number(due)?) / period as f64).floor() as i64;
        if late <= 0 {
            return Ok(Some(due.clone()));
        }
        let sent = column_int(row, "sent_count")?;
        let occurrences = column_int(row, "occurrences")?;
        let used = (sent + late).min(occurrences);
        let latest = plus(due, late * period)?;
        let until = sql::get(row, "until");
        let past = !matches!(until, Value::Null) && number(&latest)? > number(until)?;
        let prompt_id = sql::get(row, "prompt_id");
        if used >= occurrences || past {
            self.change(
                scoped,
                prompt_id,
                &[
                    ("state", word(PromptState::Done.as_str())),
                    ("reason", word(PromptReason::Missed.as_str())),
                    ("sent_count", Value::from(used)),
                    ("finished_at", Value::Float(now)),
                ],
            )
            .map_err(|_| ())?;
            let _ = scoped.count(&word("missed"));
            return Ok(None);
        }
        self.change(
            scoped,
            prompt_id,
            &[
                ("sent_count", Value::from(used)),
                ("due_at", latest.clone()),
            ],
        )
        .map_err(|_| ())?;
        let _ = scoped.count(&word("missed"));
        Ok(Some(latest))
    }

    /// `_expired(handle, row, now)`: an occurrence not sent a day after it fell due, used as expired.
    fn expired(&self, scoped: &Scoped<'_>, row: &Row, now: f64) -> Result<Option<Value>, ()> {
        let record = sql::get(row, "record_id");
        if !matches!(record, Value::Null) {
            scoped.handle().prompts_drop(record).map_err(|_| ())?;
        }
        let recurring = sql::py_eq(
            sql::get(row, "trigger"),
            &word(PromptTrigger::Recurring.as_str()),
        );
        let period = if recurring {
            period(sql::get(row, "every"))
        } else {
            None
        };
        let used = column_int(row, "sent_count")? + 1;
        let following = match period {
            Some(period) => Some(plus(sql::get(row, "due_at"), period)?),
            None => None,
        };
        let until = sql::get(row, "until");
        let ended = match &following {
            None => true,
            Some(following) => {
                used >= column_int(row, "occurrences")?
                    || (!matches!(until, Value::Null) && number(following)? > number(until)?)
            }
        };
        let prompt_id = sql::get(row, "prompt_id");
        if ended {
            self.change(
                scoped,
                prompt_id,
                &[
                    ("state", word(PromptState::Done.as_str())),
                    ("reason", word(PromptReason::Expired.as_str())),
                    ("sent_count", Value::from(used)),
                    ("finished_at", Value::Float(now)),
                ],
            )
            .map_err(|_| ())?;
        } else {
            self.change(
                scoped,
                prompt_id,
                &[
                    ("state", word(PromptState::Waiting.as_str())),
                    ("reason", word(PromptReason::Expired.as_str())),
                    ("sent_count", Value::from(used)),
                    ("record_id", Value::Null),
                    ("due_at", following.unwrap_or(Value::Null)),
                ],
            )
            .map_err(|_| ())?;
        }
        let _ = scoped.count(&word("expired"));
        Ok(None)
    }

    /// `images_of(record)`: the copies' paths of the message whose occurrence is `record`, in order.
    fn images(&self, record: &Value) -> Vec<String> {
        let ours = matches!(record, Value::Object(map)
            if matches!(map.get("record_id"), Some(Value::Str(_))) && !map.contains_key("interruption_id"));
        let Some(binding) = &self.binding else {
            return Vec::new();
        };
        if !ours {
            return Vec::new();
        }
        let key = or_null(get(record, "record_id"));
        binding
            .with(|scoped| {
                let Ok(rows) = scoped.state.prompts(&Value::Null, &Value::Bool(true)) else {
                    return Vec::new();
                };
                for row in rows {
                    if sql::py_eq(sql::get(&row, "record_id"), &key) {
                        let prompt = thread_key(sql::get(&row, "prompt_id"));
                        return crate::images::of(&self.folder(), &prompt)
                            .into_iter()
                            .map(|(_, path)| path)
                            .collect();
                    }
                }
                Vec::new()
            })
            .unwrap_or_default()
    }
}

fn column_int(row: &Row, name: &str) -> Result<i64, ()> {
    match sql::get(row, name) {
        Value::Int(int) => int.as_i64().ok_or(()),
        Value::Bool(flag) => Ok(i64::from(*flag)),
        _ => Err(()),
    }
}

/// Each conversation's rows, in the order its first row comes.
fn by_thread(rows: Vec<Row>) -> Vec<(Value, Vec<Row>)> {
    let mut found: Vec<(Value, Vec<Row>)> = Vec::new();
    for row in rows {
        let thread = sql::get(&row, "thread_id").clone();
        match found.iter_mut().find(|(held, _)| sql::py_eq(held, &thread)) {
            Some((_, queue)) => queue.push(row),
            None => found.push((thread, vec![row])),
        }
    }
    found
}

impl Code for PromptQueue {
    fn bind(&mut self, binding: Binding) -> Option<Result<(), Raised>> {
        self.binding = Some(binding);
        Some(Ok(()))
    }

    /// P2: each conversation's first prompt still to go, made due and handed with its words where it is due.
    fn records(&mut self, view: &dyn View) -> Spoke {
        let Some(binding) = &self.binding else {
            return Ok(Said::Defer);
        };
        let found = binding.with(|scoped| {
            if !scoped.handle().is_on() {
                return None;
            }
            let rows = scoped.state.prompts(&Value::Null, &Value::Null).ok()?;
            let now = scoped.now();
            self.sweep(&rows);
            let long_on = scoped.armed(&word(LONG));
            let mut found = Vec::new();
            for (thread, queue) in by_thread(rows) {
                if let Ok(Some(record)) = self.first(scoped, view, &thread, &queue, now, long_on) {
                    found.push(record);
                }
            }
            Some(found)
        });
        Ok(match found.flatten() {
            Some(records) if !records.is_empty() => Said::Value(Value::Array(records)),
            _ => Said::Defer,
        })
    }

    /// While watched: the prompt id of each conversation's first prompt still to go that `_first` would make due and
    /// hand now, from the stored rows alone. Err is a raise.
    fn watched_due(&mut self, view: &dyn View) -> Option<Spoke> {
        let Some(binding) = &self.binding else {
            return Some(Ok(Said::Value(Value::Array(Vec::new()))));
        };
        let found = binding.with(|scoped| -> Result<Vec<Value>, Raised> {
            let rows = scoped
                .state
                .prompts(&Value::Null, &Value::Null)
                .map_err(|error| Raised::new(error.class()))?;
            let now = scoped.now();
            let long_on = scoped.armed(&word(LONG));
            let mut found = Vec::new();
            for (thread, queue) in by_thread(rows) {
                let Some(row) = queue
                    .iter()
                    .find(|row| state_in(row, &[PromptState::Waiting, PromptState::Ready]))
                else {
                    continue;
                };
                if sql::py_eq(
                    sql::get(row, "record_state"),
                    &word(RecordState::InFlight.as_str()),
                ) {
                    continue;
                }
                let on = match enabled(view, &thread) {
                    Some(on) => on,
                    None => return Err(Raised::new("Exception")),
                };
                let words = sql::get(row, "words");
                if !on || matches!(words, Value::Null) || words_problem(words, long_on) {
                    continue;
                }
                if car_machine::pyval::truthy(sql::get(row, "depends")) {
                    let position = sql::get(row, "position");
                    let last = queue
                        .iter()
                        .filter(|other| {
                            matches!(
                                car_machine::pyval::order(sql::get(other, "position"), position),
                                Ok(Some(std::cmp::Ordering::Less))
                            )
                        })
                        .last();
                    if let Some(last) = last
                        && (state_in(last, &STILL_TO_GO)
                            || !sql::py_eq(
                                sql::get(last, "reason"),
                                &word(PromptReason::Delivered.as_str()),
                            ))
                    {
                        continue;
                    }
                }
                let due = match sql::get(row, "due_at") {
                    Value::Null => now,
                    found => number(found).map_err(|()| Raised::new("TypeError"))?,
                };
                if now >= due && !self.holds_for_turn(row) {
                    found.push(word(&format!(
                        "{}:{}",
                        thread_key(sql::get(row, "prompt_id")),
                        due.trunc() as i64
                    )));
                }
            }
            Ok(found)
        });
        Some(match found {
            None => Ok(Said::Value(Value::Array(Vec::new()))),
            Some(Ok(found)) => Ok(Said::Value(Value::Array(found))),
            Some(Err(raised)) => Err(raised),
        })
    }

    /// P5: the picture channel for an occurrence of a message with pictures; nothing for anything else.
    fn sender(&mut self, record: &Value) -> Spoke {
        let images = self.images(record);
        if images.is_empty() {
            return Ok(Said::Defer);
        }
        Ok(Said::Channel(Box::new(ImageChannel {
            images,
            open: self.open.clone(),
        })))
    }

    /// P15: no marker for a message with pictures.
    fn delivery(&mut self, record: &Value) -> Spoke {
        Ok(if self.images(record).is_empty() {
            Said::Defer
        } else {
            Said::Word(Alternative::ClientId)
        })
    }

    fn images_of(&mut self, record: &Value) -> Option<Spoke> {
        let images = self.images(record);
        Some(Ok(Said::Value(Value::Array(
            images.iter().map(|path| word(path)).collect(),
        ))))
    }
}

/// `make(paths)`: the capability's code with no session and no turn history known here (every waiting prompt held).
pub fn make(paths: &Paths) -> Option<Box<dyn Code>> {
    make_with(paths, no_session(), Arc::new(|_| None))
}

/// `PromptQueue(paths, session=...)` with an entry point's or a test's own session and turn history.
pub fn make_with(paths: &Paths, open: Open, running: TurnRunning) -> Option<Box<dyn Code>> {
    Some(Box::new(PromptQueue::new(paths.clone(), open, running)))
}
