//! Python's operators over the values a record or a settings dict holds, as the policy's functions read them.
//!
//! A record is a `dict` of column to `int`, `float`, `str`, `None` or `bool` (car-machine's [`Value`] model, the
//! store's rows), and the rules are written against Python's dynamic values: `x or 0`, `1 == 1.0 == True`, a dict's
//! `.get`. car-store keeps the same helpers for its rows; car-policy holds its own so the store reads the policy and
//! never the other way round.

use std::sync::LazyLock;

use car_machine::json::{Int, Map, Str, Value};
use car_machine::pyval::Py;

/// One record, or one settings dict: a `dict` in the order its keys were put in.
pub type Row = Map;

static NULL: Value = Value::Null;
static EMPTY: LazyLock<Map> = LazyLock::new(Map::new);

/// `row.get(name)`: `None` where the row has no such key.
pub fn get<'a>(row: &'a Row, name: &str) -> &'a Value {
    row.get(name).unwrap_or(&NULL)
}

/// `value.get(name)` of a value that must be a dict: anything else has no `.get` (AttributeError).
pub fn dict_get<'a>(value: &'a Value, name: &str) -> Py<&'a Value> {
    match value {
        Value::Object(map) => Ok(get(map, name)),
        _ => Err("AttributeError"),
    }
}

/// `values if isinstance(values, dict) else {}`.
pub fn dict_or_empty(value: &Value) -> &Map {
    match value {
        Value::Object(map) => map,
        _ => &EMPTY,
    }
}

/// `(values or {})`: a falsy value is `{}`, a truthy one that is no dict has no `.get` (AttributeError).
pub fn or_empty(value: &Value) -> Py<&Map> {
    match value {
        Value::Object(map) => Ok(map),
        other if !truthy(other) => Ok(&EMPTY),
        _ => Err("AttributeError"),
    }
}

/// A `str`'s text, when the value is one (and has no lone surrogate).
pub fn text(value: &Value) -> Option<&str> {
    match value {
        Value::Str(text) => text.as_str(),
        _ => None,
    }
}

/// `row[name]` as text, when it is a `str`.
pub fn text_of<'a>(row: &'a Row, name: &str) -> Option<&'a str> {
    text(get(row, name))
}

/// An `int` value.
pub fn int(number: i64) -> Value {
    Value::Int(Int::from(number))
}

/// A `str` value.
pub fn string(text: &str) -> Value {
    Value::Str(Str::new(text))
}

/// `None`, or the text.
pub fn optional(text: Option<&str>) -> Value {
    text.map_or(Value::Null, string)
}

/// The number a value is, for arithmetic and comparison: an `int` or a `float`, never a `bool`. An `int` beyond
/// f64 comes back infinite.
pub fn number(value: &Value) -> Option<f64> {
    match value {
        Value::Int(number) => Some(int_as_f64(number)),
        Value::Float(number) => Some(*number),
        _ => None,
    }
}

/// An `int`'s value as an f64, as Python's `float(n)` - infinite where that would overflow.
pub fn int_as_f64(number: &Int) -> f64 {
    number
        .as_i64()
        .map(|n| n as f64)
        .or_else(|| number.as_u64().map(|n| n as f64))
        .unwrap_or_else(|| number.to_string().parse::<f64>().unwrap_or(f64::INFINITY))
}

/// The number a value is in Python arithmetic, a `bool` counting as 0 or 1.
pub fn arithmetic(value: &Value) -> Option<f64> {
    match value {
        Value::Bool(on) => Some(f64::from(u8::from(*on))),
        other => number(other),
    }
}

/// `value or 0`, as a number (None, 0 and False all give 0).
pub fn or_zero(value: &Value) -> f64 {
    if truthy(value) {
        arithmetic(value).unwrap_or(0.0)
    } else {
        0.0
    }
}

/// Python's truthiness.
pub fn truthy(value: &Value) -> bool {
    car_machine::pyval::truthy(value)
}

/// `value is True`.
pub fn is_true(value: &Value) -> bool {
    matches!(value, Value::Bool(true))
}

/// `value in a_frozenset_of_words`: an unhashable value (a list, a dict) raises TypeError.
pub fn in_set(value: &Value, words: &[&str]) -> Py<bool> {
    car_machine::pyval::in_set(value, words)
}

/// `value in a_tuple_of_words`: compared with `==`, nothing hashed.
pub fn in_tuple(value: &Value, words: &[&str]) -> bool {
    car_machine::pyval::in_tuple(value, words)
}

/// An object whose keys keep the order given, as the Python builds its dicts.
pub fn object<const N: usize>(pairs: [(&str, Value); N]) -> Value {
    let mut map = Map::new();
    for (key, value) in pairs {
        map.insert(Str::new(key), value);
    }
    Value::Object(map)
}

/// `int(value)` as Python takes a number or a numeral (an int past i128 is held at its end): the error is the
/// exception's class.
pub fn python_int(value: &Value) -> Py<i128> {
    match value {
        Value::Bool(on) => Ok(i128::from(*on)),
        Value::Int(number) => Ok(number.to_string().parse::<i128>().unwrap_or_else(|_| {
            if number.to_string().starts_with('-') {
                i128::MIN
            } else {
                i128::MAX
            }
        })),
        Value::Float(x) if x.is_nan() => Err("ValueError"),
        Value::Float(x) if x.is_infinite() => Err("OverflowError"),
        Value::Float(x) => Ok(x.trunc() as i128),
        Value::Str(word) => {
            let parsed = car_machine::pytext::parse_int(word.as_str().ok_or("ValueError")?, 10)
                .ok_or("ValueError")?;
            let magnitude = parsed
                .magnitude
                .map_or(i128::MAX, |each| each.min(i128::MAX as u128) as i128);
            Ok(if parsed.negative {
                -magnitude
            } else {
                magnitude
            })
        }
        _ => Err("TypeError"),
    }
}
