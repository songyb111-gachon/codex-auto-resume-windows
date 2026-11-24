//! The switches the state holds: recovery on or off, and per conversation; the tiers and holds of schema 4
//! (store/policy.py).

use car_machine::json::Value;
use rusqlite::Connection;

use crate::errors::{Error, Result};
use crate::journal::{Event, event};
use crate::seam::vocab::{HOLDS, WAITING};
use crate::seam::{has, hold_for_tier, ids};
use crate::session::{Store, read_settings};
use crate::validate::{flag, now as check_now, uuid_text, validated_tier};
use crate::value::{Row, execute, first, get, int, marks, string, text_of, tuples, words};

/// `_thread_enabled(connection, thread_id)`: a conversation with no row of its own is on.
pub(crate) fn thread_enabled(connection: &Connection, thread_id: &str) -> Result<bool> {
    match first(
        connection,
        "SELECT enabled FROM threads WHERE thread_id=?",
        &[string(thread_id)],
    )? {
        None => Ok(true),
        Some(row) => flag(&row[0], "thread enabled"),
    }
}

fn thread_tier(connection: &Connection, thread_id: &str) -> Result<Value> {
    match first(
        connection,
        "SELECT tier FROM threads WHERE thread_id=?",
        &[string(thread_id)],
    )? {
        None => Ok(Value::Null),
        Some(row) => {
            validated_tier(&row[0])?;
            Ok(row[0].clone())
        }
    }
}

impl Store {
    /// `settings()`: {enabled, armed_at, poll_seconds, observe_only}.
    pub fn settings(&self) -> Result<Row> {
        self.read(read_settings)
    }

    /// `set_enabled(enabled, now)`: a new enable period starts at `now`.
    pub fn set_enabled(&self, enabled: bool, now: f64) -> Result<()> {
        check_now(now)?;
        if enabled && now == 0.0 {
            return Err(Error::store("Cannot arm with zero timestamp"));
        }
        self.transaction(|connection| {
            let settings = read_settings(connection)?;
            let was = matches!(get(&settings, "enabled"), Value::Bool(true));
            let armed_at = if enabled && !was {
                Value::Float(now)
            } else {
                get(&settings, "armed_at").clone()
            };
            execute(
                connection,
                "UPDATE settings SET enabled=?, armed_at=? WHERE singleton=1",
                &[int(i64::from(enabled)), armed_at],
            )?;
            Ok(())
        })
    }

    /// `set_observe_only(observe_only)`: returns whether it changed.
    pub fn set_observe_only(&self, observe_only: bool) -> Result<bool> {
        self.transaction(|connection| {
            let before = matches!(
                get(&read_settings(connection)?, "observe_only"),
                Value::Bool(true)
            );
            if before != observe_only {
                execute(
                    connection,
                    "UPDATE settings SET observe_only=? WHERE singleton=1",
                    &[int(i64::from(observe_only))],
                )?;
            }
            Ok(before != observe_only)
        })
    }

    /// `thread_enabled(thread_id)`.
    pub fn thread_enabled(&self, thread_id: &str) -> Result<bool> {
        uuid_text(thread_id, "thread_id")?;
        self.read(|connection| thread_enabled(connection, thread_id))
    }

    /// `disabled_threads()`, sorted.
    pub fn disabled_threads(&self) -> Result<Vec<Value>> {
        let mut found = self.read(|connection| {
            Ok(tuples(
                connection,
                "SELECT thread_id FROM threads WHERE enabled=0",
                &[],
            )?)
        })?;
        Ok(sorted_set(
            found.drain(..).map(|mut row| row.remove(0)).collect(),
        ))
    }

    /// `set_thread_enabled(thread_id, enabled, actor=..., at=...)`.
    pub fn set_thread_enabled(
        &self,
        thread_id: &str,
        enabled: bool,
        actor: &str,
        at: Option<f64>,
    ) -> Result<()> {
        uuid_text(thread_id, "thread_id")?;
        self.transaction(|connection| {
            let before = thread_enabled(connection, thread_id)?;
            execute(
                connection,
                "INSERT INTO threads (thread_id, enabled) VALUES (?,?) ON CONFLICT(thread_id) DO UPDATE SET enabled=excluded.enabled",
                &[string(thread_id), int(i64::from(enabled))],
            )?;
            if enabled && !before {
                event(connection, self.now(at)?, "thread_enabled", Event { actor, ..Event::default() })?;
            }
            Ok(())
        })
    }

    /// `thread_tier(thread_id)`: the conversation's own tier, or None.
    pub fn thread_tier(&self, thread_id: &str) -> Result<Value> {
        uuid_text(thread_id, "thread_id")?;
        self.read(|connection| thread_tier(connection, thread_id))
    }

    /// `thread_tiers()`: every conversation with a tier of its own.
    pub fn thread_tiers(&self) -> Result<Row> {
        self.read(|connection| {
            let mut found = Row::new();
            for row in tuples(
                connection,
                "SELECT thread_id, tier FROM threads WHERE tier IS NOT NULL",
                &[],
            )? {
                validated_tier(&row[1])?;
                if let Value::Str(name) = &row[0] {
                    found.insert(name.clone(), row[1].clone());
                }
            }
            Ok(found)
        })
    }

    /// `set_thread_tier(thread_id, tier, now, actor="gui")`: returns {tier, held}.
    pub fn set_thread_tier(
        &self,
        thread_id: &str,
        tier: &Value,
        now: f64,
        actor: &str,
    ) -> Result<Row> {
        uuid_text(thread_id, "thread_id")?;
        check_now(now)?;
        validated_tier(tier)?;
        let hold = hold_for_tier(tier);
        let held = self.transaction(|connection| {
            let before = thread_tier(connection, thread_id)?;
            execute(
                connection,
                "INSERT INTO threads (thread_id, enabled, tier) VALUES (?,1,?) ON CONFLICT(thread_id) DO UPDATE SET tier=excluded.tier",
                &[string(thread_id), tier.clone()],
            )?;
            if !crate::value::py_eq(tier, &before) {
                event(connection, now, "tier_set", Event { actor, ..Event::default() })?;
            }
            let mut held = 0;
            if let Some(hold) = hold {
                let waiting = words(WAITING);
                let mut parameters = vec![string(thread_id)];
                parameters.extend(waiting.iter().cloned());
                let found = self.records(
                    connection,
                    &format!(
                        " WHERE thread_id=? AND hold IS NULL AND submitted_at IS NULL AND cancel_requested=0 AND state IN ({})",
                        marks(waiting.len())
                    ),
                    &parameters,
                )?;
                for row in found {
                    execute(
                        connection,
                        "UPDATE interruptions SET hold=? WHERE interruption_id=?",
                        &[string(hold), get(&row, "interruption_id").clone()],
                    )?;
                    let state = text_of(&row, "state");
                    event(connection, now, "held", Event {
                        record: Some(&row),
                        from_state: state,
                        to_state: state,
                        actor,
                        ..Event::default()
                    })?;
                    held += 1;
                }
            }
            Ok(held)
        })?;
        let mut answer = Row::new();
        answer.insert(crate::value::key("tier"), tier.clone());
        answer.insert(crate::value::key("held"), int(held));
        Ok(answer)
    }

    /// `enrol_conversation(thread_id, tier, now)`: a conversation never seen gets `tier`; whether it was new.
    pub fn enrol_conversation(&self, thread_id: &str, tier: &Value, now: f64) -> Result<bool> {
        uuid_text(thread_id, "thread_id")?;
        check_now(now)?;
        validated_tier(tier)?;
        if matches!(tier, Value::Null) {
            return Err(Error::store("A new conversation needs a tier"));
        }
        self.transaction(|connection| {
            let seen = first(
                connection,
                "SELECT 1 FROM threads WHERE thread_id=? UNION ALL SELECT 1 FROM interruptions WHERE thread_id=? LIMIT 1",
                &[string(thread_id), string(thread_id)],
            )?;
            if seen.is_some() {
                return Ok(false);
            }
            execute(
                connection,
                "INSERT INTO threads (thread_id, enabled, tier) VALUES (?,1,?)",
                &[string(thread_id), tier.clone()],
            )?;
            event(connection, now, "tier_set", Event::default())?;
            Ok(true)
        })
    }

    /// `hold_changed(interruption_id, task_print, now, actor="engine")`: the task-changed guard's hold.
    pub fn hold_changed(
        &self,
        interruption_id: &str,
        task_print: &Value,
        now: f64,
        actor: &str,
    ) -> Result<bool> {
        check_now(now)?;
        if !ids::is_digest(task_print) {
            return Err(Error::store("Invalid task_print"));
        }
        let waiting = words(WAITING);
        self.transaction(|connection| {
            let mut parameters = vec![string(interruption_id)];
            parameters.extend(waiting.iter().cloned());
            let found = self.records(
                connection,
                &format!(
                    " WHERE interruption_id=? AND hold IS NULL AND submitted_at IS NULL AND cancel_requested=0 AND task_print IS NOT NULL AND state IN ({})",
                    marks(waiting.len())
                ),
                &parameters,
            )?;
            let Some(row) = found.into_iter().next() else {
                return Ok(false);
            };
            execute(
                connection,
                "UPDATE interruptions SET hold=?, task_print=? WHERE interruption_id=?",
                &[string("workspace_changed"), task_print.clone(), string(interruption_id)],
            )?;
            let state = text_of(&row, "state");
            event(connection, now, "held", Event {
                record: Some(&row),
                from_state: state,
                to_state: state,
                actor,
                ..Event::default()
            })?;
            Ok(true)
        })
    }

    /// `hold_waiting(interruption_ids, hold, now, actor="gui")`: how many it held.
    pub fn hold_waiting(
        &self,
        interruption_ids: &[String],
        hold: &str,
        now: f64,
        actor: &str,
    ) -> Result<i64> {
        check_now(now)?;
        if !has(HOLDS, hold) {
            return Err(Error::store("Invalid hold"));
        }
        let mut keys: Vec<&String> = interruption_ids.iter().collect();
        keys.sort();
        keys.dedup();
        let waiting = words(WAITING);
        self.transaction(|connection| {
            let mut held = 0;
            for key in keys {
                let mut parameters = vec![string(key)];
                parameters.extend(waiting.iter().cloned());
                let found = self.records(
                    connection,
                    &format!(
                        " WHERE interruption_id=? AND hold IS NULL AND submitted_at IS NULL AND cancel_requested=0 AND state IN ({})",
                        marks(waiting.len())
                    ),
                    &parameters,
                )?;
                let Some(row) = found.into_iter().next() else { continue };
                execute(connection, "UPDATE interruptions SET hold=? WHERE interruption_id=?", &[string(hold), string(key)])?;
                let state = text_of(&row, "state");
                event(connection, now, "held", Event {
                    record: Some(&row),
                    from_state: state,
                    to_state: state,
                    actor,
                    ..Event::default()
                })?;
                held += 1;
            }
            Ok(held)
        })
    }
}

/// A Python `set` of values, sorted for an answer that does not depend on hashing.
pub fn sorted_set(mut values: Vec<Value>) -> Vec<Value> {
    values.sort_by_key(sort_key);
    values.dedup_by(|a, b| crate::value::py_eq(a, b));
    values
}

fn sort_key(value: &Value) -> (u8, Vec<u8>) {
    match value {
        Value::Str(text) => (1, text.as_bytes().to_vec()),
        Value::Null => (0, Vec::new()),
        other => (2, format!("{other:?}").into_bytes()),
    }
}
