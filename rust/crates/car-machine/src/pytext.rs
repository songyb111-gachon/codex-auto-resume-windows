//! What Python's text and number readers say, which Rust's do not say alike (D12).
//!
//! `str.isspace`, `str.strip`, the decimal digits `int()` and a regex class for a digit take, `int(text, 16)`,
//! `float(text)`, `float.hex()`: ported from CPython 3.13, over the tables `tests/rustdiff/gen_tables.py` makes
//! from the reference interpreter's own Unicode database. Pure and platform-independent.

use crate::json::{Int, Options, Value, to_string};
use crate::pytext_tables::{DECIMAL_ZEROS, SPACE};

/// `str.isspace()` of one character.
pub fn is_space(c: char) -> bool {
    let point = c as u32;
    SPACE
        .binary_search_by(|&(low, high)| {
            if point < low {
                std::cmp::Ordering::Greater
            } else if point > high {
                std::cmp::Ordering::Less
            } else {
                std::cmp::Ordering::Equal
            }
        })
        .is_ok()
}

/// `str.strip()` with no argument.
pub fn strip(text: &str) -> &str {
    text.trim_matches(is_space)
}

/// The value of a decimal digit of any script (`unicodedata.decimal(c, None)`).
pub fn decimal_value(c: char) -> Option<u32> {
    let point = c as u32;
    if point < 0x80 {
        return c.to_digit(10);
    }
    let at = DECIMAL_ZEROS.partition_point(|&zero| zero <= point);
    let zero = *DECIMAL_ZEROS.get(at.checked_sub(1)?)?;
    (point - zero < 10).then(|| point - zero)
}

/// Whether `c` is what a regex `\d` matches in a `str` pattern: a decimal digit of any script.
pub fn is_digit(c: char) -> bool {
    decimal_value(c).is_some()
}

/// An integer as `int(text, base)` reads it: its sign and its magnitude, `None` when that is past 128 bits.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Parsed {
    pub negative: bool,
    pub magnitude: Option<u128>,
}

/// `int(text, base)` for base 10 or 16, as CPython reads a `str`: Unicode white space and decimal digits first
/// turned into ASCII's, then a sign, a `0x` for base 16, digits with single underscores between them, and
/// white space; anything else is a ValueError (`None`).
pub fn parse_int(text: &str, base: u32) -> Option<Parsed> {
    let chars: Vec<char> = text
        .chars()
        .map(|c| {
            if is_space(c) {
                ' '
            } else if let Some(value) = decimal_value(c) {
                char::from_digit(value, 10).unwrap_or('?')
            } else if c.is_ascii() {
                c
            } else {
                '?'
            }
        })
        .collect();
    let mut at = 0;
    while chars.get(at) == Some(&' ') {
        at += 1;
    }
    let mut negative = false;
    match chars.get(at) {
        Some('-') => {
            negative = true;
            at += 1;
        }
        Some('+') => at += 1,
        _ => {}
    }
    if base == 16 && chars.get(at) == Some(&'0') && matches!(chars.get(at + 1), Some('x' | 'X')) {
        at += 2;
        if chars.get(at) == Some(&'_') {
            at += 1;
        }
    }
    if chars.get(at) == Some(&'_') {
        return None;
    }
    let mut digits = 0;
    let mut previous = ' ';
    let mut magnitude = Some(0u128);
    while let Some(&c) = chars.get(at) {
        if c == '_' {
            if previous == '_' {
                return None;
            }
        } else if let Some(value) = c.to_digit(base) {
            digits += 1;
            magnitude = magnitude
                .and_then(|so_far| so_far.checked_mul(base as u128))
                .and_then(|so_far| so_far.checked_add(value as u128));
        } else {
            break;
        }
        previous = c;
        at += 1;
    }
    if digits == 0 || previous == '_' {
        return None;
    }
    while chars.get(at) == Some(&' ') {
        at += 1;
    }
    (at == chars.len()).then_some(Parsed {
        negative,
        magnitude,
    })
}

/// `repr(x)` of a float (shortest text that reads back), `inf` and `nan` as Python spells them.
pub fn float_repr(x: f64) -> String {
    if x.is_nan() {
        "nan".into()
    } else if x.is_infinite() {
        if x < 0.0 { "-inf" } else { "inf" }.into()
    } else {
        to_string(&Value::Float(x), &Options::new()).expect("a finite float is written")
    }
}

/// `float.hex(x)`.
pub fn float_hex(x: f64) -> String {
    if x.is_nan() {
        return "nan".into();
    }
    if x.is_infinite() {
        return if x < 0.0 { "-inf" } else { "inf" }.into();
    }
    let bits = x.to_bits();
    let sign = if bits >> 63 == 1 { "-" } else { "" };
    let exponent = ((bits >> 52) & 0x7ff) as i64;
    let fraction = bits & ((1u64 << 52) - 1);
    if exponent == 0 && fraction == 0 {
        return format!("{sign}0x0.0p+0");
    }
    let (lead, unbiased) = if exponent == 0 {
        (0, -1022)
    } else {
        (1, exponent - 1023)
    };
    let direction = if unbiased < 0 { '-' } else { '+' };
    format!(
        "{sign}0x{lead}.{fraction:013x}p{direction}{}",
        unbiased.abs()
    )
}

/// What `float(value)` does with a Python value: the number, or the exception's name.
pub fn to_float(value: &Value) -> Result<f64, &'static str> {
    match value {
        Value::Bool(on) => Ok(if *on { 1.0 } else { 0.0 }),
        Value::Float(x) => Ok(*x),
        Value::Int(int) => int_to_float(int),
        Value::Str(text) => match text.as_str() {
            Some(text) => float_from_text(text),
            None => Err("ValueError"),
        },
        _ => Err("TypeError"),
    }
}

fn int_to_float(int: &Int) -> Result<f64, &'static str> {
    let x: f64 = int.to_string().parse().map_err(|_| "ValueError")?;
    if x.is_infinite() {
        Err("OverflowError")
    } else {
        Ok(x)
    }
}

/// `float(text)` for a `str`.
pub fn float_from_text(text: &str) -> Result<f64, &'static str> {
    let ascii: String = strip(text)
        .chars()
        .map(|c| match decimal_value(c) {
            Some(value) if !c.is_ascii() => char::from_digit(value, 10).unwrap_or('?'),
            _ => c,
        })
        .collect();
    let (negative, body) = match ascii.strip_prefix('-') {
        Some(rest) => (true, rest),
        None => (false, ascii.strip_prefix('+').unwrap_or(&ascii)),
    };
    let lowered = body.to_ascii_lowercase();
    let special = match lowered.as_str() {
        "inf" | "infinity" => Some(f64::INFINITY),
        "nan" => Some(f64::NAN),
        _ => None,
    };
    if let Some(x) = special {
        return Ok(if negative { -x } else { x });
    }
    let bytes = body.as_bytes();
    let mut clean = String::new();
    for (at, &byte) in bytes.iter().enumerate() {
        if byte == b'_' {
            let before = at.checked_sub(1).map(|i| bytes[i]);
            let after = bytes.get(at + 1).copied();
            if !(before.is_some_and(|b| b.is_ascii_digit())
                && after.is_some_and(|b| b.is_ascii_digit()))
            {
                return Err("ValueError");
            }
            continue;
        }
        clean.push(byte as char);
    }
    let chars: Vec<char> = clean.chars().collect();
    let mut at = 0;
    let mut mantissa_digits = 0;
    let mut seen_point = false;
    while at < chars.len() {
        match chars[at] {
            '0'..='9' => mantissa_digits += 1,
            '.' if !seen_point => seen_point = true,
            _ => break,
        }
        at += 1;
    }
    let mut ok = mantissa_digits > 0;
    if ok && at < chars.len() {
        ok = matches!(chars[at], 'e' | 'E');
        if ok {
            at += 1;
            if matches!(chars.get(at), Some('+' | '-')) {
                at += 1;
            }
            let start = at;
            while chars.get(at).is_some_and(char::is_ascii_digit) {
                at += 1;
            }
            ok = at > start && at == chars.len();
        }
    }
    if !ok {
        return Err("ValueError");
    }
    let x: f64 = clean.parse().map_err(|_| "ValueError")?;
    Ok(if negative { -x } else { x })
}

/// `str(value)` for a scalar a JSON document holds; a list or a dict has no use here (see its callers).
pub fn py_str(value: &Value) -> String {
    match value {
        Value::Null => "None".into(),
        Value::Bool(true) => "True".into(),
        Value::Bool(false) => "False".into(),
        Value::Int(int) => int.to_string(),
        Value::Float(x) => float_repr(*x),
        Value::Str(text) => String::from_utf8_lossy(text.as_bytes()).into_owned(),
        Value::Array(_) | Value::Object(_) => String::new(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn parsed(text: &str) -> Option<(bool, Option<u128>)> {
        parse_int(text, 16).map(|p| (p.negative, p.magnitude))
    }

    #[test]
    fn int_sixteen_as_cpython_reads_it() {
        assert_eq!(parsed("ff"), Some((false, Some(255))));
        assert_eq!(parsed(" 0xFF "), Some((false, Some(255))));
        assert_eq!(parsed("0x_f_f"), Some((false, Some(255))));
        assert_eq!(parsed("-0"), Some((true, Some(0))));
        assert_eq!(parsed("f__f"), None);
        assert_eq!(parsed("_ff"), None);
        assert_eq!(parsed("ff_"), None);
        assert_eq!(parsed("0x"), None);
        assert_eq!(parsed(""), None);
        assert_eq!(parsed("\u{660}\u{661}"), Some((false, Some(1))));
    }

    #[test]
    fn float_hex_and_repr() {
        assert_eq!(float_hex(1.0), "0x1.0000000000000p+0");
        assert_eq!(float_hex(0.0), "0x0.0p+0");
        assert_eq!(float_hex(-0.0), "-0x0.0p+0");
        assert_eq!(float_hex(5e-324), "0x0.0000000000001p-1022");
        assert_eq!(float_hex(1710.5), "0x1.aba0000000000p+10");
        assert_eq!(float_repr(1e16), "1e+16");
    }

    #[test]
    fn spaces() {
        assert!(is_space('\u{1c}'));
        assert!(!is_space('a'));
        assert_eq!(strip("\u{a0} a \u{3000}"), "a");
    }
}
