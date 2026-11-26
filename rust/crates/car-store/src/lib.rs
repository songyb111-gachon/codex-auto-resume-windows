//! car-store: the state this product keeps - one SQLite file, `state.sqlite`, and the rules for writing it.
//!
//! The port of `src/codex_auto_resume/store/` and `openstate.py` (PLAN 1.2 row 7, seat S1.2). The
//! implementation is replaced, not the behaviour: the reference (the v0.6.26 tag; v0.6.26-beta.2 until it
//! exists) and this crate open, migrate, write and downgrade the same files to the same bytes, and each
//! reads what the other wrote (`tests/rustdiff/diffs_store.py`).
//!
//! | Python | here |
//! |---|---|
//! | `store/session.py` | [`session`]: the connection, its PRAGMAs, `BEGIN IMMEDIATE` / `BEGIN`, the busy timeout |
//! | `store/schema.py`, `store/columns.py` | [`schema`], [`columns`] (D13: schema 5, readable from 5, the mark) |
//! | `store/migrations.py` | [`migrations`] (1 -> 2 -> 3 -> 4 -> 5) |
//! | `store/validate.py`, `store/errors.py` | [`validate`], [`errors`] |
//! | `store/journal.py` | [`journal`] |
//! | `store/policy.py`, `records.py`, `claims.py`, `actions.py`, `schedule.py` | [`policy`], [`records`], [`claims`], [`actions`], [`schedule`] |
//! | `store/watcher.py`, `notices.py`, `reporting.py` | [`watcher`] |
//! | `store/legacy.py`, `store/downgrade.py` | [`legacy`], [`downgrade`] |
//! | `openstate.py` | [`open`] (cut C3: the Windows calls come in as a trait) |
//!
//! Not ported here, and why: `store/ledger.py`'s plug ledger (P11) and `store/plugclaims.py` need the
//! edition's `Plug` trait, which is car-policy's (S2.2); the claim here is the NULL plug's, the standard
//! edition's. What the store reads of the domain is car-machine's, through [`machine`]; what it reads of the policy
//! before car-policy exists is in [`seam`], marked for replacement.
//!
//! Values are Python's: a row is car-machine's [`Value`](car_machine::json::Value) map, so the store's checks
//! keep their dynamic meaning (a REAL column holding text fails its check, `1 == 1.0`). Times passed in are
//! `f64`, as `time.time()` gives them.

pub mod actions;
pub mod claims;
pub mod columns;
pub mod downgrade;
pub mod errors;
pub mod journal;
pub mod legacy;
pub mod machine;
pub mod migrations;
pub mod open;
pub mod plugclaims;
pub mod policy;
pub mod records;
pub mod schedule;
pub mod schema;
pub mod seam;
pub mod session;
pub mod validate;
pub mod value;
pub mod watcher;

pub use errors::{Error, Kind, Result};
pub use legacy::LegacyStore;
pub use schema::{READABLE_FROM, SCHEMA_VERSION};
pub use session::{Options, Store};
pub use value::Row;

/// The bundled SQLite's version (D4 pins it at or above the bundled Python's).
pub fn sqlite_version() -> &'static str {
    rusqlite::version()
}
