//! car-adv: the advanced edition's one crate (D19). Mirrors the Python package `codex_auto_resume_advanced`.
//!
//! Seat S7.1a: the advanced store - [`state`] (advanced.sqlite), [`ledger`] (P11, inside core's claim), [`profiles`]
//! (the saved accounts), [`watchlog`] (what a watched capability would have done) and [`images`] (a queued prompt's
//! pictures).
//!
//! Seat S7.1b: the capabilities' registry, arming, statements, vocabulary and policy - `registry`, `arming`,
//! `statement`, `vocabulary`, `policy`, `standards`, `measured` - and the seams they reach the rest through
//! (`seam`). The `_gen` files are written by `tests/rustdiff/gen_advpolicy.py` from the reference tag's own package.

pub mod arming;
pub mod images;
pub mod jsonx;
pub mod ledger;
pub mod measured;
#[rustfmt::skip]
mod measured_gen;
pub mod policy;
pub mod profiles;
pub mod registry;
#[rustfmt::skip]
mod registry_gen;
pub mod seam;
pub mod seam_autocheck;
#[rustfmt::skip]
mod seam_autocheck_gen;
pub mod standards;
#[rustfmt::skip]
mod standards_gen;
pub mod state;
pub mod statement;
#[rustfmt::skip]
mod statement_gen;
pub mod vocabulary;
#[rustfmt::skip]
mod vocabulary_gen;
pub mod watchlog;
