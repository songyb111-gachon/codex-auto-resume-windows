//! car-adv: the advanced edition's one crate (D19). Mirrors the Python package `codex_auto_resume_advanced`.
//!
//! Seat S7.1a: the advanced store - [`state`] (advanced.sqlite), [`ledger`] (P11, inside core's claim), [`profiles`]
//! (the saved accounts), [`watchlog`] (what a watched capability would have done) and [`images`] (a queued prompt's
//! pictures).
//!
//! Seat S7.1b: the capabilities' registry, arming, statements, vocabulary and policy - `registry`, `arming`,
//! `statement`, `vocabulary`, `policy`, `standards`, `measured` - and the seams they reach the rest through
//! (`seam`). The `_gen` files are written by `tests/rustdiff/gen_advpolicy.py` from the reference tag's own package.
//!
//! Seat S7.2c: reading and talking to Codex - [`codex`] (`protocol`, `inuse` and the readers), [`autocheck`] (the
//! automatic compatibility check; it replaced S7.1b's `seam_autocheck`), [`compatdata`] (the advanced compatibility data)
//! and [`pytime`] (`time.strptime` for the forms they read).
//!
//! Seat S7.2c remainder (adv72d): [`win`] (`stopflag`, `waketimer`; their Windows calls are car-platform's `wake`),
//! `codex::{tokens, wmi_escape, headless, ipc}`, `protocol::Session` and `turns::booted_of`.
//!
//! Seat S7.3c: the in-app compatibility report - [`report`] (it reads through car-control's `ownreport`, the one port
//! of core's reader since Integration 8) - and the Stop hook: [`hook`], `engine::hookclaims`, `control::hookplugin`.
//!
//! Seat S7.2a: the skeleton of P7 (P7-DESIGN 2.1) - every module of the plan below, each file named for the seat that
//! owns it (2.2), so no later seat edits this file, a `mod.rs` or `Cargo.toml` - and the plug's two halves: [`plug`]
//! (`AdvancedPlug`, the one thing core reaches), [`runtime`] (the registry's capabilities asked at the plug's points),
//! [`capabilities`] (a capability's code, `Code`, and the `make` table), [`credentials`] (the saved secrets over
//! car-platform's Credential Manager), [`seam_p7`] (the edges between the P7 seats) and [`testguard`].

pub mod arming;
pub mod autocheck;
pub mod capabilities;
pub mod codex;
pub mod compat_views;
pub mod compatdata;
pub mod control;
pub mod courier;
pub mod credentials;
pub mod engine;
pub mod evidence;
pub mod hook;
pub mod images;
pub mod jsonx;
pub mod ledger;
pub mod measure;
pub mod measured;
#[rustfmt::skip]
mod measured_gen;
pub mod plug;
pub mod policy;
pub mod profiles;
pub mod pytime;
pub mod registry;
pub mod report;
pub mod runtime;
#[rustfmt::skip]
mod registry_gen;
pub mod seam;
pub mod seam_p7;
pub mod standards;
#[rustfmt::skip]
mod standards_gen;
pub mod state;
pub mod statement;
pub mod surfaces;
#[rustfmt::skip]
mod statement_gen;
pub mod vocabulary;
#[rustfmt::skip]
mod vocabulary_gen;
pub mod testguard;
pub mod watchlog;
pub mod win;
