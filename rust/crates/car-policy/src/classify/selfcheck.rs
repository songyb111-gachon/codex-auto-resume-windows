//! `domain/public.py`'s `self_check`: the self-check a reader may show, from what the watcher's file held. It reads
//! `failures.TAG_SHAPE`, so it is car-policy's (cut C1); car-machine keeps the writer (`self_check_note`).

use car_machine::json::Value;
use car_machine::pytext;
use car_machine::pyval::{self, Py};
use car_machine::vocab_gen::domain_public::{SELF_CHECK_FORMAT, WORDS};

use super::failures::tag_shape;
use super::value::{get, in_tuple, object, text};

const VERSION_MAX: usize = 32;

/// `_VERSION.fullmatch(text)`: a letter or digit, then letters, digits, dots and hyphens, at most 32 in all.
fn version_shape(candidate: &str) -> bool {
    let mut chars = candidate.chars();
    chars
        .next()
        .is_some_and(|first| first.is_ascii_alphanumeric())
        && candidate.chars().count() <= VERSION_MAX
        && chars.all(|each| each.is_ascii_alphanumeric() || each == '.' || each == '-')
}

/// `self_check(value, started_at)`: `{blocked, unknown_error, layout_untested, updated_from}` of the watcher that runs
/// now, or None.
pub fn self_check(value: &Value, started_at: &Value) -> Py<Value> {
    let Value::Object(map) = value else {
        return Ok(Value::Null);
    };
    if !pyval::is(get(map, "format"), SELF_CHECK_FORMAT)
        || !matches!(started_at, Value::Int(_) | Value::Float(_))
    {
        return Ok(Value::Null);
    }
    let theirs = get(map, "started_at");
    if !matches!(theirs, Value::Bool(_) | Value::Int(_) | Value::Float(_)) {
        return Ok(Value::Null);
    }
    let mine = Value::Float(pytext::to_float(started_at)?);
    if !pyval::eq(theirs, &mine) {
        return Ok(Value::Null);
    }
    let blocked = get(map, "blocked");
    let word = if in_tuple(blocked, WORDS) {
        blocked.clone()
    } else {
        Value::Null
    };
    let unknown = match get(map, "unknown_error") {
        Value::Object(found) => match (get(found, "code"), get(found, "count")) {
            (Value::Str(code), Value::Int(count))
                if code.as_str().is_some_and(tag_shape)
                    && count
                        .as_i64()
                        .is_some_and(|count| 0 < count && count < 1_000_000) =>
            {
                object([
                    ("code", Value::Str(code.clone())),
                    ("count", Value::Int(count.clone())),
                ])
            }
            _ => Value::Null,
        },
        _ => Value::Null,
    };
    let version = |found: &Value| match text(found) {
        Some(said) if version_shape(said) => found.clone(),
        _ => Value::Null,
    };
    let layout = version(get(map, "layout_untested"));
    let updated = version(get(map, "updated_from"));
    if [&word, &unknown, &layout, &updated]
        .iter()
        .all(|each| matches!(each, Value::Null))
    {
        return Ok(Value::Null);
    }
    Ok(object([
        ("blocked", word),
        ("unknown_error", unknown),
        ("layout_untested", layout),
        ("updated_from", updated),
    ]))
}
