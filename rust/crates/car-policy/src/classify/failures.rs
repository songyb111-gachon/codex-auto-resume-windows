//! `failures.py`: a failed Codex turn classified into one recovery category, from the structured values Codex
//! writes; a message is read only where there is no structured code at all, for a short list of transport failures.
//!
//! An error this cannot place is `unknown`, and `unknown` is never retried. No error text leaves here: a category, or
//! the error's shape (its code, a status, its form, whether it had a message), never the message.

use car_machine::json::{Map, Str, Value};
use car_machine::pyval::{self, Py};

use super::text;
use super::value::{Row, dict_get, get, in_set, object, truthy};
pub use super::vocab_gen::failures::{
    ADMISSIBLE, CATEGORIES, CONTEXT_FULL, DECISION_FRAGMENTS, RESERVED, TERMINAL, TRANSIENT,
    UNKNOWN, USAGE_LIMIT,
};
use crate::plug::vocab_gen::domain_plug::TAKE_UP;
use crate::plug::{Alternative, FailureForm, paced_as};

/// `CODES`: the `CodexErrorInfo` variants this engine build defines, and the category each is.
pub const CODES: &[(&str, &str)] = &[
    ("usageLimitExceeded", USAGE_LIMIT),
    ("rateLimitExceeded", "rate_limit_transient"),
    ("serverOverloaded", "server_5xx"),
    ("internalServerError", "server_5xx"),
    ("httpConnectionFailed", "network_transient"),
    ("responseStreamConnectionFailed", "stream_interrupted"),
    ("responseStreamDisconnected", "stream_interrupted"),
    ("contextWindowExceeded", "terminal_invalid"),
    ("sessionBudgetExceeded", "terminal_invalid"),
    ("badRequest", "terminal_invalid"),
    ("cyberPolicy", "terminal_policy"),
    ("misalignmentPolicyViolation", "terminal_policy"),
    ("unauthorized", "terminal_auth"),
    ("responseTooManyFailedAttempts", "terminal_failure"),
    ("threadRollbackFailed", "terminal_failure"),
    ("sandboxError", "terminal_failure"),
    ("activeTurnNotSteerable", "terminal_failure"),
];

/// Keys a tagged-enum payload may use to name its variant.
const TAG_KEYS: &[&str] = &["type", "kind", "tag", "variant", "code"];
const STATUS_KEYS: &[&str] = &[
    "httpStatusCode",
    "http_status_code",
    "status",
    "statusCode",
    "status_code",
];

/// `_MESSAGE_PATTERNS`: consulted only when no structured code exists; each `\b(...)\b` over the lowered message.
const MESSAGE_PATTERNS: &[(&[&str], &str)] = &[
    (&["deadline exceeded", "timed out", "timeout"], "timeout"),
    (
        &[
            "connection reset",
            "connection refused",
            "connection closed",
            "broken pipe",
        ],
        "network_transient",
    ),
    (
        &[
            "name resolution",
            "dns error",
            "dns failure",
            "temporary failure in name resolution",
        ],
        "network_transient",
    ),
    (&["tls handshake", "handshake failed"], "network_transient"),
    (
        &[
            "stream disconnected",
            "stream ended unexpectedly",
            "incomplete stream",
        ],
        "stream_interrupted",
    ),
];

/// `_RETRY_AFTER_KEYS`.
const RETRY_AFTER_KEYS: &[&str] = &[
    "retryAfterSeconds",
    "retry_after_seconds",
    "retryAfter",
    "retry_after",
];
/// `MAX_RETRY_AFTER`: a day.
pub const MAX_RETRY_AFTER: i64 = 86400;

/// `CODES.get(tag)`.
pub fn code_category(tag: &str) -> Option<&'static str> {
    CODES
        .iter()
        .find(|(code, _)| *code == tag)
        .map(|(_, category)| *category)
}

fn is_code(tag: &Str) -> bool {
    tag.as_str().is_some_and(|tag| code_category(tag).is_some())
}

/// `type(value) is int` and its value as Python compares it.
fn int_status(value: &Value) -> Option<i128> {
    match value {
        Value::Int(number) => Some(number.to_string().parse::<i128>().unwrap_or(i128::MAX)),
        _ => None,
    }
}

/// `_tag_and_status(info)`: a bare variant name, or a tagged object with a payload. The status is `type(x) is int`
/// (as i128; an int past it compares as past every status).
fn tag_and_status(info: &Value) -> (Option<Str>, Option<i128>) {
    let map = match info {
        Value::Str(tag) => return (Some(tag.clone()), None),
        Value::Object(map) => map,
        _ => return (None, None),
    };
    let mut tag = None;
    for key in TAG_KEYS {
        if let Some(Value::Str(value)) = map.get(*key)
            && !value.is_empty()
        {
            tag = Some(value.clone());
            break;
        }
    }
    let mut info: &Map = map;
    static EMPTY: std::sync::LazyLock<Map> = std::sync::LazyLock::new(Map::new);
    if tag.is_none() && map.len() == 1 {
        let (key, payload) = map.iter().next().expect("one item");
        tag = Some(key.clone());
        if let Some(status) = int_status(payload) {
            return (tag, Some(status));
        }
        info = match payload {
            Value::Object(inner) => inner,
            _ => &EMPTY,
        };
    }
    let status = STATUS_KEYS
        .iter()
        .find_map(|key| info.get(*key).and_then(int_status));
    (tag, status)
}

fn status_category(status: i128) -> &'static str {
    match status {
        408 | 425 => "timeout",
        429 => "rate_limit_transient",
        500..=599 => "server_5xx",
        401 | 403 => "terminal_auth",
        400..=499 => "terminal_invalid",
        _ => UNKNOWN,
    }
}

/// `classify(error_info, message)`: exactly one category name. Never raises, never returns error text.
pub fn classify(info: &Value, message: &Value) -> &'static str {
    let (tag, status) = tag_and_status(info);
    if tag.as_ref().and_then(Str::as_str) == Some("responseTooManyFailedAttempts")
        && status == Some(429)
    {
        return "rate_limit_transient";
    }
    if let Some(tag) = tag {
        if let Some(category) = tag.as_str().and_then(code_category) {
            return category;
        }
        return status.map_or(UNKNOWN, status_category);
    }
    if let Some(status) = status {
        return status_category(status);
    }
    if !matches!(info, Value::Null) {
        return UNKNOWN;
    }
    if let Value::Str(message) = message {
        let length = message.len();
        if 0 < length && length <= 4096 {
            let lowered = text::lower(message);
            for (alternatives, category) in MESSAGE_PATTERNS {
                if text::search_bounded(&lowered, alternatives) {
                    return category;
                }
            }
        }
    }
    UNKNOWN
}

/// `wait_seconds(value)`: whole seconds from 1 to a day, or None.
pub fn wait_seconds(value: &Value) -> Option<i64> {
    match value {
        Value::Int(number) => number
            .as_i64()
            .filter(|seconds| (1..=MAX_RETRY_AFTER).contains(seconds)),
        _ => None,
    }
}

/// `retry_after(error_info)`: the wait a structured error names, in its variant's own payload, or None.
pub fn retry_after(info: &Value) -> Option<i64> {
    let mut payload = info;
    if let Value::Object(map) = info
        && map.len() == 1
        && !TAG_KEYS.iter().any(|key| map.contains_key(*key))
    {
        payload = map.values().next().expect("one item");
    }
    let Value::Object(payload) = payload else {
        return None;
    };
    RETRY_AFTER_KEYS
        .iter()
        .find_map(|key| wait_seconds(get(payload, key)))
}

/// `is_recoverable(category)`: a usage limit, or a temporary kind.
pub fn is_recoverable(category: &str) -> bool {
    category == USAGE_LIMIT || TRANSIENT.contains(&category)
}

/// `is_recoverable(category)` of any value: an unhashable one raises TypeError, as `in TRANSIENT` does.
pub fn is_recoverable_value(category: &Value) -> Py<bool> {
    if pyval::is(category, USAGE_LIMIT) {
        return Ok(true);
    }
    in_set(category, TRANSIENT)
}

/// `TAG_SHAPE.fullmatch(code)`: a letter, then up to 63 letters and digits, ASCII.
pub fn tag_shape(code: &str) -> bool {
    let bytes = code.as_bytes();
    !bytes.is_empty()
        && bytes.len() <= 64
        && bytes[0].is_ascii_alphabetic()
        && bytes.iter().all(u8::is_ascii_alphanumeric)
}

fn tag_shape_str(code: &Str) -> bool {
    code.as_str().is_some_and(tag_shape)
}

/// `decision_tag(code)`: whether a code may name a decision of a person's (a fragment of DECISION_FRAGMENTS in it,
/// ignoring case).
pub fn decision_tag(code: &Value) -> bool {
    let Value::Str(code) = code else {
        return false;
    };
    let lowered = text::lower(code);
    DECISION_FRAGMENTS
        .iter()
        .any(|fragment| text::contains(&lowered, fragment))
}

/// `shape(error_info, message)`: `{code, status, form, has_message}`.
pub fn shape(info: &Value, message: &Value) -> Value {
    let has_message = matches!(message, Value::Str(text) if text::has_non_space(text));
    let (mut tag, status) = tag_and_status(info);
    let status = status.filter(|status| (100..=599).contains(status));
    if tag
        .as_ref()
        .is_some_and(|tag| tag.as_str().is_some_and(|tag| STATUS_KEYS.contains(&tag)))
    {
        tag = None;
    }
    let (form, code) = if matches!(info, Value::Null) {
        (
            if has_message {
                FailureForm::MessageOnly.as_str()
            } else {
                FailureForm::Absent.as_str()
            },
            Value::Null,
        )
    } else if let Some(tag) = tag
        .as_ref()
        .filter(|tag| is_code(tag) || tag_shape_str(tag))
    {
        (FailureForm::Tagged.as_str(), Value::Str(tag.clone()))
    } else if tag.is_none() && status.is_some() {
        (FailureForm::StatusOnly.as_str(), Value::Null)
    } else {
        (FailureForm::Unrecognised.as_str(), Value::Null)
    };
    object([
        ("code", code),
        (
            "status",
            status.map_or(Value::Null, |status| Value::from(status as i64)),
        ),
        ("form", Value::from(form)),
        ("has_message", Value::Bool(has_message)),
    ])
}

/// `unknown_code(entry)`: the code of a failure classified unknown whose structured error is tagged with a code
/// outside CODES, or None. `entry` is one of `latest_failures`' with its `shape`.
pub fn unknown_code(entry: &Value) -> Py<Value> {
    let facts = match entry {
        Value::Object(map) => get(map, "shape"),
        _ => return Ok(Value::Null),
    };
    let Value::Object(facts) = facts else {
        return Ok(Value::Null);
    };
    if !pyval::is(dict_get(entry, "category")?, UNKNOWN)
        || !pyval::is(get(facts, "form"), FailureForm::Tagged.as_str())
    {
        return Ok(Value::Null);
    }
    Ok(match get(facts, "code") {
        Value::Str(code) if !is_code(code) && tag_shape_str(code) => Value::Str(code.clone()),
        _ => Value::Null,
    })
}

/// `400 <= status <= 499` of a value: a number by value, anything else TypeError.
fn status_between(status: &Value, low: i64, high: i64) -> Py<bool> {
    Ok(pyval::less_or_equal(&Value::from(low), status)?
        && pyval::less_or_equal(status, &Value::from(high))?)
}

/// `_plain_code(facts)`: a code of Codex's this product does not know, naming no decision, and no 4xx beside it.
fn plain_code(facts: &Value, status: &Value) -> Py<bool> {
    let code = dict_get(facts, "code")?;
    if !pyval::is(dict_get(facts, "form")?, FailureForm::Tagged.as_str()) {
        return Ok(false);
    }
    let Value::Str(code_text) = code else {
        return Ok(false);
    };
    if is_code(code_text) || decision_tag(code) {
        return Ok(false);
    }
    Ok(matches!(status, Value::Null) || !status_between(status, 400, 499)?)
}

/// `answer in PACED_AS`: a dict's key test, which hashes `answer`.
fn paced(answer: &Value) -> Py<Option<&'static str>> {
    pyval::hashable(answer)?;
    Ok(super::value::text(answer).and_then(|word| Alternative::parse(word).and_then(paced_as)))
}

/// `admits(facts, answer)`: whether core would carry out `answer` for the failure `facts` describe (a category and
/// its `shape`), whatever a plug says.
pub fn admits(facts: &Value, answer: &Value) -> Py<bool> {
    let category = dict_get(facts, "category")?;
    let code = dict_get(facts, "code")?;
    let status = dict_get(facts, "status")?;
    if pyval::is(answer, Alternative::Capacity.as_str()) {
        return Ok(pyval::is(category, "server_5xx") && pyval::is(code, "serverOverloaded"));
    }
    if paced(answer)?.is_some() {
        return Ok(pyval::is(category, UNKNOWN) && plain_code(facts, status)?);
    }
    if !pyval::is(answer, Alternative::Admit.as_str()) {
        return Ok(false);
    }
    if pyval::is(category, "terminal_invalid") {
        return Ok(pyval::is(code, CONTEXT_FULL));
    }
    if pyval::is(category, UNKNOWN) {
        return plain_code(facts, status);
    }
    if pyval::is(category, "terminal_auth") && pyval::is(code, "unauthorized") {
        return Ok(matches!(status, Value::Null) || pyval::eq(status, &Value::from(401)));
    }
    if pyval::is(category, "terminal_auth") {
        return Ok(plain_code(facts, &Value::Null)? && pyval::eq(status, &Value::from(401)));
    }
    if pyval::is(category, "terminal_failure") {
        return Ok(pyval::is(code, "responseTooManyFailedAttempts")
            && (matches!(status, Value::Null) || status_between(status, 500, 599)?));
    }
    Ok(false)
}

/// `_FOLLOWS`: the kind whose switch in Settings each relaxation follows.
fn follows(answer: &str) -> Option<&'static str> {
    if answer == Alternative::Capacity.as_str() {
        return Some("server_5xx");
    }
    Alternative::parse(answer).and_then(paced_as)
}

/// `takes(facts, recovers)`: the answers core would carry out for this failure now, sorted (a frozenset).
pub fn takes(facts: &Value, recovers: &dyn Fn(&str) -> bool) -> Py<Vec<&'static str>> {
    let mut found = Vec::new();
    for answer in TAKE_UP {
        if admits(facts, &Value::from(*answer))? && follows(answer).is_none_or(recovers) {
            found.push(*answer);
        }
    }
    Ok(found)
}

/// `readmits(category, answer)`: whether known_failure (P3) takes `answer` for a record of `category` that P17 took up.
pub fn readmits(category: &Value, answer: &Value) -> Py<bool> {
    if pyval::is(answer, Alternative::Admit.as_str()) {
        return in_set(category, ADMISSIBLE);
    }
    if pyval::is(answer, Alternative::Capacity.as_str()) {
        return Ok(pyval::is(category, "server_5xx"));
    }
    Ok(paced(answer)?.is_some() && pyval::is(category, UNKNOWN))
}

/// `reset_verified(row, now)` of a stored record (the store's call): a usage limit whose recorded reset is behind `now`.
pub fn reset_verified(row: &Row, now: f64) -> bool {
    let reset = get(row, "reset_at");
    pyval::is(get(row, "category"), USAGE_LIMIT)
        && matches!(reset, Value::Int(_) | Value::Float(_))
        && pyval::less_or_equal(reset, &Value::Float(now)).unwrap_or(false)
}

/// `reset_verified(row, now)` of any value: `reset <= now` as Python compares it (a TypeError for a `now` no number).
pub fn reset_verified_value(row: &Value, now: &Value) -> Py<bool> {
    let Value::Object(map) = row else {
        return Ok(false);
    };
    if !pyval::is(get(map, "category"), USAGE_LIMIT) {
        return Ok(false);
    }
    let reset = get(map, "reset_at");
    if !matches!(reset, Value::Int(_) | Value::Float(_)) {
        return Ok(false);
    }
    pyval::less_or_equal(reset, now)
}

/// `reset_carried(relaxed, channel)`: a verified reset's ("reset") only where the plug's own channel carries it.
pub fn reset_carried(relaxed: &Value, channel: &Value) -> Value {
    if pyval::is(relaxed, "reset") && !truthy(channel) {
        Value::Null
    } else {
        relaxed.clone()
    }
}
