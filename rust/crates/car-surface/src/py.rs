//! What the surfaces' Python does with a value of any type, where car-machine's `pyval` and `pytext` stop: `str()` of a
//! list or a dict, `list()` and `dict()` of anything, `in`, unpacking a pair, `int()` without a bound, and `sorted`.
//!
//! Every function answers what the reference answers, the error being the name of the exception class it raises.

use std::cmp::Ordering;

use car_machine::json::{Int, Map, Str, Value};
use car_machine::pytext::{self, float_repr};
use car_machine::pyval::{self, Py};

/// A Python `str` as Rust text: a lone surrogate (which no caller of the surfaces hands over) as U+FFFD.
pub fn text_of(text: &Str) -> String {
    String::from_utf8_lossy(text.as_bytes()).into_owned()
}

/// `str(value)`.
pub fn str_of(value: &Value) -> String {
    match value {
        Value::Str(text) => text_of(text),
        Value::Array(_) | Value::Object(_) => repr(value),
        other => pytext::py_str(other),
    }
}

/// `repr(value)` of what a JSON document holds (a dict and a list as Python writes them).
pub fn repr(value: &Value) -> String {
    match value {
        Value::Null => "None".into(),
        Value::Bool(true) => "True".into(),
        Value::Bool(false) => "False".into(),
        Value::Int(int) => int.to_string(),
        Value::Float(x) => float_repr(*x),
        Value::Str(text) => repr_str(text),
        Value::Array(items) => {
            let parts: Vec<String> = items.iter().map(repr).collect();
            format!("[{}]", parts.join(", "))
        }
        Value::Object(map) => {
            let parts: Vec<String> = map
                .iter()
                .map(|(key, item)| format!("{}: {}", repr_str(key), repr(item)))
                .collect();
            format!("{{{}}}", parts.join(", "))
        }
    }
}

/// Whether `str.isprintable()` is false of a code point, for the ones repr escapes. ASCII and the C1 controls, the
/// separators and the format characters a text is likely to hold are exact; the rest of Unicode is taken as printable
/// (recorded in AUDIT-v0628: only a list or a dict given where an id belongs is ever written this way).
fn unprintable(point: u32) -> bool {
    matches!(point,
        0..=0x1F | 0x7F..=0xA0 | 0xAD | 0x600..=0x605 | 0x61C | 0x6DD | 0x70F | 0x180E | 0x1680
        | 0x2000..=0x200F | 0x2028..=0x202F | 0x205F..=0x2064 | 0x2066..=0x206F | 0x3000 | 0xD800..=0xDFFF
        | 0xE000..=0xF8FF | 0xFEFF | 0xFFF9..=0xFFFB | 0xFFFE | 0xFFFF | 0xF0000..)
}

fn repr_str(text: &Str) -> String {
    let points: Vec<u32> = text.code_points().collect();
    let has_single = points.contains(&u32::from(b'\''));
    let has_double = points.contains(&u32::from(b'"'));
    let quote = if has_single && !has_double { '"' } else { '\'' };
    let mut out = String::new();
    out.push(quote);
    for point in points {
        match point {
            0x5C => out.push_str("\\\\"),
            0x09 => out.push_str("\\t"),
            0x0A => out.push_str("\\n"),
            0x0D => out.push_str("\\r"),
            _ if point == u32::from(quote) => {
                out.push('\\');
                out.push(quote);
            }
            _ if point == 0x20 => out.push(' '),
            _ if unprintable(point) => {
                if point < 0x100 {
                    out.push_str(&format!("\\x{point:02x}"));
                } else if point < 0x10000 {
                    out.push_str(&format!("\\u{point:04x}"));
                } else {
                    out.push_str(&format!("\\U{point:08x}"));
                }
            }
            _ => out.push(char::from_u32(point).unwrap_or('\u{fffd}')),
        }
    }
    out.push(quote);
    out
}

/// `iter(value)` as a list: a list's items, a text's characters, a dict's keys; anything else is not iterable.
pub fn items(value: &Value) -> Py<Vec<Value>> {
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

/// `a, b = value`: the two items of anything iterable of exactly two.
pub fn pair(value: &Value) -> Py<(Value, Value)> {
    let found = items(value)?;
    if found.len() != 2 {
        return Err("ValueError");
    }
    let mut each = found.into_iter();
    let first = each.next().unwrap_or(Value::Null);
    let second = each.next().unwrap_or(Value::Null);
    Ok((first, second))
}

/// `dict(value)`: a dict as it is, or a dict of the pairs an iterable gives.
pub fn dict(value: &Value) -> Py<Map> {
    match value {
        Value::Object(map) => Ok(map.clone()),
        Value::Array(_) | Value::Str(_) => {
            let mut made = Map::new();
            for entry in items(value)? {
                let parts = items(&entry)?;
                if parts.len() != 2 {
                    return Err("ValueError");
                }
                let key = match &parts[0] {
                    Value::Str(key) => key.clone(),
                    Value::Array(_) | Value::Object(_) => return Err("TypeError"),
                    // A dict of a JSON document is keyed by texts; a key of another kind is not one this port keeps.
                    other => Str::from(str_of(other)),
                };
                made.insert(key, parts[1].clone());
            }
            Ok(made)
        }
        _ => Err("TypeError"),
    }
}

/// `needle in container`, for a text needle: a substring of a text, an item of a list, a key of a dict.
pub fn contains(container: &Value, needle: &str) -> Py<bool> {
    match container {
        Value::Str(text) => Ok(text_of(text).contains(needle)),
        Value::Array(found) => Ok(found.iter().any(|item| pyval::is(item, needle))),
        Value::Object(map) => Ok(map.contains_key(needle)),
        _ => Err("TypeError"),
    }
}

/// `set(value)` of texts: what `value` holds, a TypeError for anything unhashable in it.
pub fn text_set(value: &Value) -> Py<Vec<Value>> {
    let found = items(value)?;
    for item in &found {
        pyval::hashable(item)?;
    }
    Ok(found)
}

/// Whether `set(value)` shares a member with `members` (`members & set(value)`).
pub fn meets(value: &Value, members: &[&str]) -> Py<bool> {
    Ok(text_set(value)?
        .iter()
        .any(|item| pyval::text(item).is_some_and(|word| members.contains(&word))))
}

/// `value or fallback`.
pub fn or<'a>(value: &'a Value, fallback: &'a Value) -> &'a Value {
    if pyval::truthy(value) {
        value
    } else {
        fallback
    }
}

/// `a == b` with a text.
pub fn eq_text(value: &Value, text: &str) -> bool {
    pyval::is(value, text)
}

/// `dict.get(key)` of a dict that must be one: `{}` stands in for a falsy value (`value or {}`), and anything else
/// truthy has no `.get`.
pub fn get_or_empty<'a>(value: &'a Value, key: &str) -> Py<&'a Value> {
    static NULL: Value = Value::Null;
    if !pyval::truthy(value) {
        return Ok(&NULL);
    }
    pyval::get(value, key)
}

// ------------------------------------------------------------------- int() without a bound
/// A Python int, as its sign and its decimal digits (no leading zeros; "0" for zero).
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Whole {
    pub negative: bool,
    pub digits: String,
}

impl Whole {
    pub fn from_i64(value: i64) -> Whole {
        Whole {
            negative: value < 0,
            digits: value.unsigned_abs().to_string(),
        }
    }

    fn of_text(text: String) -> Whole {
        let (negative, digits) = match text.strip_prefix('-') {
            Some(rest) => (true, rest.to_owned()),
            None => (false, text),
        };
        let digits = digits.trim_start_matches('0');
        if digits.is_empty() {
            Whole {
                negative: false,
                digits: "0".into(),
            }
        } else {
            Whole {
                negative,
                digits: digits.into(),
            }
        }
    }

    /// `int(value)`: a bool or an int as it is, a float truncated toward zero (NaN a ValueError, an infinity an
    /// OverflowError), a text as `int(text)` reads one; anything else a TypeError.
    pub fn of(value: &Value) -> Py<Whole> {
        match value {
            Value::Bool(on) => Ok(Whole::from_i64(i64::from(*on))),
            Value::Int(int) => Ok(Whole::of_text(int.to_string())),
            Value::Float(x) => {
                if x.is_nan() {
                    return Err("ValueError");
                }
                if x.is_infinite() {
                    return Err("OverflowError");
                }
                let text = format!("{:.0}", x.trunc().abs());
                let mut whole = Whole::of_text(text);
                whole.negative = whole.digits != "0" && *x < 0.0;
                Ok(whole)
            }
            Value::Str(text) => {
                let text = text.as_str().ok_or("ValueError")?;
                pytext::parse_int(text, 10).ok_or("ValueError")?;
                let digits: String = text
                    .chars()
                    .filter_map(|c| pytext::decimal_value(c).and_then(|d| char::from_digit(d, 10)))
                    .collect();
                if digits.len() > 4300 {
                    return Err("ValueError");
                }
                let mut whole = Whole::of_text(digits);
                whole.negative = whole.digits != "0" && pytext::strip(text).starts_with('-');
                Ok(whole)
            }
            _ => Err("TypeError"),
        }
    }

    pub fn is_zero(&self) -> bool {
        self.digits == "0"
    }

    pub fn is_positive(&self) -> bool {
        !self.negative && !self.is_zero()
    }

    pub fn small(&self) -> Option<i64> {
        let magnitude: i64 = self.digits.parse().ok()?;
        Some(if self.negative { -magnitude } else { magnitude })
    }

    /// `divmod(self, by)` of a non-negative int by a small positive one.
    pub fn divmod(&self, by: u64) -> (Whole, u64) {
        let mut quotient = String::with_capacity(self.digits.len());
        let mut rest: u128 = 0;
        for digit in self.digits.bytes() {
            rest = rest * 10 + u128::from(digit - b'0');
            let place = rest / u128::from(by);
            rest %= u128::from(by);
            if !(quotient.is_empty() && place == 0) {
                quotient.push(char::from(b'0' + place as u8));
            }
        }
        if quotient.is_empty() {
            quotient.push('0');
        }
        (
            Whole {
                negative: false,
                digits: quotient,
            },
            rest as u64,
        )
    }

    /// Ordering against a small int.
    pub fn cmp_small(&self, other: i64) -> Ordering {
        match self.small() {
            Some(value) => value.cmp(&other),
            None if self.negative => Ordering::Less,
            None => Ordering::Greater,
        }
    }
}

impl std::fmt::Display for Whole {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        if self.negative {
            formatter.write_str("-")?;
        }
        formatter.write_str(&self.digits)
    }
}

/// An int of a JSON document as a `Whole`.
pub fn whole_of_int(int: &Int) -> Whole {
    Whole::of_text(int.to_string())
}

// ------------------------------------------------------------------------------- sorted
/// `sorted(items, key=...)`: stable, comparing keys with `<` only, as CPython's sort does; a comparison that raises
/// stops it with that exception. Binary insertion, which is CPython's own sort for the lengths a popup lists.
pub fn sorted_by<T: Clone>(found: &[T], less: &dyn Fn(&T, &T) -> Py<bool>) -> Py<Vec<T>> {
    let mut out: Vec<T> = Vec::with_capacity(found.len());
    for item in found {
        // The first place whose element is greater than `item` (bisect_right), so equal ones keep their order.
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
pub fn tuple_less(a: &[Value], b: &[Value]) -> Py<bool> {
    for (p, q) in a.iter().zip(b) {
        if !pyval::eq(p, q) {
            return pyval::less(p, q);
        }
    }
    Ok(a.len() < b.len())
}

/// `min(values)`: the first of the smallest.
pub fn min_of<'a>(values: &[&'a Value]) -> Py<&'a Value> {
    let mut best = *values.first().ok_or("ValueError")?;
    for candidate in &values[1..] {
        if pyval::less(candidate, best)? {
            best = candidate;
        }
    }
    Ok(best)
}

/// A `Map` from pairs, in order.
pub fn object<const N: usize>(pairs: [(&str, Value); N]) -> Value {
    let mut map = Map::new();
    for (key, value) in pairs {
        map.insert(Str::from(key), value);
    }
    Value::Object(map)
}

/// A list of texts.
pub fn strings<S: AsRef<str>>(found: impl IntoIterator<Item = S>) -> Value {
    Value::Array(
        found
            .into_iter()
            .map(|each| Value::from(each.as_ref()))
            .collect(),
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    use car_machine::json::from_str;

    #[test]
    fn reprs() {
        assert_eq!(
            str_of(&from_str("[1, \"a\", null]").unwrap()),
            "[1, 'a', None]"
        );
        assert_eq!(
            str_of(&from_str("{\"a\": [true]}").unwrap()),
            "{'a': [True]}"
        );
        assert_eq!(repr(&from_str("\"it's\"").unwrap()), "\"it's\"");
        assert_eq!(repr(&from_str("\"a\\nb\\u00a0\"").unwrap()), "'a\\nb\\xa0'");
    }

    #[test]
    fn wholes() {
        assert_eq!(
            Whole::of(&from_str("-2.5").unwrap()).unwrap().to_string(),
            "-2"
        );
        assert_eq!(
            Whole::of(&from_str("\" 1_000 \"").unwrap())
                .unwrap()
                .to_string(),
            "1000"
        );
        assert_eq!(
            Whole::of(&from_str("1e30").unwrap()).unwrap().digits,
            "1000000000000000019884624838656"
        );
        assert!(Whole::of(&Value::Null).is_err());
    }

    #[test]
    fn sorting_is_stable() {
        let found = vec![(2, 'a'), (1, 'b'), (2, 'c'), (1, 'd')];
        let less = |a: &(i32, char), b: &(i32, char)| Ok(a.0 < b.0);
        let sorted = sorted_by(&found, &less).unwrap();
        assert_eq!(sorted, vec![(1, 'b'), (1, 'd'), (2, 'a'), (2, 'c')]);
    }
}
