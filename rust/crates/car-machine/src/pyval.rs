//! Python's rules over the values a JSON document holds: truth, hashing, the order of numbers, a dict's `.get`.
//!
//! The domain's functions take a record, a reading or a document as the Python does - a dict of anything - and
//! answer what Python answers, including the exception it would raise: an error here is the *name* of the
//! exception class (`"TypeError"`, `"OverflowError"`, `"AttributeError"`), which the differential harness
//! compares with the reference's `type(error).__name__`.

use std::cmp::Ordering;

use crate::json::{Int, Value};

/// A result whose error is the name of the Python exception class that would have been raised.
pub type Py<T> = Result<T, &'static str>;

static NULL: Value = Value::Null;

/// `bool(value)`.
pub fn truthy(value: &Value) -> bool {
    match value {
        Value::Null => false,
        Value::Bool(on) => *on,
        Value::Int(int) => int.as_i64() != Some(0),
        Value::Float(x) => *x != 0.0,
        Value::Str(text) => !text.is_empty(),
        Value::Array(items) => !items.is_empty(),
        Value::Object(map) => !map.is_empty(),
    }
}

/// `hash(value)` succeeds: a list and a dict are unhashable.
pub fn hashable(value: &Value) -> Py<()> {
    match value {
        Value::Array(_) | Value::Object(_) => Err("TypeError"),
        _ => Ok(()),
    }
}

/// `record.get(key)` of a dict (`None` where absent); anything else has no `.get`.
pub fn get<'a>(record: &'a Value, key: &str) -> Py<&'a Value> {
    match record {
        Value::Object(map) => Ok(map.get(key).unwrap_or(&NULL)),
        _ => Err("AttributeError"),
    }
}

/// The text of a `str`, `None` for any other value (or a text with a lone surrogate, which no vocabulary holds).
pub fn text(value: &Value) -> Option<&str> {
    match value {
        Value::Str(text) => text.as_str(),
        _ => None,
    }
}

/// `value == "text"`.
pub fn is(value: &Value, expected: &str) -> bool {
    text(value) == Some(expected)
}

/// `value in a_set_of_texts` for a frozenset or a dict's keys: an unhashable value raises.
pub fn in_set(value: &Value, members: &[&str]) -> Py<bool> {
    hashable(value)?;
    Ok(text(value).is_some_and(|word| members.contains(&word)))
}

/// `value in a_tuple_of_texts`: a tuple compares with `==` and hashes nothing.
pub fn in_tuple(value: &Value, members: &[&str]) -> bool {
    text(value).is_some_and(|word| members.contains(&word))
}

/// A number as Python orders it: `bool`, `int` and `float` are numbers, nothing else is.
#[derive(Clone, Copy, Debug)]
pub enum Num {
    Whole(i128),
    Huge(f64),
    Real(f64),
}

impl Num {
    pub fn of(value: &Value) -> Option<Num> {
        match value {
            Value::Bool(on) => Some(Num::Whole(i128::from(*on))),
            Value::Int(int) => Some(whole(int)),
            Value::Float(x) => Some(Num::Real(*x)),
            _ => None,
        }
    }

    pub fn as_f64(self) -> f64 {
        match self {
            Num::Whole(n) => n as f64,
            Num::Huge(x) | Num::Real(x) => x,
        }
    }
}

fn whole(int: &Int) -> Num {
    match int.to_string().parse::<i128>() {
        Ok(n) => Num::Whole(n),
        Err(_) => Num::Huge(int.to_string().parse().unwrap_or(f64::INFINITY)),
    }
}

/// `a ? b` for two numbers; `None` where a NaN is involved (every comparison is then false).
pub fn compare(a: Num, b: Num) -> Option<Ordering> {
    match (a, b) {
        (Num::Whole(x), Num::Whole(y)) => Some(x.cmp(&y)),
        // Python compares an int with a float exactly (`2**53 + 1 == float(2**53 + 1)` is False), never by
        // turning the int into a float.
        (Num::Whole(x), Num::Real(y)) => whole_with_real(x, y),
        (Num::Real(x), Num::Whole(y)) => whole_with_real(y, x).map(Ordering::reverse),
        _ => a.as_f64().partial_cmp(&b.as_f64()),
    }
}

/// An int and a float compared exactly, as CPython's `float_richcompare` does.
fn whole_with_real(x: i128, y: f64) -> Option<Ordering> {
    if y.is_nan() {
        return None;
    }
    // Every f64 at or past 2**127 in size is past every i128.
    const LIMIT: f64 = 170_141_183_460_469_231_731_687_303_715_884_105_728.0;
    if y >= LIMIT {
        return Some(Ordering::Less);
    }
    if y < -LIMIT {
        return Some(Ordering::Greater);
    }
    let whole = y.trunc();
    // `whole` is an integer of at most 127 bits, so the cast is exact.
    match x.cmp(&(whole as i128)) {
        Ordering::Equal => 0.0_f64.partial_cmp(&(y - whole)),
        other => Some(other),
    }
}

/// `a == b` of two values: numbers by value across `bool`, `int` and `float`, the rest by structure.
pub fn eq(a: &Value, b: &Value) -> bool {
    match (Num::of(a), Num::of(b)) {
        (Some(x), Some(y)) => compare(x, y) == Some(Ordering::Equal),
        (None, None) => match (a, b) {
            (Value::Array(x), Value::Array(y)) => {
                x.len() == y.len() && x.iter().zip(y).all(|(p, q)| eq(p, q))
            }
            (Value::Object(x), Value::Object(y)) => {
                x.len() == y.len()
                    && x.iter()
                        .all(|(key, item)| y.get(key).is_some_and(|other| eq(item, other)))
            }
            _ => a == b,
        },
        _ => false,
    }
}

/// `a < b`, `a <= b`, ... of two values: numbers by value, texts by code point, lists element by element; a
/// TypeError for any other pair.
pub fn order(a: &Value, b: &Value) -> Py<Option<Ordering>> {
    match (a, b) {
        (Value::Str(x), Value::Str(y)) => Ok(Some(x.cmp(y))),
        (Value::Array(x), Value::Array(y)) => {
            for (p, q) in x.iter().zip(y) {
                if !eq(p, q) {
                    return order(p, q);
                }
            }
            Ok(Some(x.len().cmp(&y.len())))
        }
        _ => match (Num::of(a), Num::of(b)) {
            (Some(x), Some(y)) => Ok(compare(x, y)),
            _ => Err("TypeError"),
        },
    }
}

pub fn less(a: &Value, b: &Value) -> Py<bool> {
    Ok(order(a, b)? == Some(Ordering::Less))
}

pub fn less_or_equal(a: &Value, b: &Value) -> Py<bool> {
    Ok(matches!(
        order(a, b)?,
        Some(Ordering::Less | Ordering::Equal)
    ))
}

pub fn greater(a: &Value, b: &Value) -> Py<bool> {
    Ok(order(a, b)? == Some(Ordering::Greater))
}

/// `max(*values)`: the first of the greatest, as Python keeps it.
pub fn max<'a>(values: &[&'a Value]) -> Py<&'a Value> {
    let mut best = values[0];
    for candidate in &values[1..] {
        if greater(candidate, best)? {
            best = candidate;
        }
    }
    Ok(best)
}

/// `a - b` of two numbers, as a float (every use here compares it).
pub fn minus(a: &Value, b: &Value) -> Py<f64> {
    match (Num::of(a), Num::of(b)) {
        (Some(Num::Whole(x)), Some(Num::Whole(y))) => Ok((x - y) as f64),
        (Some(x), Some(y)) => Ok(x.as_f64() - y.as_f64()),
        _ => Err("TypeError"),
    }
}

/// `type(value) is int` (a `bool` is not).
pub fn is_int(value: &Value) -> bool {
    matches!(value, Value::Int(_))
}

/// `isinstance(value, (int, float)) and type(value) is not bool`.
pub fn is_number(value: &Value) -> bool {
    matches!(value, Value::Int(_) | Value::Float(_))
}

/// `math.isfinite(value)` of an int or a float: an int past a float's reach raises OverflowError.
pub fn is_finite(value: &Value) -> Py<bool> {
    match value {
        Value::Float(x) => Ok(x.is_finite()),
        Value::Int(int) => match int.to_string().parse::<f64>() {
            Ok(x) if x.is_finite() => Ok(true),
            _ => Err("OverflowError"),
        },
        Value::Bool(_) => Ok(true),
        _ => Err("TypeError"),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::json::from_str;

    #[test]
    fn truth_and_order() {
        assert!(!truthy(&from_str("0.0").unwrap()));
        assert!(truthy(&from_str("[0]").unwrap()));
        let one = from_str("1").unwrap();
        let half = from_str("1.5").unwrap();
        assert!(less(&one, &half).unwrap());
        assert!(less(&one, &Value::Null).is_err());
        assert_eq!(max(&[&half, &one]).unwrap(), &half);
        let big = from_str("9007199254740993").unwrap();
        let near = from_str("9007199254740992.0").unwrap();
        assert!(!eq(&big, &near));
        assert!(greater(&big, &near).unwrap());
        assert!(less(&from_str("-1").unwrap(), &from_str("-0.5").unwrap()).unwrap());
    }
}
