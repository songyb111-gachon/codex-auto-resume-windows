//! car-adv: the advanced edition (D19: one crate in the alpha).
//!
//! Seat S7.1a: the advanced store - [`state`] (advanced.sqlite), [`ledger`] (P11, inside core's claim), [`profiles`]
//! (the saved accounts), [`watchlog`] (what a watched capability would have done) and [`images`] (a queued prompt's
//! pictures). Seat S7.1b adds the registry, arming, the statement, the vocabulary and the policy beside them.

pub mod state;
