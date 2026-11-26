//! What every op of the probe shares: the scripted stand-ins' answers, the one log, the token counter, bytes as the
//! request carries them (`{"hex": ...}`) and paths as the answer names them (relative to the working folder).

use std::collections::HashMap;
use std::path::Path;
use std::sync::Mutex;
use std::sync::atomic::{AtomicU64, Ordering};

use car_adv::codex::authfile::Fault;
use car_adv::state::seam::Tokens;
use car_machine::json::{Map, Str, Value};

static LOG: Mutex<Vec<Value>> = Mutex::new(Vec::new());
static COUNTER: AtomicU64 = AtomicU64::new(0);
static SEED: AtomicU64 = AtomicU64::new(0);
static CLOCK: Mutex<f64> = Mutex::new(1_767_225_600.0);

pub fn text(value: &str) -> Value {
    Value::Str(Str::new(value))
}

/// One stand-in call, as the reference's `LOG.append` writes it.
pub fn log(entry: Vec<Value>) {
    LOG.lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner)
        .push(Value::Array(entry));
}

/// The log so far, emptied.
pub fn take_log() -> Vec<Value> {
    std::mem::take(
        &mut *LOG
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner),
    )
}

/// The request's world: the token counter's seed and the saved accounts' clock.
pub fn set_world(world: &Value) {
    if let Value::Object(map) = world {
        if let Some(seed) = map.get("tokens").and_then(car_adv::state::py::small) {
            SEED.store(seed as u64, Ordering::SeqCst);
        }
        if let Some(clock) = map.get("clock").and_then(car_adv::state::py::as_f64) {
            *CLOCK
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner) = clock;
        }
    }
}

pub fn clock() -> f64 {
    *CLOCK
        .lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner)
}

pub fn reset_counter() {
    COUNTER.store(SEED.load(Ordering::SeqCst), Ordering::SeqCst);
}

/// `secrets.token_hex(count)`: the shared counter, as both sides number it.
pub struct Counter;

impl Tokens for Counter {
    fn hex(&self, count: usize) -> String {
        let next = COUNTER.fetch_add(1, Ordering::SeqCst) + 1;
        format!("{:0>width$x}", next, width = count * 2)
    }
}

/// `{"hex": "..."}` as bytes.
pub fn bytes(value: &Value) -> Option<Vec<u8>> {
    let Value::Object(map) = value else {
        return None;
    };
    if map.len() != 1 {
        return None;
    }
    let Some(Value::Str(found)) = map.get("hex") else {
        return None;
    };
    let found = found.as_str()?;
    (0..found.len())
        .step_by(2)
        .map(|at| u8::from_str_radix(found.get(at..at + 2)?, 16).ok())
        .collect()
}

pub fn hex(data: &[u8]) -> Value {
    let mut map = Map::new();
    map.insert(Str::new("hex"), text(&car_machine::hash::hex(data)));
    Value::Object(map)
}

/// A path as the answer names it: relative to the working folder, with forward slashes.
pub fn rel(path: &Path) -> String {
    let root = std::env::current_dir().unwrap_or_default();
    match path.strip_prefix(&root) {
        Ok(inside) => inside.to_string_lossy().replace('\\', "/"),
        Err(_) => path.to_string_lossy().into_owned(),
    }
}

/// `{"hex": ...}` anywhere in a value made bytes as the store carries them (a list of numbers).
pub fn unhex(value: &Value) -> Value {
    if let Some(data) = bytes(value) {
        return car_adv::profiles::bytes_value(&data);
    }
    match value {
        Value::Array(items) => Value::Array(items.iter().map(unhex).collect()),
        Value::Object(map) => Value::Object(
            map.iter()
                .map(|(key, item)| (key.clone(), unhex(item)))
                .collect(),
        ),
        other => other.clone(),
    }
}

/// Answers per call kind, taken in order (the last one repeated); "raise" or "raise:Class" raises.
pub struct Script {
    kinds: HashMap<String, Vec<Value>>,
}

impl Script {
    pub fn new(value: &Value) -> Script {
        let mut kinds = HashMap::new();
        if let Value::Object(map) = value {
            for (key, items) in map {
                if let Value::Array(items) = items {
                    kinds.insert(key.as_str().unwrap_or_default().to_owned(), items.clone());
                }
            }
        }
        Script { kinds }
    }

    pub fn take(&mut self, kind: &str, default: Value) -> Result<Value, Fault> {
        let Some(found) = self.kinds.get_mut(kind) else {
            return Ok(default);
        };
        if found.is_empty() {
            return Ok(default);
        }
        let value = if found.len() > 1 {
            found.remove(0)
        } else {
            found[0].clone()
        };
        if let Value::Str(word) = &value
            && let Some(word) = word.as_str()
            && word.starts_with("raise")
        {
            let class = word
                .split_once(':')
                .map_or("RuntimeError", |(_, class)| class);
            return Err(Fault::new(class, "stand-in"));
        }
        Ok(value)
    }
}
