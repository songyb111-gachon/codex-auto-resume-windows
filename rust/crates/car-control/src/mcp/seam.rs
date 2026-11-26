//! The one function of S3.3's `compat/*` the MCP server reads, behind a seam (the brief's rule for Rust seats: car-codex's
//! `compat/*` is ported by another seat). `compat.mcp_view(view)` is pure, a view in and the summary a model may read
//! out, so it is written here over car-machine's generated compatibility vocabulary; the integration replaces this
//! module with car-codex's `compat::report::mcp_view` once that is in (GROUNDWORK, S5.2).
//!
//! The view itself is `Host::compat_view` (`compatio.reader_view`), which `SystemHost` answers with null until S3.3.

use car_machine::json::{Map, Str, Value};
use car_machine::vocab::Node;
use car_machine::vocab_gen::compat_model as model;

/// Why the reference's `try` around the summary gave up (its `except Exception`): the summary is then None.
#[derive(Debug, PartialEq, Eq)]
pub struct Unsummarised;

fn is_in(value: Option<&Value>, set: &[&str]) -> bool {
    match value {
        Some(Value::Str(text)) => text.as_str().is_some_and(|each| set.contains(&each)),
        _ => false,
    }
}

/// `x in frozenset(...)`: a list or a dict cannot be hashed (TypeError).
fn in_frozen(value: Option<&Value>, set: &[&str]) -> Result<bool, Unsummarised> {
    match value {
        Some(Value::Array(_)) | Some(Value::Object(_)) => Err(Unsummarised),
        other => Ok(is_in(other, set)),
    }
}

/// `_finite_number(value)`: a number, not a bool, finite; an int too large for a float raises OverflowError.
fn finite_number(value: Option<&Value>) -> Result<bool, Unsummarised> {
    match value {
        Some(Value::Float(x)) => Ok(x.is_finite()),
        Some(Value::Int(int)) => {
            if int.as_i64().is_some() || int.as_u64().is_some() {
                return Ok(true);
            }
            match int.to_string().parse::<f64>() {
                Ok(x) if x.is_finite() => Ok(true),
                _ => Err(Unsummarised),
            }
        }
        _ => Ok(false),
    }
}

fn capability_names() -> Vec<&'static str> {
    match &model::CAPABILITIES {
        Node::Map(pairs) => pairs.iter().map(|(name, _)| *name).collect(),
        _ => Vec::new(),
    }
}

fn truthy(value: Option<&Value>) -> bool {
    value.is_some_and(car_machine::pyval::truthy)
}

/// `compat.mcp_view(view)`: the compatibility summary a model may read - codes, one small number and one timestamp.
pub fn mcp_view(view: &Value) -> Result<Value, Unsummarised> {
    let names = capability_names();
    let Value::Object(view) = view else {
        // `unusable_view("invalid")`, summarised: every capability UNKNOWN for `report_invalid`.
        let mut capabilities = Map::new();
        for name in &names {
            let mut entry = Map::new();
            entry.insert(Str::from("state"), Value::from("UNKNOWN"));
            entry.insert(Str::from("reason"), Value::from("report_invalid"));
            capabilities.insert(Str::from(*name), Value::Object(entry));
        }
        return Ok(summary(
            Value::from("invalid"),
            Value::from("unknown"),
            Value::Null,
            "none",
            Value::Null,
            Value::Null,
            Value::Null,
            capabilities,
        ));
    };
    let empty = Map::new();
    let data = match view.get("data") {
        Some(Value::Object(data)) => data,
        _ => &empty,
    };
    let source = if is_in(data.get("source"), model::DATA_SOURCES) {
        match data.get("source") {
            Some(Value::Str(text)) => text.as_str().unwrap_or("none"),
            _ => "none",
        }
    } else {
        "none"
    };
    let sequence = match source {
        "cache" => data.get("cache_sequence"),
        "bundled" => data.get("bundled_sequence"),
        _ => None,
    };
    let sequence = match sequence {
        Some(Value::Int(int)) if !int.to_string().starts_with('-') => Value::Int(int.clone()),
        _ => Value::Null,
    };
    let status = if is_in(view.get("status"), model::VIEW_STATUSES) {
        view.get("status").cloned().unwrap_or(Value::Null)
    } else {
        Value::from("invalid")
    };
    let overall = if is_in(view.get("overall"), model::ENGINE_STATES) {
        view.get("overall").cloned().unwrap_or(Value::Null)
    } else {
        Value::from("unknown")
    };
    let acting = if is_in(view.get("acting"), model::ENGINE_STATES) {
        view.get("acting").cloned().unwrap_or(Value::Null)
    } else {
        Value::Null
    };
    let cache = if is_in(data.get("cache"), model::CACHE_STATES) {
        data.get("cache").cloned().unwrap_or(Value::Null)
    } else {
        Value::Null
    };
    let checked_at = if finite_number(view.get("checked_at"))? {
        view.get("checked_at").cloned().unwrap_or(Value::Null)
    } else {
        Value::Null
    };
    let mut capabilities = Map::new();
    let listed = view.get("capabilities");
    if truthy(listed) {
        let Some(Value::Object(listed)) = listed else {
            // `.items()` of something that is not a dict: AttributeError.
            return Err(Unsummarised);
        };
        for (name, entry) in listed {
            if !name.as_str().is_some_and(|each| names.contains(&each)) {
                continue;
            }
            let Value::Object(entry) = entry else {
                return Err(Unsummarised);
            };
            if !is_in(entry.get("state"), model::STATES) {
                continue;
            }
            if !in_frozen(entry.get("reason"), model::REASONS)? {
                continue;
            }
            let mut kept = Map::new();
            kept.insert(
                Str::from("state"),
                entry.get("state").cloned().unwrap_or(Value::Null),
            );
            kept.insert(
                Str::from("reason"),
                entry.get("reason").cloned().unwrap_or(Value::Null),
            );
            capabilities.insert(name.clone(), Value::Object(kept));
        }
    }
    Ok(summary(
        status,
        overall,
        acting,
        source,
        sequence,
        cache,
        checked_at,
        capabilities,
    ))
}

#[allow(clippy::too_many_arguments)]
fn summary(
    status: Value,
    overall: Value,
    acting: Value,
    source: &str,
    sequence: Value,
    cache: Value,
    checked_at: Value,
    capabilities: Map,
) -> Value {
    let mut map = Map::new();
    map.insert(Str::from("status"), status);
    map.insert(Str::from("overall"), overall);
    map.insert(Str::from("acting"), acting);
    map.insert(Str::from("source"), Value::from(source));
    map.insert(Str::from("sequence"), sequence);
    map.insert(Str::from("cache"), cache);
    map.insert(Str::from("checked_at"), checked_at);
    map.insert(Str::from("capabilities"), Value::Object(capabilities));
    Value::Object(map)
}
