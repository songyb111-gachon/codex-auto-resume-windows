//! What this crate takes from car-machine, held locally until S1.1 ports it there (PLAN 1.3: platform -> machine).
//!
//! TO BE REPLACED by `car_machine::domain::errors::AdapterError` and `car_machine::domain::vocabulary::StateAccess`.
//! The strings are the Python reference's own (`domain/errors.py`, `domain/vocabulary.py`); a test in
//! `tests/rustdiff/platform_diffs.py` holds the ones this crate raises to the reference's.

use std::fmt;

/// The one refusal the platform raises: a static reason code and nothing else (no transcript, no value).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct AdapterError(pub &'static str);

impl AdapterError {
    pub fn code(&self) -> &'static str {
        self.0
    }
}

impl fmt::Display for AdapterError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.0)
    }
}

impl std::error::Error for AdapterError {}

/// `StateAccess` of the reference's vocabulary: who Windows lets open the state folder.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum StateAccess {
    OwnerOnly,
    CodexSandbox,
    Shared,
    Unknown,
}

impl StateAccess {
    pub fn as_str(self) -> &'static str {
        match self {
            StateAccess::OwnerOnly => "owner_only",
            StateAccess::CodexSandbox => "codex_sandbox",
            StateAccess::Shared => "shared",
            StateAccess::Unknown => "unknown",
        }
    }
}
