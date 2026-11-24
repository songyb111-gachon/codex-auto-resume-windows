//! The tables, as they are created today, and the readable-from mark (store/schema.py).
//!
//! D13 freezes the schema at 5 through v0.6.27: these statements are byte for byte the Python's, so a
//! state this crate creates is the file `tests/fixtures/schema.json` describes.

use std::collections::BTreeSet;

use rusqlite::Connection;

use crate::columns::{
    EVENT_COLUMNS, NOTICE_COLUMNS, SETTINGS_COLUMNS, THREAD_COLUMNS, record_columns,
    watcher_columns,
};
use crate::errors::{Error, Result};
use crate::migrations::{add_schema_3, add_schema_4, add_schema_5};
use crate::value::{execute, integer, text, tuples};

/// The schema this version writes (D13).
pub const SCHEMA_VERSION: i64 = 5;
/// The oldest version whose reader may use a state this version wrote.
pub const READABLE_FROM: i64 = 5;
/// "CA" in the high half of SQLite's application id.
pub const MARK: i64 = 0x4341_0000;
/// The mark this version writes.
pub const MARK_VALUE: i64 = MARK | (SCHEMA_VERSION << 8) | READABLE_FROM;

pub const TABLES_V2: &[&str] = &["interruptions", "settings", "threads"];
pub const TABLES_V3: &[&str] = &[
    "events",
    "interruptions",
    "settings",
    "threads",
    "watcher_status",
];
pub const TABLES_V4: &[&str] = &[
    "events",
    "interruptions",
    "notices",
    "settings",
    "threads",
    "watcher_status",
];
/// Schema 5 adds two columns and no table.
pub const TABLES_V5: &[&str] = TABLES_V4;

/// The set of the words.
pub fn table_set(names: &[&str]) -> BTreeSet<String> {
    names.iter().map(|name| (*name).to_string()).collect()
}

/// `SessionMixin._tables(connection)`.
pub fn tables(connection: &Connection) -> rusqlite::Result<BTreeSet<String>> {
    Ok(tuples(
        connection,
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'",
        &[],
    )?
    .into_iter()
    .filter_map(|row| text(&row[0]).map(str::to_string))
    .collect())
}

/// `readable_from(connection, version)`: the mark's, where the mark was written for `version`, else `version`.
pub fn readable_from(connection: &Connection, version: i64) -> rusqlite::Result<i64> {
    let found = integer(connection, "PRAGMA application_id", &[])?;
    Ok(
        if found & 0xFFFF_0000 == MARK && (found >> 8) & 0xFF == version {
            found & 0xFF
        } else {
            version
        },
    )
}

/// `marked(connection)`: whether the state carries this version's mark already.
pub fn marked(connection: &Connection) -> rusqlite::Result<bool> {
    Ok(integer(connection, "PRAGMA application_id", &[])? == MARK_VALUE)
}

/// `MARKED`.
pub fn write_mark(connection: &Connection) -> rusqlite::Result<()> {
    execute(
        connection,
        &format!("PRAGMA application_id={MARK_VALUE}"),
        &[],
    )
    .map(|_| ())
}

/// `_create_interruptions_named(connection, name)`: the schema-2 interruptions table, as v0.5 created it.
pub fn create_interruptions_named(connection: &Connection, name: &str) -> Result<()> {
    if name != "interruptions" && name != "interruptions_v2" {
        return Err(Error::store("Invalid table name"));
    }
    let sql = format!(
        "CREATE TABLE {name} (
            interruption_id TEXT PRIMARY KEY,
            thread_id TEXT NOT NULL,
            turn_id TEXT NOT NULL,
            completed_at REAL NOT NULL,
            started_at REAL,
            ordinal INTEGER NOT NULL,
            detected_at REAL NOT NULL,
            reset_at REAL,
            limit_type TEXT,
            uncertain INTEGER NOT NULL CHECK (uncertain IN (0, 1)),
            state TEXT NOT NULL,
            retry_count INTEGER NOT NULL,
            next_retry_at REAL NOT NULL,
            resumed_at REAL,
            last_error TEXT,
            marker TEXT NOT NULL,
            queue_id TEXT,
            submitted_at REAL,
            attempt_count INTEGER NOT NULL,
            cancel_requested INTEGER NOT NULL CHECK (cancel_requested IN (0, 1)),
            category TEXT NOT NULL DEFAULT 'usage_limit',
            recovery_attempts INTEGER NOT NULL DEFAULT 0,
            no_progress_count INTEGER NOT NULL DEFAULT 0
        )"
    );
    execute(connection, &sql, &[])?;
    Ok(())
}

/// `_create_interruptions(connection)`.
fn create_interruptions(connection: &Connection) -> Result<()> {
    create_interruptions_named(connection, "interruptions")?;
    execute(
        connection,
        "CREATE INDEX interruptions_thread ON interruptions(thread_id)",
        &[],
    )?;
    Ok(())
}

/// `_create_schema(connection)`: a fresh state, made the way a migration makes it.
pub fn create_schema(connection: &Connection) -> Result<()> {
    execute(
        connection,
        "CREATE TABLE settings (
            singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
            enabled INTEGER NOT NULL CHECK (enabled IN (0, 1)),
            armed_at REAL NOT NULL,
            poll_seconds INTEGER NOT NULL
        )",
        &[],
    )?;
    execute(connection, "INSERT INTO settings VALUES (1, 0, 0, 30)", &[])?;
    execute(
        connection,
        "CREATE TABLE threads (
            thread_id TEXT PRIMARY KEY,
            enabled INTEGER NOT NULL CHECK (enabled IN (0, 1))
        )",
        &[],
    )?;
    create_interruptions(connection)?;
    add_schema_3(connection)?;
    add_schema_4(connection)?;
    add_schema_5(connection)?;
    execute(connection, "PRAGMA user_version=5", &[])?;
    Ok(())
}

/// `PRAGMA table_info(table)`: (name, pk) of each column, in order.
pub fn table_info(connection: &Connection, table: &str) -> rusqlite::Result<Vec<(String, i64)>> {
    Ok(
        tuples(connection, &format!("PRAGMA table_info({table})"), &[])?
            .into_iter()
            .map(|row| {
                let pk = match &row[5] {
                    car_machine::json::Value::Int(pk) => pk.as_i64().unwrap_or(0),
                    _ => 0,
                };
                (text(&row[1]).unwrap_or_default().to_string(), pk)
            })
            .collect(),
    )
}

/// The column names of a table, as a set.
pub fn column_set(connection: &Connection, table: &str) -> rusqlite::Result<BTreeSet<String>> {
    Ok(table_info(connection, table)?
        .into_iter()
        .map(|(name, _)| name)
        .collect())
}

/// `_validate_schema(connection, newer=...)`: every table exactly as this version makes it - or, in a later
/// version's state marked readable from this one, holding at least this version's columns, first.
pub fn validate_schema(connection: &Connection, newer: bool) -> Result<()> {
    let records = record_columns();
    let watcher = watcher_columns();
    let expected: [(&str, &[&str], &str); 6] = [
        ("settings", SETTINGS_COLUMNS, "singleton"),
        ("threads", THREAD_COLUMNS, "thread_id"),
        ("interruptions", &records, "interruption_id"),
        ("events", EVENT_COLUMNS, "event_id"),
        ("watcher_status", &watcher, "singleton"),
        ("notices", NOTICE_COLUMNS, "interruption_id"),
    ];
    for (table, columns, primary_name) in expected {
        let information = table_info(connection, table)?;
        let found: BTreeSet<&str> = if newer {
            information
                .iter()
                .take(columns.len())
                .map(|(name, _)| name.as_str())
                .collect()
        } else {
            information.iter().map(|(name, _)| name.as_str()).collect()
        };
        if found != columns.iter().copied().collect::<BTreeSet<&str>>() {
            return Err(Error::store("Malformed state schema"));
        }
        let primary: BTreeSet<&str> = information
            .iter()
            .filter(|(_, pk)| *pk == 1)
            .map(|(name, _)| name.as_str())
            .collect();
        if primary != BTreeSet::from([primary_name]) || information.iter().any(|(_, pk)| *pk > 1) {
            return Err(Error::store("Malformed state primary key"));
        }
    }
    if !tuples(
        connection,
        "SELECT 1 FROM sqlite_master WHERE type IN ('trigger', 'view') LIMIT 1",
        &[],
    )?
    .is_empty()
    {
        return Err(Error::store("Unexpected state schema objects"));
    }
    Ok(())
}
