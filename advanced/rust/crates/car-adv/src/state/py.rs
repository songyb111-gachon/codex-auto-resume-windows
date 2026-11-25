//! The reference's checks of a value, each named as the Python spells it, and the session's four checkers
//! (`_timestamp`, `_thread`, `_key`, `_word`).
//!
//! The store's methods take Python-model values (`car_machine::json::Value`) where the reference checks their type
//! itself - `type(x) is int`, `isinstance(x, str)`, a word of a closed list - so a wrong type is refused exactly as
//! there, with the same sentence.

use car_machine::domain::{ids, states};
use car_machine::json::{Int, Str, Value};

use super::errors::{Error, Result};

/// `type(value) is int`.
pub fn is_int(value: &Value) -> bool {
    matches!(value, Value::Int(_))
}

/// `isinstance(value, str)`.
pub fn is_str(value: &Value) -> bool {
    matches!(value, Value::Str(_))
}

/// `type(value) is bool`.
pub fn is_bool(value: &Value) -> bool {
    matches!(value, Value::Bool(_))
}

/// `isinstance(value, (int, float)) and not isinstance(value, bool)`.
pub fn is_number(value: &Value) -> bool {
    matches!(value, Value::Int(_) | Value::Float(_))
}

/// `type(value) in (int, float)`.
pub fn is_int_or_float(value: &Value) -> bool {
    is_number(value)
}

/// The text of a `str` without half a surrogate pair.
pub fn text(value: &Value) -> Option<&str> {
    match value {
        Value::Str(text) => text.as_str(),
        _ => None,
    }
}

/// `value in tuple(Enum)` for a StrEnum: only a `str` equal to a member's word is in it.
pub fn is_word<'a, W: Word<'a>>(value: &Value, words: &[W]) -> bool {
    text(value).is_some_and(|found| words.iter().any(|word| word.word() == found))
}

/// A closed word as the store compares it: a member of one of `crate::vocabulary`'s enums (the one source of the
/// edition's closed words), or a word a caller lists itself (an `Alternative`'s, a point's).
pub trait Word<'a> {
    fn word(&self) -> &'a str;
}

impl<'a, T: crate::vocabulary::ClosedWord> Word<'a> for T {
    fn word(&self) -> &'a str {
        crate::vocabulary::ClosedWord::word(*self)
    }
}

impl<'a> Word<'a> for &'a str {
    fn word(&self) -> &'a str {
        self
    }
}

/// An `int`'s value, where it fits 64 bits.
pub fn small(value: &Value) -> Option<i64> {
    match value {
        Value::Int(number) => number.as_i64(),
        _ => None,
    }
}

/// An `int` or a `float` as a number; an `int` past f64 is infinite, as `float(n)` would raise - callers that
/// need the exception check first.
pub fn as_f64(value: &Value) -> Option<f64> {
    car_store::value::number(value)
}

/// `str` of a word.
pub fn word(text: &str) -> Value {
    Value::Str(Str::new(text))
}

/// `int` of a number.
pub fn int(number: i64) -> Value {
    Value::Int(Int::from(number))
}

/// `str(value)` of a value Python would turn into text the way the store does (a word, a number).
pub fn py_str(value: &Value) -> String {
    car_machine::pytext::py_str(value)
}

/// `_timestamp(value, name)`: a time of the store's window (`machine.epoch(value, *machine.EPOCH_STORE)`) as a
/// float, or `StateError("invalid <name>")`. An `int` too large to be a float is the OverflowError
/// `math.isfinite` raises.
pub fn timestamp(value: &Value, name: &str) -> Result<f64> {
    let (low, high) = states::EPOCH_STORE;
    match states::epoch(value, low, high, false, true) {
        Err(class) => Err(Error::python(class, "int too large to convert to float")),
        Ok(false) => Err(Error::state(format!("invalid {name}"))),
        Ok(true) => Ok(as_f64(value).unwrap_or(0.0)),
    }
}

/// `_thread(value)`: a thread id in its canonical text, or `StateError("invalid thread id")`.
pub fn thread(value: &Value) -> Result<&str> {
    if ids::uuid_problem(value, false).is_some() {
        return Err(Error::state("invalid thread id"));
    }
    Ok(text(value).unwrap_or_default())
}

/// `_key(value, name)`: an interruption id, or a record id in the same shape - 64 lowercase hex digits.
pub fn key<'a>(value: &'a Value, name: &str) -> Result<&'a str> {
    if !ids::is_interruption_id(value, false) {
        return Err(Error::state(format!("invalid {name}")));
    }
    Ok(text(value).unwrap_or_default())
}

/// `_word(value, words, name)`: `value` if it is a member's word of the StrEnum `words`, else
/// `StateError("invalid <name>")`.
pub fn closed<'a, W: Word<'a>>(value: &Value, words: &[W], name: &str) -> Result<&'a str> {
    text(value)
        .and_then(|found| words.iter().map(Word::word).find(|word| *word == found))
        .ok_or_else(|| Error::state(format!("invalid {name}")))
}

/// `_word` where the value may be None and None is kept (`None if v is None else _word(v, ...)`).
pub fn closed_or_none<'a, W: Word<'a>>(
    value: &Value,
    words: &[W],
    name: &str,
) -> Result<Option<&'a str>> {
    if matches!(value, Value::Null) {
        return Ok(None);
    }
    closed(value, words, name).map(Some)
}

/// A word or `None` as a parameter.
pub fn word_or_null(found: Option<&str>) -> Value {
    found.map_or(Value::Null, word)
}

/// Python's `int(value)` of a number or a numeric text (`journal`'s and the lists' limits): a bool is 0 or 1, a
/// float is truncated toward zero, a text is read as `int()` reads it; anything else is TypeError, a bad text or a
/// NaN ValueError, an infinity OverflowError. An `int` of any size, as Python's.
pub fn int_of(value: &Value) -> Result<Value> {
    match value {
        Value::Bool(on) => Ok(int(i64::from(*on))),
        Value::Int(_) => Ok(value.clone()),
        Value::Float(number) if number.is_nan() => Err(Error::python(
            "ValueError",
            "cannot convert float NaN to integer",
        )),
        Value::Float(number) if number.is_infinite() => Err(Error::python(
            "OverflowError",
            "cannot convert float infinity to integer",
        )),
        Value::Float(number) => {
            Ok(Int::parse(&format!("{:.0}", number.trunc())).map_or(Value::Null, Value::Int))
        }
        Value::Str(text) => {
            let parsed = text
                .as_str()
                .and_then(|text| car_machine::pytext::parse_int(text, 10))
                .and_then(|parsed| {
                    parsed
                        .magnitude
                        .map(|magnitude| (parsed.negative, magnitude))
                });
            match parsed {
                Some((negative, magnitude)) => {
                    let digits = format!(
                        "{}{magnitude}",
                        if negative && magnitude != 0 { "-" } else { "" }
                    );
                    Ok(Int::parse(&digits).map_or(Value::Null, Value::Int))
                }
                None => Err(Error::python(
                    "ValueError",
                    "invalid literal for int() with base 10",
                )),
            }
        }
        _ => Err(Error::type_error(
            "int() argument must be a string, a bytes-like object or a real number",
        )),
    }
}

/// `max(low, min(value, high))` of an `int` of any size, as a small number.
pub fn clamp(value: &Value, low: i64, high: i64) -> i64 {
    match value {
        Value::Int(number) => match number.as_i64() {
            Some(found) => found.clamp(low, high),
            None if number.to_string().starts_with('-') => low,
            None => high,
        },
        _ => low,
    }
}

/// Python's `float(value)` of a number (`float(since)` in the reads): a bool 0.0 or 1.0, a numeric text parsed;
/// anything else TypeError.
pub fn float_of(value: &Value) -> Result<f64> {
    match value {
        Value::Bool(on) => Ok(f64::from(u8::from(*on))),
        Value::Int(_) | Value::Float(_) | Value::Str(_) => car_machine::pytext::to_float(value)
            .map_err(|class| Error::python(class, "could not convert to float")),
        _ => Err(Error::type_error(
            "float() argument must be a string or a real number",
        )),
    }
}

/// Python's `a // b` of two floats (CPython's `float_divmod`): not `(a / b).floor()`, which can round up to the next
/// whole number where the remainder is a hair below `b`.
pub fn floordiv(a: f64, b: f64) -> f64 {
    let mut remainder = a % b;
    let mut division = (a - remainder) / b;
    if remainder != 0.0 && ((b < 0.0) != (remainder < 0.0)) {
        remainder += b;
        division -= 1.0;
    }
    let _ = remainder;
    if division != 0.0 {
        let floor = division.floor();
        if division - floor > 0.5 {
            floor + 1.0
        } else {
            floor
        }
    } else {
        (0.0f64).copysign(a / b)
    }
}

/// `value + 1` of a number read from the file (a generation): an `int` stays one, a `float` one, anything else is
/// Python's TypeError.
pub fn plus_one(value: &Value) -> Result<Value> {
    match value {
        Value::Int(number) => match number.as_i64().and_then(|found| found.checked_add(1)) {
            Some(found) => Ok(int(found)),
            None => Ok(Int::parse(
                &(number.to_string().parse::<i128>().unwrap_or(0) + 1).to_string(),
            )
            .map_or(Value::Null, Value::Int)),
        },
        Value::Float(number) => Ok(Value::Float(number + 1.0)),
        Value::Bool(on) => Ok(int(i64::from(*on) + 1)),
        _ => Err(Error::type_error(
            "can only concatenate str (not \"int\") to str",
        )),
    }
}

/// A list value of words.
pub fn word_list<'a>(words: impl IntoIterator<Item = &'a str>) -> Value {
    Value::Array(words.into_iter().map(word).collect())
}

/// `[a, b]`: a tuple as JSON writes it.
pub fn pair(first: Value, second: Value) -> Value {
    Value::Array(vec![first, second])
}

/// `value[name]` of a value a caller handed in: a dict's item, KeyError where it has none, TypeError for a value
/// that is not a dict.
pub fn item(value: &Value, name: &str) -> Result<Value> {
    match value {
        Value::Object(map) => map
            .get(name)
            .cloned()
            .ok_or_else(|| Error::python("KeyError", format!("'{name}'"))),
        _ => Err(Error::type_error("object is not subscriptable by a word")),
    }
}

/// `value.get(name)` of a dict (None where it has none); AttributeError for a value that is not a dict.
pub fn get_item(value: &Value, name: &str) -> Result<Value> {
    match value {
        Value::Object(map) => Ok(map.get(name).cloned().unwrap_or(Value::Null)),
        _ => Err(Error::python(
            "AttributeError",
            "object has no attribute 'get'",
        )),
    }
}

/// `len(text)` of a `str`: its code points.
pub fn length(value: &Value) -> Option<usize> {
    match value {
        Value::Str(text) => Some(text.code_points().count()),
        _ => None,
    }
}

/// The right side of `now - value` as Python takes it: an `int`, a `float` or a `bool` (0 or 1); TypeError for
/// anything else.
pub fn minus_operand(value: &Value) -> Result<f64> {
    car_store::value::arithmetic(value)
        .ok_or_else(|| Error::type_error("unsupported operand type(s) for -"))
}

/// Every `Alternative`'s word, in its order (`tuple(Alternative)`).
pub fn alternatives() -> Vec<&'static str> {
    car_policy::plug::vocab_gen::domain_plugwords::Alternative::ALL
        .iter()
        .map(|each| each.as_str())
        .collect()
}
