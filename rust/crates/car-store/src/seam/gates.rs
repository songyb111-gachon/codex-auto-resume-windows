//! domain/gates.py, the parts the store's claim and registration run: the gates, the stored vector, the
//! chain's counters and the stop a record is born in.
//!
//! SEAM, TO BE REPLACED by car-policy's gates (S2.1).

use car_machine::json::{Map, Options, Str, Value, to_string};

use super::vocab::{GATE_REASONS, GATE_RESULTS, GATES, RESENDABLE, WAITING};
use super::{has, ids};
use crate::value::{Row, arithmetic, get, int, number, or_zero, text, text_of, truthy};

pub const PASS: &str = "PASS";
pub const WAIT: &str = "WAIT";
pub const BLOCK: &str = "BLOCK";
pub const UNKNOWN: &str = "UNKNOWN";
pub const NOT_CHECKED: &str = "not_checked";
pub const HELD: &str = "held";
pub const PLUGGED: &str = "plugged";
pub const POSTPONED: &str = "postponed";
pub const QUIET_HOURS: &str = "quiet_hours";
pub const OBSERVE_ONLY: &str = "observe_only";
pub const RESEND: &str = "resend";
pub const SEND_NOW: &str = "send_now";

/// One gate's answer: (result, reason).
pub type Gate = (String, String);

/// `gate(result, reason)`: a reason outside the list is "other".
pub fn gate(result: &str, reason: &str) -> Gate {
    let reason = if has(GATE_REASONS, reason) {
        reason
    } else {
        "other"
    };
    (result.to_string(), reason.to_string())
}

/// `gate(PASS)`.
pub fn pass() -> Gate {
    gate(PASS, "ok")
}

/// A gate vector: name to answer, in the order the names were put in (a Python dict).
#[derive(Clone, Debug, Default, PartialEq)]
pub struct Vector(pub Vec<(String, Gate)>);

impl Vector {
    pub fn get(&self, name: &str) -> Option<&Gate> {
        self.0
            .iter()
            .find(|(key, _)| key == name)
            .map(|(_, gate)| gate)
    }

    pub fn set(&mut self, name: &str, gate: Gate) {
        match self.0.iter_mut().find(|(key, _)| key == name) {
            Some(slot) => slot.1 = gate,
            None => self.0.push((name.to_string(), gate)),
        }
    }

    /// `vector.get(name, (UNKNOWN, NOT_CHECKED))`.
    pub fn or_unknown(&self, name: &str) -> Gate {
        self.get(name)
            .cloned()
            .unwrap_or_else(|| (UNKNOWN.to_string(), NOT_CHECKED.to_string()))
    }
}

/// `gate_consent(...)`.
pub fn gate_consent(
    enabled: bool,
    thread_enabled: bool,
    cancel_requested: bool,
    observe_only: bool,
    hold: &Value,
) -> Gate {
    if !enabled {
        return gate(BLOCK, "paused");
    }
    if !thread_enabled {
        return gate(BLOCK, "thread_disabled");
    }
    if cancel_requested {
        return gate(BLOCK, "cancel_requested");
    }
    if observe_only {
        return gate(BLOCK, OBSERVE_ONLY);
    }
    if !matches!(hold, Value::Null) {
        return gate(WAIT, HELD);
    }
    pass()
}

/// `gate_schedule(record, now, quiet_until=..., early=..., forced=...)`.
pub fn gate_schedule(
    record: &Row,
    now: f64,
    quiet_until: Option<f64>,
    early: bool,
    forced: bool,
) -> Gate {
    if !(early || forced) && or_zero(get(record, "next_retry_at")) > now {
        return gate(WAIT, "not_due");
    }
    let reset = get(record, "reset_at");
    if !early && !matches!(reset, Value::Null) && arithmetic(reset).is_some_and(|reset| reset > now)
    {
        return gate(WAIT, "waiting_reset");
    }
    if !forced && or_zero(get(record, "not_before")) > now {
        return gate(WAIT, POSTPONED);
    }
    if quiet_until.is_some_and(|until| until > now) {
        return gate(WAIT, QUIET_HOURS);
    }
    pass()
}

/// `gate_submission_safe(record, others_in_flight)`.
pub fn gate_submission_safe(record: &Row, others_in_flight: i64) -> Gate {
    let state = text_of(record, "state");
    if !matches!(get(record, "submitted_at"), Value::Null)
        || !state.is_some_and(|state| has(WAITING, state))
    {
        return gate(BLOCK, "possibly_sent");
    }
    if others_in_flight != 0 {
        return gate(WAIT, "other_recovery_in_flight");
    }
    pass()
}

/// `own_budget_only(record, administrators)`.
pub fn own_budget_only(record: &Row, administrators: Option<f64>) -> bool {
    administrators.is_none_or(|limit| or_zero(get(record, "recovery_attempts")) < limit)
}

/// `was_resent(record)`.
pub fn was_resent(record: &Row) -> bool {
    decode_gates(get(record, "gate_eval")).or_unknown("submission_safe") == gate(PASS, RESEND)
}

/// `resend_candidate(record, now, window)`.
pub fn resend_candidate(record: &Row, now: f64, window: (f64, f64)) -> bool {
    let (after, until) = window;
    let sent = number(get(record, "submitted_at"));
    let client = get(record, "recovery_client_id");
    let own_client = match (client, text_of(record, "interruption_id")) {
        (Value::Null, _) => true,
        (Value::Str(_), Some(key)) => {
            text(client) == Some(ids::continuation_client_id(key).as_str())
        }
        _ => false,
    };
    text_of(record, "state") == Some("submission_unknown")
        && text_of(record, "last_error").is_some_and(|word| has(RESENDABLE, word))
        && matches!(get(record, "queue_id"), Value::Null)
        && matches!(get(record, "first_queued_at"), Value::Null)
        && own_client
        && sent.is_some_and(|sent| after <= now - sent && now - sent <= until)
        && !truthy(get(record, "cancel_requested"))
        && matches!(get(record, "hold"), Value::Null)
        && !was_resent(record)
        && decode_gates(get(record, "gate_eval")).or_unknown("thread_available")
            != gate(PASS, PLUGGED)
}

/// `chain_span(record)`.
pub fn chain_span(record: &Row) -> f64 {
    let span =
        or_zero(get(record, "detected_at")) - or_zero(get(record, "chain_first_detected_at"));
    if span > 0.0 { span } else { 0.0 }
}

const PACING: &[(&str, &str)] = &[
    ("schedule", "not_due"),
    ("schedule", "waiting_reset"),
    ("attempt_budget", "daily_submission_cap"),
    ("attempt_budget", "thread_submission_cooldown"),
];

/// `waited_aside(vector)`.
pub fn waited_aside(vector: &Vector) -> bool {
    for name in GATES {
        let (result, reason) = vector.or_unknown(name);
        if result == PASS || reason == NOT_CHECKED || PACING.contains(&(name, reason.as_str())) {
            continue;
        }
        if result == BLOCK
            && matches!(
                *name,
                "chain_budget" | "attempt_budget" | "no_progress_budget"
            )
        {
            continue;
        }
        return true;
    }
    false
}

/// `counted_from(row, now)`: the start of a chain's counted time, moved later by a wait aside that `now` ends.
pub fn counted_from(row: &Row, now: f64) -> Value {
    let start = get(row, "chain_first_detected_at");
    let at = get(row, "gate_eval_at");
    let Some(at) = number(at) else {
        return start.clone();
    };
    if now <= at || !waited_aside(&decode_gates(get(row, "gate_eval"))) {
        return start.clone();
    }
    Value::Float(or_zero(start) + (now - at))
}

/// The budget limits a claim and a registration are evaluated with (`limits`).
#[derive(Clone, Debug, PartialEq)]
pub struct Limits {
    pub max_no_progress: f64,
    pub max_chain_continuations: f64,
    pub max_recovery_attempts: f64,
    pub max_chain_seconds: Option<f64>,
    pub managed_max_recovery_attempts: Option<f64>,
}

/// `over_ceiling(record, limits, usage_category)`.
pub fn over_ceiling(record: &Row, limits: &Limits, usage_category: bool) -> bool {
    !usage_category
        && limits
            .max_chain_seconds
            .is_some_and(|ceiling| chain_span(record) >= ceiling)
}

/// The fields a new record takes from its parent (`CHAIN_FIELDS`).
pub const CHAIN_FIELDS: &[&str] = &[
    "chain_origin_id",
    "chain_first_detected_at",
    "chain_continuations",
    "recovery_attempts",
    "usage_unavailable_seconds",
    "budget_resets",
];

/// `inherited(parent, failed_turn_progress, legacy_carry)`: what a new record of a task starts with.
pub fn inherited(
    parent: Option<&Row>,
    failed_turn_progress: &Value,
    legacy_carry: &Value,
) -> Vec<(&'static str, Value)> {
    let Some(parent) = parent else {
        // `isinstance(carry, int) and not isinstance(carry, bool) and carry > 0`.
        let positive = |carry: &car_machine::json::Int| {
            let digits = carry.to_string();
            !digits.starts_with('-') && digits != "0"
        };
        return match legacy_carry {
            Value::Int(carry) if positive(carry) => {
                vec![("no_progress_count", legacy_carry.clone())]
            }
            _ => Vec::new(),
        };
    };
    let mut found: Vec<(&'static str, Value)> = CHAIN_FIELDS
        .iter()
        .map(|field| (*field, get(parent, field).clone()))
        .collect();
    found.push((
        "parent_interruption_id",
        get(parent, "interruption_id").clone(),
    ));
    let progress = matches!(failed_turn_progress, Value::Bool(true));
    let count =
        arithmetic(get(parent, "no_progress_count")).unwrap_or(0.0) as i64 + i64::from(!progress);
    found.push(("no_progress_count", int(count)));
    found
}

/// `birth_stop(parent, failed_turn_progress, limits, usage_category, now=..., legacy_carry=...)`.
pub fn birth_stop(
    parent: Option<&Row>,
    failed_turn_progress: &Value,
    limits: Option<&Limits>,
    usage_category: bool,
    now: f64,
    legacy_carry: &Value,
) -> Option<(&'static str, &'static str)> {
    if let Some(parent) = parent {
        if truthy(get(parent, "cancel_requested")) {
            return Some(("cancelled", "parent_cancelled"));
        }
        if truthy(get(parent, "user_joined"))
            || truthy(get(parent, "after_user_work"))
            || matches!(
                text_of(parent, "state"),
                Some("handed_over" | "stopped_by_user")
            )
        {
            return Some(("superseded", "parent_handed_over"));
        }
    }
    let limits = limits?;
    let mut row = Map::new();
    for (name, value) in [
        ("detected_at", Value::Float(now)),
        ("chain_first_detected_at", Value::Float(now)),
        ("chain_continuations", int(0)),
        ("recovery_attempts", int(0)),
        ("no_progress_count", int(0)),
    ] {
        row.insert(Str::new(name), value);
    }
    for (name, value) in inherited(parent, failed_turn_progress, legacy_carry) {
        row.insert(Str::new(name), value);
    }
    let at = |name: &str| arithmetic(get(&row, name)).unwrap_or(0.0);
    if at("no_progress_count") >= limits.max_no_progress {
        return Some(("no_progress_exhausted", "no_progress_budget"));
    }
    if at("chain_continuations") >= limits.max_chain_continuations {
        return Some(("retry_budget_exhausted", "chain_cap"));
    }
    if over_ceiling(&row, limits, usage_category) {
        return Some(("retry_budget_exhausted", "chain_time_cap"));
    }
    if !usage_category && at("recovery_attempts") >= limits.max_recovery_attempts {
        return Some(("retry_budget_exhausted", "recovery_budget"));
    }
    None
}

/// `gate_budgets(record, limits, usage_category)`.
pub fn gate_budgets(
    record: &Row,
    limits: &Limits,
    usage_category: bool,
) -> Vec<(&'static str, Gate)> {
    let at = |name: &str| arithmetic(get(record, name)).unwrap_or(0.0);
    let chain = if at("chain_continuations") >= limits.max_chain_continuations {
        gate(BLOCK, "chain_cap")
    } else if over_ceiling(record, limits, usage_category) {
        gate(BLOCK, "chain_time_cap")
    } else {
        pass()
    };
    let attempt = if !usage_category && at("recovery_attempts") >= limits.max_recovery_attempts {
        gate(BLOCK, "recovery_budget")
    } else {
        pass()
    };
    let progress = if at("no_progress_count") >= limits.max_no_progress {
        gate(BLOCK, "no_progress_budget")
    } else {
        pass()
    };
    vec![
        ("chain_budget", chain),
        ("attempt_budget", attempt),
        ("no_progress_budget", progress),
    ]
}

/// `first_refusal(vector)`: the first gate, in order, that does not pass; never evaluated is a refusal.
pub fn first_refusal(vector: &Vector) -> Option<(&'static str, Gate)> {
    GATES.iter().find_map(|name| {
        let found = vector.or_unknown(name);
        (found.0 != PASS).then_some((*name, found))
    })
}

/// `encode_gates(vector)`: compact JSON, names sorted, allowlisted words only.
pub fn encode_gates(vector: &Vector) -> String {
    let mut clean = Map::new();
    let mut names: Vec<&str> = GATES.to_vec();
    names.sort_unstable();
    for name in names {
        let (result, reason) = vector.or_unknown(name);
        let result = if has(GATE_RESULTS, &result) {
            result
        } else {
            UNKNOWN.to_string()
        };
        let reason = if has(GATE_REASONS, &reason) {
            reason
        } else {
            "other".to_string()
        };
        clean.insert(
            Str::new(name),
            Value::Array(vec![Value::from(result), Value::from(reason)]),
        );
    }
    to_string(
        &Value::Object(clean),
        &Options::new().separators(",", ":").sort_keys(true),
    )
    .expect("the gates are words")
}

/// `decode_gates(text)`: anything unexpected becomes UNKNOWN, never an error.
pub fn decode_gates(stored: &Value) -> Vector {
    let raw = match stored {
        Value::Str(stored) if stored.code_points().count() <= 4000 => stored
            .as_str()
            .and_then(|stored| super::python::loads(stored).ok())
            .unwrap_or(Value::Null),
        _ => Value::Null,
    };
    let mut result = Vector::default();
    for name in GATES {
        let value = match &raw {
            Value::Object(map) => map.get(*name),
            _ => None,
        };
        let gate = match value {
            Some(Value::Array(pair)) if pair.len() == 2 => match (text(&pair[0]), &pair[1]) {
                (Some(result), Value::Str(reason)) if has(GATE_RESULTS, result) => {
                    let reason = reason
                        .as_str()
                        .filter(|reason| has(GATE_REASONS, reason))
                        .unwrap_or("other");
                    Some((result.to_string(), reason.to_string()))
                }
                _ => None,
            },
            _ => None,
        };
        result.set(
            name,
            gate.unwrap_or_else(|| (UNKNOWN.to_string(), NOT_CHECKED.to_string())),
        );
    }
    result
}
