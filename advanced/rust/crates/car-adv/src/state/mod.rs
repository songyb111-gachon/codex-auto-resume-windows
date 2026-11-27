//! The advanced edition's state: one file, `config/advanced/advanced.sqlite`, and nothing else (the package
//! `codex_auto_resume_advanced/state/`, seat S7.1a).
//!
//! The implementation is replaced, not the behaviour: the reference (the v0.6.26 tag; v0.6.26-beta.2 until it
//! exists) and this module open, migrate, write and read the same files to the same bytes, and each reads what the
//! other wrote (`tests/rustdiff/diffs_advstore*.py`). D13: schema 9, readable from 7.
//!
//! | Python | here |
//! |---|---|
//! | `state/session.py` | [`session`]: the file, its directory and marker, the opening and every upgrade, the transaction, `attach` |
//! | `state/schema.py` | [`schema`] and the generated `schema_gen.rs` |
//! | `state/arming.py`, `spend.py`, `records.py`, `journal.py`, `choices.py` | [`arming`], [`spend`], [`records`], [`journal`], [`choices`] |
//! | `state/resets.py`, `continuations.py`, `prompts.py`, `meter.py`, `runs.py`, `chat.py`, `analytics.py` | the modules of those names |
//! | `state/restarts.py`, `opens.py`, `account.py`, `steers.py` | [`small`] |
//! | `Scoped` and the tables' handles | [`scoped`] |
//! | `state/__init__.py` | this module ([`AdvancedState`]) |
//!
//! The methods take Python-model values (`car_machine::json::Value`) where the reference checks a value's type
//! itself, so a wrong type is refused exactly as there; [`calls`] is the reference's call surface by method name, which
//! the differential harness and a Python shim use. What it reads of modules other seats port is in [`seam`].

pub mod analytics;
pub mod arming;
pub mod ask;
pub mod builds;
pub mod calls;
pub mod chat;
pub mod choices;
pub mod continuations;
pub mod errors;
pub mod journal;
pub mod meter;
pub mod port;
pub mod prompts;
pub mod py;
pub mod records;
pub mod resets;
pub mod runs;
pub mod schema;
#[rustfmt::skip]
pub mod schema_gen;
pub mod scoped;
pub mod seam;
pub mod session;
pub mod small;
pub mod spend;
pub mod sql;

pub use errors::{Error, Result};
pub use journal::{EVENT_LIMIT, EVENT_MAX_AGE, WATCH_LIMIT};
pub use schema::{ATTACHED, FILE_NAME, SCHEMA_VERSION};
pub use session::{AdvancedState, Clock};
