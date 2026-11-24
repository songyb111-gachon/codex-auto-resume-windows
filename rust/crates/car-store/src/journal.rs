//! What happened to a record, written down as it happens, and the pruning that bounds it (store/journal.py).

use car_machine::json::Value;
use rusqlite::Connection;

use crate::errors::Result;
use crate::machine::vocab::{STATES, TERMINAL};
use crate::machine::{actor_code, event_code, has, reason_code};
use crate::session::Store;
use crate::value::{
    Row, float_or_null, get, int, integer, marks, number, optional, rows, string, text, words_but,
};

/// The journal is bounded both ways, and never loses the story of a record still running.
pub const EVENT_LIMIT: i64 = 5000;
pub const EVENT_MAX_AGE: f64 = 90.0 * 86400.0;
pub const PRUNE_EVERY: i64 = 256;

/// One journal entry's fields beside its time and code (`_event`'s keywords).
#[derive(Clone, Debug)]
pub struct Event<'a> {
    pub record: Option<&'a Row>,
    pub from_state: Option<&'a str>,
    pub to_state: Option<&'a str>,
    /// `reason`: None, or any value (a word outside the list is written "other").
    pub reason: Value,
    pub actor: &'a str,
    pub turn_ref: Option<&'a str>,
    pub flags: i64,
    pub value: Option<f64>,
}

impl Default for Event<'_> {
    fn default() -> Self {
        Event {
            record: None,
            from_state: None,
            to_state: None,
            reason: Value::Null,
            actor: "engine",
            turn_ref: None,
            flags: 0,
            value: None,
        }
    }
}

/// `_finite(value, default)`.
pub fn finite(value: Option<f64>, default: Option<f64>) -> Option<f64> {
    match value {
        Some(value) if value.is_finite() => Some(value),
        _ => default,
    }
}

/// `_finite(value)` of a Python value: a finite int or float as a float, else `default`.
pub fn finite_value(value: &Value, default: Option<f64>) -> Option<f64> {
    match value {
        Value::Int(_) | Value::Float(_) => finite(number(value), default),
        _ => default,
    }
}

/// `_event(connection, at, code, ...)`: one content-free entry inside the caller's transaction. An unknown
/// code or reason is stored as "other"; a journal entry is never why a state change fails to commit.
pub fn event(connection: &Connection, at: f64, code: &str, entry: Event<'_>) -> Result<()> {
    let state = |value: Option<&str>| optional(value.filter(|state| has(STATES, state)));
    let flags = if (0..1 << 31).contains(&entry.flags) {
        entry.flags
    } else {
        0
    };
    let parameters = [
        Value::Float(finite(Some(at), Some(0.0)).unwrap_or(0.0)),
        entry
            .record
            .map_or(Value::Null, |record| get(record, "interruption_id").clone()),
        entry
            .record
            .map_or(Value::Null, |record| get(record, "chain_origin_id").clone()),
        string(&event_code(code)),
        state(entry.from_state),
        state(entry.to_state),
        optional(reason_code(&entry.reason).as_deref()),
        string(&actor_code(entry.actor)),
        optional(
            entry
                .turn_ref
                .filter(|turn| matches!(*turn, "recovery" | "failed")),
        ),
        int(flags),
        float_or_null(finite(entry.value, None)),
    ];
    crate::value::execute(
        connection,
        "INSERT INTO events (at, interruption_id, chain_origin_id, code, from_state, to_state, reason, actor, turn_ref, flags, value) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        &parameters,
    )?;
    let event_id = integer(connection, "SELECT last_insert_rowid()", &[])?;
    if event_id % PRUNE_EVERY == 0 {
        prune(connection, at)?;
    }
    Ok(())
}

/// `_prune(connection, now)`.
fn prune(connection: &Connection, now: f64) -> Result<()> {
    let running = words_but(STATES, TERMINAL);
    let keep = format!(
        "interruption_id IS NOT NULL AND interruption_id IN (SELECT interruption_id FROM interruptions WHERE state IN ({}))",
        marks(running.len())
    );
    let mut parameters = vec![Value::Float(
        finite(Some(now), Some(0.0)).unwrap_or(0.0) - EVENT_MAX_AGE,
    )];
    parameters.extend(running.iter().cloned());
    crate::value::execute(
        connection,
        &format!("DELETE FROM events WHERE at < ? AND NOT ({keep})"),
        &parameters,
    )?;
    let excess = integer(connection, "SELECT count(*) FROM events", &[])? - EVENT_LIMIT;
    if excess > 0 {
        let mut parameters = running.clone();
        parameters.push(int(excess));
        crate::value::execute(
            connection,
            &format!(
                "DELETE FROM events WHERE event_id IN (SELECT event_id FROM events WHERE NOT ({keep}) ORDER BY event_id LIMIT ?)"
            ),
            &parameters,
        )?;
    }
    Ok(())
}

/// One entry as `events()` gives it.
fn coerced(row: &Row) -> Row {
    let key = get(row, "interruption_id");
    let state = |name: &str| {
        let value = get(row, name);
        if crate::value::is_in(value, STATES) {
            value.clone()
        } else {
            Value::Null
        }
    };
    let turn = get(row, "turn_ref");
    let flags = match get(row, "flags") {
        Value::Int(flags) => Value::Int(flags.clone()),
        _ => int(0),
    };
    let mut out = Row::new();
    let mut put = |name: &str, value: Value| {
        out.insert(crate::value::key(name), value);
    };
    put(
        "event_id",
        match get(row, "event_id") {
            Value::Int(id) => Value::Int(id.clone()),
            _ => Value::Null,
        },
    );
    put(
        "at",
        Value::Float(finite_value(get(row, "at"), Some(0.0)).unwrap_or(0.0)),
    );
    put(
        "interruption_id",
        if crate::machine::ids::is_interruption_id(key, true) {
            key.clone()
        } else {
            Value::Null
        },
    );
    put(
        "code",
        string(&match get(row, "code") {
            Value::Str(code) => event_code(code.as_str().unwrap_or("")),
            _ => "other".to_owned(),
        }),
    );
    put("from_state", state("from_state"));
    put("to_state", state("to_state"));
    put(
        "reason",
        optional(reason_code(get(row, "reason")).as_deref()),
    );
    put(
        "actor",
        string(&match text(get(row, "actor")) {
            Some(actor) => actor_code(actor),
            None => "engine".to_owned(),
        }),
    );
    put(
        "turn_ref",
        if matches!(text(turn), Some("recovery" | "failed")) {
            turn.clone()
        } else {
            Value::Null
        },
    );
    put("flags", flags);
    put(
        "value",
        float_or_null(finite_value(get(row, "value"), None)),
    );
    out
}

impl Store {
    /// `events(interruption_id=None, chain_origin_id=None, limit=500)`: journal entries, oldest first, each
    /// coerced to the vocabulary - never trusted, never a failed read.
    pub fn events(
        &self,
        interruption_id: Option<&str>,
        chain_origin_id: Option<&str>,
        limit: i64,
    ) -> Result<Vec<Row>> {
        let limit = limit.clamp(1, EVENT_LIMIT);
        let (filter, mut parameters) = match (interruption_id, chain_origin_id) {
            (Some(key), _) => ("WHERE interruption_id=?", vec![string(key)]),
            (None, Some(origin)) => ("WHERE chain_origin_id=?", vec![string(origin)]),
            _ => ("", Vec::new()),
        };
        parameters.push(int(limit));
        let found = self.read(|connection| {
            Ok(rows(
                connection,
                &format!("SELECT * FROM (SELECT * FROM events {filter} ORDER BY event_id DESC LIMIT ?) ORDER BY event_id"),
                &parameters,
            )?)
        })?;
        Ok(found.iter().map(coerced).collect())
    }

    /// `usage_checks_shown(since)`: what the last usage reading a person asked for said of each record.
    pub fn usage_checks_shown(&self, since: f64) -> Result<Row> {
        let found = self.read(|connection| {
            Ok(crate::value::tuples(
                connection,
                "SELECT interruption_id, at, reason, flags, value FROM events WHERE event_id IN (SELECT max(event_id) FROM events WHERE code='usage_checked' AND interruption_id IS NOT NULL AND at >= ? GROUP BY interruption_id)",
                &[Value::Float(finite(Some(since), Some(0.0)).unwrap_or(0.0))],
            )?)
        })?;
        let mut shown = Row::new();
        for row in found {
            let [key, at, reason, flags, value] =
                <[Value; 5]>::try_from(row).expect("five columns");
            let flags = match flags {
                Value::Int(flags) => flags.as_i64().unwrap_or(0),
                _ => 0,
            };
            let (read, why) = if flags & 2 != 0 {
                let index = match number(&value) {
                    Some(index)
                        if (0.0..crate::schedule::NOT_CHECKED.len() as f64).contains(&index) =>
                    {
                        index as usize
                    }
                    _ => crate::schedule::NOT_CHECKED.len() - 1,
                };
                ("not_checked", string(crate::schedule::NOT_CHECKED[index]))
            } else {
                let read = match &reason {
                    Value::Null => "available",
                    other if text(other) == Some("usage_unavailable") => "still_limited",
                    _ => "unknown",
                };
                (read, Value::Null)
            };
            let source = if flags & crate::schedule::USAGE_RESCAN_FLAG != 0 {
                crate::schedule::USAGE_BY_RESCAN
            } else {
                crate::schedule::USAGE_BY_RETRY
            };
            let mut entry = Row::new();
            entry.insert(
                crate::value::key("at"),
                Value::Float(finite_value(&at, Some(0.0)).unwrap_or(0.0)),
            );
            entry.insert(crate::value::key("read"), string(read));
            entry.insert(crate::value::key("lifted"), Value::Bool(flags & 1 != 0));
            entry.insert(crate::value::key("why"), why);
            entry.insert(crate::value::key("source"), string(source));
            let name = match key {
                Value::Str(name) => name,
                _ => continue,
            };
            shown.insert(name, Value::Object(entry));
        }
        Ok(shown)
    }
}
