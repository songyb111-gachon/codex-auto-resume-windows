//! The edges between the P7 seats (seat S7.2a's skeleton, P7-DESIGN 2.1): every import of the tag's advanced package
//! from one seat's module into another's that is not yet ported, as one function or constant here with the reference's
//! own signature, so a seat codes against this file and the integration that merges the owner replaces the body with a
//! call into the owner's module (and then deletes the entry). Edges into modules already ported (S7.1, S7.2c, S7.3c)
//! are not here: a seat calls those modules themselves.
//!
//! Computed from the tag's import graph (`python s72a-tools/edges.py`, the list in rust/GROUNDWORK.md "Seat S7.2a"):
//!
//! | from (seat) | to (owner) | here |
//! |---|---|---|
//! | runtime (S7.2a) | engine/continued (S7.2d) | [`continued_handed`] |
//! | runtime (S7.2a) | engine/resetmessage (S7.2d) | [`reset_message_handed`] |
//! | runtime (S7.2a) | engine/chat (S7.2e1) | [`CHAT`], [`chat_watched`] |
//! | runtime (S7.2a) | engine/promptqueue (S7.2e1) | [`PROMPT_QUEUE`], [`prompt_handed`] |
//! | runtime (S7.2a) | engine/foropen (S7.2e1) | [`QUEUE_FOR_OPEN`], [`for_open_watching`] |
//! | runtime (S7.2a) | engine/sessions, engine/silent (S7.2e1) | [`OTHER_SESSIONS`], [`SILENT`] |
//! | runtime (S7.2a) | measure (S7.4) | `runtime::measurement` (S7.4's own file) |
//! | engine/account (S7.2b) | engine/resetwatch (S7.2d) | [`ResetWatch`] |
//! | engine/autoswitch (S7.2b) | engine/opentarget (S7.2e1) | [`OpenTarget`] |
//! | engine/chat, emptyreply, subagent (S7.2e1) | engine/usage (S7.2d) | [`USAGE_PAUSE`], [`EVERY_CONVERSATION`] |
//! | engine/emptyreply, keepgoing, subagent (S7.2e1) | engine/continued (S7.2d) | [`continued_handed`], [`answer_key`], [`words_pass`] |
//! | engine/anchor (S7.2e2) | engine/wrapwords (S7.2d) | [`WRAP_WORDS_ON`] |
//! | engine/retries (S7.2e1) | codex/account (S7.2b) | [`AccountReply`] |
//! | engine/opentarget (S7.2e1) | control/opencodex (S7.3a) | [`OpenCodex`] |
//! | surfaces (S7.3a) | control/courier, control/remote, courier/feed (S7.3b) | `seam_p7` entries S7.3a adds with S7.3b in wave 3 |
//! | measure, evidence (S7.4) | codex/account, authfile, restart, swap (S7.2b); engine/emptyreply, retries, subagent (S7.2e1); engine/anchor (S7.2e2) | S7.4 runs after waves 1-2: it calls the owners |
//!
//! The pure functions S7.2a's runtime needs now (`*_handed`, `chat_watched`, `for_open_watching`) are ported here,
//! faithfully, so the runtime's P2 is equal before their owners exist; the owner moves each into its module.

use car_machine::json::Value;

/// `engine/chat.CAPABILITY`.
pub const CHAT: &str = "codex_chat";
/// `engine/promptqueue.CAPABILITY`.
pub const PROMPT_QUEUE: &str = "prompt_queue";
/// `engine/foropen.CAPABILITY`.
pub const QUEUE_FOR_OPEN: &str = "queue_for_open";
/// `engine/sessions.CAPABILITY`.
pub const OTHER_SESSIONS: &str = "other_sessions";
/// `engine/silent.CAPABILITY`.
pub const SILENT: &str = "silent_continuation";
/// `engine/usage.PAUSE`.
pub const USAGE_PAUSE: &str = "usage_pause";
/// `engine/usage.EVERY_CONVERSATION`.
pub const EVERY_CONVERSATION: &str = "every_conversation";
/// `engine/wrapwords.ON`.
pub const WRAP_WORDS_ON: i64 = 1;

/// `engine/resetwatch.count(rule, row) -> int` (S7.2d), for `engine/account` (S7.2b).
pub trait ResetWatch {
    fn count(&self, rule: &Value, row: &Value) -> i64;
}

/// `engine/opentarget.idle_seconds()` (S7.2e1), for `engine/autoswitch` (S7.2b).
pub trait OpenTarget {
    fn idle_seconds(&self) -> Option<f64>;
}

/// `control/opencodex.handler_registered(read=None) -> bool` (S7.3a), for `engine/opentarget` (S7.2e1).
pub trait OpenCodex {
    fn handler_registered(&self) -> bool;
}

/// `codex/account.parse(reply) -> dict` (S7.2b), for `engine/retries` (S7.2e1).
pub trait AccountReply {
    fn parse(&self, reply: &Value) -> Value;
}

/// `engine/continued.answer_key(*parts)` (S7.2d): 64 hex digits of what a continuation answers. Filled by S7.2a's
/// next commit.
pub fn answer_key(_parts: &[String]) -> String {
    String::new()
}

/// `engine/continued.words_pass(words)` (S7.2d). Filled by S7.2a's next commit.
pub fn words_pass(_words: &Value) -> bool {
    false
}

/// `engine/continued.handed(row)` (S7.2d). Filled by S7.2a's next commit.
pub fn continued_handed(_row: &Value) -> Option<Value> {
    None
}

/// `engine/resetmessage.handed(rule)` (S7.2d). Filled by S7.2a's next commit.
pub fn reset_message_handed(_rule: &Value) -> Option<Value> {
    None
}

/// `engine/promptqueue.handed(row)` (S7.2e1). Filled by S7.2a's next commit.
pub fn prompt_handed(_row: &Value) -> Option<Value> {
    None
}

/// `engine/chat.watched(row, now, stops)` (S7.2e1). Filled by S7.2a's next commit.
pub fn chat_watched(_row: &Value, _now: f64, _stops: &[Value]) -> Option<Value> {
    None
}

/// `engine/foropen.watching(record)` (S7.2e1). Filled by S7.2a's next commit.
pub fn for_open_watching(_record: &Value) -> bool {
    false
}
