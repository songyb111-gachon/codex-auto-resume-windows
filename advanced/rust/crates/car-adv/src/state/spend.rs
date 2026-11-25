//! The spend ledger: one row for every unit a capability spent, and the counts its ceilings read (`state/spend.py`).
//!
//! A unit is spent before the send it pays for - inside core's one claim, on the claim's own connection with this
//! file attached (`ledger`) - so it commits with the claim or not at all. The same statements serve both
//! connections: this file's own, where its tables are `main`, and core's, where it is attached as `advanced`; the
//! schema name is one of those two constants and never anything else.

use car_machine::json::{Str, Value};
use rusqlite::Connection;

use super::errors::{Error, Result};
use super::journal::{prune_every, prune_spend};
use super::py;
use super::schema::ATTACHED;
use super::session::AdvancedState;
use super::sql::{self, Row, float, int, string};

pub const DAY: f64 = 86400.0;
pub const HOUR: f64 = 3600.0;
/// The points that make a capability a channel or a route for the send it pays for (`Point.SENDER`,
/// `Point.UNLOADED`).
pub const CHANNELS: &[&str] = &["sender", "unloaded"];
/// How far apart a unit's time and a claim's may be and still be the one claim.
pub const SAME_CLAIM: f64 = 0.001;
const CLAIM_GROUPS: (&str, &str) = (
    "SELECT count(*) FROM (SELECT 1 FROM ",
    ".spend WHERE at>?{left} GROUP BY interruption_id, at, CASE WHEN interruption_id IS NULL THEN spend_id END)",
);

/// `_schema(name)`: `main` or `advanced`, else `StateError("unknown schema")`.
pub fn schema_name(name: &str) -> Result<&str> {
    if name == "main" || name == ATTACHED {
        Ok(name)
    } else {
        Err(Error::state("unknown schema"))
    }
}

/// `claims_since(connection, schema, since, paid=())`: how many sends the units written after `since` paid for -
/// one for each claim - leaving out the claim's own units `paid`.
pub fn claims_since(
    connection: &Connection,
    schema: &str,
    since: f64,
    paid: &[i64],
) -> Result<i64> {
    let schema = schema_name(schema)?;
    let left = if paid.is_empty() {
        String::new()
    } else {
        format!(" AND spend_id NOT IN ({})", sql::marks(paid.len()))
    };
    let text = format!(
        "{}{schema}{}",
        CLAIM_GROUPS.0,
        CLAIM_GROUPS.1.replace("{left}", &left)
    );
    let mut parameters = vec![float(since)];
    parameters.extend(paid.iter().map(|one| int(*one)));
    sql::number(connection, &text, &parameters)
}

/// `counts(connection, schema, capability, thread_id, now, paid=())`: the capability's units in the last day,
/// overall and in this conversation, and the sends every capability together paid for in the last hour.
pub fn counts(
    connection: &Connection,
    schema: &str,
    capability: &Value,
    thread_id: &Value,
    now: f64,
    paid: &[i64],
) -> Result<Row> {
    let schema = schema_name(schema)?;
    let (day, hour) = (now - DAY, now - HOUR);
    let row = sql::first(
        connection,
        &format!(
            "SELECT coalesce(sum(capability=? AND at>?), 0) AS capability_day, \
             coalesce(sum(capability=? AND thread_id=? AND at>?), 0) AS conversation_day \
             FROM {schema}.spend WHERE at>?"
        ),
        &[
            capability.clone(),
            float(day),
            capability.clone(),
            thread_id.clone(),
            float(day),
            float(day.min(hour)),
        ],
    )?
    .unwrap_or_default();
    let mut found = Row::new();
    found.insert(
        sql::key("capability_day"),
        py::int_of(row.first().unwrap_or(&Value::Null))?,
    );
    found.insert(
        sql::key("conversation_day"),
        py::int_of(row.get(1).unwrap_or(&Value::Null))?,
    );
    found.insert(
        sql::key("global_hour"),
        int(claims_since(connection, schema, hour, paid)?),
    );
    Ok(found)
}

/// `claim_time(connection, schema, interruption_id, now)`: `now`, or the next float above it that none of the
/// record's units has.
pub fn claim_time(
    connection: &Connection,
    schema: &str,
    interruption_id: &Value,
    now: &Value,
) -> Result<f64> {
    let schema = schema_name(schema)?;
    let mut at = py::timestamp(now, "time")?;
    if matches!(interruption_id, Value::Null) {
        return Ok(at);
    }
    while sql::exists(
        connection,
        &format!("SELECT 1 FROM {schema}.spend WHERE interruption_id=? AND at=?"),
        &[interruption_id.clone(), float(at)],
    )? {
        at = next_up(at);
    }
    Ok(at)
}

/// `math.nextafter(at, math.inf)`.
pub fn next_up(at: f64) -> f64 {
    if at.is_nan() || at == f64::INFINITY {
        return at;
    }
    if at == 0.0 {
        return f64::from_bits(1);
    }
    let bits = at.to_bits();
    f64::from_bits(if at > 0.0 { bits + 1 } else { bits - 1 })
}

impl AdvancedState {
    /// `spent(capability, thread_id, now=None)`: `counts` on this file's own connection; no file, no spend.
    pub fn spent(&self, capability: &Value, thread_id: &Value, now: &Value) -> Result<Row> {
        let now = self.now(now)?;
        self.read(|connection| match connection {
            None => {
                let mut found = Row::new();
                for name in ["capability_day", "conversation_day", "global_hour"] {
                    found.insert(sql::key(name), int(0));
                }
                Ok(found)
            }
            Some(connection) => counts(connection, "main", capability, thread_id, now, &[]),
        })
    }

    /// `record_spend(connection, schema, capability, thread_id, interruption_id, now)`: one unit inside the caller's
    /// transaction; its spend id.
    pub fn record_spend(
        &self,
        connection: &Connection,
        schema: &str,
        capability: &Value,
        thread_id: &Value,
        interruption_id: &Value,
        now: &Value,
    ) -> Result<i64> {
        let schema = schema_name(schema)?;
        if self.registry.get(capability).is_none() {
            return Err(Error::state("unknown capability"));
        }
        py::thread(thread_id)?;
        if !matches!(interruption_id, Value::Null) {
            py::key(interruption_id, "interruption id")?;
        }
        let now = py::timestamp(now, "time")?;
        let spend_id = sql::insert(
            connection,
            &format!(
                "INSERT INTO {schema}.spend (at, capability, thread_id, interruption_id) VALUES (?,?,?,?)"
            ),
            &[
                float(now),
                capability.clone(),
                thread_id.clone(),
                interruption_id.clone(),
            ],
        )?;
        let spend_id =
            sql::number(connection, "SELECT last_insert_rowid()", &[]).unwrap_or(spend_id);
        if prune_every(spend_id) {
            prune_spend(connection, schema, now)?;
        }
        Ok(spend_id)
    }

    /// `spends_since(capability, since)`: {interruption id: the times of its units} from the newest 500.
    pub fn spends_since(&self, capability: &Value, since: &Value) -> Result<Row> {
        let rows = self.read(|connection| match connection {
            None => Ok(Vec::new()),
            Some(connection) => sql::tuples(
                connection,
                "SELECT interruption_id, at FROM spend WHERE capability=? AND at>=? AND interruption_id IS NOT NULL \
                 ORDER BY spend_id DESC LIMIT 500",
                &[capability.clone(), since.clone()],
            ),
        })?;
        Ok(grouped(rows))
    }

    /// `payers(interruption_id, claimed_at)`: {capability: the times of its units} for each capability of the
    /// registry that paid for that claim's send (every unit on the record where the claim's time is None).
    pub fn payers(&self, interruption_id: &Value, claimed_at: &Value) -> Result<Row> {
        py::key(interruption_id, "interruption id")?;
        let rows = self.read(|connection| match connection {
            None => Ok(Vec::new()),
            Some(connection) => sql::tuples(
                connection,
                "SELECT capability, at FROM spend WHERE interruption_id=? ORDER BY spend_id DESC LIMIT 500",
                &[interruption_id.clone()],
            ),
        })?;
        let mut kept = Vec::new();
        for row in rows {
            if self.registry.get(&row[0]).is_none() {
                continue;
            }
            let near = match claimed_at {
                Value::Null => true,
                _ => {
                    let at = py::as_f64(&row[1])
                        .ok_or_else(|| Error::type_error("unsupported operand type(s) for -"))?;
                    let claimed = py::as_f64(claimed_at)
                        .ok_or_else(|| Error::type_error("unsupported operand type(s) for -"))?;
                    (at - claimed).abs() <= SAME_CLAIM
                }
            };
            if near {
                kept.push(row);
            }
        }
        Ok(grouped(kept))
    }

    /// `channel_paid(interruption_id, claimed_at)`: whether a capability that is a channel or a route paid for it.
    pub fn channel_paid(&self, interruption_id: &Value, claimed_at: &Value) -> Result<bool> {
        let payers = self.payers(interruption_id, claimed_at)?;
        Ok(payers.keys().any(|capability| {
            self.registry
                .get(&Value::Str(capability.clone()))
                .is_some_and(|definition| CHANNELS.iter().any(|point| definition.has_point(point)))
        }))
    }
}

/// `{key: tuple(times)}` of (key, time) rows, in first-seen order.
fn grouped(rows: Vec<Vec<Value>>) -> Row {
    let mut found = Row::new();
    for row in rows {
        let name = Str::new(&py::py_str(&row[0]));
        let at = row.get(1).cloned().unwrap_or(Value::Null);
        match found.get_mut(&name) {
            Some(Value::Array(times)) => times.push(at),
            _ => {
                found.insert(name, Value::Array(vec![at]));
            }
        }
    }
    found
}

/// `string` of a capability word.
pub fn word(text: &str) -> Value {
    string(text)
}
