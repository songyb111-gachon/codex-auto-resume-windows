//! Python's operators on the engine's values: a record is a `dict`, read with `row[name]` / `row.get(name)` (one
//! here: every record the store hands out has every column), `x or y`, `dict(row, name=value)`.

use std::collections::{HashSet, VecDeque};
use std::hash::Hash;

use car_machine::json::{Map, Str, Value};
use car_machine::pyval::{self, Py};
pub use car_policy::classify::value::{arithmetic, get, number, or_zero, text, text_of, truthy};

/// A `dict` in the order the pairs are given.
pub fn row(pairs: Vec<(&str, Value)>) -> Map {
    let mut map = Map::new();
    for (key, value) in pairs {
        map.insert(Str::from(key), value);
    }
    map
}

/// `dict(row, **pairs)`.
pub fn with(row: &Map, pairs: Vec<(&str, Value)>) -> Map {
    let mut copy = row.clone();
    for (key, value) in pairs {
        copy.insert(Str::from(key), value);
    }
    copy
}

/// `row[name]` as text, "" where it is not text (a record's ids and words always are).
pub fn s(row: &Map, name: &str) -> String {
    text_of(row, name).unwrap_or_default().to_owned()
}

/// `row[name]` as text or None.
pub fn opt(row: &Map, name: &str) -> Option<String> {
    text_of(row, name).map(str::to_owned)
}

/// `value or default`, as a number.
pub fn or_number(value: &Value, default: f64) -> Py<f64> {
    if truthy(value) {
        arithmetic(value).ok_or("TypeError")
    } else {
        Ok(default)
    }
}

/// `value or default`.
pub fn or(value: &Value, default: Value) -> Value {
    if truthy(value) {
        value.clone()
    } else {
        default
    }
}

/// A number a value must be (`row[name] - x`), else TypeError.
pub fn num(value: &Value) -> Py<f64> {
    arithmetic(value).ok_or("TypeError")
}

/// `str(value)` of a text, `None` for none.
pub fn word(text: Option<&str>) -> Value {
    text.map_or(Value::Null, Value::from)
}

/// `a == b`.
pub fn eq(a: &Value, b: &Value) -> bool {
    pyval::eq(a, b)
}

/// `value.get(name)` of a value that should be a `dict`: AttributeError for anything else.
pub fn field<'a>(value: &'a Value, name: &str) -> Py<&'a Value> {
    static NULL: Value = Value::Null;
    match value {
        Value::Object(map) => Ok(map.get(name).unwrap_or(&NULL)),
        _ => Err("AttributeError"),
    }
}

/// `int + 1` of a stored count.
pub fn plus_one(value: &Value) -> Py<Value> {
    match value {
        Value::Int(number) => number
            .as_i64()
            .and_then(|n| n.checked_add(1))
            .map(Value::from)
            .ok_or("OverflowError"),
        Value::Bool(on) => Ok(Value::from(i64::from(*on) + 1)),
        Value::Float(number) => Ok(Value::Float(number + 1.0)),
        _ => Err("TypeError"),
    }
}

/// An integer a stored count is (`int(value)`).
pub fn int_of(value: &Value) -> Py<i64> {
    match value {
        Value::Int(number) => number.as_i64().ok_or("OverflowError"),
        Value::Bool(on) => Ok(i64::from(*on)),
        Value::Float(number) if number.is_finite() => Ok(number.trunc() as i64),
        Value::Float(_) => Err("OverflowError"),
        _ => Err("TypeError"),
    }
}

/// A `dict` that keeps at most `limit` keys, the oldest let go first, never all at once (engine/detect.py `_keep`).
#[derive(Debug, Default)]
pub struct Kept<K: Hash + Eq + Clone> {
    order: VecDeque<K>,
    held: HashSet<K>,
}

impl<K: Hash + Eq + Clone> Kept<K> {
    pub fn new() -> Self {
        Kept {
            order: VecDeque::new(),
            held: HashSet::new(),
        }
    }

    /// `_keep(held, key)`: whether `key` is new, which it joins.
    pub fn keep(&mut self, key: K, limit: usize) -> bool {
        if self.held.contains(&key) {
            return false;
        }
        if self.held.len() >= limit
            && let Some(oldest) = self.order.pop_front()
        {
            self.held.remove(&oldest);
        }
        self.held.insert(key.clone());
        self.order.push_back(key);
        true
    }

    pub fn contains(&self, key: &K) -> bool {
        self.held.contains(key)
    }

    pub fn len(&self) -> usize {
        self.held.len()
    }

    pub fn is_empty(&self) -> bool {
        self.held.is_empty()
    }

    pub fn keys(&self) -> impl Iterator<Item = &K> {
        self.order.iter()
    }
}
