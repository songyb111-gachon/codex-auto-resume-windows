//! `compat/report.py`: the report the watcher writes, and every surface's view of it.
//!
//! A view is built from the report and the data in force, never from a guess; a report that is damaged or about
//! another binary is UNKNOWN rather than rendered. Everything here reads a report as the reference reads a dict:
//! a value of the wrong kind refuses the report (`None`), and the one exception the reference lets through - the
//! OverflowError of a time that is an int too large for a float - is let through here too.

use car_machine::compat::model::{EPOCH_MAX, EPOCH_MIN, product_key, safe_version};
use car_machine::domain::states::epoch;
use car_machine::json::{Map, Str, Value};
use car_machine::pyval::{self, Py};
use car_machine::vocab_gen::compat_model as words;

use super::standing::{CAPABILITIES, SEND_GATE, UNAVAILABLE, UNKNOWN, aggregate, own_reason};

pub const REPORT_FORMAT: &str = words::REPORT_FORMAT;

fn get<'a>(value: &'a Value, key: &str) -> &'a Value {
    static NULL: Value = Value::Null;
    match value {
        Value::Object(map) => map.get(key).unwrap_or(&NULL),
        _ => &NULL,
    }
}

fn object(pairs: Vec<(&str, Value)>) -> Value {
    let mut map = Map::new();
    for (key, value) in pairs {
        map.insert(Str::from(key), value);
    }
    Value::Object(map)
}

/// What refused a report: a ValueError or TypeError (the report is None), or an exception let through.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum Refused {
    No,
    Raised(&'static str),
}

type Clean<T> = Result<T, Refused>;

fn raised(class: &'static str) -> Refused {
    match class {
        "ValueError" | "TypeError" | "AttributeError" => Refused::No,
        other => Refused::Raised(other),
    }
}

/// `value in a_frozenset_of_texts`: an unhashable value raises TypeError.
fn in_frozen(value: &Value, members: &[&str]) -> Clean<bool> {
    pyval::in_set(value, members).map_err(raised)
}

/// `_finite_number(value)`.
pub fn finite_number(value: &Value) -> Py<bool> {
    Ok(matches!(value, Value::Int(_) | Value::Float(_)) && pyval::is_finite(value)?)
}

fn as_float(value: &Value) -> Value {
    match value {
        Value::Int(_) | Value::Bool(_) => Value::Float(
            pyval::Num::of(value)
                .map(pyval::Num::as_f64)
                .unwrap_or(f64::NAN),
        ),
        other => other.clone(),
    }
}

/// `_epoch_or_none(value)`.
fn epoch_or_none(value: &Value) -> Clean<Value> {
    if matches!(value, Value::Null) {
        return Ok(Value::Null);
    }
    if !epoch(value, EPOCH_MIN, EPOCH_MAX, false, true).map_err(raised)? {
        return Err(Refused::No);
    }
    Ok(as_float(value))
}

/// `_small_int_or_none(value)`.
fn small_int_or_none(value: &Value) -> Clean<Value> {
    match value {
        Value::Null => Ok(Value::Null),
        Value::Int(number)
            if number
                .as_i64()
                .is_some_and(|n| (0..=2_147_483_647).contains(&n)) =>
        {
            Ok(value.clone())
        }
        _ => Err(Refused::No),
    }
}

fn hex64(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
}

/// `_clean_engine(value)`.
fn clean_engine(value: &Value) -> Clean<Value> {
    if !matches!(value, Value::Object(_)) || !matches!(get(value, "found"), Value::Bool(_)) {
        return Err(Refused::No);
    }
    let version = get(value, "version");
    if !matches!(version, Value::Null) && safe_version(version).is_none() {
        return Err(Refused::No);
    }
    let signature = get(value, "signature");
    if !matches!(signature, Value::Null) {
        let fine = matches!(signature, Value::Array(parts) if parts.len() == 2
            && parts.iter().all(|part| matches!(part, Value::Int(_))
                && pyval::less_or_equal(&Value::from(0), part).unwrap_or(false)));
        if !fine {
            return Err(Refused::No);
        }
    }
    let digest = get(value, "path_digest");
    if !matches!(digest, Value::Null)
        && !matches!(digest, Value::Str(text) if text.as_str().is_some_and(hex64))
    {
        return Err(Refused::No);
    }
    let candidates = get(value, "candidates");
    if !matches!(candidates, Value::Null)
        && !matches!(candidates, Value::Int(n) if n.as_i64().is_some_and(|n| (0..=1000).contains(&n)))
    {
        return Err(Refused::No);
    }
    Ok(object(vec![
        ("found", get(value, "found").clone()),
        ("version", version.clone()),
        ("signature", signature.clone()),
        ("path_digest", digest.clone()),
        ("candidates", candidates.clone()),
    ]))
}

/// `_clean_data(value)`.
fn clean_data(value: &Value) -> Clean<Value> {
    if !matches!(value, Value::Object(_)) {
        return Err(Refused::No);
    }
    let clean = object(vec![
        ("bundled", get(value, "bundled").clone()),
        (
            "bundled_sequence",
            small_int_or_none(get(value, "bundled_sequence"))?,
        ),
        ("cache", get(value, "cache").clone()),
        (
            "cache_sequence",
            small_int_or_none(get(value, "cache_sequence"))?,
        ),
        ("cache_origin", get(value, "cache_origin").clone()),
        ("fetched_at", epoch_or_none(get(value, "fetched_at"))?),
        ("source", get(value, "source").clone()),
        ("expired", get(value, "expired").clone()),
    ]);
    let origin = get(&clean, "cache_origin");
    if !pyval::in_tuple(get(&clean, "bundled"), words::BUNDLED_STATES)
        || !pyval::in_tuple(get(&clean, "cache"), words::CACHE_STATES)
        || !pyval::in_tuple(get(&clean, "source"), words::DATA_SOURCES)
        || !matches!(get(&clean, "expired"), Value::Bool(_))
        || !(pyval::in_tuple(origin, words::CACHE_ORIGINS) || matches!(origin, Value::Null))
    {
        return Err(Refused::No);
    }
    Ok(clean)
}

/// `_clean_capabilities(value)`.
fn clean_capabilities(value: &Value) -> Clean<Value> {
    let Value::Object(map) = value else {
        return Err(Refused::No);
    };
    let mut clean = Map::new();
    for (name, _, tier) in CAPABILITIES {
        let entry = map.get(name).unwrap_or(&Value::Null);
        if matches!(entry, Value::Null) {
            clean.insert(
                Str::from(name),
                object(vec![
                    ("state", Value::from(UNKNOWN)),
                    ("reason", Value::from("local_check_unavailable")),
                    ("source", Value::from("local")),
                    ("tier", Value::from(tier)),
                ]),
            );
            continue;
        }
        let Value::Object(fields) = entry else {
            return Err(Refused::No);
        };
        let field = |key: &str| fields.get(key).cloned().unwrap_or(Value::Null);
        let (state, reason, source, tier) = (
            field("state"),
            field("reason"),
            field("source"),
            field("tier"),
        );
        if !pyval::in_tuple(&state, words::STATES)
            || !in_frozen(&reason, words::RESOLUTION_REASONS)?
            || !pyval::in_tuple(&source, words::SOURCES)
            || !pyval::in_tuple(&tier, words::TIERS)
        {
            return Err(Refused::No);
        }
        let state_word = pyval::text(&state).unwrap_or_default();
        let reason_word = pyval::text(&reason).unwrap_or_default();
        if own_reason(state_word).unwrap_or(reason_word) != reason_word {
            return Err(Refused::No);
        }
        let mut item = Map::new();
        item.insert(Str::from("state"), state.clone());
        item.insert(Str::from("reason"), reason.clone());
        item.insert(Str::from("source"), source);
        item.insert(Str::from("tier"), tier);
        if let Some(registry) = fields.get("registry_reason") {
            if !in_frozen(registry, words::REGISTRY_REASONS)? {
                return Err(Refused::No);
            }
            item.insert(Str::from("registry_reason"), registry.clone());
        }
        clean.insert(Str::from(name), Value::Object(item));
    }
    Ok(Value::Object(clean))
}

/// `validate_report(value, now=)`: the report as a reader may use it, or None. `Err` is an exception the reference
/// lets out (an OverflowError).
pub fn validate_report(value: &Value, now: Option<f64>) -> Py<Option<Value>> {
    match validated(value, now) {
        Ok(report) => Ok(Some(report)),
        Err(Refused::No) => Ok(None),
        Err(Refused::Raised(class)) => Err(class),
    }
}

fn validated(value: &Value, now: Option<f64>) -> Clean<Value> {
    if !matches!(value, Value::Object(_)) || !pyval::is(get(value, "format"), REPORT_FORMAT) {
        return Err(Refused::No);
    }
    let checked = get(value, "checked_at");
    if !epoch(checked, EPOCH_MIN, EPOCH_MAX, false, true).map_err(raised)? {
        return Err(Refused::No);
    }
    if let Some(now) = now
        && pyval::greater(checked, &Value::Float(now + 300.0)).map_err(raised)?
    {
        return Err(Refused::No);
    }
    let product = get(value, "product");
    let product_fine = match product {
        Value::Str(text) => text.as_str() == Some("unknown") || product_key(product).is_some(),
        _ => false,
    };
    if !product_fine {
        return Err(Refused::No);
    }
    let Value::Object(checks_in) = get(value, "checks") else {
        return Err(Refused::No);
    };
    let mut checks = Map::new();
    for name in words::CHECKS {
        let result = checks_in
            .get(*name)
            .cloned()
            .unwrap_or_else(|| Value::from(UNAVAILABLE));
        if !pyval::in_tuple(&result, words::RESULTS) {
            return Err(Refused::No);
        }
        checks.insert(Str::from(*name), result);
    }
    let capabilities = clean_capabilities(get(value, "capabilities"))?;
    let engine = clean_engine(get(value, "engine"))?;
    let data = clean_data(get(value, "data"))?;
    let overall = aggregate(&capabilities, &SEND_GATE).map_err(raised)?;
    let mut report = Map::new();
    report.insert(Str::from("format"), Value::from(REPORT_FORMAT));
    report.insert(Str::from("checked_at"), as_float(checked));
    report.insert(Str::from("product"), product.clone());
    report.insert(Str::from("engine"), engine);
    report.insert(Str::from("data"), data);
    report.insert(Str::from("overall"), Value::from(overall));
    report.insert(Str::from("checks"), Value::Object(checks));
    report.insert(Str::from("capabilities"), capabilities);
    let acting = get(value, "acting");
    if !matches!(acting, Value::Null) {
        if !pyval::in_tuple(acting, words::ENGINE_STATES) {
            return Err(Refused::No);
        }
        report.insert(Str::from("acting"), acting.clone());
    }
    Ok(Value::Object(report))
}

/// `build_report(...)`: a report ready to write, validated before it is returned. `Err` is the ValueError of a
/// report that failed its own validation (or an exception let through).
pub fn build_report(
    checked_at: f64,
    product: &str,
    engine: Value,
    data: Value,
    checks: &Map,
    capabilities: Value,
    acting: Option<&str>,
) -> Py<Value> {
    let product = if product_key(&Value::from(product)).is_some() {
        product
    } else {
        "unknown"
    };
    let mut all = Map::new();
    for name in words::CHECKS {
        all.insert(
            Str::from(*name),
            checks
                .get(*name)
                .cloned()
                .unwrap_or_else(|| Value::from(UNAVAILABLE)),
        );
    }
    let mut report = Map::new();
    report.insert(Str::from("format"), Value::from(REPORT_FORMAT));
    report.insert(Str::from("checked_at"), Value::Float(checked_at));
    report.insert(Str::from("product"), Value::from(product));
    report.insert(Str::from("engine"), engine);
    report.insert(Str::from("data"), data);
    report.insert(
        Str::from("overall"),
        Value::from(aggregate(&capabilities, &SEND_GATE)?),
    );
    report.insert(Str::from("checks"), Value::Object(all));
    report.insert(Str::from("capabilities"), capabilities);
    if let Some(acting) = acting {
        report.insert(Str::from("acting"), Value::from(acting));
    }
    validate_report(&Value::Object(report), None)?.ok_or("ValueError")
}

/// `_all_unknown(reason)`.
pub fn all_unknown(reason: &str) -> Value {
    let mut out = Map::new();
    for (name, _, tier) in CAPABILITIES {
        out.insert(
            Str::from(name),
            object(vec![
                ("state", Value::from(UNKNOWN)),
                ("reason", Value::from(reason)),
                ("source", Value::from("local")),
                ("tier", Value::from(tier)),
            ]),
        );
    }
    Value::Object(out)
}

/// `unusable_view(status, data=, checked_at=, engine=)`: UNKNOWN for everything.
pub fn unusable_view(
    status: &str,
    data: Value,
    checked_at: Value,
    engine: Option<&Value>,
) -> Value {
    let reason = match status {
        "absent" => "report_absent",
        "invalid" => "report_invalid",
        "stale" => "report_stale",
        "engine_changed" => "engine_changed",
        _ => "report_invalid",
    };
    let status = if words::VIEW_STATUSES.contains(&status) {
        status
    } else {
        "invalid"
    };
    let engine_truthy = engine.is_some_and(pyval::truthy);
    let mut checks = Map::new();
    for name in words::CHECKS {
        checks.insert(Str::from(*name), Value::from(UNAVAILABLE));
    }
    object(vec![
        ("status", Value::from(status)),
        ("overall", Value::from("unknown")),
        ("acting", Value::Null),
        ("checked_at", checked_at),
        (
            "engine",
            object(vec![
                (
                    "found",
                    Value::Bool(
                        engine_truthy
                            && pyval::truthy(get(engine.unwrap_or(&Value::Null), "found")),
                    ),
                ),
                (
                    "version",
                    if engine_truthy {
                        get(engine.unwrap_or(&Value::Null), "version").clone()
                    } else {
                        Value::Null
                    },
                ),
            ]),
        ),
        ("data", data),
        ("checks", Value::Object(checks)),
        ("capabilities", all_unknown(reason)),
    ])
}

/// `view_of(report)`: a usable report as readers see it, without the path digest or the signature.
pub fn view_of(report: &Value) -> Value {
    let engine = get(report, "engine");
    object(vec![
        ("status", Value::from("ok")),
        ("overall", get(report, "overall").clone()),
        ("acting", get(report, "acting").clone()),
        ("checked_at", get(report, "checked_at").clone()),
        (
            "engine",
            object(vec![
                ("found", get(engine, "found").clone()),
                ("version", get(engine, "version").clone()),
            ]),
        ),
        ("data", get(report, "data").clone()),
        ("checks", get(report, "checks").clone()),
        ("capabilities", get(report, "capabilities").clone()),
    ])
}

/// `mcp_view(view)`: the compatibility summary a model may read - codes, one small number and one timestamp.
pub fn mcp_view(view: &Value) -> Py<Value> {
    let fallback;
    let view = if matches!(view, Value::Object(_)) {
        view
    } else {
        fallback = unusable_view("invalid", Value::Null, Value::Null, None);
        &fallback
    };
    let empty = Value::Object(Map::new());
    let data = match get(view, "data") {
        found @ Value::Object(_) => found,
        _ => &empty,
    };
    let source_value = get(data, "source");
    let source = if pyval::in_tuple(source_value, words::DATA_SOURCES) {
        pyval::text(source_value).unwrap_or("none")
    } else {
        "none"
    };
    let sequence = match source {
        "cache" => get(data, "cache_sequence"),
        "bundled" => get(data, "bundled_sequence"),
        _ => get(data, "\u{0}none"),
    };
    let sequence = if matches!(sequence, Value::Int(_))
        && pyval::less_or_equal(&Value::from(0), sequence).unwrap_or(false)
    {
        sequence.clone()
    } else {
        Value::Null
    };
    let in_or = |value: &Value, members: &[&str], or: Value| {
        if pyval::in_tuple(value, members) {
            value.clone()
        } else {
            or
        }
    };
    let checked = get(view, "checked_at");
    let checked = if finite_number(checked)? {
        checked.clone()
    } else {
        Value::Null
    };
    let mut capabilities = Map::new();
    let listed = get(view, "capabilities");
    let entries: Vec<(Str, Value)> = match listed {
        Value::Object(map) => map.iter().map(|(k, v)| (k.clone(), v.clone())).collect(),
        Value::Null => Vec::new(),
        _ if !pyval::truthy(listed) => Vec::new(),
        _ => return Err("AttributeError"),
    };
    for (name, entry) in entries {
        if !name
            .as_str()
            .is_some_and(|name| CAPABILITIES.iter().any(|(each, _, _)| *each == name))
        {
            continue;
        }
        let Value::Object(fields) = &entry else {
            return Err("AttributeError");
        };
        let state = fields.get("state").cloned().unwrap_or(Value::Null);
        if !pyval::in_tuple(&state, words::STATES) {
            continue;
        }
        let reason = fields.get("reason").cloned().unwrap_or(Value::Null);
        if !pyval::in_set(&reason, words::REASONS)? {
            continue;
        }
        capabilities.insert(
            name,
            object(vec![
                ("state", fields.get("state").cloned().ok_or("KeyError")?),
                ("reason", fields.get("reason").cloned().ok_or("KeyError")?),
            ]),
        );
    }
    Ok(object(vec![
        (
            "status",
            in_or(
                get(view, "status"),
                words::VIEW_STATUSES,
                Value::from("invalid"),
            ),
        ),
        (
            "overall",
            in_or(
                get(view, "overall"),
                words::ENGINE_STATES,
                Value::from("unknown"),
            ),
        ),
        (
            "acting",
            in_or(get(view, "acting"), words::ENGINE_STATES, Value::Null),
        ),
        ("source", Value::from(source)),
        ("sequence", sequence),
        (
            "cache",
            in_or(get(data, "cache"), words::CACHE_STATES, Value::Null),
        ),
        ("checked_at", checked),
        ("capabilities", Value::Object(capabilities)),
    ]))
}
