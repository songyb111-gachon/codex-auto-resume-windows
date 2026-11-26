//! The engine's store as a plug is shown it: the reads, and none of the writes (`engine/storeview.py`).
//!
//! car-policy's [`View`] is the trait a hook is handed at P2, P8 and P22 (and an errand of P8's when it runs); NULL
//! reads nothing through it. Each read is the store's own, made when it is used, on this engine's own home alone
//! (`records_in` and `claimed_on_thread` with its home key), and `last_usage` is the engine's own last usage reading.

use car_machine::json::Value;
use car_policy::plug::{ReadFailed, View};

use crate::seam::Store;

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

/// The view a hook is handed: `StoreView(store, now, last_usage, home_key=home_key)`.
pub struct StoreView<'a> {
    store: &'a dyn Store,
    now: f64,
    last_usage: Value,
    home_key: &'a str,
}

impl<'a> StoreView<'a> {
    /// The view of `store` at `now`; `last_usage` is the engine's `last_usage()` as the hook would read it.
    pub fn new(
        store: &'a dyn Store,
        now: f64,
        last_usage: Option<(f64, Vec<Value>)>,
        home_key: &'a str,
    ) -> StoreView<'a> {
        let last_usage = match last_usage {
            Some((at, windows)) => Value::Array(vec![Value::Float(at), Value::Array(windows)]),
            None => Value::Null,
        };
        StoreView {
            store,
            now,
            last_usage,
            home_key,
        }
    }
}

fn read<T>(found: car_machine::pyval::Py<T>) -> Result<T, ReadFailed> {
    found.map_err(ReadFailed)
}

impl View for StoreView<'_> {
    fn now(&self) -> f64 {
        self.now
    }

    fn get(&self, interruption_id: &str) -> Result<Value, ReadFailed> {
        Ok(read(self.store.get(interruption_id))?.map_or(Value::Null, Value::Object))
    }

    fn records_in(&self, states: &[&str]) -> Result<Vec<Value>, ReadFailed> {
        Ok(read(self.store.records_in(states, Some(self.home_key)))?
            .into_iter()
            .map(Value::Object)
            .collect())
    }

    fn settings(&self) -> Result<Value, ReadFailed> {
        read(self.store.settings()).map(Value::Object)
    }

    fn thread_enabled(&self, thread_id: &str) -> Result<bool, ReadFailed> {
        read(self.store.thread_enabled(thread_id))
    }

    fn others_in_flight(&self, thread_id: &str, exclude: &str) -> Result<i64, ReadFailed> {
        read(self.store.others_in_flight(thread_id, exclude))
    }

    fn recent_claims(&self, thread_id: &str, since: f64) -> Result<Vec<Value>, ReadFailed> {
        read(self.store.recent_claims(thread_id, since))
    }

    fn recent_claim_count(&self, thread_id: &str, since: f64) -> Result<i64, ReadFailed> {
        read(self.store.recent_claim_count(thread_id, since))
    }

    fn claimed_on_thread(&self, thread_id: &str) -> Result<Vec<Value>, ReadFailed> {
        let home = self.home_key;
        Ok(read(self.store.claimed_on_thread(thread_id))?
            .into_iter()
            .filter(|row| matches!(row.get("home_key"), Some(Value::Str(key)) if key.as_str() == Some(home)))
            .map(Value::Object)
            .collect())
    }

    fn last_usage(&self) -> Value {
        self.last_usage.clone()
    }
}
