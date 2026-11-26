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

// ------------------------------------------------------------------------------- the v0.6.26 final's additions
// `newest` and `meter_windows` came with the v0.6.26 final (car-surface's S6.0 ported them beside this beta.2 port as a
// seam; Integration 7 moved them here unchanged). The small Python helpers they read are this module's own.

/// `newest(reading, added)`: the watcher's own `reading`, or the advanced edition's meter's where it read later and
/// its shape is one `windows_of` keeps (v0.6.26 final).
pub fn newest(reading: &Value, added: &Value) -> Py<Value> {
    Ok(newest_made(reading, added)?.unwrap_or_else(|| reading.clone()))
}

/// `newest(reading, added)` as its callers that test by identity read it (`control/watcher.py` `get_status`: `if newest
/// is not watcher.get("usage")`): `Some` with the reading the rule made - a new object - where it made one, `None`
/// where it answered the very `reading` it was given. Equality would not do: a reading whose `read_at` is `true` equals
/// a meter's `1` in Python and is still not the object the rule hands back.
pub fn newest_made(reading: &Value, added: &Value) -> Py<Option<Value>> {
    let meter = match added {
        Value::Object(map) => map.get("meter").cloned().unwrap_or(Value::Null),
        _ => Value::Null,
    };
    let Value::Object(fields) = &meter else {
        return Ok(None);
    };
    let (Some(Value::Array(found)), Some(read_at)) = (fields.get("windows"), fields.get("read_at"))
    else {
        return Ok(None);
    };
    if !pyval::is_number(read_at) {
        return Ok(None);
    }
    if let Value::Object(own) = reading
        && let Some(own_at) = own.get("read_at")
        && pyval::is_number(own_at)
        && !pyval::less(own_at, read_at)?
        && pyval::order(own_at, read_at)?.is_some()
    {
        return Ok(None);
    }
    Ok(
        meter_windows(&Value::Array(found.clone()), reading)?.map(|windows| {
            object_of([
                ("read_at", read_at.clone()),
                ("windows", Value::Array(windows)),
            ])
        }),
    )
}

/// A dict keyed by a pair of values, as Python keys one.
fn find<'a, T>(entries: &'a [((Value, Value), T)], key: &(Value, Value)) -> Option<&'a T> {
    entries
        .iter()
        .find(|((a, b), _)| pyval::eq(a, &key.0) && pyval::eq(b, &key.1))
        .map(|(_, value)| value)
}

fn get(window: &Value, key: &str) -> Value {
    match window {
        Value::Object(map) => map.get(key).cloned().unwrap_or(Value::Null),
        _ => Value::Null,
    }
}

/// `meter_windows(found, reading)`: the meter's windows as core keeps a window, or None.
pub fn meter_windows(found: &Value, reading: &Value) -> Py<Option<Vec<Value>>> {
    let Value::Array(found) = found else {
        return Ok(None);
    };
    let own = match reading {
        Value::Object(map) => map.get("windows").cloned().unwrap_or(Value::Null),
        _ => Value::Null,
    };
    let mut known: Vec<((Value, Value), Value)> = Vec::new();
    for window in items_of(or_else(&own, &Value::Array(Vec::new())))? {
        if let Value::Object(_) = window {
            let key = (get(&window, "bucket"), get(&window, "window_minutes"));
            pyval::hashable(&key.0)?;
            pyval::hashable(&key.1)?;
            let slot = get(&window, "window");
            match known
                .iter_mut()
                .find(|((a, b), _)| pyval::eq(a, &key.0) && pyval::eq(b, &key.1))
            {
                Some(entry) => entry.1 = slot,
                None => known.push((key, slot)),
            }
        }
    }
    let mut lengths: Vec<(Value, Vec<Value>)> = Vec::new();
    for window in found {
        if !matches!(window, Value::Object(_)) {
            return Ok(None);
        }
        let bucket = get(window, "bucket");
        pyval::hashable(&bucket)?;
        let minutes = get(window, "window_minutes");
        match lengths
            .iter_mut()
            .find(|(each, _)| pyval::eq(each, &bucket))
        {
            Some(entry) => entry.1.push(minutes),
            None => lengths.push((bucket, vec![minutes])),
        }
    }
    let mut shaped = Vec::new();
    for window in found {
        let bucket = get(window, "bucket");
        let minutes = get(window, "window_minutes");
        let mut slot = find(&known, &(bucket.clone(), minutes.clone()))
            .cloned()
            .unwrap_or(Value::Null);
        if !SLOTS.iter().any(|each| pyval::is(&slot, each)) {
            let listed = lengths
                .iter()
                .find(|(each, _)| pyval::eq(each, &bucket))
                .map(|(_, listed)| listed.clone())
                .ok_or("KeyError")?;
            // `sorted(lengths, key=lambda each: (each is None, each if type(each) is int else 0))`.
            let key = |each: &Value| -> (i64, Value) {
                let none = i64::from(matches!(each, Value::Null));
                let number = match each {
                    Value::Int(_) => each.clone(),
                    _ => Value::from(0),
                };
                (none, number)
            };
            let ordered = sorted_by(&listed, &|a: &Value, b: &Value| {
                let (p, q) = (key(a), key(b));
                tuple_less(&[Value::from(p.0), p.1], &[Value::from(q.0), q.1])
            })?;
            let first = ordered
                .iter()
                .position(|each| pyval::eq(each, &minutes))
                .ok_or("ValueError")?;
            slot = Value::from(if first == 0 { SLOTS[0] } else { SLOTS[1] });
        }
        let mut made = Map::new();
        made.insert(Str::from("bucket"), bucket);
        made.insert(Str::from("window"), slot);
        made.insert(Str::from("used_percent"), get(window, "used_percent"));
        made.insert(Str::from("window_minutes"), minutes);
        made.insert(Str::from("reset_at"), get(window, "reset_at"));
        shaped.push(Value::Object(made));
    }
    windows_of(&object_of([("windows", Value::Array(shaped))]))
}

/// `iter(value)` as a list: a list's items, a text's characters, a dict's keys; anything else is not iterable.
fn items_of(value: &Value) -> Py<Vec<Value>> {
    match value {
        Value::Array(found) => Ok(found.clone()),
        Value::Str(text) => Ok(text
            .code_points()
            .map(|point| Value::Str(Str::from_code_points([point]).unwrap_or_default()))
            .collect()),
        Value::Object(map) => Ok(map.keys().map(|key| Value::Str(key.clone())).collect()),
        _ => Err("TypeError"),
    }
}

/// `value or fallback`.
fn or_else<'a>(value: &'a Value, fallback: &'a Value) -> &'a Value {
    if pyval::truthy(value) {
        value
    } else {
        fallback
    }
}

/// `sorted(items, key=...)`: stable, comparing keys with `<` only, as CPython's sort does; a comparison that raises
/// stops it with that exception (binary insertion).
fn sorted_by<T: Clone>(found: &[T], less: &dyn Fn(&T, &T) -> Py<bool>) -> Py<Vec<T>> {
    let mut out: Vec<T> = Vec::with_capacity(found.len());
    for item in found {
        let (mut low, mut high) = (0, out.len());
        while low < high {
            let middle = (low + high) / 2;
            if less(item, &out[middle])? {
                high = middle;
            } else {
                low = middle + 1;
            }
        }
        out.insert(low, item.clone());
    }
    Ok(out)
}

/// `a < b` of two tuples of values, as Python compares tuples: the first pair that is not `==` decides.
fn tuple_less(a: &[Value], b: &[Value]) -> Py<bool> {
    for (p, q) in a.iter().zip(b) {
        if !pyval::eq(p, q) {
            return pyval::less(p, q);
        }
    }
    Ok(a.len() < b.len())
}

/// A `Map` from pairs, in order.
fn object_of<const N: usize>(pairs: [(&str, Value); N]) -> Value {
    let mut map = Map::new();
    for (key, value) in pairs {
        map.insert(Str::from(key), value);
    }
    Value::Object(map)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn newest_reading() {
        let own = from_str(r#"{"read_at": 100, "windows": []}"#).unwrap();
        let added = from_str(
            r#"{"meter": {"read_at": 200, "windows": [{"bucket": "codex", "window_minutes": 300, "used_percent": 5, "reset_at": null}]}}"#,
        )
        .unwrap();
        let found = newest(&own, &added).unwrap();
        let Value::Object(found) = found else {
            panic!("a reading")
        };
        assert_eq!(found["read_at"], Value::from(200));
        let Value::Array(windows) = &found["windows"] else {
            panic!("windows")
        };
        let Value::Object(first) = &windows[0] else {
            panic!("a window")
        };
        assert_eq!(first["window"], Value::from("primary"));
        let later = from_str(r#"{"read_at": 300, "windows": []}"#).unwrap();
        assert_eq!(newest(&later, &added).unwrap(), later);
    }

    #[test]
    fn a_meter_of_two_windows_with_a_band_is_kept_in_cores_shape() {
        let added = from_str(
            r#"{"meter": {"read_at": 1799655000, "notices": [], "windows": [{"bucket": "codex", "window_minutes": 300, "used_percent": 12, "reset_at": 1800003600, "band": "none"}, {"bucket": "codex", "window_minutes": 10080, "used_percent": 2, "reset_at": 1800086400, "band": "warn"}]}}"#,
        )
        .unwrap();
        let made = newest_made(&Value::Null, &added).unwrap();
        assert!(made.is_some(), "{made:?}");
    }
}
