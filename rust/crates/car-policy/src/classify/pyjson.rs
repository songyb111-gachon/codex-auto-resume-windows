//! `json.loads(text)` where Python reads what serde_json refuses: `NaN`, `Infinity`, `-Infinity` and a lone
//! surrogate escape. Moved here from car-store's seam (`seam/python.rs`, which re-exports it): the gates' stored
//! vector is read with it, and the store's readers of a stored column (the usage reading, the homes) too.

use car_machine::json::{ReadError, Value, from_str};

/// `json.loads(text)` for the store's three readers of a stored column (the gates, the usage reading, the
/// homes). Python reads `NaN`, `Infinity`, `-Infinity` and a lone surrogate escape, which serde refuses. Each
/// is read here as a value those readers treat exactly as Python's: the number literal as `[]` - never a
/// gate's word, a window's number or a home, as NaN and infinity are none either - and the lone surrogate as
/// U+FFFD, never one of the words they allow, as a surrogate is none either.
pub fn loads(text: &str) -> Result<Value, ReadError> {
    match from_str(text) {
        Ok(value) => Ok(value),
        Err(first) => from_str(&lenient(text)).map_err(|_| first),
    }
}

fn hex4(bytes: &[u8]) -> Option<u32> {
    let digits = bytes.get(..4)?;
    if !digits.iter().all(u8::is_ascii_hexdigit) {
        return None;
    }
    u32::from_str_radix(std::str::from_utf8(digits).ok()?, 16).ok()
}

/// The text with Python's three number literals outside strings, and lone surrogate escapes inside them,
/// written as above.
pub fn lenient(text: &str) -> String {
    let bytes = text.as_bytes();
    let mut out = String::with_capacity(text.len());
    let mut index = 0;
    let mut in_string = false;
    while index < bytes.len() {
        let rest = &text[index..];
        if in_string {
            if rest.starts_with("\\u") {
                let unit = hex4(&bytes[index + 2..]);
                let low = if bytes.get(index + 6..index + 8) == Some(b"\\u".as_slice()) {
                    hex4(&bytes[index + 8..])
                } else {
                    None
                };
                match unit {
                    Some(0xD800..=0xDBFF)
                        if low.is_some_and(|low| (0xDC00..=0xDFFF).contains(&low)) =>
                    {
                        out.push_str(&rest[..12]);
                        index += 12;
                    }
                    Some(0xD800..=0xDFFF) => {
                        out.push_str("\\ufffd");
                        index += 6;
                    }
                    _ => {
                        out.push_str("\\u");
                        index += 2;
                    }
                }
                continue;
            }
            if let Some(after) = rest.strip_prefix('\\') {
                let width = after.chars().next().map_or(0, char::len_utf8);
                out.push_str(&rest[..1 + width]);
                index += 1 + width;
                continue;
            }
            if rest.starts_with('"') {
                in_string = false;
            }
        } else if rest.starts_with('"') {
            in_string = true;
        } else if let Some(token) = ["-Infinity", "Infinity", "NaN"]
            .into_iter()
            .find(|token| rest.starts_with(token))
        {
            out.push_str("[]");
            index += token.len();
            continue;
        }
        let c = rest.chars().next().expect("not at the end");
        out.push(c);
        index += c.len_utf8();
    }
    out
}
