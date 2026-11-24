//! domain/ids.py, the parts the store reads: UUIDs, interruption ids, markers, client ids.
//!
//! SEAM, TO BE REPLACED by car-machine's ids (S1.1). Kept to the Python's rules exactly, the differences
//! named where they are.

use car_machine::json::Value;

use crate::value::text;

/// Why a value is not a UUID in canonical text (`ids.uuid_problem`).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum UuidProblem {
    /// `MALFORMED`: not a UUID at all.
    Malformed,
    /// `NOT_CANONICAL`: a UUID, written some other way than the canonical text.
    NotCanonical,
}

/// `ids.uuid_problem(value)`: None for a `str` holding a UUID's canonical text (lowercase 8-4-4-4-12).
pub fn uuid_problem(value: &Value) -> Option<UuidProblem> {
    let Some(candidate) = text(value) else {
        return Some(UuidProblem::Malformed);
    };
    if is_canonical_uuid(candidate) {
        None
    } else if parses_as_uuid(candidate) {
        Some(UuidProblem::NotCanonical)
    } else {
        Some(UuidProblem::Malformed)
    }
}

/// `ids.is_uuid(value)`.
pub fn is_uuid(value: &Value) -> bool {
    uuid_problem(value).is_none()
}

fn is_canonical_uuid(candidate: &str) -> bool {
    let bytes = candidate.as_bytes();
    bytes.len() == 36
        && bytes.iter().enumerate().all(|(index, byte)| match index {
            8 | 13 | 18 | 23 => *byte == b'-',
            _ => matches!(byte, b'0'..=b'9' | b'a'..=b'f'),
        })
}

/// Whether Python's `uuid.UUID(text)` reads `text`: "urn:" and "uuid:" taken out, braces stripped from
/// both ends, dashes taken out, then exactly 32 characters that `int(_, 16)` reads.
fn parses_as_uuid(candidate: &str) -> bool {
    let hex = candidate.replace("urn:", "").replace("uuid:", "");
    let hex = hex.trim_matches(|c| c == '{' || c == '}').replace('-', "");
    hex.chars().count() == 32 && python_int_base16(&hex)
}

/// Whether `int(text, 16)` reads `text`: white space around it, a `+`, a `0x`, digits with single
/// underscores between them. (Python also takes any Unicode decimal digit; this takes ASCII hex only.)
fn python_int_base16(text: &str) -> bool {
    let space = |c: char| c.is_whitespace() || ('\u{1c}'..='\u{1f}').contains(&c);
    let body = text.trim_matches(space);
    let body = body.strip_prefix('+').unwrap_or(body);
    let (body, prefixed) = match body.get(..2) {
        Some("0x" | "0X") => (&body[2..], true),
        _ => (body, false),
    };
    let mut digits = 0;
    let mut last_underscore = !prefixed;
    for character in body.chars() {
        if character == '_' {
            if last_underscore {
                return false;
            }
            last_underscore = true;
        } else if character.is_ascii_hexdigit() {
            digits += 1;
            last_underscore = false;
        } else {
            return false;
        }
    }
    digits > 0 && !body.ends_with('_')
}

const HEX: &[u8] = b"0123456789abcdef";

/// `ids.is_digest(value)`: 64 lowercase hex digits and nothing else.
pub fn is_digest(value: &Value) -> bool {
    text(value).is_some_and(is_digest_text)
}

/// `ids.is_digest` of a text.
pub fn is_digest_text(candidate: &str) -> bool {
    candidate.len() == 64 && candidate.bytes().all(|byte| HEX.contains(&byte))
}

/// `ids.is_interruption_id(value, as_stored=...)`: exactly 64 lowercase hex digits - or, `as_stored`,
/// what the store keeps as a key: 1 to 128 of `[A-Za-z0-9_-]`.
pub fn is_interruption_id(value: &Value, as_stored: bool) -> bool {
    match text(value) {
        Some(candidate) if as_stored => is_stored_key(candidate),
        Some(candidate) => is_digest_text(candidate),
        None => false,
    }
}

/// The store's key rule (`_STORED_KEY`).
pub fn is_stored_key(candidate: &str) -> bool {
    (1..=128).contains(&candidate.len())
        && candidate
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || byte == b'_' || byte == b'-')
}

/// The marker prefix.
pub const MARKER_PREFIX: &str = "[codex-auto-resume:";
const SHORT_MARKER_DIGITS: usize = 16;

/// `ids.marker(key)`: the marker of the whole key.
pub fn marker(key: &str) -> String {
    format!("{MARKER_PREFIX}{key}]")
}

/// `ids.short_marker(key)`: the first 16 hex digits of an interruption id, or the whole key.
pub fn short_marker(key: &str) -> String {
    if is_digest_text(key) {
        marker(&key[..SHORT_MARKER_DIGITS])
    } else {
        marker(key)
    }
}

/// `ids.record_markers(key)`: the short marker, and the whole key's when it differs.
pub fn record_markers(key: &str) -> Vec<String> {
    let short = short_marker(key);
    let whole = marker(key);
    if short == whole {
        vec![short]
    } else {
        vec![short, whole]
    }
}

/// `ids.is_client_id(value)`: 1 to 64 letters, digits and dashes.
pub fn is_client_id(value: &Value) -> bool {
    text(value).is_some_and(|candidate| {
        (1..=64).contains(&candidate.len())
            && candidate
                .bytes()
                .all(|byte| byte.is_ascii_alphanumeric() || byte == b'-')
    })
}

/// `ids.continuation_client_id(key)`: `uuid5` of the key in the product's own namespace.
pub fn continuation_client_id(key: &str) -> String {
    // uuid.NAMESPACE_URL.
    const URL: [u8; 16] = [
        0x6b, 0xa7, 0xb8, 0x11, 0x9d, 0xad, 0x11, 0xd1, 0x80, 0xb4, 0x00, 0xc0, 0x4f, 0xd4, 0x30,
        0xc8,
    ];
    let namespace = uuid5(&URL, "urn:codex-auto-resume:continuation-client-id");
    format_uuid(&uuid5(&namespace, key))
}

fn uuid5(namespace: &[u8; 16], name: &str) -> [u8; 16] {
    let mut message = namespace.to_vec();
    message.extend_from_slice(name.as_bytes());
    let digest = sha1(&message);
    let mut bytes = [0u8; 16];
    bytes.copy_from_slice(&digest[..16]);
    bytes[6] = (bytes[6] & 0x0f) | 0x50;
    bytes[8] = (bytes[8] & 0x3f) | 0x80;
    bytes
}

fn format_uuid(bytes: &[u8; 16]) -> String {
    let hex: String = bytes.iter().map(|byte| format!("{byte:02x}")).collect();
    format!(
        "{}-{}-{}-{}-{}",
        &hex[..8],
        &hex[8..12],
        &hex[12..16],
        &hex[16..20],
        &hex[20..]
    )
}

/// SHA-1 (FIPS 180-4), for `uuid5` alone: a name-based UUID is its only use, and no crate is added for it.
fn sha1(message: &[u8]) -> [u8; 20] {
    let mut state: [u32; 5] = [
        0x6745_2301,
        0xEFCD_AB89,
        0x98BA_DCFE,
        0x1032_5476,
        0xC3D2_E1F0,
    ];
    let mut padded = message.to_vec();
    padded.push(0x80);
    while padded.len() % 64 != 56 {
        padded.push(0);
    }
    padded.extend_from_slice(&((message.len() as u64) * 8).to_be_bytes());
    for block in padded.as_chunks::<64>().0 {
        let mut words = [0u32; 80];
        for (index, chunk) in block.as_chunks::<4>().0.iter().enumerate() {
            words[index] = u32::from_be_bytes([chunk[0], chunk[1], chunk[2], chunk[3]]);
        }
        for index in 16..80 {
            words[index] =
                (words[index - 3] ^ words[index - 8] ^ words[index - 14] ^ words[index - 16])
                    .rotate_left(1);
        }
        let [mut a, mut b, mut c, mut d, mut e] = state;
        for (index, word) in words.iter().enumerate() {
            let (f, k) = match index {
                0..=19 => ((b & c) | (!b & d), 0x5A82_7999),
                20..=39 => (b ^ c ^ d, 0x6ED9_EBA1),
                40..=59 => ((b & c) | (b & d) | (c & d), 0x8F1B_BCDC),
                _ => (b ^ c ^ d, 0xCA62_C1D6),
            };
            let next = a
                .rotate_left(5)
                .wrapping_add(f)
                .wrapping_add(e)
                .wrapping_add(k)
                .wrapping_add(*word);
            e = d;
            d = c;
            c = b.rotate_left(30);
            b = a;
            a = next;
        }
        for (slot, add) in state.iter_mut().zip([a, b, c, d, e]) {
            *slot = slot.wrapping_add(add);
        }
    }
    let mut digest = [0u8; 20];
    for (index, word) in state.iter().enumerate() {
        digest[index * 4..index * 4 + 4].copy_from_slice(&word.to_be_bytes());
    }
    digest
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::value::string;

    #[test]
    fn sha1_vectors() {
        let hex = |digest: [u8; 20]| {
            digest
                .iter()
                .map(|b| format!("{b:02x}"))
                .collect::<String>()
        };
        assert_eq!(
            hex(sha1(b"abc")),
            "a9993e364706816aba3e25717850c26c9cd0d89d"
        );
        assert_eq!(hex(sha1(b"")), "da39a3ee5e6b4b0d3255bfef95601890afd80709");
    }

    #[test]
    fn uuid5_matches_python() {
        // uuid.uuid5(uuid.NAMESPACE_URL, "urn:codex-auto-resume:continuation-client-id")
        // and the client id Python gives the key "ab" * 32 (python -c, v0.6.26-beta.2).
        assert_eq!(
            format_uuid(&uuid5(
                &[
                    0x6b, 0xa7, 0xb8, 0x11, 0x9d, 0xad, 0x11, 0xd1, 0x80, 0xb4, 0x00, 0xc0, 0x4f,
                    0xd4, 0x30, 0xc8
                ],
                "python.org"
            )),
            "7af94e2b-4dd9-50f0-9c9a-8a48519bdef0"
        );
        assert_eq!(
            continuation_client_id(&"ab".repeat(32)),
            "e753d85e-4193-56c4-97f0-a08614e5b7f4"
        );
    }

    #[test]
    fn uuid_problems() {
        let problem = |text: &str| uuid_problem(&string(text));
        assert_eq!(problem("0a1b2c3d-0001-7000-8000-000000000001"), None);
        assert_eq!(
            problem("0A1B2C3D-0001-7000-8000-000000000001"),
            Some(UuidProblem::NotCanonical)
        );
        assert_eq!(
            problem("{0a1b2c3d00017000-8000-000000000001}"),
            Some(UuidProblem::NotCanonical)
        );
        assert_eq!(
            problem("urn:uuid:0a1b2c3d-0001-7000-8000-000000000001"),
            Some(UuidProblem::NotCanonical)
        );
        assert_eq!(
            problem("0a1b2c3d-0001-7000-8000-00000000000g"),
            Some(UuidProblem::Malformed)
        );
        assert_eq!(problem(""), Some(UuidProblem::Malformed));
        assert_eq!(uuid_problem(&Value::Null), Some(UuidProblem::Malformed));
    }
}
