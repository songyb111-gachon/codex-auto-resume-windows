//! `control/actions.py`: what a person asks for, and nothing that sends.
//!
//! Every method here changes a flag, a schedule or a budget. None of them hands anything to Codex: the watcher is
//! the only thing that does. A look-now is asked of a running watcher through [`Host::signal`](crate::host::Host),
//! and Rescan's judge is the watcher's own rules, handed in through [`Host::rescan_judge`](crate::host::Host).

use car_machine::domain::public;
use car_machine::json::{Map, Str, Value};
use car_machine::pyval;
use car_machine::vocab_gen::domain_states::{CLAIMED, OBSERVING, TERMINAL, WAITING};
use car_policy::classify::{gates, power, projects, quiet};
use car_policy::settings::homes;
use car_store::Store;
use car_store::actions::{RECHECKED, RETIRED, UNRESOLVED};
use car_store::errors::Error as StoreError;
use car_store::schedule::{USAGE_BY_RESCAN, USAGE_BY_RETRY};
use car_store::value::{Row, get, number, text_of};

use crate::error::{
    ControlError, Failure, REFUSALS_POSTPONE, REFUSALS_RELEASE, REFUSALS_RESTORE, REFUSALS_RETRY,
    REFUSALS_UNPOSTPONE, Res, interruption_id, refusal, refuse, thread_id,
};
use crate::host::{Event, Judge};
use crate::layer::{Control, State, from_store};
use crate::oncewords::{OnceWords, Put};

/// `CHANGED`: a record that moved meanwhile, which Rescan leaves as it is.
pub const CHANGED: &str = "changed";
/// `CANCEL_RETRY_SECONDS`: a cancel tries again for this long in total while the watcher is writing.
pub const CANCEL_RETRY_SECONDS: f64 = 30.0;
/// The pause between two tries of a cancel (`time.sleep(0.5)`).
pub const CANCEL_PAUSE_SECONDS: f64 = 0.5;

/// `_NOT_CHECKED_NOTES`: why Retry now asked for no usage reading, in the reply's note.
fn not_checked_note(why: &str) -> &'static str {
    match why {
        "paused" => "recovery is paused",
        "conversation_off" => "recovery is off for this conversation",
        "observe_only" => "Observe only is on",
        "quiet_hours" => "it is quiet hours",
        _ => "Windows reports no internet",
    }
}

fn key(name: &str) -> Str {
    Str::from(name)
}

fn object(pairs: Vec<(&str, Value)>) -> Value {
    let mut map = Map::new();
    for (name, value) in pairs {
        map.insert(key(name), value);
    }
    Value::Object(map)
}

fn state_of(row: &Row) -> &str {
    text_of(row, "state").unwrap_or_default()
}

fn among(row: &Row, states: &[&str]) -> bool {
    states.contains(&state_of(row))
}

/// `(value or 0)` as a number, for the comparisons `_reads_usage` and Retry now's note make.
fn or_zero(value: &Value) -> f64 {
    if pyval::truthy(value) {
        number(value).unwrap_or(0.0)
    } else {
        0.0
    }
}

/// `_reads_usage(record, now)`: whether a person's click reads Codex's usage for `record`.
pub fn reads_usage(record: &Row, now: f64) -> bool {
    text_of(record, "category") == Some("usage_limit")
        && among(record, WAITING)
        && !pyval::truthy(get(record, "cancel_requested"))
        && matches!(get(record, "submitted_at"), Value::Null)
        && or_zero(get(record, "reset_at")) > now
        && or_zero(get(record, "not_before")) <= now
        && !record.get("hold").is_some_and(pyval::truthy)
}

/// `store.get(key)` as `_bound_record` and the actions read it.
fn record(store: &Store, key: &str) -> Res<Option<Row>> {
    store.get(key).map_err(from_store)
}

fn no_such() -> Failure {
    Failure::Control(ControlError::new(
        "no such interruption",
        "no_such_interruption",
    ))
}

/// `_bound_record(store, key, thread)`: the record a row's click names, refused if it is gone, finished or another
/// conversation's.
fn bound_record(store: &Store, key: &str, thread: &str) -> Res<Row> {
    let Some(row) = record(store, key)? else {
        return Err(no_such());
    };
    if text_of(&row, "thread_id") != Some(thread) {
        return refuse(
            "that recovery belongs to a different conversation",
            "thread_mismatch",
        );
    }
    if among(&row, TERMINAL) {
        return refuse("that recovery has already finished", "already_finished");
    }
    Ok(row)
}

fn detail_text(detail: &Value) -> Option<String> {
    match detail {
        Value::Str(text) => text.as_str().map(str::to_owned),
        _ => None,
    }
}

/// `raise ControlError(*_refusal(table, detail))`.
fn refused_by<T>(table: crate::error::Refusals, detail: &Value) -> Res<T> {
    let (message, code) = refusal(table, detail_text(detail).as_deref());
    refuse(message, code)
}

impl Control {
    /// `WakeEvent(state_dir).signal()`, where anything it raises is "not woken".
    fn wake(&self) -> bool {
        self.host
            .signal(Event::Wake, &self.state_dir())
            .unwrap_or(false)
    }

    /// `set_enabled(enabled)`: global pause and resume.
    pub fn set_enabled(&self, enabled: bool) -> Res<Value> {
        if enabled && self.managed().disable_auto_resume {
            return refuse(
                "recovery is paused by your administrator",
                "managed_by_policy",
            );
        }
        let now = self.host.now();
        let on = match self.open(true)? {
            State::Current(store) => {
                store.set_enabled(enabled, now).map_err(from_store)?;
                pyval::truthy(get(&store.settings().map_err(from_store)?, "enabled"))
            }
            State::Legacy(store) => {
                store.set_enabled(enabled, now).map_err(from_store)?;
                pyval::truthy(get(&store.settings().map_err(from_store)?, "enabled"))
            }
        };
        Ok(object(vec![("enabled", Value::Bool(on))]))
    }

    /// `set_thread_enabled(thread_id, enabled, actor="gui")`: one conversation's recovery on or off.
    pub fn set_thread_enabled(&self, thread: &Value, enabled: bool, actor: &str) -> Res<Value> {
        let thread = thread_id(thread)?;
        let on = match self.open(true)? {
            State::Current(store) => {
                store
                    .set_thread_enabled(&thread, enabled, actor, None)
                    .map_err(from_store)?;
                store.thread_enabled(&thread).map_err(from_store)?
            }
            State::Legacy(store) => {
                store
                    .set_thread_enabled(&thread, enabled)
                    .map_err(from_store)?;
                store.thread_enabled(&thread).map_err(from_store)?
            }
        };
        if !enabled {
            self.plug().conversation_off(&thread);
        }
        Ok(object(vec![
            ("thread_id", Value::from(thread.as_str())),
            ("enabled", Value::Bool(on)),
        ]))
    }

    /// `cancel_interruption(interruption_id, actor="gui")`: one exact interruption stopped, and what continues it.
    /// Retried while the watcher is writing, for CANCEL_RETRY_SECONDS.
    pub fn cancel_interruption(&self, id: &Value, actor: &str) -> Res<Value> {
        let key = interruption_id(id)?;
        let deadline = self.host.monotonic() + CANCEL_RETRY_SECONDS;
        let (result, row) = loop {
            let store = self.open_current()?;
            // The cancel and the record read after it, in one `try`: a StoreError of either is tried again.
            let attempt = store
                .cancel_interruption(&key, self.host.now(), actor)
                .and_then(|result| match result {
                    Some(result) => store.get(&key).map(|row| Some((result, row))),
                    None => Ok(None),
                });
            match attempt {
                Ok(None) => return Err(no_such()),
                Ok(Some((result, Some(row)))) => break (result, row),
                Ok(Some((_, None))) => return Err(Failure::Other("TypeError".into())),
                Err(StoreError::Store(..)) => {
                    drop(store);
                    if self.host.monotonic() >= deadline {
                        return refuse(
                            "the state is busy; the cancel was not recorded",
                            "state_busy",
                        );
                    }
                    self.host.sleep(CANCEL_PAUSE_SECONDS);
                }
                Err(other) => return Err(from_store(other)),
            }
        };
        let changed = pyval::truthy(get(&result, "changed"));
        let effects = get(&result, "effects").clone();
        let requested = match &effects {
            Value::Object(map) => map
                .values()
                .any(|effect| pyval::text(effect) == Some("cancel_requested")),
            _ => false,
        };
        let message = if !changed {
            "already finished; nothing to stop"
        } else if requested {
            "cancelled; a continuation already handed to Codex is withdrawn if it is still queued, and one already \
             running is not stopped"
        } else {
            "cancelled"
        };
        Ok(object(vec![
            ("interruption_id", Value::from(key.as_str())),
            ("thread_id", get(&row, "thread_id").clone()),
            ("state", get(&row, "state").clone()),
            ("changed", get(&result, "changed").clone()),
            ("effects", effects),
            ("message", Value::from(message)),
        ]))
    }

    /// `cancel_thread(thread_id, actor="gui")`: a conversation's recovery off, and what it has stopped.
    pub fn cancel_thread(&self, thread: &Value, actor: &str) -> Res<Value> {
        let thread = thread_id(thread)?;
        let now = self.host.now();
        match self.open(true)? {
            State::Current(store) => store
                .cancel_thread(&thread, now, actor)
                .map_err(from_store)?,
            State::Legacy(store) => store.cancel_thread(&thread, now).map_err(from_store)?,
        }
        self.plug().conversation_off(&thread);
        Ok(object(vec![("thread_id", Value::from(thread.as_str()))]))
    }

    /// `reset_recovery_budget(interruption_id, actor="gui")`: an exhausted interruption's attempts given back.
    pub fn reset_recovery_budget(&self, id: &Value, actor: &str) -> Res<Value> {
        let key = interruption_id(id)?;
        let store = self.open_current()?;
        let Some(row) = record(&store, &key)? else {
            return Err(no_such());
        };
        let (restored, detail) = store
            .restore_budget_detailed(
                &key,
                self.host.now(),
                actor,
                car_store::actions::MAX_BUDGET_RESETS,
            )
            .map_err(from_store)?;
        if !restored {
            let mut detail = detail;
            if detail_text(&detail).as_deref() == Some("not_exhausted") && among(&row, TERMINAL) {
                detail = Value::from(if pyval::truthy(get(&row, "cancel_requested")) {
                    "cancel_requested"
                } else {
                    "finished"
                });
            }
            return refused_by(REFUSALS_RESTORE, &detail);
        }
        let thread = text_of(&row, "thread_id").unwrap_or_default().to_owned();
        let on = store.thread_enabled(&thread).map_err(from_store)?;
        let note = if on {
            Value::Null
        } else {
            Value::from(
                "automatic recovery is off for this conversation; switch it on for this recovery to run",
            )
        };
        let state = match record(&store, &key)? {
            Some(now) => get(&now, "state").clone(),
            None => return Err(Failure::Other("TypeError".into())),
        };
        Ok(object(vec![
            ("interruption_id", Value::from(key.as_str())),
            ("state", state),
            ("note", note),
        ]))
    }

    /// `request_retry_now(interruption_id, actor="gui")`: a waiting interruption made eligible at once, and - for a
    /// person's click on a usage limit whose reset is still ahead - usage read once at the look it brings forward.
    pub fn request_retry_now(&self, id: &Value, actor: &str) -> Res<Value> {
        let key = interruption_id(id)?;
        let (row, accepted, detail, blocked, check) = {
            let store = self.open_current()?;
            let Some(row) = record(&store, &key)? else {
                return Err(no_such());
            };
            let (accepted, detail) = store
                .request_retry_now(&key, self.host.now(), actor)
                .map_err(from_store)?;
            let now = self.host.now();
            let wanted = accepted && actor == "gui" && reads_usage(&row, now);
            let blocked = if wanted {
                self.not_checked(&store, &row, now)?
            } else {
                None
            };
            let check = wanted
                && blocked.is_none()
                && store
                    .ask_usage_check(&key, now, USAGE_BY_RETRY)
                    .map_err(from_store)?;
            (row, accepted, detail, blocked, check)
        };
        if !accepted {
            return refused_by(REFUSALS_RETRY, &detail);
        }
        let woke = self.wake();
        let mut usage_check: Value = blocked.map_or(Value::Null, Value::from);
        if check && !woke {
            let store = self.open_current()?;
            store.usage_check_taken(&key);
            usage_check = Value::from("not_running");
        } else if check {
            usage_check = Value::from("asked");
        }
        let now = self.host.now();
        let at = number(&detail);
        let later = at.is_some_and(|at| at > now + 1.0);
        let note = if let Some(why) = blocked {
            format!(
                "usage was not checked: {}; it waits for the reset Codex gave",
                not_checked_note(why)
            )
        } else if pyval::text(&usage_check) == Some("asked") {
            "checking usage now: if Codex says the limit has lifted, the recovery goes on through every safety \
             check; otherwise it waits for the reset Codex gave"
                .to_owned()
        } else if pyval::text(&usage_check) == Some("not_running") {
            "the watcher is not running, so usage was not checked; it waits for the reset Codex gave".to_owned()
        } else if later && or_zero(get(&row, "reset_at")) >= at.unwrap_or(f64::INFINITY) {
            "the usage reset is at a later time; the watcher checks then, and every safety check still applies"
                .to_owned()
        } else if later {
            "it is postponed to a later time, which this does not shorten; the watcher checks then, and every \
             safety check still applies"
                .to_owned()
        } else if woke {
            "checking now; every safety check still applies".to_owned()
        } else {
            "the watcher checks at its next poll; every safety check still applies".to_owned()
        };
        Ok(object(vec![
            ("interruption_id", Value::from(key.as_str())),
            ("state", get(&row, "state").clone()),
            ("eligible_at", detail),
            ("woke", Value::Bool(woke)),
            ("note", Value::from(note)),
            ("usage_check", usage_check),
        ]))
    }

    /// `_not_checked(store, record, now)`: what would stop the watcher reading usage for `record` now, or None.
    fn not_checked(&self, store: &Store, row: &Row, now: f64) -> Res<Option<&'static str>> {
        let stored = store.settings().map_err(from_store)?;
        let values = self
            .get_settings()
            .map(Value::Object)
            .unwrap_or_else(|_| Value::Object(Map::new()));
        let enabled = pyval::truthy(get(&stored, "enabled")) && !self.managed().disable_auto_resume;
        let thread = text_of(row, "thread_id").unwrap_or_default();
        let conversation_on = store.thread_enabled(thread).map_err(from_store)?;
        let observing = stored.get("observe_only").is_some_and(pyval::truthy)
            || pyval::get(&values, "observe_only").is_ok_and(pyval::truthy);
        let clock = self.host.local_clock();
        let quiet = quiet::quiet_until(&Value::Float(now), &values, &*clock)
            .map_err(|class| Failure::Other(class.to_owned()))?
            .is_some();
        if let Some(stopped) = gates::usage_read_stopped(enabled, conversation_on, observing, quiet)
        {
            return Ok(Some(stopped));
        }
        if power::waits_for_network(&values)
            && let Ok(Some(false)) = self.host.internet()
        {
            return Ok(Some("offline"));
        }
        Ok(None)
    }

    /// `set_interruption_recovery(interruption_id, thread_id, enabled, actor="gui")`: the per-task checkbox.
    pub fn set_interruption_recovery(
        &self,
        id: &Value,
        thread: &Value,
        enabled: bool,
        actor: &str,
    ) -> Res<Value> {
        let key = interruption_id(id)?;
        let thread = thread_id(thread)?;
        let store = self.open_current()?;
        let row = bound_record(&store, &key, &thread)?;
        store
            .set_thread_enabled(&thread, enabled, actor, None)
            .map_err(from_store)?;
        let found = object(vec![
            ("interruption_id", Value::from(key.as_str())),
            ("thread_id", Value::from(thread.as_str())),
            (
                "enabled",
                Value::Bool(store.thread_enabled(&thread).map_err(from_store)?),
            ),
            ("state", get(&row, "state").clone()),
        ]);
        drop(store);
        if !enabled {
            self.plug().conversation_off(&thread);
        }
        Ok(found)
    }

    /// `_postpone_until(now, until, preset, minutes)`: the one time a postponement asks for.
    fn postpone_until(
        &self,
        now: f64,
        until: &Value,
        preset: &Value,
        minutes: &Value,
    ) -> Res<Value> {
        let invalid = || {
            refuse(
                "that is not a time to postpone a recovery to",
                "invalid_time",
            )
        };
        let given = [until, preset, minutes]
            .iter()
            .filter(|each| !matches!(each, Value::Null))
            .count();
        if given != 1 {
            return invalid();
        }
        let when = if !matches!(preset, Value::Null) {
            match preset {
                Value::Str(_) => {
                    let clock = self.host.local_clock();
                    quiet::postpone_time(&Value::Float(now), preset, &*clock)
                        .map_err(|class| Failure::Other(class.to_owned()))?
                        .map(Value::Float)
                }
                _ => None,
            }
        } else if !matches!(minutes, Value::Null) {
            match minutes {
                Value::Int(count) if pyval::greater(minutes, &Value::from(0)).unwrap_or(false) => {
                    let count = car_machine::pytext::to_float(&Value::Int(count.clone()))
                        .map_err(|class| Failure::Other(class.to_owned()))?;
                    Some(Value::Float(now + 60.0 * count))
                }
                _ => None,
            }
        } else {
            Some(until.clone())
        };
        match when {
            Some(when) => Ok(when),
            None => invalid(),
        }
    }

    /// `postpone(interruption_id, thread_id, until=None, preset=None, minutes=None, actor="gui")`.
    pub fn postpone(
        &self,
        id: &Value,
        thread: &Value,
        until: &Value,
        preset: &Value,
        minutes: &Value,
        actor: &str,
    ) -> Res<Value> {
        let key = interruption_id(id)?;
        let thread = thread_id(thread)?;
        let now = self.host.now();
        let when = self.postpone_until(now, until, preset, minutes)?;
        let (accepted, detail, state) = {
            let store = self.open_current()?;
            let (accepted, detail) = store
                .postpone(&key, &thread, &when, now, actor)
                .map_err(from_store)?;
            let state = record(&store, &key)?
                .map(|row| get(&row, "state").clone())
                .unwrap_or(Value::Null);
            (accepted, detail, state)
        };
        if !accepted {
            return refused_by(REFUSALS_POSTPONE, &detail);
        }
        Ok(object(vec![
            ("interruption_id", Value::from(key.as_str())),
            ("thread_id", Value::from(thread.as_str())),
            ("state", state),
            ("not_before", detail),
            (
                "note",
                Value::from("not sent before then; every safety check still applies"),
            ),
        ]))
    }

    /// `unpostpone(interruption_id, thread_id, actor="gui")`: a person's own postponement taken away.
    pub fn unpostpone(&self, id: &Value, thread: &Value, actor: &str) -> Res<Value> {
        let key = interruption_id(id)?;
        let thread = thread_id(thread)?;
        let (accepted, detail, row) = {
            let store = self.open_current()?;
            let (accepted, detail) = store
                .unpostpone(&key, &thread, self.host.now(), actor)
                .map_err(from_store)?;
            let row = if accepted {
                record(&store, &key)?
            } else {
                None
            };
            (accepted, detail, row)
        };
        if !accepted {
            return refused_by(REFUSALS_UNPOSTPONE, &detail);
        }
        let woke = self.wake();
        let eligible = match &row {
            Some(row) => public::eligible_at(&Value::Object(row.clone()))
                .map_err(|class| Failure::Other(class.to_owned()))?,
            None => Value::Null,
        };
        Ok(object(vec![
            ("interruption_id", Value::from(key.as_str())),
            ("thread_id", Value::from(thread.as_str())),
            (
                "state",
                row.as_ref()
                    .map_or(Value::Null, |row| get(row, "state").clone()),
            ),
            ("not_before", detail),
            ("eligible_at", eligible),
            ("woke", Value::Bool(woke)),
            (
                "note",
                Value::from("no longer postponed; every safety check still applies"),
            ),
        ]))
    }

    /// `release_hold(interruption_id, thread_id, actor="gui")`: one exact held recovery let continue.
    pub fn release_hold(&self, id: &Value, thread: &Value, actor: &str) -> Res<Value> {
        let key = interruption_id(id)?;
        let thread = thread_id(thread)?;
        let (released, detail) = {
            let store = self.open_current()?;
            store
                .release_hold(&key, &thread, self.host.now(), actor)
                .map_err(from_store)?
        };
        if !released {
            return refused_by(REFUSALS_RELEASE, &detail);
        }
        let woke = self.wake();
        Ok(object(vec![
            ("interruption_id", Value::from(key.as_str())),
            ("thread_id", Value::from(thread.as_str())),
            ("state", detail),
            ("woke", Value::Bool(woke)),
            (
                "note",
                Value::from("nothing is sent now; every safety check still applies"),
            ),
        ]))
    }

    /// `set_once_words(interruption_id, thread_id, text)`: words for this time for one exact waiting recovery, or
    /// taken away (None, or nothing but spaces).
    pub fn set_once_words(&self, id: &Value, thread: &Value, text: &Value) -> Res<Value> {
        let key = interruption_id(id)?;
        let thread = thread_id(thread)?;
        let held = OnceWords::of(&self.paths.once_words_file, &*self.host);
        let blank = match text {
            Value::Null => true,
            Value::Str(each) => each
                .as_str()
                .is_some_and(|plain| car_machine::pytext::strip(plain).is_empty()),
            _ => false,
        };
        let reply = |set: bool| {
            object(vec![
                ("interruption_id", Value::from(key.as_str())),
                ("thread_id", Value::from(thread.as_str())),
                ("set", Value::Bool(set)),
            ])
        };
        if blank {
            if !held.remove(&key) {
                return refuse("the state is busy", "state_busy");
            }
            return Ok(reply(false));
        }
        self.validated_text(text)?;
        let still_waiting = || -> Res<()> {
            let row = {
                let store = self.open_current()?;
                bound_record(&store, &key, &thread)?
            };
            if pyval::truthy(get(&row, "cancel_requested")) {
                return refuse("that recovery was cancelled", "cancel_requested");
            }
            if among(&row, CLAIMED) {
                return refuse("that recovery is being sent now", "being_sent");
            }
            if among(&row, OBSERVING) {
                return refuse("that recovery is already running in Codex", "observing");
            }
            if !among(&row, WAITING) {
                return refuse("that recovery is already in Codex", "in_flight");
            }
            Ok(())
        };
        still_waiting()?;
        match held.put(&key, text, None, still_waiting) {
            Ok(_) => Ok(reply(true)),
            Err(Put::Guard(failure)) => Err(failure),
            Err(Put::Words(error)) => match error.code.as_str() {
                "too_many_messages" => refuse(error.message, "too_many_messages"),
                "state_busy" => refuse("the state is busy", "state_busy"),
                _ => refuse(error.message, "request_failed"),
            },
        }
    }

    /// `set_thread_tier(thread_id, tier, interruption_id=None, actor="gui")`: how much one conversation asks first.
    pub fn set_thread_tier(
        &self,
        thread: &Value,
        tier: &Value,
        id: &Value,
        actor: &str,
    ) -> Res<Value> {
        let thread = thread_id(thread)?;
        let tiers = car_policy::settings::vocab_gen::settings::TIERS;
        let known = match tier {
            Value::Null => true,
            Value::Str(text) => text.as_str().is_some_and(|word| tiers.contains(&word)),
            _ => false,
        };
        if !known {
            return refuse("invalid tier", "invalid_tier");
        }
        let store = self.open_current()?;
        if !matches!(id, Value::Null) {
            let key = interruption_id(id)?;
            bound_record(&store, &key, &thread)?;
        }
        let result = store
            .set_thread_tier(&thread, tier, self.host.now(), actor)
            .map_err(from_store)?;
        Ok(object(vec![
            ("thread_id", Value::from(thread.as_str())),
            ("tier", get(&result, "tier").clone()),
            ("held", get(&result, "held").clone()),
        ]))
    }

    /// `set_project_rule(interruption_id, thread_id, always, source=..., actor="gui")`: Always, or Never, for the
    /// project one exact task's conversation is filed under.
    pub fn set_project_rule(
        &self,
        id: &Value,
        thread: &Value,
        always: bool,
        source: Option<&car_codex::source::LocalSource>,
        actor: &str,
    ) -> Res<Value> {
        let key = interruption_id(id)?;
        let thread = thread_id(thread)?;
        let row = {
            let store = self.open_current()?;
            bound_record(&store, &key, &thread)?
        };
        let values = self.get_settings()?;
        let others =
            crate::records::other_homes(self, values.get(homes::FIELD).unwrap_or(&Value::Null));
        let mut readers: Vec<(Str, Option<car_codex::source::LocalSource>)> = Vec::new();
        let mut seen: Vec<((String, String), Value)> = Vec::new();
        let mut project_of = |row: &Row| -> Value {
            let home_key = text_of(row, "home_key").unwrap_or_default().to_owned();
            let thread_of = text_of(row, "thread_id").unwrap_or_default().to_owned();
            let home = others
                .iter()
                .find(|(each, _)| *each == home_key)
                .map(|(_, found)| found.1.clone());
            let mark = (home_key, thread_of.clone());
            if let Some((_, found)) = seen.iter().find(|(each, _)| *each == mark) {
                return found.clone();
            }
            let mut reader = source;
            if let (Some(path), Some(base)) = (&home, source) {
                let at = match readers.iter().position(|(each, _)| each == path) {
                    Some(at) => at,
                    None => {
                        let made = path.as_str().and_then(|text| base.elsewhere(text).ok());
                        readers.push((path.clone(), made));
                        readers.len() - 1
                    }
                };
                reader = readers[at].1.as_ref();
            }
            let found = match reader {
                Some(reader) => match reader.project_key(&thread_of) {
                    Ok(Some(project)) => Value::from(project),
                    _ => Value::Null,
                },
                None => Value::Null,
            };
            seen.push((mark, found.clone()));
            found
        };
        let project = project_of(&row);
        if matches!(project, Value::Null) {
            return refuse(
                "the project of that conversation cannot be read",
                "project_unreadable",
            );
        }
        let stored = Value::Object(self.stored_settings()?);
        let changes = match projects::rule(&stored, &project, always) {
            Ok(changes) => changes,
            Err("ValueError") => {
                return refuse(
                    format!("at most {} projects can be listed", projects::MAX_KEYS),
                    "too_many_projects",
                );
            }
            Err(class) => return Err(Failure::Other(class.to_owned())),
        };
        let saved = Value::Object(self.update_settings(&changes)?);
        let allowed = projects::allows(&saved, &project);
        let mut held = Value::from(0);
        if !allowed {
            let store = self.open_current()?;
            let mut keys: Vec<String> = Vec::new();
            for row in store.pending().map_err(from_store)? {
                if !matches!(get(&row, "hold"), Value::Null) || !among(&row, WAITING) {
                    continue;
                }
                if pyval::eq(&project_of(&row), &project) {
                    keys.push(
                        text_of(&row, "interruption_id")
                            .unwrap_or_default()
                            .to_owned(),
                    );
                }
            }
            let hold = projects::hold_for(&saved, &project).unwrap_or("notify_only");
            held = Value::from(
                store
                    .hold_waiting(&keys, hold, self.host.now(), actor)
                    .map_err(from_store)?,
            );
        }
        Ok(object(vec![
            ("thread_id", Value::from(thread.as_str())),
            ("always", Value::Bool(always)),
            (
                "project_policy",
                pyval::get(&saved, "project_policy")
                    .cloned()
                    .map_err(|class| Failure::Other(class.to_owned()))?,
            ),
            ("allowed", Value::Bool(allowed)),
            ("held", held),
        ]))
    }

    /// `cancel_all_pending(actor="gui")`: every pending recovery stopped, one exact interruption at a time.
    pub fn cancel_all_pending(&self, actor: &str) -> Res<Value> {
        let keys: Vec<Value> = {
            let store = self.open_current()?;
            store
                .pending()
                .map_err(from_store)?
                .iter()
                .map(|row| get(row, "interruption_id").clone())
                .collect()
        };
        let (mut cancelled, mut finished, mut failed) = (0i64, 0i64, 0i64);
        for key in &keys {
            match self.cancel_interruption(key, actor) {
                Err(Failure::Control(_)) => failed += 1,
                Err(other) => return Err(other),
                Ok(result) => {
                    if pyval::get(&result, "changed").is_ok_and(pyval::truthy) {
                        cancelled += 1;
                    } else {
                        finished += 1;
                    }
                }
            }
        }
        Ok(object(vec![
            ("requested", Value::from(keys.len() as i64)),
            ("cancelled", Value::from(cancelled)),
            ("already_finished", Value::from(finished)),
            ("failed", Value::from(failed)),
        ]))
    }

    /// `rescan.judge_for(control)` then `rescan_pending(judge, actor="gui", read_usage=True)`: the Dashboard's
    /// Rescan and reconcile.
    pub fn rescan(&self, actor: &str, read_usage: bool) -> Res<Value> {
        let home = std::path::PathBuf::from(&self.paths.home);
        let mut judge = self
            .host
            .rescan_judge(&home)
            .map_err(|raised| Failure::Other(raised.class))?;
        self.rescan_pending(&mut *judge, actor, read_usage)
    }

    /// `rescan_pending(judge, actor="gui", read_usage=False)`: every waiting recovery looked at again, each by its
    /// own interruption id, retired only on proof of newer work.
    pub fn rescan_pending(
        &self,
        judge: &mut dyn Judge,
        actor: &str,
        read_usage: bool,
    ) -> Res<Value> {
        let everything = {
            let store = self.open_current()?;
            store.all_records().map_err(from_store)?
        };
        let waiting: Vec<&Row> = everything
            .iter()
            .filter(|row| {
                among(row, WAITING)
                    && !pyval::truthy(get(row, "cancel_requested"))
                    && matches!(get(row, "submitted_at"), Value::Null)
                    && matches!(get(row, "queue_id"), Value::Null)
            })
            .collect();
        let mut counts = [
            (RETIRED, 0i64),
            (RECHECKED, 0),
            (UNRESOLVED, 0),
            (CHANGED, 0),
        ];
        let mut found = Vec::new();
        for row in &waiting {
            let thread = get(row, "thread_id");
            let kin: Vec<Row> = everything
                .iter()
                .filter(|other| pyval::eq(get(other, "thread_id"), thread))
                .cloned()
                .collect();
            let (mut outcome, mut reason) = match judge.judge(row, &kin) {
                Ok(found) => found,
                Err(_) => (Value::from(UNRESOLVED), Value::from("unreadable")),
            };
            let said = pyval::text(&outcome).unwrap_or_default();
            if said != RETIRED && said != RECHECKED {
                outcome = Value::from(UNRESOLVED);
            }
            let word = pyval::text(&outcome).unwrap_or(UNRESOLVED).to_owned();
            let key = text_of(row, "interruption_id")
                .unwrap_or_default()
                .to_owned();
            let applied = self.open_current().and_then(|store| {
                store
                    .rescan_apply(&key, row, &word, self.host.now(), &reason, actor)
                    .map_err(|error| match error {
                        StoreError::Store(..) => Failure::Other("StoreError".into()),
                        other => from_store(other),
                    })
            });
            let applied: Option<bool> = match applied {
                Ok(applied) => Some(applied),
                Err(failed) => {
                    let busy = matches!(&failed, Failure::Control(_))
                        || matches!(&failed, Failure::Other(class) if class == "StoreError");
                    outcome = Value::from(UNRESOLVED);
                    reason = Value::from(if busy { "state_busy" } else { "apply_failed" });
                    if let Ok(store) = self.open_current()
                        && let Ok(false) = store.rescan_apply(
                            &key,
                            row,
                            UNRESOLVED,
                            self.host.now(),
                            &Value::Null,
                            actor,
                        )
                    {
                        outcome = Value::from(CHANGED);
                        reason = Value::Null;
                    }
                    None
                }
            };
            if applied == Some(false) {
                outcome = Value::from(CHANGED);
                reason = Value::Null;
            }
            let word = pyval::text(&outcome).unwrap_or(UNRESOLVED);
            if let Some(count) = counts.iter_mut().find(|(name, _)| *name == word) {
                count.1 += 1;
            }
            found.push(object(vec![
                ("interruption_id", get(row, "interruption_id").clone()),
                ("thread_id", get(row, "thread_id").clone()),
                ("outcome", outcome),
                ("reason", reason),
            ]));
        }
        let count = |name: &str| {
            counts
                .iter()
                .find(|(each, _)| *each == name)
                .map_or(0, |each| each.1)
        };
        let read_usage = read_usage && actor == "gui";
        let (mut usage_check, asked) = if read_usage {
            self.ask_usage_for_all()?
        } else {
            (Value::Null, Vec::new())
        };
        let mut woke = false;
        if count(RECHECKED) > 0 || !asked.is_empty() {
            woke = self.wake();
        }
        if !asked.is_empty() && !woke {
            let store = self.open_current()?;
            for key in &asked {
                store.usage_check_taken(key);
            }
            usage_check = Value::from("not_running");
        }
        let live = everything
            .iter()
            .filter(|row| !among(row, TERMINAL))
            .count() as i64;
        let mut reply = vec![
            ("scanned", Value::from(waiting.len() as i64)),
            ("not_waiting", Value::from(live - waiting.len() as i64)),
            ("retired", Value::from(count(RETIRED))),
            ("rechecked", Value::from(count(RECHECKED))),
            ("unresolved", Value::from(count(UNRESOLVED))),
            ("changed", Value::from(count(CHANGED))),
            ("records", Value::Array(found)),
            ("woke", Value::Bool(woke)),
        ];
        if read_usage {
            let many = if pyval::text(&usage_check) == Some("asked") {
                asked.len() as i64
            } else {
                0
            };
            reply.push(("usage_check", usage_check));
            reply.push(("usage_asked", Value::from(many)));
        }
        Ok(object(reply))
    }

    /// `_ask_usage_for_all()`: Rescan's reading - (usage_check, the ids asked for).
    fn ask_usage_for_all(&self) -> Res<(Value, Vec<String>)> {
        let now = self.host.now();
        let store = self.open_current()?;
        let rows: Vec<Row> = store
            .all_records()
            .map_err(from_store)?
            .into_iter()
            .filter(|row| reads_usage(row, now))
            .collect();
        if rows.is_empty() {
            return Ok((Value::Null, Vec::new()));
        }
        let mut blocked: Vec<(String, Option<&'static str>)> = Vec::new();
        for row in &rows {
            let key = text_of(row, "interruption_id")
                .unwrap_or_default()
                .to_owned();
            let why = self.not_checked(&store, row, now)?;
            match blocked.iter_mut().find(|(each, _)| *each == key) {
                Some(entry) => entry.1 = why,
                None => blocked.push((key, why)),
            }
        }
        let open: Vec<String> = rows
            .iter()
            .filter_map(|row| {
                let key = text_of(row, "interruption_id").unwrap_or_default();
                blocked
                    .iter()
                    .find(|(each, _)| each == key)
                    .is_some_and(|(_, why)| why.is_none())
                    .then(|| key.to_owned())
            })
            .collect();
        if open.is_empty() {
            let shared = blocked
                .iter()
                .filter_map(|(_, why)| *why)
                .find(|why| *why != "conversation_off");
            return Ok((
                Value::from(shared.unwrap_or("conversation_off")),
                Vec::new(),
            ));
        }
        let mut asked = Vec::new();
        for key in open {
            if store
                .ask_usage_check(&key, now, USAGE_BY_RESCAN)
                .map_err(from_store)?
            {
                asked.push(key);
            }
        }
        let word = if asked.is_empty() { "held" } else { "asked" };
        Ok((Value::from(word), asked))
    }

    /// `clear_history(actor="gui")`: finished recoveries hidden from History; nothing deleted.
    pub fn clear_history(&self, actor: &str) -> Res<Value> {
        let store = self.open_current()?;
        let hidden = store
            .hide_history(self.host.now(), actor)
            .map_err(from_store)?;
        Ok(Value::Object(hidden))
    }
}
