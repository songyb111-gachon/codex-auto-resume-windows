//! `codex_auto_resume/domain/`: what the product's values are, with no side effects.
//!
//! `errors`, `ids`, `skips`, `states`, `usage`, `public` are ported here; the vocabularies (`vocabulary`,
//! `compat_vocabulary`, `power_vocabulary`, `reason_vocabulary`) are enums only and are generated into
//! [`crate::vocab_gen`]. `gates` and `plug*` belong to car-policy (PLAN 1.2), and `public`'s self-check reader
//! (`self_check`, which reads `failures.TAG_SHAPE`) moves there with them (cut C1).

pub mod errors;
pub mod ids;
pub mod public;
pub mod skips;
pub mod states;
pub mod usage;
