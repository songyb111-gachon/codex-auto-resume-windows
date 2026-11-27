//! SEAM (seat S7.1a): the two functions the claim ledger reads from a module another seat ports - the Stop hook's
//! claims (`engine/hookclaims.py`'s `held` and `spent_on`, seat S7.3c) - written here as the tag has them, so the
//! ledger can be held to the reference now. Send now's freshness (`control/sendnow.py`'s `fresh`) is S7.3a's
//! `control::sendnow::fresh` (the third function this file held until then).

use car_machine::json::Value;
use rusqlite::Connection;

use crate::state::errors::Result;
use crate::state::py;
use crate::state::sql;
use crate::vocabulary::HookOutcome;

/// `hookclaims.CAPABILITY`.
pub const HOOK_CAPABILITY: &str = "stop_hook_continuation";
/// `hookclaims.HOLD_SECONDS`.
pub const HOLD_SECONDS: f64 = 900.0;
const DAY: f64 = 86400.0;

/// `hookclaims.held(connection, schema, interruption_id, now)`: whether the hook blocked the turn of
/// `interruption_id` within HOLD_SECONDS.
pub fn held(
    connection: &Connection,
    schema: &str,
    interruption_id: &Value,
    now: f64,
) -> Result<bool> {
    let row = sql::first(
        connection,
        &format!("SELECT at FROM {schema}.hook_claims WHERE interruption_id=? AND outcome=?"),
        &[
            interruption_id.clone(),
            py::word(HookOutcome::Blocked.as_str()),
        ],
    )?;
    Ok(match row {
        None => false,
        Some(values) => match py::as_f64(&values[0]) {
            Some(at) => (0.0..HOLD_SECONDS).contains(&(now - at)),
            None if matches!(values[0], Value::Null) => {
                return Err(crate::state::errors::Error::type_error(
                    "unsupported operand type(s) for -: 'float' and 'NoneType'",
                ));
            }
            None => {
                return Err(crate::state::errors::Error::type_error(
                    "unsupported operand type(s) for -",
                ));
            }
        },
    })
}

/// `hookclaims.spent_on(connection, schema, thread_id, now)`: (the hook's continuations in `thread_id` in the last
/// day, when the latest was or None).
pub fn spent_on(
    connection: &Connection,
    schema: &str,
    thread_id: &Value,
    now: f64,
) -> Result<(i64, Value)> {
    let row = sql::first(
        connection,
        &format!("SELECT count(*), max(at) FROM {schema}.spend WHERE capability=? AND thread_id=? AND at>?"),
        &[py::word(HOOK_CAPABILITY), thread_id.clone(), sql::float(now - DAY)],
    )?
    .unwrap_or_default();
    let count = row.first().and_then(py::small).unwrap_or(0);
    Ok((count, row.get(1).cloned().unwrap_or(Value::Null)))
}
