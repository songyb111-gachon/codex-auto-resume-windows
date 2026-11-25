//! The acting half of `bridge.run`'s world (S5.1b): what car-control asks the machine to do, or asks only the
//! watcher and the registry - each answered from the request's world, and each call written down, in order, with its
//! arguments (`calls`), so the diff holds the calls to the reference's, which `tests/rustdiff/actworld.py` patches
//! to the same stand-ins and records the same way.
//!
//! Nothing here starts a process, signals an event, writes the registry, reads the network or acts on the power: a
//! launch is a stand-in whose `poll` answers the world's list, the Run key is a value in memory, and a sleep only
//! moves the stand-in clock.

use std::collections::VecDeque;
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex};

use car_control::host::{Event, Judge, Launched, Raised};
use car_machine::json::{Map, Str, Value};

/// The world's answers for the acting calls, and the record of the calls made.
pub struct Acts {
    world: Map,
    calls: Mutex<Vec<Value>>,
    clock: Mutex<f64>,
    probes: Mutex<VecDeque<Value>>,
    startup: Mutex<Option<String>>,
    tokens: Mutex<u64>,
}

fn text(value: &Value) -> Option<String> {
    match value {
        Value::Str(text) => text.as_str().map(str::to_owned),
        _ => None,
    }
}

fn path_text(path: &Path) -> Value {
    Value::from(path.to_string_lossy().into_owned())
}

/// `{"raise": [class, message]}` or `{"raise": class}`: what the stand-in raises.
fn raised_of(value: &Value) -> Option<Raised> {
    let Value::Object(map) = value else {
        return None;
    };
    match map.get("raise")? {
        Value::Array(pair) => Some(Raised::new(
            &text(pair.first()?)?,
            text(pair.get(1).unwrap_or(&Value::Null)).unwrap_or_default(),
        )),
        other => Some(Raised::new(&text(other)?, "")),
    }
}

impl Acts {
    pub fn from_world(world: &Map) -> Acts {
        let probes = match world.get("probes") {
            Some(Value::Array(items)) => items.iter().cloned().collect(),
            _ => VecDeque::new(),
        };
        Acts {
            world: world.clone(),
            calls: Mutex::new(Vec::new()),
            clock: Mutex::new(1000.0),
            probes: Mutex::new(probes),
            startup: Mutex::new(world.get("startup_value").and_then(text)),
            tokens: Mutex::new(0),
        }
    }

    fn get(&self, name: &str) -> &Value {
        static NULL: Value = Value::Null;
        self.world.get(name).unwrap_or(&NULL)
    }

    /// Write one call down.
    pub fn call(&self, name: &str, arguments: Vec<Value>) {
        let mut entry = vec![Value::from(name)];
        entry.extend(arguments);
        self.calls
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .push(Value::Array(entry));
    }

    pub fn calls(&self) -> Value {
        Value::Array(
            self.calls
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner)
                .clone(),
        )
    }

    /// The next answer of the watcher's mutex: the world's `probes` in turn, then `watcher_running`.
    pub fn watcher_running(&self, fixed: Option<bool>) -> Option<bool> {
        self.call("watcher_running", vec![]);
        let next = self
            .probes
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .pop_front();
        match next {
            Some(Value::Bool(on)) => Some(on),
            Some(_) => None,
            None => fixed,
        }
    }

    pub fn monotonic(&self) -> f64 {
        *self
            .clock
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
    }

    pub fn sleep(&self, seconds: f64) {
        self.call("sleep", vec![Value::Float(seconds)]);
        *self
            .clock
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner) += seconds;
    }

    pub fn signal(&self, event: Event) -> Result<bool, Raised> {
        self.call("signal", vec![Value::from(event.word())]);
        match self.get("signals") {
            Value::Object(map) => match map.get(event.word()) {
                Some(Value::Bool(on)) => Ok(*on),
                Some(other) => {
                    Err(raised_of(other).unwrap_or_else(|| Raised::new("AdapterError", "")))
                }
                None => Ok(false),
            },
            _ => Ok(false),
        }
    }

    fn startup_raise(&self, name: &str) -> Option<Raised> {
        match self.get("startup_raise") {
            Value::Object(map) => map
                .get(name)
                .and_then(text)
                .map(|message| Raised::new("StartupError", message)),
            _ => None,
        }
    }

    pub fn startup_read(&self) -> Result<Option<String>, Raised> {
        self.call("startup_read", vec![]);
        if let Some(raised) = self.startup_raise("read") {
            return Err(raised);
        }
        Ok(self
            .startup
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .clone())
    }

    pub fn startup_install(&self, command: &str) -> Result<bool, Raised> {
        self.call("startup_install", vec![Value::from(command)]);
        if let Some(raised) = self.startup_raise("install") {
            return Err(raised);
        }
        let mut held = self
            .startup
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        let changed = held.as_deref() != Some(command);
        *held = Some(command.to_owned());
        Ok(changed)
    }

    pub fn startup_uninstall(&self) -> Result<bool, Raised> {
        self.call("startup_uninstall", vec![]);
        if let Some(raised) = self.startup_raise("uninstall") {
            return Err(raised);
        }
        Ok(self
            .startup
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .take()
            .is_some())
    }

    /// A value the world names, or the exception it says to raise.
    fn answer(&self, name: &str) -> Result<Value, Raised> {
        let found = self.get(name);
        match raised_of(found) {
            Some(raised) => Err(raised),
            None => Ok(match found {
                Value::Object(map) if map.contains_key("value") => {
                    map.get("value").cloned().unwrap_or(Value::Null)
                }
                other => other.clone(),
            }),
        }
    }

    pub fn protocol_value(&self) -> Result<Option<String>, Raised> {
        self.call("protocol_value", vec![]);
        Ok(text(&self.answer("protocol_value")?))
    }

    pub fn notification_identity_owner(&self, home: &str) -> Result<Option<bool>, Raised> {
        self.call("notification_identity_owner", vec![Value::from(home)]);
        Ok(match self.answer("notification_owner")? {
            Value::Bool(on) => Some(on),
            _ => None,
        })
    }

    pub fn python_launcher(&self) -> Result<PathBuf, Raised> {
        self.call("python_launcher", vec![]);
        match self.get("launcher") {
            Value::Str(path) => Ok(PathBuf::from(path.as_str().unwrap_or_default())),
            other => Err(raised_of(other).unwrap_or_else(|| {
                Raised::new("StartupError", "no pythonw.exe beside python.exe")
            })),
        }
    }

    pub fn launch(
        self: &Arc<Self>,
        argv: &[String],
        cwd: &Path,
        flags: u32,
    ) -> Result<Box<dyn Launched>, Raised> {
        self.call(
            "launch",
            vec![
                Value::Array(argv.iter().map(|each| Value::from(each.as_str())).collect()),
                path_text(cwd),
                Value::from(i64::from(flags)),
            ],
        );
        let launch = self.get("launch");
        if let Some(raised) = raised_of(launch) {
            return Err(raised);
        }
        let polls = match launch {
            Value::Object(map) => match map.get("polls") {
                Some(Value::Array(items)) => items.clone(),
                _ => Vec::new(),
            },
            _ => Vec::new(),
        };
        let pid = match launch {
            Value::Object(map) => match map.get("pid") {
                Some(Value::Int(pid)) => pid.as_i64().unwrap_or(0) as u32,
                _ => 4242,
            },
            _ => 4242,
        };
        Ok(Box::new(Stood {
            acts: Arc::clone(self),
            pid,
            polls: polls.into(),
        }))
    }

    pub fn power_available(&self, action: &str) -> Result<(bool, Option<String>), Raised> {
        self.call("power_available", vec![Value::from(action)]);
        match self.get("power") {
            Value::Object(map) => match map.get(action) {
                None | Some(Value::Null) => Ok((true, None)),
                Some(Value::Str(reason)) => Ok((false, reason.as_str().map(str::to_owned))),
                Some(other) => Err(raised_of(other).unwrap_or_else(|| Raised::new("OSError", ""))),
            },
            other => match raised_of(other) {
                Some(raised) => Err(raised),
                None => Ok((true, None)),
            },
        }
    }

    pub fn internet(&self) -> Result<Option<bool>, Raised> {
        self.call("internet", vec![]);
        Ok(match self.answer("internet")? {
            Value::Bool(on) => Some(on),
            _ => None,
        })
    }

    /// The world's tokens: SHA-256 of `token-<n>`, the n-th asked, cut to length - the same on both sides.
    fn token(&self, count: usize) -> Vec<u8> {
        let mut number = self
            .tokens
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        *number += 1;
        let mut bytes = Vec::new();
        let mut round = 0;
        while bytes.len() < count {
            let seed = format!("token-{}-{round}", *number);
            bytes.extend_from_slice(&car_machine::hash::sha256(seed.as_bytes()));
            round += 1;
        }
        bytes.truncate(count);
        bytes
    }

    pub fn token_hex(&self, count: usize) -> String {
        self.call("token_hex", vec![Value::from(count as i64)]);
        car_machine::hash::hex(&self.token(count))
    }

    pub fn token_bytes(&self, count: usize) -> Vec<u8> {
        self.call("token_bytes", vec![Value::from(count as i64)]);
        self.token(count)
    }

    pub fn process_context(&self) -> Result<Value, Raised> {
        self.call("process_context", vec![]);
        self.answer("process_context")
    }

    pub fn pid(&self) -> u32 {
        match self.get("pid") {
            Value::Int(pid) => pid.as_i64().unwrap_or(0) as u32,
            _ => 7777,
        }
    }

    pub fn process_there(&self, pid: u32) -> bool {
        self.call("process_there", vec![Value::from(i64::from(pid))]);
        match self.get("alive") {
            Value::Array(items) => items.iter().any(
                |each| matches!(each, Value::Int(found) if found.as_i64() == Some(i64::from(pid))),
            ),
            _ => false,
        }
    }

    pub fn windows_version(&self) -> Option<String> {
        self.call("windows_version", vec![]);
        text(self.get("windows_version"))
    }

    pub fn system(&self) -> Value {
        self.call("system", vec![]);
        self.get("system").clone()
    }

    pub fn compat_view(&self, settings: &Map) -> Value {
        self.call(
            "compat_view",
            vec![settings.get("codex_exe").cloned().unwrap_or(Value::Null)],
        );
        self.get("compat_view").clone()
    }

    pub fn compat_live_view(&self, codex_home: &str, explicit: &Value) -> Result<Value, Raised> {
        self.call(
            "compat_live_view",
            vec![Value::from(codex_home), explicit.clone()],
        );
        self.answer("compat_live")
    }

    pub fn compat_import(&self, target: &Str, origin: &Value) -> Result<Value, Raised> {
        self.call(
            "compat_import",
            vec![Value::Str(target.clone()), origin.clone()],
        );
        self.answer("compat_import")
    }

    pub fn compat_refresh(&self, home: &Path) -> Result<Value, Raised> {
        self.call("compat_refresh", vec![path_text(home)]);
        self.answer("compat_refresh")
    }

    pub fn checkup(&self) -> Result<Value, Raised> {
        self.call("checkup", vec![]);
        self.answer("checkup")
    }

    pub fn checkup_for_bundle(&self, key: &[u8]) -> Result<Value, Raised> {
        self.call(
            "checkup_for_bundle",
            vec![Value::from(car_machine::hash::hex(key))],
        );
        self.answer("checkup_bundle")
    }

    pub fn note_turn(&self) -> bool {
        self.call("note_turn", vec![]);
        !matches!(self.get("note_turn"), Value::Bool(false))
    }

    pub fn rescan_judge(self: &Arc<Self>) -> Result<Box<dyn Judge>, Raised> {
        self.call("rescan_judge_for", vec![]);
        if let Some(raised) = raised_of(self.get("judge_for")) {
            return Err(raised);
        }
        let table = match self.get("judge") {
            Value::Object(map) => map.clone(),
            _ => Map::new(),
        };
        Ok(Box::new(Judged {
            acts: Arc::clone(self),
            table,
        }))
    }
}

/// A launch's stand-in: `poll` answers the world's list in turn, its last answer from then on.
struct Stood {
    acts: Arc<Acts>,
    pid: u32,
    polls: VecDeque<Value>,
}

impl Launched for Stood {
    fn pid(&self) -> u32 {
        self.pid
    }

    fn poll(&mut self) -> Option<i64> {
        self.acts.call("poll", vec![]);
        let answer = if self.polls.len() > 1 {
            self.polls.pop_front()
        } else {
            self.polls.front().cloned()
        };
        match answer {
            Some(Value::Int(code)) => code.as_i64(),
            _ => None,
        }
    }
}

/// Rescan's judge, from the world's table: `{"<id>": [outcome, reason] | {"raise": class}, "*": ...}`.
struct Judged {
    acts: Arc<Acts>,
    table: Map,
}

impl Judge for Judged {
    fn judge(&mut self, row: &Map, _kin: &[Map]) -> Result<(Value, Value), Raised> {
        let key = row
            .get("interruption_id")
            .and_then(text)
            .unwrap_or_default();
        self.acts.call("judge", vec![Value::from(key.as_str())]);
        let found = self
            .table
            .get(key.as_str())
            .or_else(|| self.table.get("*"))
            .cloned()
            .unwrap_or(Value::Null);
        if let Some(raised) = raised_of(&found) {
            return Err(raised);
        }
        match found {
            Value::Array(pair) if pair.len() == 2 => Ok((pair[0].clone(), pair[1].clone())),
            _ => Ok((Value::from("unresolved"), Value::from("no_proof"))),
        }
    }
}
