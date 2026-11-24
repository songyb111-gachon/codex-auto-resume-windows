//! car-config: paths, the product version, the one official codex.exe, and the log (PLAN 1.2 row 4).
//!
//! Replaces `config.py` (without its three settings loaders, which read `settings` and so are car-policy's, cut C2),
//! `logbook.py` and the package root's `__version__` (a manifest read, `codex::version`). What only the platform can
//! ask - the registry's long-path switch, the local time zone, whether a build passes the engine checks, which
//! images the app runs - is handed in. Held to the reference tag by `tests/rustdiff/diffs_leaves_config.py`.

pub mod codex;
pub mod logbook;
#[rustfmt::skip]
mod logbook_gen;
pub mod paths;
#[rustfmt::skip]
pub mod vocab_gen;
pub mod winpath;

pub use paths::{ConfigError, Os, Paths};
