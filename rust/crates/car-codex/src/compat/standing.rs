//! `compat/standing.py`: what a document says about a version - whether it may be used, which claim wins, and on
//! what evidence. Pure.

use car_machine::compat::model::{
    Advisory, Document, FUTURE_SKEW_SECONDS, MAX_SEQUENCE_LEAD, parse_version, product_key,
};
use car_machine::json::{Map, Str, Value};
use car_machine::pyval::{self, Py};

pub const VERIFIED: &str = "VERIFIED";
pub const CHECKED: &str = "CHECKED";
pub const COMPATIBLE: &str = "COMPATIBLE";
pub const FAILED_HERE: &str = "FAILED_HERE";
pub const INCOMPATIBLE: &str = "INCOMPATIBLE";
pub const UNKNOWN: &str = "UNKNOWN";
pub const PASS: &str = "PASS";
pub const FAIL: &str = "FAIL";
pub const UNAVAILABLE: &str = "UNAVAILABLE";
pub const NOT_APPLICABLE: &str = "NOT_APPLICABLE";
pub const RESULTS: [&str; 4] = [PASS, FAIL, UNAVAILABLE, NOT_APPLICABLE];

/// capability -> (the local checks that prove it, tier), in the reference's order.
pub const CAPABILITIES: [(&str, &[&str], &str); 16] = [
    (
        "engine_present",
        &["official_location", "version_runs", "single_candidate"],
        "conservative",
    ),
    (
        "exact_thread_recovery",
        &["official_location", "version_runs", "queue_flags"],
        "conservative",
    ),
    (
        "usage_limit_detection",
        &["history_schema", "state_schema"],
        "conservative",
    ),
    (
        "usage_reset_hint",
        &["history_schema", "sessions_directory"],
        "conservative",
    ),
    (
        "usage_probe",
        &["version_runs", "protocol_usage_method"],
        "conservative",
    ),
    (
        "thread_eligibility",
        &["state_schema", "sessions_directory"],
        "conservative",
    ),
    (
        "loaded_state_detection",
        &["lock_directory", "restart_manager"],
        "conservative",
    ),
    (
        "recovery_turn_tracking",
        &["history_schema", "queue_schema", "projection_table"],
        "conservative",
    ),
    (
        "queue_withdraw",
        &["version_runs", "protocol_delete_method", "queue_schema"],
        "conservative",
    ),
    ("outcome_observation", &["history_schema"], "conservative"),
    (
        "transient_classification",
        &["history_schema"],
        "conservative",
    ),
    (
        "projection_freshness",
        &["projection_table", "sessions_directory"],
        "conservative",
    ),
    ("empty_response_recovery", &[], "unsupported"),
    ("not_loaded_recovery", &[], "unsupported"),
    ("goal_continuation", &[], "unsupported"),
    ("subagent_recovery", &[], "unsupported"),
];

/// The engine-level checks of a backend the watcher accepted.
pub const ACCEPTED_CHECKS: [(&str, &str); 4] = [
    ("official_location", PASS),
    ("version_runs", PASS),
    ("queue_flags", PASS),
    ("single_candidate", PASS),
];

/// Worst first: `_ORDER`.
pub fn order(state: &str) -> Option<u8> {
    Some(match state {
        INCOMPATIBLE => 0,
        FAILED_HERE => 1,
        UNKNOWN => 2,
        COMPATIBLE => 3,
        CHECKED => 4,
        VERIFIED => 5,
        _ => return None,
    })
}

/// `COARSE`: the heartbeat's word for a state.
pub fn coarse(state: &str) -> &'static str {
    match state {
        VERIFIED => "verified",
        CHECKED => "checked",
        COMPATIBLE => "structurally_compatible",
        FAILED_HERE => "failed_here",
        INCOMPATIBLE => "incompatible",
        _ => "unknown",
    }
}

/// `_OWN_REASON.get(state)`.
pub fn own_reason(state: &str) -> Option<&'static str> {
    match state {
        VERIFIED => Some("registry_verified"),
        CHECKED => Some("registry_checked"),
        FAILED_HERE => Some("local_check_failed_here"),
        _ => None,
    }
}

/// One of the documents in force, as `compat.evidence_for` weighs them: its name, the document (or none), and
/// whether it may verify.
pub type Source<'a> = (&'a str, Option<&'a Document>, bool);

/// `document_standing(document, product=, bundled=, now=, role=)`: whether a validated document may be used.
pub fn document_standing(
    document: &Document,
    product: &str,
    bundled: Option<&Document>,
    now: f64,
    role_bundled: bool,
) -> &'static str {
    if let Some(ours) = product_key(&Value::from(product))
        && document.min_product > ours
    {
        return "from_newer_product";
    }
    if role_bundled {
        return "ok";
    }
    if let Some(bundled) = bundled {
        if document.sequence < bundled.sequence {
            return "superseded";
        }
        if document.sequence > bundled.sequence + MAX_SEQUENCE_LEAD {
            return "rejected";
        }
        // `requires_signature`: a document that sets it is rejected whole, so neither side carries it.
    }
    if document.published_at > now + FUTURE_SKEW_SECONDS as f64 {
        return "from_the_future";
    }
    match document.expires_at {
        Some(expires) if expires > now => "ok",
        _ => "expired",
    }
}

/// `combine(results)`: several check results to one.
pub fn combine(results: &[&Value]) -> &'static str {
    let words: Vec<&str> = results
        .iter()
        .map(|each| {
            RESULTS
                .iter()
                .copied()
                .find(|word| pyval::is(each, word))
                .unwrap_or(UNAVAILABLE)
        })
        .collect();
    if words.is_empty() {
        return NOT_APPLICABLE;
    }
    for word in [FAIL, UNAVAILABLE, NOT_APPLICABLE] {
        if words.contains(&word) {
            return word;
        }
    }
    PASS
}

/// `resolve(local, evidence)`: (state, reason) for one capability.
pub fn resolve(local: &str, evidence: Option<&str>) -> (&'static str, &'static str) {
    let local = RESULTS
        .iter()
        .copied()
        .find(|word| *word == local)
        .unwrap_or(UNAVAILABLE);
    let evidence = evidence.filter(|word| [VERIFIED, CHECKED, INCOMPATIBLE].contains(word));
    if local == FAIL {
        return if matches!(evidence, Some(VERIFIED | CHECKED)) {
            (FAILED_HERE, "local_check_failed_here")
        } else {
            (INCOMPATIBLE, "local_check_failed")
        };
    }
    if evidence == Some(INCOMPATIBLE) {
        return (INCOMPATIBLE, "registry_incompatible");
    }
    if local == UNAVAILABLE || local == NOT_APPLICABLE {
        return (UNKNOWN, "local_check_unavailable");
    }
    match evidence {
        Some(VERIFIED) => (VERIFIED, "registry_verified"),
        Some(CHECKED) => (CHECKED, "registry_checked"),
        _ => (COMPATIBLE, "local_checks_passed"),
    }
}

/// `_in_range(key, advisory)`.
pub fn in_range(key: Option<[i64; 6]>, advisory: &Advisory) -> bool {
    let Some(key) = key else {
        return false;
    };
    if advisory.low.is_some_and(|low| key < low) {
        return false;
    }
    if advisory.high.is_some_and(|high| key >= high) {
        return false;
    }
    true
}

fn claim<'a>(
    document: &'a Document,
    version: &str,
    capability: &str,
) -> Option<&'a car_machine::compat::model::Claim> {
    document
        .engines
        .iter()
        .find(|(each, _)| each == version)
        .and_then(|(_, claims)| claims.iter().find(|(name, _)| name == capability))
        .map(|(_, claim)| claim)
}

/// `evidence_for(capability, version, sources)`: (state, source, registry_reason) from the documents in force.
pub fn evidence_for<'a>(
    capability: &str,
    version: &Value,
    sources: &[Source<'a>],
) -> (Option<&'static str>, Option<&'a str>, Option<String>) {
    let key = parse_version(version);
    let version_text = match version {
        Value::Str(text) => text.as_str(),
        _ => None,
    };
    for (name, document, _) in sources {
        let Some(document) = document else { continue };
        if let Some(found) = version_text.and_then(|version| claim(document, version, capability))
            && found.state == INCOMPATIBLE
        {
            return (Some(INCOMPATIBLE), Some(name), Some(found.reason.clone()));
        }
        for advisory in &document.advisories {
            if advisory.capabilities.iter().any(|each| each == capability)
                && in_range(key, advisory)
            {
                return (
                    Some(INCOMPATIBLE),
                    Some(name),
                    Some(advisory.reason.clone()),
                );
            }
        }
    }
    if key.is_none() {
        return (None, None, None);
    }
    let mut best: (Option<&'static str>, Option<&'a str>, Option<String>) = (None, None, None);
    for (name, document, verified_allowed) in sources {
        let found = match (document, verified_allowed) {
            (Some(document), true) => version_text.and_then(|v| claim(document, v, capability)),
            _ => None,
        };
        if let Some(found) = found {
            if found.state == VERIFIED {
                return (Some(VERIFIED), Some(name), None);
            }
            if found.state == CHECKED && best.0.is_none() {
                best = (Some(CHECKED), Some(name), None);
            }
        }
    }
    best
}

/// `evaluate(checks, version=, sources=)`: every capability's state.
pub fn evaluate(checks: &Map, version: &Value, sources: &[Source<'_>]) -> Map {
    static MISSING: std::sync::LazyLock<Value> =
        std::sync::LazyLock::new(|| Value::from(UNAVAILABLE));
    let mut capabilities = Map::new();
    for (name, needed, tier) in CAPABILITIES {
        let results: Vec<&Value> = needed
            .iter()
            .map(|check| checks.get(*check).unwrap_or(&MISSING))
            .collect();
        let local = combine(&results);
        let (evidence, origin, why) = evidence_for(name, version, sources);
        let (state, mut reason) = resolve(local, evidence);
        if needed.is_empty() && reason == "local_check_unavailable" {
            reason = "not_implemented";
        }
        let mut entry = Map::new();
        entry.insert(Str::from("state"), Value::from(state));
        entry.insert(Str::from("reason"), Value::from(reason));
        entry.insert(
            Str::from("source"),
            if reason.starts_with("registry_") {
                origin.map_or(Value::Null, Value::from)
            } else {
                Value::from("local")
            },
        );
        entry.insert(Str::from("tier"), Value::from(tier));
        if reason == "registry_incompatible" {
            entry.insert(
                Str::from("registry_reason"),
                why.as_deref().map_or(Value::Null, Value::from),
            );
        }
        capabilities.insert(Str::from(name), Value::Object(entry));
    }
    capabilities
}

/// `aggregate(capabilities, names=SEND_GATE)`: the worst state over `names`, as the heartbeat stores it.
pub fn aggregate(capabilities: &Value, names: &[&str]) -> Py<&'static str> {
    let mut worst = VERIFIED;
    for name in names {
        let entry = match capabilities {
            Value::Object(map) => map.get(*name),
            _ => None,
        };
        let state = match entry {
            Some(Value::Object(entry)) => entry.get("state").cloned().unwrap_or(Value::Null),
            _ => Value::from(UNKNOWN),
        };
        pyval::hashable(&state)?;
        let word = pyval::text(&state)
            .and_then(|word| order(word).map(|_| word))
            .unwrap_or(UNKNOWN);
        let word: &'static str = [
            INCOMPATIBLE,
            FAILED_HERE,
            UNKNOWN,
            COMPATIBLE,
            CHECKED,
            VERIFIED,
        ]
        .into_iter()
        .find(|each| *each == word)
        .unwrap_or(UNKNOWN);
        if order(word) < order(worst) {
            worst = word;
        }
    }
    Ok(coarse(worst))
}

/// The send gate's capabilities.
pub const SEND_GATE: [&str; 2] = ["engine_present", "exact_thread_recovery"];

/// `accepted_word(version, sources)`: the gate's word for an engine that passed its local checks.
pub fn accepted_word(version: &Value, sources: &[Source<'_>]) -> &'static str {
    let mut checks = Map::new();
    for (name, result) in ACCEPTED_CHECKS {
        checks.insert(Str::from(name), Value::from(result));
    }
    let version = match version {
        Value::Str(_) => version.clone(),
        _ => Value::Null,
    };
    let capabilities = evaluate(&checks, &version, sources);
    aggregate(&Value::Object(capabilities), &SEND_GATE).unwrap_or("unknown")
}

/// `verified_versions(document)`: exact versions a document marks VERIFIED for sending, sorted.
pub fn verified_versions(document: Option<&Document>) -> Vec<String> {
    let Some(document) = document else {
        return Vec::new();
    };
    let mut found: Vec<String> = document
        .engines
        .iter()
        .filter(|(_, claims)| {
            claims
                .iter()
                .any(|(name, claim)| name == "exact_thread_recovery" && claim.state == VERIFIED)
        })
        .map(|(version, _)| version.clone())
        .collect();
    found.sort();
    found
}
