//! domain/usage.py: the last usage reading, as the watcher's heartbeat keeps it.
//!
//! SEAM, TO BE REPLACED by car-machine's usage (S1.1).

use car_machine::json::{Map, Options, Str, Value, from_str, to_string};

use super::vocab::{USAGE_BUCKETS, USAGE_KEYS, USAGE_SLOTS};
use super::{EPOCH_USAGE, has};
use crate::value::{number, text};

const MAX_WINDOWS: usize = 8;
const MAX_TEXT: usize = 2048;
const WEEK_MINUTES: i64 = 7 * 24 * 60;

fn window(value: &Value) -> Option<Value> {
    let Value::Object(map) = value else {
        return None;
    };
    if map.len() != USAGE_KEYS.len() || !USAGE_KEYS.iter().all(|name| map.contains_key(*name)) {
        return None;
    }
    let field = |name: &str| map.get(name).expect("checked above");
    if !text(field("bucket")).is_some_and(|word| has(USAGE_BUCKETS, word))
        || !text(field("window")).is_some_and(|word| has(USAGE_SLOTS, word))
    {
        return None;
    }
    match field("used_percent") {
        Value::Int(_) | Value::Float(_) => {
            let used = number(field("used_percent"))?;
            if !used.is_finite() || !(0.0..=10000.0).contains(&used) {
                return None;
            }
        }
        _ => return None,
    }
    match field("window_minutes") {
        Value::Null => {}
        Value::Int(minutes) => {
            if !minutes
                .as_i64()
                .is_some_and(|m| 0 < m && m <= 10 * WEEK_MINUTES)
            {
                return None;
            }
        }
        _ => return None,
    }
    match field("reset_at") {
        Value::Null => {}
        Value::Int(reset) => {
            let reset = reset.as_i64()? as f64;
            if !(EPOCH_USAGE.0 <= reset && reset <= EPOCH_USAGE.1) {
                return None;
            }
        }
        _ => return None,
    }
    let mut kept = Map::new();
    for name in USAGE_KEYS {
        kept.insert(Str::new(name), field(name).clone());
    }
    Some(Value::Object(kept))
}

/// `windows_of({"windows": value})`.
pub fn windows_of(found: &Value) -> Option<Vec<Value>> {
    let Value::Array(found) = found else {
        return None;
    };
    if found.is_empty() || found.len() > MAX_WINDOWS {
        return None;
    }
    found.iter().map(window).collect()
}

/// `usage.encode(windows)`: compact JSON, or None.
pub fn encode(windows: &Value) -> Option<String> {
    let kept = windows_of(windows)?;
    let text = to_string(&Value::Array(kept), &Options::new().separators(",", ":")).ok()?;
    (text.chars().count() <= MAX_TEXT).then_some(text)
}

/// `usage.decode(text)`.
pub fn decode(stored: &Value) -> Option<Vec<Value>> {
    let stored = text(stored)?;
    if stored.is_empty() || stored.chars().count() > MAX_TEXT {
        return None;
    }
    windows_of(&from_str(stored).ok()?)
}
