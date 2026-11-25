//! What the advanced store reads of modules other seats port, behind seams the integration replaces (rust/GROUNDWORK.md,
//! "The advanced store (S7.1a)" and "Integration 5"). The registry and the vocabulary are no longer seams: the store
//! reads `crate::registry` and `crate::vocabulary` (S7.1b's) directly.
//!
//! | here | stands in for | replaced by |
//! |---|---|---|
//! | [`hooks`] | `engine/hookclaims.py` `held`/`spent_on`, `control/sendnow.py` `fresh` | S7.2, S7.3 |
//! | [`Tokens`] | `secrets.token_hex` | car-platform's random source (none yet), at the entry points |

pub mod accounts;
pub mod hooks;

/// `secrets.token_hex(count)`: `count` random bytes as lowercase hex. The OS's random source is car-platform's to
/// give (D3: every Windows call lives there; it has none yet), so the caller hands one in; the diffs hand both
/// implementations the same counter.
pub trait Tokens: Send + Sync {
    fn hex(&self, count: usize) -> String;
}
