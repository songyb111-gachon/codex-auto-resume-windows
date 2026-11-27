//! `control/steer.py` (seat S7.3a): the Dashboard's steer (v0.6.20, issue #50 item 2 - steer_send) - one line asked to
//! be added to the turn running in a conversation, and the steers shown in History. `request` sends nothing: it
//! writes one row `requested` and wakes the watcher, whose errand alone writes it (`engine/steer.rs`).

use std::cmp::Ordering;

use car_machine::domain::ids;
use car_machine::json::{Map, Value};
use car_machine::pyval;

use super::resets::{
    Result, among, arg, call, codex_home, get, int, length, list, on, refused_here, shown, stale, switched_off, text,
    wake, with,
};
use crate::engine::steer::{CAPABILITY, DAY, PER_CONVERSATION, PER_DAY, RUNNING};
use crate::runtime::Runtime;
use crate::vocabulary::{Refusal, SteerState};

pub const SHOWN: &[&str] = &["steer_id", "thread_id", "words", "state", "reason", "created_at", "finished_at"];
/// How long History shows a steer.
pub const KEPT: f64 = 30.0 * DAY;
/// `state.steers.WAITING`.
pub const WAITING: &[&str] = &[SteerState::Requested.as_str(), SteerState::Sending.as_str()];

/// `rows(runtime)`: every steer of the last 30 days, newest first; empty where none is or none can be read.
pub fn rows(runtime: &Runtime) -> Vec<Value> {
    let since = (runtime.now() - KEPT).max(0.0);
    let Ok(found) = call(runtime, "steers", &[Value::Float(since)], &[]) else {
        return Vec::new();
    };
    let mut shown_rows: Vec<Map> = list(&found).iter().map(|row| shown(row, SHOWN)).collect();
    shown_rows.sort_by(|a, b| {
        let key = |row: &Map| (get(row, "created_at"), get(row, "steer_id"));
        let (a, b) = (key(a), key(b));
        let first = pyval::order(&b.0, &a.0).ok().flatten().unwrap_or(Ordering::Equal);
        first.then_with(|| pyval::order(&b.1, &a.1).ok().flatten().unwrap_or(Ordering::Equal))
    });
    shown_rows.into_iter().map(Value::Object).collect()
}

/// `waiting(runtime)`: how many steers wait for the watcher.
pub fn waiting(runtime: &Runtime) -> i64 {
    match call(runtime, "waiting_steers", &[], &[]) {
        Ok(found) => list(&found).iter().filter(|row| among(&get(row, "state"), WAITING)).count() as i64,
        Err(_) => 0,
    }
}

/// `engine.steer.latest_status(home, thread)`: the status of the conversation's latest turn, or None.
pub fn latest_status(home: &str, thread: &Value) -> Option<String> {
    let turns = crate::codex::turns::Turns::new(home, super::resets::codex_os());
    match turns.latest(thread) {
        Ok(Some(turn)) => Some(turn.status),
        _ => None,
    }
}

/// `request(runtime, argument)`: advanced-steer.
pub fn request(runtime: &Runtime, argument: &Map) -> Result<Value> {
    if stale(runtime, &arg(argument, "generation")) {
        return Ok(refused_here(Refusal::StaleGeneration, runtime));
    }
    let (thread, words) = (arg(argument, "thread_id"), arg(argument, "words"));
    if !ids::is_uuid(&thread) {
        return Ok(refused_here(Refusal::InvalidRequest, runtime));
    }
    if !on(runtime, CAPABILITY) {
        return Ok(refused_here(Refusal::NotOn, runtime));
    }
    if switched_off(runtime, &thread) {
        return Ok(refused_here(Refusal::ConversationOff, runtime));
    }
    if car_policy::classify::continuation::validate_prompt(&words).is_err()
        || length(&words) > super::prompts::words_limit(runtime)
    {
        return Ok(refused_here(Refusal::PromptRefused, runtime));
    }
    let now = runtime.now();
    let Ok(recent) = call(runtime, "steers", &[Value::Float((now - DAY).max(0.0))], &[]) else {
        return Ok(refused_here(Refusal::StateUnavailable, runtime));
    };
    let recent = list(&recent);
    let mine = |row: &&Map| pyval::eq(&get(row, "thread_id"), &thread);
    if recent.iter().filter(mine).any(|row| among(&get(row, "state"), WAITING)) {
        return Ok(refused_here(Refusal::BeingSent, runtime));
    }
    if recent.len() as i64 >= PER_DAY || recent.iter().filter(mine).count() as i64 >= PER_CONVERSATION {
        return Ok(refused_here(Refusal::QueueFull, runtime));
    }
    let home = codex_home(runtime)?;
    if latest_status(&home, &thread).as_deref() != Some(RUNNING) {
        return Ok(refused_here(Refusal::NoTurnRunning, runtime));
    }
    let bounds = Value::Array(vec![int(DAY as i64), int(PER_DAY), int(PER_CONVERSATION)]);
    let made = call(
        runtime,
        "add_steer",
        &[thread, words, text(&car_platform::ipc_pipe::uuid4())],
        &[("at", Value::Float(now)), ("bounds", bounds)],
    );
    let steer = match made {
        Ok(steer) => steer,
        Err(error) if error.class() == "SteerRefused" => {
            let refusal = if error.word() == Some("being_sent") {
                Refusal::BeingSent
            } else {
                Refusal::QueueFull
            };
            return Ok(refused_here(refusal, runtime));
        }
        Err(_) => return Ok(refused_here(Refusal::StateUnavailable, runtime)),
    };
    wake(runtime);
    Ok(with(
        super::prompts::view(runtime),
        vec![("done", Value::Bool(true)), ("steer", steer)],
    ))
}
