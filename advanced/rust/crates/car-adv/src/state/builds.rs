//! "A build of version N", for the advanced proxy (owner Q3 (c), the main session's call): a reference test patches
//! `state.session.SCHEMA_VERSION` (and once `session.TABLES`) to open the file as an older or newer build would - or
//! one of the opening's statements (`UPGRADE_TO_V019`, `FREE_OPTIONS`, `FREE_WORDINGS`, `MARKED`) to cut a run short -
//! and the advanced proxy hands that patch to car-adv here for the call it is made in. `prepare` reads each through
//! this module ([`version`], [`tables`], [`statements`], [`statement`]); nothing in the product sets them, so every
//! one is the compiled-in constant there (as `runtime::faults` is empty in the product).

use std::collections::BTreeMap;
use std::sync::{Mutex, PoisonError};

use super::schema;
use super::schema_gen;

type Tables = &'static [(&'static str, &'static [&'static str])];

static PATCHED: Mutex<Option<(i64, Tables)>> = Mutex::new(None);
/// The statements patched, by their name in `state.session`, each as the test wrote it (kept for the process: a test
/// build's statements are few and small, and a `&'static` list is what `prepare`'s steps hold).
static STATEMENTS: Mutex<BTreeMap<String, &'static [&'static str]>> = Mutex::new(BTreeMap::new());
static KEPT: Mutex<Vec<&'static [&'static str]>> = Mutex::new(Vec::new());

fn kept(found: Vec<String>) -> &'static [&'static str] {
    let mut held = KEPT.lock().unwrap_or_else(PoisonError::into_inner);
    if let Some(same) = held
        .iter()
        .find(|each| each.len() == found.len() && each.iter().zip(&found).all(|(a, b)| *a == b))
    {
        return same;
    }
    let made: Vec<&'static str> = found
        .into_iter()
        .map(|each| &*Box::leak(each.into_boxed_str()))
        .collect();
    let made: &'static [&'static str] = Box::leak(made.into_boxed_slice());
    held.push(made);
    made
}

/// From now on these statements are the test's (by name), and every other one this build's own.
pub fn set_statements(found: Vec<(String, Vec<String>)>) {
    let made = found
        .into_iter()
        .map(|(name, statements)| (name, kept(statements)))
        .collect();
    *STATEMENTS.lock().unwrap_or_else(PoisonError::into_inner) = made;
}

/// `session.<name>`, a tuple of statements: this build's `built`, unless a test patched it.
pub fn statements(name: &str, built: &'static [&'static str]) -> &'static [&'static str] {
    STATEMENTS
        .lock()
        .unwrap_or_else(PoisonError::into_inner)
        .get(name)
        .copied()
        .unwrap_or(built)
}

/// `session.<name>`, one statement: this build's `built`, unless a test patched it.
pub fn statement(name: &str, built: &'static str) -> &'static str {
    STATEMENTS
        .lock()
        .unwrap_or_else(PoisonError::into_inner)
        .get(name)
        .and_then(|found| found.first().copied())
        .unwrap_or(built)
}

/// The tables of the version a reference test names (its `schema.<NAME>`), or `None` for a name not known.
pub fn tables_named(name: &str) -> Option<Tables> {
    Some(match name {
        "TABLES" => schema::TABLES,
        "TABLES_V1" => schema_gen::TABLES_V1,
        "TABLES_V2" => schema_gen::TABLES_V2,
        "TABLES_V3_BEFORE_RESETS" => schema_gen::TABLES_V3_BEFORE_RESETS,
        "TABLES_V3" => schema_gen::TABLES_V3,
        "TABLES_V4" => schema_gen::TABLES_V4,
        "TABLES_V5" => schema_gen::TABLES_V5,
        "TABLES_BEFORE_STAGE4" => schema_gen::TABLES_BEFORE_STAGE4,
        "TABLES_V7" => schema_gen::TABLES_V7,
        "TABLES_V8" => schema_gen::TABLES_V8,
        _ => return None,
    })
}

/// From now on a file is held to `version` and `tables` (`Some`), or to this build's own again (`None`).
pub fn set(patched: Option<(i64, Tables)>) {
    *PATCHED.lock().unwrap_or_else(PoisonError::into_inner) = patched;
}

/// `session.SCHEMA_VERSION`: this build's, unless a test patched it.
pub fn version() -> i64 {
    PATCHED
        .lock()
        .unwrap_or_else(PoisonError::into_inner)
        .map_or(schema::SCHEMA_VERSION, |(version, _)| version)
}

/// `session.TABLES`: this build's, unless a test patched it.
pub fn tables() -> Tables {
    PATCHED
        .lock()
        .unwrap_or_else(PoisonError::into_inner)
        .map_or(schema::TABLES, |(_, tables)| tables)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn unpatched_is_this_build() {
        assert_eq!(version(), schema::SCHEMA_VERSION);
        assert_eq!(tables(), schema::TABLES);
        assert!(tables_named("TABLES_V7").is_some());
        assert!(tables_named("NOPE").is_none());
        assert_eq!(statements("NOT_PATCHED", &["a"]), &["a"]);
        assert_eq!(statement("NOT_PATCHED", "b"), "b");
    }
}
