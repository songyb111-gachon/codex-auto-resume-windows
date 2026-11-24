//! `statusfile.py`: a status file for other tools (v0.6.11), off by default (`status_file`).
//!
//! While it is on, the watcher writes `config\status.json` after every tick and once as it stops; nothing reads it
//! back. It is written whole or not at all, and holds exactly [`KEYS`] - no id, label, path or text anyone wrote.
//! Turned off, the file is removed: only a regular file that says it is this one.

use std::io::Write;
use std::path::Path;

use car_machine::domain::{public, states, usage};
use car_machine::json::{self, Map, Options, Str, Value};
use car_machine::pytext;
use car_machine::pyval::{self, Num, Py};

use super::os::Os;
use super::os_error_class;
use super::unicode_gen::ALNUM;
use super::vocab_gen::statusfile as words;

pub const FIELD: &str = words::FIELD;
pub const NAME: &str = words::NAME;
pub const FORMAT: &str = words::FORMAT;
pub const KEYS: &[&str] = words::KEYS;
pub const WATCHER_WORDS: &[&str] = words::WATCHER_WORDS;
pub const RECOVERY_WORDS: &[&str] = words::RECOVERY_WORDS;
pub const ENGINE_WORDS: &[&str] = words::ENGINE_WORDS;
pub const MAX_BYTES: u64 = 16 * 1024;

/// `wanted(values)`: only while the setting is True itself.
pub fn wanted(values: &Value) -> bool {
    matches!(values, Value::Object(map) if matches!(map.get(FIELD), Some(Value::Bool(true))))
}

/// `_time(value)`: the value as a float when it is a time in the store's window, else None (OverflowError raised).
fn time(value: &Value) -> Py<Option<f64>> {
    let (low, high) = states::EPOCH_STORE;
    if states::epoch(value, low, high, false, true)? {
        Ok(Some(Num::of(value).ok_or("TypeError")?.as_f64()))
    } else {
        Ok(None)
    }
}

fn get<'a>(value: &'a Value, key: &str) -> Py<&'a Value> {
    pyval::get(value, key)
}

/// `content(...)`: the file's content, from what the watcher already has; ValueError where `clean` refuses it.
#[allow(clippy::too_many_arguments)]
pub fn content(
    now: &Value,
    version: &Value,
    running: &Value,
    enabled: &Value,
    observe_only: &Value,
    engine: &Value,
    rows: &Value,
    reading: &Value,
) -> Py<Value> {
    let mut counted: Vec<(&'static str, i64)> = Vec::new();
    let mut soonest: Option<Value> = None;
    let rows: &[Value] = match rows {
        Value::Array(items) => items,
        other if !pyval::truthy(other) => &[],
        _ => return Err("TypeError"),
    };
    for row in rows {
        let code = public::public_code(row)?;
        match counted.iter_mut().find(|(known, _)| *known == code) {
            Some(slot) => slot.1 += 1,
            None => counted.push((code, 1)),
        }
        let due = public::eligible_at(row)?;
        if matches!(due, Value::Int(_) | Value::Float(_)) && pyval::is_finite(&due)? {
            soonest = Some(match soonest {
                None => due,
                Some(held) => {
                    if pyval::less(&due, &held)? {
                        due
                    } else {
                        held
                    }
                }
            });
        }
    }
    let mut used = Value::Null;
    if let Value::Object(_) = reading {
        let mut reply = Map::new();
        reply.insert(Str::from("windows"), get(reading, "windows")?.clone());
        let windows = usage::windows_of(&Value::Object(reply))?;
        let read_at = time(get(reading, "read_at")?)?;
        if let (Some(windows), Some(read_at)) = (windows, read_at) {
            let mut kept = Map::new();
            kept.insert(Str::from("read_at"), Value::Float(read_at));
            kept.insert(Str::from("windows"), Value::Array(windows));
            used = Value::Object(kept);
        }
    }
    counted.sort_by(|a, b| a.0.cmp(b.0));
    let pending: i64 = counted.iter().map(|(_, count)| count).sum();
    let mut by_code = Map::new();
    for (code, count) in &counted {
        by_code.insert(Str::from(*code), Value::from(*count));
    }
    let recovery = if !pyval::truthy(enabled) {
        "paused"
    } else if pyval::truthy(observe_only) {
        "observe_only"
    } else {
        "on"
    };
    let next = match &soonest {
        Some(due) => time(due)?.map_or(Value::Null, Value::Float),
        None => Value::Null,
    };
    let mut out = Map::new();
    out.insert(Str::from("format"), Value::from(FORMAT));
    out.insert(
        Str::from("written_at"),
        Value::Float(pytext::to_float(now)?),
    );
    out.insert(Str::from("version"), Value::from(pytext::py_str(version)));
    out.insert(
        Str::from("watcher"),
        Value::from(if pyval::truthy(running) {
            "running"
        } else {
            "stopped"
        }),
    );
    out.insert(Str::from("recovery"), Value::from(recovery));
    out.insert(
        Str::from("engine"),
        if pyval::in_tuple(engine, ENGINE_WORDS) {
            engine.clone()
        } else {
            Value::from("unknown")
        },
    );
    out.insert(Str::from("pending"), Value::from(pending));
    out.insert(Str::from("states"), Value::Object(by_code));
    out.insert(Str::from("next_check_at"), next);
    out.insert(Str::from("usage"), used);
    clean(&Value::Object(out))
}

fn alnum(point: u32) -> bool {
    ALNUM
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

/// `clean(value)`: `value` exactly as the file may hold it, or ValueError - the allowlist, checked key by key.
pub fn clean(value: &Value) -> Py<Value> {
    let Value::Object(map) = value else {
        return Err("ValueError");
    };
    if map.len() != KEYS.len()
        || !map
            .keys()
            .zip(KEYS)
            .all(|(key, want)| key.as_str() == Some(want))
    {
        return Err("ValueError");
    }
    let field = |name: &str| &map[name];
    if !pyval::is(field("format"), FORMAT)
        || !pyval::in_tuple(field("watcher"), WATCHER_WORDS)
        || !pyval::in_tuple(field("recovery"), RECOVERY_WORDS)
        || !pyval::in_tuple(field("engine"), ENGINE_WORDS)
    {
        return Err("ValueError");
    }
    if time(field("written_at"))?.is_none()
        || (!matches!(field("next_check_at"), Value::Null)
            && time(field("next_check_at"))?.is_none())
    {
        return Err("ValueError");
    }
    let Value::Str(version) = field("version") else {
        return Err("ValueError");
    };
    if version.is_empty()
        || version.len() > 32
        || version
            .code_points()
            .any(|point| !(alnum(point) || matches!(point, 0x2E | 0x2D | 0x2B)))
    {
        return Err("ValueError");
    }
    let Value::Object(counts) = field("states") else {
        return Err("ValueError");
    };
    let mut total: i128 = 0;
    for (code, count) in counts {
        let known = code.as_str().is_some_and(|code| {
            car_machine::vocab_gen::domain_public::PUBLIC_CODES.contains(&code)
        });
        let whole = match count {
            Value::Int(int) => int.as_i64().filter(|number| *number >= 1),
            _ => None,
        };
        let Some(whole) = whole.filter(|_| known) else {
            return Err("ValueError");
        };
        total += i128::from(whole);
    }
    match field("pending") {
        Value::Int(int)
            if int
                .as_i64()
                .is_some_and(|pending| i128::from(pending) == total) => {}
        _ => return Err("ValueError"),
    }
    match field("usage") {
        Value::Null => {}
        Value::Object(used) => {
            let ordered = used.len() == 2
                && used
                    .keys()
                    .map(|key| key.as_str())
                    .eq([Some("read_at"), Some("windows")]);
            if !ordered || time(&used["read_at"])?.is_none() {
                return Err("ValueError");
            }
            let mut reply = Map::new();
            reply.insert(Str::from("windows"), used["windows"].clone());
            let kept = usage::windows_of(&Value::Object(reply))?;
            if !kept.is_some_and(|kept| pyval::eq(&Value::Array(kept), &used["windows"])) {
                return Err("ValueError");
            }
        }
        _ => return Err("ValueError"),
    }
    Ok(value.clone())
}

/// `_ours(target)`: a regular file, not a link, that says it is this product's status file.
pub fn ours(os: &dyn Os, target: &Path) -> Py<bool> {
    if os.is_symlink(target) {
        return Ok(false);
    }
    let Ok(found) = std::fs::metadata(target) else {
        return Ok(false);
    };
    if !found.is_file() || found.len() > MAX_BYTES {
        return Ok(false);
    }
    let Ok(bytes) = std::fs::read(target) else {
        return Ok(false);
    };
    let Ok(text) = std::str::from_utf8(&bytes) else {
        return Ok(false);
    };
    match car_machine::compat::loads(text) {
        Ok(Value::Object(map)) => Ok(map
            .get("format")
            .is_some_and(|format| pyval::is(format, FORMAT))),
        Ok(_) => Ok(false),
        Err(car_machine::compat::LoadsError::Recursion) => Err("RecursionError"),
        Err(_) => Ok(false),
    }
}

/// `write(target, value)`: replace the file with `value` whole. ValueError where `clean` refuses it; OSError where
/// something that is not this file stands in its place, or the write failed (the class of what was raised).
pub fn write(os: &dyn Os, target: &Path, value: &Value) -> Py<()> {
    let cleaned = clean(value)?;
    let mut text =
        json::to_string(&cleaned, &Options::new().indent(2)).map_err(|_| "ValueError")?;
    text.push('\n');
    if os.is_symlink(target) || (target.exists() && !ours(os, target)?) {
        return Err("OSError");
    }
    // Python writes it in text mode: every line ends in CR LF.
    let data = text.replace('\n', "\r\n").into_bytes();
    let folder = target.parent().unwrap_or(Path::new("."));
    let (temporary, mut file) =
        temporary_beside(folder, "status.").map_err(|error| os_error_class(&error))?;
    let written = file
        .write_all(&data)
        .and_then(|_| file.flush())
        .and_then(|_| file.sync_all());
    drop(file);
    if let Err(error) = written.and_then(|_| std::fs::rename(&temporary, target)) {
        let _ = std::fs::remove_file(&temporary);
        return Err(os_error_class(&error));
    }
    Ok(())
}

/// `remove(target)`: remove the file if it is there and ours; whether it was removed.
pub fn remove(os: &dyn Os, target: &Path) -> Py<bool> {
    if !ours(os, target)? {
        return Ok(false);
    }
    Ok(std::fs::remove_file(target).is_ok())
}

/// A new file in `folder` named `<prefix><random>.json.tmp`, made exclusively (`tempfile.mkstemp`).
pub(crate) fn temporary_beside(
    folder: &Path,
    prefix: &str,
) -> std::io::Result<(std::path::PathBuf, std::fs::File)> {
    super::temporary_named(folder, prefix)
}
