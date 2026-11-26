//! The edition's plug's own work, claimed and guarded as core's is (`store/plugclaims.py`, v0.6.14; seat S7.2a).
//!
//! What a plug answers and core carries out of its own is held to the same write lock as core's claims and launches:
//! P8's errand makes its one irrevocable write - a request to Codex - inside [`Store::errand_guard`], which a Pause,
//! Observe only or quiet hours that committed first refuse. The standard edition's plug answers none of it, so none of
//! this runs there.
//!
//! Not ported here (left for the next S7.2 seat, rust/GROUNDWORK.md "Seat S7.2a"): `reserve_record` and `record_guard`
//! (a record of the plug's own, P2, claimed and launched under the plug's ledger) and the ledger's own asking inside a
//! claim (`store/ledger.py` `_ledger_holds`, P11), which need the plug handed to the claim.

use car_machine::json::Value;

use crate::errors::{Error, Result};
use crate::session::{Store, read_settings};

impl Store {
    /// `with store.errand_guard(held=held) as permitted:` - `body` runs inside one write transaction with `permitted`:
    /// recovery on and not only observed, read under the lock, and nothing `held` says (asked only where the store
    /// permits). A `held` that raises ends the guard with its exception, as the reference's context manager does.
    pub fn errand_guard<T>(
        &self,
        held: Option<&mut dyn FnMut() -> std::result::Result<bool, &'static str>>,
        body: impl FnOnce(bool) -> T,
    ) -> Result<T> {
        self.transaction(|connection| {
            let settings = read_settings(connection)?;
            let on = |name: &str| matches!(settings.get(name), Some(Value::Bool(true)));
            let mut permitted = on("enabled") && !on("observe_only");
            if permitted && let Some(held) = held {
                permitted = !held().map_err(|class| Error::Python(class, String::new()))?;
            }
            Ok(body(permitted))
        })
    }
}
