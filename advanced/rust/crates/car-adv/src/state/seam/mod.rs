//! What the advanced store reads of modules other seats port, behind seams the integration replaces (rust/GROUNDWORK.md,
//! "The advanced store (S7.1a)"):
//!
//! | here | stands in for | replaced by |
//! |---|---|---|
//! | [`registry`], `registry_gen.rs` | `registry.py`'s `REGISTRY`, `GLOBAL_HOURLY`, `CORE_DAILY_CAP`, `CORE_COOLDOWN_SECONDS` | S7.1b's registry |
//! | `words_gen.rs` | `vocabulary.py`'s StrEnums and `KEPT_NOTICES` | S7.1b's vocabulary |
//! | [`hooks`] | `engine/hookclaims.py` `held`/`spent_on`, `control/sendnow.py` `fresh` | S7.2, S7.3 |
//! | [`Tokens`] | `secrets.token_hex` | car-platform's random source (none yet), at the entry points |

pub mod accounts;
pub mod hooks;
pub mod registry;
#[rustfmt::skip]
pub mod registry_gen;
#[rustfmt::skip]
pub mod words_gen;

/// `secrets.token_hex(count)`: `count` random bytes as lowercase hex. The OS's random source is car-platform's to
/// give (D3: every Windows call lives there; it has none yet), so the caller hands one in; the diffs hand both
/// implementations the same counter.
pub trait Tokens: Send + Sync {
    fn hex(&self, count: usize) -> String;
}
