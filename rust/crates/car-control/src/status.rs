//! `control/watcher.py`'s reading half: whether the watcher runs, what its heartbeat says, whether it starts at
//! sign-in, which edition is installed, and the status every surface opens with. (Starting and stopping the watcher
//! are not here: they start a process or signal one, which a quiet command never does - S5.1b.)

use std::path::PathBuf;

use car_machine::compat::LoadsError;
use car_machine::domain::public;
use car_machine::json::{Map, Str, Value};
use car_machine::pyval;
use car_machine::vocab_gen::domain_vocabulary::WatcherEnd;
use car_policy::plug::{Answer, Surface, edition};
use car_policy::settings::{homes, managed, poweraction, selfcheck};
use car_store::value::{get, number};

use crate::error::{Failure, Res};
use crate::layer::{Control, State, from_store, other};

/// `TICK_STALE_SECONDS`: a heartbeat older than this, from a watcher that holds the mutex, is not ticking.
pub const TICK_STALE_SECONDS: f64 = 180.0;
/// `BOOT_SLACK_SECONDS`: two readings of when Windows started that differ by no more than this are one start.
pub const BOOT_SLACK_SECONDS: f64 = 300.0;

fn word(text: &str) -> Value {
    Value::from(text)
}

/// `how_it_ended(status, running, sign_in, booted_at)`: how a watcher that is not running ended, and when.
pub fn how_it_ended(
    status: Option<&Map>,
    running: Option<bool>,
    sign_in: Option<&str>,
    booted_at: Option<f64>,
) -> (Value, Value) {
    let none = (Value::Null, Value::Null);
    let (Some(status), Some(false)) = (status, running) else {
        return none;
    };
    let mark = match status.get("end_mark") {
        Some(Value::Str(text)) => text.as_str().unwrap_or_default(),
        _ => "",
    };
    if mark == WatcherEnd::Clean.as_str() || mark == WatcherEnd::MemoryGuard.as_str() {
        return (
            word(mark),
            status.get("ended_at").cloned().unwrap_or(Value::Null),
        );
    }
    if mark != WatcherEnd::Running.as_str() {
        return none;
    }
    let then = match status.get("booted_at") {
        Some(Value::Float(x)) => Some(*x),
        _ => None,
    };
    let same = match (sign_in, then, booted_at) {
        (Some(sign_in), Some(then), Some(now)) => {
            matches!(status.get("sign_in"), Some(Value::Str(held)) if held.as_str() == Some(sign_in))
                && (then - now).abs() <= BOOT_SLACK_SECONDS
        }
        _ => false,
    };
    if same {
        (
            word(WatcherEnd::Unexpected.as_str()),
            status.get("last_tick_at").cloned().unwrap_or(Value::Null),
        )
    } else {
        none
    }
}

/// `read_self_check(paths, status)`: the running watcher's self-check, or None.
fn read_self_check(control: &Control, status: Option<&Map>) -> Res<Value> {
    let path = PathBuf::from(&control.paths.self_check_file);
    let Ok(info) = std::fs::metadata(&path) else {
        return Ok(Value::Null);
    };
    if !info.is_file() || control.host.is_symlink(&path) || info.len() > 4096 {
        return Ok(Value::Null);
    }
    let Ok(bytes) = control.host.read_file(&path) else {
        return Ok(Value::Null);
    };
    let Ok(text) = String::from_utf8(bytes) else {
        return Ok(Value::Null);
    };
    let document = match car_machine::compat::loads(&text) {
        Ok(document) => document,
        Err(LoadsError::Recursion) | Err(_) => return Ok(Value::Null),
    };
    let started = status
        .and_then(|row| row.get("started_at"))
        .cloned()
        .unwrap_or(Value::Null);
    match selfcheck::self_check(&document, &started) {
        Ok(found) => Ok(found),
        Err("TypeError" | "AttributeError" | "ValueError" | "RecursionError" | "MemoryError") => {
            Ok(Value::Null)
        }
        Err(class) => Err(Failure::Other(class.to_owned())),
    }
}

impl Control {
    /// `watcher_running()`: True, False, or None where the probe itself was unavailable.
    pub fn watcher_running(&self) -> Option<bool> {
        self.host.watcher_running(&self.state_dir())
    }

    /// `_watcher(store)`: what is known about the watcher: the mutex probe plus its own heartbeat.
    pub fn watcher(&self, store: &State) -> Res<Value> {
        let running = self.watcher_running();
        let status: Option<Map> = match store {
            State::Current(store) => store.watcher_status().ok().flatten(),
            State::Legacy(_) => None,
        };
        let held = |name: &str| -> Value {
            status
                .as_ref()
                .and_then(|row| row.get(name))
                .cloned()
                .unwrap_or(Value::Null)
        };
        let mut ticking = Value::Null;
        if running == Some(true)
            && let Some(row) = status.as_ref()
            && let Some(last) = row.get("last_tick_at")
            && pyval::truthy(last)
        {
            let last = number(last).unwrap_or(0.0);
            ticking = Value::Bool(self.host.now() - last < TICK_STALE_SECONDS);
        }
        let boot = self.host.boot();
        let (ended, ended_at) =
            if running == Some(false) && status.as_ref().is_some_and(|row| !row.is_empty()) {
                how_it_ended(
                    status.as_ref(),
                    running,
                    boot.sign_in.as_deref(),
                    boot.booted_at,
                )
            } else {
                (Value::Null, Value::Null)
            };
        let engine_state = match status.as_ref().and_then(|row| row.get("engine_state")) {
            Some(found) => found.clone(),
            None => word("unknown"),
        };
        let mut out = Map::new();
        let mut put = |name: &str, value: Value| {
            out.insert(Str::from(name), value);
        };
        put("running", running.map_or(Value::Null, Value::Bool));
        put("ticking", ticking);
        put("engine_state", engine_state);
        put("last_tick_at", held("last_tick_at"));
        put("last_tick_ok", held("last_tick_ok"));
        put("code_version", held("code_version"));
        put("pid", held("pid"));
        put("started_at", held("started_at"));
        put("usage", held("usage"));
        put(
            "awake_since",
            if running == Some(true) {
                held("awake_since")
            } else {
                Value::Null
            },
        );
        put("memory_peak", held("memory_peak"));
        put("ended", ended);
        put("ended_at", ended_at);
        put(
            "self_check",
            if running == Some(true) {
                read_self_check(self, status.as_ref())?
            } else {
                Value::Null
            },
        );
        Ok(Value::Object(out))
    }

    /// `plugin_copy()`: which edition is installed here, and which edition the copy of this plugin Codex keeps is.
    pub fn plugin_copy(&self) -> Value {
        let installed = self.host.edition_name();
        let home = PathBuf::from(self.host.codex_home());
        let is_symlink = |path: &std::path::Path| self.host.is_symlink(path);
        let copy = edition::cached_copy(&home, &is_symlink).map(|found| found.as_str().to_owned());
        let matches = copy.as_ref().is_none_or(|found| *found == installed);
        let mut out = Map::new();
        out.insert(Str::from("installed"), Value::from(installed));
        out.insert(Str::from("copy"), copy.map_or(Value::Null, Value::from));
        out.insert(Str::from("matches"), Value::Bool(matches));
        Value::Object(out)
    }

    /// `startup_enabled()`.
    pub fn startup_enabled(&self) -> bool {
        match self.host.startup_read() {
            Ok(Some(value)) if !value.is_empty() => {
                car_platform::startup::belongs_to(&value, &self.paths.home)
            }
            _ => false,
        }
    }

    /// `homes_view(configured, found)`: the Codex homes as Settings show them, with the Codex version in force read
    /// where the Dashboard reads it (the compatibility report).
    pub fn homes_view(&self, configured: &Value, found: &Value) -> Res<Value> {
        let os = self.host.os();
        if !pyval::truthy(configured) {
            return homes::view(&*os, configured, found, &Value::Null, false).map_err(other_class);
        }
        let version = (|| -> Option<Value> {
            let loaded = car_policy::settings::load(&*os, &self.settings_path()).ok()?;
            let reported = self.host.compat_view(&self.state_dir(), &loaded);
            let Value::Object(view) = reported else {
                return None;
            };
            match view.get("engine") {
                Some(Value::Object(engine)) => {
                    Some(engine.get("version").cloned().unwrap_or(Value::Null))
                }
                _ => None,
            }
        })()
        .unwrap_or(Value::Null);
        homes::view(&*os, configured, found, &version, true).map_err(other_class)
    }

    /// `read_power_action(now)`'s `read_file`: (why, document).
    pub fn read_power_action(&self) -> Res<(&'static str, Value)> {
        self.read_power_action_at(self.host.now())
    }

    /// `read_file(path, now)`: (why, document) as of `now`.
    pub fn read_power_action_at(&self, now: f64) -> Res<(&'static str, Value)> {
        let path = PathBuf::from(&self.paths.power_action_file);
        if car_config::paths::is_link(&path.to_string_lossy()) {
            return Ok((poweraction::READ_INVALID, Value::Null));
        }
        let info = match std::fs::metadata(&path) {
            Ok(info) => info,
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
                return Ok((poweraction::READ_MISSING, Value::Null));
            }
            Err(_) => return Ok((poweraction::READ_UNREADABLE, Value::Null)),
        };
        if info.len() > POWER_FILE_LIMIT {
            return Ok((poweraction::READ_INVALID, Value::Null));
        }
        let bytes = match self.host.read_file(&path) {
            Ok(bytes) => bytes,
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
                return Ok((poweraction::READ_MISSING, Value::Null));
            }
            Err(_) => return Ok((poweraction::READ_UNREADABLE, Value::Null)),
        };
        let Ok(text) = String::from_utf8(bytes) else {
            return Ok((poweraction::READ_INVALID, Value::Null));
        };
        let parsed = match car_machine::compat::loads(&text) {
            Ok(parsed) => parsed,
            Err(_) => return Ok((poweraction::READ_INVALID, Value::Null)),
        };
        let document =
            poweraction::read_document(&parsed, &Value::Float(now)).map_err(other_class)?;
        if matches!(document, Value::Null) {
            Ok((poweraction::READ_INVALID, Value::Null))
        } else {
            Ok((poweraction::READ_OK, document))
        }
    }

    /// `power_view()`: what a surface is told of the file, or None while there is no file.
    pub fn power_view(&self) -> Res<Option<Value>> {
        let (why, document) = self.read_power_action()?;
        if why == poweraction::READ_MISSING {
            return Ok(None);
        }
        poweraction::view(&document).map(Some).map_err(other_class)
    }

    /// `get_status()`: what `status` and the top of `dashboard` carry.
    pub fn get_status(&self) -> Res<Value> {
        let held = self.managed();
        let os = self.host.os();
        let loaded = car_policy::settings::load(&*os, &self.settings_path()).map_err(other)?;
        let values = managed::clamp(&loaded, &held);
        let state = self.open(true)?;
        let (stored, counts, legacy, watcher, watcher_homes, codes, pending, marks) = match &state {
            State::Current(store) => {
                let stored = store.settings().map_err(from_store)?;
                let counts = store.status_counts().map_err(from_store)?;
                let watcher = self.watcher(&state)?;
                let homes_found = store
                    .watcher_status()
                    .map_err(from_store)?
                    .and_then(|row| row.get("homes").cloned())
                    .unwrap_or(Value::Null);
                let mut codes = Map::new();
                let mut pending = 0i64;
                for row in store.pending().map_err(from_store)? {
                    pending += 1;
                    let code = public::public_code(&Value::Object(row)).map_err(other_class)?;
                    let at = Str::from(code);
                    let count = match codes.get(&at) {
                        Some(Value::Int(n)) => n.as_i64().unwrap_or(0),
                        _ => 0,
                    };
                    codes.insert(at, Value::from(count + 1));
                }
                let marks = store.failure_marks().map_err(from_store)?;
                (
                    stored,
                    counts,
                    false,
                    watcher,
                    homes_found,
                    codes,
                    pending,
                    Some(marks),
                )
            }
            State::Legacy(store) => {
                let stored = store.settings().map_err(from_store)?;
                let counts = store.status_counts().map_err(from_store)?;
                let watcher = self.watcher(&state)?;
                let pending: i64 = counts
                    .iter()
                    .filter(|(state, _)| {
                        !car_machine::vocab_gen::domain_states::TERMINAL
                            .contains(&state.as_str().unwrap_or_default())
                    })
                    .map(|(_, count)| match count {
                        Value::Int(n) => n.as_i64().unwrap_or(0),
                        _ => 0,
                    })
                    .sum();
                (
                    stored,
                    counts,
                    true,
                    watcher,
                    Value::Null,
                    Map::new(),
                    pending,
                    None,
                )
            }
        };
        drop(state);
        let enabled = pyval::truthy(get(&stored, "enabled")) && !held.disable_auto_resume;
        let observe = pyval::truthy(get(&stored, "observe_only"))
            || values.get("observe_only").is_some_and(pyval::truthy);
        let running = match &watcher {
            Value::Object(map) => map.get("running").cloned().unwrap_or(Value::Null),
            _ => Value::Null,
        };
        let mut status = Map::new();
        let mut put = |name: &str, value: Value| {
            status.insert(Str::from(name), value);
        };
        put("version", Value::from(self.host.version()));
        put("edition", Value::from(edition::shown(self.plug())));
        put("enabled", Value::Bool(enabled));
        put("observe_only", Value::Bool(observe));
        put("watcher_running", running);
        put("watcher", watcher);
        put("upgrade_pending", Value::Bool(legacy));
        put("startup_enabled", Value::Bool(self.startup_enabled()));
        put("pending", Value::from(pending));
        put("states", Value::Object(counts));
        put("codes", Value::Object(codes));
        put(
            "failure_unseen",
            Value::Bool(self.failure_unseen(marks.as_ref())?),
        );
        put(
            "unconfirmed_unseen",
            Value::Bool(self.unconfirmed_unseen(marks.as_ref())?),
        );
        put("settings", Value::Object(values.clone()));
        if held.active() {
            put(
                "managed",
                Value::Array(held.codes().into_iter().map(Value::from).collect()),
            );
        }
        let configured = values.get(homes::FIELD).cloned().unwrap_or(Value::Null);
        let configured = if pyval::truthy(&configured) {
            configured
        } else {
            Value::Array(Vec::new())
        };
        put("codex_homes", self.homes_view(&configured, &watcher_homes)?);
        if let Some(power) = self.power_view()? {
            put("power_action", power);
        }
        let facts = Value::Object(status.clone());
        if let Answer::Is(added) = self.plug().surface(Surface::Status, &facts) {
            // v0.6.26 final: the last usage reading is the newest of the watcher's and the meter's (domain/usage.newest),
            // the one every surface says. Only a plug's meter can make it another - a new object, which is what the
            // reference tests for (`is not`) - so the standard edition's status is exactly what it was.
            let reading = match status.get("watcher") {
                Some(Value::Object(fields)) => fields.get("usage").cloned().unwrap_or(Value::Null),
                _ => Value::Null,
            };
            let made =
                car_machine::domain::usage::newest_made(&reading, &added).map_err(other_class)?;
            status.insert(Str::from(car_policy::plug::EXTRA), added);
            if let Some(newest) = made
                && let Some(Value::Object(fields)) = status.get_mut("watcher")
            {
                // `dict(watcher, usage=newest)`: the key keeps its place, or comes last where it was not there.
                fields.insert(Str::from("usage"), newest);
            }
        }
        Ok(Value::Object(status))
    }
}

/// `poweraction.FILE_LIMIT`.
const POWER_FILE_LIMIT: u64 = 32 * 1024;

/// A Python exception named by a pure function's error.
pub(crate) fn other_class(class: &'static str) -> Failure {
    Failure::Other(class.to_owned())
}
