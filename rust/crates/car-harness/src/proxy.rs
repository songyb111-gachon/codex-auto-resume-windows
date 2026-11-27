//! The scenario proxy's engine (S4.2): car-engine driven by `tests/rustdiff/engineproxy.py`, the `Engine` the frozen
//! scenario modules build under `CODEX_AR_CORE=rust`, with EVERYTHING it is handed asked back over the pipe.
//!
//! The engine traces (`engine.rs`) give car-engine car-store and car-codex of its own; here the store, the reader of
//! Codex and the backend stay the test's Python objects - a test's `Store`, `LocalSource`, `SimBackend`, a spy or a
//! stand-in - and so do the clock, the log, the notifier, the words for this time, jitter's draw, `time.localtime` and
//! the environment: every call the engine makes of them goes out as one line `{"ask": name, "args": [...]}` and is
//! answered by one line `{"value": v}` or `{"raise": class}`.
//!
//! A call of ours that takes a callable (`once_words.prune(keep)`) is asked with the callable kept here: while the
//! answer is awaited, each line `{"callback": [args]}` from the Python side is the callable called, answered
//! `{"value": v}` / `{"raise": class}` (and it may ask again, nested).
//!
//! * `proxy.open` {session, options, home_key, language, once_words}: one engine per session, in one process for the
//!   whole test run. A call arriving while an answer is awaited is answered nested (`read_value`), so an engine's
//!   backend may tick another engine while it waits, as test_engine's 16 does.
//! * `proxy.close` {session, sessions}: the engines the Python side let go.
//! * `proxy.call` {session, method, args, sync}: `sync` is what the Python side holds of the engine's attributes (`options`,
//!   `retiring`, `once_words`, `home_key`), set before the call; the reply is {result} or {raised}, and `state`, what
//!   the Python side mirrors after it (`options`, `policy_values`, `detection_failed`, `handed_waits`, `usage_cached`).

use std::cell::RefCell;
use std::collections::{BTreeSet, HashMap};
use std::io::{BufRead, Write};
use std::panic::{AssertUnwindSafe, catch_unwind};
use std::rc::Rc;
use std::sync::Arc;

use car_engine::seam::{Claimed, Correlate, Withdrawn};
use car_engine::{Backend, Claim, Engine, Given, LaunchGuard, OnceWords, Options, Register};
use car_machine::json::{Map, Str, Value, to_string};
use car_machine::pyval::Py;
use car_policy::classify::clock::{LocalClock, Tm};
use car_policy::classify::gates::{Limits, Vector};
use car_policy::classify::value::{arithmetic, text, truthy};
use car_policy::plug::Guarded;
use car_policy::settings::managed::Managed;

use crate::object;

#[path = "proxyplug.rs"]
mod plug;
use crate::policy::PlatformOs;

/// A Python exception class as a `'static` word.
fn class(name: &str) -> &'static str {
    match name {
        "OSError" => "OSError",
        "RuntimeError" => "RuntimeError",
        "ValueError" => "ValueError",
        "TypeError" => "TypeError",
        "KeyError" => "KeyError",
        "AttributeError" => "AttributeError",
        "StoreError" => "StoreError",
        "Exception" => "Exception",
        other => Box::leak(other.to_owned().into_boxed_str()),
    }
}

fn write_line(value: &Value) -> Py<()> {
    let text = to_string(value, &car_machine::json::Options::wire())
        .or_else(|_| to_string(value, &car_machine::json::Options::new()))
        .map_err(|_| "ValueError")?;
    let mut out = std::io::stdout().lock();
    writeln!(out, "{text}").map_err(|_| "OSError")?;
    out.flush().map_err(|_| "OSError")
}

/// The next line from the Python side. A request line (`{"id", "call": "proxy.*"}`) read while an answer is awaited is
/// another engine's call made from inside the answer (test_engine's 16: a backend that ticks a second engine while the
/// first one's send waits): it is answered here, nested, and the wait goes on.
fn read_value() -> Py<Map> {
    loop {
        let mut line = String::new();
        let read = std::io::stdin()
            .lock()
            .read_line(&mut line)
            .map_err(|_| "OSError")?;
        if read == 0 {
            return Err("OSError");
        }
        let line = line.trim_start_matches('\u{feff}').trim();
        if line.is_empty() {
            continue;
        }
        let Ok(Value::Object(answer)) = car_machine::compat::loads(line) else {
            return Err("OSError");
        };
        if answer.contains_key("call") {
            let (id, reply) = self::line(line).unwrap_or((
                Value::Null,
                crate::rejected("this call is not ported", crate::NOT_PORTED),
            ));
            write_line(&object([("id", id), ("reply", reply)]))?;
            continue;
        }
        return Ok(answer);
    }
}

fn answered(found: Py<Value>) -> Value {
    match found {
        Ok(value) => object([("value", value)]),
        Err(raised) => object([("raise", Value::from(raised))]),
    }
}

/// One question to the Python side, a callable it may call meanwhile.
pub fn ask_with(
    name: &str,
    args: Vec<Value>,
    callback: &mut dyn FnMut(&[Value]) -> Py<Value>,
) -> Py<Value> {
    write_line(&object([
        ("ask", Value::from(name)),
        ("args", Value::Array(args)),
    ]))?;
    loop {
        let answer = read_value()?;
        if let Some(Value::Array(arguments)) = answer.get("callback") {
            let found = catch_unwind(AssertUnwindSafe(|| callback(arguments)))
                .unwrap_or(Err("RuntimeError"));
            write_line(&answered(found))?;
            continue;
        }
        if let Some(Value::Str(raised)) = answer.get("raise") {
            return Err(class(raised.as_str().unwrap_or("Exception")));
        }
        // A seam that panics (engineproxy's `Panic`): what a panic in S3.3's transport, car-codex or car-policy would
        // be at this call, so a test can hold each boundary D15 asks for.
        if answer.contains_key("panic") {
            panic!("the Python side asked this call to panic: {name}");
        }
        return Ok(answer.get("value").cloned().unwrap_or(Value::Null));
    }
}

/// One question to the Python side.
pub fn ask(name: &str, args: Vec<Value>) -> Py<Value> {
    ask_with(name, args, &mut |_| Err("TypeError"))
}

// ------------------------------------------------------------------ values, both ways
fn s(text: &str) -> Value {
    Value::from(text)
}

fn f(number: f64) -> Value {
    Value::Float(number)
}

fn opt_f(number: Option<f64>) -> Value {
    number.map_or(Value::Null, Value::Float)
}

fn opt_s(text: Option<&str>) -> Value {
    text.map_or(Value::Null, Value::from)
}

/// A number the reference holds as an `int` (a budget, a count) written as one where it is whole.
fn whole(number: f64) -> Value {
    if number.is_finite() && number.fract() == 0.0 && number.abs() < 9.0e15 {
        Value::from(number as i64)
    } else {
        Value::Float(number)
    }
}

fn strings(items: &[String]) -> Value {
    Value::Array(items.iter().map(|item| s(item)).collect())
}

fn set_of(items: &BTreeSet<String>) -> Value {
    Value::Array(items.iter().map(|item| s(item)).collect())
}

fn gates(vector: &Vector) -> Value {
    let mut map = Map::new();
    for (name, (result, reason)) in &vector.0 {
        map.insert(
            name.as_str().into(),
            Value::Array(vec![s(result), s(reason)]),
        );
    }
    Value::Object(map)
}

fn limits(limits: &Limits) -> Value {
    let mut map = Map::new();
    map.insert(
        "max_recovery_attempts".into(),
        whole(limits.max_recovery_attempts),
    );
    map.insert("max_no_progress".into(), whole(limits.max_no_progress));
    map.insert(
        "max_chain_continuations".into(),
        whole(limits.max_chain_continuations),
    );
    if let Some(seconds) = limits.max_chain_seconds {
        map.insert("max_chain_seconds".into(), whole(seconds));
    }
    if let Some(count) = limits.managed_max_recovery_attempts {
        map.insert("managed_max_recovery_attempts".into(), whole(count));
    }
    Value::Object(map)
}

fn kwargs(pairs: Vec<(&str, Value)>) -> Value {
    let mut map = Map::new();
    for (name, value) in pairs {
        map.insert(name.into(), value);
    }
    Value::Object(map)
}

fn boolean(found: Py<Value>) -> Py<bool> {
    found.map(|value| truthy(&value))
}

fn integer(found: Py<Value>) -> Py<i64> {
    let value = found?;
    match &value {
        Value::Bool(flag) => Ok(i64::from(*flag)),
        _ => car_engine::py::int_of(&value),
    }
}

fn map(found: Py<Value>) -> Py<Map> {
    match found? {
        Value::Object(map) => Ok(map),
        _ => Err("TypeError"),
    }
}

fn opt_map(found: Py<Value>) -> Py<Option<Map>> {
    match found? {
        Value::Null => Ok(None),
        Value::Object(map) => Ok(Some(map)),
        _ => Err("TypeError"),
    }
}

fn maps(found: Py<Value>) -> Py<Vec<Map>> {
    match found? {
        Value::Array(items) => items
            .into_iter()
            .map(|item| match item {
                Value::Object(map) => Ok(map),
                _ => Err("TypeError"),
            })
            .collect(),
        _ => Err("TypeError"),
    }
}

fn values(found: Py<Value>) -> Py<Vec<Value>> {
    match found? {
        Value::Array(items) => Ok(items),
        _ => Err("TypeError"),
    }
}

fn texts(found: Py<Value>) -> Py<Vec<String>> {
    Ok(values(found)?
        .iter()
        .filter_map(|item| text(item).map(str::to_owned))
        .collect())
}

// ------------------------------------------------------------------ the store
/// The test's store, asked back: `store.<method>` with the reference's arguments.
pub struct AskStore;

fn store(method: &str, args: Vec<Value>) -> Py<Value> {
    ask(&format!("store.{method}"), args)
}

impl car_scheduler::Store for AskStore {
    fn get(&self, interruption_id: &str) -> Py<Option<Map>> {
        opt_map(store("get", vec![s(interruption_id)]))
    }
    fn update(
        &self,
        interruption_id: &str,
        changes: &Map,
        at: Option<f64>,
        event: Option<&str>,
        flags: i64,
    ) -> Py<()> {
        store(
            "update",
            vec![
                s(interruption_id),
                Value::Object(changes.clone()),
                opt_f(at),
                opt_s(event),
                Value::from(flags),
            ],
        )
        .map(|_| ())
    }
    fn thread_enabled(&self, thread_id: &str) -> Py<bool> {
        boolean(store("thread_enabled", vec![s(thread_id)]))
    }
    fn settings(&self) -> Py<Map> {
        map(store("settings", Vec::new()))
    }
    fn correlate(
        &self,
        interruption_id: &str,
        recovery_turn_id: &str,
        now: f64,
        options: &Correlate,
    ) -> Py<bool> {
        boolean(store(
            "correlate",
            vec![
                s(interruption_id),
                s(recovery_turn_id),
                f(now),
                kwargs(vec![
                    ("client_id", options.client_id.clone()),
                    ("status", options.status.clone()),
                    ("state", s(&options.state)),
                    ("reason", options.reason.clone()),
                    ("after_user_work", Value::Bool(options.after_user_work)),
                    ("user_joined", Value::Bool(options.user_joined)),
                    ("extra_event", opt_s(options.extra_event.as_deref())),
                ]),
            ],
        ))
    }
    fn release_withdrawn(&self, interruption_id: &str, now: f64, proofs: &Withdrawn) -> Py<bool> {
        boolean(store(
            "release_withdrawn",
            vec![
                s(interruption_id),
                f(now),
                kwargs(vec![
                    ("window", whole(proofs.window)),
                    ("later_turn", Value::Bool(proofs.later_turn)),
                    ("marker_rows", Value::from(proofs.marker_rows)),
                    ("row_present", Value::Bool(proofs.row_present)),
                    ("fresh", Value::Bool(proofs.fresh)),
                    ("target", s(&proofs.target)),
                    ("next_retry_at", opt_f(proofs.next_retry_at)),
                ]),
            ],
        ))
    }
    fn records_in(&self, states: &[&str], home_key: Option<&str>) -> Py<Vec<Map>> {
        maps(store(
            "records_in",
            vec![
                Value::Array(states.iter().map(|state| s(state)).collect()),
                opt_s(home_key),
            ],
        ))
    }
}

impl car_engine::Store for AskStore {
    fn record_gates(&self, interruption_id: &str, vector: &Vector, now: f64) -> Py<()> {
        store(
            "record_gates",
            vec![s(interruption_id), gates(vector), f(now)],
        )
        .map(|_| ())
    }
    fn record_would_send(
        &self,
        interruption_id: &str,
        vector: &Vector,
        now: f64,
        next_retry_at: f64,
    ) -> Py<bool> {
        boolean(store(
            "record_would_send",
            vec![s(interruption_id), gates(vector), f(now), f(next_retry_at)],
        ))
    }
    fn submission_guard(
        &self,
        interruption_id: &str,
        body: &mut dyn FnMut(bool) -> Value,
    ) -> Py<Value> {
        // `with store.submission_guard(key) as permitted:` - entered on the Python side, `body` run here, then left.
        let permitted = boolean(store("guard_enter", vec![s(interruption_id)]))?;
        let found = catch_unwind(AssertUnwindSafe(|| body(permitted)));
        store("guard_exit", Vec::new())?;
        found.map_err(|_| "RuntimeError")
    }
    fn recent_claims(&self, thread_id: &str, since: f64) -> Py<Vec<Value>> {
        values(store("recent_claims", vec![s(thread_id), f(since)]))
    }
    fn recent_claim_count(&self, thread_id: &str, since: f64) -> Py<i64> {
        integer(store("recent_claim_count", vec![s(thread_id), f(since)]))
    }
    fn others_in_flight(&self, thread_id: &str, exclude: &str) -> Py<i64> {
        integer(store("others_in_flight", vec![s(thread_id), s(exclude)]))
    }
    fn reserve_detailed(&self, interruption_id: &str, now: f64, claim: &Claim) -> Py<Claimed> {
        let found = values(store(
            "reserve_detailed",
            vec![
                s(interruption_id),
                f(now),
                kwargs(vec![
                    ("limits", limits(&claim.limits)),
                    ("gates", gates(&claim.gates)),
                    (
                        "carried",
                        Value::Array(
                            claim
                                .carried
                                .iter()
                                .map(|point| s(point.as_str()))
                                .collect(),
                        ),
                    ),
                    ("quiet_until", opt_f(claim.quiet_until)),
                    ("relaxed", opt_s(claim.relaxed.as_deref())),
                    (
                        "resend",
                        claim
                            .resend
                            .map_or(Value::Null, |(a, b)| Value::Array(vec![whole(a), whole(b)])),
                    ),
                    ("forced", Value::Bool(claim.forced)),
                    (
                        "caps",
                        Value::Array(vec![whole(claim.caps.0), whole(claim.caps.1)]),
                    ),
                ]),
            ],
        ))?;
        let word = |index: usize| {
            found
                .get(index)
                .and_then(|value| text(value).map(str::to_owned))
        };
        Ok((found.first().is_some_and(truthy), word(1), word(2)))
    }
    fn release_claim(
        &self,
        interruption_id: &str,
        target: &str,
        reason: &str,
        now: f64,
        next_retry_at: Option<f64>,
    ) -> Py<bool> {
        boolean(store(
            "release_claim",
            vec![
                s(interruption_id),
                s(target),
                s(reason),
                f(now),
                opt_f(next_retry_at),
            ],
        ))
    }
    fn claimed_on_thread(&self, thread_id: &str) -> Py<Vec<Map>> {
        maps(store("claimed_on_thread", vec![s(thread_id)]))
    }
    fn chain_parent(
        &self,
        thread_id: &str,
        turn_id: &str,
        owner_id: Option<&str>,
    ) -> Py<Option<Map>> {
        opt_map(store(
            "chain_parent",
            vec![s(thread_id), s(turn_id), opt_s(owner_id)],
        ))
    }
    fn register(&self, detection: &Map, now: f64, options: &Register) -> Py<bool> {
        boolean(store(
            "register",
            vec![
                Value::Object(detection.clone()),
                f(now),
                kwargs(vec![
                    ("state", s(&options.state)),
                    ("next_retry_at", f(options.next_retry_at)),
                    ("owner_id", opt_s(options.owner_id.as_deref())),
                    ("failed_turn_progress", options.failed_turn_progress.clone()),
                    ("legacy_carry", options.legacy_carry.clone()),
                    ("limits", limits(&options.limits)),
                    ("hold", options.hold.clone()),
                    ("home_key", s(&options.home_key)),
                    ("task_print", options.task_print.clone()),
                    ("context_tokens", options.context_tokens.clone()),
                ]),
            ],
        ))
    }
    fn thread_tier(&self, thread_id: &str) -> Py<Value> {
        store("thread_tier", vec![s(thread_id)])
    }
    fn enrol_conversation(&self, thread_id: &str, tier: &str, now: f64) -> Py<bool> {
        boolean(store(
            "enrol_conversation",
            vec![s(thread_id), s(tier), f(now)],
        ))
    }
    fn hold_changed(&self, interruption_id: &str, task_print: &Value, now: f64) -> Py<bool> {
        boolean(store(
            "hold_changed",
            vec![s(interruption_id), task_print.clone(), f(now)],
        ))
    }
    fn hold_waiting(&self, interruption_ids: &[String], hold: &str, now: f64) -> Py<i64> {
        integer(store(
            "hold_waiting",
            vec![strings(interruption_ids), s(hold), f(now)],
        ))
    }
    fn cancel_waiting(
        &self,
        interruption_ids: &[String],
        now: f64,
        reason: &str,
    ) -> Py<Vec<Value>> {
        values(store(
            "cancel_waiting",
            vec![strings(interruption_ids), f(now), s(reason)],
        ))
    }
    fn open_objection_window(&self, interruption_id: &str, until: f64, now: f64) -> Py<bool> {
        boolean(store(
            "open_objection_window",
            vec![s(interruption_id), f(until), f(now)],
        ))
    }
    fn raise_notice(&self, notice_key: &str, thread_id: &str, kind: &str, now: f64) -> Py<bool> {
        boolean(store(
            "raise_notice",
            vec![s(notice_key), s(thread_id), s(kind), f(now)],
        ))
    }
    fn watcher_status(&self) -> Py<Option<Map>> {
        opt_map(store("watcher_status", Vec::new()))
    }
    fn usage_checks_asked(&self, now: f64) -> Py<Map> {
        map(store("usage_checks_asked", vec![f(now)]))
    }
    fn usage_not_checked(&self, interruption_id: &str, now: f64, why: &str) -> Py<()> {
        store(
            "usage_not_checked",
            vec![s(interruption_id), f(now), s(why)],
        )
        .map(|_| ())
    }
    fn usage_check_taken(&self, interruption_id: &str) -> Py<Value> {
        store("usage_check_taken", vec![s(interruption_id)])
    }
    fn usage_checked(
        &self,
        interruption_id: &str,
        now: f64,
        read: &str,
        source: &Value,
    ) -> Py<Option<Map>> {
        opt_map(store(
            "usage_checked",
            vec![s(interruption_id), f(now), s(read), source.clone()],
        ))
    }
    fn early_check_asked(&self, now: f64) -> Py<bool> {
        boolean(store("early_check_asked", vec![f(now)]))
    }
    fn early_check_taken(&self) -> Py<()> {
        store("early_check_taken", Vec::new()).map(|_| ())
    }
    /// `reserve_record(record, now, ledger=plug, quiet_until=...)`: the test's store with the engine's own plug as
    /// its ledger (the plug the test handed the engine, kept on the Python side), its answer as `reserve_detailed`'s.
    fn reserve_record(
        &self,
        record: &Map,
        now: f64,
        _ledger: &car_policy::plug::Guarded,
        quiet_until: Option<f64>,
    ) -> Py<Claimed> {
        let found = values(store(
            "reserve_record",
            vec![Value::Object(record.clone()), f(now), opt_f(quiet_until)],
        ))?;
        let word = |index: usize| {
            found
                .get(index)
                .and_then(|value| text(value).map(str::to_owned))
        };
        Ok((found.first().is_some_and(truthy), word(1), word(2)))
    }
    /// `with store.record_guard(record, plug, now) as permitted:` - entered on the Python side with the engine's own
    /// plug, `body` run here, then left (as `submission_guard`).
    fn record_guard(
        &self,
        record: &Map,
        _ledger: &car_policy::plug::Guarded,
        now: f64,
        body: &mut dyn FnMut(bool) -> Value,
    ) -> Py<Value> {
        let permitted = boolean(store(
            "record_guard_enter",
            vec![Value::Object(record.clone()), f(now)],
        ))?;
        let found = catch_unwind(AssertUnwindSafe(|| body(permitted)));
        store("guard_exit", Vec::new())?;
        found.map_err(|_| "RuntimeError")
    }
}

// ------------------------------------------------------------------ the reader of Codex
/// The test's source, asked back: `source.<method>` with the reference's arguments.
pub struct AskSource;

fn source(method: &str, args: Vec<Value>) -> Py<Value> {
    ask(&format!("source.{method}"), args)
}

impl car_scheduler::Source for AskSource {
    fn marker_rows(&self, thread_id: &str, marker: &str) -> Py<Vec<Map>> {
        maps(source("marker_rows", vec![s(thread_id), s(marker)]))
    }
    fn queued_rows(&self, thread_id: &str, marker: &str) -> Py<Vec<Map>> {
        maps(source("queued_rows", vec![s(thread_id), s(marker)]))
    }
    fn queue_row(&self, thread_id: &str, queue_id: &str, marker: &str) -> Py<Map> {
        map(source(
            "queue_row",
            vec![s(thread_id), s(queue_id), s(marker)],
        ))
    }
    fn later_turns(&self, thread_id: &str, after_ordinal: &Value, marker: &str) -> Py<Vec<Map>> {
        maps(source(
            "later_turns",
            vec![s(thread_id), after_ordinal.clone(), s(marker)],
        ))
    }
    fn foreign_queued(&self, thread_id: &str, marker: &str) -> Py<i64> {
        integer(source("foreign_queued", vec![s(thread_id), s(marker)]))
    }
}

impl car_engine::Source for AskSource {
    fn latest(&self, thread_id: &str) -> Py<Option<Map>> {
        opt_map(source("latest", vec![s(thread_id)]))
    }
    fn progress(&self, thread_id: &str, after_ordinal: &Value) -> Py<Map> {
        map(source(
            "progress",
            vec![s(thread_id), after_ordinal.clone()],
        ))
    }
    fn latest_failures(
        &self,
        since: f64,
        needs_you: &[&str],
        admissible: bool,
        shapes: bool,
    ) -> Py<Vec<Map>> {
        maps(source(
            "latest_failures",
            vec![
                f(since),
                Value::Array(needs_you.iter().map(|kind| s(kind)).collect()),
                Value::Bool(admissible),
                Value::Bool(shapes),
            ],
        ))
    }
    fn passed_over(&self, since: f64, before: f64, known: &BTreeSet<String>) -> Py<Map> {
        map(source(
            "passed_over",
            vec![f(since), f(before), set_of(known)],
        ))
    }
    fn reset_hint(&self, thread_id: &str, turn_id: &str) -> Py<Map> {
        map(source("reset_hint", vec![s(thread_id), s(turn_id)]))
    }
    fn turn_markers(&self, thread_id: &str, turn_id: &str, markers: &[String]) -> Py<Vec<String>> {
        texts(source(
            "turn_markers",
            vec![s(thread_id), s(turn_id), strings(markers)],
        ))
    }
    fn turn_progress(&self, thread_id: &str, turn_id: &str) -> Py<Option<bool>> {
        match source("turn_progress", vec![s(thread_id), s(turn_id)])? {
            Value::Null => Ok(None),
            other => Ok(Some(truthy(&other))),
        }
    }
    fn turn_observation(&self, thread_id: &str, turn_id: &str, marker: &str) -> Py<Map> {
        map(source(
            "turn_observation",
            vec![s(thread_id), s(turn_id), s(marker)],
        ))
    }
    fn marker_presence(&self, thread_id: &str, marker: &str) -> Py<Map> {
        map(source("marker_presence", vec![s(thread_id), s(marker)]))
    }
    fn projection(&self, thread_id: &str) -> Py<Map> {
        map(source("projection", vec![s(thread_id)]))
    }
    fn project_key(&self, thread_id: &str) -> Py<Option<String>> {
        Ok(text(&source("project_key", vec![s(thread_id)])?).map(str::to_owned))
    }
    fn task_facts(&self, thread_id: &str, fingerprint: bool, tokens: bool) -> Py<Map> {
        map(source(
            "task_facts",
            vec![s(thread_id), Value::Bool(fingerprint), Value::Bool(tokens)],
        ))
    }
    fn stalled_turns(&self, since: f64, quiet_seconds: f64, now: f64) -> Py<Vec<Map>> {
        maps(source(
            "stalled_turns",
            vec![f(since), whole(quiet_seconds), f(now)],
        ))
    }
    fn activity(&self, threads: &[String], now: f64, booted: &Value) -> Py<Map> {
        map(source(
            "activity",
            vec![strings(threads), f(now), booted.clone()],
        ))
    }
    fn newer_than_engine(
        &self,
        thread_id: &str,
        kinds: &BTreeSet<String>,
        engine_version: &Value,
    ) -> Py<bool> {
        boolean(source(
            "newer_than_engine",
            vec![s(thread_id), set_of(kinds), engine_version.clone()],
        ))
    }
    fn taken(
        &self,
        thread_id: &str,
        kinds: &BTreeSet<String>,
        widened: &BTreeSet<String>,
    ) -> Py<bool> {
        boolean(source(
            "taken",
            vec![s(thread_id), set_of(kinds), set_of(widened)],
        ))
    }
    fn set_kinds(&mut self, kinds: &BTreeSet<String>, widened: &BTreeSet<String>) {
        let _ = source("set_kinds", vec![set_of(kinds), set_of(widened)]);
    }
}

// ------------------------------------------------------------------ the backend
/// The test's backend, asked back. A send hands the backend the reference's own launch guard: the Python side builds
/// `store.submission_guard(key)` of the test's store, which the backend enters as it would the reference's.
pub struct AskBackend;

fn backend(method: &str, args: Vec<Value>) -> Py<Value> {
    ask(&format!("backend.{method}"), args)
}

fn attribute(name: &str) -> Value {
    backend("getattr", vec![s(name)]).unwrap_or(Value::Null)
}

impl Backend for AskBackend {
    fn app_identity(&self) -> Py<Value> {
        backend("app_identity", Vec::new())
    }
    fn loaded(&self, thread_id: &str, app_identity: &Value) -> Py<Value> {
        backend("loaded", vec![s(thread_id), app_identity.clone()])
    }
    fn usage(&self) -> Py<Value> {
        backend("usage", Vec::new())
    }
    fn send(&self, thread_id: &str, prompt: &Str, launch_guard: &dyn LaunchGuard) -> Py<Value> {
        backend(
            "send",
            vec![
                s(thread_id),
                Value::Str(prompt.clone()),
                opt_s(launch_guard.key()),
            ],
        )
    }
    fn delete_queue(&self, thread_id: &str, queue_id: &str) -> Py<Value> {
        backend("delete_queue", vec![s(thread_id), s(queue_id)])
    }
    fn app_look(&self) -> Value {
        attribute("app_look")
    }
    fn app_unmatched_reason(&self) -> Value {
        attribute("app_unmatched_reason")
    }
    fn protocol_results(&self) -> Value {
        attribute("protocol_results")
    }
    fn session_holder(&self) -> Value {
        attribute("session_holder")
    }
    fn engine_version(&self) -> Value {
        attribute("engine_version")
    }
    fn holder(&self, thread_id: &str) -> Option<Py<Value>> {
        // [has the call, what it answered]
        match backend("holder", vec![s(thread_id)]) {
            Ok(Value::Array(pair)) if pair.first().is_some_and(truthy) => {
                Some(Ok(pair.get(1).cloned().unwrap_or(Value::Null)))
            }
            Ok(_) => None,
            Err(raised) => Some(Err(raised)),
        }
    }
}

// ------------------------------------------------------------------ the words for this time, the local clock
/// The test's `OnceWords`, asked back; `prune(keep)` hands it `keep` as a callable it calls back.
pub struct AskOnceWords;

impl OnceWords for AskOnceWords {
    fn words(&self, interruption_id: &str) -> Py<Value> {
        ask("once.words", vec![s(interruption_id)])
    }
    fn unchanged(&self, interruption_id: &str, seen: &Value) -> Py<Value> {
        ask("once.unchanged", vec![s(interruption_id), seen.clone()])
    }
    fn remove(&self, interruption_id: &str) -> Py<Value> {
        ask("once.remove", vec![s(interruption_id)])
    }
    fn restore(&self, interruption_id: &str, words: &Value) -> Py<()> {
        ask("once.restore", vec![s(interruption_id), words.clone()]).map(|_| ())
    }
    fn prune(&self, keep: &mut dyn FnMut(&str) -> Py<bool>) -> Py<()> {
        ask_with("once.prune", Vec::new(), &mut |arguments| {
            let key = arguments.first().and_then(text).unwrap_or_default();
            keep(key).map(Value::Bool)
        })
        .map(|_| ())
    }
}

/// `time.localtime` and `time.mktime`, asked of the test's Python.
pub struct AskLocal;

impl LocalClock for AskLocal {
    fn localtime(&self, seconds: f64) -> Py<Tm> {
        let found = values(ask("local.localtime", vec![f(seconds)]))?;
        let at = |index: usize| {
            found
                .get(index)
                .and_then(|value| car_engine::py::int_of(value).ok())
                .unwrap_or(0)
        };
        Ok(Tm {
            year: at(0),
            mon: at(1),
            mday: at(2),
            hour: at(3),
            min: at(4),
            sec: at(5),
            wday: at(6),
        })
    }
    fn mktime(&self, year: i64, mon: i64, mday: i64, hour: i64, min: i64, sec: i64) -> Py<f64> {
        let found = ask(
            "local.mktime",
            [year, mon, mday, hour, min, sec]
                .into_iter()
                .map(Value::from)
                .collect(),
        )?;
        arithmetic(&found).ok_or("TypeError")
    }
}

// ------------------------------------------------------------------ the sessions
thread_local! {
    /// One engine per session id. Each is its own cell, so an engine's call may run another's, nested.
    static ENGINES: RefCell<HashMap<i64, Rc<RefCell<Engine>>>> = RefCell::new(HashMap::new());
}

fn raised(class: &str) -> Value {
    object([("raised", Value::from(class))])
}

fn result(found: Py<Value>) -> Value {
    match found {
        Ok(value) => object([("result", value)]),
        Err(class) => raised(class),
    }
}

fn number(value: Option<&Value>) -> f64 {
    value.and_then(arithmetic).unwrap_or(0.0)
}

/// An administrator's policy keys, as `managed.Managed`'s fields name them.
pub fn managed(value: &Value) -> Option<Managed> {
    let Value::Object(fields) = value else {
        return None;
    };
    let flag = |name: &str| fields.get(name).is_some_and(truthy);
    Some(Managed {
        disable_auto_resume: flag("disable_auto_resume"),
        force_observe_only: flag("force_observe_only"),
        disable_update_check: flag("disable_update_check"),
        disable_status_file: flag("disable_status_file"),
        max_recovery_attempts: fields
            .get("max_recovery_attempts")
            .and_then(|value| car_engine::py::int_of(value).ok()),
        quiet_hours: match fields.get("quiet_hours") {
            Some(Value::Array(items)) => items
                .iter()
                .filter_map(|item| match item {
                    Value::Object(map) => Some(map.clone()),
                    _ => None,
                })
                .collect(),
            _ => Vec::new(),
        },
        disable_power_action: flag("disable_power_action"),
    })
}

/// `engine.options` as the Python's dict holds it (the ladder and the categories as lists).
fn options_map(options: &Options) -> Value {
    let mut map = Map::new();
    let mut put = |name: &str, value: Value| {
        map.insert(name.into(), value);
    };
    put("reset_grace_seconds", whole(options.reset_grace_seconds));
    put(
        "conservative_poll_seconds",
        whole(options.conservative_poll_seconds),
    );
    put("state_poll_seconds", whole(options.state_poll_seconds));
    put(
        "delivery_timeout_seconds",
        whole(options.delivery_timeout_seconds),
    );
    put("max_queue_retries", whole(options.max_queue_retries));
    put(
        "max_submissions_per_thread_per_day",
        whole(options.max_submissions_per_thread_per_day),
    );
    put(
        "thread_cooldown_seconds",
        whole(options.thread_cooldown_seconds),
    );
    put(
        "detection_lookback_seconds",
        f(options.detection_lookback_seconds),
    );
    put(
        "unknown_reconcile_window_seconds",
        whole(options.unknown_reconcile_window_seconds),
    );
    put(
        "max_recovery_attempts",
        options.max_recovery_attempts.clone(),
    );
    put("max_no_progress", options.max_no_progress.clone());
    put(
        "max_chain_continuations",
        options.max_chain_continuations.clone(),
    );
    put("settle_seconds", whole(options.settle_seconds));
    put(
        "projection_grace_seconds",
        whole(options.projection_grace_seconds),
    );
    put(
        "usage_never_available_seconds",
        whole(options.usage_never_available_seconds),
    );
    put(
        "usage_after_reset_seconds",
        whole(options.usage_after_reset_seconds),
    );
    put("loaded_check_seconds", whole(options.loaded_check_seconds));
    put(
        "max_withdraw_attempts",
        whole(options.max_withdraw_attempts),
    );
    put("delete_retry_seconds", whole(options.delete_retry_seconds));
    put("watch_budget_seconds", whole(options.watch_budget_seconds));
    put("retry_ladder", Value::Array(options.retry_ladder.clone()));
    put(
        "recoverable_categories",
        options
            .recoverable_categories
            .as_ref()
            .map_or(Value::Null, set_of),
    );
    put("resend_after_seconds", whole(options.resend_after_seconds));
    put("resend_until_seconds", whole(options.resend_until_seconds));
    put("max_chain_seconds", options.max_chain_seconds.clone());
    Value::Object(map)
}

fn open(request: &Map) -> Engine {
    let options = match request.get("options") {
        Some(Value::Object(options)) => options.clone(),
        _ => Map::new(),
    };
    let language = request.get("language").and_then(text).map(str::to_owned);
    let home_key = request
        .get("home_key")
        .and_then(text)
        .unwrap_or_default()
        .to_owned();
    let given = Given {
        dispatch_lock: None,
        clock: Box::new(|| {
            ask("clock", Vec::new())
                .ok()
                .and_then(|v| arithmetic(&v))
                .unwrap_or(0.0)
        }),
        log: Some(Box::new(|thread, event, detail| {
            let _ = ask("log", vec![opt_s(thread), s(event), detail.clone()]);
        })),
        options,
        notify: Some(Box::new(|event, payload| {
            ask("notify", vec![s(event), Value::Object(payload.clone())]).map(|_| ())
        })),
        language,
        home_lock: Some(Box::new(|| boolean(ask("home_lock", Vec::new())))),
        engine_state: Some(Box::new(|| ask("engine_state", Vec::new()))),
        plug: plug::named(request).map_or_else(Guarded::null, |made| Guarded::new(Box::new(made))),
        connectivity: Some(Box::new(|| ask("connectivity", Vec::new()))),
        home_key,
        open_store: false,
        once_words: matches!(request.get("once_words"), Some(Value::Bool(true)))
            .then(|| Box::new(AskOnceWords) as Box<dyn OnceWords>),
        draw: Box::new(|| {
            ask("draw", Vec::new())
                .ok()
                .and_then(|value| arithmetic(&value))
                .unwrap_or(0.0)
        }),
        local: Box::new(AskLocal),
        environ: Box::new(|name| {
            ask("environ", vec![s(name)])
                .ok()
                .and_then(|value| text(&value).map(str::to_owned))
        }),
        windows_languages: Box::new(|| {
            texts(ask("windows_languages", Vec::new())).unwrap_or_default()
        }),
        os: Arc::new(PlatformOs),
    };
    Engine::new(
        Box::new(AskStore),
        Box::new(AskSource),
        Box::new(AskBackend),
        given,
    )
}

fn sync(engine: &mut Engine, given: &Map) {
    if let Some(Value::Object(options)) = given.get("options") {
        let mut fresh = Options::default();
        fresh.apply(options);
        engine.options = fresh;
    }
    if let Some(value) = given.get("retiring") {
        engine.retiring = truthy(value);
    }
    if let Some(value) = given.get("home_key").and_then(text) {
        value.clone_into(&mut engine.home_key);
    }
    if let Some(value) = given.get("once_words") {
        // As `Engine::new` holds what it is handed: a panic inside is the exception at that call (caught.rs).
        engine.once_words = truthy(value).then(|| {
            Box::new(car_engine::caught::Caught(
                Box::new(AskOnceWords) as Box<dyn OnceWords>
            )) as Box<dyn OnceWords>
        });
    }
}

fn state(engine: &Engine) -> Value {
    object([
        ("options", options_map(&engine.options)),
        ("policy_values", Value::Object(engine.policy_values.clone())),
        (
            "detection_failed",
            engine.detection_failed.map_or(Value::Null, Value::Bool),
        ),
        ("handed_waits", Value::Object(engine.handed_waits.clone())),
        ("usage_cached", Value::Bool(engine.usage_cached().is_some())),
    ])
}

fn row(args: &[Value], index: usize) -> Map {
    match args.get(index) {
        Some(Value::Object(map)) => map.clone(),
        _ => Map::new(),
    }
}

fn word(args: &[Value], index: usize) -> String {
    args.get(index)
        .and_then(text)
        .unwrap_or_default()
        .to_owned()
}

fn unit(found: Py<()>) -> Value {
    result(found.map(|()| Value::Null))
}

fn call(engine: &mut Engine, method: &str, args: &[Value]) -> Value {
    match method {
        "tick" => unit(engine.tick()),
        "watch" => unit(engine.watch()),
        "watch_needed" => result(engine.watch_needed().map(Value::Bool)),
        "observe_all" => unit(engine.observe_all()),
        "observe_projections" => unit(engine.observe_projections()),
        "collect" => unit(engine.collect()),
        "attempt" => unit(engine.attempt(&row(args, 0))),
        "observe" => unit(engine.observe(&row(args, 0))),
        "apply_policy" => {
            let values = args.first().cloned().unwrap_or(Value::Null);
            let held = args.get(1).and_then(managed);
            engine.apply_policy(&values, held);
            result(Ok(Value::Null))
        }
        "after_sleep" => result(
            engine
                .after_sleep(number(args.first()), number(args.get(1)))
                .map(Value::from),
        ),
        "activity" => {
            let threads: Vec<String> = match args.first() {
                Some(Value::Array(items)) => items
                    .iter()
                    .filter_map(|item| text(item).map(str::to_owned))
                    .collect(),
                _ => Vec::new(),
            };
            result(Ok(Value::Object(engine.activity(&threads))))
        }
        "last_usage" => result(Ok(engine
            .last_usage()
            .map_or(Value::Null, |(at, windows)| {
                Value::Array(vec![f(at), Value::Array(windows)])
            }))),
        "limits" => result(Ok(Value::Object(engine.limits()))),
        "capacity_limits" => result(Ok(Value::Object(engine.capacity_limits()))),
        "recovers" => result(Ok(Value::Bool(engine.recovers(&word(args, 0))))),
        "presend_problem" => {
            let claim = match args.first() {
                Some(Value::Object(map)) => Some(map.clone()),
                _ => None,
            };
            let forced = args.get(1).is_some_and(truthy);
            result(engine.presend_problem(claim.as_ref(), forced).map(|found| {
                found.map_or(Value::Null, |(target, why, delay)| {
                    Value::Array(vec![s(&target), s(&why), whole(delay)])
                })
            }))
        }
        "detection_since" => result(engine.detection_since(&row(args, 0)).map(Value::Float)),
        "not_taken_up" => result(engine.not_taken_up(&row(args, 0)).map(|found| {
            found.map_or(Value::Null, |(reason, kind)| {
                Value::Array(vec![s(&reason), kind])
            })
        })),
        "valid_interruption" => result(engine.valid_interruption(&row(args, 0)).map(Value::Bool)),
        "proof" => result(Ok(s(&engine.proof(&row(args, 0))))),
        "persons_turns" => {
            let turns: Vec<Map> = match args.get(1) {
                Some(Value::Array(items)) => items
                    .iter()
                    .filter_map(|item| match item {
                        Value::Object(map) => Some(map.clone()),
                        _ => None,
                    })
                    .collect(),
                _ => Vec::new(),
            };
            let found = engine.persons_turns(&word(args, 0), turns);
            result(Ok(Value::Array(
                found.into_iter().map(Value::Object).collect(),
            )))
        }
        "foreign" => result(Ok(Value::Bool(
            engine.foreign(&row(args, 0), &row(args, 1)),
        ))),
        "fresh_throughout" => result(Ok(Value::Bool(
            engine.fresh_throughout(&word(args, 0), number(args.get(1))),
        ))),
        "tier" => result(engine.tier(&word(args, 0))),
        "allowed" => result(engine.allowed(&row(args, 0)).map(Value::Bool)),
        "observing" => result(Ok(Value::Bool(engine.observing(&row(args, 0))))),
        "quiet_until" => result(engine.quiet_until(number(args.first())).map(opt_f)),
        "delay_for" => result(Ok(engine.delay_for(
            args.first()
                .and_then(|value| car_engine::py::int_of(value).ok())
                .unwrap_or(0),
        ))),
        "first_delay" => result(Ok(engine.first_delay(&word(args, 0)))),
        "caps" => {
            let relaxed = args.first().and_then(text).map(str::to_owned);
            let (a, b) = engine.caps(relaxed.as_deref());
            result(Ok(Value::Array(vec![whole(a), whole(b)])))
        }
        "clear_usage_cache" => {
            engine.clear_usage_cache();
            result(Ok(Value::Null))
        }
        _ => raised("not_ported"),
    }
}

fn session_of(request: &Map) -> i64 {
    request
        .get("session")
        .and_then(|value| match value {
            Value::Int(number) => number.as_i64(),
            _ => None,
        })
        .unwrap_or(0)
}

/// `proxy.open`, `proxy.call`, `proxy.close`: the reply's value.
pub fn answer(method: &str, request: &Map) -> Value {
    let id = session_of(request);
    match method {
        "proxy.open" => match catch_unwind(AssertUnwindSafe(|| open(request))) {
            Ok(engine) => {
                let mut found = result(Ok(Value::Null));
                if let Value::Object(reply) = &mut found {
                    reply.insert("state".into(), state(&engine));
                }
                ENGINES.with(|engines| {
                    engines
                        .borrow_mut()
                        .insert(id, Rc::new(RefCell::new(engine)))
                });
                found
            }
            Err(_) => raised("panic"),
        },
        "proxy.close" => {
            let mut ids = vec![id];
            if let Some(Value::Array(more)) = request.get("sessions") {
                ids.extend(more.iter().filter_map(|value| match value {
                    Value::Int(number) => number.as_i64(),
                    _ => None,
                }));
            }
            ENGINES.with(|engines| {
                let mut engines = engines.borrow_mut();
                for id in ids {
                    engines.remove(&id);
                }
            });
            result(Ok(Value::Null))
        }
        "proxy.call" => {
            let Some(engine) = ENGINES.with(|engines| engines.borrow().get(&id).cloned()) else {
                return raised("no_session");
            };
            let Ok(mut engine) = engine.try_borrow_mut() else {
                // The same engine called again from inside one of its own calls: the reference would run it; the
                // proxy cannot, and says so.
                return raised("RecursionError");
            };
            if let Some(Value::Object(given)) = request.get("sync") {
                sync(&mut engine, given);
            }
            let name = request.get("method").and_then(text).unwrap_or_default();
            let args = match request.get("args") {
                Some(Value::Array(args)) => args.clone(),
                _ => Vec::new(),
            };
            // D15: a panic is caught at the boundary, and said.
            let mut found = catch_unwind(AssertUnwindSafe(|| call(&mut engine, name, &args)))
                .unwrap_or_else(|_| raised("panic"));
            if let Value::Object(reply) = &mut found {
                reply.insert("state".into(), state(&engine));
            }
            found
        }
        _ => raised("not_ported"),
    }
}

/// A `proxy.*` request line, read as Python's `json.loads` reads it (NaN, a lone surrogate): (id, reply).
pub fn line(line: &str) -> Option<(Value, Value)> {
    let Ok(Value::Object(request)) = car_machine::compat::loads(line) else {
        return None;
    };
    let id = match request.get("id") {
        Some(Value::Int(int)) => int.as_i64().map_or(Value::Null, Value::from),
        _ => Value::Null,
    };
    let method = request.get("call").and_then(text)?.to_owned();
    if !method.starts_with("proxy.") {
        return None;
    }
    let value = answer(&method, &request);
    Some((id, object([("ok", Value::Bool(true)), ("value", value)])))
}
