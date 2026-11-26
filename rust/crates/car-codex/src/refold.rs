//! What `re.IGNORECASE` and `str.casefold()` of the reference make of the paths the pairing and the queue route read.
//!
//! A `str` pattern compiled with `re.I` matches a literal character when the text's character, lowered by the simple
//! mapping (`_sre.unicode_tolower`), is the pattern's lowered character, or one of the few that `re._casefix` lists as
//! the same letter (`ı` for `i`, `ſ` for `s`, the Greek symbol forms). The lowering is the reference interpreter's
//! (car-policy's tables, Unicode 16.0, the product's Python), never Rust's own.

use car_policy::classify::text::{casefold, lower_point};

/// `re._casefix._EXTRA_CASES` (the same in 3.13.15 and 3.14.10): a lowered character and the others it matches.
const EXTRA: &[(u32, &[u32])] = &[
    (105, &[305]),
    (115, &[383]),
    (181, &[956]),
    (305, &[105]),
    (383, &[115]),
    (837, &[953, 8126]),
    (912, &[8147]),
    (944, &[8163]),
    (946, &[976]),
    (949, &[1013]),
    (952, &[977]),
    (953, &[837, 8126]),
    (954, &[1008]),
    (956, &[181]),
    (960, &[982]),
    (961, &[1009]),
    (962, &[963]),
    (963, &[962]),
    (966, &[981]),
    (976, &[946]),
    (977, &[952]),
    (981, &[966]),
    (982, &[960]),
    (1008, &[954]),
    (1009, &[961]),
    (1013, &[949]),
    (1074, &[7296]),
    (1076, &[7297]),
    (1086, &[7298]),
    (1089, &[7299]),
    (1090, &[7300, 7301]),
    (1098, &[7302]),
    (1123, &[7303]),
    (7296, &[1074]),
    (7297, &[1076]),
    (7298, &[1086]),
    (7299, &[1089]),
    (7300, &[1090, 7301]),
    (7301, &[1090, 7300]),
    (7302, &[1098]),
    (7303, &[1123]),
    (7304, &[42571]),
    (7777, &[7835]),
    (7835, &[7777]),
    (8126, &[837, 953]),
    (8147, &[912]),
    (8163, &[944]),
    (42571, &[7304]),
    (64261, &[64262]),
    (64262, &[64261]),
];

/// The simple lowercase mapping of one code point (the first of `str.lower()`'s, which differs only for `İ`).
pub fn simple_lower(point: u32) -> u32 {
    let mut out = Vec::with_capacity(2);
    lower_point(point, &mut out);
    out.first().copied().unwrap_or(point)
}

/// Whether the text's character `text` matches the pattern's literal `pattern` under `re.IGNORECASE`.
pub fn same(pattern: u32, text: u32) -> bool {
    let (p, t) = (simple_lower(pattern), simple_lower(text));
    p == t
        || EXTRA
            .binary_search_by_key(&p, |&(each, _)| each)
            .is_ok_and(|at| EXTRA[at].1.contains(&t))
}

/// The code points of a text.
pub fn points(text: &str) -> Vec<u32> {
    text.chars().map(|c| c as u32).collect()
}

/// Where the literal `literal` ends if it matches `text` at `at` under `re.IGNORECASE`.
pub fn literal(text: &[u32], at: usize, literal: &str) -> Option<usize> {
    let mut end = at;
    for c in literal.chars() {
        if !text.get(end).is_some_and(|each| same(c as u32, *each)) {
            return None;
        }
        end += 1;
    }
    Some(end)
}

/// Whether `text` is, from `at` to its end, exactly `word` under `re.IGNORECASE`.
pub fn exactly(text: &[u32], at: usize, word: &str) -> bool {
    literal(text, at, word) == Some(text.len())
}

/// `text.casefold()` as code points (a lone surrogate stays itself).
pub fn casefold_points(text: &[u32]) -> Vec<u32> {
    let mut out = Vec::with_capacity(text.len());
    for point in text {
        match char::from_u32(*point) {
            Some(c) => out.extend(casefold(&c.to_string()).chars().map(|each| each as u32)),
            None => out.push(*point),
        }
    }
    out
}

/// `text.lower()` as code points.
pub fn lower_points(text: &[u32]) -> Vec<u32> {
    let mut out = Vec::with_capacity(text.len());
    for point in text {
        lower_point(*point, &mut out);
    }
    out
}

/// Split at every backslash (`text.split("\\")`).
pub fn split(text: &[u32]) -> Vec<&[u32]> {
    text.split(|each| *each == u32::from(b'\\')).collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn ignorecase_as_python() {
        assert!(same('i' as u32, 0x130));
        assert!(same('k' as u32, 0x212A));
        assert!(same('s' as u32, 0x17F));
        assert!(!same('s' as u32, 0xDF));
        assert!(exactly(&points("CODEX.EXE"), 0, "codex.exe"));
    }
}
