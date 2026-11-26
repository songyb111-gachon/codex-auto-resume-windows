//! The edges between the P7 seats (seat S7.2a's skeleton, P7-DESIGN 2.1): every import of the tag's advanced package
//! from one seat's module into another's that is not yet ported, as one function or constant here with the reference's
//! own signature, so a seat codes against this file and the integration that merges the owner replaces the body with a
//! call into the owner's module (and then deletes the entry). Edges into modules already ported (S7.1, S7.2c, S7.3c)
//! are not here: a seat calls those modules themselves.
//!
//! Computed from the tag's import graph (`python s72a-tools/edges.py`, the list in rust/GROUNDWORK.md "Seat S7.2a"):
//!
//! | from (seat) | to (owner) | here |
//! |---|---|---|
//! | runtime (S7.2a) | engine/continued (S7.2d) | [`continued_handed`] |
//! | runtime (S7.2a) | engine/resetmessage (S7.2d) | [`reset_message_handed`] |
//! | runtime (S7.2a) | engine/chat (S7.2e1) | [`CHAT`], [`chat_watched`] |
//! | runtime (S7.2a) | engine/promptqueue (S7.2e1) | [`PROMPT_QUEUE`], [`prompt_handed`] |
//! | runtime (S7.2a) | engine/foropen (S7.2e1) | [`QUEUE_FOR_OPEN`], [`for_open_watching`] |
//! | runtime (S7.2a) | engine/sessions, engine/silent (S7.2e1) | [`OTHER_SESSIONS`], [`SILENT`] |
//! | runtime (S7.2a) | measure (S7.4) | `runtime::measurement` (S7.4's own file) |
//! | engine/account (S7.2b) | engine/resetwatch (S7.2d) | [`ResetWatch`] |
//! | engine/autoswitch (S7.2b) | engine/opentarget (S7.2e1) | [`OpenTarget`] |
//! | engine/chat, emptyreply, subagent (S7.2e1) | engine/usage (S7.2d) | [`USAGE_PAUSE`], [`EVERY_CONVERSATION`] |
//! | engine/emptyreply, keepgoing, subagent (S7.2e1) | engine/continued (S7.2d) | [`continued_handed`], [`answer_key`], [`words_pass`] |
//! | engine/anchor (S7.2e2) | engine/wrapwords (S7.2d) | [`WRAP_WORDS_ON`] |
//! | engine/retries (S7.2e1) | codex/account (S7.2b) | [`AccountReply`] |
//! | engine/opentarget (S7.2e1) | control/opencodex (S7.3a) | [`OpenCodex`] |
//! | surfaces (S7.3a) | control/courier, control/remote, courier/feed (S7.3b) | `seam_p7` entries S7.3a adds with S7.3b in wave 3 |
//! | measure, evidence (S7.4) | codex/account, authfile, restart, swap (S7.2b); engine/emptyreply, retries, subagent (S7.2e1); engine/anchor (S7.2e2) | S7.4 runs after waves 1-2: it calls the owners |
//!
//! The pure functions S7.2a's runtime needs now (`*_handed`, `chat_watched`, `for_open_watching`) are ported here,
//! faithfully, so the runtime's P2 is equal before their owners exist; the owner moves each into its module.

use car_machine::json::{Map, Value};

/// `engine/chat.CAPABILITY`.
pub const CHAT: &str = "codex_chat";
/// `engine/promptqueue.CAPABILITY`.
pub const PROMPT_QUEUE: &str = "prompt_queue";
/// `engine/foropen.CAPABILITY`.
pub const QUEUE_FOR_OPEN: &str = "queue_for_open";
/// `engine/sessions.CAPABILITY`.
pub const OTHER_SESSIONS: &str = "other_sessions";
/// `engine/silent.CAPABILITY`.
pub const SILENT: &str = "silent_continuation";
/// `engine/usage.PAUSE`.
pub const USAGE_PAUSE: &str = "usage_pause";
/// `engine/usage.EVERY_CONVERSATION`.
pub const EVERY_CONVERSATION: &str = "every_conversation";
/// `engine/wrapwords.ON`.
pub const WRAP_WORDS_ON: i64 = 1;

/// `engine/resetwatch.count(rule, row) -> int` (S7.2d), for `engine/account` (S7.2b).
pub trait ResetWatch {
    fn count(&self, rule: &Value, row: &Value) -> i64;
}

/// `engine/opentarget.idle_seconds()` (S7.2e1), for `engine/autoswitch` (S7.2b).
pub trait OpenTarget {
    fn idle_seconds(&self) -> Option<f64>;
}

/// `control/opencodex.handler_registered(read=None) -> bool` (S7.3a), for `engine/opentarget` (S7.2e1).
pub trait OpenCodex {
    fn handler_registered(&self) -> bool;
}

/// `codex/account.parse(reply) -> dict` (S7.2b), for `engine/retries` (S7.2e1).
pub trait AccountReply {
    fn parse(&self, reply: &Value) -> Value;
}

// ------------------------------------------------------------------ the pure functions S7.2a's runtime needs now

fn is(value: Option<&Value>, word: &str) -> bool {
    matches!(value, Some(Value::Str(text)) if text.as_str() == Some(word))
}

fn get<'a>(row: &'a Value, name: &str) -> Option<&'a Value> {
    match row {
        Value::Object(map) => map.get(name),
        _ => None,
    }
}

fn null(value: Option<&Value>) -> bool {
    matches!(value, None | Some(Value::Null))
}

fn or_null(value: Option<&Value>) -> Value {
    value.cloned().unwrap_or(Value::Null)
}

fn truthy(value: Option<&Value>) -> bool {
    value.is_some_and(car_machine::pyval::truthy)
}

/// `row.get(a) or row.get(b)`.
fn either(row: &Value, first: &str, second: &str) -> Value {
    match get(row, first) {
        Some(found) if car_machine::pyval::truthy(found) => found.clone(),
        _ => or_null(get(row, second)),
    }
}

fn marker(key: &Value) -> Value {
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

fn word(text: &str) -> Value {
    Value::Str(text.into())
}

/// The keys of one in flight.
fn in_flight(own: &[(&str, Value)], sent_at: Value, queue_id: Value, withdraw: bool) -> Value {
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
fn waiting(own: &[(&str, Value)], words: Value) -> Value {
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

/// `engine/continued.answer_key(*parts)` (S7.2d): 64 hex digits of what a continuation answers -
/// `sha256(json.dumps([str(part) ...], separators=(",", ":")))`.
pub fn answer_key(parts: &[String]) -> String {
    let list = Value::Array(parts.iter().map(|part| word(part)).collect());
    let options = car_machine::json::Options::new().separators(",", ":");
    let text = car_machine::json::to_string(&list, &options).unwrap_or_default();
    car_machine::hash::sha256(text.as_bytes())
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect()
}

/// `engine/continued.words_pass(words)` (S7.2d): words core sends as a continuation.
pub fn words_pass(words: &Value) -> bool {
    car_policy::classify::continuation::validate_continuation(words).is_ok()
}

/// `engine/continued.handed(row)` (S7.2d): what core is handed of one continuation - one waiting, with its words; one in
/// flight, to be watched - or None.
pub fn continued_handed(row: &Value) -> Option<Value> {
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

/// `engine/resetmessage.handed(rule)` (S7.2d): what core is handed of one message, or None.
pub fn reset_message_handed(rule: &Value) -> Option<Value> {
    let key = or_null(get(rule, "record_id"));
    let own = [
        ("record_id", key.clone()),
        ("thread_id", or_null(get(rule, "thread_id"))),
        ("marker", marker(&key)),
        ("purpose", word("message")),
        ("ordinal", Value::Null),
    ];
    if is(get(rule, "record_state"), "in_flight") {
        let sent_at = or_null(get(rule, "sent_at"));
        return Some(in_flight(
            &own,
            sent_at,
            or_null(get(rule, "queue_id")),
            truthy(get(rule, "withdraw")),
        ));
    }
    if is(get(rule, "state"), "ready")
        && is(get(rule, "record_state"), "waiting")
        && truthy(get(rule, "words"))
    {
        return Some(waiting(&own, or_null(get(rule, "words"))));
    }
    None
}

/// `engine/promptqueue.handed(row)`: what core is handed of one prompt's occurrence, or None (moved into its module by
/// S7.2e1b; the runtime's name kept).
pub use crate::engine::promptqueue::handed as prompt_handed;

/// `engine/chat.handed(row)` (S7.2e1): one message as core is handed it, marked `pause_keeps` (v0.6.23).
pub fn chat_handed(row: &Value) -> Option<Value> {
    let key = get(row, "record_id")?;
    if !matches!(key, Value::Str(text) if text.len() == 64) {
        return None;
    }
    let own = [
        ("record_id", key.clone()),
        ("thread_id", or_null(get(row, "thread_id"))),
        ("marker", marker(key)),
        ("purpose", word("message")),
        ("ordinal", Value::Null),
        ("pause_keeps", Value::Bool(true)),
    ];
    if is(get(row, "state"), "in_flight") {
        return Some(in_flight(
            &own,
            or_null(get(row, "sent_at")),
            Value::Null,
            false,
        ));
    }
    if is(get(row, "state"), "waiting") && truthy(get(row, "words")) {
        return Some(waiting(&own, or_null(get(row, "words"))));
    }
    None
}

/// `engine/chat.TAKEN_WITHIN`: how long Codex has to take a message it holds in its queue before it is taken back.
pub const TAKEN_WITHIN: f64 = 180.0;

fn number(value: Option<&Value>) -> Option<f64> {
    match value {
        Some(Value::Int(int)) => int.as_i64().map(|n| n as f64),
        Some(Value::Float(number)) => Some(*number),
        Some(Value::Bool(flag)) => Some(f64::from(u8::from(*flag))),
        _ => None,
    }
}

/// `engine/chat.paused_by_stop(row, stops)`: whether a message in flight sat in a queue usage_pause stopped.
pub fn paused_by_stop(row: &Value, stops: &[Value]) -> bool {
    stops.iter().any(|stop| {
        let ended = match (
            number(get(stop, "finished_at")),
            number(get(row, "sent_at")),
        ) {
            (Some(end), Some(sent)) => end >= sent,
            _ => false,
        };
        is(get(stop, "capability"), USAGE_PAUSE)
            && is(get(stop, "kind"), "after_reset")
            && get(stop, "thread_id") == get(row, "thread_id")
            && (null(get(stop, "finished_at")) || ended)
    })
}

/// `engine/chat.watched(row, now, stops)` (S7.2e1): a message in flight as core watches it, asked back out of Codex's
/// queue once TAKEN_WITHIN has passed - never one in a queue the forced stop paused (v0.6.26, M1).
pub fn chat_watched(row: &Value, now: f64, stops: &[Value]) -> Option<Value> {
    let mut found = chat_handed(row)?;
    let sent = number(get(&found, "sent_at"));
    if let Some(sent) = sent
        && now - sent >= TAKEN_WITHIN
        && !paused_by_stop(row, stops)
        && let Value::Object(map) = &mut found
    {
        map.insert("withdraw".into(), Value::Bool(true));
    }
    Some(found)
}

/// `engine/foropen.watching(record)`: core asks about a continuation already queued for opening (moved into its
/// module by S7.2e1b; the runtime's name kept).
pub use crate::engine::foropen::watching as for_open_watching;
