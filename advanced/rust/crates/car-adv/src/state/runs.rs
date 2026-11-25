//! A turn run here (`state/runs.py`): while it runs, a person's Stop of it, how it ended, and the model a fallback
//! turn owes the conversation back.

use car_machine::json::Value;

use super::errors::{Error, Result};
use super::py;
use super::schema::{HEADLESS_CAPABILITIES, MODEL_NAME};
use super::seam::words_gen::run_end;
use super::session::AdvancedState;
use super::sql::{self, Row, float, string};

const COLUMNS: &str = "interruption_id, capability, thread_id, started_at, ends_by, stop_requested_at, ended_at, end, restore_model";

fn capability_of(value: &Value) -> Result<()> {
    if !py::is_word(value, HEADLESS_CAPABILITIES) {
        return Err(Error::state("invalid capability"));
    }
    Ok(())
}

impl AdvancedState {
    /// `run_started(key, capability, thread_id, started_at=..., ends_by=...)`.
    pub fn run_started(
        &self,
        key: &Value,
        capability: &Value,
        thread_id: &Value,
        started_at: &Value,
        ends_by: &Value,
    ) -> Result<()> {
        py::key(key, "run key")?;
        capability_of(capability)?;
        py::thread(thread_id)?;
        let started = py::timestamp(started_at, "started_at")?;
        let ends = py::timestamp(ends_by, "ends_by")?;
        self.writing(|connection| {
            sql::exec(
                connection,
                "INSERT INTO headless_runs (interruption_id, capability, thread_id, started_at, ends_by) VALUES \
                 (?,?,?,?,?) ON CONFLICT(interruption_id) DO UPDATE SET capability=excluded.capability, \
                 thread_id=excluded.thread_id, started_at=excluded.started_at, ends_by=excluded.ends_by, \
                 ended_at=NULL, end=NULL",
                &[key.clone(), capability.clone(), thread_id.clone(), float(started), float(ends)],
            )?;
            Ok(())
        })
    }

    /// `run_owed(key, capability, thread_id, model, started_at=..., ends_by=...)`.
    #[allow(clippy::too_many_arguments)]
    pub fn run_owed(
        &self,
        key: &Value,
        capability: &Value,
        thread_id: &Value,
        model: &Value,
        started_at: &Value,
        ends_by: &Value,
    ) -> Result<()> {
        py::key(key, "run key")?;
        capability_of(capability)?;
        py::thread(thread_id)?;
        if !py::length(model).is_some_and(|length| 0 < length && length as i64 <= MODEL_NAME) {
            return Err(Error::state("invalid model"));
        }
        let started = py::timestamp(started_at, "started_at")?;
        let ends = py::timestamp(ends_by, "ends_by")?;
        self.writing(|connection| {
            sql::exec(
                connection,
                "INSERT INTO headless_runs (interruption_id, capability, thread_id, started_at, ends_by, restore_model) \
                 VALUES (?,?,?,?,?,?) ON CONFLICT(interruption_id) DO UPDATE SET capability=excluded.capability, \
                 thread_id=excluded.thread_id, started_at=excluded.started_at, ends_by=excluded.ends_by, \
                 ended_at=NULL, end=NULL, restore_model=excluded.restore_model",
                &[
                    key.clone(),
                    capability.clone(),
                    thread_id.clone(),
                    float(started),
                    float(ends),
                    model.clone(),
                ],
            )?;
            Ok(())
        })
    }

    /// `run_restored(key)`: owed no more; false where none was owed.
    pub fn run_restored(&self, key: &Value) -> Result<bool> {
        py::key(key, "run key")?;
        self.writing(|connection| {
            Ok(sql::exec(
                connection,
                "UPDATE headless_runs SET restore_model=NULL WHERE interruption_id=? AND restore_model IS NOT NULL",
                &[key.clone()],
            )? == 1)
        })
    }

    /// `runs_owed(capability)`: its runs that still owe their conversation its model, oldest first.
    pub fn runs_owed(&self, capability: &Value) -> Result<Vec<Row>> {
        capability_of(capability)?;
        self.read(|connection| match connection {
            None => Ok(Vec::new()),
            Some(connection) => sql::all(
                connection,
                &format!(
                    "SELECT {COLUMNS} FROM headless_runs WHERE capability=? AND restore_model IS NOT NULL \
                     ORDER BY started_at"
                ),
                &[capability.clone()],
            ),
        })
    }

    /// `run_ended(key, end, at=None)`.
    pub fn run_ended(&self, key: &Value, end: &Value, at: &Value) -> Result<bool> {
        py::key(key, "run key")?;
        let end = py::closed(end, run_end::ALL, "end")?;
        let now = self.now(at)?;
        self.writing(|connection| {
            Ok(sql::exec(
                connection,
                "UPDATE headless_runs SET ended_at=?, end=? WHERE interruption_id=? AND end IS NULL",
                &[float(now), string(end), key.clone()],
            )? == 1)
        })
    }

    /// `run_stop(key, at=None)`: a person's Stop.
    pub fn run_stop(&self, key: &Value, at: &Value) -> Result<bool> {
        py::key(key, "run key")?;
        let now = self.now(at)?;
        self.writing(|connection| {
            Ok(sql::exec(
                connection,
                "UPDATE headless_runs SET stop_requested_at=? WHERE interruption_id=? AND end IS NULL",
                &[float(now), key.clone()],
            )? == 1)
        })
    }

    /// `runs(live=True, limit=20)`: the newest first.
    pub fn runs(&self, live: &Value, limit: &Value) -> Result<Vec<Row>> {
        self.read(|connection| match connection {
            None => Ok(Vec::new()),
            Some(connection) => {
                let limit = py::int_of(limit)?;
                sql::all(
                    connection,
                    &format!(
                        "SELECT {COLUMNS} FROM headless_runs {} ORDER BY started_at DESC LIMIT ?",
                        if sql::truthy(live) {
                            "WHERE end IS NULL"
                        } else {
                            ""
                        }
                    ),
                    &[limit],
                )
            }
        })
    }

    /// `prune_runs(before, capability=None)`: ended runs older than `before` gone, never one still owing a model.
    pub fn prune_runs(&self, before: &Value, capability: &Value) -> Result<i64> {
        py::timestamp(before, "before")?;
        if !matches!(capability, Value::Null) {
            capability_of(capability)?;
        }
        self.transaction(false, |connection| match connection {
            None => Ok(0),
            Some(connection) => Ok(sql::exec(
                connection,
                "DELETE FROM headless_runs WHERE end IS NOT NULL AND ended_at < ? AND restore_model IS NULL \
                 AND (? IS NULL OR capability = ?)",
                &[before.clone(), capability.clone(), capability.clone()],
            )? as i64),
        })
    }
}
