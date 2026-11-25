//! SEAM (seat S7.1a): the three functions the claim ledger reads from modules other seats port - the Stop hook's
//! claims (`engine/hookclaims.py`'s `held` and `spent_on`, seat S7.2) and a Send now's freshness
//! (`control/sendnow.py`'s `fresh`, seat S7.3) - written here as the tag has them, so the ledger can be held to the
//! reference now. The seats that port those modules replace these with theirs; nothing else of either module is here.

use car_machine::json::Value;
use rusqlite::Connection;

use crate::state::errors::Result;
use crate::state::py;
use crate::state::seam::words_gen::{hook_outcome, override_kind};
use crate::state::sql;

/// `hookclaims.CAPABILITY`.
pub const HOOK_CAPABILITY: &str = "stop_hook_continuation";
/// `hookclaims.HOLD_SECONDS`.
pub const HOLD_SECONDS: f64 = 900.0;
/// `sendnow.LIFETIME`.
pub const LIFETIME: f64 = 900.0;
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
        &[interruption_id.clone(), py::word(hook_outcome::BLOCKED)],
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

/// `sendnow.fresh(override, since, now)`: whether a FORCE_ONCE override is one a send may still use at `now` -
/// unused, younger than LIFETIME and made at or after `since`.
pub fn fresh(kind: &Value, created_at: &Value, used_at: &Value, since: &Value, now: f64) -> bool {
    if !matches!(used_at, Value::Null) {
        return false;
    }
    if !py::is_word(kind, &[override_kind::FORCE_ONCE]) {
        return false;
    }
    if !(py::is_number(created_at) && py::is_number(since)) {
        return false;
    }
    let (Some(made), Some(since)) = (py::as_f64(created_at), py::as_f64(since)) else {
        return false;
    };
    made >= since && (0.0..LIFETIME).contains(&(now - made))
}
