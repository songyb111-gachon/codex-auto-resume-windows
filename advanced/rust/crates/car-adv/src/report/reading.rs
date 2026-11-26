//! `ownreport/reading.py` (core's, which the advanced report reads through): this PC's own records, read for a
//! compatibility report - never written, migrated or locked. The state is opened read-only (no `-journal`, no folder),
//! `query_only` on, `trusted_schema` off, with a three-second busy timeout; a link, a reparse point or a path out of the
//! home is refused. A refusal is one closed code and nothing else.
//!
//! SEAT S7.3c. As with `evidence.rs`, core's own port of this is car-control's `ownreport::reading` (bridge6), which
//! reads through `Control`. This one takes the home's `Paths` and the three things a `Control` would have given - the
//! local clock, the watcher's report and the reader of a file - as arguments, so the advanced report needs no `Control`.
//! The watcher's report (`compatio.reader_view`, S3.3's) is the seam [`WatcherView`]: a diff hands it in as data,
//! production hands it S3.3's reader.
//!
//! What `read_all` (the Dashboard's every-version report) does is core's and not here: only the functions the advanced
//! reader (`records.py`) imports are - `readonly`, `_present`, `_busy`, `state`, `paused`, `log_names`, `log_lines`,
//! `watcher_view`, `current_engine`, and the closed codes.

use std::path::{Path, PathBuf};
use std::time::Duration;

use car_config::Paths;
use car_machine::json::{Map, Str, Value};
use car_machine::localclock::LocalClock;
use car_machine::pyval;
use rusqlite::types::ValueRef;
use rusqlite::{Connection, OpenFlags};

use super::evidence::{self, Row};

/// `STATE_SCHEMAS`: the state database's `user_version`s read: 3, 4 and 5.
pub const STATE_SCHEMAS: &[i64] = &[3, 4, 5];
/// `COLUMNS`: the columns read from the state, and nothing else.
pub const COLUMNS: &[&str] = &[
    "thread_id",
    "category",
    "state",
    "last_error",
    "detected_at",
    "resumed_at",
    "outcome_at",
    "submitted_at",
    "recovery_turn_id",
    "recovery_turn_status",
    "gate_eval",
    "reset_at",
    "limit_type",
    "history_hidden_at",
    "interruption_id",
    "recovery_client_id",
    "last_claim_at",
];
/// `TIMEOUT`: seconds a database may be busy before it is refused.
pub const TIMEOUT: u64 = 3;
/// `MAX_LOG_BYTES`.
pub const MAX_LOG_BYTES: u64 = 8 * 1024 * 1024;

/// `ReadRefusal`'s words.
pub const NO_STATE: &str = "no_state";
pub const STATE_NEWER: &str = "state_newer";
pub const STATE_OLDER: &str = "state_older";
pub const STATE_UNREADABLE: &str = "state_unreadable";
pub const STATE_BUSY: &str = "state_busy";
pub const LEDGER_NEWER: &str = "ledger_newer";
pub const LEDGER_UNREADABLE: &str = "ledger_unreadable";
pub const NO_ENGINE_VERSION: &str = "no_engine_version";
pub const VERSION_INVALID: &str = "version_invalid";
pub const TOO_MANY_RECORDS: &str = "too_many_records";

/// Why no report could be read (`ReadRefused`), or the class of an exception the reader lets through.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Refused {
    Code(&'static str),
    Raised(&'static str),
}

/// What the watcher's own report is, as a reader takes it (`compatio.reader_view`): the seam S3.3 fills. `None`: the
/// reader could not be had (`watcher_view`'s `except Exception`), which `current_engine` reads as no view.
pub trait WatcherView {
    fn view(&self) -> Option<Value>;
}

impl<F: Fn() -> Option<Value>> WatcherView for F {
    fn view(&self) -> Option<Value> {
        self()
    }
}

fn link(path: &Path) -> bool {
    car_config::paths::is_link(&path.to_string_lossy())
}

/// `_present(paths, path, unreadable)`: whether one of the home's databases is there - false when it is not, true for a
/// plain file inside the home; a link or a reparse point (the file's or its folder's) or a path out of the home is
/// refused with `unreadable`, never followed.
pub fn present(paths: &Paths, path: &Path, unreadable: &'static str) -> Result<bool, Refused> {
    let parent = path.parent().unwrap_or(Path::new(""));
    if link(path) || link(parent) {
        return Err(Refused::Code(unreadable));
    }
    if !path.exists() {
        return Ok(false);
    }
    if !path.is_file() || !paths.confined(&path.to_string_lossy()) {
        return Err(Refused::Code(unreadable));
    }
    Ok(true)
}

/// `readonly(path)`: a SQLite file opened so that nothing can be written to it.
pub fn readonly(path: &Path) -> rusqlite::Result<Connection> {
    let connection = Connection::open_with_flags(
        path,
        OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_NO_MUTEX,
    )?;
    connection.busy_timeout(Duration::from_secs(TIMEOUT))?;
    connection.execute_batch("PRAGMA query_only = ON")?;
    connection.execute_batch("PRAGMA trusted_schema = OFF")?;
    Ok(connection)
}

/// `_busy(error)`: SQLITE_BUSY or SQLITE_LOCKED, or "locked" in the message.
pub fn busy(error: &rusqlite::Error) -> bool {
    if let rusqlite::Error::SqliteFailure(failure, _) = error
        && matches!(failure.extended_code & 0xFF, 5 | 6)
    {
        return true;
    }
    error.to_string().contains("locked")
}

/// A column as Python's sqlite3 hands it: text that is not UTF-8 is an error (it cannot be decoded); a blob is
/// bytes, which no reader here takes as a word or a time - except `gate_eval`, which `json.loads` reads as UTF-8.
pub fn column(value: ValueRef<'_>, name: &str) -> rusqlite::Result<Value> {
    Ok(match value {
        ValueRef::Null => Value::Null,
        ValueRef::Integer(number) => Value::from(number),
        ValueRef::Real(number) => Value::Float(number),
        ValueRef::Text(bytes) => match std::str::from_utf8(bytes) {
            Ok(text) => Value::from(text),
            Err(_) => {
                return Err(rusqlite::Error::InvalidColumnType(
                    0,
                    name.to_owned(),
                    rusqlite::types::Type::Text,
                ));
            }
        },
        ValueRef::Blob(bytes) => match (name, std::str::from_utf8(bytes)) {
            ("gate_eval", Ok(text)) => Value::from(text),
            _ => Value::Array(
                bytes
                    .iter()
                    .map(|byte| Value::from(i64::from(*byte)))
                    .collect(),
            ),
        },
    })
}

/// `_paused(db)`: the switch off, or None when it cannot be read.
fn paused_in(db: &Connection) -> Option<bool> {
    let found: rusqlite::Result<Option<Value>> = db
        .query_row(
            "SELECT enabled FROM settings WHERE singleton = 1",
            [],
            |row| column(row.get_ref(0)?, "enabled"),
        )
        .map(Some)
        .or_else(|error| match error {
            rusqlite::Error::QueryReturnedNoRows => Ok(None),
            other => Err(other),
        });
    match found {
        Ok(Some(Value::Int(int))) => match int.as_i64() {
            Some(0) => Some(true),
            Some(1) => Some(false),
            _ => None,
        },
        // `row[0] not in (0, 1)`: a float 0.0 or 1.0 equals them; the answer is `not row[0]`, a bool.
        Ok(Some(Value::Float(x))) => match x {
            0.0 => Some(true),
            1.0 => Some(false),
            _ => None,
        },
        _ => None,
    }
}

/// What `state` reads: (schema, rows, hidden, paused).
pub type StateRead = (i64, Vec<Row>, i64, Option<bool>);

fn state_file(paths: &Paths) -> PathBuf {
    PathBuf::from(&paths.state_dir).join("state.sqlite")
}

/// `state(paths)`: (schema, rows, hidden, paused): the records not hidden with Clear history that have a time they
/// were found at, as maps of COLUMNS; how many are hidden; and whether recovery is paused.
pub fn state(paths: &Paths) -> Result<StateRead, Refused> {
    let path = state_file(paths);
    if !present(paths, &path, STATE_UNREADABLE)? {
        return Err(Refused::Code(NO_STATE));
    }
    let read = || -> Result<Result<StateRead, Refused>, rusqlite::Error> {
        let db = readonly(&path)?;
        let found: i64 = db.query_row("PRAGMA user_version", [], |row| row.get(0))?;
        if found > *STATE_SCHEMAS.iter().max().unwrap_or(&5) {
            return Ok(Err(Refused::Code(STATE_NEWER)));
        }
        if !STATE_SCHEMAS.contains(&found) {
            return Ok(Err(Refused::Code(STATE_OLDER)));
        }
        let mut statement = db.prepare("PRAGMA table_info(interruptions)")?;
        let present: Vec<String> = statement
            .query_map([], |row| row.get::<_, String>(1))?
            .collect::<rusqlite::Result<_>>()?;
        drop(statement);
        if !COLUMNS
            .iter()
            .all(|name| present.iter().any(|each| each == name))
        {
            return Ok(Err(Refused::Code(STATE_UNREADABLE)));
        }
        let sql = format!(
            "SELECT {} FROM interruptions WHERE history_hidden_at IS NULL",
            COLUMNS.join(", ")
        );
        let mut statement = db.prepare(&sql)?;
        let rows: Vec<Row> = statement
            .query_map([], |row| {
                let mut map = Map::new();
                for (index, name) in COLUMNS.iter().enumerate() {
                    map.insert(Str::from(*name), column(row.get_ref(index)?, name)?);
                }
                Ok(map)
            })?
            .collect::<rusqlite::Result<_>>()?;
        drop(statement);
        let hidden: i64 = db.query_row(
            "SELECT count(*) FROM interruptions WHERE history_hidden_at IS NOT NULL",
            [],
            |row| row.get(0),
        )?;
        let paused = paused_in(&db);
        Ok(Ok((found, rows, hidden, paused)))
    };
    match read() {
        Ok(Ok((found, rows, hidden, paused))) => Ok((
            found,
            rows.into_iter()
                .filter(|row| {
                    evidence::moment(row.get("detected_at").unwrap_or(&Value::Null)).is_some()
                })
                .collect(),
            hidden,
            paused,
        )),
        Ok(Err(refused)) => Err(refused),
        Err(error) => Err(Refused::Code(if busy(&error) {
            STATE_BUSY
        } else {
            STATE_UNREADABLE
        })),
    }
}

/// `paused(paths)`: whether recovery is paused now - the state's switch off - or None where that cannot be told: no
/// state, a link, a damaged file or a switch that is not 0 or 1. Read as the rest is, so nothing is written.
pub fn paused(paths: &Paths) -> Option<bool> {
    let path = state_file(paths);
    if !present(paths, &path, STATE_UNREADABLE).ok()? {
        return None;
    }
    paused_in(&readonly(&path).ok()?)
}

/// `log_names(paths)`: the log and its rotated copies (`logbook.BACKUP_COUNT`), oldest first.
pub fn log_names(paths: &Paths) -> Vec<String> {
    let name = Path::new(&paths.log_file)
        .file_name()
        .map(|each| each.to_string_lossy().into_owned())
        .unwrap_or_default();
    let backups = car_config::logbook::BACKUP_COUNT;
    let mut names: Vec<String> = (1..=backups)
        .rev()
        .map(|number| format!("{name}.{number}"))
        .collect();
    names.push(name);
    names
}

/// `log_lines(paths)`: (time, text) for every line of the logs, oldest first. A copy that is missing, a link, out of
/// the home, unreadable or far larger than the product writes is passed over.
pub fn log_lines(paths: &Paths, clock: &dyn LocalClock) -> Vec<(f64, String)> {
    let mut texts = Vec::new();
    for name in log_names(paths) {
        let path = PathBuf::from(&paths.logs_dir).join(&name);
        if link(&path)
            || !path.is_file()
            || !paths.confined(&path.to_string_lossy())
            || std::fs::metadata(&path).map_or(true, |info| info.len() > MAX_LOG_BYTES)
        {
            continue;
        }
        if let Ok(bytes) = std::fs::read(&path) {
            texts.push(String::from_utf8_lossy(&bytes).into_owned());
        }
    }
    evidence::log_lines(&texts, clock)
}

/// `current_engine(view, lines)`: (version, source, capabilities): the Codex version in use now and where it was
/// read, with the watcher's capabilities when its report says it. A report that is not usable - absent, damaged, stale
/// or about a binary that changed - says nothing, and the last engine line of the log is the version (G7).
pub fn current_engine(
    view: Option<&Value>,
    lines: &[(f64, String)],
) -> Result<(String, &'static str, Option<Value>), Refused> {
    if let Some(Value::Object(view)) = view
        && view
            .get("status")
            .is_some_and(|status| pyval::is(status, "ok"))
    {
        let engine = match view.get("engine") {
            Some(Value::Object(engine)) => engine.clone(),
            _ => Map::new(),
        };
        if let Some(Value::Str(version)) = engine.get("version")
            && let Some(version) = version.as_str()
            && !car_machine::pytext::strip(version).is_empty()
            && evidence::version_matches(&evidence::full(version))
        {
            let capabilities = match view.get("capabilities") {
                Some(Value::Object(found)) => Value::Object(found.clone()),
                _ => Value::Object(Map::new()),
            };
            return Ok((
                evidence::full(version),
                "watcher_report",
                Some(capabilities),
            ));
        }
    }
    match evidence::latest_engine(lines) {
        Some(version) => Ok((version, "log", None)),
        None => Err(Refused::Code(NO_ENGINE_VERSION)),
    }
}
