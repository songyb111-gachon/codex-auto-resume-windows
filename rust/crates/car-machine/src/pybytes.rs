//! Python's `bytes` in a JSON-shaped value: a BLOB a SQLite column holds, as car-store's rows and car-codex's cells
//! carry it (fix5's `value::blob`, moved here by Integration 6 so both crates carry one the same way).
//!
//! A JSON value has no type for `bytes`, so a BLOB is a one-key object of its bytes in hex (`{"\u0000bytes": "01"}`):
//! its key starts with a NUL, which no column name and no word of the product holds. The reference's diff runners
//! write `bytes` the same way. Whoever reads a value as Python would asks [`blob_bytes`] first where `bytes` behaves
//! otherwise than a dict (truth, equality, binding back, sort).

use crate::json::{Map, Str, Value};

/// The key of a BLOB's value (`blob`): it starts with a NUL, which no column name and no word of the product holds.
pub const BLOB_KEY: &str = "\u{0}bytes";

/// A BLOB as a row holds it: Python's `bytes`, which a JSON value has no type for, kept as a one-key object of its
/// bytes in hex (`{"\u0000bytes": "01"}`). The helpers here give it `bytes`' behaviour: its truth is whether it holds
/// a byte, it equals only the same bytes, it binds back as a BLOB, and no check that wants a number or a text takes it.
pub fn blob(bytes: &[u8]) -> Value {
    let mut hex = String::with_capacity(bytes.len() * 2);
    for byte in bytes {
        hex.push(char::from_digit(u32::from(byte >> 4), 16).unwrap_or('0'));
        hex.push(char::from_digit(u32::from(byte & 15), 16).unwrap_or('0'));
    }
    let mut map = Map::with_capacity(1);
    map.insert(Str::new(BLOB_KEY), Value::from(hex.as_str()));
    Value::Object(map)
}

/// The bytes of a BLOB's value (`blob`), or None for any other value.
pub fn blob_bytes(value: &Value) -> Option<Vec<u8>> {
    let Value::Object(map) = value else {
        return None;
    };
    if map.len() != 1 {
        return None;
    }
    let Value::Str(hex) = map.get(BLOB_KEY)? else {
        return None;
    };
    let hex = hex.as_str()?;
    if hex.len() % 2 != 0 {
        return None;
    }
    (0..hex.len() / 2)
        .map(|at| u8::from_str_radix(hex.get(at * 2..at * 2 + 2)?, 16).ok())
        .collect()
}
