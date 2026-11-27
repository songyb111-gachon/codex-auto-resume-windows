//! `engine/continued.py` (seat S7.2d): what the edition's own continuations share - the key one is kept under, whether
//! words pass core's check, and what core is handed of one (P2's CONTINUATION).
//!
//! S7.2a's skeleton ported these into `seam_p7` faithfully, for the runtime's P2 before this seat existed; Integration
//! 10 moved the bodies here, where the tag has them, and every caller (the runtime's P2, emptyreply, keepgoing,
//! subagent) calls this module. The keys of one waiting or in flight are shared with `engine/resetmessage.handed`.

use car_machine::json::{Map, Value};

pub(crate) fn is(value: Option<&Value>, word: &str) -> bool {
    matches!(value, Some(Value::Str(text)) if text.as_str() == Some(word))
}

pub(crate) fn get<'a>(row: &'a Value, name: &str) -> Option<&'a Value> {
    match row {
        Value::Object(map) => map.get(name),
        _ => None,
    }
}

fn null(value: Option<&Value>) -> bool {
    matches!(value, None | Some(Value::Null))
}

pub(crate) fn or_null(value: Option<&Value>) -> Value {
    value.cloned().unwrap_or(Value::Null)
}

pub(crate) fn truthy(value: Option<&Value>) -> bool {
    value.is_some_and(car_machine::pyval::truthy)
}

/// `row.get(a) or row.get(b)`.
fn either(row: &Value, first: &str, second: &str) -> Value {
    match get(row, first) {
        Some(found) if car_machine::pyval::truthy(found) => found.clone(),
        _ => or_null(get(row, second)),
    }
}

/// `short_marker(key)` of a record's key; None for one that is no text.
pub(crate) fn marker(key: &Value) -> Value {
    match key {
        Value::Str(text) => Value::Str(
            car_machine::domain::ids::short_marker(text.as_str().unwrap_or_default()).into(),
        ),
        _ => Value::Null,
    }
}

/// `dict(own, **more)`: `own`'s keys first, then the rest, a key already there replaced in its place.
fn with(own: &[(&str, Value)], more: Vec<(&str, Value)>) -> Value {
    let mut pairs: Vec<(&str, Value)> = own.to_vec();
    for (name, value) in more {
        match pairs.iter_mut().find(|(held, _)| *held == name) {
            Some(held) => held.1 = value,
            None => pairs.push((name, value)),
        }
    }
    let mut map = Map::new();
    for (name, value) in pairs {
        map.insert(name.into(), value);
    }
    Value::Object(map)
}

pub(crate) fn word(text: &str) -> Value {
    Value::Str(text.into())
}

/// The keys of one in flight.
pub(crate) fn in_flight(
    own: &[(&str, Value)],
    sent_at: Value,
    queue_id: Value,
    withdraw: bool,
) -> Value {
    with(
        own,
        vec![
            ("state", word("in_flight")),
            ("words", Value::Null),
            ("sent_at", sent_at),
            ("queue_id", queue_id),
            ("withdraw", Value::Bool(withdraw)),
        ],
    )
}

/// The keys of one waiting, with its words.
pub(crate) fn waiting(own: &[(&str, Value)], words: Value) -> Value {
    with(
        own,
        vec![
            ("state", word("waiting")),
            ("words", words),
            ("sent_at", Value::Null),
            ("queue_id", Value::Null),
            ("withdraw", Value::Bool(false)),
        ],
    )
}

/// `answer_key(*parts)`: 64 hex digits of `json.dumps([str(part) ...], separators=(",", ":"))`. Each part is written
/// as Python's `str` writes it (`str(None)` is `None`, `str(300)` is `300`).
pub fn answer_key(parts: &[Value]) -> String {
    let texts: Vec<String> = parts.iter().map(car_machine::pytext::py_str).collect();
    answer_key_text(&texts)
}

/// `answer_key(*parts)` of parts already written as `str()` writes them: `sha256(json.dumps([...], separators=(",",
/// ":")))` in hex.
pub fn answer_key_text(parts: &[String]) -> String {
    let list = Value::Array(parts.iter().map(|part| word(part)).collect());
    let options = car_machine::json::Options::new().separators(",", ":");
    let text = car_machine::json::to_string(&list, &options).unwrap_or_default();
    car_machine::hash::sha256(text.as_bytes())
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect()
}

/// `words_pass(words)`: words core sends as a continuation (`continuation.validate_continuation`).
pub fn words_pass(words: &Value) -> bool {
    car_policy::classify::continuation::validate_continuation(words).is_ok()
}

/// `handed(row)`: what core is handed of one continuation - one waiting, with its words; one in flight, to be
/// watched - or None.
pub fn handed(row: &Value) -> Option<Value> {
    let key = get(row, "record_id")?;
    if null(Some(key)) || !null(get(row, "finished_at")) {
        return None;
    }
    // A wrap-up (v0.6.16-beta.3, engine/usage.py) is core's WRAP_UP: sent only while its turn still runs.
    let purpose = if is(get(row, "kind"), "wrap_up") {
        "wrap_up"
    } else {
        "continuation"
    };
    let own = [
        ("record_id", key.clone()),
        ("thread_id", or_null(get(row, "thread_id"))),
        ("marker", marker(key)),
        ("purpose", word(purpose)),
        ("ordinal", or_null(get(row, "ordinal"))),
    ];
    if is(get(row, "record_state"), "in_flight") {
        let sent_at = either(row, "launching_at", "claimed_at");
        return Some(in_flight(
            &own,
            sent_at,
            or_null(get(row, "queue_id")),
            truthy(get(row, "withdraw")),
        ));
    }
    if is(get(row, "record_state"), "waiting") && truthy(get(row, "words")) {
        return Some(waiting(&own, or_null(get(row, "words"))));
    }
    None
}
