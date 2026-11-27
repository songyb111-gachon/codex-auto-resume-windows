//! `control/conversations.py` (seat S7.3a): the Dashboard's Find a conversation (v0.6.20, issue #50) - the person's own
//! conversations of the Codex home the watcher drives, with their names, newest first, at most LIMIT, none switched
//! off for recovery. Read-only and the Dashboard's alone.

use std::collections::BTreeSet;

use car_machine::json::Value;

use super::resets::{Result, codex_home, codex_os, core, int, object, refusal, text};
use crate::codex::threads::Threads;
use crate::codex::turns::Failure;
use crate::runtime::Runtime;
use crate::state::Error;
use crate::vocabulary::Refusal;

pub const LIMIT: i64 = 200;

/// Core's switched-off conversations as the set `Threads.own` skips.
pub fn off_set(found: &[Value]) -> BTreeSet<String> {
    found
        .iter()
        .filter_map(|value| match value {
            Value::Str(text) => text.as_str().map(str::to_owned),
            _ => None,
        })
        .collect()
}

/// `view(runtime)`: advanced-conversations.
pub fn view(runtime: &Runtime) -> Result<Value> {
    let off = match core(runtime).and_then(|store| {
        store
            .disabled_threads()
            .map_err(|_| Error::state("cannot read core's state"))
    }) {
        Ok(off) => off_set(&off),
        Err(_) => return Ok(refusal(Refusal::StateUnavailable)),
    };
    let home = codex_home(runtime)?;
    let found = match (Threads {
        home,
        os: codex_os(),
    })
    .own(LIMIT, &off)
    {
        Ok(found) => found,
        Err(Failure::Unavailable(_)) => return Ok(refusal(Refusal::StateUnavailable)),
        Err(Failure::Raised(class)) => return Err(Error::python(class, "")),
    };
    Ok(object(vec![
        ("done", Value::Bool(true)),
        ("refusal", Value::Null),
        ("limit", int(LIMIT)),
        (
            "conversations",
            Value::Array(
                found
                    .iter()
                    .map(|(thread, name)| {
                        object(vec![("thread_id", text(thread)), ("name", text(name))])
                    })
                    .collect(),
            ),
        ),
    ]))
}
