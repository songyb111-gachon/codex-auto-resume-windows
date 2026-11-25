//! The usage meter's last reading of each window, and what each stage acted for (`state/meter.py`).

use car_machine::json::Value;
use rusqlite::Connection;

use super::errors::{Error, Result};
use super::py;
use super::schema::BUCKETS;
use super::session::AdvancedState;
use super::sql::{self, Row, float, int};

/// The meter's capability, whose move off deletes the rows.
pub const METER: &str = "usage_meter";
pub const MAX_MINUTES: i64 = 100800;
const COLUMNS: &str =
    "bucket, minutes, used_percent, reset_at, read_at, warned_reset_at, warned_at, paused_reset_at";

/// `_family(bucket, minutes)`.
fn family(bucket: &Value, minutes: &Value) -> Result<(Value, Value)> {
    let fits = py::small(minutes).is_some_and(|minutes| (1..=MAX_MINUTES).contains(&minutes));
    if !py::is_word(bucket, BUCKETS) || !fits {
        return Err(Error::state("invalid window"));
    }
    Ok((bucket.clone(), minutes.clone()))
}

/// `_reset(value)`: None, or a whole number from 0.
fn reset(value: &Value) -> Result<Value> {
    match value {
        Value::Null => Ok(Value::Null),
        Value::Int(number) if !number.to_string().starts_with('-') => Ok(value.clone()),
        _ => Err(Error::state("invalid reset time")),
    }
}

/// `type(used) in (int, float) and math.isfinite(used) and used >= 0`: the share as Codex gives it, as a float; an
/// `int` too large for `math.isfinite` is its OverflowError.
pub(crate) fn share(used: &Value) -> Result<Option<f64>> {
    match used {
        Value::Int(_) | Value::Float(_) => {
            let finite = car_machine::pyval::is_finite(used)
                .map_err(|class| Error::python(class, "int too large to convert to float"))?;
            let value = py::as_f64(used).unwrap_or(f64::NAN);
            Ok((finite && value >= 0.0).then_some(value))
        }
        _ => Ok(None),
    }
}

impl AdvancedState {
    /// `meter()`: {(bucket, minutes): row} of the meter's last reading.
    pub fn meter(&self) -> Result<Vec<((Value, Value), Row)>> {
        let rows = self.read(|connection| match connection {
            None => Ok(Vec::new()),
            Some(connection) => sql::all(connection, &format!("SELECT {COLUMNS} FROM meter"), &[]),
        })?;
        Ok(super::resets::keyed(rows))
    }

    /// `save_meter(windows, at=None)`: one successful reading written; how many rows it holds after.
    pub fn save_meter(&self, windows: &Value, at: &Value) -> Result<i64> {
        let now = self.now(at)?;
        let mut kept: Vec<((Value, Value), (f64, Value))> = Vec::new();
        let listed = if sql::truthy(windows) {
            super::arming::iterate(windows)?
        } else {
            Vec::new()
        };
        for window in listed {
            let Value::Object(map) = &window else {
                continue;
            };
            let field = |name: &str| map.get(name).cloned().unwrap_or(Value::Null);
            let Some(used) = share(&field("used_percent"))? else {
                continue;
            };
            let Ok(family) = family(&field("bucket"), &field("window_minutes")) else {
                continue;
            };
            let Ok(reset_at) = reset(&field("reset_at")) else {
                continue;
            };
            match kept
                .iter_mut()
                .find(|(each, _)| sql::py_eq(&each.0, &family.0) && sql::py_eq(&each.1, &family.1))
            {
                Some(entry) => {
                    if used > entry.1.0 {
                        entry.1 = (used, reset_at);
                    }
                }
                None => kept.push((family, (used, reset_at))),
            }
        }
        self.writing(|connection| {
            for ((bucket, minutes), (used, reset_at)) in &kept {
                sql::exec(
                    connection,
                    "INSERT INTO meter (bucket, minutes, used_percent, reset_at, read_at) VALUES (?,?,?,?,?) \
                     ON CONFLICT(bucket, minutes) DO UPDATE SET used_percent=excluded.used_percent, \
                     reset_at=excluded.reset_at, read_at=excluded.read_at",
                    &[bucket.clone(), minutes.clone(), float(*used), reset_at.clone(), float(now)],
                )?;
            }
            for stored in sql::tuples(connection, "SELECT bucket, minutes FROM meter", &[])? {
                if !kept
                    .iter()
                    .any(|((bucket, minutes), _)| sql::py_eq(bucket, &stored[0]) && sql::py_eq(minutes, &stored[1]))
                {
                    sql::exec(
                        connection,
                        "DELETE FROM meter WHERE bucket=? AND minutes=?",
                        &[stored[0].clone(), stored[1].clone()],
                    )?;
                }
            }
            sql::number(connection, "SELECT count(*) FROM meter", &[])
        })
    }

    /// `mark_meter(bucket, minutes, warned_reset_at=None, paused_reset_at=None, clear_pause=False, at=None)`.
    pub fn mark_meter(
        &self,
        bucket: &Value,
        minutes: &Value,
        warned_reset_at: &Value,
        paused_reset_at: &Value,
        clear_pause: &Value,
        at: &Value,
    ) -> Result<bool> {
        let (bucket, minutes) = family(bucket, minutes)?;
        let now = self.now(at)?;
        let mut sets: Vec<&str> = Vec::new();
        let mut values: Vec<Value> = Vec::new();
        if !matches!(warned_reset_at, Value::Null) {
            sets.extend(["warned_reset_at=?", "warned_at=?"]);
            values.push(reset(warned_reset_at)?);
            values.push(float(now));
        }
        if !matches!(paused_reset_at, Value::Null) {
            sets.push("paused_reset_at=?");
            values.push(reset(paused_reset_at)?);
        } else if sql::truthy(clear_pause) {
            sets.push("paused_reset_at=NULL");
        }
        if sets.is_empty() {
            return Err(Error::state("nothing to mark"));
        }
        values.push(bucket);
        values.push(minutes);
        self.transaction(false, |connection| match connection {
            None => Ok(false),
            Some(connection) => Ok(sql::exec(
                connection,
                &format!(
                    "UPDATE meter SET {} WHERE bucket=? AND minutes=?",
                    sets.join(", ")
                ),
                &values,
            )? == 1),
        })
    }
}

/// `end_meter(connection)`: every row of the meter deleted, in the caller's transaction.
pub fn end_meter(connection: &Connection) -> Result<()> {
    sql::exec(connection, "DELETE FROM meter", &[])?;
    Ok(())
}

/// A zero, for callers that count rows.
pub fn none() -> Value {
    int(0)
}
