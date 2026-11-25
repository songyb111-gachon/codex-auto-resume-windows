//! `compat/reported.py`: what other people's filed reports add up to, per Codex version. Read, never acted on.
//!
//! A file of its own (`data/reported.json`) with a format of its own; a bad file only makes Reported read
//! `rejected`. Nothing that decides reads this module.

use std::sync::Mutex;

use car_machine::compat::model::{DocumentError, decode, parse_version, safe_version};
use car_machine::json::{Map, Str, Value};
use car_machine::pytext::strip;

use super::files::{read_capped, stamp};

pub const FORMAT: &str = "codex-auto-resume-reported/1";
pub const MAX_BYTES: usize = 128 * 1024;
pub const MAX_VERSIONS: usize = 500;
pub const MAX_COUNT: i64 = 100_000;
pub const MAX_COMMENT_LINES: usize = 40;
pub const MAX_COMMENT_CHARS: usize = 200;
pub const COUNTS: [&str; 5] = ["reports", "worked", "failed", "neither", "both"];
pub const PREFIX: &str = "codex-cli ";

/// One version's counts, in `COUNTS` order.
pub type Counts = [i64; 5];
/// The table: version -> counts, in the file's order.
pub type Table = Vec<(String, Counts)>;

fn invalid() -> DocumentError {
    DocumentError::new("invalid_field")
}

/// `parse(raw)`: {version: counts} from the file's bytes, or the DocumentError that refuses all of it.
pub fn parse(raw: &[u8]) -> Result<Table, DocumentError> {
    let document = decode(raw, MAX_BYTES)?;
    let Value::Object(map) = &document else {
        return Err(DocumentError::new("not_an_object"));
    };
    if !matches!(map.get("format"), Some(Value::Str(text)) if text.as_str() == Some(FORMAT)) {
        return Err(DocumentError::new("unknown_format"));
    }
    let keys_fine = map
        .keys()
        .all(|key| matches!(key.as_str(), Some("_comment" | "format" | "versions")));
    if !keys_fine || !map.contains_key("versions") {
        return Err(invalid());
    }
    let empty = Value::Array(Vec::new());
    let comment = map.get("_comment").unwrap_or(&empty);
    let comment_fine = matches!(comment, Value::Array(lines) if lines.len() <= MAX_COMMENT_LINES
        && lines.iter().all(|line| matches!(line, Value::Str(text) if text.code_points().count() <= MAX_COMMENT_CHARS)));
    if !comment_fine {
        return Err(invalid());
    }
    let Value::Array(entries) = &map["versions"] else {
        return Err(invalid());
    };
    if entries.len() > MAX_VERSIONS {
        return Err(DocumentError::new("too_many"));
    }
    let mut table: Table = Vec::new();
    for entry in entries {
        let Value::Object(fields) = entry else {
            return Err(invalid());
        };
        let wanted = ["version", "reports", "worked", "failed", "neither", "both"];
        if fields.len() != wanted.len()
            || !fields
                .keys()
                .all(|key| key.as_str().is_some_and(|key| wanted.contains(&key)))
        {
            return Err(invalid());
        }
        let version = &fields["version"];
        let text = match version {
            Value::Str(text) => text.as_str(),
            _ => None,
        };
        if safe_version(version).is_none()
            || parse_version(version).is_none()
            || text.is_some_and(|text| table.iter().any(|(each, _)| each == text))
        {
            return Err(invalid());
        }
        let mut counts: Counts = [0; 5];
        for (slot, name) in counts.iter_mut().zip(COUNTS) {
            match &fields[name] {
                Value::Int(number)
                    if number
                        .as_i64()
                        .is_some_and(|n| (0..=MAX_COUNT).contains(&n)) =>
                {
                    *slot = number.as_i64().unwrap_or_default();
                }
                _ => return Err(invalid()),
            }
        }
        let [reports, worked, failed, neither, both] = counts;
        if reports < 1
            || worked.max(failed).max(neither) > reports
            || both != worked + failed + neither - reports
            || !(0 <= both && both <= worked.min(failed))
        {
            return Err(invalid());
        }
        table.push((text.unwrap_or_default().to_owned(), counts));
    }
    Ok(table)
}

type Held = Vec<(String, (Option<(u64, u64)>, (&'static str, Table)))>;

static HELD: Mutex<Held> = Mutex::new(Vec::new());

/// A fresh process's `_held`.
pub fn reset() {
    HELD.lock()
        .unwrap_or_else(|poisoned| poisoned.into_inner())
        .clear();
}

/// `read(path)`: (standing, table) - `ok`, `missing` or `rejected` - parsed once per version of the file.
pub fn read(path: &str) -> (&'static str, Table) {
    let Some(found) = stamp(path) else {
        return ("missing", Vec::new());
    };
    let mut held = HELD.lock().unwrap_or_else(|poisoned| poisoned.into_inner());
    if let Some((_, (at, result))) = held.iter().find(|(key, _)| key == path)
        && *at == Some(found)
    {
        return result.clone();
    }
    let result = match read_capped(path, MAX_BYTES).and_then(|raw| parse(&raw)) {
        Ok(table) => ("ok", table),
        Err(_) => ("rejected", Vec::new()),
    };
    match held.iter_mut().find(|(key, _)| key == path) {
        Some(slot) => slot.1 = (Some(found), result.clone()),
        None => held.push((path.to_owned(), (Some(found), result.clone()))),
    }
    result
}

/// `_named(version)`: `codex-cli X` for an engine version given with or without its prefix, or None.
fn named(version: &Value) -> Option<String> {
    let Value::Str(text) = version else {
        return None;
    };
    let text = strip(text.as_str()?);
    let full = if text.starts_with(PREFIX) {
        text.to_owned()
    } else {
        format!("{PREFIX}{text}")
    };
    let value = Value::from(full.as_str());
    (safe_version(&value).is_some() && parse_version(&value).is_some()).then_some(full)
}

/// `lookup(version, path=)`: {"state", "reports", "worked", "failed", "neither", "both"} for one engine version.
pub fn lookup(version: &Value, path: &str) -> Value {
    let answer = |state: &str, counts: Counts| {
        let mut map = Map::new();
        map.insert(Str::from("state"), Value::from(state));
        for (name, count) in COUNTS.iter().zip(counts) {
            map.insert(Str::from(*name), Value::from(count));
        }
        Value::Object(map)
    };
    let Some(name) = named(version) else {
        return answer("unavailable", [0; 5]);
    };
    let (standing, table) = read(path);
    match standing {
        "missing" => answer("unavailable", [0; 5]),
        "rejected" => answer("rejected", [0; 5]),
        _ => match table.iter().find(|(each, _)| *each == name) {
            None => answer("none_yet", [0; 5]),
            Some((_, counts)) => answer("reported", *counts),
        },
    }
}
