//! The edition's plug's own work, claimed and guarded as core's is (`store/plugclaims.py`, v0.6.14; seat S7.2a).
//!
//! What a plug answers and core carries out of its own is held to the same write lock as core's claims and launches:
//! P8's errand makes its one irrevocable write - a request to Codex - inside [`Store::errand_guard`], which a Pause,
//! Observe only or quiet hours that committed first refuse. The standard edition's plug answers none of it, so none of
//! this runs there.
//!
//! A record of the plug's own (P2, engine/plugrecords.rs) is claimed in [`Store::reserve_record`], which reads consent
//! and quiet hours again and asks the plug's ledger (P11, [`crate::ledger`]), and launched inside
//! [`Store::record_guard`], which reads consent again and asks the ledger once more (seat S7.2a2).

use car_machine::json::{Map, Value};
use car_policy::plug::{Guarded, Point};

use crate::claims::others_in_flight;
use crate::errors::{Error, Result};
use crate::ledger::ledger_holds;
use crate::machine::policy::gates::HELD;
use crate::policy::thread_enabled;
use crate::session::{Store, read_settings};
use crate::validate::{now as check_now, uuid};
use car_policy::classify::gates::{OBSERVE_ONLY, QUIET_HOURS};

/// (claimed, refusing gate, reason), as `reserve_detailed` answers.
pub type Claimed = (bool, Option<String>, Option<String>);

fn refused(gate: &str, reason: &str) -> Claimed {
    (false, Some(gate.to_owned()), Some(reason.to_owned()))
}

/// `record[name]`: KeyError where the record has none.
fn field<'a>(record: &'a Map, name: &str) -> Result<&'a Value> {
    record
        .get(name)
        .ok_or_else(|| Error::Python("KeyError", format!("'{name}'")))
}

/// `dict(record, phase=phase)`.
fn phased(record: &Map, phase: &str) -> Value {
    let mut told = record.clone();
    told.insert("phase".into(), Value::from(phase));
    Value::Object(told)
}

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

    /// `reserve_record(record, now, ledger=ledger, quiet_until=quiet_until)`: claim the right to send a record of the
    /// plug's own - consent read again (recovery on, not only observed, the conversation on), quiet hours, nothing of
    /// core's queued in the conversation, then the plug's ledger with `phase` "claim" and RECORDS carried. Anything
    /// but DEFER, or a ledger that raised, holds it; NULL's plug claims none.
    pub fn reserve_record(
        &self,
        record: &Map,
        now: f64,
        ledger: &Guarded,
        quiet_until: Option<f64>,
    ) -> Result<Claimed> {
        check_now(now)?;
        if ledger.is_null() {
            return Ok(refused("submission_safe", HELD));
        }
        let thread = field(record, "thread_id")?;
        uuid(thread, "thread_id")?;
        let thread = match thread {
            Value::Str(thread) => thread.as_str().unwrap_or_default().to_owned(),
            _ => return Err(Error::store("Invalid thread_id")),
        };
        self.transaction(|connection| {
            let settings = read_settings(connection)?;
            let on = |name: &str| crate::value::truthy(crate::value::get(&settings, name));
            if !on("enabled") {
                return Ok(refused("consent", "paused"));
            }
            if on("observe_only") {
                return Ok(refused("consent", OBSERVE_ONLY));
            }
            if !thread_enabled(connection, &thread)? {
                return Ok(refused("consent", "thread_disabled"));
            }
            if quiet_until.is_some() {
                return Ok(refused("schedule", QUIET_HOURS));
            }
            let exclude = match field(record, "record_id")? {
                Value::Str(id) => id.as_str().unwrap_or_default().to_owned(),
                _ => String::new(),
            };
            if others_in_flight(connection, &Value::from(thread.as_str()), &exclude)? != 0 {
                return Ok(refused("submission_safe", "other_recovery_in_flight"));
            }
            if ledger_holds(
                connection,
                ledger,
                self.links.as_ref(),
                &phased(record, "claim"),
                now,
                &[Point::Records],
            )? {
                return Ok(refused("submission_safe", HELD));
            }
            Ok((true, None, None))
        })
    }

    /// `with store.record_guard(record, ledger, now) as permitted:` - the launch guard of a record of the plug's own:
    /// consent read under the write lock, and the ledger asked in the same transaction with `phase` "launch".
    pub fn record_guard<T>(
        &self,
        record: &Map,
        ledger: &Guarded,
        now: f64,
        body: impl FnOnce(bool) -> T,
    ) -> Result<T> {
        self.transaction(|connection| {
            let settings = read_settings(connection)?;
            let on = |name: &str| crate::value::truthy(crate::value::get(&settings, name));
            let mut permitted = !ledger.is_null() && on("enabled") && !on("observe_only");
            if permitted {
                permitted = match field(record, "thread_id")? {
                    Value::Str(thread) => {
                        thread_enabled(connection, thread.as_str().unwrap_or_default())?
                    }
                    _ => true, // no row is found for an id that is not text
                };
            }
            if permitted {
                permitted = !ledger_holds(
                    connection,
                    ledger,
                    self.links.as_ref(),
                    &phased(record, "launch"),
                    now,
                    &[Point::Records],
                )?;
            }
            Ok(body(permitted))
        })
    }
}
