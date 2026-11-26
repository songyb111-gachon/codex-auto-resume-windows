//! `compat/model.py`'s `decode`: bytes to a JSON value, hardened.
//!
//! A byte cap before anything is parsed, duplicate keys refused, `NaN`/`Infinity` and overflowing numbers
//! refused, deep nesting refused. Python reads it with `json.loads(object_pairs_hook=..., parse_constant=...,
//! parse_float=...)`; serde_json refuses a lone surrogate escape and nests no deeper than 128, so this reads
//! the same grammar by hand (iteratively, so a nesting of thousands costs no stack), in the order Python's
//! scanner meets things: the first problem it meets decides the code.
//!
//! How deep a document may nest is the bundled Python 3.14.10's: a stack budget that a list's level and an object's
//! level spend differently ([`crate::json::depth`] holds the measurement and the rule), and, for `decode`, the room its
//! hooks need at the deepest point.

use crate::json::depth::{self, Budget, Hooks};
use crate::json::{Int, Map, Str, Value};
use crate::vocab_gen::compat_model::IMPORT_REASONS;

pub use crate::json::depth::{LOADS_LIST_LEVELS, LOADS_OBJECT_LEVELS};
/// Python's limit on the digits of an integer literal.
const MAX_INT_DIGITS: usize = 4300;
pub const MAX_DOCUMENT_BYTES: usize = 256 * 1024;

/// A refused document: `code` is one of `IMPORT_REASONS` and nothing else (`DocumentError`).
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct DocumentError {
    pub code: &'static str,
}

impl DocumentError {
    pub fn new(code: &'static str) -> DocumentError {
        DocumentError {
            code: if IMPORT_REASONS.contains(&code) {
                code
            } else {
                "invalid_field"
            },
        }
    }
}

impl std::fmt::Display for DocumentError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter.write_str(self.code)
    }
}

impl std::error::Error for DocumentError {}

enum Failure {
    /// Not JSON: a `JSONDecodeError`, or the ValueError of a number too long.
    Syntax,
    /// Python's RecursionError.
    TooDeep,
    /// The ValueError of an integer literal past Python's digit limit (not a JSONDecodeError).
    IntTooLong,
    /// A hook refused: `duplicate_key` or `not_finite`.
    Code(&'static str),
}

enum Frame {
    Array(Vec<Value>),
    Object(Vec<(Str, Value)>, Option<Str>),
}

struct Scanner<'a> {
    chars: &'a [char],
    /// `decode`'s hooks (no duplicate key, no NaN, no overflowing float) or plain `json.loads`.
    strict: bool,
}

impl Scanner<'_> {
    fn at(&self, i: usize) -> Option<char> {
        self.chars.get(i).copied()
    }

    fn skip_ws(&self, mut i: usize) -> usize {
        while matches!(self.at(i), Some(' ' | '\t' | '\n' | '\r')) {
            i += 1;
        }
        i
    }

    fn word(&self, i: usize, word: &str) -> bool {
        word.chars()
            .enumerate()
            .all(|(offset, each)| self.at(i + offset) == Some(each))
    }

    fn hex4(&self, i: usize) -> Option<u32> {
        let mut value = 0;
        for offset in 0..4 {
            value = value * 16 + self.at(i + offset)?.to_digit(16)?;
        }
        Some(value)
    }

    /// The string whose opening quote is at `i - 1`: its text and the index after its closing quote.
    fn string(&self, mut i: usize) -> Result<(Str, usize), Failure> {
        let mut points: Vec<u32> = Vec::new();
        loop {
            let each = self.at(i).ok_or(Failure::Syntax)?;
            i += 1;
            match each {
                '"' => break,
                '\\' => {
                    let escape = self.at(i).ok_or(Failure::Syntax)?;
                    i += 1;
                    match escape {
                        '"' | '\\' | '/' => points.push(escape as u32),
                        'b' => points.push(8),
                        'f' => points.push(12),
                        'n' => points.push(10),
                        'r' => points.push(13),
                        't' => points.push(9),
                        'u' => {
                            let mut unit = self.hex4(i).ok_or(Failure::Syntax)?;
                            i += 4;
                            let pair = (0xD800..=0xDBFF).contains(&unit)
                                && self.at(i) == Some('\\')
                                && self.at(i + 1) == Some('u');
                            if pair
                                && let Some(low) = self
                                    .hex4(i + 2)
                                    .filter(|low| (0xDC00..=0xDFFF).contains(low))
                            {
                                unit = 0x10000 + ((unit - 0xD800) << 10) + (low - 0xDC00);
                                i += 6;
                            }
                            points.push(unit);
                        }
                        _ => return Err(Failure::Syntax),
                    }
                }
                control if (control as u32) < 0x20 => return Err(Failure::Syntax),
                plain => points.push(plain as u32),
            }
        }
        Ok((Str::from_code_points(points).ok_or(Failure::Syntax)?, i))
    }

    /// A number at `i`: the value and the index after it.
    fn number(&self, start: usize) -> Result<(Value, usize), Failure> {
        let mut i = start;
        if self.at(i) == Some('-') {
            i += 1;
        }
        match self.at(i) {
            Some('0') => i += 1,
            Some('1'..='9') => {
                while self.at(i).is_some_and(|each| each.is_ascii_digit()) {
                    i += 1;
                }
            }
            _ => return Err(Failure::Syntax),
        }
        let mut real = false;
        if self.at(i) == Some('.') && self.at(i + 1).is_some_and(|each| each.is_ascii_digit()) {
            i += 1;
            while self.at(i).is_some_and(|each| each.is_ascii_digit()) {
                i += 1;
            }
            real = true;
        }
        if matches!(self.at(i), Some('e' | 'E')) {
            let mut j = i + 1;
            if matches!(self.at(j), Some('+' | '-')) {
                j += 1;
            }
            if self.at(j).is_some_and(|each| each.is_ascii_digit()) {
                while self.at(j).is_some_and(|each| each.is_ascii_digit()) {
                    j += 1;
                }
                i = j;
                real = true;
            }
        }
        let literal: String = self.chars[start..i].iter().collect();
        if real {
            let value: f64 = literal.parse().map_err(|_| Failure::Syntax)?;
            return Ok((Value::Float(value), i));
        }
        if literal.trim_start_matches('-').len() > MAX_INT_DIGITS {
            return Err(Failure::IntTooLong);
        }
        Ok((Value::Int(Int::parse(&literal).ok_or(Failure::Syntax)?), i))
    }

    /// `"key"` then `:` from `i` (just after an opening brace or a comma and white space): the key and the index of
    /// the value.
    fn key(&self, i: usize) -> Result<(Str, usize), Failure> {
        if self.at(i) != Some('"') {
            return Err(Failure::Syntax);
        }
        let (key, after) = self.string(i + 1)?;
        let colon = self.skip_ws(after);
        if self.at(colon) != Some(':') {
            return Err(Failure::Syntax);
        }
        Ok((key, self.skip_ws(colon + 1)))
    }

    /// `object_pairs_hook`, called when an object closes (`{}` too): a Python call made from the scanner, which needs
    /// room on the stack at the deepest point (`decode` passes one; the plain reader has none).
    fn object_hook(&self, budget: &Budget) -> Result<(), Failure> {
        if self.strict && !budget.room_for_object_levels(Hooks::OBJECT_PAIRS_OBJECT_LEVELS) {
            return Err(Failure::TooDeep);
        }
        Ok(())
    }

    /// `NaN`, `Infinity`, `-Infinity`: `decode`'s `parse_constant` hook (a Python call, which then refuses it) or the
    /// plain reader's own table (a little room too).
    fn constant(&self, budget: &Budget) -> Result<(), Failure> {
        if self.strict {
            if !budget.room_for_list_levels(Hooks::PARSE_CONSTANT_LIST_LEVELS) {
                return Err(Failure::TooDeep);
            }
            return Err(Failure::Code("not_finite"));
        }
        if !budget.room_for_list_levels(Hooks::PLAIN_CONSTANT_LIST_LEVELS) {
            return Err(Failure::TooDeep);
        }
        Ok(())
    }

    fn parse(&self) -> Result<Value, Failure> {
        self.parse_at(self.skip_ws(0), true).map(|(value, _)| value)
    }

    /// One value from `start` (no white space skipped before it): the value and the index after it; with `whole`,
    /// only white space may follow it.
    fn parse_at(&self, start: usize, whole: bool) -> Result<(Value, usize), Failure> {
        let mut stack: Vec<Frame> = Vec::new();
        let mut budget = depth::loads();
        let mut i = start;
        loop {
            let mut done = match self.at(i).ok_or(Failure::Syntax)? {
                '[' => {
                    if !budget.enter_list() {
                        return Err(Failure::TooDeep);
                    }
                    i = self.skip_ws(i + 1);
                    if self.at(i) == Some(']') {
                        i += 1;
                        budget.leave_list();
                        Value::Array(Vec::new())
                    } else {
                        stack.push(Frame::Array(Vec::new()));
                        continue;
                    }
                }
                '{' => {
                    if !budget.enter_object() {
                        return Err(Failure::TooDeep);
                    }
                    i = self.skip_ws(i + 1);
                    if self.at(i) == Some('}') {
                        i += 1;
                        self.object_hook(&budget)?;
                        budget.leave_object();
                        Value::Object(Map::new())
                    } else {
                        let (key, value_at) = self.key(i)?;
                        i = value_at;
                        stack.push(Frame::Object(Vec::new(), Some(key)));
                        continue;
                    }
                }
                '"' => {
                    let (text, after) = self.string(i + 1)?;
                    i = after;
                    Value::Str(text)
                }
                'n' if self.word(i, "null") => {
                    i += 4;
                    Value::Null
                }
                't' if self.word(i, "true") => {
                    i += 4;
                    Value::Bool(true)
                }
                'f' if self.word(i, "false") => {
                    i += 5;
                    Value::Bool(false)
                }
                'N' if self.word(i, "NaN") => {
                    self.constant(&budget)?;
                    i += 3;
                    Value::Float(f64::NAN)
                }
                'I' if self.word(i, "Infinity") => {
                    self.constant(&budget)?;
                    i += 8;
                    Value::Float(f64::INFINITY)
                }
                '-' if self.word(i, "-Infinity") => {
                    self.constant(&budget)?;
                    i += 9;
                    Value::Float(f64::NEG_INFINITY)
                }
                _ => {
                    let (value, after) = self.number(i)?;
                    i = after;
                    if self.strict
                        && let Value::Float(x) = value
                    {
                        // `parse_float` is a Python call from the scanner: it needs room, and then refuses what is
                        // not finite.
                        if !budget.room_for_list_levels(Hooks::PARSE_FLOAT_LIST_LEVELS) {
                            return Err(Failure::TooDeep);
                        }
                        if !x.is_finite() {
                            return Err(Failure::Code("not_finite"));
                        }
                    }
                    value
                }
            };
            loop {
                let Some(top) = stack.last_mut() else {
                    return if !whole || self.skip_ws(i) == self.chars.len() {
                        Ok((done, i))
                    } else {
                        Err(Failure::Syntax)
                    };
                };
                i = self.skip_ws(i);
                match top {
                    Frame::Array(items) => {
                        items.push(done);
                        match self.at(i) {
                            Some(',') => {
                                i = self.skip_ws(i + 1);
                                break;
                            }
                            Some(']') => {
                                i += 1;
                                done = Value::Array(std::mem::take(items));
                                stack.pop();
                                budget.leave_list();
                            }
                            _ => return Err(Failure::Syntax),
                        }
                    }
                    Frame::Object(pairs, pending) => {
                        let key = pending.take().ok_or(Failure::Syntax)?;
                        pairs.push((key, done));
                        match self.at(i) {
                            Some(',') => {
                                let (key, value_at) = self.key(self.skip_ws(i + 1))?;
                                i = value_at;
                                *pending = Some(key);
                                break;
                            }
                            Some('}') => {
                                i += 1;
                                self.object_hook(&budget)?;
                                let mut map = Map::with_capacity(pairs.len());
                                for (key, item) in std::mem::take(pairs) {
                                    if map.insert(key, item).is_some() && self.strict {
                                        return Err(Failure::Code("duplicate_key"));
                                    }
                                }
                                done = Value::Object(map);
                                stack.pop();
                                budget.leave_object();
                            }
                            _ => return Err(Failure::Syntax),
                        }
                    }
                }
            }
        }
    }
}

/// `decode(raw, limit)`: bytes to a JSON value, hardened. Never returns a partial value.
pub fn decode(raw: &[u8], limit: usize) -> Result<Value, DocumentError> {
    if raw.len() > limit {
        return Err(DocumentError::new("too_large"));
    }
    let body = raw.strip_prefix(b"\xEF\xBB\xBF").unwrap_or(raw);
    let Ok(text) = std::str::from_utf8(body) else {
        return Err(DocumentError::new("not_json"));
    };
    let chars: Vec<char> = text.chars().collect();
    match (Scanner {
        chars: &chars,
        strict: true,
    })
    .parse()
    {
        Ok(value) => Ok(value),
        Err(Failure::Code(code)) => Err(DocumentError::new(code)),
        Err(Failure::TooDeep) => Err(DocumentError::new("too_deep")),
        Err(Failure::Syntax | Failure::IntTooLong) => Err(DocumentError::new("not_json")),
    }
}

/// Why `json.loads` refused a text: the ValueError of a bad one, or the RecursionError of a deep one.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum LoadsError {
    /// A `JSONDecodeError`.
    Value,
    Recursion,
    /// The plain ValueError of an integer literal of more than 4300 digits (S2.2: the settings file names the class).
    IntTooLong,
}

/// `json.loads(text)` as Python reads it with no hooks: `NaN` and `Infinity` are numbers, a number too big for a float
/// is infinity, a repeated key keeps its first place and its last value; nesting past the interpreter's limit and an
/// integer of more than 4300 digits are refused.
pub fn loads(text: &str) -> Result<Value, LoadsError> {
    let chars: Vec<char> = text.chars().collect();
    match (Scanner {
        chars: &chars,
        strict: false,
    })
    .parse()
    {
        Ok(value) => Ok(value),
        Err(Failure::TooDeep) => Err(LoadsError::Recursion),
        Err(Failure::IntTooLong) => Err(LoadsError::IntTooLong),
        Err(_) => Err(LoadsError::Value),
    }
}

/// `json.JSONDecoder().raw_decode(text, at)`: one value starting exactly at `at` (a code point index), and the index
/// after it. Nothing may be skipped before it; anything may follow it.
pub fn raw_decode(chars: &[char], at: usize) -> Result<(Value, usize), LoadsError> {
    match (Scanner {
        chars,
        strict: false,
    })
    .parse_at(at, false)
    {
        Ok(found) => Ok(found),
        Err(Failure::TooDeep) => Err(LoadsError::Recursion),
        Err(Failure::IntTooLong) => Err(LoadsError::IntTooLong),
        Err(_) => Err(LoadsError::Value),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn code(text: &str) -> &'static str {
        decode(text.as_bytes(), MAX_DOCUMENT_BYTES)
            .unwrap_err()
            .code
    }

    #[test]
    fn loads_is_pythons_loose_reader() {
        assert!(loads("[NaN, Infinity, -Infinity, 1e999]").is_ok());
        assert!(loads("{\"a\": 1, \"a\": 2}").is_ok());
        assert_eq!(loads("[1,]"), Err(LoadsError::Value));
        assert_eq!(
            loads(&"[".repeat(LOADS_LIST_LEVELS as usize + 1)),
            Err(LoadsError::Recursion)
        );
    }

    #[test]
    fn the_first_problem_decides() {
        assert_eq!(code("{\"a\": 1, \"a\": 2}"), "duplicate_key");
        assert_eq!(code("{\"a\": 1, \"a\": 2} x"), "duplicate_key");
        assert_eq!(code("[1, NaN"), "not_finite");
        assert_eq!(code("[1e999]"), "not_finite");
        assert_eq!(code("[1,]"), "not_json");
        assert_eq!(code(""), "not_json");
        assert_eq!(
            code(&"[".repeat(LOADS_LIST_LEVELS as usize + 1)),
            "too_deep"
        );
        assert!(decode("[[], {\"a\": [1.5, \"\\ud83d\\ude00\"]}]".as_bytes(), 1000).is_ok());
        assert!(
            decode(
                ("[".repeat(2000) + &"]".repeat(2000)).as_bytes(),
                MAX_DOCUMENT_BYTES
            )
            .is_ok()
        );
        assert_eq!(decode(b"[]", 1).unwrap_err().code, "too_large");
    }
}
