//! One connection to the state, opened and closed (store/session.py).
//!
//! The connection is opened as Python's `sqlite3.connect(path, timeout=10, isolation_level=None)`: read-write,
//! created if missing, no URI parsing, a busy timeout of 10 s, and no transaction but the ones the store
//! begins itself. Then `trusted_schema=OFF`, `foreign_keys=ON`, `synchronous=FULL`; the journal stays
//! SQLite's default (DELETE, never WAL), as Python leaves it. A write is `BEGIN IMMEDIATE`, a read `BEGIN`.

use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use car_machine::json::Value;
use rusqlite::{Connection, OpenFlags};

use crate::columns::{notice_select, record_select};
use crate::errors::{Error, Kind, Result};
use crate::migrations::migrate;
use crate::schema::{
    SCHEMA_VERSION, TABLES_V4, create_schema, marked, readable_from, table_set, tables,
    validate_schema, write_mark,
};
use crate::validate::{flag, timestamp, uuid, validated_notice, validated_record, validated_tier};
use crate::value::{Row, execute, get, integer, rows, string};

/// Python sqlite3's `timeout=10`.
pub const BUSY_TIMEOUT: Duration = Duration::from_secs(10);

/// The store's clock: seconds since 1970, as `time.time()`.
pub type Clock = Box<dyn Fn() -> f64 + Send>;

/// `time.time()`.
pub fn wall_clock() -> f64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_or(0.0, |elapsed| elapsed.as_secs_f64())
}

/// The one question the store asks of Windows about a path (cut C3, as [`crate::open::Windows`]): whether it is a
/// symbolic link as Python's `Path.is_symlink()` says. A junction is not one, so a junction redirecting the state
/// folder is not refused, as the reference does not refuse it. car-platform has the one probe
/// (`car_platform::links::is_symlink`); the harness and the entry points wire it in.
pub trait Links: Send + Sync {
    /// `Path(path).is_symlink()`.
    fn is_symlink(&self, path: &Path) -> bool;
    /// `(os.stat(path).st_dev, os.stat(path).st_ino)`, as `os.path.samefile` compares two files (P11's ATTACH,
    /// `store/ledger.py` `_same_file`): None where `stat` raises OSError, and so where nothing is wired in.
    fn file_identity(&self, _path: &Path) -> Option<(u32, u64)> {
        None
    }
}

/// Open a connection as Python's `sqlite3.connect(path, timeout=10, isolation_level=None)` does.
pub fn connect(path: &Path) -> rusqlite::Result<Connection> {
    let flags = OpenFlags::SQLITE_OPEN_READ_WRITE
        | OpenFlags::SQLITE_OPEN_CREATE
        | OpenFlags::SQLITE_OPEN_NO_MUTEX;
    let connection = Connection::open_with_flags(path, flags)?;
    connection.busy_timeout(BUSY_TIMEOUT)?;
    Ok(connection)
}

/// How a store is opened (`Store(state_dir, migrate=..., check=..., clock=...)`).
pub struct Options {
    /// Only the watcher, or a caller holding its mutex, may upgrade an older schema.
    pub migrate: bool,
    /// The full integrity check and every row validated at open.
    pub check: bool,
    pub clock: Clock,
    /// `Path.is_symlink()`.
    pub links: Arc<dyn Links>,
}

impl Options {
    /// The defaults of `Store(state_dir)`: no migration, the full check, the wall clock.
    pub fn new(links: Arc<dyn Links>) -> Self {
        Options {
            migrate: false,
            check: true,
            clock: Box::new(wall_clock),
            links,
        }
    }
}

/// One connection to our own state database (`codex_auto_resume.store.Store`).
pub struct Store {
    pub state_dir: PathBuf,
    pub path: PathBuf,
    pub(crate) clock: Clock,
    pub(crate) links: Arc<dyn Links>,
    connection: Option<Connection>,
    /// The schema the open upgraded from, or None.
    pub migrated_from: Option<i64>,
    /// How a record is read: `SELECT *`, or this version's own columns in a later version's readable state.
    pub(crate) record_sql: String,
}

impl Store {
    /// `Store(state_dir, migrate=False, check=True)`.
    pub fn open(state_dir: &Path, links: Arc<dyn Links>) -> Result<Store> {
        Store::open_with(state_dir, Options::new(links))
    }

    /// `Store(state_dir, migrate=..., check=..., clock=...)`.
    pub fn open_with(state_dir: &Path, options: Options) -> Result<Store> {
        let mut store = Store {
            state_dir: state_dir.to_path_buf(),
            path: state_dir.join("state.sqlite"),
            clock: options.clock,
            links: options.links,
            connection: None,
            migrated_from: None,
            record_sql: "SELECT * FROM interruptions".into(),
        };
        match store.opening(options.migrate, options.check) {
            Ok(()) => Ok(store),
            Err(error) => {
                store.close();
                match error {
                    Error::Store(..) | Error::Python(..) => Err(error),
                    Error::Sqlite(_) => Err(Error::store("Cannot open valid auto-resume state")),
                }
            }
        }
    }

    fn opening(&mut self, migrate_allowed: bool, check: bool) -> Result<()> {
        if self.links.is_symlink(&self.state_dir) || self.links.is_symlink(&self.path) {
            return Err(Error::store("State paths must not be symbolic links"));
        }
        if std::fs::create_dir_all(&self.state_dir).is_err() || !self.state_dir.is_dir() {
            return Err(Error::store("Cannot open valid auto-resume state"));
        }
        let was_present = self.path.exists();
        let connection = connect(&self.path)?;
        execute(&connection, "PRAGMA trusted_schema=OFF", &[])?;
        execute(&connection, "PRAGMA foreign_keys=ON", &[])?;
        execute(&connection, "PRAGMA synchronous=FULL", &[])?;
        let version = integer(&connection, "PRAGMA user_version", &[])?;
        self.connection = Some(connection);
        if version > SCHEMA_VERSION && readable_from(self.connection(), version)? > SCHEMA_VERSION {
            return Err(newer());
        }
        if (1..SCHEMA_VERSION).contains(&version) {
            if !migrate_allowed {
                return Err(pending());
            }
            self.forensic_copy(version)?;
        }
        let marking = migrate_allowed && version == SCHEMA_VERSION && !marked(self.connection())?;
        let writing = version < SCHEMA_VERSION || marking;
        let statement = if writing { "BEGIN IMMEDIATE" } else { "BEGIN" };
        let clock = &self.clock;
        let mut migrated_from = None;
        let mut record_sql = None;
        let connection = self.connection.as_ref().expect("opened above");
        begin(connection, statement, |connection| {
            let version = integer(connection, "PRAGMA user_version", &[])?;
            let found = tables(connection)?;
            if found.is_empty() && version == 0 {
                if was_present {
                    return Err(Error::store(
                        "Existing state is empty or uninitialized; refusing to reset",
                    ));
                }
                create_schema(connection)?;
            } else if version > SCHEMA_VERSION {
                if readable_from(connection, version)? > SCHEMA_VERSION {
                    return Err(newer());
                }
                if !table_set(TABLES_V4).is_subset(&found) {
                    return Err(Error::store("Unsupported or malformed state schema"));
                }
            } else if (1..SCHEMA_VERSION).contains(&version) {
                if !migrate_allowed {
                    return Err(pending());
                }
                migrated_from = Some(version);
                migrate(connection, version, clock.as_ref())?;
            } else if version != SCHEMA_VERSION || found != table_set(TABLES_V4) {
                return Err(Error::store("Unsupported or malformed state schema"));
            }
            let current = integer(connection, "PRAGMA user_version", &[])?;
            let newer = current > SCHEMA_VERSION;
            validate_schema(connection, newer)?;
            let records = if newer {
                record_select()
            } else {
                "SELECT * FROM interruptions".to_string()
            };
            if newer {
                record_sql = Some(records.clone());
            }
            if writing && current == SCHEMA_VERSION && !marked(connection)? {
                write_mark(connection)?;
            }
            read_settings(connection)?;
            if check || migrated_from.is_some() {
                if integer_text(connection, "PRAGMA quick_check")? != "ok" {
                    return Err(Error::store("State integrity check failed"));
                }
                for row in rows(
                    connection,
                    "SELECT thread_id, enabled, tier FROM threads",
                    &[],
                )? {
                    uuid(get(&row, "thread_id"), "thread_id")?;
                    flag(get(&row, "enabled"), "thread enabled")?;
                    validated_tier(get(&row, "tier"))?;
                }
                for row in rows(connection, &records, &[])? {
                    validated_record(row)?;
                }
                let notices = if newer {
                    notice_select()
                } else {
                    "SELECT * FROM notices".to_string()
                };
                for row in rows(connection, &notices, &[])? {
                    validated_notice(row)?;
                }
            }
            Ok(())
        })?;
        self.migrated_from = migrated_from;
        if let Some(sql) = record_sql {
            self.record_sql = sql;
        }
        Ok(())
    }

    /// `close()`.
    pub fn close(&mut self) {
        self.connection = None;
    }

    pub(crate) fn connection(&self) -> &Connection {
        self.connection.as_ref().expect("an open store")
    }

    fn open_connection(&self) -> Result<&Connection> {
        self.connection
            .as_ref()
            .ok_or_else(|| Error::store("Store is closed"))
    }

    /// `_transaction()`: a write transaction, taken before anything that might change a row.
    pub(crate) fn transaction<T>(&self, body: impl FnOnce(&Connection) -> Result<T>) -> Result<T> {
        begin(self.open_connection()?, "BEGIN IMMEDIATE", body)
    }

    /// `_read()`: one consistent snapshot, without blocking writers.
    pub(crate) fn read<T>(&self, body: impl FnOnce(&Connection) -> Result<T>) -> Result<T> {
        begin(self.open_connection()?, "BEGIN", body)
    }

    /// `_row(connection, interruption_id)`.
    pub(crate) fn row(
        &self,
        connection: &Connection,
        interruption_id: &str,
    ) -> Result<Option<Row>> {
        let found = rows(
            connection,
            &format!("{} WHERE interruption_id=?", self.record_sql),
            &[string(interruption_id)],
        )?;
        found.into_iter().next().map(validated_record).transpose()
    }

    /// Every record the query (after the record select) gives, validated.
    pub(crate) fn records(
        &self,
        connection: &Connection,
        rest: &str,
        parameters: &[Value],
    ) -> Result<Vec<Row>> {
        rows(
            connection,
            &format!("{}{rest}", self.record_sql),
            parameters,
        )?
        .into_iter()
        .map(validated_record)
        .collect()
    }

    /// `_now(at)`.
    pub(crate) fn now(&self, at: Option<f64>) -> Result<f64> {
        let at = at.unwrap_or_else(|| (self.clock)());
        timestamp(&Value::Float(at), "now", false)?;
        Ok(at)
    }

    /// `_forensic_copy(version)`: a copy of the old state taken before any schema change. Forensic only,
    /// never a restore path.
    fn forensic_copy(&self, version: i64) -> Result<()> {
        let target = self.state_dir.join(format!(
            "state.v{version}-backup-{}.sqlite",
            utc_stamp(wall_clock())
        ));
        if target.exists() {
            return Ok(());
        }
        let target = target.to_string_lossy().into_owned();
        execute(self.connection(), "VACUUM INTO ?", &[string(&target)])
            .map_err(|_| Error::store("Cannot take a copy of the state before upgrading it"))?;
        Ok(())
    }

    /// One PRAGMA's value on this store's own connection (`store._connection.execute("PRAGMA name")`), read
    /// only: how the differential harness holds the connection's settings to Python's.
    pub fn pragma(&self, name: &str) -> Result<Value> {
        if !name
            .bytes()
            .all(|byte| byte.is_ascii_lowercase() || byte == b'_')
        {
            return Err(Error::Python("ValueError", "not a PRAGMA name".into()));
        }
        Ok(crate::value::scalar(
            self.open_connection()?,
            &format!("PRAGMA {name}"),
            &[],
        )?)
    }

    /// `schema_version()`: the schema on disk now.
    pub fn schema_version(&self) -> Result<i64> {
        self.read(|connection| Ok(integer(connection, "PRAGMA user_version", &[])?))
    }

    /// `readable_from()`: the oldest version whose reader may use the state on disk now.
    pub fn readable_from(&self) -> Result<i64> {
        self.read(|connection| {
            let version = integer(connection, "PRAGMA user_version", &[])?;
            Ok(readable_from(connection, version)?)
        })
    }
}

fn newer() -> Error {
    Error::Store(
        Kind::StateFromNewerVersion,
        "This state was written by a newer version of codex-auto-resume".into(),
    )
}

fn pending() -> Error {
    Error::Store(
        Kind::UpgradePending,
        "Upgrade pending: an older watcher still owns the state".into(),
    )
}

fn integer_text(connection: &Connection, sql: &str) -> Result<String> {
    Ok(match crate::value::scalar(connection, sql, &[])? {
        Value::Str(found) => found.as_str().unwrap_or_default().to_string(),
        _ => String::new(),
    })
}

/// Rolls back the open transaction when a panic unwinds through `begin` (D15 catches panics at the thread, and a
/// Store that outlives one must not keep its transaction and its RESERVED lock, as Python, whose `except Exception`
/// always rolls back, never does).
struct RollbackOnUnwind<'a>(&'a Connection);

impl Drop for RollbackOnUnwind<'_> {
    fn drop(&mut self) {
        if std::thread::panicking() && !self.0.is_autocommit() {
            let _ = self.0.execute_batch("ROLLBACK");
        }
    }
}

/// `_begin(statement)`: the statement, the body, COMMIT; on any error ROLLBACK where a transaction is open,
/// and SQLite's own error as `StoreError("State transaction failed")`. A panic in the body rolls back too.
pub(crate) fn begin<T>(
    connection: &Connection,
    statement: &str,
    body: impl FnOnce(&Connection) -> Result<T>,
) -> Result<T> {
    let _guard = RollbackOnUnwind(connection);
    let outcome = (|| {
        execute(connection, statement, &[])?;
        let value = body(connection)?;
        execute(connection, "COMMIT", &[])?;
        Ok(value)
    })();
    match outcome {
        Ok(value) => Ok(value),
        Err(error) => {
            if !connection.is_autocommit() {
                execute(connection, "ROLLBACK", &[])
                    .map_err(|_| Error::store("State transaction failed"))?;
            }
            match error {
                Error::Sqlite(_) => Err(Error::store("State transaction failed")),
                other => Err(other),
            }
        }
    }
}

/// `_read_settings(connection)`: the one settings row, checked. An older watcher's state has no
/// `observe_only`, and nothing there is only observed.
pub(crate) fn read_settings(connection: &Connection) -> Result<Row> {
    let found = rows(connection, "SELECT * FROM settings", &[])?;
    if found.len() != 1 || !crate::value::py_eq(get(&found[0], "singleton"), &crate::value::int(1))
    {
        return Err(Error::store("Invalid settings"));
    }
    let row = &found[0];
    let enabled = flag(get(row, "enabled"), "enabled")?;
    timestamp(get(row, "armed_at"), "armed_at", false)?;
    let armed_at = get(row, "armed_at").clone();
    let poll = crate::validate::integer(get(row, "poll_seconds"), "poll_seconds")?;
    if !(5..=3600).contains(&poll)
        || (enabled && crate::value::py_eq(&armed_at, &crate::value::int(0)))
    {
        return Err(Error::store("Invalid settings"));
    }
    let observe_only = flag(
        row.get("observe_only").unwrap_or(&crate::value::int(0)),
        "observe_only",
    )?;
    let mut settings = Row::new();
    settings.insert(crate::value::key("enabled"), Value::Bool(enabled));
    settings.insert(crate::value::key("armed_at"), armed_at);
    settings.insert(crate::value::key("poll_seconds"), crate::value::int(poll));
    settings.insert(crate::value::key("observe_only"), Value::Bool(observe_only));
    Ok(settings)
}

/// `time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(seconds))`.
pub fn utc_stamp(seconds: f64) -> String {
    let whole = seconds.floor() as i64;
    let (days, rest) = (whole.div_euclid(86400), whole.rem_euclid(86400));
    let (year, month, day) = civil(days);
    format!(
        "{year:04}{month:02}{day:02}T{:02}{:02}{:02}Z",
        rest / 3600,
        rest % 3600 / 60,
        rest % 60
    )
}

/// Days since 1970-01-01 as (year, month, day), proleptic Gregorian (Howard Hinnant's `civil_from_days`).
fn civil(days: i64) -> (i64, i64, i64) {
    let z = days + 719_468;
    let era = z.div_euclid(146_097);
    let doe = z.rem_euclid(146_097);
    let yoe = (doe - doe / 1460 + doe / 36524 - doe / 146_096) / 365;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let day = doy - (153 * mp + 2) / 5 + 1;
    let month = if mp < 10 { mp + 3 } else { mp - 9 };
    let year = yoe + era * 400 + i64::from(month <= 2);
    (year, month, day)
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

    #[test]
    fn stamps() {
        assert_eq!(utc_stamp(0.0), "19700101T000000Z");
        assert_eq!(utc_stamp(1_764_000_000.5), "20251124T160000Z");
        assert_eq!(utc_stamp(951_782_400.0), "20000229T000000Z");
    }
}
