//! `codex/`: reading and talking to Codex, the advanced edition's own (seat S7.2c).
//!
//! `protocol` (the methods each measurement and capability may call, and the refusals), `inuse` (the Codex an
//! installation drives, and what the app main ran instead). The saved accounts' modules (`authfile`, `account`, `swap`,
//! `restart`) are seat S7.2b's.

pub mod inuse;
pub mod protocol;
