//! `domain/ids.py`: every identifier the product reads or writes, and the one parser for each kind.
//!
//! Recovery is exact or it does not happen: a continuation goes to the one conversation that was interrupted,
//! named by its id, so an id is read strictly everywhere, here. The constants (the prefixes, the schema patterns)
//! are generated into [`crate::vocab_gen::domain_ids`]; the functions take the values a record holds - any JSON
//! value - and answer what the Python answers, an exception's name where it would raise.

use crate::hash;
use crate::json::{Options, Value, to_string};
use crate::pytext::{self, to_float};
use crate::pyval::{Py, text, truthy};
use crate::vocab_gen::domain_ids::{CODEX_APP_PUBLISHER, MALFORMED, MARKER_PREFIX, NOT_CANONICAL};

pub const INTERRUPTION_ID_LENGTH: usize = 64;
pub const POWER_NONCE_LENGTH: usize = 16;
pub const SHORT_MARKER_DIGITS: usize = 16;
/// The groups of a UUID's text.
const GROUPS: [usize; 5] = [8, 4, 4, 4, 12];

/// `CODEX_APP_FAMILY` (generated as a constant too): the package family every install of the Codex app shares.
pub fn codex_app_family() -> String {
    format!("OpenAI.Codex_{CODEX_APP_PUBLISHER}")
}

/// `uuid_pattern(any_case=...)`: a regular expression for a UUID's canonical text, with no anchors.
pub fn uuid_pattern(any_case: bool) -> String {
    let digit = if any_case { "[0-9a-fA-F]" } else { "[0-9a-f]" };
    GROUPS
        .iter()
        .map(|size| format!("{digit}{{{size}}}"))
        .collect::<Vec<_>>()
        .join("-")
}

/// `THREAD_ID_SCHEMA`.
pub fn thread_id_schema() -> String {
    format!("^{}$", uuid_pattern(false))
}

/// `INTERRUPTION_ID_SCHEMA`.
pub fn interruption_id_schema() -> String {
    format!("^[0-9a-fA-F]{{{INTERRUPTION_ID_LENGTH}}}$")
}

/// What `uuid.UUID(hex)` makes of `text`, as the canonical text it writes back, or `None` for its ValueError.
fn uuid_canonical(text: &str) -> Option<String> {
    let removed = text.replace("urn:", "").replace("uuid:", "");
    let stripped = removed
        .trim_matches(|c| c == '{' || c == '}')
        .replace('-', "");
    if stripped.chars().count() != 32 {
        return None;
    }
    let parsed = pytext::parse_int(&stripped, 16)?;
    let number = parsed.magnitude?;
    if parsed.negative && number != 0 {
        return None;
    }
    let hex = format!("{number:032x}");
    Some(format!(
        "{}-{}-{}-{}-{}",
        &hex[..8],
        &hex[8..12],
        &hex[12..16],
        &hex[16..20],
        &hex[20..]
    ))
}

/// `uuid_problem(value, as_text=...)`: `None` when `value` is a UUID in canonical text, otherwise `"not_canonical"`
/// for a UUID written some other way and `"malformed"` for anything else.
pub fn uuid_problem(value: &Value, as_text: bool) -> Option<&'static str> {
    let owned;
    let candidate: &str = if as_text {
        match value {
            Value::Array(_) | Value::Object(_) => return Some(MALFORMED),
            Value::Str(each) => match each.as_str() {
                Some(each) => each,
                None => return Some(MALFORMED),
            },
            other => {
                owned = pytext::py_str(other);
                &owned
            }
        }
    } else {
        match text(value) {
            Some(each) => each,
            None => return Some(MALFORMED),
        }
    };
    match uuid_canonical(candidate) {
        None => Some(MALFORMED),
        Some(canonical) if canonical == candidate => None,
        Some(_) => Some(NOT_CANONICAL),
    }
}

/// `is_uuid(value)`: a thread, turn or queue id: a `str` holding a UUID's canonical text.
pub fn is_uuid(value: &Value) -> bool {
    uuid_problem(value, false).is_none()
}

fn json_error(error: crate::json::Error) -> &'static str {
    match error {
        crate::json::Error::TooDeep => "RecursionError",
        _ => "ValueError",
    }
}

/// `hashlib.sha256(json.dumps(identity, separators=(",", ":"), allow_nan=False).encode("ascii")).hexdigest()`.
fn digest_of(identity: Vec<Value>) -> Py<String> {
    let options = Options::new().separators(",", ":");
    let written = to_string(&Value::Array(identity), &options).map_err(json_error)?;
    Ok(hash::hex(&hash::sha256(written.as_bytes())))
}

/// `interruption_id(thread_id, turn_id, completed_at, ordinal, home_key="")`: the id of a failed turn.
pub fn interruption_id(
    thread_id: &Value,
    turn_id: &Value,
    completed_at: &Value,
    ordinal: &Value,
    home_key: &Value,
) -> Py<String> {
    let moment = Value::from(pytext::float_hex(to_float(completed_at)?));
    let mut identity = vec![thread_id.clone(), turn_id.clone(), moment, ordinal.clone()];
    if truthy(home_key) {
        let mut longer = vec![Value::from("home"), home_key.clone()];
        longer.append(&mut identity);
        identity = longer;
    }
    digest_of(identity)
}

/// `stalled_id(thread_id, turn_id, home_key="")`: the key a needs-you notice about a stalled turn is kept under.
pub fn stalled_id(thread_id: &Value, turn_id: &Value, home_key: &Value) -> Py<String> {
    let identity = if truthy(home_key) {
        vec![
            Value::from("stalled"),
            home_key.clone(),
            thread_id.clone(),
            turn_id.clone(),
        ]
    } else {
        vec![Value::from("stalled"), thread_id.clone(), turn_id.clone()]
    };
    digest_of(identity)
}

fn lower_hex(each: char) -> bool {
    matches!(each, '0'..='9' | 'a'..='f')
}

/// `is_digest(value)`: 64 lowercase hex digits, with nothing around them.
pub fn is_digest(value: &Value) -> bool {
    text(value).is_some_and(|word| {
        word.chars().count() == INTERRUPTION_ID_LENGTH && word.chars().all(lower_hex)
    })
}

/// `is_interruption_id(value, as_stored=...)`.
pub fn is_interruption_id(value: &Value, as_stored: bool) -> bool {
    if as_stored {
        return text(value).is_some_and(|word| {
            (1..=128).contains(&word.chars().count())
                && word
                    .chars()
                    .all(|each| each.is_ascii_alphanumeric() || each == '_' || each == '-')
        });
    }
    is_digest(value)
}

/// `is_power_nonce(value)`: 16 lowercase hex digits.
pub fn is_power_nonce(value: &Value) -> bool {
    text(value).is_some_and(|word| {
        word.chars().count() == POWER_NONCE_LENGTH && word.chars().all(lower_hex)
    })
}

/// `read_interruption_id(text)`: the id in `text` as a person or a link hands one over, or `None`.
pub fn read_interruption_id(input: &str) -> Option<String> {
    let candidate = pytext::strip(input).to_lowercase();
    is_interruption_id(&Value::from(candidate.as_str()), false).then_some(candidate)
}

/// `marker(key)`: the prefix, the key, `]`.
pub fn marker(key: &str) -> String {
    format!("{MARKER_PREFIX}{key}]")
}

/// `short_marker(key)`: the first 16 hex digits of an id, or the whole key where it is not one.
pub fn short_marker(key: &str) -> String {
    if is_interruption_id(&Value::from(key), false) {
        marker(&key[..SHORT_MARKER_DIGITS])
    } else {
        marker(key)
    }
}

/// `record_markers(key)`: every marker a record of `key` may carry, the short one first.
pub fn record_markers(key: &str) -> Vec<String> {
    let mut found = vec![short_marker(key)];
    let whole = marker(key);
    if !found.contains(&whole) {
        found.push(whole);
    }
    found
}

/// `is_marker(value)`.
pub fn is_marker(value: &Value) -> bool {
    let Some(word) = text(value) else {
        return false;
    };
    let Some(rest) = word.strip_prefix(MARKER_PREFIX) else {
        return false;
    };
    let Some(body) = rest.strip_suffix(']') else {
        return false;
    };
    is_interruption_id(&Value::from(body), false)
        || (body.chars().count() == SHORT_MARKER_DIGITS && body.chars().all(lower_hex))
}

/// `is_client_id(value)`: 1 to 64 letters, digits and dashes.
pub fn is_client_id(value: &Value) -> bool {
    text(value).is_some_and(|word| {
        (1..=64).contains(&word.chars().count())
            && word
                .chars()
                .all(|each| each.is_ascii_alphanumeric() || each == '-')
    })
}

/// `uuid.uuid5(namespace, name)` as canonical text.
fn uuid5(namespace: [u8; 16], name: &str) -> String {
    let mut input = namespace.to_vec();
    input.extend_from_slice(name.as_bytes());
    let digest = hash::sha1(&input);
    let mut bytes = [0u8; 16];
    bytes.copy_from_slice(&digest[..16]);
    bytes[6] = (bytes[6] & 0x0f) | 0x50;
    bytes[8] = (bytes[8] & 0x3f) | 0x80;
    let hex = hash::hex(&bytes);
    format!(
        "{}-{}-{}-{}-{}",
        &hex[..8],
        &hex[8..12],
        &hex[12..16],
        &hex[16..20],
        &hex[20..]
    )
}

/// `uuid.NAMESPACE_URL`.
const NAMESPACE_URL: [u8; 16] = [
    0x6b, 0xa7, 0xb8, 0x11, 0x9d, 0xad, 0x11, 0xd1, 0x80, 0xb4, 0x00, 0xc0, 0x4f, 0xd4, 0x30, 0xc8,
];

/// `continuation_client_id(key)`: the client id a marker-free continuation of the record `key` is queued under.
pub fn continuation_client_id(key: &str) -> String {
    let namespace = uuid5(
        NAMESPACE_URL,
        "urn:codex-auto-resume:continuation-client-id",
    );
    let mut bytes = [0u8; 16];
    let hex: String = namespace.chars().filter(|c| *c != '-').collect();
    for (at, slot) in bytes.iter_mut().enumerate() {
        *slot = u8::from_str_radix(&hex[at * 2..at * 2 + 2], 16).unwrap_or(0);
    }
    uuid5(bytes, key)
}

/// `is_delivery_proof(value)`: a marker, or the canonical UUID a marker-free continuation was queued under.
pub fn is_delivery_proof(value: &Value) -> bool {
    is_marker(value) || is_uuid(value)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::json::from_str;

    fn v(text: &str) -> Value {
        from_str(text).unwrap()
    }

    #[test]
    fn uuids() {
        let good = v("\"0a1b2c3d-0001-7000-8000-000000000001\"");
        assert!(is_uuid(&good));
        assert_eq!(
            uuid_problem(&v("\"{0A1B2C3D-0001-7000-8000-000000000001}\""), false),
            Some("not_canonical")
        );
        assert_eq!(uuid_problem(&v("5"), false), Some("malformed"));
        assert_eq!(uuid_problem(&v("5"), true), Some("malformed"));
    }

    #[test]
    fn the_namespace_client_id_is_the_pythons() {
        assert_eq!(
            uuid5(NAMESPACE_URL, "python.org"),
            "7af94e2b-4dd9-50f0-9c9a-8a48519bdef0"
        );
    }

    #[test]
    fn an_interruption_id_is_sixty_four_hex_digits() {
        let id = interruption_id(
            &v("\"t\""),
            &v("\"u\""),
            &v("1.5"),
            &v("0"),
            &Value::from(""),
        )
        .unwrap();
        assert!(is_digest(&Value::from(id.as_str())));
    }
}
