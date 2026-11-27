//! `control/chat.py` (seat S7.3a): the Dashboard's chat with a conversation (codex_chat, v0.6.19) - the conversation's
//! last turns and the page's own messages to it read, one message added for core to send at its next look, and the
//! one still waiting cancelled. The Dashboard's alone; the watcher alone sends.

use car_machine::domain::ids;
use car_machine::json::{Map, Str, Value};
use car_machine::pyval;

use super::resets::{
    Result, among, arg, call, codex_home, codex_os, field, generation, get, int, length, list, object, on,
    refused_here, shown, stale, switched_off, text, wake, with,
};
use crate::codex::conversation::Conversation;
use crate::codex::turns::Failure;
use crate::engine::chat::{CAPABILITY, WORDS};
use crate::runtime::Runtime;
use crate::state::Error;
use crate::vocabulary::{ChatReason, ChatState, Refusal};

pub const SHOWN: &[&str] = &["chat_id", "state", "reason", "created_at", "sent_at", "finished_at"];
pub const RECENT: f64 = 3600.0;

/// `view(runtime, thread)`: advanced-chat-read.
pub fn view(runtime: &Runtime, thread: &Value) -> Result<Value> {
    if !ids::is_uuid(thread) {
        return Ok(refused_here(Refusal::InvalidRequest, runtime));
    }
    if !on(runtime, CAPABILITY) {
        return Ok(refused_here(Refusal::NotOn, runtime));
    }
    let home = codex_home(runtime)?;
    let reader = Conversation { home, os: codex_os() };
    let turns = match reader.view(thread) {
        Ok(turns) => turns,
        Err(Failure::Unavailable(_)) => return Ok(refused_here(Refusal::StateUnavailable, runtime)),
        Err(Failure::Raised(class)) => return Err(Error::python(class, "")),
    };
    let read = || -> Result<(Vec<Map>, Value)> {
        let rows = list(&call(runtime, "chats", &[], &[("thread_id", thread.clone())])?);
        Ok((rows, generation(runtime)?))
    };
    let Ok((rows, generation)) = read() else {
        return Ok(refused_here(Refusal::StateUnavailable, runtime));
    };
    let now = runtime.now();
    let mut messages = Vec::new();
    for row in &rows {
        let state = get(row, "state");
        if among(&state, &[ChatState::Done.as_str(), ChatState::Cancelled.as_str()])
            && super::resets::or_zero(&get(row, "finished_at")).is_some_and(|at| at < now - RECENT)
        {
            continue;
        }
        let mut item = shown(row, SHOWN);
        let words = if super::resets::is(&state, ChatState::Waiting.as_str()) {
            get(row, "words")
        } else {
            Value::Null
        };
        item.insert(Str::new("words"), words);
        messages.push(Value::Object(item));
    }
    Ok(object(vec![
        ("done", Value::Bool(true)),
        ("refusal", Value::Null),
        ("generation", generation),
        ("turns", Value::Array(turns)),
        ("messages", Value::Array(messages)),
        ("words_limit", int(WORDS as i64)),
        ("limit", object(vec![("full", Value::Bool(limit_full(runtime, now)))])),
    ]))
}

/// `limit_full(runtime, now)`: some window at 100 per cent whose reset is still ahead, as the watcher last read it.
pub fn limit_full(runtime: &Runtime, now: f64) -> bool {
    let read = || -> Option<bool> {
        let store = super::resets::core(runtime).ok()?;
        let status = store.watcher_status().ok()?.map(Value::Object).unwrap_or(Value::Object(Map::new()));
        let usage = field(&status, "usage");
        let usage = if pyval::truthy(&usage) { usage } else { Value::Object(Map::new()) };
        let windows = field(&usage, "windows");
        let windows = match &windows {
            Value::Array(items) => items.clone(),
            other if !pyval::truthy(other) => Vec::new(),
            Value::Object(map) => map.keys().map(|key| Value::Str(key.clone())).collect(),
            _ => return None,
        };
        for window in &windows {
            let Value::Object(window) = window else {
                return None;
            };
            let used = window.get("used_percent")?;
            let full = pyval::greater(used, &int(100)).ok()? || pyval::eq(used, &int(100));
            if !full {
                continue;
            }
            let reset = window.get("reset_at")?;
            if matches!(reset, Value::Null) || pyval::greater(reset, &Value::Float(now)).ok()? {
                return Some(true);
            }
        }
        Some(false)
    };
    read().unwrap_or(false)
}

/// `add(runtime, argument)`: advanced-chat-send.
pub fn add(runtime: &Runtime, argument: &Map) -> Result<Value> {
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
    if car_policy::classify::continuation::validate_prompt(&words).is_err() || length(&words) > WORDS {
        return Ok(refused_here(Refusal::PromptRefused, runtime));
    }
    let wrote = (|| -> Result<bool> {
        let pending = call(
            runtime,
            "chats",
            &[],
            &[("thread_id", thread.clone()), ("pending", Value::Bool(true))],
        )?;
        if pyval::truthy(&pending) {
            return Ok(false);
        }
        let record = text(&runtime.state.tokens.hex(32));
        let at = Value::Float(runtime.now());
        call(runtime, "add_chat", &[thread.clone(), words.clone(), record], &[("at", at)])?;
        Ok(true)
    })();
    match wrote {
        Ok(true) => {}
        Ok(false) => return Ok(refused_here(Refusal::BeingSent, runtime)),
        Err(_) => return Ok(refused_here(Refusal::StateUnavailable, runtime)),
    }
    wake(runtime);
    Ok(with(view(runtime, &thread)?, vec![("done", Value::Bool(true))]))
}

/// `cancel(runtime, argument)`: advanced-chat-cancel.
pub fn cancel(runtime: &Runtime, argument: &Map) -> Result<Value> {
    if stale(runtime, &arg(argument, "generation")) {
        return Ok(refused_here(Refusal::StaleGeneration, runtime));
    }
    let thread = arg(argument, "thread_id");
    if !ids::is_uuid(&thread) {
        return Ok(refused_here(Refusal::InvalidRequest, runtime));
    }
    let at = Value::Float(runtime.now());
    let cancelled = match call(
        runtime,
        "cancel_chat",
        &[text(ChatReason::Cancelled.as_str())],
        &[("thread_id", thread.clone()), ("at", at)],
    ) {
        Ok(cancelled) => cancelled,
        Err(_) => return Ok(refused_here(Refusal::StateUnavailable, runtime)),
    };
    if !pyval::truthy(&cancelled) {
        return Ok(refused_here(Refusal::BeingSent, runtime));
    }
    Ok(with(view(runtime, &thread)?, vec![("done", Value::Bool(true))]))
}
