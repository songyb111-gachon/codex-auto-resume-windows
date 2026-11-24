//! What is left of the store's seam: CPython's own readings of a text ([`python`]), which are the store's.
//!
//! The policy the store reads - the failure categories, the notice kinds, the gates and their words, `is_recoverable`,
//! `postponement_problem`, `KEEP_SECONDS`, `CAPACITY_MAX_SECONDS`, `USAGE_LIMIT` - is car-policy's (S2.1) and comes from
//! [`car_policy::classify`] through [`crate::machine`]'s `policy` module.

pub mod python;
