//! The reader: serde_json (D5), turned into Python's values as `json.loads` gives them.
//!
//! Where serde_json and `json.loads` part (neither the wire nor the goldens reach these):
//! serde_json refuses a lone surrogate escape (`"\ud800"`), the literals `NaN`, `Infinity`
//! and `-Infinity`, and nesting past 128; `json.loads` takes all three. Numbers are read as
//! Python reads them: an integer literal as an `int` of any size (`-0` as 0), anything with
//! a fraction or an exponent as the nearest float (`1e400` as infinity).

use std::fmt;

use super::value::{Int, Map, Str, Value};
use super::write::MAX_INT_DIGITS;

/// Why a text could not be read.
#[derive(Debug)]
pub enum ReadError {
    /// Not JSON, as serde_json reads it.
    Syntax(serde_json::Error),
    /// An integer literal past Python's digit limit, which `json.loads` refuses (ValueError).
    IntTooLong { digits: usize },
}

impl fmt::Display for ReadError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            ReadError::Syntax(error) => write!(formatter, "{error}"),
            ReadError::IntTooLong { digits } => write!(
                formatter,
                "Exceeds the limit ({MAX_INT_DIGITS} digits) for integer string conversion: value has {digits} digits"
            ),
        }
    }
}

impl std::error::Error for ReadError {}

/// `json.loads(text)`.
pub fn from_str(text: &str) -> Result<Value, ReadError> {
    let parsed: serde_json::Value = serde_json::from_str(text).map_err(ReadError::Syntax)?;
    convert(parsed)
}

/// `json.loads(bytes)` for UTF-8 bytes.
pub fn from_slice(bytes: &[u8]) -> Result<Value, ReadError> {
    let parsed: serde_json::Value = serde_json::from_slice(bytes).map_err(ReadError::Syntax)?;
    convert(parsed)
}

fn convert(value: serde_json::Value) -> Result<Value, ReadError> {
    Ok(match value {
        serde_json::Value::Null => Value::Null,
        serde_json::Value::Bool(on) => Value::Bool(on),
        serde_json::Value::Number(number) => number_of(number.as_str())?,
        serde_json::Value::String(text) => Value::Str(Str::from(text)),
        serde_json::Value::Array(items) => {
            Value::Array(items.into_iter().map(convert).collect::<Result<_, _>>()?)
        }
        serde_json::Value::Object(entries) => {
            let mut map = Map::with_capacity(entries.len());
            for (key, item) in entries {
                map.insert(Str::from(key), convert(item)?);
            }
            Value::Object(map)
        }
    })
}

/// A number as written (serde_json's `arbitrary_precision` keeps the literal).
fn number_of(literal: &str) -> Result<Value, ReadError> {
    if literal.contains(['.', 'e', 'E']) {
        // Rust's parse rounds to nearest as Python's float() does, and overflows to infinity.
        let x: f64 = literal
            .parse()
            .expect("serde_json gives only valid number literals");
        return Ok(Value::Float(x));
    }
    let digits = literal.trim_start_matches('-').len();
    if digits > MAX_INT_DIGITS {
        return Err(ReadError::IntTooLong { digits });
    }
    Ok(Value::Int(
        Int::parse(literal).expect("serde_json gives only valid integer literals"),
    ))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn numbers_as_python_reads_them() {
        assert_eq!(from_str("-0").unwrap(), Value::Int(0.into()));
        assert_eq!(from_str("1e400").unwrap(), Value::Float(f64::INFINITY));
        assert_eq!(from_str("1E400").unwrap(), Value::Float(f64::INFINITY));
        assert_eq!(from_str("-0.0").unwrap(), Value::Float(-0.0));
        assert_eq!(from_str("1.0").unwrap(), Value::Float(1.0));
        assert_eq!(
            from_str("18446744073709551615").unwrap(),
            Value::Int(u64::MAX.into())
        );
        let big = "123456789012345678901234567890";
        assert_eq!(from_str(big).unwrap(), Value::Int(Int::parse(big).unwrap()));
        assert!(from_str(&"9".repeat(4300)).is_ok());
        assert!(matches!(
            from_str(&"9".repeat(4301)),
            Err(ReadError::IntTooLong { digits: 4301 })
        ));
    }

    #[test]
    fn keys_keep_their_order_and_a_repeated_key_its_first_place() {
        let value = from_str(r#"{"b": 1, "a": 2, "b": 3}"#).unwrap();
        let Value::Object(map) = value else {
            panic!("an object")
        };
        let keys: Vec<_> = map.keys().map(|key| key.as_str().unwrap()).collect();
        assert_eq!(keys, ["b", "a"]);
        assert_eq!(map.get("b"), Some(&Value::Int(3.into())));
    }
}
