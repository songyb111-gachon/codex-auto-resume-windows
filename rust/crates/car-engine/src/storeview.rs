//! The engine's store as a plug is shown it: the reads, and none of the writes (`engine/storeview.py`).
//!
//! car-policy's [`View`] is the trait a hook is handed at P2, P8 and P22; NULL reads nothing through it. The reads
//! themselves (`VIEW_READS`) are the advanced plug's to call and come with its seat (S7.2).

use car_policy::plug::View;

/// What a plug is shown of the store, at P2, P8 and P22.
pub const VIEW_READS: &[&str] = &[
    "get",
    "records_in",
    "settings",
    "thread_enabled",
    "others_in_flight",
    "recent_claims",
    "recent_claim_count",
    "claimed_on_thread",
    "last_usage",
];

/// The view a hook is handed.
pub struct StoreView;

impl View for StoreView {}
