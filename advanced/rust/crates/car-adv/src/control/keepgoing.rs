//! `control/keepgoing.py` (seat S7.3a): the Dashboard's keep going (v0.6.15-beta) - the conversations kept going read,
//! one picked with a count, one stopped. Each the long-lived bridge's, the Dashboard's alone, against the generation
//! the page read; no MCP tool reaches any of them.

use car_machine::domain::ids;
use car_machine::json::{Map, Str, Value};

use super::resets::{
    Result, arg, call, failed, generation, get, int, is, list, object, refused_here, refusal, shown, small, stale,
    standing, switched_off, text, verdict, with,
};
use crate::engine::keepgoing::{CAPABILITY, UNMEASURED_COUNT, allowed};
use crate::runtime::Runtime;
use crate::vocabulary::{KeepReason, KeepState, Measurement, Refusal};

/// `state.continuations.KEEP_COUNTS`: 1 to 10.
pub const KEEP_COUNTS: std::ops::RangeInclusive<i64> = 1..=10;
pub const SHOWN: &[&str] = &["thread_id", "count", "used", "armed_at", "state", "reason", "finished_at"];

fn measured(runtime: &Runtime) -> bool {
    verdict(runtime, Measurement::Mk) == Some("pass")
}

/// `view(runtime)`: advanced-keep-going.
pub fn view(runtime: &Runtime) -> Result<Value> {
    let read = || -> Result<(Value, Value)> {
        let rows = call(runtime, "keep_going", &[], &[])?;
        Ok((rows, generation(runtime)?))
    };
    let Ok((rows, generation)) = read() else {
        return Ok(refusal(Refusal::StateUnavailable));
    };
    let measured = measured(runtime);
    let mut shown_rows = Vec::new();
    for row in list(&rows) {
        let mut item: Map = shown(&row, SHOWN);
        let count = get(&row, "count");
        let Some(count) = small(&count) else {
            return Err(crate::state::Error::type_error("unsupported operand type(s) for min"));
        };
        item.insert(Str::new("allowed"), int(allowed(count, measured)));
        shown_rows.push(Value::Object(item));
    }
    Ok(object(vec![
        ("done", Value::Bool(true)),
        ("refusal", Value::Null),
        ("generation", generation),
        ("rows", Value::Array(shown_rows)),
        ("count_capped", Value::Bool(!measured)),
        ("count_failed", Value::Bool(failed(runtime, Measurement::Mk))),
        (
            "limits",
            object(vec![("count", int(*KEEP_COUNTS.end())), ("unmeasured", int(UNMEASURED_COUNT))]),
        ),
    ]))
}

/// `set_one(runtime, argument)`: advanced-keep-going-set.
pub fn set_one(runtime: &Runtime, argument: &Map) -> Result<Value> {
    if stale(runtime, &arg(argument, "generation")) {
        return Ok(refused_here(Refusal::StaleGeneration, runtime));
    }
    let (thread, count) = (arg(argument, "thread_id"), arg(argument, "count"));
    if !ids::is_uuid(&thread) {
        return Ok(refused_here(Refusal::InvalidRequest, runtime));
    }
    if !small(&count).is_some_and(|count| KEEP_COUNTS.contains(&count)) {
        return Ok(refused_here(Refusal::KeepCountInvalid, runtime));
    }
    if !standing(runtime, CAPABILITY) {
        return Ok(refused_here(Refusal::NotOn, runtime));
    }
    if switched_off(runtime, &thread) {
        return Ok(refused_here(Refusal::ConversationOff, runtime));
    }
    let at = Value::Float(runtime.now());
    if call(runtime, "set_keep_going", &[thread, count], &[("at", at)]).is_err() {
        return Ok(refused_here(Refusal::StateUnavailable, runtime));
    }
    Ok(with(view(runtime)?, vec![("done", Value::Bool(true))]))
}

/// `stop(runtime, argument)`: advanced-keep-going-stop (by_person).
pub fn stop(runtime: &Runtime, argument: &Map) -> Result<Value> {
    if stale(runtime, &arg(argument, "generation")) {
        return Ok(refused_here(Refusal::StaleGeneration, runtime));
    }
    let thread = arg(argument, "thread_id");
    if !ids::is_uuid(&thread) {
        return Ok(refused_here(Refusal::InvalidRequest, runtime));
    }
    let stopped = (|| -> Result<bool> {
        let row = call(runtime, "keep_going", &[thread.clone()], &[])?;
        let Value::Object(row) = row else {
            return Ok(false);
        };
        if !is(&get(&row, "state"), KeepState::On.as_str()) {
            return Ok(false);
        }
        let at = Value::Float(runtime.now());
        call(
            runtime,
            "stop_keep_going",
            &[text(KeepReason::ByPerson.as_str())],
            &[("thread_id", thread.clone()), ("at", at)],
        )?;
        Ok(true)
    })();
    match stopped {
        Ok(true) => {}
        Ok(false) => return Ok(refused_here(Refusal::InvalidRequest, runtime)),
        Err(_) => return Ok(refused_here(Refusal::StateUnavailable, runtime)),
    }
    Ok(with(view(runtime)?, vec![("done", Value::Bool(true))]))
}
