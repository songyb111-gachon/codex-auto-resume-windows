//! advanced.sqlite: where it is, opening it, and the transaction everything is written in (`state/session.py`).
//!
//! It lives in `config/advanced/` (`Paths.advanced_dir`) with the provenance marker core's purge reads. The same
//! rules as core's store: no link on the way, nothing outside the home, one connection opened the first time it
//! is needed (Python's `sqlite3.connect(path, timeout=10, isolation_level=None)`, then `trusted_schema=OFF`,
//! `foreign_keys=ON`, `synchronous=FULL`), `BEGIN IMMEDIATE` for every write; a file whose tables, columns or
//! version are not exactly these is refused - but a file of an earlier version, exactly as it made it, is brought to
//! this one at its opening, and a later version's file marked readable from this one is used as it is. A read
//! never creates the file.
//!
//! The one connection serves every thread of its process: a mutex gives each transaction the connection whole,
//! as the reference's re-entrant lock does. Whether it is open is also kept outside the mutex (`open`), so the
//! claim's `attach` asks it without waiting for another thread's transaction, as the reference's `_open` reads
//! `self._connection` without its lock.

use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex, MutexGuard};

use car_config::paths::{OWNER_MARKER, OWNER_TEXT, Paths, is_link};
use car_machine::json::Value;
use rusqlite::Connection;

use super::ask::DefinitionAsked;
use super::errors::{Error, Result};
use super::py;
use super::schema::{self, Shape};
use super::seam::Tokens;
use super::sql;
use crate::registry::GLOBAL_HOURLY;
use crate::registry::Registry;

/// The state's clock: seconds since 1970 (`time.time`), or what a test pins.
pub type Clock = Box<dyn Fn() -> f64 + Send + Sync>;

/// `time.time()`.
pub fn wall_clock() -> f64 {
    car_store::session::wall_clock()
}

/// One installation's advanced state, for one process: opened when first needed (`AdvancedState`).
pub struct AdvancedState {
    pub paths: Paths,
    pub registry: Arc<Registry>,
    /// `config/advanced/`.
    pub directory: PathBuf,
    /// `config/advanced/advanced.sqlite`.
    pub path: PathBuf,
    pub clock: Clock,
    /// `secrets.token_hex`, where a write makes an id of its own.
    pub tokens: Arc<dyn Tokens>,
    connection: Mutex<Option<Connection>>,
    /// Set while `connection` holds an open, checked connection: written under the mutex, read without it
    /// (`_open`'s unlocked read of `self._connection`).
    open: AtomicBool,
}

/// One upgrade step: the version it starts from, the tables it needs, its statements.
type Step = (
    i64,
    &'static [(&'static str, &'static [&'static str])],
    &'static [&'static str],
);

/// The connection, held for one transaction.
pub(crate) type Held<'a> = MutexGuard<'a, Option<Connection>>;

impl AdvancedState {
    /// `AdvancedState(paths, registry=..., clock=...)`.
    pub fn new(
        paths: Paths,
        registry: Arc<Registry>,
        clock: Clock,
        tokens: Arc<dyn Tokens>,
    ) -> Self {
        let directory = PathBuf::from(&paths.advanced_dir);
        let path = directory.join(schema::FILE_NAME);
        AdvancedState {
            paths,
            registry,
            directory,
            path,
            clock,
            tokens,
            connection: Mutex::new(None),
            open: AtomicBool::new(false),
        }
    }

    fn lock(&self) -> Held<'_> {
        self.connection
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
    }

    // ------------------------------------------------------------------ the file
    /// `exists()`: the file is there, and neither it nor its directory is a link or a junction.
    pub fn exists(&self) -> bool {
        self.path.is_file()
            && !is_link(&self.path.to_string_lossy())
            && !is_link(&self.directory.to_string_lossy())
    }

    fn directory_text(&self) -> String {
        self.directory.to_string_lossy().into_owned()
    }

    /// `_directory()`: config/advanced/, made and marked as ours, or a refusal.
    fn make_directory(&self) -> Result<()> {
        self.paths
            .ensure()
            .map_err(|raised| Error::python(raised.class(), raised.message()))?;
        let directory = self.directory_text();
        if is_link(&directory) || (self.directory.exists() && !self.paths.confined(&directory)) {
            return Err(Error::state(
                "the advanced state directory is a link or escapes the home",
            ));
        }
        match std::fs::create_dir(&self.directory) {
            Ok(()) => {}
            Err(_) if self.directory.is_dir() => {}
            Err(_) => return Err(cannot_open()),
        }
        let marker = self.directory.join(OWNER_MARKER);
        self.checked()?;
        if !marker.exists() {
            std::fs::write(&marker, owner_text().as_bytes()).map_err(|_| cannot_open())?;
        }
        Ok(())
    }

    /// `_checked()`: the refusals `_directory` makes, and nothing it writes.
    fn checked(&self) -> Result<()> {
        let directory = self.directory_text();
        if is_link(&directory) || !self.paths.confined(&directory) {
            return Err(Error::state(
                "the advanced state directory is a link or escapes the home",
            ));
        }
        if is_link(&self.path.to_string_lossy()) {
            return Err(Error::state("the advanced state is a link"));
        }
        Ok(())
    }

    /// `_open(create=...)` under the lock: the connection, opened and checked the first time; None where the file
    /// is not there and `create` is false.
    pub(crate) fn opened<'a>(
        &self,
        held: &'a mut Held<'_>,
        create: bool,
    ) -> Result<Option<&'a Connection>> {
        if held.is_none() {
            match self.open_connection(create)? {
                Some(connection) => {
                    **held = Some(connection);
                    self.open.store(true, Ordering::SeqCst);
                }
                None => return Ok(None),
            }
        }
        Ok(held.as_ref())
    }

    fn open_connection(&self, create: bool) -> Result<Option<Connection>> {
        if !create && !self.exists() {
            return Ok(None);
        }
        if create {
            self.make_directory()?;
        } else {
            self.checked()?;
        }
        let was_present = self.path.exists();
        let connection = car_store::session::connect(&self.path).map_err(|_| cannot_open())?;
        let prepared = (|| -> Result<bool> {
            sql::exec(&connection, "PRAGMA trusted_schema=OFF", &[])?;
            sql::exec(&connection, "PRAGMA foreign_keys=ON", &[])?;
            sql::exec(&connection, "PRAGMA synchronous=FULL", &[])?;
            sql::exec(
                &connection,
                if create { "BEGIN IMMEDIATE" } else { "BEGIN" },
                &[],
            )?;
            match self.prepare(&connection, was_present, create) {
                Ok(prepared) => {
                    sql::exec(&connection, "COMMIT", &[])?;
                    Ok(prepared)
                }
                Err(error) => {
                    sql::exec(&connection, "ROLLBACK", &[])?;
                    Err(error)
                }
            }
        })();
        match prepared {
            Ok(true) => Ok(Some(connection)),
            Ok(false) => Ok(None),
            Err(error @ Error::State { .. }) => Err(error),
            Err(Error::Sqlite(_)) => Err(cannot_open()),
            Err(other) => Err(other),
        }
    }

    /// `_tables(connection)`: every table but SQLite's own, with its columns, in sqlite_master's order.
    pub(crate) fn tables(connection: &Connection) -> Result<Shape> {
        let names = sql::tuples(
            connection,
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'",
            &[],
        )?;
        let mut found = Shape::new();
        for row in names {
            let name = py::py_str(row.first().unwrap_or(&Value::Null));
            let columns = sql::tuples(connection, &format!("PRAGMA table_info({name})"), &[])?
                .into_iter()
                .map(|column| py::py_str(column.get(1).unwrap_or(&Value::Null)))
                .collect();
            found.push((name, columns));
        }
        Ok(found)
    }

    /// `_prepare(connection, was_present, create)`: whether the file is this schema, made now where `create` and
    /// there is none; every earlier version's step taken, a newer readable one used as it is.
    fn prepare(&self, connection: &Connection, was_present: bool, create: bool) -> Result<bool> {
        let mut version = sql::number(connection, "PRAGMA user_version", &[])?;
        let mut tables = Self::tables(connection)?;
        if version == 0 && tables.is_empty() {
            if !create {
                return Ok(false);
            }
            let size = std::fs::metadata(&self.path)
                .map(|found| found.len())
                .unwrap_or(0);
            if was_present && size > 0 {
                return Err(Error::state(
                    "the advanced state is empty or uninitialized; refusing to reset it",
                ));
            }
            for statement in schema::STATEMENTS {
                sql::exec(connection, statement, &[])?;
            }
            tables = Self::tables(connection)?;
            version = super::builds::version();
        }
        if version > super::builds::version() {
            if schema::readable_from(connection, version)? > super::builds::version() {
                return Err(Error::state(
                    "the advanced state was written by a newer version",
                ));
            }
            if !schema::holds(&tables, super::builds::tables()) {
                return Err(Error::state("unsupported or malformed advanced state"));
            }
        } else {
            let steps: [Step; 9] = [
                (1, schema::TABLES_V1, schema::UPGRADE_FROM_1),
                (2, schema::TABLES_V2, schema::UPGRADE_FROM_2),
                (3, schema::TABLES_V3_BEFORE_RESETS, schema::ADD_RESETS),
                (3, schema::TABLES_V3, schema::UPGRADE_FROM_3),
                (4, schema::TABLES_V4, schema::UPGRADE_FROM_4),
                (5, schema::TABLES_V5, schema::UPGRADE_FROM_5),
                (
                    schema::STAGE4_VERSION - 1,
                    schema::TABLES_BEFORE_STAGE4,
                    schema::UPGRADE_TO_STAGE4,
                ),
                (
                    schema::STAGE4_VERSION,
                    schema::TABLES_V7,
                    super::builds::statements("UPGRADE_TO_V019", schema::UPGRADE_TO_V019),
                ),
                (
                    schema::V019_VERSION,
                    schema::TABLES_V8,
                    schema::UPGRADE_TO_V020,
                ),
            ];
            for (old, shape, statements) in steps {
                if version == old && schema::same(&tables, shape) {
                    for statement in statements {
                        sql::exec(connection, statement, &[])?;
                    }
                    tables = Self::tables(connection)?;
                    version = sql::number(connection, "PRAGMA user_version", &[])?;
                }
            }
            if version != super::builds::version() || !schema::same(&tables, super::builds::tables()) {
                return Err(Error::state("unsupported or malformed advanced state"));
            }
            if schema::names_checked(connection)? {
                for statement in super::builds::statements("FREE_OPTIONS", schema::FREE_OPTIONS) {
                    sql::exec(connection, statement, &[])?;
                }
            } else if schema::readable_from(connection, version)? != schema::READABLE_FROM {
                sql::exec(connection, super::builds::statement("MARKED", schema::MARKED), &[])?;
            }
            if schema::wordings_checked(connection)? {
                for statement in super::builds::statements("FREE_WORDINGS", schema::FREE_WORDINGS) {
                    sql::exec(connection, statement, &[])?;
                }
            }
            if let Some(old) = schema::hourly_bound(connection)?
                && old < GLOBAL_HOURLY
            {
                for statement in schema::HOURLY_REMADE {
                    sql::exec(connection, statement, &[])?;
                }
                sql::exec(
                    connection,
                    "UPDATE meta SET global_hourly=? WHERE global_hourly=?",
                    &[py::int(GLOBAL_HOURLY), py::int(old)],
                )?;
            }
            schema::widen_words(connection)?;
        }
        if sql::number(connection, "SELECT count(*) FROM meta", &[])? != 1 {
            return Err(Error::state("malformed advanced state"));
        }
        self.carry_windows(connection)?;
        Ok(true)
    }

    /// `_carry_windows(connection)`: the wrap-up's and the stop's window switches written once, as the usage
    /// meter's switch for that window stands, for each one this registry's capability offers and has no row yet.
    fn carry_windows(&self, connection: &Connection) -> Result<()> {
        let mut wanted: Vec<(&str, &str)> = Vec::new();
        for capability in schema::WINDOW_FOLLOWERS {
            let definition = self.registry.get(capability);
            for choice in schema::WINDOW_CHOICES {
                if definition
                    .is_some_and(|definition| definition.option_of(&py::word(choice)).is_some())
                {
                    wanted.push((capability, choice));
                }
            }
        }
        if wanted.is_empty() {
            return Ok(());
        }
        let rows = sql::tuples(
            connection,
            "SELECT capability, choice, value FROM options WHERE choice IN (?, ?)",
            &sql::words(schema::WINDOW_CHOICES),
        )?;
        let mut held: Vec<((String, String), Value)> = Vec::new();
        for row in rows {
            let pair = (py::py_str(&row[0]), py::py_str(&row[1]));
            let value = row[2].clone();
            match held.iter_mut().find(|(each, _)| *each == pair) {
                Some(entry) => entry.1 = value,
                None => held.push((pair, value)),
            }
        }
        let find = |capability: &str, choice: &str| {
            held.iter()
                .find(|((one, two), _)| one == capability && two == choice)
                .map(|(_, value)| value.clone())
        };
        for (capability, choice) in wanted {
            if find(capability, choice).is_some() {
                continue;
            }
            let value = find(schema::WINDOW_LEADER, choice).unwrap_or(py::int(schema::WINDOW_ON));
            let value = if sql::py_eq(&value, &py::int(schema::WINDOW_ON))
                || sql::py_eq(&value, &py::int(schema::WINDOW_OFF))
            {
                value
            } else {
                py::int(schema::WINDOW_ON)
            };
            sql::exec(
                connection,
                "INSERT INTO options (capability, choice, value) VALUES (?,?,?)",
                &[py::word(capability), py::word(choice), value],
            )?;
        }
        Ok(())
    }

    /// `close()`.
    pub fn close(&self) {
        let mut held = self.lock();
        self.open.store(false, Ordering::SeqCst);
        *held = None;
    }

    // ---------------------------------------------------------------- transactions
    /// `_transaction(create=...)`: a write transaction, or `body(None)` where the file is not there and nothing
    /// asked to make it.
    pub(crate) fn transaction<T>(
        &self,
        create: bool,
        body: impl FnOnce(Option<&Connection>) -> Result<T>,
    ) -> Result<T> {
        let mut held = self.lock();
        match self.opened(&mut held, create)? {
            None => body(None),
            Some(connection) => begin(connection, "BEGIN IMMEDIATE", |connection| {
                body(Some(connection))
            }),
        }
    }

    /// `_transaction()` that always makes the file (the default `create=True`): the body sees the connection.
    pub(crate) fn writing<T>(&self, body: impl FnOnce(&Connection) -> Result<T>) -> Result<T> {
        self.transaction(true, |connection| match connection {
            Some(connection) => body(connection),
            None => Err(Error::state("cannot open the advanced state")),
        })
    }

    /// `_read()`: one consistent snapshot, or `body(None)` where there is no file to read.
    pub(crate) fn read<T>(&self, body: impl FnOnce(Option<&Connection>) -> Result<T>) -> Result<T> {
        let mut held = self.lock();
        match self.opened(&mut held, false)? {
            None => body(None),
            Some(connection) => begin(connection, "BEGIN", |connection| body(Some(connection))),
        }
    }

    /// `_now(at)`: `at`, or the clock, as a time of the store's window.
    pub fn now(&self, at: &Value) -> Result<f64> {
        if matches!(at, Value::Null) {
            return py::timestamp(&Value::Float((self.clock)()), "time");
        }
        py::timestamp(at, "time")
    }

    /// The clock's reading (`state.clock()`).
    pub fn clock_now(&self) -> f64 {
        (self.clock)()
    }

    // ---------------------------------------------------------------- the one claim
    /// `attach(connection)`: this file attached to `connection` - core's, inside its one claim - as ATTACHED, once
    /// per connection. The file is opened and checked on its own connection first, so a file that would be refused
    /// is never attached; one that is not there is not made, and false says so.
    ///
    /// An already-open connection is answered without the mutex: the claim attaches the file from core's
    /// transaction, which must not wait for a transaction of this connection's on another thread (`_open`).
    pub fn attach(&self, connection: &Connection) -> Result<bool> {
        if !self.open.load(Ordering::SeqCst) {
            let mut held = self.lock();
            if self.opened(&mut held, false)?.is_none() {
                return Ok(false);
            }
        }
        let names: Vec<Value> = sql::tuples(connection, "PRAGMA database_list", &[])?
            .into_iter()
            .filter_map(|row| row.into_iter().nth(1))
            .collect();
        if !names
            .iter()
            .any(|name| py::is_word(name, &[schema::ATTACHED]))
        {
            let text = self.path.to_string_lossy().replace('\'', "''");
            sql::exec(
                connection,
                &format!("ATTACH DATABASE '{text}' AS {}", schema::ATTACHED),
                &[],
            )?;
        }
        Ok(true)
    }

    /// The directory, as a path.
    pub fn folder(&self) -> &Path {
        &self.directory
    }
}

/// `OWNER_TEXT` as Python's `write_text` writes it: in text mode, so a line ends CR LF on Windows.
pub fn owner_text() -> String {
    if cfg!(windows) {
        OWNER_TEXT.replace('\n', "\r\n")
    } else {
        OWNER_TEXT.to_string()
    }
}

fn cannot_open() -> Error {
    Error::state("cannot open the advanced state")
}

/// Rolls back the open transaction when a panic unwinds through `begin` (D15 catches panics at the host, and a state
/// that outlives one must not keep its transaction and advanced.sqlite RESERVED, as Python, whose `except
/// BaseException` always rolls back, never does). car-store's `begin` has the same guard.
struct RollbackOnUnwind<'a>(&'a Connection);

impl Drop for RollbackOnUnwind<'_> {
    fn drop(&mut self) {
        if std::thread::panicking() && !self.0.is_autocommit() {
            let _ = self.0.execute_batch("ROLLBACK");
        }
    }
}

/// `_begin(connection, statement)`: the statement, the body, COMMIT; on any error ROLLBACK where a transaction is
/// open, and SQLite's own error as `StateError("advanced state transaction failed")`. A panic in the body rolls
/// back too. A ROLLBACK that fails goes out as SQLite's own error, as the reference's `connection.execute
/// ("ROLLBACK")` inside its `except` raises the raw `sqlite3.Error`.
pub(crate) fn begin<T>(
    connection: &Connection,
    statement: &str,
    body: impl FnOnce(&Connection) -> Result<T>,
) -> Result<T> {
    let _guard = RollbackOnUnwind(connection);
    let outcome = (|| {
        sql::exec(connection, statement, &[])?;
        let value = body(connection)?;
        sql::exec(connection, "COMMIT", &[])?;
        Ok(value)
    })();
    match outcome {
        Ok(value) => Ok(value),
        Err(error) => {
            if !connection.is_autocommit() {
                sql::exec(connection, "ROLLBACK", &[])?;
            }
            match error {
                Error::Sqlite(_) => Err(Error::state("advanced state transaction failed")),
                other => Err(other),
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_panic_in_a_body_rolls_back() {
        let connection = Connection::open_in_memory().unwrap();
        connection
            .execute_batch("CREATE TABLE t (x INTEGER)")
            .unwrap();
        let caught = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
            let _ = begin(&connection, "BEGIN IMMEDIATE", |connection| -> Result<()> {
                connection
                    .execute_batch("INSERT INTO t VALUES (1)")
                    .unwrap();
                panic!("a body that panics");
            });
        }));
        assert!(caught.is_err());
        assert!(
            connection.is_autocommit(),
            "the transaction was rolled back"
        );
        let count: i64 = connection
            .query_row("SELECT count(*) FROM t", [], |row| row.get(0))
            .unwrap();
        assert_eq!(count, 0);
        begin(&connection, "BEGIN IMMEDIATE", |_| Ok(())).unwrap();
    }
}
