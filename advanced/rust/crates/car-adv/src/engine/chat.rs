//! `codex_chat`'s code (seat S7.2e1b; `engine/chat.py`): a message a person writes on the Dashboard's Chat page, handed
//! core at P2 as a person's MESSAGE record and sent with no marker through this capability's own channel (P5, P15).
//!
//! P2: each conversation's oldest waiting message, and those in flight (core watches them); one waiting in a conversation
//! switched off is cancelled. P5: the channel (`thread/queue/add` under the client id core derives) for a record of the
//! edition's own alone; P15: CLIENT_ID for it. [`handed`], [`watched`] and [`paused_by_stop`] are the runtime's too
//! (moved here from `seam_p7` by S7.2e1b; the runtime calls them here since Integration 10).

use car_config::Paths;
use car_machine::json::{Map, Str, Value};
use car_policy::plug::{Alternative, Channel, HookFailed, View};

use super::emptyreply::{enabled, word};
use super::markerfree::{Open, no_session, send, text_input};
use crate::capabilities::{Binding, Code, Raised, Said, Spoke};
use crate::state::sql;
use crate::vocabulary::{ArmingWarning, ChatState, ContinuationKind};

pub const CAPABILITY: &str = "codex_chat";
pub const WORDS: usize = 2000;
/// How long Codex has to take a message it holds in its queue before it is taken back.
pub const TAKEN_WITHIN: f64 = 180.0;

fn get<'a>(row: &'a Value, name: &str) -> Option<&'a Value> {
    match row {
        Value::Object(map) => map.get(name),
        _ => None,
    }
}

fn or_null(value: Option<&Value>) -> Value {
    value.cloned().unwrap_or(Value::Null)
}

fn is(value: Option<&Value>, text: &str) -> bool {
    matches!(value, Some(Value::Str(held)) if held.as_str() == Some(text))
}

fn with(own: &[(&str, Value)], more: Vec<(&str, Value)>) -> Value {
    let mut map = Map::new();
    for (name, value) in own.iter().cloned().chain(more) {
        map.insert(name.into(), value);
    }
    Value::Object(map)
}

/// `handed(row)`: one message as core is handed it, marked `pause_keeps` (v0.6.23), or None.
pub fn handed(row: &Value) -> Option<Value> {
    let key = get(row, "record_id")?;
    if !matches!(key, Value::Str(text) if text.len() == 64) {
        return None;
    }
    let marker = match key {
        Value::Str(text) => Value::Str(
            car_machine::domain::ids::short_marker(text.as_str().unwrap_or_default()).into(),
        ),
        _ => Value::Null,
    };
    let own = [
        ("record_id", key.clone()),
        ("thread_id", or_null(get(row, "thread_id"))),
        ("marker", marker),
        ("purpose", word("message")),
        ("ordinal", Value::Null),
        ("pause_keeps", Value::Bool(true)),
    ];
    let tail = |state: &str, words: Value, sent_at: Value| {
        vec![
            ("state", word(state)),
            ("words", words),
            ("sent_at", sent_at),
            ("queue_id", Value::Null),
            ("withdraw", Value::Bool(false)),
        ]
    };
    if is(get(row, "state"), ChatState::InFlight.as_str()) {
        return Some(with(
            &own,
            tail("in_flight", Value::Null, or_null(get(row, "sent_at"))),
        ));
    }
    if is(get(row, "state"), ChatState::Waiting.as_str())
        && get(row, "words").is_some_and(car_machine::pyval::truthy)
    {
        return Some(with(
            &own,
            tail("waiting", or_null(get(row, "words")), Value::Null),
        ));
    }
    None
}

fn number(value: Option<&Value>) -> Option<f64> {
    match value {
        Some(Value::Int(int)) => int.as_i64().map(|n| n as f64),
        Some(Value::Float(number)) => Some(*number),
        Some(Value::Bool(flag)) => Some(f64::from(u8::from(*flag))),
        _ => None,
    }
}

/// `paused_by_stop(row, stops)`: whether a message in flight sat in a queue usage_pause stopped.
pub fn paused_by_stop(row: &Value, stops: &[Value]) -> bool {
    stops.iter().any(|stop| {
        let ended = match (
            number(get(stop, "finished_at")),
            number(get(row, "sent_at")),
        ) {
            (Some(end), Some(sent)) => end >= sent,
            _ => false,
        };
        is(get(stop, "capability"), crate::engine::usage::PAUSE)
            && is(get(stop, "kind"), ContinuationKind::AfterReset.as_str())
            && get(stop, "thread_id") == get(row, "thread_id")
            && (matches!(get(stop, "finished_at"), None | Some(Value::Null)) || ended)
    })
}

/// `watched(row, now, stops)`: a message in flight as core watches it, asked back out of Codex's queue once
/// TAKEN_WITHIN has passed - never one in a queue the forced stop paused (v0.6.26, M1).
pub fn watched(row: &Value, now: f64, stops: &[Value]) -> Option<Value> {
    let mut found = handed(row)?;
    if let Some(sent) = number(get(&found, "sent_at"))
        && now - sent >= TAKEN_WITHIN
        && !paused_by_stop(row, stops)
        && let Value::Object(map) = &mut found
    {
        map.insert("withdraw".into(), Value::Bool(true));
    }
    Some(found)
}

/// `_ours(record)`: a record of this edition's own - a record id and no interruption id.
fn ours(record: &Value) -> bool {
    matches!(record, Value::Object(map) if map.contains_key("record_id") && !map.contains_key("interruption_id"))
}

/// The one call a chat message goes by: thread/queue/add with its client id, in a session of this capability's.
pub struct ChatChannel {
    open: Open,
}

impl Channel for ChatChannel {
    fn send(&self, thread_id: &str, prompt: &Str, client_id: Option<&str>) -> Value {
        send(
            &self.open, CAPABILITY, thread_id, prompt, client_id, text_input,
        )
    }
    // Made unbound, as the reference's `Channel(paths, session=...)`: MarkerFreeContinuation's `pools()` with no view.
    fn pools(&self) -> Result<bool, HookFailed> {
        Ok(false)
    }
    fn pools_said(&self) -> Option<Result<Value, HookFailed>> {
        Some(Ok(word(ArmingWarning::Unmeasured.as_str())))
    }
}

/// `CodexChat(paths, session=None)`.
pub struct CodexChat {
    pub paths: Paths,
    binding: Option<Binding>,
    open: Open,
}

impl CodexChat {
    pub fn new(paths: Paths, open: Open) -> CodexChat {
        CodexChat {
            paths,
            binding: None,
            open,
        }
    }
}

impl Code for CodexChat {
    fn bind(&mut self, binding: Binding) -> Option<Result<(), Raised>> {
        self.binding = Some(binding);
        Some(Ok(()))
    }

    /// P2: each conversation's oldest waiting message, and those in flight.
    fn records(&mut self, view: &dyn View) -> Spoke {
        let Some(binding) = &self.binding else {
            return Ok(Said::Defer);
        };
        let found = binding.with(|scoped| -> Result<Option<Vec<Value>>, Raised> {
            let handle = scoped.handle();
            let Ok(rows) = handle.chat_pending() else {
                return Ok(None);
            };
            let mut found = Vec::new();
            let mut seen: Vec<Value> = Vec::new();
            for row in rows {
                let thread = sql::get(&row, "thread_id").clone();
                let waiting =
                    sql::py_eq(sql::get(&row, "state"), &word(ChatState::Waiting.as_str()));
                if waiting {
                    match enabled(view, &thread) {
                        None => return Err(Raised::new("Exception")),
                        Some(false) => {
                            let _ = handle.chat_conversation_off(sql::get(&row, "record_id"));
                            continue;
                        }
                        Some(true) => {}
                    }
                }
                if waiting && seen.iter().any(|held| sql::py_eq(held, &thread)) {
                    continue;
                }
                seen.push(thread);
                if let Some(record) = handed(&Value::Object(row)) {
                    found.push(record);
                }
            }
            Ok(Some(found))
        });
        Ok(match found {
            Some(Err(raised)) => return Err(raised),
            Some(Ok(Some(records))) if !records.is_empty() => Said::Value(Value::Array(records)),
            _ => Said::Defer,
        })
    }

    /// P5: the channel, for a message of its own alone.
    fn sender(&mut self, record: &Value) -> Spoke {
        if !ours(record) {
            return Ok(Said::Defer);
        }
        Ok(Said::Channel(Box::new(ChatChannel {
            open: self.open.clone(),
        })))
    }

    /// P15: no marker for a message of its own.
    fn delivery(&mut self, record: &Value) -> Spoke {
        Ok(if ours(record) {
            Said::Word(Alternative::ClientId)
        } else {
            Said::Defer
        })
    }
}

/// `make(paths)`: the capability's code with the session a code made from `paths` alone has.
pub fn make(paths: &Paths) -> Option<Box<dyn Code>> {
    make_with(paths, no_session())
}

/// `CodexChat(paths, session=...)` with an entry point's or a test's own session.
pub fn make_with(paths: &Paths, open: Open) -> Option<Box<dyn Code>> {
    Some(Box::new(CodexChat::new(paths.clone(), open)))
}
