//! The edition's own records, and what a capability asks of one of core's (`state/records.py`).
//!
//! A record of this edition's lives here, never as a row of core's; the one claim counts it with core's rows
//! (`ledger`), so one in flight per conversation, five claims a day and fifteen minutes between them hold across
//! both tables. An override is a capability's request about one standard record, keyed by its interruption id.

use car_machine::domain::states;
use car_machine::json::Value;
use rusqlite::Connection;

use super::errors::{Error, Result};
use super::py;
use super::schema::ATTACHED;
use super::seam::registry::Registry;
use super::seam::registry_gen::{CORE_COOLDOWN_SECONDS, CORE_DAILY_CAP};
use super::seam::words_gen::{override_kind, record_state};
use super::session::AdvancedState;
use super::sql::{self, Row, float, string};

pub const DAY: f64 = 86400.0;

/// `_MOVES`: where `move_record` may take a record from where it is.
fn allowed(from: &Value, to: &str) -> bool {
    match py::text(from) {
        Some(record_state::WAITING) => to == record_state::CANCELLED,
        Some(record_state::IN_FLIGHT) => [
            record_state::WAITING,
            record_state::FINISHED,
            record_state::CANCELLED,
        ]
        .contains(&to),
        _ => false,
    }
}

/// `own_paced(registry)`: the capabilities whose records keep a pace of their own (those that depart from A20),
/// sorted.
pub fn own_paced(registry: &dyn Registry) -> Vec<&'static str> {
    let mut found: Vec<&'static str> = registry
        .definitions()
        .iter()
        .filter(|definition| definition.departs("A20"))
        .map(|definition| definition.id)
        .collect();
    found.sort_unstable();
    found
}

/// `not_among(capabilities)`: the SQL test that a records row is of none of them.
pub fn not_among(capabilities: &[&str]) -> String {
    if capabilities.is_empty() {
        "1".into()
    } else {
        format!("capability NOT IN ({})", sql::marks(capabilities.len()))
    }
}

fn number_or_none(value: &Value) -> Option<f64> {
    py::as_f64(value)
}

impl AdvancedState {
    fn known(&self, capability: &Value) -> Result<()> {
        if self.registry.get(capability).is_none() {
            return Err(Error::state("unknown capability"));
        }
        Ok(())
    }

    /// `add_record(record_id, capability, thread_id, at=None)`: a new record, waiting; false if the id is taken.
    pub fn add_record(
        &self,
        record_id: &Value,
        capability: &Value,
        thread_id: &Value,
        at: &Value,
    ) -> Result<bool> {
        py::key(record_id, "record id")?;
        self.known(capability)?;
        py::thread(thread_id)?;
        let now = self.now(at)?;
        self.writing(|connection| {
            if sql::exists(connection, "SELECT 1 FROM records WHERE record_id=?", &[record_id.clone()])? {
                return Ok(false);
            }
            sql::exec(
                connection,
                "INSERT INTO records (record_id, capability, thread_id, state, created_at, claims) VALUES (?,?,?,?,?,0)",
                &[
                    record_id.clone(),
                    capability.clone(),
                    thread_id.clone(),
                    string(record_state::WAITING),
                    float(now),
                ],
            )?;
            Ok(true)
        })
    }

    /// `move_record(record_id, state, at=None)`: back to waiting, finished or cancelled, along `_MOVES`.
    pub fn move_record(&self, record_id: &Value, state: &Value, at: &Value) -> Result<bool> {
        py::key(record_id, "record id")?;
        let state = py::closed(state, record_state::ALL, "record state")?;
        let now = self.now(at)?;
        self.transaction(false, |connection| {
            let Some(connection) = connection else {
                return Ok(false);
            };
            let row = sql::one(
                connection,
                "SELECT state FROM records WHERE record_id=?",
                &[record_id.clone()],
            )?;
            let Some(row) = row else { return Ok(false) };
            if !allowed(sql::get(&row, "state"), state) {
                return Ok(false);
            }
            let finished = if state == record_state::FINISHED || state == record_state::CANCELLED {
                float(now)
            } else {
                Value::Null
            };
            sql::exec(
                connection,
                "UPDATE records SET state=?, finished_at=? WHERE record_id=?",
                &[string(state), finished, record_id.clone()],
            )?;
            Ok(true)
        })
    }

    /// `claim_record(connection, record_id, now, own_pace=False)`: a waiting record of this edition's put in flight
    /// on core's connection, inside its claim, with this file attached - where both stores allow one more on the
    /// conversation.
    pub fn claim_record(
        &self,
        connection: &Connection,
        record_id: &Value,
        now: &Value,
        own_pace: bool,
    ) -> Result<bool> {
        py::key(record_id, "record id")?;
        let now = py::timestamp(now, "time")?;
        if connection.is_autocommit() {
            return Err(Error::state("a record is claimed only inside core's claim"));
        }
        if !self.attach(connection)? {
            return Ok(false);
        }
        let row = sql::first(
            connection,
            &format!("SELECT state, thread_id FROM {ATTACHED}.records WHERE record_id=?"),
            &[record_id.clone()],
        )?;
        let Some(row) = row else { return Ok(false) };
        if !sql::py_eq(&row[0], &string(record_state::WAITING)) {
            return Ok(false);
        }
        let thread_id = row[1].clone();
        for core in sql::tuples(
            connection,
            "SELECT state, queue_id FROM main.interruptions WHERE thread_id=?",
            &[thread_id.clone()],
        )? {
            if states::may_be_queued(&core[0], &core[1])
                .map_err(|class| Error::python(class, "unhashable"))?
            {
                return Ok(false);
            }
        }
        let own = own_paced(self.registry.as_ref());
        let mut parameters = vec![string(record_state::IN_FLIGHT), float(now - DAY)];
        parameters.extend(own.iter().map(|id| string(id)));
        parameters.extend(own.iter().map(|id| string(id)));
        parameters.push(thread_id.clone());
        let ours = sql::first(
            connection,
            &format!(
                "SELECT coalesce(sum(state=?), 0), \
                 coalesce(sum(CASE WHEN claimed_at > ? AND {among} THEN max(claims, 1) ELSE 0 END), 0), \
                 max(CASE WHEN {among} THEN claimed_at END) FROM {ATTACHED}.records WHERE thread_id=?",
                among = not_among(&own)
            ),
            &parameters,
        )?
        .unwrap_or_default();
        let cores = sql::first(
            connection,
            "SELECT coalesce(sum(CASE WHEN coalesce(submitted_at, last_claim_at) > ? THEN max(attempt_count, 1) \
             ELSE 0 END), 0), max(coalesce(submitted_at, last_claim_at)) FROM main.interruptions WHERE thread_id=?",
            &[float(now - DAY), thread_id],
        )?
        .unwrap_or_default();
        let last = [ours.get(2), cores.get(1)]
            .into_iter()
            .flatten()
            .filter_map(number_or_none)
            .fold(None, |most: Option<f64>, at| {
                Some(most.map_or(at, |most| most.max(at)))
            });
        let in_flight = sql::truthy(ours.first().unwrap_or(&Value::Null));
        let recent = py::as_f64(ours.get(1).unwrap_or(&Value::Null)).unwrap_or(0.0)
            + py::as_f64(cores.first().unwrap_or(&Value::Null)).unwrap_or(0.0);
        if in_flight
            || (!own_pace
                && (recent >= CORE_DAILY_CAP as f64
                    || last.is_some_and(|last| now - last < CORE_COOLDOWN_SECONDS as f64)))
        {
            return Ok(false);
        }
        sql::exec(
            connection,
            &format!(
                "UPDATE {ATTACHED}.records SET state=?, claimed_at=?, claims=claims+1 WHERE record_id=?"
            ),
            &[
                string(record_state::IN_FLIGHT),
                float(now),
                record_id.clone(),
            ],
        )?;
        Ok(true)
    }

    /// `records_on(thread_id)`: the conversation's records of capabilities this registry holds, oldest first.
    pub fn records_on(&self, thread_id: &Value) -> Result<Vec<Row>> {
        py::thread(thread_id)?;
        let rows = self.read(|connection| match connection {
            None => Ok(Vec::new()),
            Some(connection) => sql::all(
                connection,
                "SELECT * FROM records WHERE thread_id=? ORDER BY created_at",
                &[thread_id.clone()],
            ),
        })?;
        Ok(rows
            .into_iter()
            .filter(|row| self.registry.get(sql::get(row, "capability")).is_some())
            .collect())
    }

    // ---------------------------------------------------------------- overrides
    /// `add_override(interruption_id, capability, kind, at=None)`: false if it already has one.
    pub fn add_override(
        &self,
        interruption_id: &Value,
        capability: &Value,
        kind: &Value,
        at: &Value,
    ) -> Result<bool> {
        py::key(interruption_id, "interruption id")?;
        self.known(capability)?;
        let kind = py::closed(kind, override_kind::ALL, "override kind")?;
        let now = self.now(at)?;
        self.writing(|connection| {
            if sql::exists(
                connection,
                "SELECT 1 FROM overrides WHERE interruption_id=? AND capability=?",
                &[interruption_id.clone(), capability.clone()],
            )? {
                return Ok(false);
            }
            sql::exec(
                connection,
                "INSERT INTO overrides (interruption_id, capability, kind, created_at) VALUES (?,?,?,?)",
                &[interruption_id.clone(), capability.clone(), string(kind), float(now)],
            )?;
            Ok(true)
        })
    }

    /// `overrides_for(interruption_id)`: every unused override on one standard record, of known capabilities.
    pub fn overrides_for(&self, interruption_id: &Value) -> Result<Vec<Row>> {
        py::key(interruption_id, "interruption id")?;
        let rows = self.read(|connection| match connection {
            None => Ok(Vec::new()),
            Some(connection) => sql::all(
                connection,
                "SELECT * FROM overrides WHERE interruption_id=? AND used_at IS NULL ORDER BY created_at",
                &[interruption_id.clone()],
            ),
        })?;
        Ok(rows
            .into_iter()
            .filter(|row| {
                self.registry.get(sql::get(row, "capability")).is_some()
                    && py::is_word(sql::get(row, "kind"), override_kind::ALL)
            })
            .collect())
    }

    /// `use_override(interruption_id, capability, at=None)`: mark it used, once.
    pub fn use_override(
        &self,
        interruption_id: &Value,
        capability: &Value,
        at: &Value,
    ) -> Result<bool> {
        py::key(interruption_id, "interruption id")?;
        let now = self.now(at)?;
        self.transaction(false, |connection| match connection {
            None => Ok(false),
            Some(connection) => Ok(sql::exec(
                connection,
                "UPDATE overrides SET used_at=? WHERE interruption_id=? AND capability=? AND used_at IS NULL",
                &[float(now), interruption_id.clone(), capability.clone()],
            )? == 1),
        })
    }

    /// `renew_override(interruption_id, capability, kind, at=None)`: a new request, or the one it had, unused again.
    pub fn renew_override(
        &self,
        interruption_id: &Value,
        capability: &Value,
        kind: &Value,
        at: &Value,
    ) -> Result<()> {
        py::key(interruption_id, "interruption id")?;
        self.known(capability)?;
        let kind = py::closed(kind, override_kind::ALL, "override kind")?;
        let now = self.now(at)?;
        self.writing(|connection| {
            sql::exec(
                connection,
                "INSERT OR REPLACE INTO overrides (interruption_id, capability, kind, created_at, used_at) \
                 VALUES (?,?,?,?,NULL)",
                &[interruption_id.clone(), capability.clone(), string(kind), float(now)],
            )?;
            Ok(())
        })
    }

    /// `override(interruption_id, capability)`: its override of one standard record, used or not, or None.
    pub fn override_of(&self, interruption_id: &Value, capability: &Value) -> Result<Option<Row>> {
        py::key(interruption_id, "interruption id")?;
        let row = self.read(|connection| match connection {
            None => Ok(None),
            Some(connection) => sql::one(
                connection,
                "SELECT * FROM overrides WHERE interruption_id=? AND capability=?",
                &[interruption_id.clone(), capability.clone()],
            ),
        })?;
        Ok(row.filter(|row| py::is_word(sql::get(row, "kind"), override_kind::ALL)))
    }

    /// `resent(interruption_id)`: whether this edition sent it once more, by any capability.
    pub fn resent(&self, interruption_id: &Value) -> Result<bool> {
        py::key(interruption_id, "interruption id")?;
        self.read(|connection| match connection {
            None => Ok(false),
            Some(connection) => sql::exists(
                connection,
                "SELECT 1 FROM overrides WHERE interruption_id=? AND kind=?",
                &[interruption_id.clone(), string(override_kind::RESEND_ONCE)],
            ),
        })
    }

    /// `open_overrides(kind, capability=None)`: every unused override of `kind`, oldest first.
    pub fn open_overrides(&self, kind: &Value, capability: &Value) -> Result<Vec<Row>> {
        let kind = py::closed(kind, override_kind::ALL, "override kind")?;
        let (clause, mut arguments) = if matches!(capability, Value::Null) {
            ("", vec![string(kind)])
        } else {
            ("AND capability=?", vec![string(kind), capability.clone()])
        };
        arguments.truncate(2);
        let rows = self.read(|connection| match connection {
            None => Ok(Vec::new()),
            Some(connection) => sql::all(
                connection,
                &format!("SELECT * FROM overrides WHERE kind=? AND used_at IS NULL {clause} ORDER BY created_at"),
                &arguments,
            ),
        })?;
        Ok(rows
            .into_iter()
            .filter(|row| self.registry.get(sql::get(row, "capability")).is_some())
            .collect())
    }
}
