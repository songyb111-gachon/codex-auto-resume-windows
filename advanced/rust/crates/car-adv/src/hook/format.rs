//! The Stop hook's format (`hook/format.py`): everything about how Codex declares, calls and hears a plugin's Stop hook, in
//! one place. Pure: a table and two builders, and nothing read.
//!
//! Codex's hook interface is the least stable surface this edition touches, and the measurement MHK settles it for the engine
//! in force; until its record is made this is the recommended reading - the shape Codex's hooks take in its documentation.

use car_machine::json::{Map, Str, Value};

/// `HookFormat`.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct HookFormat {
    /// The Stop event's name, as the declaration and the input's event key say it.
    pub event: &'static str,
    pub event_key: &'static str,
    pub thread_key: &'static str,
    pub turn_key: &'static str,
    pub active_key: &'static str,
    pub decision_key: &'static str,
    pub block_word: &'static str,
    pub reason_key: &'static str,
    /// Where it is declared: a file at this path under the plugin's root, optionally named by the manifest under
    /// `manifest_key`.
    pub file: &'static [&'static str],
    pub manifest_key: Option<&'static str>,
    /// `"absolute"` (the launcher's path in the installation's home) or `"contained"` (its path inside the plugin).
    pub command: &'static str,
    /// The plugin roots it is written into: `"installation"` and `"codex_copy"`.
    pub roots: &'static [&'static str],
    pub timeout_seconds: i64,
}

/// `FORMAT`: the reading this build declares and answers in.
pub const FORMAT: HookFormat = HookFormat {
    event: "Stop",
    event_key: "hook_event_name",
    thread_key: "session_id",
    turn_key: "turn_id",
    active_key: "stop_hook_active",
    decision_key: "decision",
    block_word: "block",
    reason_key: "reason",
    file: &["hooks", "hooks.json"],
    manifest_key: None,
    command: "absolute",
    roots: &["installation", "codex_copy"],
    timeout_seconds: 10,
};

/// `SETTLED_BY`: the measurement record FORMAT was read from, or None while MHK has not been made.
pub const SETTLED_BY: Option<&str> = None;

/// `allowed_keys(found)`: the input keys the handler keeps, and the only ones whose values it ever reads.
pub fn allowed_keys(found: &HookFormat) -> [&'static str; 4] {
    [
        found.event_key,
        found.thread_key,
        found.turn_key,
        found.active_key,
    ]
}

fn object(pairs: Vec<(&str, Value)>) -> Value {
    let mut map = Map::new();
    for (name, value) in pairs {
        map.insert(Str::from(name), value);
    }
    Value::Object(map)
}

/// `declaration(command, found)`: the document the declaration file holds: the one Stop hook, running `command`.
pub fn declaration(command: &str, found: &HookFormat) -> Value {
    object(vec![(
        "hooks",
        object(vec![(
            found.event,
            Value::Array(vec![object(vec![(
                "hooks",
                Value::Array(vec![object(vec![
                    ("type", Value::from("command")),
                    ("command", Value::from(command)),
                    ("timeout", Value::from(found.timeout_seconds)),
                ])]),
            )])]),
        )]),
    )])
}

/// `commands_in(document, found)`: every command `document` declares, in the shape `declaration` writes; None for a document
/// of any other shape - which is never ours to remove.
pub fn commands_in(document: &Value) -> Option<Vec<String>> {
    let Value::Object(top) = document else {
        return None;
    };
    let Value::Object(groups) = top.get("hooks")? else {
        return None;
    };
    if groups.is_empty() {
        return None;
    }
    let mut found = Vec::new();
    for (_event, entries) in groups {
        let Value::Array(entries) = entries else {
            return None;
        };
        for entry in entries {
            let Value::Object(entry) = entry else {
                return None;
            };
            let Value::Array(hooks) = entry.get("hooks")? else {
                return None;
            };
            for hook in hooks {
                let Value::Object(hook) = hook else {
                    return None;
                };
                let Some(Value::Str(command)) = hook.get("command") else {
                    return None;
                };
                found.push(command.as_str()?.to_owned());
            }
        }
    }
    Some(found)
}

/// `answer(reason, found)`: the block, with `reason` - the continuation Codex goes on with.
pub fn answer(reason: &str, found: &HookFormat) -> Value {
    object(vec![
        (found.decision_key, Value::from(found.block_word)),
        (found.reason_key, Value::from(reason)),
    ])
}
