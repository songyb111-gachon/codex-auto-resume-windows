//! The edges between the P7 seats (seat S7.2a's skeleton, P7-DESIGN 2.1): every import of the tag's advanced package
//! from one seat's module into another's that is not yet ported, as one function, trait or constant here with the
//! reference's own signature, so a seat codes against this file and the integration that merges the owner replaces the
//! body with a call into the owner's module and deletes the entry. Edges into modules already ported are not here: a
//! seat calls those modules themselves.
//!
//! Integration 10 merged S7.2a, S7.2b, S7.2d, S7.2e1, S7.2e2 and S7.3b and deleted every entry whose both ends are now in
//! the branch, each caller pointed at the owner (rust/GROUNDWORK.md "Integration 10"):
//!
//! | from (seat) | to (owner) | now |
//! |---|---|---|
//! | runtime (S7.2a) | engine/continued, engine/resetmessage (S7.2d) | `continued::handed`, `resetmessage::handed` |
//! | runtime (S7.2a) | engine/chat, promptqueue, foropen, sessions, silent (S7.2e1) | each module's `CAPABILITY`, `chat::watched`, `promptqueue::handed`, `foropen::watching` |
//! | engine/account (S7.2b) | engine/resetwatch (S7.2d) | `resetwatch::count` (the `ResetWatch` trait and S7.2b's `TagCount` are gone) |
//! | engine/autoswitch (S7.2b) | engine/opentarget (S7.2e1) | `opentarget.idle_seconds()` is core's `powerdown.idle_seconds()`: car-platform's, read by autoswitch itself (the `OpenTarget` trait, which nothing asked, is gone) |
//! | engine/chat, emptyreply, subagent (S7.2e1) | engine/usage (S7.2d) | `usage::PAUSE`, `usage::EVERY_CONVERSATION` |
//! | engine/emptyreply, keepgoing, subagent (S7.2e1) | engine/continued (S7.2d) | `continued::{handed, answer_key_text, words_pass}` |
//! | engine/anchor (S7.2e2) | engine/wrapwords (S7.2d) | `wrapwords::ON` (anchor read it there already) |
//! | engine/retries (S7.2e1) | codex/account (S7.2b) | `codex::account::parse` (the `AccountReply` trait is gone) |
//!
//! What is left waits for a seat not merged yet:
//!
//! | from (seat) | to (owner) | here |
//! |---|---|---|
//! | engine/opentarget (S7.2e1) | control/opencodex (S7.3a) | [`OpenCodex`] |
//! | runtime (S7.2a) | measure (S7.4) | `runtime::measurement` (S7.4's own file) |
//! | surfaces (S7.3a) | control/courier, control/remote, courier/feed (S7.3b) | the entries S7.3a adds against S7.3b's modules, merged here |
//! | measure, evidence (S7.4) | codex/account, authfile, restart, swap (S7.2b); engine/emptyreply, retries, subagent (S7.2e1); engine/anchor (S7.2e2) | S7.4 calls the owners (all merged) |

/// `control/opencodex.handler_registered(read=None) -> bool` (S7.3a), for `engine/opentarget` (S7.2e1).
pub trait OpenCodex {
    fn handler_registered(&self) -> bool;
}
