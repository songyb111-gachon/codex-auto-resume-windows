//! The state as an older release wrote it, opened without changing its schema (store/legacy.py).
//!
//! Opened as Python opens it: `timeout=10`, no transaction but its own, `trusted_schema=OFF` - and nothing
//! else, so `foreign_keys` is set OFF here, which is Python's sqlite3 default and not the bundled SQLite's.
//! Every call, a read too, is one `BEGIN IMMEDIATE` transaction.

use std::path::{Path, PathBuf};

use car_machine::json::Value;
use rusqlite::Connection;

use crate::errors::{Error, Result};
use crate::machine::vocab::{STATES, TERMINAL, V2_STATES};
use crate::schema::{TABLES_V2, TABLES_V3, TABLES_V4, table_set, tables};
use crate::session::{Links, begin, connect, read_settings};
use crate::validate::{now as check_now, uuid_text};
use crate::value::{Row, execute, first, int, integer, marks, string, tuples, words};

/// A state an older watcher still owns - schema 1 or 2 (v0.5), 3 (v0.6.0 to v0.6.10) or 4 (v0.6.11 to
/// v0.6.15) - opened without changing it (`LegacyStore`).
pub struct LegacyStore {
    pub path: PathBuf,
    pub version: i64,
    connection: Option<Connection>,
    states: Vec<&'static str>,
    terminal: Vec<&'static str>,
}

impl LegacyStore {
    /// `LegacyStore(state_dir)`.
    pub fn open(state_dir: &Path, links: &dyn Links) -> Result<LegacyStore> {
        let path = state_dir.join("state.sqlite");
        let unreadable = || Error::store("Cannot open valid auto-resume state");
        if links.is_symlink(state_dir) || links.is_symlink(&path) || !path.is_file() {
            return Err(unreadable());
        }
        let opened =
            (|| -> rusqlite::Result<(Connection, i64, std::collections::BTreeSet<String>)> {
                let connection = connect(&path)?;
                execute(&connection, "PRAGMA trusted_schema=OFF", &[])?;
                execute(&connection, "PRAGMA foreign_keys=OFF", &[])?;
                let version = integer(&connection, "PRAGMA user_version", &[])?;
                let found = tables(&connection)?;
                Ok((connection, version, found))
            })();
        let (connection, version, found) = opened.map_err(|_| unreadable())?;
        let known = [
            (1, TABLES_V2),
            (2, TABLES_V2),
            (3, TABLES_V3),
            (4, TABLES_V4),
        ];
        if !known
            .iter()
            .any(|(v, names)| *v == version && table_set(names) == found)
        {
            return Err(Error::store("Not a state an older watcher owns"));
        }
        let states: Vec<&'static str> = if version < 3 {
            V2_STATES.to_vec()
        } else {
            STATES.to_vec()
        };
        let terminal = states
            .iter()
            .copied()
            .filter(|state| TERMINAL.contains(state))
            .collect();
        Ok(LegacyStore {
            path,
            version,
            connection: Some(connection),
            states,
            terminal,
        })
    }

    /// `close()`.
    pub fn close(&mut self) {
        self.connection = None;
    }

    fn transaction<T>(&self, body: impl FnOnce(&Connection) -> Result<T>) -> Result<T> {
        let connection = self.connection.as_ref().ok_or_else(|| {
            Error::Python(
                "AttributeError",
                "'NoneType' object has no attribute 'execute'".into(),
            )
        })?;
        begin(connection, "BEGIN IMMEDIATE", body)
    }

    /// One PRAGMA's value on this store's connection, read only (as [`Store::pragma`](crate::Store::pragma)).
    pub fn pragma(&self, name: &str) -> Result<Value> {
        if !name
            .bytes()
            .all(|byte| byte.is_ascii_lowercase() || byte == b'_')
        {
            return Err(Error::Python("ValueError", "not a PRAGMA name".into()));
        }
        let connection = self
            .connection
            .as_ref()
            .ok_or_else(|| Error::store("Store is closed"))?;
        Ok(crate::value::scalar(
            connection,
            &format!("PRAGMA {name}"),
            &[],
        )?)
    }

    /// `settings()`.
    pub fn settings(&self) -> Result<Row> {
        self.transaction(read_settings)
    }

    /// `set_enabled(enabled, now)`.
    pub fn set_enabled(&self, enabled: bool, now: f64) -> Result<()> {
        check_now(now)?;
        self.transaction(|connection| {
            // `row[0]` of no row is Python's TypeError, which the transaction rolls back and lets through.
            let row = first(
                connection,
                "SELECT enabled, armed_at FROM settings WHERE singleton=1",
                &[],
            )?
            .ok_or_else(|| {
                Error::Python("TypeError", "'NoneType' object is not subscriptable".into())
            })?;
            let was = row.first().is_some_and(crate::value::truthy);
            let armed = if enabled && !was {
                Value::Float(now)
            } else {
                row.get(1).cloned().unwrap_or(Value::Null)
            };
            execute(
                connection,
                "UPDATE settings SET enabled=?, armed_at=? WHERE singleton=1",
                &[int(i64::from(enabled)), armed],
            )?;
            Ok(())
        })
    }

    /// `thread_enabled(thread_id)`.
    pub fn thread_enabled(&self, thread_id: &str) -> Result<bool> {
        uuid_text(thread_id, "thread_id")?;
        let row = self.transaction(|connection| {
            Ok(first(
                connection,
                "SELECT enabled FROM threads WHERE thread_id=?",
                &[string(thread_id)],
            )?)
        })?;
        Ok(row.is_none_or(|row| crate::value::truthy(&row[0])))
    }

    /// `set_thread_enabled(thread_id, enabled)`.
    pub fn set_thread_enabled(&self, thread_id: &str, enabled: bool) -> Result<()> {
        uuid_text(thread_id, "thread_id")?;
        self.transaction(|connection| {
            execute(
                connection,
                "INSERT INTO threads (thread_id, enabled) VALUES (?,?) ON CONFLICT(thread_id) DO UPDATE SET enabled=excluded.enabled",
                &[string(thread_id), int(i64::from(enabled))],
            )?;
            Ok(())
        })
    }

    /// `cancel_thread(thread_id, now)`: v0.5's cancel, exactly.
    pub fn cancel_thread(&self, thread_id: &str, now: f64) -> Result<()> {
        uuid_text(thread_id, "thread_id")?;
        check_now(now)?;
        let terminal = words(&self.terminal);
        let reason = if self.version >= 3 {
            ", last_error='user_cancelled'"
        } else {
            ""
        };
        self.transaction(|connection| {
            execute(
                connection,
                "INSERT INTO threads (thread_id, enabled) VALUES (?,0) ON CONFLICT(thread_id) DO UPDATE SET enabled=0",
                &[string(thread_id)],
            )?;
            let mut parameters = vec![string(thread_id)];
            parameters.extend(terminal.iter().cloned());
            execute(
                connection,
                &format!(
                    "UPDATE interruptions SET cancel_requested=1 WHERE thread_id=? AND submitted_at IS NOT NULL AND state NOT IN ({})",
                    marks(terminal.len())
                ),
                &parameters,
            )?;
            let mut parameters = vec![Value::Float(now), string(thread_id)];
            parameters.extend(terminal.iter().cloned());
            execute(
                connection,
                &format!(
                    "UPDATE interruptions SET state='cancelled', cancel_requested=1{reason}, next_retry_at=? WHERE thread_id=? AND submitted_at IS NULL AND state NOT IN ({})",
                    marks(terminal.len())
                ),
                &parameters,
            )?;
            Ok(())
        })
    }

    /// `status_counts()`: by the states that older watcher knows.
    pub fn status_counts(&self) -> Result<Row> {
        let found = self.transaction(|connection| {
            Ok(tuples(
                connection,
                "SELECT state, count(*) FROM interruptions GROUP BY state",
                &[],
            )?)
        })?;
        let mut counts = Row::new();
        for row in found {
            if let Value::Str(state) = &row[0]
                && crate::value::is_in(&row[0], &self.states)
            {
                counts.insert(state.clone(), row[1].clone());
            }
        }
        Ok(counts)
    }

    /// `thread_of(interruption_id)`.
    pub fn thread_of(&self, interruption_id: &str) -> Result<Value> {
        let row = self.transaction(|connection| {
            Ok(first(
                connection,
                "SELECT thread_id FROM interruptions WHERE interruption_id=?",
                &[string(interruption_id)],
            )?)
        })?;
        Ok(row.map_or(Value::Null, |mut row| row.remove(0)))
    }

    /// `disabled_threads()`, sorted.
    pub fn disabled_threads(&self) -> Result<Vec<Value>> {
        let found = self.transaction(|connection| {
            Ok(tuples(
                connection,
                "SELECT thread_id FROM threads WHERE enabled=0",
                &[],
            )?)
        })?;
        Ok(crate::policy::sorted_set(
            found.into_iter().map(|mut row| row.remove(0)).collect(),
        ))
    }
}
