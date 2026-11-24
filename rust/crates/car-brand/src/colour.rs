//! Colour arithmetic on #RRGGBB, and nothing that decides a colour (brand/colour.py).

use crate::Py;

/// `int(text, 16)` for one channel's two characters: ASCII hex digits, a sign or a space beside one digit.
///
/// Python's `int()` also takes other scripts' decimal digits and Unicode spaces; no colour the product holds has
/// one, and a colour that did would be a mistake in the table. Here such a colour is refused (ValueError).
fn channel(part: &[char]) -> Py<i64> {
    let text: String = part.iter().collect();
    let trimmed = text.trim_matches(|c: char| matches!(c, ' ' | '\t'..='\r' | '\x1c'..='\x1f'));
    let (sign, digits) = match trimmed.strip_prefix('-') {
        Some(rest) => (-1, rest),
        None => (1, trimmed.strip_prefix('+').unwrap_or(trimmed)),
    };
    if digits.is_empty() || !digits.chars().all(|c| c.is_ascii_hexdigit()) {
        return Err("ValueError");
    }
    i64::from_str_radix(digits, 16)
        .map(|value| sign * value)
        .map_err(|_| "ValueError")
}

/// `#RRGGBB` to a byte triple (`rgb`).
pub fn rgb(value: &str) -> Py<[i64; 3]> {
    let text: Vec<char> = value.trim_start_matches('#').chars().collect();
    if text.len() != 6 {
        return Err("ValueError");
    }
    Ok([
        channel(&text[0..2])?,
        channel(&text[2..4])?,
        channel(&text[4..6])?,
    ])
}

/// `"%02X" % value`.
pub fn hex2(value: i64) -> String {
    if value < 0 {
        format!("-{:X}", value.unsigned_abs())
    } else {
        format!("{value:02X}")
    }
}

/// `"#%02X%02X%02X" % triple`.
pub fn hex(triple: [i64; 3]) -> String {
    format!("#{}{}{}", hex2(triple[0]), hex2(triple[1]), hex2(triple[2]))
}

/// `int(math.floor(x))`, with the errors math.floor raises.
fn floor_int(x: f64) -> Py<i64> {
    if x.is_nan() {
        return Err("ValueError");
    }
    if x.is_infinite() {
        return Err("OverflowError");
    }
    Ok(x.floor() as i64)
}

/// `one` moved `amount` of the way toward `other`, per channel, rounded half up (`mix`).
pub fn mix(one: &str, other: &str, amount: f64) -> Py<String> {
    let (a, b) = (rgb(one)?, rgb(other)?);
    let mut out = [0i64; 3];
    for index in 0..3 {
        out[index] = floor_int(a[index] as f64 + (b[index] - a[index]) as f64 * amount + 0.5)?;
    }
    Ok(hex(out))
}

/// Every channel times `factor`, rounded half up and held at 255: CSS `brightness()` (`brighten`).
pub fn brighten(value: &str, factor: f64) -> Py<String> {
    let channels = rgb(value)?;
    let mut out = [0i64; 3];
    for index in 0..3 {
        out[index] = floor_int(channels[index] as f64 * factor + 0.5)?.min(255);
    }
    Ok(hex(out))
}

fn linear(byte: i64) -> f64 {
    let part = byte as f64 / 255.0;
    if part <= 0.04045 {
        part / 12.92
    } else {
        ((part + 0.055) / 1.055).powf(2.4)
    }
}

/// The relative luminance WCAG measures (`luminance`).
pub fn luminance(value: &str) -> Py<f64> {
    let [red, green, blue] = rgb(value)?;
    Ok(0.2126 * linear(red) + 0.7152 * linear(green) + 0.0722 * linear(blue))
}

/// WCAG contrast ratio (`contrast`).
pub fn contrast(one: &str, other: &str) -> Py<f64> {
    let (first, second) = (luminance(one)?, luminance(other)?);
    let lighter = crate::pyfmt::max(first, second);
    let darker = crate::pyfmt::min(first, second);
    Ok((lighter + 0.05) / (darker + 0.05))
}
