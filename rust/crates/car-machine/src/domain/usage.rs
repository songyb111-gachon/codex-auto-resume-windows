//! `domain/usage.py`: Codex's usage, the last reading: what the watcher keeps of it, and how it is stored.
//!
//! Nothing here reads anything. A reading holds the allowlisted numbers (bucket, window, used_percent,
//! window_minutes, reset_at) and nothing else; one that holds anything else, or is not what these rules make,
//! is no reading at all.

use crate::json::{Map, Options, Str, Value, from_str, to_string};
use crate::pyval::{self, Py, in_tuple, is_finite, is_int, is_number, less};
use crate::vocab_gen::domain_usage::{BUCKETS, KEYS, SLOTS};

use super::states::{EPOCH_USAGE, epoch};

pub const MAX_WINDOWS: usize = 8;
pub const MAX_TEXT: usize = 2048;
pub const WEEK_MINUTES: i64 = 7 * 24 * 60;

/// One window as it is kept, or `None` when it is not exactly one.
fn window(value: &Value) -> Py<Option<Value>> {
    let Value::Object(map) = value else {
        return Ok(None);
    };
    if map.len() != KEYS.len() || !KEYS.iter().all(|key| map.contains_key(*key)) {
        return Ok(None);
    }
    let (used, minutes, reset) = (
        &map["used_percent"],
        &map["window_minutes"],
        &map["reset_at"],
    );
    if !in_tuple(&map["bucket"], BUCKETS) || !in_tuple(&map["window"], SLOTS) {
        return Ok(None);
    }
    if !is_number(used)
        || !is_finite(used)?
        || less(used, &Value::from(0))?
        || pyval::greater(used, &Value::from(10000))?
    {
        return Ok(None);
    }
    if !matches!(minutes, Value::Null) {
        let allowed = is_int(minutes)
            && less(&Value::from(0), minutes)?
            && pyval::less_or_equal(minutes, &Value::from(10 * WEEK_MINUTES))?;
        if !allowed {
            return Ok(None);
        }
    }
    if !matches!(reset, Value::Null) && !epoch(reset, EPOCH_USAGE.0, EPOCH_USAGE.1, true, false)? {
        return Ok(None);
    }
    let mut kept = Map::new();
    for key in KEYS {
        kept.insert(Str::from(*key), map[*key].clone());
    }
    Ok(Some(Value::Object(kept)))
}

/// `windows_of(reply)`: the windows of one usage reply as they are kept, or `None`.
pub fn windows_of(reply: &Value) -> Py<Option<Vec<Value>>> {
    let Value::Object(map) = reply else {
        return Ok(None);
    };
    let Some(Value::Array(found)) = map.get("windows") else {
        return Ok(None);
    };
    if found.is_empty() || found.len() > MAX_WINDOWS {
        return Ok(None);
    }
    let mut kept = Vec::new();
    for entry in found {
        match window(entry)? {
            Some(each) => kept.push(each),
            None => return Ok(None),
        }
    }
    Ok(Some(kept))
}

fn wrapped(windows: Value) -> Value {
    let mut reply = Map::new();
    reply.insert(Str::from("windows"), windows);
    Value::Object(reply)
}

/// `encode(windows)`: the windows as the heartbeat stores them: compact JSON, or `None` when they are not a reading.
pub fn encode(windows: &Value) -> Py<Option<String>> {
    let Some(kept) = windows_of(&wrapped(windows.clone()))? else {
        return Ok(None);
    };
    let options = Options::new().separators(",", ":");
    let written = to_string(&Value::Array(kept), &options).map_err(|_| "ValueError")?;
    Ok((written.chars().count() <= MAX_TEXT).then_some(written))
}

/// `decode(text)`: the windows the heartbeat stored, or `None` for anything that is not exactly a reading.
pub fn decode(stored: &Value) -> Py<Option<Vec<Value>>> {
    let Value::Str(text) = stored else {
        return Ok(None);
    };
    let Some(text) = text.as_str() else {
        return Ok(None);
    };
    if text.is_empty() || text.chars().count() > MAX_TEXT {
        return Ok(None);
    }
    let Ok(value) = from_str(text) else {
        return Ok(None);
    };
    windows_of(&wrapped(value))
}
