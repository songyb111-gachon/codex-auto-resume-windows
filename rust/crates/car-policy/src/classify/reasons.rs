//! `reasons.py`: what each interruption category is called, and what may be said or configured about it. The
//! classifier ([`super::failures`]) decides what happened; nothing here may change that.

use car_machine::json::Value;
use car_machine::pyval::{self, Py};

use super::failures::{UNKNOWN, USAGE_LIMIT};
pub use super::vocab_gen::reasons::{ALL, RECOVERABLE};

/// One interruption category, as the product presents and configures it (`Reason`).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Reason {
    pub category: &'static str,
    pub recoverable: bool,
    pub order: u32,
    pub has_reset_time: bool,
    pub configurable: bool,
}

impl Reason {
    /// `label_key`: `reason.<category>`.
    pub fn label_key(&self) -> String {
        format!("reason.{}", self.category)
    }

    /// `standard_key`: only a recoverable category has text to send.
    pub fn standard_key(&self) -> Option<String> {
        self.recoverable
            .then(|| format!("continuation.standard.{}", self.category))
    }

    /// `detailed_key`.
    pub fn detailed_key(&self) -> Option<String> {
        self.recoverable
            .then(|| format!("continuation.detailed.{}", self.category))
    }
}

const fn reason(
    category: &'static str,
    recoverable: bool,
    order: u32,
    has_reset_time: bool,
    configurable: bool,
) -> Reason {
    Reason {
        category,
        recoverable,
        order,
        has_reset_time,
        configurable,
    }
}

/// `_ENTRIES`, in the order the Python lists them (presentation order is `order`).
pub const ENTRIES: &[Reason] = &[
    reason(USAGE_LIMIT, true, 1, true, true),
    reason("rate_limit_transient", true, 2, false, true),
    reason("network_transient", true, 3, false, true),
    reason("timeout", true, 4, false, true),
    reason("server_5xx", true, 5, false, true),
    reason("stream_interrupted", true, 6, false, true),
    reason(UNKNOWN, false, 50, false, false),
    reason("terminal_auth", false, 51, false, false),
    reason("terminal_permission", false, 52, false, false),
    reason("terminal_policy", false, 53, false, false),
    reason("terminal_user", false, 54, false, false),
    reason("terminal_invalid", false, 55, false, false),
    reason("terminal_failure", false, 56, false, false),
    reason("auth_service_transient", false, 57, false, false),
];

/// `REASONS.get(category)` of a category's text.
pub fn find(category: &str) -> Option<&'static Reason> {
    ENTRIES.iter().find(|entry| entry.category == category)
}

/// `get(category)`: the entry, falling back to `unknown`.
pub fn get(category: &str) -> &'static Reason {
    find(category)
        .or_else(|| find(UNKNOWN))
        .expect("unknown has an entry")
}

/// `get(category)` of any value: a dict lookup, so an unhashable value raises TypeError.
pub fn get_value(category: &Value) -> Py<&'static Reason> {
    pyval::hashable(category)?;
    Ok(get(pyval::text(category).unwrap_or(UNKNOWN)))
}

/// `is_recoverable(category)`.
pub fn is_recoverable(category: &Value) -> Py<bool> {
    pyval::hashable(category)?;
    Ok(pyval::text(category)
        .and_then(find)
        .is_some_and(|entry| entry.recoverable))
}

/// `label_key(category)`.
pub fn label_key(category: &Value) -> Py<String> {
    Ok(get_value(category)?.label_key())
}

/// `has_reset_time(category)`.
pub fn has_reset_time(category: &Value) -> Py<bool> {
    Ok(get_value(category)?.has_reset_time)
}

/// `configurable()`: the categories with a switch, in presentation order.
pub fn configurable() -> Vec<&'static str> {
    let mut found: Vec<&Reason> = ENTRIES.iter().filter(|entry| entry.configurable).collect();
    found.sort_by_key(|entry| entry.order);
    found.iter().map(|entry| entry.category).collect()
}
