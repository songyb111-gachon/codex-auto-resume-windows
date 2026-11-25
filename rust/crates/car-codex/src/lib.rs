//! car-codex: Codex's own files, read (PLAN 1.2 row 8).
//!
//! This is the readers' half (seat S3.2) - `codex/` but its transport, app server, pairing and layout, and none of
//! `compat/` - which replaces the implementation, not the behaviour, of the reference tag's:
//!
//! | here | the reference |
//! |---|---|
//! | `paths`, `sql`, `source` | `codex/paths.py`, `codex/schema.py`, `codex/history.py`, `codex/__init__.py`: finding the databases, refusing one whose schema has moved, and every statement this product sends to Codex |
//! | `rollout` | `codex/rollout.py`: a conversation's file, and the split ids it carries |
//! | `payload`, `values`, `labels` | `codex/payload.py`, `codex/values.py`, `codex/labels.py`: one interruption read out of what Codex recorded |
//! | `eligibility`, `workspace`, `usage`, `chains` | the module of the same name in `codex/` |
//! | `errors` | `codex/errors.py` and the exceptions the reference lets through |
//!
//! Everything is read-only: the connections are opened `mode=ro` with `query_only`, and nothing here writes to Codex.
//! Held to the reference by `tests/rustdiff/diffs_codex_*.py` against v0.6.26-beta.2.

pub mod appserver;
pub mod chains;
pub mod compat;
pub mod compatio;
pub mod eligibility;
pub mod errors;
pub mod labels;
pub mod layout;
pub mod pairing;
pub mod paths;
pub mod payload;
#[rustfmt::skip]
mod printable_gen;
pub mod refold;
pub mod rollout;
pub mod source;
pub mod sql;
pub mod system;
pub mod transport;
pub mod usage;
pub mod values;
pub mod workspace;

pub use errors::{Error, Result, SourceError};
pub use source::{LocalSource, Verdict, Why, Written};
