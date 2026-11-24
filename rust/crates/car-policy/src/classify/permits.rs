//! `compat/permits.py`: what may be done at a tier, and with whose word (v0.6.11's opt-in gate). Never raises, and
//! UNKNOWN is never permission: anything Python would raise on is answered `(False, "unknown")`.

use car_machine::json::Value;
use car_machine::pyval;
use car_machine::vocab_gen::compat_model::{STATES, TIERS};

use super::value::{in_tuple, truthy};
pub use super::vocab_gen::compat_permits::PERMIT_REASONS;

const UNKNOWN: &str = "UNKNOWN";

/// `(x or {})` of a value, then `.get(key)`: a truthy value that is no dict raises (AttributeError), and so does an
/// unhashable key.
fn or_get<'a>(value: &'a Value, key: &Value) -> Option<&'a Value> {
    static NULL: Value = Value::Null;
    pyval::hashable(key).ok()?;
    match value {
        Value::Object(map) => Some(
            pyval::text(key)
                .and_then(|key| map.get(key))
                .unwrap_or(&NULL),
        ),
        other if !truthy(other) => Some(&NULL),
        _ => None,
    }
}

/// `permits(view, capability, tier=, opt_in=, engine_version=, acknowledged_version=)`: (allowed, reason).
pub fn permits(
    view: &Value,
    capability: &Value,
    tier: &Value,
    opt_in: &Value,
    engine_version: &Value,
    acknowledged_version: &Value,
) -> (bool, &'static str) {
    let answer = || -> Option<(bool, &'static str)> {
        let entry = match view {
            Value::Object(map) => {
                or_get(map.get("capabilities").unwrap_or(&Value::Null), capability)?
            }
            _ => &Value::Null,
        };
        let mut state = match entry {
            Value::Object(entry) => entry.get("state").cloned().unwrap_or(Value::Null),
            _ => Value::from(UNKNOWN),
        };
        if !in_tuple(&state, STATES) {
            state = Value::from(UNKNOWN);
        }
        if !in_tuple(tier, TIERS) || pyval::is(tier, "unsupported") {
            return Some((false, "unsupported_tier"));
        }
        if in_tuple(&state, &["INCOMPATIBLE", "FAILED_HERE"]) {
            return Some((false, "incompatible"));
        }
        if pyval::is(&state, UNKNOWN) {
            return Some((false, "unknown"));
        }
        if pyval::is(tier, "conservative") {
            return Some((true, "allowed"));
        }
        if !matches!(opt_in, Value::Bool(true)) {
            return Some((false, "not_opted_in"));
        }
        if pyval::is(tier, "advanced") {
            return Some(if pyval::is(&state, "VERIFIED") {
                (true, "allowed")
            } else {
                (false, "not_verified")
            });
        }
        let Value::Object(view) = view else {
            return None;
        };
        let reported = or_get(
            view.get("engine").unwrap_or(&Value::Null),
            &Value::from("version"),
        )?;
        if !matches!(engine_version, Value::Str(_))
            || !pyval::eq(engine_version, reported)
            || !pyval::eq(acknowledged_version, engine_version)
        {
            return Some((false, "not_acknowledged_for_this_engine"));
        }
        Some((true, "allowed"))
    };
    answer().unwrap_or((false, "unknown"))
}
