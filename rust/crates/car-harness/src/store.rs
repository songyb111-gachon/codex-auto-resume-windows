//! The store's calls, through car-store (S1.2): this replaced S0.4's `state.rs` stand-in.
//!
//! `store.script` opens a `Store` the way the Python's `Store(home, migrate=..., check=..., clock=...)` does
//! and runs a list of operations on it, each `{"method", "args", "kwargs"}` with the Python method's own
//! name and arguments; every answer is what the reference's runner (tests/rustdiff/diffs_store.py) prints
//! for the same call: the value, with tuples and sets as lists (a set sorted), or `{"raised": class,
//! "message": text}`. `store.legacy` does the same with a `LegacyStore`, `store.downgrade` runs
//! `downgrade_state`, `store.open_state` runs `openstate.open_state` with a Windows stand-in.
//!
//! `ready` and `go`, when given, are paths: once the store is open the call writes `ready` and waits for
//! `go` to exist before its operations - so two processes, either implementation, can be made to claim
//! one record at the same moment.

use std::any::Any;
use std::path::{Path, PathBuf};
use std::time::Instant;

use car_machine::json::{Map, Str, Value};
use car_store::claims::{Claim, Correlate, Withdrawn};
use car_store::downgrade::downgrade_state_at;
use car_store::open::{AdapterError, OpenState, Opened, Windows, open_state};
use car_store::records::{Register, Update};
use car_store::seam::gates::{Limits, Vector};
use car_store::watcher::Beat;
use car_store::{Error, LegacyStore, Options, Row, Store};

type Answer = std::result::Result<Value, Error>;

fn type_error(message: &str) -> Error {
    Error::Python("TypeError", message.into())
}

/// One call's arguments: positional, then by keyword.
struct Call<'a> {
    args: &'a [Value],
    kwargs: Option<&'a Map>,
}

impl<'a> Call<'a> {
    fn of(operation: &'a Map) -> Call<'a> {
        let args = match operation.get("args") {
            Some(Value::Array(args)) => args.as_slice(),
            _ => &[],
        };
        let kwargs = match operation.get("kwargs") {
            Some(Value::Object(kwargs)) => Some(kwargs),
            _ => None,
        };
        Call { args, kwargs }
    }

    fn get(&self, index: usize, name: &str) -> Option<&'a Value> {
        self.args
            .get(index)
            .or_else(|| self.kwargs.and_then(|kwargs| kwargs.get(name)))
    }

    fn value(&self, index: usize, name: &str) -> Value {
        self.get(index, name).cloned().unwrap_or(Value::Null)
    }

    fn number(&self, index: usize, name: &str) -> Result<f64, Error> {
        self.optional_number(index, name)?
            .ok_or_else(|| type_error(&format!("{name} is required")))
    }

    fn optional_number(&self, index: usize, name: &str) -> Result<Option<f64>, Error> {
        match self.get(index, name) {
            None | Some(Value::Null) => Ok(None),
            Some(value @ (Value::Int(_) | Value::Float(_))) => Ok(car_store::value::number(value)),
            Some(_) => Err(type_error(&format!("{name} must be a number"))),
        }
    }

    fn text(&self, index: usize, name: &str) -> Result<String, Error> {
        self.optional_text(index, name)?
            .ok_or_else(|| type_error(&format!("{name} is required")))
    }

    fn text_or(&self, index: usize, name: &str, default: &str) -> Result<String, Error> {
        Ok(self
            .optional_text(index, name)?
            .unwrap_or_else(|| default.to_string()))
    }

    fn optional_text(&self, index: usize, name: &str) -> Result<Option<String>, Error> {
        match self.get(index, name) {
            None | Some(Value::Null) => Ok(None),
            Some(Value::Str(found)) => Ok(Some(found.as_str().unwrap_or_default().to_string())),
            Some(_) => Err(type_error(&format!("{name} must be a str"))),
        }
    }

    /// A bool argument; anything else is the store's own refusal of it.
    fn flag(&self, index: usize, name: &str, refusal: &str) -> Result<bool, Error> {
        match self.get(index, name) {
            Some(Value::Bool(on)) => Ok(*on),
            _ => Err(Error::store(refusal)),
        }
    }

    fn truthy(&self, index: usize, name: &str) -> bool {
        self.get(index, name).is_some_and(car_store::value::truthy)
    }

    fn int_or(&self, index: usize, name: &str, default: i64) -> i64 {
        match self.get(index, name) {
            Some(Value::Int(found)) => found.as_i64().unwrap_or(default),
            Some(Value::Bool(on)) => i64::from(*on),
            _ => default,
        }
    }

    fn row(&self, index: usize, name: &str) -> Result<Row, Error> {
        match self.get(index, name) {
            Some(Value::Object(found)) => Ok(found.clone()),
            _ => Err(type_error(&format!("{name} must be a dict"))),
        }
    }

    fn strings(&self, index: usize, name: &str) -> Vec<String> {
        match self.get(index, name) {
            Some(Value::Array(items)) => items
                .iter()
                .filter_map(|item| car_store::value::text(item).map(str::to_string))
                .collect(),
            _ => Vec::new(),
        }
    }

    fn values(&self, index: usize, name: &str) -> Vec<Value> {
        match self.get(index, name) {
            Some(Value::Array(items)) => items.clone(),
            _ => Vec::new(),
        }
    }

    fn pair(&self, index: usize, name: &str) -> Result<Option<(f64, f64)>, Error> {
        match self.get(index, name) {
            None | Some(Value::Null) => Ok(None),
            Some(Value::Array(pair)) if pair.len() == 2 => {
                match (
                    car_store::value::number(&pair[0]),
                    car_store::value::number(&pair[1]),
                ) {
                    (Some(a), Some(b)) => Ok(Some((a, b))),
                    _ => Err(type_error(&format!("{name} must be two numbers"))),
                }
            }
            Some(_) => Err(type_error(&format!("{name} must be two numbers"))),
        }
    }

    fn limits(&self, index: usize, name: &str) -> Result<Option<Limits>, Error> {
        let Some(found) = self.get(index, name) else {
            return Ok(None);
        };
        let Value::Object(found) = found else {
            return Ok(None);
        };
        let need = |key: &str| {
            found
                .get(key)
                .and_then(car_store::value::number)
                .ok_or_else(|| Error::Python("KeyError", format!("'{key}'")))
        };
        let maybe = |key: &str| found.get(key).and_then(car_store::value::number);
        Ok(Some(Limits {
            max_no_progress: need("max_no_progress")?,
            max_chain_continuations: need("max_chain_continuations")?,
            max_recovery_attempts: need("max_recovery_attempts")?,
            max_chain_seconds: maybe("max_chain_seconds"),
            managed_max_recovery_attempts: maybe("managed_max_recovery_attempts"),
        }))
    }

    fn gates(&self, index: usize, name: &str) -> Option<Vector> {
        let Some(Value::Object(found)) = self.get(index, name) else {
            return None;
        };
        let mut vector = Vector::default();
        for (gate, answer) in found {
            if let Value::Array(pair) = answer
                && let (Some(result), Some(reason)) = (
                    pair.first().and_then(car_store::value::text),
                    pair.get(1).and_then(car_store::value::text),
                )
            {
                vector.set(
                    gate.as_str().unwrap_or_default(),
                    (result.to_string(), reason.to_string()),
                );
            }
        }
        Some(vector)
    }

    fn claim(&self) -> Result<Claim, Error> {
        Ok(Claim {
            limits: self.limits(usize::MAX, "limits")?,
            gates: self.gates(usize::MAX, "gates"),
            quiet_until: self.optional_number(usize::MAX, "quiet_until")?,
            relaxed: self.optional_text(usize::MAX, "relaxed")?,
            resend: self.pair(usize::MAX, "resend")?,
            forced: self.truthy(usize::MAX, "forced"),
            caps: self.pair(usize::MAX, "caps")?,
        })
    }
}

fn rows(found: Vec<Row>) -> Value {
    Value::Array(found.into_iter().map(Value::Object).collect())
}

fn maybe_row(found: Option<Row>) -> Value {
    found.map_or(Value::Null, Value::Object)
}

fn claimed((granted, gate, reason): car_store::claims::Claimed) -> Value {
    let word = |found: Option<String>| found.map_or(Value::Null, Value::from);
    Value::Array(vec![Value::Bool(granted), word(gate), word(reason)])
}

fn answer((accepted, detail): car_store::actions::Answer) -> Value {
    Value::Array(vec![Value::Bool(accepted), detail])
}

const NOT_KEYWORDS: &[&str] = &["at", "actor", "event", "flags"];

/// One operation on an open store.
fn operate(store: &Store, method: &str, call: &Call<'_>) -> Answer {
    let k = || call.text(0, "interruption_id");
    Ok(match method {
        "schema_version" => Value::from(store.schema_version()?),
        "readable_from" => Value::from(store.readable_from()?),
        "pragma" => store.pragma(&call.text(0, "name")?)?,
        // policy
        "settings" => Value::Object(store.settings()?),
        "set_enabled" => {
            let enabled = call.flag(0, "enabled", "enabled must be boolean")?;
            store.set_enabled(enabled, call.number(1, "now")?)?;
            Value::Null
        }
        "set_observe_only" => Value::Bool(store.set_observe_only(call.flag(
            0,
            "observe_only",
            "observe_only must be boolean",
        )?)?),
        "thread_enabled" => Value::Bool(store.thread_enabled(&call.text(0, "thread_id")?)?),
        "disabled_threads" => Value::Array(store.disabled_threads()?),
        "set_thread_enabled" => {
            let thread = call.text(0, "thread_id")?;
            car_store::validate::uuid_text(&thread, "thread_id")?;
            let enabled = call.flag(1, "enabled", "enabled must be boolean")?;
            store.set_thread_enabled(
                &thread,
                enabled,
                &call.text_or(usize::MAX, "actor", "engine")?,
                call.optional_number(usize::MAX, "at")?,
            )?;
            Value::Null
        }
        "thread_tier" => store.thread_tier(&call.text(0, "thread_id")?)?,
        "thread_tiers" => Value::Object(store.thread_tiers()?),
        "set_thread_tier" => Value::Object(store.set_thread_tier(
            &call.text(0, "thread_id")?,
            &call.value(1, "tier"),
            call.number(2, "now")?,
            &call.text_or(3, "actor", "gui")?,
        )?),
        "enrol_conversation" => Value::Bool(store.enrol_conversation(
            &call.text(0, "thread_id")?,
            &call.value(1, "tier"),
            call.number(2, "now")?,
        )?),
        "hold_changed" => Value::Bool(store.hold_changed(
            &k()?,
            &call.value(1, "task_print"),
            call.number(2, "now")?,
            &call.text_or(3, "actor", "engine")?,
        )?),
        "hold_waiting" => Value::from(store.hold_waiting(
            &call.strings(0, "interruption_ids"),
            &call.text(1, "hold")?,
            call.number(2, "now")?,
            &call.text_or(3, "actor", "gui")?,
        )?),
        // records
        "register" => {
            let options = Register {
                state: call.text_or(usize::MAX, "state", "waiting_reset")?,
                next_retry_at: call.optional_number(usize::MAX, "next_retry_at")?,
                owner_id: call.optional_text(usize::MAX, "owner_id")?,
                failed_turn_progress: call.value(usize::MAX, "failed_turn_progress"),
                legacy_carry: call.value(usize::MAX, "legacy_carry"),
                limits: call.limits(usize::MAX, "limits")?,
                hold: call.value(usize::MAX, "hold"),
                task_print: call.value(usize::MAX, "task_print"),
                context_tokens: call.value(usize::MAX, "context_tokens"),
                home_key: call
                    .get(usize::MAX, "home_key")
                    .cloned()
                    .unwrap_or_else(|| Value::from("")),
            };
            Value::Bool(store.register(
                &call.row(0, "record")?,
                call.number(1, "now")?,
                &options,
            )?)
        }
        "claimed_on_thread" => rows(store.claimed_on_thread(&call.text(0, "thread_id")?)?),
        "chain_parent" => maybe_row(store.chain_parent(
            &call.text(0, "thread_id")?,
            &call.text(1, "turn_id")?,
            call.optional_text(2, "owner_id")?.as_deref(),
        )?),
        "get" => maybe_row(store.get(&k()?)?),
        "all_records" => rows(store.all_records()?),
        "records_in" => rows(store.records_in(
            &call.strings(0, "states"),
            call.optional_text(1, "home_key")?.as_deref(),
        )?),
        "home_keys" => Value::Array(store.home_keys()?),
        "cancel_home" => Value::from(store.cancel_home(
            &call.text(0, "home_key")?,
            call.number(1, "now")?,
            &call.text(2, "reason")?,
        )?),
        "pending" => rows(store.pending()?),
        "failure_marks" => Value::Object(store.failure_marks()?),
        "history" => rows(store.history(
            call.truthy(0, "include_hidden"),
            call.int_or(1, "limit", 500),
        )?),
        "update" => {
            let mut changes = Map::new();
            if let Some(kwargs) = call.kwargs {
                for (name, value) in kwargs {
                    if !NOT_KEYWORDS.contains(&name.as_str().unwrap_or_default()) {
                        changes.insert(name.clone(), value.clone());
                    }
                }
            }
            let options = Update {
                at: call.optional_number(usize::MAX, "at")?,
                actor: call.text_or(usize::MAX, "actor", "engine")?,
                event: call.optional_text(usize::MAX, "event")?,
                flags: call.int_or(usize::MAX, "flags", 0),
            };
            store.update(&k()?, &changes, &options)?;
            Value::Null
        }
        // claims
        "recent_claims" => Value::Array(
            store.recent_claims(&call.text(0, "thread_id")?, call.number(1, "since")?)?,
        ),
        "recent_claim_count" => Value::from(
            store.recent_claim_count(&call.text(0, "thread_id")?, call.number(1, "since")?)?,
        ),
        "others_in_flight" => Value::from(
            store.others_in_flight(&call.text(0, "thread_id")?, &call.text(1, "exclude")?)?,
        ),
        "submission_guard" => Value::Bool(store.submission_guard(&k()?, |permitted| permitted)?),
        "reserve" => Value::Bool(store.reserve(&k()?, call.number(1, "now")?, &call.claim()?)?),
        "reserve_detailed" => {
            claimed(store.reserve_detailed(&k()?, call.number(1, "now")?, &call.claim()?)?)
        }
        "record_gates" => {
            store.record_gates(
                &k()?,
                &call.gates(1, "gates").unwrap_or_default(),
                call.number(2, "now")?,
            )?;
            Value::Null
        }
        "record_would_send" => Value::Bool(store.record_would_send(
            &k()?,
            &call.gates(1, "gates").unwrap_or_default(),
            call.number(2, "now")?,
            call.number(3, "next_retry_at")?,
        )?),
        "release_claim" => Value::Bool(store.release_claim(
            &k()?,
            &call.text(1, "target")?,
            &call.text(2, "reason")?,
            call.number(3, "now")?,
            call.optional_number(usize::MAX, "next_retry_at")?,
            &call.text_or(usize::MAX, "actor", "engine")?,
        )?),
        "correlate" => {
            let options = Correlate {
                client_id: call.value(usize::MAX, "client_id"),
                status: call.value(usize::MAX, "status"),
                state: call.text_or(usize::MAX, "state", "turn_started")?,
                reason: call.value(usize::MAX, "reason"),
                after_user_work: call.truthy(usize::MAX, "after_user_work"),
                user_joined: call.truthy(usize::MAX, "user_joined"),
                extra_event: call.optional_text(usize::MAX, "extra_event")?,
            };
            Value::Bool(store.correlate(
                &k()?,
                &call.text(1, "recovery_turn_id")?,
                call.number(2, "now")?,
                &options,
            )?)
        }
        "release_withdrawn" => {
            let proofs = Withdrawn {
                window: call.number(usize::MAX, "window")?,
                later_turn: call.truthy(usize::MAX, "later_turn"),
                marker_rows: call.int_or(usize::MAX, "marker_rows", 0),
                row_present: call.truthy(usize::MAX, "row_present"),
                fresh: call.truthy(usize::MAX, "fresh"),
                target: call.text(usize::MAX, "target")?,
                next_retry_at: call.optional_number(usize::MAX, "next_retry_at")?,
            };
            Value::Bool(store.release_withdrawn(&k()?, call.number(1, "now")?, &proofs)?)
        }
        // journal
        "events" => rows(
            store.events(
                call.optional_text(0, "interruption_id")?.as_deref(),
                call.optional_text(usize::MAX, "chain_origin_id")?
                    .as_deref(),
                call.int_or(usize::MAX, "limit", 500),
            )?,
        ),
        "usage_checks_shown" => Value::Object(store.usage_checks_shown(call.number(0, "since")?)?),
        // actions
        "cancel_interruption" => maybe_row(store.cancel_interruption(
            &k()?,
            call.number(1, "now")?,
            &call.text_or(2, "actor", "gui")?,
        )?),
        "cancel_waiting" => Value::Array(store.cancel_waiting(
            &call.values(0, "interruption_ids"),
            call.number(1, "now")?,
            &call.text(2, "reason")?,
        )?),
        "cancel_thread" => {
            store.cancel_thread(
                &call.text(0, "thread_id")?,
                call.number(1, "now")?,
                &call.text_or(2, "actor", "gui")?,
            )?;
            Value::Null
        }
        "restore_budget" | "restore_budget_detailed" => {
            let found = store.restore_budget_detailed(
                &k()?,
                call.number(1, "now")?,
                &call.text_or(usize::MAX, "actor", "gui")?,
                call.int_or(
                    usize::MAX,
                    "max_resets",
                    car_store::actions::MAX_BUDGET_RESETS,
                ),
            )?;
            if method == "restore_budget" {
                Value::Bool(found.0)
            } else {
                answer(found)
            }
        }
        "request_retry_now" => answer(store.request_retry_now(
            &k()?,
            call.number(1, "now")?,
            &call.text_or(2, "actor", "gui")?,
        )?),
        "rescan_apply" => Value::Bool(store.rescan_apply(
            &k()?,
            &call.row(1, "seen")?,
            &call.text(2, "outcome")?,
            call.number(3, "now")?,
            &call.value(usize::MAX, "reason"),
            &call.text_or(usize::MAX, "actor", "gui")?,
        )?),
        "hide_history" => Value::Object(
            store.hide_history(call.number(0, "now")?, &call.text_or(1, "actor", "gui")?)?,
        ),
        // schedule
        "postpone" => answer(store.postpone(
            &k()?,
            &call.text(1, "thread_id")?,
            &call.value(2, "until"),
            call.number(3, "now")?,
            &call.text_or(4, "actor", "gui")?,
        )?),
        "unpostpone" => answer(store.unpostpone(
            &k()?,
            &call.text(1, "thread_id")?,
            call.number(2, "now")?,
            &call.text_or(3, "actor", "gui")?,
        )?),
        "open_objection_window" => Value::Bool(store.open_objection_window(
            &k()?,
            call.number(1, "until")?,
            call.number(2, "now")?,
        )?),
        "release_hold" => answer(store.release_hold(
            &k()?,
            &call.text(1, "thread_id")?,
            call.number(2, "now")?,
            &call.text_or(3, "actor", "gui")?,
        )?),
        "ask_usage_check" => Value::Bool(store.ask_usage_check(
            &k()?,
            call.number(1, "now")?,
            &call.text_or(2, "source", "retry_now")?,
        )?),
        "usage_checks_asked" => Value::Object(store.usage_checks_asked(call.number(0, "now")?)?),
        "usage_not_checked" => {
            store.usage_not_checked(&k()?, call.number(1, "now")?, &call.text(2, "why")?)?;
            Value::Null
        }
        "usage_check_taken" => store
            .usage_check_taken(&k()?)
            .map_or(Value::Null, Value::from),
        "ask_early_check" => Value::Bool(store.ask_early_check(call.number(0, "now")?)?),
        "early_check_asked" => Value::Bool(store.early_check_asked(call.number(0, "now")?)),
        "early_check_taken" => {
            store.early_check_taken();
            Value::Null
        }
        "usage_checked" => maybe_row(store.usage_checked(
            &k()?,
            call.number(1, "now")?,
            &call.text(2, "read")?,
            &call.text_or(3, "source", "retry_now")?,
        )?),
        // the watcher, the notices, the counts
        "heartbeat" => {
            let usage = match call.get(usize::MAX, "usage") {
                Some(Value::Array(pair)) if pair.len() == 2 => {
                    Some((pair[0].clone(), pair[1].clone()))
                }
                _ => None,
            };
            let beat = Beat {
                pid: call.int_or(usize::MAX, "pid", 0),
                session_id: call.text(usize::MAX, "session_id")?,
                started_at: call.value(usize::MAX, "started_at"),
                ok: call.truthy(usize::MAX, "ok"),
                engine_state: call.text(usize::MAX, "engine_state")?,
                code_version: call.text(usize::MAX, "code_version")?,
                usage,
                awake_since: call.value(usize::MAX, "awake_since"),
                memory_peak: call.value(usize::MAX, "memory_peak"),
                sign_in: call.value(usize::MAX, "sign_in"),
                booted_at: call.value(usize::MAX, "booted_at"),
                homes: call.value(usize::MAX, "homes"),
            };
            store.heartbeat(call.number(0, "now")?, &beat)?;
            Value::Null
        }
        "watcher_ended" => {
            Value::Bool(store.watcher_ended(call.number(0, "now")?, &call.text(1, "end")?)?)
        }
        "watcher_status" => maybe_row(store.watcher_status()?),
        "raise_notice" => Value::Bool(store.raise_notice(
            &call.text(0, "key")?,
            &call.text(1, "thread_id")?,
            &call.text(2, "kind")?,
            call.number(3, "now")?,
        )?),
        "status_counts" => Value::Object(store.status_counts()?),
        "statistics" => Value::Object(store.statistics(
            call.optional_number(0, "since")?.unwrap_or(0.0),
            call.optional_number(1, "until")?,
        )?),
        _ => {
            return Err(Error::Python(
                "AttributeError",
                format!("'Store' object has no attribute '{method}'"),
            ));
        }
    })
}

/// One operation on a legacy store.
fn operate_legacy(store: &LegacyStore, method: &str, call: &Call<'_>) -> Answer {
    Ok(match method {
        "pragma" => store.pragma(&call.text(0, "name")?)?,
        "settings" => Value::Object(store.settings()?),
        "set_enabled" => {
            let enabled = call.flag(0, "enabled", "enabled must be boolean")?;
            store.set_enabled(enabled, call.number(1, "now")?)?;
            Value::Null
        }
        "thread_enabled" => Value::Bool(store.thread_enabled(&call.text(0, "thread_id")?)?),
        "set_thread_enabled" => {
            let thread = call.text(0, "thread_id")?;
            car_store::validate::uuid_text(&thread, "thread_id")?;
            store
                .set_thread_enabled(&thread, call.flag(1, "enabled", "enabled must be boolean")?)?;
            Value::Null
        }
        "cancel_thread" => {
            store.cancel_thread(&call.text(0, "thread_id")?, call.number(1, "now")?)?;
            Value::Null
        }
        "status_counts" => Value::Object(store.status_counts()?),
        "thread_of" => store.thread_of(&call.text(0, "interruption_id")?)?,
        "disabled_threads" => Value::Array(store.disabled_threads()?),
        "version" => Value::from(store.version),
        _ => {
            return Err(Error::Python(
                "AttributeError",
                format!("'LegacyStore' object has no attribute '{method}'"),
            ));
        }
    })
}

/// `{"raised": class, "message": text}`.
pub fn raised(error: &Error) -> Value {
    let mut map = Map::new();
    map.insert(Str::new("raised"), Value::from(error.class()));
    map.insert(Str::new("message"), Value::from(error.message()));
    Value::Object(map)
}

fn settle(found: Answer) -> Value {
    found.unwrap_or_else(|error| raised(&error))
}

fn wait_for_go(request: &Map) {
    let path = |name: &str| {
        request
            .get(name)
            .and_then(car_store::value::text)
            .map(PathBuf::from)
    };
    if let Some(ready) = path("ready") {
        let _ = std::fs::write(ready, b"ready");
    }
    if let Some(go) = path("go") {
        let started = Instant::now();
        while !go.exists() && started.elapsed().as_secs() < 120 {
            std::thread::sleep(std::time::Duration::from_millis(1));
        }
    }
}

fn operations(request: &Map) -> Vec<&Map> {
    match request.get("ops") {
        Some(Value::Array(ops)) => ops
            .iter()
            .filter_map(|op| match op {
                Value::Object(op) => Some(op),
                _ => None,
            })
            .collect(),
        _ => Vec::new(),
    }
}

fn method_of(operation: &Map) -> String {
    operation
        .get("method")
        .and_then(car_store::value::text)
        .unwrap_or_default()
        .to_string()
}

fn timed(operation: &Map, run: impl FnOnce() -> Value) -> Value {
    let started = Instant::now();
    let value = run();
    if !matches!(operation.get("timed"), Some(Value::Bool(true))) {
        return value;
    }
    let mut map = Map::new();
    map.insert(Str::new("value"), value);
    map.insert(
        Str::new("seconds"),
        Value::Float(started.elapsed().as_secs_f64()),
    );
    Value::Object(map)
}

/// `store.script`: {open, migrated_from, results}.
pub fn script(home: &Path, request: &Map) -> Value {
    let open = match request.get("open") {
        Some(Value::Object(open)) => open.clone(),
        _ => Map::new(),
    };
    let flag = |name: &str, default: bool| match open.get(name) {
        Some(Value::Bool(on)) => *on,
        _ => default,
    };
    let clock = open.get("clock").and_then(car_store::value::number);
    let options = Options {
        migrate: flag("migrate", false),
        check: flag("check", true),
        clock: match clock {
            Some(fixed) => Box::new(move || fixed),
            None => Box::new(car_store::session::wall_clock),
        },
        links: crate::links::for_store(),
    };
    let mut out = Map::new();
    let store = match Store::open_with(home, options) {
        Ok(store) => {
            out.insert(Str::new("open"), Value::Null);
            store
        }
        Err(error) => {
            out.insert(Str::new("open"), raised(&error));
            out.insert(Str::new("migrated_from"), Value::Null);
            out.insert(Str::new("results"), Value::Array(Vec::new()));
            return Value::Object(out);
        }
    };
    out.insert(
        Str::new("migrated_from"),
        store.migrated_from.map_or(Value::Null, Value::from),
    );
    wait_for_go(request);
    let results = operations(request)
        .into_iter()
        .map(|operation| {
            timed(operation, || {
                settle(operate(&store, &method_of(operation), &Call::of(operation)))
            })
        })
        .collect();
    out.insert(Str::new("results"), Value::Array(results));
    Value::Object(out)
}

/// `store.legacy`: {open, results}.
pub fn legacy(home: &Path, request: &Map) -> Value {
    let mut out = Map::new();
    let store = match LegacyStore::open(home, &crate::links::Probe) {
        Ok(store) => {
            out.insert(Str::new("open"), Value::Null);
            store
        }
        Err(error) => {
            out.insert(Str::new("open"), raised(&error));
            out.insert(Str::new("results"), Value::Array(Vec::new()));
            return Value::Object(out);
        }
    };
    let results = operations(request)
        .into_iter()
        .map(|operation| {
            settle(operate_legacy(
                &store,
                &method_of(operation),
                &Call::of(operation),
            ))
        })
        .collect();
    out.insert(Str::new("results"), Value::Array(results));
    Value::Object(out)
}

/// `store.downgrade`: the report, or what was raised.
pub fn downgrade(home: &Path, request: &Map) -> Value {
    let target = match request.get("target") {
        Some(Value::Int(target)) => target.as_i64().unwrap_or(0),
        _ => 0,
    };
    let now = request
        .get("now")
        .and_then(car_store::value::number)
        .unwrap_or_else(car_store::session::wall_clock);
    settle(downgrade_state_at(home, target, now, &crate::links::Probe).map(Value::Object))
}

/// The Windows stand-in `store.open_state` is given: what an install lock and the watcher's mutex say.
struct StandIn {
    install_in_progress: Option<bool>,
    mutex_free: bool,
}

impl Windows for StandIn {
    fn install_in_progress(&self) -> Option<bool> {
        self.install_in_progress
    }

    fn watcher_mutex(&self, _state_dir: &Path) -> std::result::Result<Box<dyn Any>, AdapterError> {
        if self.mutex_free {
            Ok(Box::new(()))
        } else {
            Err(AdapterError("held".into()))
        }
    }

    fn links(&self) -> std::sync::Arc<dyn car_store::session::Links> {
        crate::links::for_store()
    }
}

/// `store.open_state`: what was opened, and its schema - or what was raised.
pub fn open(home: &Path, request: &Map) -> Value {
    let flag = |name: &str| matches!(request.get(name), Some(Value::Bool(true)));
    let windows = StandIn {
        install_in_progress: match request.get("install_in_progress") {
            Some(Value::Bool(on)) => Some(*on),
            _ => None,
        },
        mutex_free: flag("mutex_free"),
    };
    let superseded_answer = flag("superseded");
    let superseded = move || superseded_answer;
    let legacy = request
        .get("legacy")
        .and_then(car_store::value::text)
        .unwrap_or("never")
        .to_string();
    let options = OpenState {
        legacy: &legacy,
        reducing: flag("reducing"),
        check: flag("check"),
        upgrade_failed: None,
        hold_while_installing: flag("hold_while_installing"),
        superseded: if request.contains_key("superseded") {
            Some(&superseded)
        } else {
            None
        },
        clock: request.get("clock").and_then(car_store::value::number),
    };
    settle(open_state(home, &windows, &options).and_then(|opened| {
        let mut map = Map::new();
        match opened {
            Opened::Store(store) => {
                map.insert(Str::new("opened"), Value::from("Store"));
                map.insert(Str::new("version"), Value::from(store.schema_version()?));
            }
            Opened::Legacy(store) => {
                map.insert(Str::new("opened"), Value::from("LegacyStore"));
                map.insert(Str::new("version"), Value::from(store.version));
            }
        }
        Ok(Value::Object(map))
    }))
}

/// `store.record_state`: the state of one record, opened by car-store (S0.4's call, kept).
pub fn record_state(home: &Path, interruption_id: &str) -> Answer {
    let store = Store::open(home, crate::links::for_store())?;
    Ok(store.get(interruption_id)?.map_or(Value::Null, |row| {
        car_store::value::get(&row, "state").clone()
    }))
}

/// `store.schema_version`.
pub fn schema_version(home: &Path) -> Answer {
    Ok(Value::from(
        Store::open(home, crate::links::for_store())?.schema_version()?,
    ))
}
