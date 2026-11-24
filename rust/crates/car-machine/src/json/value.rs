//! The value model: Python's `str`, `int` and `dict` as JSON sees them.

use std::fmt;
use std::hash::{Hash, Hasher};

use indexmap::{Equivalent, IndexMap};

/// A JSON object: keys in the order they were inserted, as a Python `dict` keeps them.
/// Inserting a key that is already there keeps its place and replaces its value, as a
/// `dict` (and `json.loads` with a repeated key) does.
pub type Map = IndexMap<Str, Value>;

/// A JSON value, as Python's `json` module reads and writes it.
#[derive(Clone, Debug, PartialEq)]
pub enum Value {
    Null,
    Bool(bool),
    Int(Int),
    /// Any f64. A NaN or an infinity is refused when written (`allow_nan=False`).
    Float(f64),
    Str(Str),
    Array(Vec<Value>),
    Object(Map),
}

/// A Python `str`: a sequence of code points from U+0000 to U+10FFFF, surrogates included.
///
/// Held as the bytes `s.encode("utf-8", "surrogatepass")` gives: UTF-8, where a surrogate code
/// point is written as the three bytes its value would take. A text without surrogates is
/// plain UTF-8, so [`Str::as_str`] borrows it. Two surrogates side by side stay two code points,
/// as in Python (`"\ud83d" + "\ude00"` is not `"\U0001f600"`). Byte order is code point order,
/// which is how Python sorts keys.
#[derive(Clone, Default, PartialEq, Eq, PartialOrd, Ord)]
pub struct Str(Vec<u8>);

impl Str {
    /// A text that is valid UTF-8.
    pub fn new(text: &str) -> Str {
        Str(text.as_bytes().to_vec())
    }

    /// The code points of a Python `str`; `None` if one is past U+10FFFF.
    pub fn from_code_points<I: IntoIterator<Item = u32>>(points: I) -> Option<Str> {
        let mut bytes = Vec::new();
        for point in points {
            if point > 0x10FFFF {
                return None;
            }
            push_code_point(&mut bytes, point);
        }
        Some(Str(bytes))
    }

    /// A Windows wide string as Python decodes one: pairs joined, a lone half kept as itself.
    pub fn from_wide(units: &[u16]) -> Str {
        let points = char::decode_utf16(units.iter().copied()).map(|unit| match unit {
            Ok(c) => c as u32,
            Err(lone) => u32::from(lone.unpaired_surrogate()),
        });
        Str::from_code_points(points).expect("UTF-16 never reaches past U+10FFFF")
    }

    /// The bytes of Python's `s.encode("utf-8", "surrogatepass")`; `None` if they are not that.
    pub fn from_surrogatepass(bytes: Vec<u8>) -> Option<Str> {
        let mut at = 0;
        while at < bytes.len() {
            let (_, length) = decode(&bytes[at..])?;
            at += length;
        }
        Some(Str(bytes))
    }

    /// The bytes `s.encode("utf-8", "surrogatepass")` gives.
    pub fn as_bytes(&self) -> &[u8] {
        &self.0
    }

    /// The text, when it holds no surrogate.
    pub fn as_str(&self) -> Option<&str> {
        std::str::from_utf8(&self.0).ok()
    }

    /// Whether a surrogate code point is in it, which strict UTF-8 cannot write.
    pub fn has_surrogate(&self) -> bool {
        self.as_str().is_none()
    }

    /// The code points, in order.
    pub fn code_points(&self) -> CodePoints<'_> {
        CodePoints(&self.0)
    }

    /// `len(s)` in Python: the number of code points.
    pub fn len(&self) -> usize {
        self.code_points().count()
    }

    pub fn is_empty(&self) -> bool {
        self.0.is_empty()
    }
}

/// The code points of a [`Str`].
pub struct CodePoints<'a>(&'a [u8]);

impl Iterator for CodePoints<'_> {
    type Item = u32;

    fn next(&mut self) -> Option<u32> {
        if self.0.is_empty() {
            return None;
        }
        let (point, length) = decode(self.0).expect("a Str holds only well-formed bytes");
        self.0 = &self.0[length..];
        Some(point)
    }
}

/// The code point the bytes start with and how many bytes it takes, or `None` where they are
/// not UTF-8 extended to surrogates (overlong forms and values past U+10FFFF refused).
pub(crate) fn decode(bytes: &[u8]) -> Option<(u32, usize)> {
    let first = *bytes.first()?;
    let (length, initial, least) = match first {
        0x00..=0x7F => return Some((u32::from(first), 1)),
        0xC2..=0xDF => (2, u32::from(first & 0x1F), 0x80),
        0xE0..=0xEF => (3, u32::from(first & 0x0F), 0x800),
        0xF0..=0xF4 => (4, u32::from(first & 0x07), 0x10000),
        _ => return None,
    };
    let mut point = initial;
    for index in 1..length {
        let byte = *bytes.get(index)?;
        if byte & 0xC0 != 0x80 {
            return None;
        }
        point = (point << 6) | u32::from(byte & 0x3F);
    }
    if point < least || point > 0x10FFFF {
        return None;
    }
    Some((point, length))
}

pub(crate) fn push_code_point(bytes: &mut Vec<u8>, point: u32) {
    // The bytes are cast down on purpose: each is masked or shifted into 0..=0xFF first.
    match point {
        0..=0x7F => bytes.push(point as u8),
        0x80..=0x7FF => bytes.extend([0xC0 | (point >> 6) as u8, 0x80 | (point & 0x3F) as u8]),
        0x800..=0xFFFF => bytes.extend([
            0xE0 | (point >> 12) as u8,
            0x80 | ((point >> 6) & 0x3F) as u8,
            0x80 | (point & 0x3F) as u8,
        ]),
        _ => bytes.extend([
            0xF0 | (point >> 18) as u8,
            0x80 | ((point >> 12) & 0x3F) as u8,
            0x80 | ((point >> 6) & 0x3F) as u8,
            0x80 | (point & 0x3F) as u8,
        ]),
    }
}

// Hashed as `str` hashes, so a `&str` finds its key in a `Map` (`map.get("ok")`).
impl Hash for Str {
    fn hash<H: Hasher>(&self, state: &mut H) {
        match self.as_str() {
            Some(text) => text.hash(state),
            None => {
                state.write(&self.0);
                state.write_u8(0xFF);
            }
        }
    }
}

impl Equivalent<Str> for str {
    fn equivalent(&self, key: &Str) -> bool {
        self.as_bytes() == key.0.as_slice()
    }
}

impl fmt::Debug for Str {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self.as_str() {
            Some(text) => fmt::Debug::fmt(text, formatter),
            None => {
                formatter.write_str("\"")?;
                for point in self.code_points() {
                    match char::from_u32(point) {
                        Some(c) => write!(formatter, "{}", c.escape_debug())?,
                        None => write!(formatter, "\\u{{{point:x}}}")?,
                    }
                }
                formatter.write_str("\"")
            }
        }
    }
}

impl From<&str> for Str {
    fn from(text: &str) -> Str {
        Str::new(text)
    }
}

impl From<String> for Str {
    fn from(text: String) -> Str {
        Str(text.into_bytes())
    }
}

/// A Python `int`: any size.
#[derive(Clone, PartialEq, Eq, Hash)]
pub struct Int(Repr);

#[derive(Clone, PartialEq, Eq, Hash)]
enum Repr {
    I64(i64),
    /// Past i64::MAX only.
    U64(u64),
    /// Outside i64 and u64: canonical decimal (`-?[1-9][0-9]*`).
    Big(String),
}

impl Int {
    /// The integer a decimal text says, as Python's `int(text)` reads one: an optional sign,
    /// then digits (leading zeros allowed). `None` for anything else. No digit limit here:
    /// that is the writer's ([`MAX_INT_DIGITS`](crate::json::MAX_INT_DIGITS)) and the reader's.
    pub fn parse(text: &str) -> Option<Int> {
        let (negative, digits) = match text.as_bytes().first()? {
            b'-' => (true, &text[1..]),
            b'+' => (false, &text[1..]),
            _ => (false, text),
        };
        if digits.is_empty() || !digits.bytes().all(|b| b.is_ascii_digit()) {
            return None;
        }
        let digits = digits.trim_start_matches('0');
        if digits.is_empty() {
            return Some(Int(Repr::I64(0)));
        }
        let canonical = if negative {
            format!("-{digits}")
        } else {
            digits.to_owned()
        };
        if let Ok(small) = canonical.parse::<i64>() {
            return Some(Int(Repr::I64(small)));
        }
        if let Ok(large) = canonical.parse::<u64>() {
            return Some(Int(Repr::U64(large)));
        }
        Some(Int(Repr::Big(canonical)))
    }

    pub fn as_i64(&self) -> Option<i64> {
        match self.0 {
            Repr::I64(value) => Some(value),
            _ => None,
        }
    }

    pub fn as_u64(&self) -> Option<u64> {
        match self.0 {
            Repr::I64(value) => u64::try_from(value).ok(),
            Repr::U64(value) => Some(value),
            Repr::Big(_) => None,
        }
    }

    /// How many decimal digits it has, the sign not counted: what Python's digit limit counts.
    pub fn digits(&self) -> usize {
        match &self.0 {
            Repr::I64(value) => value.unsigned_abs().to_string().len(),
            Repr::U64(value) => value.to_string().len(),
            Repr::Big(text) => text.trim_start_matches('-').len(),
        }
    }
}

impl fmt::Display for Int {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match &self.0 {
            Repr::I64(value) => write!(formatter, "{value}"),
            Repr::U64(value) => write!(formatter, "{value}"),
            Repr::Big(text) => formatter.write_str(text),
        }
    }
}

impl fmt::Debug for Int {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        fmt::Display::fmt(self, formatter)
    }
}

impl From<i64> for Int {
    fn from(value: i64) -> Int {
        Int(Repr::I64(value))
    }
}

impl From<u64> for Int {
    fn from(value: u64) -> Int {
        match i64::try_from(value) {
            Ok(small) => Int(Repr::I64(small)),
            Err(_) => Int(Repr::U64(value)),
        }
    }
}

impl From<i32> for Int {
    fn from(value: i32) -> Int {
        Int(Repr::I64(i64::from(value)))
    }
}

impl From<u32> for Int {
    fn from(value: u32) -> Int {
        Int(Repr::I64(i64::from(value)))
    }
}

impl From<bool> for Value {
    fn from(value: bool) -> Value {
        Value::Bool(value)
    }
}

impl From<Int> for Value {
    fn from(value: Int) -> Value {
        Value::Int(value)
    }
}

impl From<i64> for Value {
    fn from(value: i64) -> Value {
        Value::Int(value.into())
    }
}

impl From<u64> for Value {
    fn from(value: u64) -> Value {
        Value::Int(value.into())
    }
}

impl From<i32> for Value {
    fn from(value: i32) -> Value {
        Value::Int(value.into())
    }
}

impl From<u32> for Value {
    fn from(value: u32) -> Value {
        Value::Int(value.into())
    }
}

impl From<f64> for Value {
    fn from(value: f64) -> Value {
        Value::Float(value)
    }
}

impl From<&str> for Value {
    fn from(value: &str) -> Value {
        Value::Str(value.into())
    }
}

impl From<String> for Value {
    fn from(value: String) -> Value {
        Value::Str(value.into())
    }
}

impl From<Str> for Value {
    fn from(value: Str) -> Value {
        Value::Str(value)
    }
}

impl From<Vec<Value>> for Value {
    fn from(value: Vec<Value>) -> Value {
        Value::Array(value)
    }
}

impl From<Map> for Value {
    fn from(value: Map) -> Value {
        Value::Object(value)
    }
}

impl<T: Into<Value>> From<Option<T>> for Value {
    fn from(value: Option<T>) -> Value {
        value.map_or(Value::Null, Into::into)
    }
}
