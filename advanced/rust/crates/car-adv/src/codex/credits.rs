//! `codex/credits.py`: Codex's usage read as the reset actions keep it - core's windows, how many reset credits there
//! are, and when the soonest of them expires - and nothing else (seat S7.2c). Pure.

use car_machine::domain::states::{EPOCH_USAGE, epoch};
use car_machine::json::{Map, Value};
use car_machine::pyval::Py;

use crate::vocabulary::SpendOutcome;

pub const READ: &str = "account/rateLimits/read";
pub const CONSUME: &str = "account/rateLimitResetCredit/consume";
pub const AVAILABLE: &str = "available";
pub const MAX_COUNT: i64 = 1000;

/// `DETAILED`: the read's params for a detailed read (`{}`).
pub fn detailed() -> Value {
    Value::Object(Map::new())
}

/// `LIGHT`: the read's params that leave the credits' details out.
pub fn light() -> Value {
    let mut map = Map::new();
    map.insert("excludeResetCreditDetails".into(), Value::Bool(true));
    Value::Object(map)
}

fn get<'a>(value: &'a Value, key: &str) -> Option<&'a Value> {
    match value {
        Value::Object(map) => map.get(key),
        _ => None,
    }
}

/// `_count(value)`.
fn count(value: Option<&Value>) -> Option<i64> {
    match value {
        Some(Value::Int(n)) => n.as_i64().filter(|n| (0..=MAX_COUNT).contains(n)),
        _ => None,
    }
}

/// `_expiry(value)`: whole seconds, none for one that never expires - or `Err(())` for anything else.
fn expiry(value: Option<&Value>) -> Py<Result<Option<Value>, ()>> {
    match value {
        None | Some(Value::Null) => Ok(Ok(None)),
        Some(found) => Ok(if epoch(found, EPOCH_USAGE.0, EPOCH_USAGE.1, true, false)? {
            Ok(Some(found.clone()))
        } else {
            Err(())
        }),
    }
}

/// `_soonest(count, listed)`: (whether the expiry is known, the soonest one).
fn soonest(count: Option<i64>, listed: Option<&Value>) -> Py<(bool, Option<Value>)> {
    let Some(count) = count else {
        return Ok((false, None));
    };
    if count == 0 {
        return Ok((true, None));
    }
    let Some(Value::Array(listed)) = listed else {
        return Ok((false, None));
    };
    let mut expiries: Vec<Option<Value>> = Vec::new();
    for credit in listed {
        let Some(Value::Str(status)) = get(credit, "status") else {
            return Ok((false, None));
        };
        if status.as_bytes() != AVAILABLE.as_bytes() {
            continue;
        }
        match expiry(get(credit, "expiresAt"))? {
            Ok(found) => expiries.push(found),
            Err(()) => return Ok((false, None)),
        }
    }
    if expiries.is_empty() {
        return Ok((false, None));
    }
    let dated: Vec<i64> = expiries
        .iter()
        .flatten()
        .filter_map(|at| match at {
            Value::Int(n) => n.as_i64(),
            _ => None,
        })
        .collect();
    Ok((true, dated.into_iter().min().map(Value::from)))
}

/// `parse(reply)`: `{windows, credits, expiry_known, nearest_expiry, ordinary_usage_allowed}`.
pub fn parse(reply: &Value) -> Py<Value> {
    let parsed = car_codex::usage::parse_usage(reply)?;
    let windows = car_machine::domain::usage::windows_of(&Value::Object(parsed))?;
    let summary = get(reply, "rateLimitResetCredits").filter(|summary| matches!(summary, Value::Object(_)));
    let credits = summary.and_then(|summary| count(get(summary, "availableCount")));
    let (known, nearest) = soonest(credits, summary.and_then(|summary| get(summary, "credits")))?;
    let allowed = match get(reply, "ordinaryUsageAllowed") {
        Some(Value::Bool(on)) => Value::Bool(*on),
        _ => Value::Null,
    };
    let mut out = Map::new();
    out.insert("windows".into(), windows.map_or(Value::Null, Value::Array));
    out.insert("credits".into(), credits.map_or(Value::Null, Value::from));
    out.insert("expiry_known".into(), Value::Bool(known));
    out.insert("nearest_expiry".into(), nearest.unwrap_or(Value::Null));
    out.insert("ordinary_usage_allowed".into(), allowed);
    Ok(Value::Object(out))
}

/// `details_listed(reply)`: whether the reply carries the credits' details, a list.
pub fn details_listed(reply: &Value) -> bool {
    matches!(get(reply, "rateLimitResetCredits").and_then(|summary| get(summary, "credits")), Some(Value::Array(_)))
}

/// `outcome(reply)`: what a consume came to, or UNKNOWN for a reply of any other shape.
pub fn outcome(reply: &Value) -> SpendOutcome {
    match get(reply, "outcome") {
        Some(Value::Str(word)) => match word.as_str() {
            Some("reset") => SpendOutcome::Reset,
            Some("nothingToReset") => SpendOutcome::NothingToReset,
            Some("noCredit") => SpendOutcome::NoCredit,
            Some("alreadyRedeemed") => SpendOutcome::AlreadyRedeemed,
            _ => SpendOutcome::Unknown,
        },
        _ => SpendOutcome::Unknown,
    }
}

/// `full(windows)`: the windows of a reading that are full - at 100 % or more, with a reset time.
pub fn full(windows: &[Value]) -> Py<Vec<Value>> {
    let mut found = Vec::new();
    for window in windows {
        let used = get(window, "used_percent").ok_or("KeyError")?;
        let reset = get(window, "reset_at").ok_or("KeyError")?;
        if car_machine::pyval::less_or_equal(&Value::from(100), used)? && !matches!(reset, Value::Null) {
            found.push(window.clone());
        }
    }
    Ok(found)
}
