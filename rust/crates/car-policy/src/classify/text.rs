//! What the classifier asks of Python's own `str`: `str.lower()` and the word characters `re`'s `\b` sees.
//!
//! Rust's `to_lowercase` and `char::is_alphanumeric` follow another Unicode version and another definition of a word
//! character (Rust counts combining marks that are Other_Alphabetic; Python's `isalnum` does not), so the answers come
//! from tables the reference interpreter itself made (`tests/rustdiff/gen_policy.py`, [`UNICODE`]).

use car_machine::json::Str;

pub use super::text_tables::UNICODE;
use super::text_tables::{FOLD, LOWER, WORD};

/// `str.lower()` of one code point, pushed onto `out`: what it becomes, or itself. (Python's context rule for a final
/// sigma, which turns a word's last `Σ` into `ς` rather than `σ`, turns no word character into a non-word one, and
/// nothing here asks more of a lowered text than its ASCII letters and its word characters.)
pub fn lower_point(point: u32, out: &mut Vec<u32>) {
    match LOWER.binary_search_by_key(&point, |&(each, _)| each) {
        Ok(at) => out.extend(LOWER[at].1.chars().map(|c| c as u32)),
        Err(_) => out.push(point),
    }
}

/// `text.lower()`, as code points (a lone surrogate stays itself).
pub fn lower(text: &Str) -> Vec<u32> {
    let mut out = Vec::with_capacity(text.len());
    for point in text.code_points() {
        lower_point(point, &mut out);
    }
    out
}

/// `text.casefold()` of a text with no lone surrogate.
pub fn casefold(text: &str) -> String {
    let mut out = String::with_capacity(text.len());
    for c in text.chars() {
        match FOLD.binary_search_by_key(&(c as u32), |&(each, _)| each) {
            Ok(at) => out.push_str(FOLD[at].1),
            Err(_) => out.push(c),
        }
    }
    out
}

/// Whether `re`'s `\w` matches this code point in a str pattern.
pub fn is_word(point: u32) -> bool {
    WORD.binary_search_by(|&(low, high)| {
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

/// `\b` at `at` in `points`: a word character on one side and not on the other (the ends count as non-word).
pub fn boundary(points: &[u32], at: usize) -> bool {
    let before = at > 0 && is_word(points[at - 1]);
    let after = at < points.len() && is_word(points[at]);
    before != after
}

/// Whether `points` holds `needle` (an ASCII text) starting at `at`.
pub fn starts_at(points: &[u32], at: usize, needle: &str) -> bool {
    let bytes = needle.as_bytes();
    at + bytes.len() <= points.len()
        && bytes
            .iter()
            .zip(&points[at..])
            .all(|(byte, point)| u32::from(*byte) == *point)
}

/// `re.search(r"\b(a|b|...)\b", text) is not None` for literal ASCII alternatives: an alternative that matches at a
/// place and fails the closing `\b` there lets the next one be tried, as the regex backtracks.
pub fn search_bounded(points: &[u32], alternatives: &[&str]) -> bool {
    (0..=points.len()).any(|at| {
        boundary(points, at)
            && alternatives
                .iter()
                .any(|each| starts_at(points, at, each) && boundary(points, at + each.len()))
    })
}

/// `needle in text` for an ASCII needle.
pub fn contains(points: &[u32], needle: &str) -> bool {
    needle.is_empty() || (0..points.len()).any(|at| starts_at(points, at, needle))
}

/// `bool(text.strip())`: a code point that is not `str.isspace()`.
pub fn has_non_space(text: &Str) -> bool {
    text.code_points()
        .any(|point| char::from_u32(point).is_none_or(|c| !car_machine::pytext::is_space(c)))
}

/// `text.strip()` of a text with no lone surrogate.
pub fn strip(text: &str) -> &str {
    car_machine::pytext::strip(text)
}
