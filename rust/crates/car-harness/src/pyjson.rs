//! An inline writer of Python's `json.dumps(value, ensure_ascii=False, allow_nan=False)` bytes.
//!
//! TO BE REPLACED by S0.2's Python-compatible JSON writer in car-machine (PLAN 5.3) once that crate is
//! merged: this one covers only what the harness's proof writes (no lone surrogates, i64 integers) and
//! has no property test behind it. D12: the wire is byte for byte, so nothing here may round a value.

use std::fmt::Write as _;

/// A JSON value in the order the code built it (Python's dict keeps insertion order).
#[derive(Clone, Debug, PartialEq)]
pub enum Value {
    Null,
    Bool(bool),
    Int(i64),
    Float(f64),
    Str(String),
    List(Vec<Value>),
    Object(Vec<(String, Value)>),
}

/// What `allow_nan=False` refuses.
#[derive(Debug, PartialEq)]
pub struct Unwritable;

/// `json.dumps(value, ensure_ascii=False, allow_nan=False)`: separators ", " and ": ", one line.
pub fn dumps(value: &Value) -> Result<String, Unwritable> {
    let mut out = String::new();
    write_value(&mut out, value, None, 0, false)?;
    Ok(out)
}

/// `json.dumps(value, indent=indent, sort_keys=sort_keys, ensure_ascii=False, allow_nan=False)`.
pub fn dumps_indented(value: &Value, indent: usize, sort_keys: bool) -> Result<String, Unwritable> {
    let mut out = String::new();
    write_value(&mut out, value, Some(indent), 0, sort_keys)?;
    Ok(out)
}

fn write_value(
    out: &mut String,
    value: &Value,
    indent: Option<usize>,
    level: usize,
    sort: bool,
) -> Result<(), Unwritable> {
    match value {
        Value::Null => out.push_str("null"),
        Value::Bool(true) => out.push_str("true"),
        Value::Bool(false) => out.push_str("false"),
        Value::Int(number) => {
            let _ = write!(out, "{number}");
        }
        Value::Float(number) => out.push_str(&float_repr(*number)?),
        Value::Str(text) => write_string(out, text),
        Value::List(items) => {
            if items.is_empty() {
                out.push_str("[]");
                return Ok(());
            }
            out.push('[');
            for (index, item) in items.iter().enumerate() {
                separator(out, indent, level + 1, index == 0);
                write_value(out, item, indent, level + 1, sort)?;
            }
            closing(out, indent, level);
            out.push(']');
        }
        Value::Object(pairs) => {
            if pairs.is_empty() {
                out.push_str("{}");
                return Ok(());
            }
            let mut ordered: Vec<&(String, Value)> = pairs.iter().collect();
            if sort {
                // Python sorts str keys by code point; UTF-8 byte order is the same order.
                ordered.sort_by(|a, b| a.0.cmp(&b.0));
            }
            out.push('{');
            for (index, (key, item)) in ordered.into_iter().enumerate() {
                separator(out, indent, level + 1, index == 0);
                write_string(out, key);
                out.push_str(": ");
                write_value(out, item, indent, level + 1, sort)?;
            }
            closing(out, indent, level);
            out.push('}');
        }
    }
    Ok(())
}

fn separator(out: &mut String, indent: Option<usize>, level: usize, first: bool) {
    match indent {
        // With an indent Python's item separator is "," (no trailing space) and every item on its own line.
        Some(width) => {
            if !first {
                out.push(',');
            }
            out.push('\n');
            out.push_str(&" ".repeat(width * level));
        }
        None => {
            if !first {
                out.push_str(", ");
            }
        }
    }
}

fn closing(out: &mut String, indent: Option<usize>, level: usize) {
    if let Some(width) = indent {
        out.push('\n');
        out.push_str(&" ".repeat(width * level));
    }
}

/// `json.encoder.py_encode_basestring`: only `"`, `\` and the C0 controls are escaped.
fn write_string(out: &mut String, text: &str) {
    out.push('"');
    for character in text.chars() {
        match character {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            '\u{08}' => out.push_str("\\b"),
            '\u{0c}' => out.push_str("\\f"),
            c if (c as u32) < 0x20 => {
                let _ = write!(out, "\\u{:04x}", c as u32);
            }
            c => out.push(c),
        }
    }
    out.push('"');
}

/// `float.__repr__`: the shortest digits that round-trip, laid out the way Python lays them out
/// (exponent form when the decimal point falls before the 4th leading zero or past 16 digits).
pub fn float_repr(number: f64) -> Result<String, Unwritable> {
    if !number.is_finite() {
        return Err(Unwritable);
    }
    if number == 0.0 {
        return Ok(if number.is_sign_negative() {
            "-0.0"
        } else {
            "0.0"
        }
        .to_string());
    }
    // Rust's `{:e}` writes the shortest round-trip digits as d[.ddd]e<exp>.
    let scientific = format!("{:e}", number.abs());
    let (mantissa, exponent) = scientific
        .split_once('e')
        .expect("LowerExp always writes an exponent");
    let exponent: i32 = exponent
        .parse()
        .expect("LowerExp writes an integer exponent");
    let digits: String = mantissa.chars().filter(|c| *c != '.').collect();
    let count = digits.len() as i32;
    let point = exponent + 1; // where the decimal point falls after the digits' start
    let sign = if number.is_sign_negative() { "-" } else { "" };
    let body = if point <= -4 || point > 16 {
        let mut text = digits[..1].to_string();
        if count > 1 {
            text.push('.');
            text.push_str(&digits[1..]);
        }
        let _ = write!(
            text,
            "e{}{:02}",
            if exponent < 0 { '-' } else { '+' },
            exponent.abs()
        );
        text
    } else if point <= 0 {
        format!("0.{}{}", "0".repeat((-point) as usize), digits)
    } else if point >= count {
        format!("{}{}.0", digits, "0".repeat((point - count) as usize))
    } else {
        format!(
            "{}.{}",
            &digits[..point as usize],
            &digits[point as usize..]
        )
    };
    Ok(format!("{sign}{body}"))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn floats_as_python_writes_them() {
        // repr() of each, from CPython 3.13.
        for (number, text) in [
            (6.0, "6.0"),
            (0.5, "0.5"),
            (1e-05, "1e-05"),
            (0.0001, "0.0001"),
            (1e16, "1e+16"),
            (1e15, "1000000000000000.0"),
            (123.456, "123.456"),
            (-2.5e-7, "-2.5e-07"),
            (1.7976931348623157e308, "1.7976931348623157e+308"),
            (0.1, "0.1"),
            (-0.0, "-0.0"),
        ] {
            assert_eq!(float_repr(number).unwrap(), text, "{number}");
        }
        assert_eq!(float_repr(f64::NAN), Err(Unwritable));
    }

    #[test]
    fn strings_and_separators() {
        let value = Value::Object(vec![
            ("a".into(), Value::Str("é\"\\\n\u{01}".into())),
            (
                "b".into(),
                Value::List(vec![Value::Int(1), Value::Null, Value::Bool(true)]),
            ),
            ("c".into(), Value::List(vec![])),
        ]);
        assert_eq!(
            dumps(&value).unwrap(),
            "{\"a\": \"é\\\"\\\\\\n\\u0001\", \"b\": [1, null, true], \"c\": []}"
        );
        assert_eq!(
            dumps_indented(&value, 2, true).unwrap(),
            "{\n  \"a\": \"é\\\"\\\\\\n\\u0001\",\n  \"b\": [\n    1,\n    null,\n    true\n  ],\n  \"c\": []\n}"
        );
    }
}
