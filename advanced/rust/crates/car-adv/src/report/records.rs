//! This PC's own records, read for a compatibility report (`report/records.py`) - and never written, migrated or
//! locked.
//!
//! The same files codex-compat-reporter 1.5.0 reads, read the same way, so that the two write the same report of the
//! same records (`advanced/tests/test_advanced_report_records.py` holds them to what 1.5.0 wrote, through the six
//! goldens): the state (`reading::state`), the spend ledger's `interruption_id` and `at`, its count, its oldest unit
//! and how many units SQLite ever gave it, the logs, the watcher's own report (a seam, [`WatcherView`]) and Codex's
//! history, for counts alone.
//!
//! Never through the Store: each database is opened `mode=ro`, with `query_only` on, `trusted_schema` off and a
//! three-second timeout, so nothing is written beside it and nothing is migrated. A link, a reparse point or a path out
//! of the home is refused. A schema newer than this reads is refused, not read as today's. A refusal is one closed code
//! ([`Refused`]) and nothing else: never an id, a path, a login or text.

use std::path::Path;
use std::sync::Arc;

use car_codex::LocalSource;
use car_codex::paths::{child, newest_generation, parent_of, safe_path};
use car_config::Paths;
use car_config::winpath;
use car_machine::domain::ids;
use car_machine::json::{Map, Str, Value};
use car_machine::localclock::LocalClock;
use car_policy::settings::os::Os;

use super::evidence::{self, Paid, Reach};
use super::reading::{
    self, LEDGER_NEWER, LEDGER_UNREADABLE, NO_ENGINE_VERSION, Refused, STATE_BUSY,
    TOO_MANY_RECORDS, VERSION_INVALID, WatcherView,
};
use crate::state::journal::{EVENT_LIMIT, EVENT_MAX_AGE};
use crate::state::schema::{FILE_NAME, SCHEMA_VERSION, readable_from};

/// `SPEND`: the spend ledger's columns read, and nothing else.
const SPEND: &[&str] = &["interruption_id", "at"];
/// The one question asked of Codex's history: how many items of each kind one turn made.
const PROGRESS_SQL: &str = "SELECT item_type, count(*) FROM thread_items WHERE thread_id=? AND turn_id=? GROUP BY item_type";

/// `HistoryRead`: what became of Codex's history, which only the progress counts need.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum HistoryRead {
    Read,
    Absent,
    Unreadable,
}

impl HistoryRead {
    pub fn word(self) -> &'static str {
        match self {
            HistoryRead::Read => "read",
            HistoryRead::Absent => "absent",
            HistoryRead::Unreadable => "unreadable",
        }
    }
}

/// What a read asks of the machine it runs on, each replaceable: Windows' answers about paths (`os`), the local clock
/// the log's times are read back with, and the watcher's own report as a reader takes it (`watcher`, S3.3's reader).
pub struct World<'a> {
    pub os: Arc<dyn Os + Send + Sync>,
    pub clock: &'a dyn LocalClock,
    pub watcher: &'a dyn WatcherView,
}

/// `ledger(paths, now)`: (the ledger's schema or None, what was paid, the reach): `paid` is `{interruption id: the
/// claim times a feature paid a unit at}`, and the reach the earliest claim the ledger can still tell. None, {} and
/// "every claim" where there is no ledger - every installation nothing was ever armed on.
pub fn ledger(paths: &Paths, now: f64) -> Result<(Option<i64>, Paid, Reach), Refused> {
    let path = Path::new(&paths.advanced_dir).join(FILE_NAME);
    if !reading::present(paths, &path, LEDGER_UNREADABLE)? {
        return Ok((None, Paid::new(), Reach::All));
    }
    let failed = |error: &rusqlite::Error| {
        Refused::Code(if reading::busy(error) {
            STATE_BUSY
        } else {
            LEDGER_UNREADABLE
        })
    };
    let inside = || -> Result<Result<(i64, Paid, Reach), Refused>, rusqlite::Error> {
        let db = reading::readonly(&path)?;
        let found: i64 = db.query_row("PRAGMA user_version", [], |row| row.get(0))?;
        // A newer ledger is read where it is marked readable from this version (v0.6.17): its spend columns are checked
        // below either way.
        if found > SCHEMA_VERSION {
            let readable = readable_from(&db, found).map_err(|error| match error {
                crate::state::Error::Sqlite(error) => error,
                _ => rusqlite::Error::InvalidQuery,
            })?;
            if readable > SCHEMA_VERSION {
                return Ok(Err(Refused::Code(LEDGER_NEWER)));
            }
        }
        if found < 1 {
            return Ok(Err(Refused::Code(LEDGER_UNREADABLE)));
        }
        let mut statement = db.prepare("PRAGMA table_info(spend)")?;
        let present: Vec<String> = statement
            .query_map([], |row| row.get::<_, String>(1))?
            .collect::<rusqlite::Result<_>>()?;
        drop(statement);
        if !SPEND
            .iter()
            .all(|name| present.iter().any(|each| each == name))
        {
            return Ok(Err(Refused::Code(LEDGER_UNREADABLE)));
        }
        let mut paid = Paid::new();
        let mut statement = db.prepare(&format!(
            "SELECT {} FROM spend WHERE interruption_id IS NOT NULL",
            SPEND.join(", ")
        ))?;
        let rows: Vec<(Value, Value)> = statement
            .query_map([], |row| {
                Ok((
                    reading::column(row.get_ref(0)?, "interruption_id")?,
                    reading::column(row.get_ref(1)?, "at")?,
                ))
            })?
            .collect::<rusqlite::Result<_>>()?;
        drop(statement);
        for (key, at) in rows {
            if let Value::Str(key) = &key
                && let Some(key) = key.as_str()
                && let Some(when) = evidence::moment(&at)
            {
                paid.entry(key.to_owned()).or_default().push(when);
            }
        }
        let (units, oldest): (i64, Value) =
            db.query_row("SELECT count(*), min(at) FROM spend", [], |row| {
                Ok((row.get(0)?, reading::column(row.get_ref(1)?, "at")?))
            })?;
        let sequences: i64 = db.query_row(
            "SELECT count(*) FROM sqlite_master WHERE type = 'table' AND name = 'sqlite_sequence'",
            [],
            |row| row.get(0),
        )?;
        // How many units SQLite ever gave the table; null when it keeps no count.
        let given = if sequences != 0 {
            let top: Option<i64> = db.query_row(
                "SELECT max(seq) FROM sqlite_sequence WHERE name = 'spend'",
                [],
                |row| row.get(0),
            )?;
            Value::from(top.unwrap_or(0))
        } else {
            Value::Null
        };
        let reach = evidence::ledger_reach(units, &oldest, &given, now, EVENT_MAX_AGE, EVENT_LIMIT);
        Ok(Ok((found, paid, reach)))
    };
    match inside() {
        Ok(Ok((found, paid, reach))) => Ok((Some(found), paid, reach)),
        Ok(Err(refused)) => Err(refused),
        Err(error) => Err(failed(&error)),
    }
}

/// `_counts(db, row)`: how many items of each of the four kinds one record's recovered turn made, or None.
fn counts(db: &rusqlite::Connection, row: &Map) -> Option<Map> {
    let thread = row.get("thread_id")?;
    let turn = row.get("recovery_turn_id")?;
    if !ids::is_uuid(thread) || !ids::is_uuid(turn) {
        return None;
    }
    let (Value::Str(thread), Value::Str(turn)) = (thread, turn) else {
        return None;
    };
    let (thread, turn) = (thread.as_str()?, turn.as_str()?);
    let mut statement = db.prepare(PROGRESS_SQL).ok()?;
    let found: Vec<(Value, Value)> = statement
        .query_map([thread, turn], |each| {
            Ok((
                reading::column(each.get_ref(0)?, "item_type")?,
                reading::column(each.get_ref(1)?, "count")?,
            ))
        })
        .ok()?
        .collect::<rusqlite::Result<_>>()
        .ok()?;
    let mut counted = Map::new();
    for kind in evidence::PROGRESS {
        let many = found
            .iter()
            .find(|(name, _)| matches!(name, Value::Str(text) if text.as_str() == Some(kind)))
            .map_or_else(|| Value::from(0), |(_, many)| many.clone());
        counted.insert(Str::from(*kind), many);
    }
    Some(counted)
}

/// `progress(codex_home, rows)`: (what became of the history, each row's counts or None): how many items of each of the
/// four kinds the row's recovered turn made, read through core's read-only opener, which reads the newest generation
/// only and refuses one whose schema moved. The one question that passes over a conversation: SQLite reads that turn's
/// rows to count them, and only the counts come back.
pub fn progress(
    os: &Arc<dyn Os + Send + Sync>,
    codex_home: &Path,
    rows: &[Map],
) -> (HistoryRead, Vec<Option<Map>>) {
    let nothing = || vec![None; rows.len()];
    let source = match LocalSource::new(Arc::clone(os), &codex_home.to_string_lossy(), None) {
        Ok(source) => source,
        Err(_) => return (HistoryRead::Unreadable, nothing()),
    };
    match newest_generation(os.as_ref(), &source.home, "history") {
        Ok(None) => return (HistoryRead::Absent, nothing()),
        Ok(Some(_)) => {}
        Err(car_codex::Error::Os) => {
            // `FileNotFoundError` (the home is not there) is the one OSError that says the history is absent.
            return match std::fs::read_dir(&source.home) {
                Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
                    (HistoryRead::Absent, nothing())
                }
                _ => (HistoryRead::Unreadable, nothing()),
            };
        }
        Err(_) => return (HistoryRead::Unreadable, nothing()),
    }
    // `source._db("history")`: the newest generation, only if its schema is supported, opened read-only.
    let opened = (|| -> Result<rusqlite::Connection, ()> {
        let name = source.resolve("history").map_err(|_| ())?;
        let path = safe_path(os.as_ref(), &child(&source.home, &name)).map_err(|_| ())?;
        if !winpath::same_path(&parent_of(&path), &source.home) {
            return Err(());
        }
        car_codex::sql::connect(Path::new(&path)).map_err(|_| ())
    })();
    match opened {
        Ok(db) => (
            HistoryRead::Read,
            rows.iter().map(|row| counts(&db, row)).collect(),
        ),
        Err(()) => (HistoryRead::Unreadable, nothing()),
    }
}

/// What `read` found.
pub struct Found {
    pub state_schema: i64,
    pub ledger_schema: Option<i64>,
    pub history: HistoryRead,
    pub paused: Option<bool>,
    pub current: String,
    pub source: &'static str,
    pub hidden: i64,
    pub another_route: i64,
    pub beyond_reach: i64,
    pub elsewhere: i64,
    pub unplaced: Vec<(&'static str, i64)>,
    pub body: Value,
}

impl Found {
    /// The reference's answer, as the dict it is.
    pub fn value(&self) -> Value {
        fn object(pairs: Vec<(&str, Value)>) -> Value {
            let mut map = Map::new();
            for (name, value) in pairs {
                map.insert(Str::from(name), value);
            }
            Value::Object(map)
        }
        let mut codes = Map::new();
        for code in evidence::UNPLACED {
            let many = self
                .unplaced
                .iter()
                .find(|(each, _)| each == code)
                .map_or(0, |each| each.1);
            codes.insert(Str::from(*code), Value::from(many));
        }
        object(vec![
            (
                "read",
                object(vec![
                    ("state_schema", Value::from(self.state_schema)),
                    (
                        "ledger_schema",
                        self.ledger_schema.map_or(Value::Null, Value::from),
                    ),
                    ("history", Value::from(self.history.word())),
                    ("paused", self.paused.map_or(Value::Null, Value::Bool)),
                ]),
            ),
            (
                "engine",
                object(vec![
                    ("current", Value::from(self.current.as_str())),
                    ("from", Value::from(self.source)),
                ]),
            ),
            (
                "left_out",
                object(vec![
                    ("hidden", Value::from(self.hidden)),
                    ("another_route", Value::from(self.another_route)),
                    ("beyond_reach", Value::from(self.beyond_reach)),
                    ("elsewhere", Value::from(self.elsewhere)),
                    ("unplaced", Value::Object(codes)),
                ]),
            ),
            ("body", self.body.clone()),
        ])
    }
}

/// `read(paths, codex_home, codex_version=None, now=..., view=...)`: what this PC's own records show for one Codex
/// version - `codex_version`, or the one in use now - or the refusal. `now` is the clock the ledger's reach is read at;
/// `view`, where given, stands in for the watcher's report (a seam for the tests). The ledger is read only when there are
/// records for it to tell apart, as 1.5.0 reads it; `ledger_schema` is None where it was not read.
pub fn read(
    paths: &Paths,
    world: &World<'_>,
    codex_home: &Path,
    codex_version: Option<&Value>,
    now: f64,
    view: Option<&dyn WatcherView>,
) -> Result<Found, Refused> {
    let mut asked = None;
    if let Some(version) = codex_version {
        asked = evidence::canonical_version(version);
        if asked.is_none() {
            return Err(Refused::Code(VERSION_INVALID));
        }
    }
    let (state_schema, rows, hidden, paused) = reading::state(paths)?;
    // As 1.5.0's by_route: with no record to tell apart, the ledger is not read, nor refused.
    let (ledger_schema, paid, reach) = if rows.is_empty() {
        (None, Paid::new(), Reach::All)
    } else {
        ledger(paths, now)?
    };
    let (rows, routed, unknown) = evidence::by_route(rows, &paid, reach.bound());
    let lines = reading::log_lines(paths, world.clock);
    let seen = view.unwrap_or(world.watcher).view();
    let (current, source, capabilities) = reading::current_engine(seen.as_ref(), &lines)?;
    let version = match asked {
        Some(asked) => asked,
        None => evidence::canonical_version(&Value::from(current.as_str()))
            .ok_or(Refused::Code(VERSION_INVALID))?,
    };
    let timeline = evidence::engine_timeline(&lines);
    let (placed, elsewhere, unplaced) = evidence::place(&rows, &timeline, &current, &version);
    if placed.len() > evidence::MAX_RECORDS {
        return Err(Refused::Code(TOO_MANY_RECORDS));
    }
    let (history, counted) = progress(&world.os, codex_home, &placed);
    let watcher = if version == current {
        capabilities.as_ref()
    } else {
        None
    };
    let body =
        evidence::body(&version, &placed, &lines, watcher, &counted).map_err(Refused::Raised)?;
    let _ = NO_ENGINE_VERSION;
    Ok(Found {
        state_schema,
        ledger_schema,
        history,
        paused,
        current,
        source,
        hidden,
        another_route: routed,
        beyond_reach: unknown,
        elsewhere,
        unplaced,
        body,
    })
}
