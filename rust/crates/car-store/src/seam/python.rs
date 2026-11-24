//! The few readings of text the store makes the way CPython makes them, where Rust's own would refuse more:
//! `int(text, 16)`, `float(text)`, `str.split()` and `json.loads`.
//!
//! SEAM, TO BE REPLACED by car-machine's readers (S1.1) where it grows them. Each item names the CPython rule
//! it keeps; the Unicode table is the bundled Python's (3.13, Unicode 15.1), generated with
//! `unicodedata.decimal`, and tests/rustdiff/diffs_store.py (PythonTextDiff) holds the readings to the reference.

use car_machine::json::{ReadError, Value, from_str};

/// The code point of each Unicode decimal digit zero; every decimal digit is one of these plus 0 to 9
/// (`[c for c in range(0x110000) if unicodedata.decimal(chr(c), None) == 0]`, 68 of them).
const DECIMAL_ZEROS: &[u32] = &[
    0x30, 0x660, 0x6F0, 0x7C0, 0x966, 0x9E6, 0xA66, 0xAE6, 0xB66, 0xBE6, 0xC66, 0xCE6, 0xD66,
    0xDE6, 0xE50, 0xED0, 0xF20, 0x1040, 0x1090, 0x17E0, 0x1810, 0x1946, 0x19D0, 0x1A80, 0x1A90,
    0x1B50, 0x1BB0, 0x1C40, 0x1C50, 0xA620, 0xA8D0, 0xA900, 0xA9D0, 0xA9F0, 0xAA50, 0xABF0, 0xFF10,
    0x104A0, 0x10D30, 0x11066, 0x110F0, 0x11136, 0x111D0, 0x112F0, 0x11450, 0x114D0, 0x11650,
    0x116C0, 0x11730, 0x118E0, 0x11950, 0x11C50, 0x11D50, 0x11DA0, 0x11F50, 0x16A60, 0x16AC0,
    0x16B50, 0x1D7CE, 0x1D7D8, 0x1D7E2, 0x1D7EC, 0x1D7F6, 0x1E140, 0x1E2F0, 0x1E4F0, 0x1E950,
    0x1FBF0,
];

/// `unicodedata.decimal(c)`: the value of a Unicode decimal digit, or None.
pub fn decimal(c: char) -> Option<u32> {
    let point = c as u32;
    DECIMAL_ZEROS
        .iter()
        .find(|zero| (**zero..**zero + 10).contains(&point))
        .map(|zero| point - zero)
}

/// `str.isspace()`: Unicode's White_Space and the four ASCII separators U+001C to U+001F.
pub fn is_space(c: char) -> bool {
    c.is_whitespace() || ('\u{1c}'..='\u{1f}').contains(&c)
}

/// `str.split()` with no argument.
pub fn split(text: &str) -> Vec<&str> {
    text.split(is_space)
        .filter(|word| !word.is_empty())
        .collect()
}

/// `_PyUnicode_TransformDecimalAndSpaceToASCII`: what `int()` and `float()` read a str as - each Unicode
/// decimal digit its ASCII digit, each white space a space - or None where another non-ASCII character is.
fn ascii_form(text: &str) -> Option<String> {
    text.chars()
        .map(|c| {
            if is_space(c) {
                Some(' ')
            } else if c.is_ascii() {
                Some(c)
            } else {
                decimal(c).and_then(|value| char::from_digit(value, 10))
            }
        })
        .collect()
}

/// Whether `int(text, 16)` reads `text`: white space around it, a sign, a `0x`, hex digits with single
/// underscores between them (and one may follow the prefix).
pub fn int_base16(text: &str) -> bool {
    let Some(form) = ascii_form(text) else {
        return false;
    };
    let body = form.trim_matches(' ');
    let body = body.strip_prefix(['+', '-']).unwrap_or(body);
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

/// `float(text)`: the ASCII form stripped, an underscore taken out where it stands between two digits.
pub fn float(text: &str) -> Option<f64> {
    let form = ascii_form(text)?;
    let body = form.trim_matches(' ');
    let bytes = body.as_bytes();
    for (index, byte) in bytes.iter().enumerate() {
        if *byte == b'_' {
            let before = index.checked_sub(1).map(|i| bytes[i]);
            let after = bytes.get(index + 1).copied();
            if !before.is_some_and(|b| b.is_ascii_digit())
                || !after.is_some_and(|b| b.is_ascii_digit())
            {
                return None;
            }
        }
    }
    let body: String = body.chars().filter(|c| *c != '_').collect();
    if body.is_empty() || body.contains(' ') {
        return None;
    }
    body.parse::<f64>().ok()
}

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
fn lenient(text: &str) -> String {
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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn readings() {
        assert_eq!(decimal('\u{0660}'), Some(0));
        assert_eq!(decimal('\u{0669}'), Some(9));
        assert_eq!(decimal('a'), None);
        assert!(int_base16("\u{0660}a1b2c3d000170008000000000000001"));
        assert!(int_base16(" 0x_1f "));
        assert!(!int_base16("1__f"));
        assert_eq!(float("1_700_000_148.5"), Some(1_700_000_148.5));
        assert_eq!(float(" 12\n"), Some(12.0));
        assert_eq!(float("1__0"), None);
        assert_eq!(float("_1"), None);
        assert_eq!(split("1.5\u{1c}rescan"), vec!["1.5", "rescan"]);
        let u = concat!('\\', "u");
        let given = format!(
            "{{\"a\":NaN,\"b\":\"{u}d800x\",\"c\":\"{u}d83d{u}de00\",\"d\":-Infinity,\"e\":\"NaN\"}}"
        );
        let wanted = format!(
            "{{\"a\":[],\"b\":\"{u}fffdx\",\"c\":\"{u}d83d{u}de00\",\"d\":[],\"e\":\"NaN\"}}"
        );
        assert_eq!(lenient(&given), wanted);
        assert!(loads(r#"{"consent":["WAIT","paused"],"x":NaN}"#).is_ok());
    }
}
