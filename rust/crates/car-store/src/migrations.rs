//! Bringing an older state forward (store/migrations.py).
//!
//! Only a caller holding the watcher's single-instance mutex may run these, and a copy of the file is taken
//! first (`Store::forensic_copy`). An upgraded database ends up the same file as a fresh one.

use rusqlite::Connection;

use crate::columns::{
    SCHEMA_2_COLUMNS, SCHEMA_3_COLUMNS, SCHEMA_4_COLUMNS, SCHEMA_5_COLUMNS, V2_COLUMNS,
    V4_WATCHER_COLUMNS, v3_columns, v4_record_columns,
};
use crate::errors::{Error, Result};
use crate::journal::{Event, event};
use crate::machine::vocab::{STATES, TERMINAL};
use crate::schema::{TABLES_V2, TABLES_V3, TABLES_V4, column_set, table_set, tables};
use crate::value::{execute, integer, marks, words_but};

fn columns_are(connection: &Connection, table: &str, columns: &[&str]) -> Result<bool> {
    Ok(column_set(connection, table)? == table_set(columns))
}

/// `_migrate_1_to_2`: the general-recovery columns on a schema-1 database.
fn migrate_1_to_2(connection: &Connection) -> Result<()> {
    if tables(connection)? != table_set(TABLES_V2) {
        return Err(Error::store("Unsupported or malformed state schema"));
    }
    let found = column_set(connection, "interruptions")?;
    for (name, definition) in SCHEMA_2_COLUMNS {
        if !found.contains(*name) {
            execute(
                connection,
                &format!("ALTER TABLE interruptions ADD COLUMN {name} {definition}"),
                &[],
            )?;
        }
    }
    execute(connection, "PRAGMA user_version=2", &[])?;
    Ok(())
}

/// `_add_schema_3`.
pub fn add_schema_3(connection: &Connection) -> Result<()> {
    let found = column_set(connection, "interruptions")?;
    for (name, definition) in SCHEMA_3_COLUMNS {
        if !found.contains(*name) {
            execute(
                connection,
                &format!("ALTER TABLE interruptions ADD COLUMN {name} {definition}"),
                &[],
            )?;
        }
    }
    execute(
        connection,
        "CREATE TABLE IF NOT EXISTS events (
            event_id INTEGER PRIMARY KEY AUTOINCREMENT,
            at REAL NOT NULL,
            interruption_id TEXT,
            chain_origin_id TEXT,
            code TEXT NOT NULL,
            from_state TEXT,
            to_state TEXT,
            reason TEXT,
            actor TEXT,
            turn_ref TEXT,
            flags INTEGER NOT NULL DEFAULT 0,
            value REAL
        )",
        &[],
    )?;
    execute(
        connection,
        "CREATE INDEX IF NOT EXISTS events_record ON events(interruption_id, at)",
        &[],
    )?;
    execute(
        connection,
        "CREATE TABLE IF NOT EXISTS watcher_status (
            singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
            pid INTEGER,
            session_id TEXT,
            started_at REAL,
            last_tick_at REAL,
            last_tick_ok INTEGER,
            engine_state TEXT,
            code_version TEXT
        )",
        &[],
    )?;
    execute(
        connection,
        "CREATE INDEX IF NOT EXISTS interruptions_thread_turn ON interruptions(thread_id, turn_id)",
        &[],
    )?;
    execute(
        connection,
        "CREATE UNIQUE INDEX IF NOT EXISTS interruptions_recovery_turn ON interruptions(recovery_turn_id) WHERE recovery_turn_id IS NOT NULL",
        &[],
    )?;
    execute(
        connection,
        "CREATE INDEX IF NOT EXISTS interruptions_claims ON interruptions(thread_id, last_claim_at)",
        &[],
    )?;
    execute(
        connection,
        "CREATE INDEX IF NOT EXISTS interruptions_chain ON interruptions(chain_origin_id)",
        &[],
    )?;
    Ok(())
}

/// `_migrate_2_to_3`: the journal, the heartbeat and the chains, with their backfills.
fn migrate_2_to_3(connection: &Connection, now: f64) -> Result<()> {
    if tables(connection)? != table_set(TABLES_V2) {
        return Err(Error::store("Unsupported or malformed state schema"));
    }
    if !columns_are(connection, "interruptions", V2_COLUMNS)? {
        return Err(Error::store("Malformed state schema"));
    }
    add_schema_3(connection)?;
    execute(
        connection,
        "UPDATE interruptions SET chain_origin_id=interruption_id, chain_first_detected_at=detected_at, legacy=CASE WHEN state='resumed' THEN 1 ELSE 0 END, last_claim_at=submitted_at, first_queued_at=CASE WHEN state IN ('queued','resumed') THEN submitted_at END",
        &[],
    )?;
    let count = integer(connection, "SELECT count(*) FROM interruptions", &[])?;
    event(
        connection,
        now,
        "migrated",
        Event {
            value: Some(count as f64),
            ..Event::default()
        },
    )?;
    let pending = words_but(STATES, TERMINAL);
    let disabled = integer(
        connection,
        &format!(
            "SELECT count(DISTINCT t.thread_id) FROM threads t JOIN interruptions i ON i.thread_id=t.thread_id WHERE t.enabled=0 AND i.state IN ({})",
            marks(pending.len())
        ),
        &pending,
    )?;
    if disabled != 0 {
        event(
            connection,
            now,
            "disabled_threads_with_pending",
            Event {
                value: Some(disabled as f64),
                ..Event::default()
            },
        )?;
    }
    execute(connection, "PRAGMA user_version=3", &[])?;
    Ok(())
}

/// `_add_schema_4`.
pub fn add_schema_4(connection: &Connection) -> Result<()> {
    for (table, name, definition) in SCHEMA_4_COLUMNS {
        if !column_set(connection, table)?.contains(*name) {
            execute(
                connection,
                &format!("ALTER TABLE {table} ADD COLUMN {name} {definition}"),
                &[],
            )?;
        }
    }
    execute(
        connection,
        "CREATE TABLE IF NOT EXISTS notices (
            interruption_id TEXT PRIMARY KEY,
            thread_id TEXT NOT NULL,
            category TEXT NOT NULL,
            raised_at REAL NOT NULL,
            seen_at REAL
        )",
        &[],
    )?;
    Ok(())
}

/// `_migrate_3_to_4`.
fn migrate_3_to_4(
    connection: &Connection,
    clock: &dyn Fn() -> f64,
    migrated_from: i64,
) -> Result<()> {
    if tables(connection)? != table_set(TABLES_V3) {
        return Err(Error::store("Unsupported or malformed state schema"));
    }
    let v3 = v3_columns();
    let shapes: [(&str, &[&str]); 3] = [
        ("interruptions", &v3),
        ("threads", &["thread_id", "enabled"]),
        (
            "settings",
            &["singleton", "enabled", "armed_at", "poll_seconds"],
        ),
    ];
    for (table, columns) in shapes {
        if !columns_are(connection, table, columns)? {
            return Err(Error::store("Malformed state schema"));
        }
    }
    add_schema_4(connection)?;
    if migrated_from == 3 {
        let count = integer(connection, "SELECT count(*) FROM interruptions", &[])?;
        event(
            connection,
            clock(),
            "migrated",
            Event {
                value: Some(count as f64),
                ..Event::default()
            },
        )?;
    }
    execute(connection, "PRAGMA user_version=4", &[])?;
    Ok(())
}

/// `_add_schema_5`.
pub fn add_schema_5(connection: &Connection) -> Result<()> {
    for (table, name, definition) in SCHEMA_5_COLUMNS {
        if !column_set(connection, table)?.contains(*name) {
            execute(
                connection,
                &format!("ALTER TABLE {table} ADD COLUMN {name} {definition}"),
                &[],
            )?;
        }
    }
    Ok(())
}

/// `_migrate_4_to_5`.
fn migrate_4_to_5(
    connection: &Connection,
    clock: &dyn Fn() -> f64,
    migrated_from: i64,
) -> Result<()> {
    if tables(connection)? != table_set(TABLES_V4) {
        return Err(Error::store("Unsupported or malformed state schema"));
    }
    let v4 = v4_record_columns();
    let shapes: [(&str, &[&str]); 2] = [
        ("interruptions", &v4),
        ("watcher_status", V4_WATCHER_COLUMNS),
    ];
    for (table, columns) in shapes {
        if !columns_are(connection, table, columns)? {
            return Err(Error::store("Malformed state schema"));
        }
    }
    add_schema_5(connection)?;
    if migrated_from == 4 {
        let count = integer(connection, "SELECT count(*) FROM interruptions", &[])?;
        event(
            connection,
            clock(),
            "migrated",
            Event {
                value: Some(count as f64),
                ..Event::default()
            },
        )?;
    }
    execute(connection, "PRAGMA user_version=5", &[])?;
    Ok(())
}

/// `_migrate(connection, version)`: 1 -> 2 -> 3 -> 4 -> 5, each step checking its source. `clock` is the
/// store's, asked at each step that journals (as `self.clock()` is).
pub fn migrate(connection: &Connection, version: i64, clock: &dyn Fn() -> f64) -> Result<()> {
    let from = version;
    let mut version = version;
    if version == 1 {
        migrate_1_to_2(connection)?;
        version = 2;
    }
    if version == 2 {
        migrate_2_to_3(connection, clock())?;
        version = 3;
    }
    if version == 3 {
        migrate_3_to_4(connection, clock, from)?;
        version = 4;
    }
    if version == 4 {
        migrate_4_to_5(connection, clock, from)?;
    }
    Ok(())
}
