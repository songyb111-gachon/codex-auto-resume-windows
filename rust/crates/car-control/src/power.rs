//! `control/poweraction.py`'s writers: the power action armed, turned off, a batch stopped, ended or shown.
//!
//! `config/power-action.json` holds one arming. Each write takes one named lock, rereads, decides and replaces the
//! file whole (a temporary file nobody can plant a link at, flushed to disk, then moved over it). Nothing here
//! sends anything, and nothing here asks Windows anything but whether an action is available
//! ([`Host::power_available`](crate::host::Host)). Nothing here acts: there is no call that sleeps, hibernates or
//! shuts down this PC anywhere in this crate.

use std::io::Write;
use std::path::{Path, PathBuf};

use car_machine::domain::ids;
use car_machine::json::{Map, Options, Str, Value, to_string};
use car_policy::plug::Point;
use car_policy::settings::poweraction;
use car_store::open::UPGRADE_PENDING;
use car_store::value::{get, text_of};

use crate::error::{Failure, Res, refuse};
use crate::layer::{Control, State, from_store};

/// `POWER_LOCK_SECONDS`.
pub const POWER_LOCK_SECONDS: f64 = 5.0;
/// `DISARM_ACTORS`: who may turn it off.
pub const DISARM_ACTORS: &[&str] = &["dashboard", "mcp", "tray", "toast", "card", "watcher"];
/// `STOP_ACTORS`: who may stop a batch.
pub const STOP_ACTORS: &[&str] = &["toast", "card", "dashboard"];
pub const STOPPED: &str = "stopped";
pub const IGNORED: &str = "ignored";
pub const BUSY: &str = "the state is busy";
pub const UNAVAILABLE: &str = "that power action is not available on this PC";
pub const NO_TASKS: &str = "nothing here answers for tasks a person picked";
pub const MANAGED: &str = "your administrator has set this";
/// `poweraction.UNAVAILABLE`: the reasons Windows gives for an action it will not do.
pub const REASONS: &[&str] = &["no_privilege", "no_sleep_state", "hibernate_off"];
/// `REPLACE_TRIES`, `REPLACE_PAUSE`.
pub const REPLACE_TRIES: usize = 20;
pub const REPLACE_PAUSE: f64 = 0.025;

/// `FAILED % reason`.
fn failed(reason: &str) -> String {
    format!("the request could not be completed: {reason}")
}

fn other(class: &'static str) -> Failure {
    Failure::Other(class.to_owned())
}

fn key(name: &str) -> Str {
    Str::from(name)
}

/// `dict(document, **changes)`: each change in its place, a new key after the rest.
fn with(document: &Value, changes: Vec<(&str, Value)>) -> Value {
    let mut map = match document {
        Value::Object(map) => map.clone(),
        _ => Map::new(),
    };
    for (name, value) in changes {
        map.insert(key(name), value);
    }
    Value::Object(map)
}

fn field<'a>(document: &'a Value, name: &str) -> &'a Value {
    static NULL: Value = Value::Null;
    match document {
        Value::Object(map) => map.get(name).unwrap_or(&NULL),
        _ => &NULL,
    }
}

impl Control {
    /// `_replace(temporary, path)`: `os.replace`, tried again while a reader holds `path` open.
    fn power_replace(&self, temporary: &Path, path: &Path) -> std::io::Result<()> {
        let mut attempt = 0;
        loop {
            match self.host.replace(temporary, path) {
                Ok(()) => return Ok(()),
                Err(error)
                    if error.kind() == std::io::ErrorKind::PermissionDenied
                        && attempt < REPLACE_TRIES - 1 =>
                {
                    attempt += 1;
                    self.host.sleep(REPLACE_PAUSE);
                }
                Err(error) => return Err(error),
            }
        }
    }

    /// `_write(path, document)`: the document to `path` whole, sorted, ASCII; false where Windows refused, with
    /// nothing left behind.
    fn power_write(&self, path: &Path, document: &Value) -> bool {
        let folder = path.parent().unwrap_or(Path::new("."));
        let Ok((temporary, mut file)) =
            crate::seen::temporary(&*self.host, folder, "power-action.", ".tmp")
        else {
            return false;
        };
        let written = match to_string(document, &Options::new().sort_keys(true)) {
            Ok(text) => file
                .write_all(text.as_bytes())
                .and_then(|_| file.flush())
                .and_then(|_| file.sync_all())
                .is_ok(),
            Err(_) => false,
        };
        drop(file);
        if written && self.power_replace(&temporary, path).is_ok() {
            return true;
        }
        let _ = std::fs::remove_file(&temporary);
        false
    }

    /// `power_options()`: what the Dashboard's card draws - the view, each action and whether Windows will do it
    /// here, an administrator's key, and an older watcher holding the state.
    pub fn power_options(&self) -> Res<Value> {
        let legacy = matches!(self.open(true)?, State::Legacy(_));
        let mut actions = Vec::new();
        for action in poweraction::ACTIONS {
            let (available, reason) = self.power_available(action);
            let mut entry = Map::new();
            entry.insert(key("value"), Value::from(*action));
            entry.insert(key("available"), Value::Bool(available));
            entry.insert(key("reason"), reason.map_or(Value::Null, Value::from));
            actions.push(Value::Object(entry));
        }
        let (_, document) = self.read_power_action()?;
        let mut out = Map::new();
        out.insert(key("view"), poweraction::view(&document).map_err(other)?);
        out.insert(key("actions"), Value::Array(actions));
        out.insert(
            key("managed"),
            Value::Bool(self.managed().disable_power_action),
        );
        out.insert(key("upgrade_pending"), Value::Bool(legacy));
        Ok(Value::Object(out))
    }

    /// `_power_available(action)`: (available, a reason Windows gave), anything it raised being "not available".
    fn power_available(&self, action: &str) -> (bool, Option<String>) {
        match self.host.power_available(action) {
            Ok((available, reason)) => (
                available,
                reason.filter(|why| REASONS.contains(&why.as_str())),
            ),
            Err(_) => (false, None),
        }
    }

    /// `_power_change(change, now)`: under the lock, reread the file and write what `change(why, document)`
    /// returns (None writes nothing). Busy is a refusal, and so is a write Windows refused.
    fn power_change(
        &self,
        now: f64,
        change: impl FnOnce(&str, &Value) -> Option<Value>,
    ) -> Res<Option<Value>> {
        let path = PathBuf::from(&self.paths.power_action_file);
        let Ok(lock) = self.host.lock(&path.to_string_lossy(), POWER_LOCK_SECONDS) else {
            return refuse(BUSY, "state_busy");
        };
        let outcome = (|| {
            let (why, document) = self.read_power_action_at(now)?;
            let Some(written) = change(why, &document) else {
                return Ok(None);
            };
            // What is about to be written, read back as the file would be.
            let believed = match to_string(&written, &Options::new()) {
                Ok(text) => match car_machine::compat::loads(&text) {
                    Ok(again) => match poweraction::read_document(&again, &Value::Float(now)) {
                        Ok(found) => found,
                        Err("ValueError" | "TypeError") => Value::Null,
                        Err(class) => return Err(other(class)),
                    },
                    Err(_) => Value::Null,
                },
                Err(_) => Value::Null,
            };
            if matches!(believed, Value::Null) {
                return refuse(failed("it would not be believed"), "request_failed");
            }
            if !path.parent().is_some_and(Path::is_dir) || !self.power_write(&path, &written) {
                return refuse(failed("the file could not be written"), "request_failed");
            }
            Ok(Some(written))
        })();
        drop(lock);
        outcome
    }

    /// `arm_power_action(choice, actor="dashboard", tasks=False)`: armed as a person chose in the Dashboard - the
    /// only place it is armed - and the view returned.
    pub fn arm_power_action(&self, choice: &Value, actor: &str, tasks: bool) -> Res<Value> {
        if actor != "dashboard" {
            return refuse(
                failed("it is turned on only in the Dashboard"),
                "request_failed",
            );
        }
        let choice = if tasks && matches!(choice, Value::Object(_)) {
            with(choice, vec![("repeat", Value::from("once"))])
        } else {
            choice.clone()
        };
        if let Some(problem) = poweraction::choice_problem(&choice) {
            return refuse(failed(&problem), "request_failed");
        }
        if tasks && !self.plug().wants(Point::Power) {
            return refuse(failed(NO_TASKS), "request_failed");
        }
        if self.managed().disable_power_action {
            return refuse(MANAGED, "managed_by_policy");
        }
        let carried: Vec<Value> = match self.open(false)? {
            State::Legacy(_) => return refuse(UPGRADE_PENDING, "upgrade_pending"),
            State::Current(store) => store
                .pending()
                .map_err(from_store)?
                .iter()
                .filter(|row| {
                    text_of(row, "category") == Some("usage_limit")
                        && ids::is_digest(get(row, "interruption_id"))
                })
                .map(|row| get(row, "interruption_id").clone())
                .collect(),
        };
        let action = field(&choice, "action").clone();
        let action_text = car_machine::pyval::text(&action)
            .unwrap_or_default()
            .to_owned();
        if !self.power_available(&action_text).0 {
            return refuse(UNAVAILABLE, "power_unavailable");
        }
        let now = self.host.now();
        let mut unique: Vec<Value> = Vec::new();
        for each in carried {
            if !unique
                .iter()
                .any(|seen| car_machine::pyval::eq(seen, &each))
            {
                unique.push(each);
            }
        }
        unique.truncate(poweraction::MAX_CARRIED);
        let grace = match field(&choice, "grace_minutes") {
            Value::Int(minutes) => minutes
                .as_i64()
                .map_or(Value::Null, |m| Value::from(m * 60)),
            other => other.clone(),
        };
        let mut armed = Map::new();
        armed.insert(
            key("nonce"),
            Value::from(self.host.token_hex(ids::POWER_NONCE_LENGTH / 2)),
        );
        armed.insert(key("action"), action);
        armed.insert(key("after"), field(&choice, "after").clone());
        armed.insert(key("repeat"), field(&choice, "repeat").clone());
        armed.insert(key("grace_seconds"), grace);
        armed.insert(key("armed_at"), Value::Float(now));
        armed.insert(key("since"), Value::Float(now));
        armed.insert(key("carried"), Value::Array(unique));
        armed.insert(key("stop_at"), Value::Null);
        if tasks {
            armed.insert(key("carried"), Value::Array(Vec::new()));
            armed.insert(key(poweraction::TASKS_KEY), Value::Bool(true));
        }
        let armed = Value::Object(armed);
        let written = self.power_change(now, |why, document| {
            let kept = if why == poweraction::READ_OK {
                document.clone()
            } else {
                poweraction::blank()
            };
            Some(with(&kept, vec![("armed", armed), ("shown", Value::Null)]))
        })?;
        poweraction::view(&written.unwrap_or(Value::Null)).map_err(other)
    }

    /// `disarm_power_action(actor)`: turned off, from anywhere; `{"changed": whether there was an arming}`.
    pub fn disarm_power_action(&self, actor: &str) -> Res<Value> {
        if !DISARM_ACTORS.contains(&actor) {
            return refuse(failed("an unknown actor"), "request_failed");
        }
        let written = self.power_change(self.host.now(), |why, document| {
            if why != poweraction::READ_OK || matches!(field(document, "armed"), Value::Null) {
                return None;
            }
            Some(with(
                document,
                vec![("armed", Value::Null), ("shown", Value::Null)],
            ))
        })?;
        let mut out = Map::new();
        out.insert(key("changed"), Value::Bool(written.is_some()));
        Ok(Value::Object(out))
    }

    /// `stop_power_countdown(nonce, actor="toast")`: a notice's stop button - STOPPED for the armed batch's nonce,
    /// IGNORED for any other.
    pub fn stop_power_countdown(&self, nonce: &Value, actor: &str) -> Res<&'static str> {
        if !STOP_ACTORS.contains(&actor) {
            return refuse(failed("an unknown actor"), "request_failed");
        }
        if !ids::is_power_nonce(nonce) {
            return Ok(IGNORED);
        }
        let now = self.host.now();
        let written = self.power_change(now, |why, document| {
            let armed = if why == poweraction::READ_OK {
                field(document, "armed").clone()
            } else {
                Value::Null
            };
            if matches!(armed, Value::Null)
                || !car_machine::pyval::eq(field(&armed, "nonce"), nonce)
            {
                return None;
            }
            if !matches!(field(&armed, "stop_at"), Value::Null) {
                return Some(document.clone());
            }
            Some(with(
                document,
                vec![("armed", with(&armed, vec![("stop_at", Value::Float(now))]))],
            ))
        })?;
        Ok(if written.is_some() { STOPPED } else { IGNORED })
    }

    /// The next batch of an Always, or a spent Once: `dict(document, armed=..., shown=None, last=last)`.
    fn batch_ended(&self, document: &Value, armed: &Value, last: Value, now: f64) -> Value {
        if car_machine::pyval::is(field(armed, "repeat"), "once") {
            return with(
                document,
                vec![
                    ("armed", Value::Null),
                    ("shown", Value::Null),
                    ("last", last),
                ],
            );
        }
        let old = car_machine::pyval::text(field(armed, "nonce"))
            .unwrap_or_default()
            .to_owned();
        let since = match car_store::value::number(field(armed, "armed_at")) {
            Some(at) if at > now => field(armed, "armed_at").clone(),
            _ => Value::Float(now),
        };
        let following = with(
            armed,
            vec![
                ("nonce", Value::from(self.fresh_nonce(&old))),
                ("since", since),
                ("carried", Value::Array(Vec::new())),
                ("stop_at", Value::Null),
            ],
        );
        with(
            document,
            vec![("armed", following), ("shown", Value::Null), ("last", last)],
        )
    }

    /// `_fresh_nonce(old)`.
    fn fresh_nonce(&self, old: &str) -> String {
        loop {
            let nonce = self.host.token_hex(ids::POWER_NONCE_LENGTH / 2);
            if nonce != old {
                return nonce;
            }
        }
    }

    fn armed_of(why: &str, document: &Value, nonce: &Value) -> Option<Value> {
        let armed = if why == poweraction::READ_OK {
            field(document, "armed").clone()
        } else {
            Value::Null
        };
        if matches!(armed, Value::Null) || !car_machine::pyval::eq(field(&armed, "nonce"), nonce) {
            return None;
        }
        Some(armed)
    }

    fn last(armed: &Value, result: &str, now: f64) -> Value {
        let mut last = Map::new();
        last.insert(key("action"), field(armed, "action").clone());
        last.insert(key("result"), Value::from(result));
        last.insert(key("at"), Value::Float(now));
        Value::Object(last)
    }

    /// `power_batch_end(nonce, result, now=None)`: the watcher ends the batch `nonce` names as `result`.
    pub fn power_batch_end(&self, nonce: &Value, result: &Value, now: Option<f64>) -> bool {
        let known =
            car_machine::pyval::text(result).is_some_and(|word| poweraction::ENDS.contains(&word));
        if !known || !ids::is_power_nonce(nonce) {
            return false;
        }
        let now = now.unwrap_or_else(|| self.host.now());
        let word = car_machine::pyval::text(result)
            .unwrap_or_default()
            .to_owned();
        matches!(
            self.power_change(now, |why, document| {
                let armed = Self::armed_of(why, document, nonce)?;
                let last = Self::last(&armed, &word, now);
                Some(self.batch_ended(document, &armed, last, now))
            }),
            Ok(Some(_))
        )
    }

    /// `power_batch_finish(nonce, now=None)`: the countdown ran out - DONE, or SKIPPED when a stop came meanwhile.
    pub fn power_batch_finish(&self, nonce: &Value, now: Option<f64>) -> Option<&'static str> {
        if !ids::is_power_nonce(nonce) {
            return None;
        }
        let now = now.unwrap_or_else(|| self.host.now());
        let mut ended: Option<&'static str> = None;
        let written = self.power_change(now, |why, document| {
            let armed = Self::armed_of(why, document, nonce)?;
            let result = if matches!(field(&armed, "stop_at"), Value::Null) {
                "done"
            } else {
                "skipped"
            };
            ended = Some(result);
            let last = Self::last(&armed, result, now);
            Some(self.batch_ended(document, &armed, last, now))
        });
        match written {
            Ok(Some(_)) => ended,
            _ => None,
        }
    }

    /// `power_refused(now=None)`: Windows refused what a batch was ended DONE for; `last` says FAILED from now on.
    pub fn power_refused(&self, now: Option<f64>) -> bool {
        let now = now.unwrap_or_else(|| self.host.now());
        matches!(
            self.power_change(now, |why, document| {
                let last = if why == poweraction::READ_OK {
                    field(document, "last").clone()
                } else {
                    Value::Null
                };
                if matches!(last, Value::Null)
                    || !car_machine::pyval::is(field(&last, "result"), "done")
                {
                    return None;
                }
                Some(with(
                    document,
                    vec![(
                        "last",
                        with(
                            &last,
                            vec![("result", Value::from("failed")), ("at", Value::Float(now))],
                        ),
                    )],
                ))
            }),
            Ok(Some(_))
        )
    }

    /// `power_show(nonce, shown, now=None)`: what the watcher shows, written only when it changed.
    pub fn power_show(&self, nonce: &Value, shown: &Value, now: Option<f64>) -> bool {
        let Value::Object(map) = shown else {
            return false;
        };
        let keys: Vec<&str> = map.keys().filter_map(|each| each.as_str()).collect();
        let wanted_keys = ["phase", "waiting_for", "grace_until"];
        if map.len() != 3 || !wanted_keys.iter().all(|name| keys.contains(name)) {
            return false;
        }
        let now = now.unwrap_or_else(|| self.host.now());
        matches!(
            self.power_change(now, |why, document| {
                Self::armed_of(why, document, nonce)?;
                let wanted = with(shown, vec![("nonce", nonce.clone())]);
                if car_machine::pyval::eq(field(document, "shown"), &wanted) {
                    return None;
                }
                Some(with(document, vec![("shown", wanted)]))
            }),
            Ok(Some(_))
        )
    }
}
