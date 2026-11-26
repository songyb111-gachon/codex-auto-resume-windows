//! `codex/`: reading and talking to Codex, the advanced edition's own (seat S7.2c).
//!
//! `protocol` (the methods each measurement and capability may call, and the refusals), `inuse` (the Codex an
//! installation drives, and what the app main ran instead), the read-only readers of Codex's own files (`turns`,
//! `lineage`, `threads`, `conversation`, `sessions`, `goals`) and `credits` (a usage reply as the reset actions keep it).
//! The saved accounts' modules (`authfile`, `account`, `swap`, `restart`) are seat S7.2b's.

#[rustfmt::skip]
mod alpha_gen;
pub mod conversation;
pub mod credits;
pub mod goals;
pub mod headless;
pub mod inuse;
pub mod ipc;
pub mod lineage;
pub mod protocol;
pub mod session;
pub mod sessions;
pub mod threads;
pub mod tokens;
pub mod turns;
pub mod wmi_escape;
