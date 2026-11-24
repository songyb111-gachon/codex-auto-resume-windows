//! `codex/usage.py`: Codex's usage reply, read to an allowlist of numbers.
//!
//! Never the account it belongs to, never a plan name, never a balance: the fields below and nothing else, so a
//! reply that grows cannot start carrying something this product then logs.

use car_machine::domain::states;
use car_machine::json::{Map, Str, Value};
use car_machine::pyval::{self, Py};

fn entry(pairs: Vec<(&str, Value)>) -> Map {
    let mut map = Map::new();
    for (key, value) in pairs {
        map.insert(Str::from(key), value);
    }
    map
}

fn unknown() -> Map {
    entry(vec![
        ("available", Value::Null),
        ("reset_at", Value::Null),
        ("limit_type", Value::from("unknown")),
        ("reason", Value::from("usage_snapshot_unknown")),
    ])
}

static NULL: Value = Value::Null;

fn field<'a>(map: &'a Map, key: &str) -> &'a Value {
    map.get(key).unwrap_or(&NULL)
}

/// `machine.epoch(value, *EPOCH_USAGE, integer=True, exact=True, finite=False)`.
fn usage_epoch(value: &Value) -> Py<bool> {
    let (low, high) = states::EPOCH_USAGE;
    states::epoch(value, low, high, true, false)
}

/// `parse_usage(value)`: allowlist numeric usage fields. Never retain account IDs, banners or credits.
pub fn parse_usage(value: &Value) -> Py<Map> {
    let Value::Object(reply) = value else {
        return Ok(unknown());
    };
    let legacy_holder;
    let buckets: &Map = match reply.get("rateLimitsByLimitId") {
        Some(Value::Object(found)) if !found.is_empty() => found,
        _ => match reply.get("rateLimits") {
            Some(Value::Object(legacy)) => {
                legacy_holder = {
                    let mut single = Map::new();
                    single.insert(Str::from("legacy"), Value::Object(legacy.clone()));
                    single
                };
                &legacy_holder
            }
            _ => {
                legacy_holder = Map::new();
                &legacy_holder
            }
        },
    };
    let mut windows: Vec<Value> = Vec::new();
    let mut blocked: Vec<Map> = Vec::new();
    let (mut spending, mut explicit_limit, mut named) = (false, false, !buckets.is_empty());
    for (bucket_id, bucket) in buckets {
        let Value::Object(bucket) = bucket else {
            return Ok(unknown());
        };
        named &= bucket.contains_key("primary") && bucket.contains_key("secondary");
        let word = bucket_id.as_str().unwrap_or("");
        let safe_id = if ["codex", "premium", "legacy"].contains(&word) {
            word
        } else {
            "other"
        };
        spending |= matches!(bucket.get("spendControlReached"), Some(Value::Bool(true)));
        explicit_limit |= pyval::is(field(bucket, "rateLimitReachedType"), "rate_limit_reached");
        if [
            "workspace_owner_credits_depleted",
            "workspace_member_credits_depleted",
            "workspace_owner_usage_limit_reached",
            "workspace_member_usage_limit_reached",
        ]
        .iter()
        .any(|word| pyval::is(field(bucket, "rateLimitReachedType"), word))
        {
            spending = true;
        }
        for slot in ["primary", "secondary"] {
            let window = field(bucket, slot);
            if matches!(window, Value::Null) {
                continue;
            }
            let Value::Object(window) = window else {
                return Ok(unknown());
            };
            let used = field(window, "usedPercent");
            // `type(used) not in (int, float) or not math.isfinite(used) or used < 0`
            if !matches!(used, Value::Int(_) | Value::Float(_))
                || !pyval::is_finite(used)?
                || pyval::less(used, &Value::from(0))?
            {
                return Ok(unknown());
            }
            let duration = field(window, "windowDurationMins");
            if !matches!(duration, Value::Null)
                && (!pyval::is_int(duration) || !pyval::greater(duration, &Value::from(0))?)
            {
                return Ok(unknown());
            }
            let resets_at = field(window, "resetsAt");
            if !matches!(resets_at, Value::Null) && !usage_epoch(resets_at)? {
                return Ok(unknown());
            }
            let found = entry(vec![
                ("bucket", Value::from(safe_id)),
                ("window", Value::from(slot)),
                ("used_percent", used.clone()),
                ("window_minutes", duration.clone()),
                ("reset_at", resets_at.clone()),
            ]);
            windows.push(Value::Object(found.clone()));
            if !pyval::less(used, &Value::from(100))? {
                blocked.push(found);
            }
        }
    }
    let windows_value = Value::Array(windows.clone());
    if spending {
        return Ok(entry(vec![
            ("available", Value::Bool(false)),
            ("reset_at", Value::Null),
            ("limit_type", Value::from("spend_or_credits")),
            ("reason", Value::from("account_spend_or_credit_block")),
            ("windows", windows_value),
        ]));
    }
    if !blocked.is_empty() {
        let resets: Vec<&Value> = blocked.iter().map(|each| field(each, "reset_at")).collect();
        let reset = if resets.iter().all(|each| !matches!(each, Value::Null)) {
            pyval::max(&resets)?.clone()
        } else {
            Value::Null
        };
        let mut kinds: Vec<String> = blocked
            .iter()
            .map(|each| {
                let minutes = field(each, "window_minutes");
                let word = if pyval::truthy(minutes) {
                    car_machine::pytext::py_str(minutes)
                } else {
                    "unknown".to_owned()
                };
                format!("{word}m")
            })
            .collect();
        kinds.sort();
        kinds.dedup();
        return Ok(entry(vec![
            ("available", Value::Bool(false)),
            ("reset_at", reset),
            ("limit_type", Value::from(kinds.join(","))),
            (
                "reason",
                Value::from("one_or_more_exposed_windows_exhausted_blocking_bucket_not_attributed"),
            ),
            ("windows", windows_value),
        ]));
    }
    if explicit_limit {
        return Ok(entry(vec![
            ("available", Value::Bool(false)),
            ("reset_at", Value::Null),
            ("limit_type", Value::from("unattributed")),
            ("reason", Value::from("server_reports_rate_limit_reached")),
            ("windows", windows_value),
        ]));
    }
    if !windows.is_empty() {
        return Ok(entry(vec![
            ("available", Value::Bool(true)),
            ("reset_at", Value::Null),
            ("limit_type", Value::from("exposed_windows")),
            (
                "reason",
                Value::from("exposed_windows_available_specific_model_bucket_not_guaranteed"),
            ),
            ("windows", windows_value),
        ]));
    }
    if named {
        // Fourth round A2: every bucket names both windows and exposes neither (null): a known answer that tells
        // nothing, as a refusal does: the record waits usage_unknown, and the method is not "Codex changed".
        return Ok(entry(vec![
            ("available", Value::Null),
            ("reset_at", Value::Null),
            ("limit_type", Value::from("unknown")),
            ("reason", Value::from("usage_no_exposed_windows")),
            ("windows", Value::Array(Vec::new())),
        ]));
    }
    Ok(unknown())
}
