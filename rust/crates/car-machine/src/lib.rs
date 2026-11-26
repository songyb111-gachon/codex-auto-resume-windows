//! car-machine: the domain's values (states, ids, errors, vocabularies, usage), the compatibility registry's data
//! types and format, and the Python-compatible JSON writer. Pure: no file, no process, no clock, no Windows call.
//!
//! Each module says which Python module it replaces, and `tests/rustdiff/diffs_leaves_machine.py` holds it to the
//! reference tag's own answers.

pub mod caught;
pub mod compat;
pub mod domain;
pub mod hash;
pub mod json;
pub mod localclock;
pub mod pybytes;
pub mod pyfile;
pub mod pytext;
#[rustfmt::skip]
mod pytext_tables;
pub mod pyval;
pub mod stack;
pub mod vocab;
pub mod winpath;
#[rustfmt::skip]
pub mod vocab_gen;
