//! `standards.py`: the standards a capability may say it departs from - every id the standards file numbers.
//!
//! `FAMILIES` is generated (`standards_gen.rs`); the ids, the binding family and what a capability may name are made
//! from it as the tag's module makes them.

use std::collections::HashSet;
use std::sync::OnceLock;

pub use crate::standards_gen::FAMILIES;

/// Repository-relative: the standards file the registry's test reads these ids from.
pub const BASIS: &str = "docs/STANDARDS.md";
/// The families a capability may not name: family K is the advanced edition's own rules, which every one keeps.
pub const BINDING: &[&str] = &["K"];

/// `STANDARDS`: every id, family by family, each numbered from 1.
pub fn standards() -> &'static [String] {
    static ALL: OnceLock<Vec<String>> = OnceLock::new();
    ALL.get_or_init(|| {
        FAMILIES
            .iter()
            .flat_map(|(prefix, count)| (1..=*count).map(move |number| format!("{prefix}{number}")))
            .collect()
    })
}

/// `DEPARTABLE`: every standard but the binding families'.
pub fn departable() -> &'static [String] {
    static SOME: OnceLock<Vec<String>> = OnceLock::new();
    SOME.get_or_init(|| {
        standards()
            .iter()
            .filter(|standard| !BINDING.contains(&&standard[..1]))
            .cloned()
            .collect()
    })
}

/// `DECLARABLE`: what a capability may name (K5 was here from 2026-11-06 to 2026-11-10; the rule itself was amended).
pub fn declarable() -> &'static [String] {
    departable()
}

/// `set(DECLARABLE)`, for the registry's subset test.
pub fn declarable_set() -> &'static HashSet<&'static str> {
    static SET: OnceLock<HashSet<&'static str>> = OnceLock::new();
    SET.get_or_init(|| declarable().iter().map(String::as_str).collect())
}
