//! `measured.py`: what each measurement found, as this build ships it - its verdict and the Codex it was made on.
//!
//! The table is the build-time one the tag ships (`measured_gen.rs`, written by `tests/rustdiff/gen_advpolicy.py` from
//! `measured.MEASURED`). Pure: a table, and nothing read. A measurement is here only when it settled; one that is not here
//! was never measured, as far as this build knows.

use std::collections::BTreeMap;

use crate::vocabulary::{Measurement, Verdict};

pub use crate::measured_gen::MEASURED;

/// A table of what the measurements found, as `arming` reads one (`measured.MEASURED`'s shape): each measurement's
/// verdict and the engine version it was made on.
pub type Table = BTreeMap<Measurement, (Verdict, String)>;

/// `MEASURED` as a `Table`.
pub fn table() -> Table {
    MEASURED
        .iter()
        .map(|(measurement, verdict, engine)| (*measurement, (*verdict, (*engine).to_owned())))
        .collect()
}

/// The measurements in the order the tag's dict has them (a `BTreeMap` has its own).
pub fn order() -> Vec<Measurement> {
    MEASURED
        .iter()
        .map(|(measurement, _, _)| *measurement)
        .collect()
}
