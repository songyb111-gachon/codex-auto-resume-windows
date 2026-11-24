//! `codex/labels.py`: the name a person would recognise a conversation by, cut to a length.
//!
//! Only ever shown back to the person whose conversation it is: a label never leaves the machine, and never
//! reaches a log. `str.isprintable` is Python's own Unicode answer, a table made from the reference interpreter
//! (`tests/rustdiff/gen_codex.py`).

use car_machine::json::{Str, Value};
use car_machine::pytext;

use crate::printable_gen::PRINTABLE;

pub const MAX_LABEL_CHARS: usize = 72;

/// `str.isprintable()` of one code point.
pub fn is_printable(point: u32) -> bool {
    PRINTABLE
        .binary_search_by(|&(low, high)| {
            if point < low {
                std::cmp::Ordering::Greater
            } else if point > high {
                std::cmp::Ordering::Less
            } else {
                std::cmp::Ordering::Equal
            }
        })
        .is_ok()
}

/// `_label(value)`: a display label, or None. Never a paragraph, never multi-line.
///
/// A defensive cap: if a future schema starts putting prompt-like text in the field this reads, a long or
/// multi-line value is dropped rather than shown. Control characters are stripped so a label can never rearrange a
/// notification.
pub fn label(value: &Value) -> Option<String> {
    let Value::Str(text) = value else {
        return None;
    };
    label_of(text)
}

pub fn label_of(text: &Str) -> Option<String> {
    let kept: String = text
        .code_points()
        .filter(|point| is_printable(*point))
        .filter_map(char::from_u32)
        .collect();
    let cleaned = pytext::strip(&kept);
    if cleaned.is_empty()
        || text
            .code_points()
            .any(|point| matches!(point, 0x0A | 0x0D | 0x09))
    {
        return None;
    }
    let characters: Vec<char> = cleaned.chars().collect();
    if characters.len() > MAX_LABEL_CHARS {
        let cut: String = characters[..MAX_LABEL_CHARS - 1].iter().collect();
        let trimmed = cut.trim_end_matches(pytext::is_space);
        return Some(format!("{trimmed}\u{2026}"));
    }
    Some(cleaned.to_owned())
}
