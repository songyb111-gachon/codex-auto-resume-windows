//! The panic test's trip wire (P6-DESIGN 1.3, D15), built only with the feature `panic-test`.
//!
//! A core built with the feature panics on purpose, once per place, where `CAR_CORE_PANIC` names that place: `tick`
//! (inside the span one tick's `try` covers), `worker` (inside the toasts worker's one notice) or an export's name
//! (car-host). The boundaries must catch each: the tick costs that tick, the worker that notice, the export answers
//! `panic`, and the next one runs. A build without the feature has no wire and does not name the variable at all;
//! car-host's `panic_feature` test reads the release DLL's bytes for it.

/// Panics the first time `place` is reached while `CAR_CORE_PANIC` names it (comma-separated places allowed).
#[cfg(feature = "panic-test")]
pub fn wire(place: &str) {
    use std::collections::BTreeSet;
    use std::sync::{Mutex, PoisonError};
    static TRIPPED: Mutex<BTreeSet<String>> = Mutex::new(BTreeSet::new());
    let named = std::env::var("CAR_CORE_PANIC").unwrap_or_default();
    if !named.split(',').any(|each| each.trim() == place) {
        return;
    }
    if TRIPPED
        .lock()
        .unwrap_or_else(PoisonError::into_inner)
        .insert(place.to_owned())
    {
        panic!("the panic test tripped in {place}");
    }
}

/// Nothing: the feature is off.
#[cfg(not(feature = "panic-test"))]
#[inline(always)]
pub fn wire(_place: &str) {}
