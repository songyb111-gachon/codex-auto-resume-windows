//! `domain/public.self_check` (cut C1: it reads `failures.TAG_SHAPE`, so it is car-policy's, beside the classifier).
//!
//! The self-check a reader may show, from what the watcher wrote beside its heartbeat (`self_check_note`, which stays
//! in car-machine): only of the watcher that runs now, and only what the note writes.

use car_machine::domain::public;
use car_machine::json::{Map, Str, Value};
use car_machine::pytext::to_float;
use car_machine::pyval::{self, Py};
use car_machine::vocab_gen::domain_public as table;

use crate::classify::failures;

/// `_VERSION.fullmatch(text)`: a letter or digit, then letters, digits, dots and hyphens, at most VERSION_MAX in all.
fn version_shape(value: &Value) -> bool {
    let Some(text) = pyval::text(value) else {
        return false;
    };
    let ok = |each: char| each.is_ascii_alphanumeric() || each == '.' || each == '-';
    text.chars()
        .next()
        .is_some_and(|first| first.is_ascii_alphanumeric())
        && text.chars().count() <= public::VERSION_MAX
        && text.chars().all(ok)
}

/// `self_check(value, started_at)`: `{"blocked", "unknown_error", "layout_untested", "updated_from"}`, each None where
/// it says nothing - or None. `float(started_at)` of an int past a float's reach raises OverflowError, as in Python.
pub fn self_check(value: &Value, started_at: &Value) -> Py<Value> {
    let Value::Object(note) = value else {
        return Ok(Value::Null);
    };
    if !note
        .get("format")
        .is_some_and(|format| pyval::is(format, table::SELF_CHECK_FORMAT))
    {
        return Ok(Value::Null);
    }
    if !matches!(started_at, Value::Int(_) | Value::Float(_)) {
        return Ok(Value::Null);
    }
    // isinstance(value.get("started_at"), (int, float)): a bool is an int here.
    let numeric =
        |found: &&Value| matches!(found, Value::Int(_) | Value::Float(_) | Value::Bool(_));
    let Some(written) = note.get("started_at").filter(numeric) else {
        return Ok(Value::Null);
    };
    let started = to_float(started_at)?;
    if !pyval::eq(written, &Value::Float(started)) {
        return Ok(Value::Null);
    }
    let word = note
        .get("blocked")
        .filter(|found| pyval::in_tuple(found, table::WORDS))
        .cloned()
        .unwrap_or(Value::Null);
    let unknown = match note.get("unknown_error") {
        Some(Value::Object(found)) => {
            let code = found
                .get("code")
                .and_then(pyval::text)
                .filter(|code| failures::tag_shape(code));
            let count = match found.get("count") {
                Some(Value::Int(int)) => int
                    .as_i64()
                    .filter(|count| *count > 0 && *count < 1_000_000),
                _ => None,
            };
            match (code, count) {
                (Some(code), Some(count)) => {
                    let mut kept = Map::new();
                    kept.insert(Str::from("code"), Value::from(code));
                    kept.insert(Str::from("count"), Value::from(count));
                    Value::Object(kept)
                }
                _ => Value::Null,
            }
        }
        _ => Value::Null,
    };
    let version = |key: &str| {
        note.get(key)
            .filter(|found| version_shape(found))
            .cloned()
            .unwrap_or(Value::Null)
    };
    let (layout, updated) = (version("layout_untested"), version("updated_from"));
    if [&word, &unknown, &layout, &updated]
        .iter()
        .all(|each| matches!(each, Value::Null))
    {
        return Ok(Value::Null);
    }
    let mut out = Map::new();
    out.insert(Str::from("blocked"), word);
    out.insert(Str::from("unknown_error"), unknown);
    out.insert(Str::from("layout_untested"), layout);
    out.insert(Str::from("updated_from"), updated);
    Ok(Value::Object(out))
}
