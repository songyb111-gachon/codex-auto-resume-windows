//! The tokens each conversation used a day, the rollouts read, and the meter's samples (`state/analytics.py`).

use car_machine::domain::ids;
use car_machine::json::{Str, Value};

use super::errors::{Error, Result};
use super::py;
use super::schema::BUCKETS;
use super::session::AdvancedState;
use super::sql::{self, Row, float, int};

pub const CAPABILITY: &str = "usage_analytics";
pub const METER: &str = "usage_meter";
pub const MAX_MINUTES: i64 = 100800;
/// A count larger than this is refused.
pub const MOST: i64 = 10_000_000_000_000;
const DAY_COLUMNS: &str = "day, thread_id, project_digest, input, cached, output, reasoning, turns";
const FILE_COLUMNS: &str = "file_digest, thread_id, size, offset, mtime_ns, read_at";
const SAMPLE_COLUMNS: &str = "bucket, minutes, at, used_percent, reset_at";

/// `DAY.match(value)`: `\A[0-9]{4}-[01][0-9]-[0-3][0-9]\Z`.
fn day_shaped(value: &Value) -> bool {
    py::text(value).is_some_and(|text| {
        let bytes = text.as_bytes();
        bytes.len() == 10
            && bytes[..4].iter().all(u8::is_ascii_digit)
            && bytes[4] == b'-'
            && (b'0'..=b'1').contains(&bytes[5])
            && bytes[6].is_ascii_digit()
            && bytes[7] == b'-'
            && (b'0'..=b'3').contains(&bytes[8])
            && bytes[9].is_ascii_digit()
    })
}

/// `HEX16.match(value)`.
fn hex16(value: &Value) -> bool {
    py::text(value).is_some_and(|text| {
        text.len() == 16
            && text
                .bytes()
                .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    })
}

/// `_count(value, what)`: an `int` from 0 to MOST.
fn count(value: &Value, what: &str) -> Result<Value> {
    if !py::small(value).is_some_and(|number| (0..=MOST).contains(&number)) {
        return Err(Error::state(format!("invalid {what}")));
    }
    Ok(value.clone())
}

/// `_hex16(value, what, null)`.
fn hex(value: &Value, what: &str, null: bool) -> Result<Value> {
    if null && matches!(value, Value::Null) {
        return Ok(Value::Null);
    }
    if !hex16(value) {
        return Err(Error::state(format!("invalid {what}")));
    }
    Ok(value.clone())
}

/// `_uuid(value)`: a canonical UUID in lowercase.
fn uuid(value: &Value) -> Result<()> {
    let lower = py::text(value).is_some_and(|text| text == text.to_lowercase());
    if !ids::is_uuid(value) || !lower {
        return Err(Error::state("invalid thread id"));
    }
    Ok(())
}

impl AdvancedState {
    /// `token_files()`: {file_key: row} of every rollout read so far.
    pub fn token_files(&self) -> Result<Row> {
        let rows = self.read(|connection| match connection {
            None => Ok(Vec::new()),
            Some(connection) => sql::all(
                connection,
                &format!("SELECT {FILE_COLUMNS} FROM token_files"),
                &[],
            ),
        })?;
        let mut found = Row::new();
        for row in rows {
            found.insert(
                Str::new(&py::py_str(sql::get(&row, "file_digest"))),
                Value::Object(row),
            );
        }
        Ok(found)
    }

    /// `ingest_file(file_key, thread_id, size=..., offset=..., changed_ns=..., days=..., project_key=..., at=None)`:
    /// one rollout's pass written; how many day rows it touched.
    #[allow(clippy::too_many_arguments)]
    pub fn ingest_file(
        &self,
        file_key: &Value,
        thread_id: &Value,
        size: &Value,
        offset: &Value,
        changed_ns: &Value,
        days: &Value,
        project_key: &Value,
        at: &Value,
    ) -> Result<i64> {
        hex(file_key, "file key", false)?;
        uuid(thread_id)?;
        hex(project_key, "project key", true)?;
        count(size, "size")?;
        count(offset, "offset")?;
        if !matches!(changed_ns, Value::Int(number) if !number.to_string().starts_with('-')) {
            return Err(Error::state("invalid mtime"));
        }
        let now = self.now(at)?;
        let mut rows: Vec<Vec<Value>> = Vec::new();
        let entries: Vec<(Value, Value)> = match days {
            Value::Object(map) => map
                .iter()
                .map(|(day, numbers)| (Value::Str(day.clone()), numbers.clone()))
                .collect(),
            other if !sql::truthy(other) => Vec::new(),
            _ => {
                return Err(Error::python(
                    "AttributeError",
                    "object has no attribute 'items'",
                ));
            }
        };
        for (day, numbers) in entries {
            if !day_shaped(&day) {
                return Err(Error::state("invalid day"));
            }
            let Value::Array(numbers) = numbers else {
                return Err(Error::state("invalid numbers"));
            };
            if numbers.len() != 5 {
                return Err(Error::state("invalid numbers"));
            }
            let mut row = vec![day];
            for number in &numbers {
                row.push(count(number, "count")?);
            }
            rows.push(row);
        }
        self.writing(|connection| {
            sql::exec(
                connection,
                "INSERT INTO token_files (file_digest, thread_id, size, offset, mtime_ns, read_at) VALUES (?,?,?,?,?,?) \
                 ON CONFLICT(file_digest) DO UPDATE SET thread_id=excluded.thread_id, size=excluded.size, \
                 offset=excluded.offset, mtime_ns=excluded.mtime_ns, read_at=excluded.read_at",
                &[
                    file_key.clone(),
                    thread_id.clone(),
                    size.clone(),
                    offset.clone(),
                    changed_ns.clone(),
                    float(now),
                ],
            )?;
            for row in &rows {
                let mut parameters = vec![row[0].clone(), thread_id.clone(), project_key.clone()];
                parameters.extend(row[1..].iter().cloned());
                parameters.extend((0..5).map(|_| int(MOST)));
                sql::exec(
                    connection,
                    "INSERT INTO token_days (day, thread_id, project_digest, input, cached, output, reasoning, turns) \
                     VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(day, thread_id) DO UPDATE SET \
                     project_digest=coalesce(excluded.project_digest, project_digest), input=min(input+excluded.input, ?), \
                     cached=min(cached+excluded.cached, ?), output=min(output+excluded.output, ?), \
                     reasoning=min(reasoning+excluded.reasoning, ?), turns=min(turns+excluded.turns, ?)",
                    &parameters,
                )?;
            }
            Ok(())
        })?;
        Ok(rows.len() as i64)
    }

    /// `token_days(since_day=None)`: every row from `since_day` on, the oldest day first.
    pub fn token_days(&self, since_day: &Value) -> Result<Vec<Row>> {
        if !matches!(since_day, Value::Null) && !day_shaped(since_day) {
            return Err(Error::state("invalid day"));
        }
        let since = if sql::truthy(since_day) {
            since_day.clone()
        } else {
            sql::string("0000-00-00")
        };
        self.read(|connection| match connection {
            None => Ok(Vec::new()),
            Some(connection) => sql::all(
                connection,
                &format!(
                    "SELECT {DAY_COLUMNS} FROM token_days WHERE day >= ? ORDER BY day, thread_id"
                ),
                &[since],
            ),
        })
    }

    /// `add_samples(windows, at=None)`: one meter reading's windows appended as samples; how many it kept.
    pub fn add_samples(&self, windows: &Value, at: &Value) -> Result<i64> {
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
            let (used, bucket, minutes, reset) = (
                field("used_percent"),
                field("bucket"),
                field("window_minutes"),
                field("reset_at"),
            );
            let Some(used) = super::meter::share(&used)? else {
                continue;
            };
            let fits = py::is_word(&bucket, BUCKETS)
                && py::small(&minutes).is_some_and(|minutes| (1..=MAX_MINUTES).contains(&minutes))
                && match &reset {
                    Value::Null => true,
                    Value::Int(number) => !number.to_string().starts_with('-'),
                    _ => false,
                };
            if !fits {
                continue;
            }
            match kept
                .iter_mut()
                .find(|(each, _)| sql::py_eq(&each.0, &bucket) && sql::py_eq(&each.1, &minutes))
            {
                Some(entry) => {
                    if used > entry.1.0 {
                        entry.1 = (used, reset);
                    }
                }
                None => kept.push(((bucket, minutes), (used, reset))),
            }
        }
        if kept.is_empty() {
            return Ok(0);
        }
        self.writing(|connection| {
            for ((bucket, minutes), (used, reset)) in &kept {
                sql::exec(
                    connection,
                    "INSERT OR REPLACE INTO usage_samples (bucket, minutes, at, used_percent, reset_at) VALUES (?,?,?,?,?)",
                    &[bucket.clone(), minutes.clone(), float(now), float(*used), reset.clone()],
                )?;
            }
            Ok(())
        })?;
        Ok(kept.len() as i64)
    }

    /// `usage_samples(since=None)`: every sample taken at or after `since`, the oldest first.
    pub fn usage_samples(&self, since: &Value) -> Result<Vec<Row>> {
        self.read(|connection| match connection {
            None => Ok(Vec::new()),
            Some(connection) => {
                let since = if sql::truthy(since) {
                    py::float_of(since)?
                } else {
                    0.0
                };
                sql::all(
                    connection,
                    &format!(
                        "SELECT {SAMPLE_COLUMNS} FROM usage_samples WHERE at >= ? ORDER BY at"
                    ),
                    &[float(since)],
                )
            }
        })
    }
}
