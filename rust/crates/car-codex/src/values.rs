//! `codex/values.py`: Codex's words and numbers, read the same way everywhere.
//!
//! A status Codex gives, a time it writes, the JSON in a row: each is read through one function here, so two readers
//! cannot disagree about what a value means.

use std::collections::BTreeSet;

use car_machine::compat::loads;
use car_machine::domain::{ids, states};
use car_machine::json::{Map, Str, Value};
use car_machine::pyval::{self, Py};
use car_policy::classify::failures;

pub const MAX_SCAN_BYTES: usize = 8 * 1024 * 1024;
pub const MAX_META_BYTES: usize = 256 * 1024;
pub const MAX_ITEM_BYTES: usize = 1024 * 1024;

/// A person's own conversations in the Codex desktop app (A15), by what Codex records of them (`None` is in it).
pub const OWN_THREAD_SOURCES: [Option<&str>; 3] = [Some("user"), Some("chatgpt_handoff"), None];
/// The kinds Codex makes for itself, which nothing takes up however widely the plug asks (P19).
pub const INTERNAL_THREAD_SOURCES: [&str; 4] = [
    "subagent",
    "guardian_review",
    "memory_consolidation",
    "agent_created_thread",
];

/// Issue #54: a conversation an agent made becomes the person's own in the turns they start from the input box.
pub const AGENT_CREATED_THREAD: &str = "agent_created_thread";
pub const COMPOSER: &str = "composer";

pub const DESKTOP_ORIGINATORS: [&str; 2] = ["Codex Desktop", "codex_work_desktop"];
/// Issue #37: a conversation started in the Codex CLI's TUI and continued in the Desktop app is the app's.
pub const ADOPTED_ORIGINATORS: [&str; 1] = ["codex-tui"];
/// Issue #66: a conversation a person forked from a `codex exec` run into the Desktop app.
pub const EXEC_FORK_ORIGINATORS: [&str; 1] = ["codex_exec"];
/// The originators confirmed not to be the app's desktop conversations (the closed deny-list of P19).
pub const NOT_DESKTOP_ORIGINATORS: [&str; 1] = ["codex_vscode"];

/// Codex's own four statuses (`"other"` is ours).
pub const KNOWN_STATUSES: [&str; 4] = ["completed", "failed", "inProgress", "interrupted"];

/// Item types that count as a turn having produced something. Anything Codex adds later does not count until it is
/// added here on purpose. In one order, for a query's parameters (`PROGRESS_KINDS`).
pub const PROGRESS_ITEM_TYPES: [&str; 4] = [
    "agentMessage",
    "commandExecution",
    "fileChange",
    "mcpToolCall",
];

/// `taken_thread_source(value, widened, composed)`: whether a conversation labelled `value` is one this product
/// takes up: a person's own, or - while the plug widens to every desktop conversation (P19) - any label but the
/// internal ones; an agent-made conversation only where `composed`.
pub fn taken_thread_source(value: &Value, widened: &BTreeSet<String>, composed: bool) -> Py<bool> {
    if pyval::is(value, AGENT_CREATED_THREAD) {
        return Ok(composed);
    }
    // `value in OWN_THREAD_SOURCES` hashes the value: a list or a dict raises.
    pyval::hashable(value)?;
    if matches!(value, Value::Null) || pyval::in_tuple(value, &["user", "chatgpt_handoff"]) {
        return Ok(true);
    }
    Ok(widened.contains("every_desktop")
        && match value {
            Value::Str(text) => {
                let length = text.len();
                0 < length
                    && length <= 64
                    && !text
                        .as_str()
                        .is_some_and(|word| INTERNAL_THREAD_SOURCES.contains(&word))
            }
            _ => false,
        })
}

/// `_turn_status(value)`: None, one of Codex's four, or `"other"`.
pub fn turn_status(value: &Value) -> Py<Option<&'static str>> {
    if matches!(value, Value::Null) {
        return Ok(None);
    }
    pyval::hashable(value)?;
    Ok(Some(
        KNOWN_STATUSES
            .iter()
            .find(|word| pyval::is(value, word))
            .copied()
            .unwrap_or("other"),
    ))
}

/// `_turn_status(row["status"])` for a value read from a column: a BLOB, which this crate carries as an empty list, is
/// Python's `bytes` - hashable, and no status of Codex's.
pub fn row_status(value: &Value) -> Py<Option<&'static str>> {
    if matches!(value, Value::Array(items) if items.is_empty()) {
        return Ok(Some("other"));
    }
    turn_status(value)
}

/// `epoch(value)`: a plausible time in Codex's window (2000 to 2100), a number and no subclass.
pub fn epoch(value: &Value) -> Py<bool> {
    let (low, high) = states::EPOCH_CODEX;
    states::epoch(value, low, high, false, true)
}

/// `_json(value)`: the JSON a row holds, or None for anything that is not text, is too long (in characters) or is
/// not JSON (or nested too deep to be read).
pub fn json_of(value: &Value) -> Option<Value> {
    let Value::Str(text) = value else {
        return None;
    };
    if text.len() > MAX_ITEM_BYTES {
        return None;
    }
    loads(text.as_str()?).ok()
}

/// `_json(text)` of a text that is plain UTF-8.
pub fn json_text(text: &str) -> Option<Value> {
    if text.len() > MAX_ITEM_BYTES && text.chars().count() > MAX_ITEM_BYTES {
        return None;
    }
    loads(text).ok()
}

pub fn text_value(text: &str) -> Value {
    Value::Str(Str::from(text))
}

fn dict_get<'a>(value: &'a Value, key: &str) -> Option<&'a Value> {
    match value {
        Value::Object(map) => map.get(key),
        _ => None,
    }
}

static NULL: Value = Value::Null;

fn or_null(value: Option<&Value>) -> &Value {
    value.unwrap_or(&NULL)
}

/// `normalize(row)`: just the required scalar fields of a turn's row, its raw error text discarded: None for a row
/// that is not one of a turn this product reads.
pub fn normalize(row: &Value) -> Py<Option<Map>> {
    let Value::Object(map) = row else {
        return Ok(None);
    };
    let thread = or_null(map.get("thread_id"));
    let turn = or_null(map.get("turn_id"));
    let status = or_null(map.get("status"));
    let ordinal = match map.get("ordinal") {
        Some(found) => found,
        None => or_null(map.get("rollout_ordinal")),
    };
    let status_word = match status {
        Value::Str(text) => text.as_str(),
        _ => None,
    };
    if !ids::is_uuid(thread)
        || !ids::is_uuid(turn)
        || !matches!(status, Value::Str(_))
        || !status_word.is_some_and(|word| KNOWN_STATUSES.contains(&word))
        || !pyval::is_int(ordinal)
        || pyval::less(ordinal, &Value::from(0))?
    {
        return Ok(None);
    }
    let started = or_null(map.get("started_at"));
    let completed = or_null(map.get("completed_at"));
    if !epoch(started)? || (!matches!(completed, Value::Null) && !epoch(completed)?) {
        return Ok(None);
    }
    if !matches!(completed, Value::Null) && pyval::less(completed, started)? {
        return Ok(None);
    }
    let category: Option<&'static str>;
    let wait: Option<i64>;
    if map.contains_key("category") {
        // Already normalized once: keep the decision rather than reclassifying from fields that no longer exist, so
        // normalize() stays idempotent.
        let held = &map["category"];
        pyval::hashable(held)?;
        category = failures::CATEGORIES
            .iter()
            .find(|word| pyval::is(held, word))
            .copied();
        wait = failures::wait_seconds(or_null(map.get("retry_after")));
    } else {
        let (info, text) = error_parts(map);
        // The raw error is classified here and then dropped: only the category name continues past this point, so no
        // error text can reach state, logs or a toast.
        category = (status_word == Some("failed")).then(|| failures::classify(&info, &text));
        // v0.6.11: a Retry-After the structured error names, kept as a number of seconds for a temporary failure only.
        wait = if category.is_some_and(|word| failures::TRANSIENT.contains(&word)) {
            failures::retry_after(&info)
        } else {
            None
        };
    }
    let mut found = Map::new();
    found.insert(Str::from("thread_id"), thread.clone());
    found.insert(Str::from("turn_id"), turn.clone());
    found.insert(Str::from("status"), status.clone());
    found.insert(Str::from("started_at"), started.clone());
    found.insert(Str::from("completed_at"), completed.clone());
    found.insert(Str::from("ordinal"), ordinal.clone());
    found.insert(
        Str::from("category"),
        category.map_or(Value::Null, Value::from),
    );
    if let Some(seconds) = wait
        && category.is_some_and(|word| failures::TRANSIENT.contains(&word))
    {
        found.insert(Str::from("retry_after"), Value::from(seconds));
    }
    Ok(Some(found))
}

/// The structured error of a row and its message: `error_json` read as `_json` reads it, else the row's
/// `error_info` (or `codexErrorInfo`) and `message`.
fn error_parts(row: &Map) -> (Value, Value) {
    if let Some(raw) = row.get("error_json") {
        let err = json_of(raw);
        let info = err
            .as_ref()
            .and_then(|each| dict_get(each, "codexErrorInfo"));
        let text = err.as_ref().and_then(|each| dict_get(each, "message"));
        return (
            info.cloned().unwrap_or(Value::Null),
            text.cloned().unwrap_or(Value::Null),
        );
    }
    let info = match row.get("error_info") {
        Some(found) => found.clone(),
        None => or_null(row.get("codexErrorInfo")).clone(),
    };
    (info, or_null(row.get("message")).clone())
}

/// `error_shape(row)`: what a failed turn's error says of itself (`failures.shape`), read from its row as
/// `normalize` reads it: Codex's code, a status, a form, whether a message exists - never the message. An error that
/// is there and is no JSON object is unrecognised.
pub fn error_shape(row: &Map) -> Value {
    if let Some(raw) = row.get("error_json") {
        let err = json_of(raw);
        if !matches!(raw, Value::Null) && !matches!(err, Some(Value::Object(_))) {
            return failures::shape(&Value::Bool(false), &Value::Null);
        }
    }
    let (info, text) = error_parts(row);
    failures::shape(&info, &text)
}
