//! `control/resets.py` (seat S7.3a): the Dashboard's reset actions (v0.6.14) - their rules read, one added, one
//! cancelled, one held over a gap let go on, and a reset credit used now - and the helpers every card of `control/`
//! shares with it at the tag (`_refused`, `_stale`, `_on`, `_standing`, `switched_off`).
//!
//! Each is the long-lived bridge's, the Dashboard's alone (`surfaces.rs`), against the generation the page read. A
//! state method a test made raise (`runtime.faults`, the advanced proxy's `patch.object`) raises here too ([`call`]).

use std::cmp::Ordering;
use std::sync::Arc;

use car_machine::json::{Int, Map, Str, Value};
use car_machine::pyval;

use crate::engine::credits::{self, CAPABILITY as CREDIT};
use crate::engine::resetmessage::{CAPABILITY as MESSAGE, LONG, SHORT_LIMIT};
use crate::runtime::Runtime;
use crate::state::calls::{self, Call};
use crate::state::resets::{CREDIT_RULES_LIMIT, MESSAGES_LIMIT};
use crate::state::schema::BUCKETS;
use crate::state::sql::Row;
use crate::state::{AdvancedState, Error};
use crate::vocabulary::{ArmingState, Measurement, Refusal, RuleState};

/// A week, in minutes.
pub const WEEK: i64 = 10080;
/// The families offered where nothing has been counted yet.
pub const DEFAULT_FAMILIES: [(&str, i64); 2] = [("codex", 300), ("codex", WEEK)];
/// What the Dashboard is shown of a rule.
pub const SHOWN: &[&str] = &[
    "rule_id",
    "capability",
    "bucket",
    "minutes",
    "ordinal",
    "repeat",
    "ask_first",
    "state",
    "reason",
    "gate",
    "gate_reason",
    "created_at",
    "adopted_at",
    "due_at",
    "sent_at",
    "finished_at",
    "thread_id",
];

pub type Result<T> = std::result::Result<T, Error>;

// ------------------------------------------------------------------ what every card shares

/// `runtime.state.<method>(*args, **kwargs)`, as the reference binds them (car-adv `state::calls`), raising where a
/// test made the method raise.
pub fn call(runtime: &Runtime, method: &str, args: &[Value], kwargs: &[(&str, Value)]) -> Result<Value> {
    runtime.faulted(method)?;
    let mut map = Map::new();
    for (name, value) in kwargs {
        map.insert(Str::new(name), value.clone());
    }
    calls::call(&runtime.state, method, Call { args, kwargs: &map })
}

/// The state, for a typed read, raising where a test made `method` raise.
pub fn state<'a>(runtime: &'a Runtime, method: &str) -> Result<&'a AdvancedState> {
    runtime.faulted(method)?;
    Ok(&runtime.state)
}

/// `row.get(name)`, None where absent.
pub fn get(row: &Row, name: &str) -> Value {
    row.get(name).cloned().unwrap_or(Value::Null)
}

/// `value.get(name)` of a dict; None for anything else or a key it lacks.
pub fn field(value: &Value, name: &str) -> Value {
    match value {
        Value::Object(map) => map.get(name).cloned().unwrap_or(Value::Null),
        _ => Value::Null,
    }
}

/// A list of rows as one Python list.
pub fn list(value: &Value) -> Vec<Row> {
    match value {
        Value::Array(items) => items
            .iter()
            .filter_map(|item| match item {
                Value::Object(map) => Some(map.clone()),
                _ => None,
            })
            .collect(),
        _ => Vec::new(),
    }
}

/// `{name: row.get(name) for name in names}`.
pub fn shown(row: &Row, names: &[&str]) -> Map {
    let mut map = Map::new();
    for name in names {
        map.insert(Str::new(name), get(row, name));
    }
    map
}

/// An object of `(key, value)` pairs, in order.
pub fn object(pairs: Vec<(&str, Value)>) -> Value {
    let mut map = Map::new();
    for (key, value) in pairs {
        map.insert(Str::new(key), value);
    }
    Value::Object(map)
}

/// `dict(base, key=value, ...)`: a key already there keeps its place, a new one goes last.
pub fn with(base: Value, pairs: Vec<(&str, Value)>) -> Value {
    let mut map = match base {
        Value::Object(map) => map,
        _ => Map::new(),
    };
    for (key, value) in pairs {
        map.insert(Str::new(key), value);
    }
    Value::Object(map)
}

pub fn text(word: &str) -> Value {
    Value::Str(Str::new(word))
}

pub fn int(number: i64) -> Value {
    Value::Int(Int::from(number))
}

/// Whether `value` is the text `word`.
pub fn is(value: &Value, word: &str) -> bool {
    matches!(value, Value::Str(text) if text.as_str() == Some(word))
}

/// Whether `value` is one of `words`.
pub fn among(value: &Value, words: &[&str]) -> bool {
    words.iter().any(|word| is(value, word))
}

/// `type(value) is int`.
pub fn is_int(value: &Value) -> bool {
    matches!(value, Value::Int(_))
}

/// `type(value) is bool`.
pub fn is_bool(value: &Value) -> bool {
    matches!(value, Value::Bool(_))
}

/// An int's value, where it fits.
pub fn small(value: &Value) -> Option<i64> {
    match value {
        Value::Int(number) => number.as_i64(),
        _ => None,
    }
}

/// `(value or 0)` as a number: a falsy value is 0, a number its own; anything else is no number.
pub fn or_zero(value: &Value) -> Option<f64> {
    if !pyval::truthy(value) {
        return Some(0.0);
    }
    number_of(value)
}

/// `a + b` of two numbers: an int where both are ints, a float otherwise; None where either is no number.
pub fn plus(a: &Value, b: &Value) -> Value {
    match (a, b) {
        (Value::Int(x), Value::Int(y)) => match (x.as_i64(), y.as_i64()) {
            (Some(x), Some(y)) => x.checked_add(y).map_or(Value::Float(x as f64 + y as f64), int),
            _ => Value::Null,
        },
        _ => match (number_of(a), number_of(b)) {
            (Some(x), Some(y)) => Value::Float(x + y),
            _ => Value::Null,
        },
    }
}

/// `a - b` of two numbers, as [`plus`]; a TypeError where either is no number.
pub fn minus(a: &Value, b: &Value) -> Result<Value> {
    match (a, b) {
        (Value::Int(x), Value::Int(y)) => match (x.as_i64(), y.as_i64()) {
            (Some(x), Some(y)) => Ok(x.checked_sub(y).map_or(Value::Float(x as f64 - y as f64), int)),
            _ => Err(Error::python("OverflowError", "int too large")),
        },
        _ => match (number_of(a), number_of(b)) {
            (Some(x), Some(y)) => Ok(Value::Float(x - y)),
            _ => Err(Error::type_error("unsupported operand type(s) for -")),
        },
    }
}

/// A number's value (a bool is one, as Python's `True - 1`).
pub fn number_of(value: &Value) -> Option<f64> {
    match value {
        Value::Bool(on) => Some(f64::from(u8::from(*on))),
        _ => pyval::Num::of(value).map(|number| number.as_f64()),
    }
}

/// `isinstance(value, (int, float)) and not isinstance(value, bool)`.
pub fn is_time(value: &Value) -> bool {
    matches!(value, Value::Int(_) | Value::Float(_))
}

/// The length of a text in code points, as Python's `len`.
pub fn length(value: &Value) -> usize {
    match value {
        Value::Str(text) => text.code_points().count(),
        _ => 0,
    }
}

/// `_refused(refusal, runtime=None)`: the refusal, and the generation where the runtime can read it.
pub fn refused(refusal: &str, runtime: Option<&Runtime>) -> Value {
    let mut map = Map::new();
    map.insert(Str::new("done"), Value::Bool(false));
    map.insert(Str::new("refusal"), text(refusal));
    if let Some(runtime) = runtime {
        if let Ok(generation) = generation(runtime) {
            map.insert(Str::new("generation"), generation);
        }
    }
    Value::Object(map)
}

/// `{"done": False, "refusal": refusal}`.
pub fn refusal(refusal: Refusal) -> Value {
    refused(refusal.as_str(), None)
}

/// `_refused(refusal, runtime)`.
pub fn refused_here(refusal: Refusal, runtime: &Runtime) -> Value {
    refused(refusal.as_str(), Some(runtime))
}

/// `runtime.state.meta()["generation"]`.
pub fn generation(runtime: &Runtime) -> Result<Value> {
    let meta = state(runtime, "meta")?.meta()?;
    Ok(get(&meta, "generation"))
}

/// `_stale(runtime, generation)`.
pub fn stale(runtime: &Runtime, asked: &Value) -> bool {
    if !is_int(asked) {
        return true;
    }
    match generation(runtime) {
        Ok(held) => !pyval::eq(&held, asked),
        Err(_) => true,
    }
}

/// `_on(runtime, capability)`.
pub fn on(runtime: &Runtime, capability: &str) -> bool {
    runtime.states(true, &[]).state_of(capability) == ArmingState::Armed
}

/// `_standing(runtime, capability)`: on or watched.
pub fn standing(runtime: &Runtime, capability: &str) -> bool {
    matches!(
        runtime.states(true, &[]).state_of(capability),
        ArmingState::Armed | ArmingState::Shadow
    )
}

/// Core's state, opened for one read (`Store(runtime.paths.state_dir)`).
pub fn core(runtime: &Runtime) -> Result<car_store::Store> {
    car_store::Store::open(std::path::Path::new(&runtime.paths.state_dir), Arc::new(car_control::host::Probe))
        .map_err(|_| Error::python("StoreError", "cannot open core's state"))
}

/// `switched_off(runtime, thread)`: whether core holds conversation `thread` switched off now; unreadable is not.
pub fn switched_off(runtime: &Runtime, thread: &Value) -> bool {
    let Some(thread) = (match thread {
        Value::Str(text) => text.as_str(),
        _ => None,
    }) else {
        return false;
    };
    match core(runtime) {
        Ok(store) => matches!(store.thread_enabled(thread), Ok(false)),
        Err(_) => false,
    }
}

/// `try: sendnow.wake(paths) except Exception: pass` - whether a watcher holds the event.
pub fn wake(runtime: &Runtime) -> bool {
    super::sendnow::wake(&runtime.paths).unwrap_or(false)
}

/// `arming.verdict(measurement)`, None where it cannot be read.
pub fn verdict(runtime: &Runtime, measurement: Measurement) -> Option<&'static str> {
    runtime.arming().verdict(measurement.as_str()).ok().flatten()
}

/// `_failed(runtime, measurement)`: the verdict is a fail; False where it cannot be read.
pub fn failed(runtime: &Runtime, measurement: Measurement) -> bool {
    verdict(runtime, measurement) == Some("fail")
}

/// What a state error refuses as: a `Refused` its own word, a `StateError` STATE_UNAVAILABLE; anything else escapes
/// (the reference's `except Refused` and `except StateError`).
pub fn state_refusal(runtime: &Runtime, error: Error) -> Result<Value> {
    if error.class() == "Refused" {
        return Ok(refused(error.word().unwrap_or_default(), Some(runtime)));
    }
    if error.is_state() {
        return Ok(refused_here(Refusal::StateUnavailable, runtime));
    }
    Err(error)
}

/// `argument.get(name)`.
pub fn arg(argument: &Map, name: &str) -> Value {
    argument.get(name).cloned().unwrap_or(Value::Null)
}

// ------------------------------------------------------------------ the reset actions

/// `KINDS.get(kind)`.
fn kind(word: &Value) -> Option<&'static str> {
    if is(word, "credit") {
        Some(CREDIT)
    } else if is(word, "message") {
        Some(MESSAGE)
    } else {
        None
    }
}

/// `words_limit(runtime)`: A27's 2,000, or what one continuation carries while Longer reset messages stands on.
pub fn words_limit(runtime: &Runtime) -> usize {
    if on(runtime, LONG) {
        car_policy::classify::continuation::prompt_limit()
    } else {
        SHORT_LIMIT
    }
}

/// `occasion_problem(bucket, minutes, ordinal)`.
pub fn occasion_problem(bucket: &Value, minutes: &Value, ordinal: &Value) -> bool {
    if !among(bucket, BUCKETS) {
        return true;
    }
    let Some(minutes) = small(minutes) else {
        return true;
    };
    if !(0 < minutes && minutes <= 10 * WEEK) {
        return true;
    }
    match small(ordinal) {
        Some(ordinal) if (1..10).contains(&ordinal) => minutes >= WEEK && ordinal != 1,
        _ => true,
    }
}

/// `count_unproven(runtime)`.
pub fn count_unproven(runtime: &Runtime) -> bool {
    verdict(runtime, Measurement::Mu) != Some("pass")
}

/// `windows.get((bucket, minutes))`.
fn window<'a>(windows: &'a [((Value, Value), Row)], bucket: &Value, minutes: &Value) -> Option<&'a Row> {
    windows
        .iter()
        .find(|((b, m), _)| pyval::eq(b, bucket) && pyval::eq(m, minutes))
        .map(|(_, row)| row)
}

/// `view(runtime)`: advanced-resets.
pub fn view(runtime: &Runtime) -> Value {
    let read = || -> Result<_> {
        let rules = list(&call(runtime, "reset_rules", &[], &[("pending", Value::Null)])?);
        let windows = state(runtime, "windows")?.windows()?;
        let reading = state(runtime, "reading")?.reading()?;
        let spends = list(&call(runtime, "credit_spends", &[], &[])?);
        let generation = generation(runtime)?;
        Ok((rules, windows, reading, spends, generation))
    };
    let Ok((rules, windows, reading, spends, generation)) = read() else {
        return refusal(Refusal::StateUnavailable);
    };
    let now = runtime.now();
    let mut shown_rules = Vec::new();
    for rule in &rules {
        let pending = among(
            &get(rule, "state"),
            &[RuleState::Counting.as_str(), RuleState::Ready.as_str(), RuleState::Held.as_str()],
        );
        if !pending && or_zero(&get(rule, "finished_at")).is_some_and(|at| at < now - 30.0 * 86400.0) {
            continue;
        }
        let mut item = shown(rule, SHOWN);
        let row = window(&windows, &get(rule, "bucket"), &get(rule, "minutes"));
        let base = get(rule, "base");
        let counted = match (&base, row) {
            (Value::Null, _) | (_, None) => Value::Null,
            (_, Some(row)) => {
                let held = if is(&get(rule, "capability"), CREDIT) {
                    get(row, "hits")
                } else {
                    get(row, "resets")
                };
                minus(&held, &base).unwrap_or(Value::Null)
            }
        };
        item.insert(Str::new("counted"), counted);
        item.insert(
            Str::new("next_reset"),
            row.map_or(Value::Null, |row| get(row, "open_reset_at")),
        );
        item.insert(Str::new("words"), get(rule, "words"));
        item.insert(
            Str::new("being_sent"),
            Value::Bool(
                !matches!(get(rule, "launching_at"), Value::Null)
                    || is(&get(rule, "record_state"), "in_flight"),
            ),
        );
        shown_rules.push(Value::Object(item));
    }
    let mut families: Vec<(Value, Value)> = DEFAULT_FAMILIES
        .iter()
        .map(|(bucket, minutes)| (text(bucket), int(*minutes)))
        .collect();
    for ((bucket, minutes), _) in &windows {
        if !families
            .iter()
            .any(|(b, m)| pyval::eq(b, bucket) && pyval::eq(m, minutes))
        {
            families.push((bucket.clone(), minutes.clone()));
        }
    }
    families.sort_by(|(b1, m1), (b2, m2)| {
        pyval::order(m1, m2)
            .ok()
            .flatten()
            .unwrap_or(Ordering::Equal)
            .then_with(|| pyval::order(b1, b2).ok().flatten().unwrap_or(Ordering::Equal))
    });
    let families = families
        .iter()
        .map(|(bucket, minutes)| {
            let row = window(&windows, bucket, minutes);
            object(vec![
                ("bucket", bucket.clone()),
                ("minutes", minutes.clone()),
                ("open_reset_at", row.map_or(Value::Null, |row| get(row, "open_reset_at"))),
                (
                    "open_full",
                    Value::Bool(row.is_some_and(|row| pyval::truthy(&get(row, "open_full")))),
                ),
            ])
        })
        .collect();
    let credit_on = on(runtime, CREDIT);
    let last = spends
        .iter()
        .find(|spend| !matches!(get(spend, "outcome"), Value::Null));
    let when_on = |name: &str| if credit_on { get(&reading, name) } else { Value::Null };
    object(vec![
        ("done", Value::Bool(true)),
        ("refusal", Value::Null),
        ("generation", generation),
        ("rules", Value::Array(shown_rules)),
        ("families", Value::Array(families)),
        (
            "reading",
            object(vec![
                ("read_at", get(&reading, "read_at")),
                ("credits", when_on("credits")),
                ("nearest_expiry", when_on("nearest_expiry")),
                (
                    "expiry_known",
                    if credit_on {
                        Value::Bool(pyval::truthy(&get(&reading, "expiry_known")))
                    } else {
                        Value::Null
                    },
                ),
            ]),
        ),
        (
            "last_spend",
            last.map_or(Value::Null, |last| {
                object(vec![("outcome", get(last, "outcome")), ("at", get(last, "finished_at"))])
            }),
        ),
        ("count_unproven", Value::Bool(count_unproven(runtime))),
        ("count_failed", Value::Bool(failed(runtime, Measurement::Mu))),
        ("credit_failed", Value::Bool(failed(runtime, Measurement::Mr))),
        (
            "limits",
            object(vec![
                ("messages", int(MESSAGES_LIMIT)),
                ("credit_rules", int(CREDIT_RULES_LIMIT)),
                ("words", int(words_limit(runtime) as i64)),
                ("ordinals", int(9)),
                ("use_now_minutes", int(credits::USE_NOW as i64 / 60)),
            ]),
        ),
    ])
}

/// `add(runtime, argument)`: advanced-reset-add.
pub fn add(runtime: &Runtime, argument: &Map) -> Result<Value> {
    let Some(capability) = kind(&arg(argument, "kind")) else {
        return Ok(refusal(Refusal::InvalidRequest));
    };
    if runtime.registry.get(capability).is_none() {
        return Ok(refusal(Refusal::InvalidRequest));
    }
    if stale(runtime, &arg(argument, "generation")) {
        return Ok(refused_here(Refusal::StaleGeneration, runtime));
    }
    if !standing(runtime, capability) {
        return Ok(refused_here(Refusal::NotOn, runtime));
    }
    let (bucket, minutes, ordinal) = (arg(argument, "bucket"), arg(argument, "minutes"), arg(argument, "ordinal"));
    if occasion_problem(&bucket, &minutes, &ordinal) {
        return Ok(refused_here(Refusal::OccasionInvalid, runtime));
    }
    let made = if capability == CREDIT {
        let repeat = argument.get("repeat").cloned().unwrap_or(Value::Bool(false));
        let ask_first = argument.get("ask_first").cloned().unwrap_or(Value::Bool(false));
        if !is_bool(&repeat)
            || !is_bool(&ask_first)
            || argument.contains_key("words")
            || argument.contains_key("thread_id")
        {
            return Ok(refused_here(Refusal::InvalidRequest, runtime));
        }
        call(
            runtime,
            "add_reset_rule",
            &[text(CREDIT), bucket, minutes, ordinal],
            &[("repeat", repeat), ("ask_first", ask_first)],
        )
    } else {
        let (thread, words) = (arg(argument, "thread_id"), arg(argument, "words"));
        if car_machine::domain::ids::uuid_problem(&thread, false).is_some()
            || argument.contains_key("repeat")
            || argument.contains_key("ask_first")
        {
            return Ok(refused_here(Refusal::InvalidRequest, runtime));
        }
        if car_policy::classify::continuation::validate_prompt(&words).is_err()
            || length(&words) > words_limit(runtime)
        {
            return Ok(refused_here(Refusal::MessageRefused, runtime));
        }
        if switched_off(runtime, &thread) {
            return Ok(refused_here(Refusal::ConversationOff, runtime));
        }
        let record = text(&runtime.state.tokens.hex(32));
        call(
            runtime,
            "add_reset_rule",
            &[text(MESSAGE), bucket, minutes, ordinal],
            &[("thread_id", thread), ("words", words), ("record_id", record)],
        )
    };
    let rule = match made {
        Ok(rule) => rule,
        Err(error) => return state_refusal(runtime, error),
    };
    wake(runtime);
    Ok(object(vec![
        ("done", Value::Bool(true)),
        ("refusal", Value::Null),
        ("rule", rule),
        ("generation", generation(runtime)?),
    ]))
}

/// `cancel(runtime, rule, generation)`: advanced-reset-cancel.
pub fn cancel(runtime: &Runtime, rule: &Value, asked: &Value) -> Result<Value> {
    if !is_int(rule) {
        return Ok(refusal(Refusal::InvalidRequest));
    }
    if stale(runtime, asked) {
        return Ok(refused_here(Refusal::StaleGeneration, runtime));
    }
    let done = match call(
        runtime,
        "cancel_reset_rule",
        &[rule.clone()],
        &[("at", Value::Float(runtime.now()))],
    ) {
        Ok(done) => done,
        Err(error) => return state_refusal(runtime, error),
    };
    Ok(object(vec![
        ("done", Value::Bool(true)),
        ("refusal", Value::Null),
        ("rule", rule.clone()),
        ("withdrawing", Value::Bool(is(&done, "withdrawing"))),
    ]))
}

/// `go_on(runtime, rule, generation)`: advanced-reset-go-on.
pub fn go_on(runtime: &Runtime, rule: &Value, asked: &Value) -> Result<Value> {
    if !is_int(rule) {
        return Ok(refusal(Refusal::InvalidRequest));
    }
    if stale(runtime, asked) {
        return Ok(refused_here(Refusal::StaleGeneration, runtime));
    }
    let Value::Object(found) = call(runtime, "reset_rule", &[rule.clone()], &[])? else {
        return Ok(refused_here(Refusal::UnknownRule, runtime));
    };
    if !is(&get(&found, "state"), RuleState::Held.as_str()) {
        return Ok(refused_here(Refusal::UnknownRule, runtime));
    }
    let on_now = match get(&found, "capability") {
        Value::Str(text) => text.as_str().is_some_and(|text| on(runtime, text)),
        _ => false,
    };
    if !on_now {
        return Ok(refused_here(Refusal::NotOn, runtime));
    }
    let moved = call(
        runtime,
        "change_rule",
        &[rule.clone()],
        &[
            ("expect", text(RuleState::Held.as_str())),
            ("state", text(RuleState::Counting.as_str())),
            ("reason", Value::Null),
            ("base", Value::Null),
            ("adopted_at", Value::Null),
        ],
    );
    let moved = match moved {
        Ok(moved) => moved,
        Err(error) if error.is_state() => return Ok(refused_here(Refusal::StateUnavailable, runtime)),
        Err(error) => return Err(error),
    };
    if !pyval::truthy(&moved) {
        return Ok(refused_here(Refusal::UnknownRule, runtime));
    }
    wake(runtime);
    Ok(object(vec![
        ("done", Value::Bool(true)),
        ("refusal", Value::Null),
        ("rule", rule.clone()),
    ]))
}

/// `credit_now(runtime, argument)`: advanced-credit-now.
pub fn credit_now(runtime: &Runtime, argument: &Map) -> Result<Value> {
    if stale(runtime, &arg(argument, "generation")) {
        return Ok(refused_here(Refusal::StaleGeneration, runtime));
    }
    if !on(runtime, CREDIT) {
        return Ok(refused_here(Refusal::NotOn, runtime));
    }
    let family: (Value, Value);
    if argument.contains_key("rule") {
        let rule = arg(argument, "rule");
        let found = if is_int(&rule) {
            call(runtime, "reset_rule", &[rule], &[])?
        } else {
            Value::Null
        };
        let ready = match &found {
            Value::Object(found) => {
                is(&get(found, "capability"), CREDIT) && is(&get(found, "state"), RuleState::Ready.as_str())
            }
            _ => false,
        };
        if !ready {
            return Ok(refused_here(Refusal::UnknownRule, runtime));
        }
        family = (field(&found, "bucket"), field(&found, "minutes"));
    } else if argument.contains_key("bucket") || argument.contains_key("minutes") {
        family = (arg(argument, "bucket"), arg(argument, "minutes"));
        if occasion_problem(&family.0, &family.1, &int(1)) {
            return Ok(refused_here(Refusal::OccasionInvalid, runtime));
        }
    } else {
        let windows = state(runtime, "windows")?.windows()?;
        let full: Vec<&(Value, Value)> = windows
            .iter()
            .filter(|(_, row)| pyval::truthy(&get(row, "open_reset_at")) && pyval::truthy(&get(row, "open_full")))
            .map(|(key, _)| key)
            .collect();
        if full.len() != 1 {
            return Ok(refused_here(Refusal::OccasionInvalid, runtime));
        }
        family = full[0].clone();
    }
    let mut now = 0.0;
    let made = call(runtime, "add_reset_rule", &[text(CREDIT), family.0, family.1, int(0)], &[]).and_then(|rule| {
        now = runtime.now();
        call(
            runtime,
            "change_rule",
            &[rule.clone()],
            &[
                ("state", text(RuleState::Ready.as_str())),
                ("due_at", Value::Float(now)),
                ("reason", Value::Null),
            ],
        )
        .map(|_| rule)
    });
    let rule = match made {
        Ok(rule) => rule,
        Err(error) => return state_refusal(runtime, error),
    };
    wake(runtime);
    Ok(object(vec![
        ("done", Value::Bool(true)),
        ("refusal", Value::Null),
        ("rule", rule),
        ("expires_at", Value::Float(now + credits::USE_NOW)),
    ]))
}

/// `counts(runtime)`: what P10's status shows of the reset actions - counts only; empty where none waits.
pub fn counts(runtime: &Runtime) -> Map {
    let Ok(rules) = call(runtime, "reset_rules", &[], &[]) else {
        return Map::new();
    };
    let rules = list(&rules);
    if rules.is_empty() {
        return Map::new();
    }
    let count = |test: &dyn Fn(&Row) -> bool| int(rules.iter().filter(|rule| test(rule)).count() as i64);
    let mut map = Map::new();
    map.insert(Str::new("messages"), count(&|rule| is(&get(rule, "capability"), MESSAGE)));
    map.insert(Str::new("credit_rules"), count(&|rule| is(&get(rule, "capability"), CREDIT)));
    map.insert(
        Str::new("ready"),
        count(&|rule| is(&get(rule, "state"), RuleState::Ready.as_str())),
    );
    map
}

/// car-codex's reader of the system (`PolicyOs`), as every reader of a Codex home here is made in the product.
pub fn codex_os() -> crate::codex::turns::SharedOs {
    Arc::new(car_codex::system::PolicyOs)
}

/// A raise's class as the static name the state's errors carry.
pub fn class_of(class: &str) -> &'static str {
    match class {
        "OSError" => "OSError",
        "TypeError" => "TypeError",
        "ValueError" => "ValueError",
        "KeyError" => "KeyError",
        "AttributeError" => "AttributeError",
        "AdapterError" => "AdapterError",
        "TurnsUnavailable" => "TurnsUnavailable",
        _ => "ConfigError",
    }
}

/// `inuse.home(runtime.paths)`: the Codex home the watcher told, else CODEX_HOME's; the reference's raise where none.
pub fn codex_home(runtime: &Runtime) -> Result<String> {
    crate::engine::supervise::codex_home(&runtime.paths)
        .map_err(|raised| Error::python(class_of(&raised.class), "no Codex home"))
}
