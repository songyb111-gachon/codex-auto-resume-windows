//! Putting the state back for an older release: schema 4 for v0.6.11 to v0.6.14, schema 3 for v0.6.0 to
//! v0.6.10, schema 2 for v0.5 (store/downgrade.py). Asked for by hand, never done on its own.
//!
//! Opened as Python opens it - `timeout=10`, `trusted_schema=OFF`, `foreign_keys` OFF (Python's default) -
//! and done in one `BEGIN IMMEDIATE` transaction after a forensic copy.

use std::collections::BTreeSet;
use std::path::Path;

use car_machine::json::Value;
use rusqlite::Connection;

use crate::columns::{SCHEMA_4_COLUMNS, SCHEMA_5_COLUMNS, V2_COLUMNS};
use crate::errors::{Error, Result};
use crate::machine::ids;
use crate::machine::vocab::{CLAIMED, IN_FLIGHT, OBSERVING, V2_STATES, WAITING, WATCHED};
use crate::schema::{MARK, TABLES_V4, TABLES_V5, create_interruptions_named, table_set, tables};
use crate::session::{Links, connect, utc_stamp, wall_clock};
use crate::validate::validated_record;
use crate::value::{
    Row, execute, get, int, integer, key, marks, number, rows, set, string, text, text_of, words,
};

/// What each schema-3 state means to a schema-2 reader.
const DOWNGRADE_STATES: &[(&str, &str)] = &[
    ("completed_no_progress", "resumed"),
    ("handed_over", "superseded_by_user"),
    ("outcome_unverified", "resumed"),
    ("recovered", "resumed"),
    ("recovery_turn_failed", "resumed"),
    ("stopped_by_user", "resumed"),
    ("turn_completed", "resumed"),
    ("turn_started", "resumed"),
    ("withdrawn_unconfirmed", "submission_unknown"),
];

pub const TARGETS: &[i64] = &[2, 3, 4];

/// Withdrawal reasons a schema-4 reader does not know, as the one it settles the same way (sorted).
const NEW_WITHDRAWALS: &[(&str, &str)] = &[
    ("not_delivered_on_open", "not_loaded"),
    ("window_ended", "expired"),
];

/// A withdrawal for Observe only, as the Pause's v0.6.10 knows.
const OBSERVE_WITHDRAWALS: &[(&str, &str)] = &[
    ("observe_only", "paused"),
    ("observe_only_unknown", "paused_unknown"),
];

fn observed(value: &Value) -> Option<&'static str> {
    let word = text(value)?;
    OBSERVE_WITHDRAWALS
        .iter()
        .find(|(from, _)| *from == word)
        .map(|(_, to)| *to)
}

/// `downgrade_state(state_dir, target)`: a newer state rewritten as schema `target`; the report.
pub fn downgrade_state(state_dir: &Path, target: i64, links: &dyn Links) -> Result<Row> {
    downgrade_state_at(state_dir, target, wall_clock(), links)
}

/// `downgrade_state` with `time.time()` given: `now` is what a record made final is stamped with.
pub fn downgrade_state_at(
    state_dir: &Path,
    target: i64,
    now: f64,
    links: &dyn Links,
) -> Result<Row> {
    if !TARGETS.contains(&target) {
        return Err(Error::store(
            "A state can be downgraded to schema 4, 3 or 2 only",
        ));
    }
    let path = state_dir.join("state.sqlite");
    if links.is_symlink(state_dir) || links.is_symlink(&path) || !path.is_file() {
        return Err(Error::store("Cannot open valid auto-resume state"));
    }
    let connection = connect(&path)?;
    let outcome = downgrade_open(&connection, state_dir, target, now);
    drop(connection);
    match outcome {
        Err(Error::Sqlite(_)) => Err(Error::store("The state could not be downgraded")),
        other => other,
    }
}

fn downgrade_open(connection: &Connection, state_dir: &Path, target: i64, now: f64) -> Result<Row> {
    execute(connection, "PRAGMA trusted_schema=OFF", &[])?;
    execute(connection, "PRAGMA foreign_keys=OFF", &[])?;
    let version = integer(connection, "PRAGMA user_version", &[])?;
    if (1..=target).contains(&version) {
        let mut report = Row::new();
        report.insert(key("changed"), Value::Bool(false));
        report.insert(key("rows"), Value::Null);
        return Ok(report);
    }
    if !matches!(version, 3..=5) {
        return Err(Error::store(
            "Only a schema-5, schema-4 or schema-3 state can be downgraded",
        ));
    }
    let backup = state_dir.join(format!(
        "state.v{version}-backup-{}.sqlite",
        utc_stamp(wall_clock())
    ));
    execute(
        connection,
        "VACUUM INTO ?",
        &[string(&backup.to_string_lossy())],
    )?;
    execute(connection, "BEGIN IMMEDIATE", &[])?;
    let outcome = (|| -> Result<Row> {
        if integer(connection, "PRAGMA user_version", &[])? != version {
            return Err(Error::store(
                "The state changed while it was being downgraded",
            ));
        }
        let mut report = Row::new();
        report.insert(key("changed"), Value::Bool(true));
        if version == 5 {
            for (name, value) in to_v4(connection, now)? {
                report.insert(name, value);
            }
        }
        if (version == 4 || version == 5) && target <= 3 {
            let fours = count(&report, "made_final");
            for (name, value) in to_v3(connection, now)? {
                report.insert(name, value);
            }
            let total = count(&report, "made_final") + fours;
            set(&mut report, "made_final", int(total));
        }
        let kept = if target == 2 {
            to_v2(connection)?
        } else {
            integer(connection, "SELECT count(*) FROM interruptions", &[])?
        };
        report.insert(key("rows"), int(kept));
        execute(connection, &format!("PRAGMA user_version={target}"), &[])?;
        if integer(connection, "PRAGMA application_id", &[])? & 0xFFFF_0000 == MARK {
            execute(connection, "PRAGMA application_id=0", &[])?;
        }
        execute(connection, "COMMIT", &[])?;
        Ok(report)
    })();
    if outcome.is_err() && !connection.is_autocommit() {
        execute(connection, "ROLLBACK", &[])?;
    }
    outcome
}

fn count(report: &Row, name: &str) -> i64 {
    match get(report, name) {
        Value::Int(found) => found.as_i64().unwrap_or(0),
        _ => 0,
    }
}

/// `downgrade_to_v3(state_dir)`.
pub fn downgrade_to_v3(state_dir: &Path, links: &dyn Links) -> Result<Row> {
    downgrade_state(state_dir, 3, links)
}

/// `downgrade_to_v2(state_dir)`.
pub fn downgrade_to_v2(state_dir: &Path, links: &dyn Links) -> Result<Row> {
    downgrade_state(state_dir, 2, links)
}

/// `_to_v4(connection, now)`: schema 5 as schema 4, inside the caller's transaction.
fn to_v4(connection: &Connection, now: f64) -> Result<Row> {
    if tables(connection)? != table_set(TABLES_V5) {
        return Err(Error::store("Unsupported or malformed state schema"));
    }
    let watched = words(WATCHED);
    if integer(
        connection,
        &format!(
            "SELECT count(*) FROM interruptions WHERE home_key<>'' AND state IN ({})",
            marks(watched.len())
        ),
        &watched,
    )? != 0
    {
        return Err(Error::store(
            "A continuation sent to another Codex home may still be in its queue; let it settle first",
        ));
    }
    let extra = integer(
        connection,
        "SELECT count(*) FROM interruptions WHERE home_key<>''",
        &[],
    )?;
    let mut report = Row::new();
    report.insert(key("made_final"), int(0));
    if extra != 0 {
        report.insert(key("extra_home_rows"), int(extra));
    }
    let (waiting, observing) = (words(WAITING), words(OBSERVING));
    let mut made = 0;
    let mut parameters = vec![Value::Float(now)];
    parameters.extend(waiting.iter().cloned());
    made += execute(
        connection,
        &format!(
            "UPDATE interruptions SET state='cancelled', last_error='home_not_watched', cancel_requested=1, outcome_at=? WHERE home_key<>'' AND state IN ({})",
            marks(waiting.len())
        ),
        &parameters,
    )?;
    let mut parameters = vec![Value::Float(now)];
    parameters.extend(observing.iter().cloned());
    made += execute(
        connection,
        &format!(
            "UPDATE interruptions SET state='outcome_unverified', outcome_at=? WHERE home_key<>'' AND state IN ({})",
            marks(observing.len())
        ),
        &parameters,
    )?;
    set(&mut report, "made_final", int(made as i64));
    for (new, old) in NEW_WITHDRAWALS {
        execute(
            connection,
            "UPDATE interruptions SET withdraw_reason=? WHERE withdraw_reason=?",
            &[string(old), string(new)],
        )?;
    }
    for (table, name, _) in SCHEMA_5_COLUMNS.iter().rev() {
        execute(
            connection,
            &format!("ALTER TABLE {table} DROP COLUMN {name}"),
            &[],
        )?;
    }
    execute(connection, "PRAGMA user_version=4", &[])?;
    Ok(report)
}

/// `_to_v3(connection, now)`: schema 4 as schema 3, inside the caller's transaction.
fn to_v3(connection: &Connection, now: f64) -> Result<Row> {
    if tables(connection)? != table_set(TABLES_V4) {
        return Err(Error::store("Unsupported or malformed state schema"));
    }
    let mut report = Row::new();
    for (name, value) in [
        ("short_markers", int(0)),
        ("made_final", int(0)),
        ("postponed", int(0)),
        ("conversations_off", int(0)),
        ("unfollowed_off", int(0)),
        ("observe_only_paused", Value::Bool(false)),
    ] {
        report.insert(key(name), value);
    }
    let (mut short, mut made, mut postponed) = (0i64, 0i64, 0i64);
    let found: Vec<Row> = rows(connection, "SELECT * FROM interruptions", &[])?
        .into_iter()
        .map(|mut row| {
            set(&mut row, "home_key", string(""));
            validated_record(row)
        })
        .collect::<Result<_>>()?;
    let (mut held, mut unfollowed) = (BTreeSet::new(), BTreeSet::new());
    let thread = |row: &Row| text_of(row, "thread_id").unwrap_or_default().to_string();
    for row in &found {
        let record_key = text_of(row, "interruption_id").unwrap_or_default();
        let state = text_of(row, "state").unwrap_or_default();
        let mut changes: Vec<(&str, Value)> = Vec::new();
        let whole = ids::marker(record_key);
        if text_of(row, "marker") != Some(whole.as_str()) {
            short += 1;
            changes.push(("marker", string(&whole)));
            if WATCHED.contains(&state) {
                unfollowed.insert(thread(row));
            }
            if CLAIMED.contains(&state) || IN_FLIGHT.contains(&state) {
                changes.push(("state", string("submission_unknown")));
                changes.push(("queue_id", Value::Null));
                changes.push(("last_error", string("queue_result_unknown_do_not_resend")));
            } else if OBSERVING.contains(&state) {
                changes.push(("state", string("outcome_unverified")));
                changes.push(("outcome_at", Value::Float(now)));
            } else if state == "submission_unknown" {
                changes.push(("queue_id", Value::Null));
            }
            if changes.iter().any(|(name, _)| *name == "state") {
                made += 1;
            }
        }
        if let Some(word) = observed(get(row, "withdraw_reason")) {
            changes.push(("withdraw_reason", string(word)));
            if let Some(error) = observed(get(row, "last_error"))
                && !changes.iter().any(|(name, _)| *name == "last_error")
            {
                changes.push(("last_error", string(error)));
            }
        }
        if WAITING.contains(&state) {
            let not_before = get(row, "not_before");
            if let (Some(before), Some(next)) =
                (number(not_before), number(get(row, "next_retry_at")))
                && before > next
            {
                changes.push(("next_retry_at", not_before.clone()));
                postponed += 1;
            }
            if !matches!(get(row, "hold"), Value::Null) {
                held.insert(thread(row));
            }
        }
        if !changes.is_empty() {
            changes.sort_by(|a, b| a.0.cmp(b.0));
            let assignments = changes
                .iter()
                .map(|(name, _)| format!("{name}=?"))
                .collect::<Vec<_>>()
                .join(", ");
            let mut values: Vec<Value> = changes.into_iter().map(|(_, value)| value).collect();
            values.push(string(record_key));
            execute(
                connection,
                &format!("UPDATE interruptions SET {assignments} WHERE interruption_id=?"),
                &values,
            )?;
        }
    }
    for row in crate::value::tuples(
        connection,
        "SELECT thread_id FROM threads WHERE tier IS NOT NULL AND tier<>'automatic'",
        &[],
    )? {
        held.insert(text(&row[0]).unwrap_or_default().to_string());
    }
    let every: BTreeSet<&String> = held.iter().chain(unfollowed.iter()).collect();
    for thread in every {
        execute(
            connection,
            "INSERT INTO threads (thread_id, enabled) VALUES (?,0) ON CONFLICT(thread_id) DO UPDATE SET enabled=0",
            &[string(thread)],
        )?;
    }
    set(&mut report, "short_markers", int(short));
    set(&mut report, "made_final", int(made));
    set(&mut report, "postponed", int(postponed));
    set(&mut report, "conversations_off", int(held.len() as i64));
    set(&mut report, "unfollowed_off", int(unfollowed.len() as i64));
    if crate::value::truthy(&crate::value::scalar(
        connection,
        "SELECT observe_only FROM settings WHERE singleton=1",
        &[],
    )?) {
        execute(
            connection,
            "UPDATE settings SET enabled=0 WHERE singleton=1",
            &[],
        )?;
        set(&mut report, "observe_only_paused", Value::Bool(true));
    }
    execute(connection, "DROP TABLE notices", &[])?;
    for (table, name, _) in SCHEMA_4_COLUMNS.iter().rev() {
        execute(
            connection,
            &format!("ALTER TABLE {table} DROP COLUMN {name}"),
            &[],
        )?;
    }
    execute(connection, "PRAGMA user_version=3", &[])?;
    Ok(report)
}

/// `_to_v2(connection)`: schema 3 as schema 2, inside the caller's transaction; the rows kept.
fn to_v2(connection: &Connection) -> Result<i64> {
    let mapping = DOWNGRADE_STATES
        .iter()
        .map(|(from, to)| format!("WHEN '{from}' THEN '{to}'"))
        .collect::<Vec<_>>()
        .join(" ");
    let columns = V2_COLUMNS.join(",");
    let selected = V2_COLUMNS
        .iter()
        .map(|name| {
            if *name == "state" {
                format!("CASE state {mapping} ELSE state END")
            } else {
                (*name).to_string()
            }
        })
        .collect::<Vec<_>>()
        .join(",");
    create_interruptions_named(connection, "interruptions_v2")?;
    execute(
        connection,
        &format!("INSERT INTO interruptions_v2 ({columns}) SELECT {selected} FROM interruptions"),
        &[],
    )?;
    let kept = integer(connection, "SELECT count(*) FROM interruptions_v2", &[])?;
    execute(connection, "DROP TABLE interruptions", &[])?;
    execute(connection, "DROP TABLE events", &[])?;
    execute(connection, "DROP TABLE watcher_status", &[])?;
    execute(
        connection,
        "ALTER TABLE interruptions_v2 RENAME TO interruptions",
        &[],
    )?;
    execute(
        connection,
        "CREATE INDEX interruptions_thread ON interruptions(thread_id)",
        &[],
    )?;
    let v2 = words(V2_STATES);
    if integer(
        connection,
        &format!(
            "SELECT count(*) FROM interruptions WHERE state NOT IN ({})",
            marks(v2.len())
        ),
        &v2,
    )? != 0
    {
        return Err(Error::store("A state has no schema-2 meaning"));
    }
    execute(connection, "PRAGMA user_version=2", &[])?;
    Ok(kept)
}
