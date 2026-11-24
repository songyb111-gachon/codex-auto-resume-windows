//! `memguard.py`: the watcher's memory guard (v0.6.11), off by default.
//!
//! `memory_guard` is off, warn (one notification the first time over the limit) or stop (the same, then the watcher
//! stops between two ticks); `memory_guard_limit` is the limit, read only while the guard is on. Pure: settings and
//! numbers in, answers out.

use car_machine::json::{Int, Value};
use car_machine::pyval::{self, Num};

use super::ownvalues::{self, Measured, Own, OwnKind};

pub const GUARD_FIELD: &str = "memory_guard";
pub const LIMIT_FIELD: &str = "memory_guard_limit";
/// `MODES` (MemoryGuard) and `LIMITS` (MemoryLimit).
pub const MODES: &[&str] = &["off", "warn", "stop"];
pub const LIMITS: &[&str] = &["mb256", "mb512", "mb768", "mb1024", "mb1536", "mb2048"];
pub const DEFAULT_MODE: &str = "off";
pub const DEFAULT_LIMIT: &str = "mb1024";
pub const MIB: i64 = 1024 * 1024;
pub const OK: &str = "ok";
pub const WARN: &str = "warn";
pub const STOP: &str = "stop";
/// `OWN[LIMIT_FIELD]`: 128 MiB to 16 GiB in whole MiB, said as "{n} MB".
pub static LIMIT_OWN: Own = Own::new(OwnKind::Count, 128, 16 * 1024, &[""])
    .prefix("mb")
    .amount("own.mb");

fn field<'a>(values: &'a Value, name: &str) -> &'a Value {
    static NULL: Value = Value::Null;
    match values {
        Value::Object(map) => map.get(name).unwrap_or(&NULL),
        _ => &NULL,
    }
}

/// `mode(values)`: off, warn or stop - off for anything the settings would not store.
pub fn mode(values: &Value) -> &str {
    match field(values, GUARD_FIELD) {
        Value::Str(text) => text
            .as_str()
            .and_then(|text| MODES.iter().find(|mode| **mode == text))
            .copied(),
        _ => None,
    }
    .unwrap_or(DEFAULT_MODE)
}

/// `limit_mib(values)`: the limit, in MiB.
pub fn limit_mib(values: &Value) -> i64 {
    let own = ownvalues::amount(&LIMIT_OWN, field(values, LIMIT_FIELD))
        .or_else(|| ownvalues::amount(&LIMIT_OWN, &Value::from(DEFAULT_LIMIT)));
    match own {
        Some(Measured::Number(mib)) => mib,
        _ => 1024,
    }
}

/// `mib(count)`: a number of bytes as whole MiB, rounded up; None for anything that is not a count of bytes.
pub fn mib(count: &Value) -> Value {
    let Value::Int(int) = count else {
        return Value::Null;
    };
    let text = int.to_string();
    if text.starts_with('-') {
        return Value::Null;
    }
    // -(-count // MIB): a ceiling division, by long division of the decimal digits (an int of any size).
    let mut quotient = String::new();
    let mut remainder: u128 = 0;
    for digit in text.bytes() {
        remainder = remainder * 10 + u128::from(digit - b'0');
        let place = remainder / MIB as u128;
        remainder %= MIB as u128;
        if !(quotient.is_empty() && place == 0) {
            quotient.push(char::from(b'0' + place as u8));
        }
    }
    let quotient = if quotient.is_empty() {
        "0".to_owned()
    } else {
        quotient
    };
    let quotient = Int::parse(&quotient).expect("digits");
    if remainder == 0 {
        return Value::Int(quotient);
    }
    Value::Int(add_one(&quotient))
}

fn add_one(int: &Int) -> Int {
    let mut digits: Vec<u8> = int.to_string().into_bytes();
    let mut at = digits.len();
    loop {
        if at == 0 {
            digits.insert(0, b'1');
            break;
        }
        at -= 1;
        if digits[at] == b'9' {
            digits[at] = b'0';
        } else {
            digits[at] += 1;
            break;
        }
    }
    Int::parse(std::str::from_utf8(&digits).expect("digits")).expect("digits")
}

/// `verdict(values, private, warned)`: after a tick, OK, WARN (the first time over the limit, with warn) or STOP.
pub fn verdict(values: &Value, private: &Value, warned: &Value) -> &'static str {
    let chosen = mode(values);
    if chosen == "off" || !matches!(private, Value::Int(_)) {
        return OK;
    }
    let limit = Num::Whole(i128::from(limit_mib(values)) * i128::from(MIB));
    let over = Num::of(private).is_some_and(|found| {
        pyval::compare(found, limit).is_some_and(|order| order == std::cmp::Ordering::Greater)
    });
    if !over {
        return OK;
    }
    if chosen == "stop" {
        return STOP;
    }
    if pyval::truthy(warned) { OK } else { WARN }
}
