//! `codex/turns.py`: Codex's turn history, read-only - what kinds of item a conversation's latest turn left, which
//! conversations finished a turn lately, which run now, and the statuses of a plan's steps; never what any of it says
//! (seat S7.2c).
//!
//! The file is found as core finds every Codex database (car-codex's `paths::newest_generation`): the newest
//! generation, a link never followed, the columns read required, opened read-only with `query_only` on and
//! `trusted_schema` off ([`connect`], which `lineage`, `threads`, `conversation` and `sessions` share). A conversation
//! Codex split (issue #30) is read as core reads it, through car-codex's `LocalSource` (`turn_chain`, `owner_of`).
//! Anything that goes wrong is `TurnsUnavailable` ([`Failure::Unavailable`]), with the reference's own words; a class
//! the reference does not catch is [`Failure::Raised`].
//!
//! `booted_of(paths)` (the watcher's heartbeat's boot time, read from core's store) is the caller's: [`Turns::running`]
//! takes the boot time as a value.

use std::collections::BTreeMap;
use std::path::Path;
use std::sync::Arc;

use car_codex::errors::Error;
use car_codex::paths::{newest_generation, parent_of, safe_path};
use car_codex::rollout::SPAN;
use car_codex::source::LocalSource;
use car_codex::sql::{self, Cell, Param};
use car_config::winpath;
use car_machine::domain::{ids, states};
use car_machine::json::Value;
use car_policy::settings::os::Os;
use rusqlite::Connection;

pub const LATEST: &str = "SELECT turn_id, status, error_json IS NOT NULL AND error_json NOT IN ('', 'null'), completed_at, final_agent_item_id IS NOT NULL, rollout_ordinal, started_at FROM thread_turns WHERE thread_id=? ORDER BY rollout_ordinal DESC LIMIT 1";
pub const KINDS: &str = "SELECT item_type, count(*) FROM thread_items WHERE thread_id=? AND turn_id=? GROUP BY item_type";
pub const RECENT: &str = "SELECT thread_id FROM thread_turns WHERE status='completed' AND completed_at >= ? GROUP BY thread_id ORDER BY max(completed_at) DESC LIMIT ?";
pub const PLAN_ITEM_TYPE: &str = "plan";
pub const HAS_PLAN: &str = "SELECT EXISTS(SELECT 1 FROM thread_items WHERE thread_id=? AND item_type=?)";
pub const PLAN: &str = "SELECT json_extract(step.value, '$.status') FROM (SELECT item_json FROM thread_items WHERE thread_id=? AND item_type=? ORDER BY rollout_ordinal DESC LIMIT 1) AS newest, json_each(newest.item_json, '$.steps') AS step";
pub const BETWEEN: &str = "SELECT count(*) FROM thread_turns WHERE thread_id=? AND rollout_ordinal > ? AND rollout_ordinal < ?";
pub const RUNNING: &str = "SELECT t.thread_id, t.started_at FROM thread_turns t WHERE t.status='inProgress' AND NOT EXISTS (SELECT 1 FROM thread_turns n WHERE n.thread_id=t.thread_id AND n.rollout_ordinal > t.rollout_ordinal) ORDER BY t.started_at DESC LIMIT ?";
pub const ERROR: &str = "SELECT error_json FROM thread_turns WHERE thread_id=? AND turn_id=?";
pub const STATUS: &str = "SELECT status FROM thread_turns WHERE thread_id=? AND turn_id=?";
pub const STATEMENTS: [&str; 9] = [LATEST, KINDS, RECENT, HAS_PLAN, PLAN, BETWEEN, RUNNING, ERROR, STATUS];
pub const TURN_COLUMNS: &[&str] = &[
    "thread_id",
    "turn_id",
    "status",
    "error_json",
    "completed_at",
    "rollout_ordinal",
    "final_agent_item_id",
    "started_at",
];
pub const ITEM_COLUMNS: &[&str] = &["thread_id", "turn_id", "item_type", "item_json", "rollout_ordinal"];
pub const TURN_STATUSES: [&str; 4] = ["completed", "failed", "interrupted", "inProgress"];
pub const STEP_STATUSES: [&str; 3] = ["pending", "in_progress", "completed"];
pub const UNKNOWN: &str = "unknown";
pub const RECENT_LIMIT: i64 = 50;
pub const KIND_MAX: usize = 64;

/// What a read of Codex's databases ends in when it does not answer.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Failure {
    /// `TurnsUnavailable(reason)` (or the module's own: `GoalsUnavailable`), a static reason.
    Unavailable(String),
    /// A class the reference does not catch there.
    Raised(&'static str),
}

pub type Read<T> = std::result::Result<T, Failure>;

pub fn unavailable(reason: &str) -> Failure {
    Failure::Unavailable(reason.to_owned())
}

/// `str.isalpha()` of a whole text: every code point a letter of Python's Unicode database, and at least one.
pub fn is_alpha(text: &str) -> bool {
    !text.is_empty()
        && text.chars().all(|c| {
            let point = c as u32;
            super::alpha_gen::ALPHA
                .binary_search_by(|&(low, high)| {
                    if point < low {
                        std::cmp::Ordering::Greater
                    } else if point > high {
                        std::cmp::Ordering::Less
                    } else {
                        std::cmp::Ordering::Equal
                    }
                })
                .is_ok()
        })
}

/// A shared handle on car-policy's `Os` (car-codex's `PolicyOs` in the product).
pub type SharedOs = Arc<dyn Os + Send + Sync>;

/// `connect(home, kind, tables)`: a read-only connection to the newest generation of core's `kind` database in the Codex
/// home, its `tables` (`{name: columns}`) required - or TurnsUnavailable.
pub fn connect(os: &dyn Os, home: &str, kind: &str, tables: &[(&str, &[&str])]) -> Read<Connection> {
    let root = safe_path(os, home).map_err(raised)?;
    let path = match newest_generation(os, &root, kind) {
        Ok(path) => path,
        Err(Error::Os) => return Err(unavailable("the Codex home cannot be listed")),
        Err(other) => return Err(raised(other)),
    };
    let Some(path) = path else {
        return Err(Failure::Unavailable(format!("no {kind} database")));
    };
    let path = safe_path(os, &path).map_err(raised)?;
    if !winpath::same_path(&parent_of(&path), &root) {
        return Err(unavailable("the database is outside the Codex home"));
    }
    let cannot = || unavailable("the database cannot be read");
    let connection = sql::connect(Path::new(&path)).map_err(|_| cannot())?;
    for (table, columns) in tables {
        let found = sql::columns(&connection, table).map_err(|_| cannot())?;
        if !columns.iter().all(|column| found.iter().any(|each| each == column)) {
            return Err(Failure::Unavailable(format!("the {table} table has moved on")));
        }
    }
    Ok(connection)
}

/// A car-codex error the reference lets out as its own class.
pub fn raised(error: Error) -> Failure {
    match error {
        Error::Os => Failure::Raised("OSError"),
        Error::Sqlite => Failure::Raised("Error"),
        other => Failure::Raised(other.class()),
    }
}

/// `_kind(value)`: a kind word as Codex spells one, or "other".
pub fn kind_word(cell: &Cell) -> String {
    match cell {
        Cell::Text(text) if (1..=KIND_MAX).contains(&text.chars().count()) && is_alpha(text) => text.clone(),
        _ => "other".to_owned(),
    }
}

/// One turn, as `latest` reads it.
#[derive(Clone, Debug, PartialEq)]
pub struct Turn {
    pub turn_id: String,
    /// completed, failed, interrupted, inProgress - or "other".
    pub status: String,
    pub errored: bool,
    pub completed_at: Option<i64>,
    pub final_agent: bool,
    pub ordinal: i128,
    /// `{item_type: count}` in the order first met.
    pub kinds: Vec<(String, i64)>,
    pub started_at: Option<Value>,
}

/// The turn history of the Codex home `home`.
pub struct Turns {
    pub home: String,
    pub os: SharedOs,
}

fn text_param(text: &str) -> Param<'_> {
    Param::Text(text)
}

/// `(sqlite3.Error, OSError, ValueError)` inside a read: the reason given.
fn caught(reason: &'static str) -> impl Fn(rusqlite::Error) -> Failure {
    move |_| unavailable(reason)
}

impl Turns {
    pub fn new(home: &str, os: SharedOs) -> Turns {
        Turns {
            home: home.to_owned(),
            os,
        }
    }

    fn uuid(value: &Value) -> bool {
        ids::is_uuid(value)
    }

    /// `_core(ask, *arguments)`: `ask` of core's reader of this home. A home whose state database core does not read maps
    /// nothing.
    fn chain(&self, thread_id: &str) -> Read<Vec<String>> {
        let core = LocalSource::new(Arc::clone(&self.os), &self.home, None).map_err(raised)?;
        match core.resolve("state") {
            Ok(_) => {}
            Err(Error::Source(_)) => return Ok(vec![thread_id.to_owned()]),
            Err(other) => return Err(raised(other)),
        }
        core.turn_chain(thread_id).map_err(core_failure)
    }

    fn owner_of(&self, turns_id: &str) -> Read<Option<String>> {
        let core = LocalSource::new(Arc::clone(&self.os), &self.home, None).map_err(raised)?;
        match core.resolve("state") {
            Ok(_) => {}
            Err(Error::Source(_)) => return Ok(None),
            Err(other) => return Err(raised(other)),
        }
        core.owner_of(turns_id).map_err(core_failure)
    }

    fn read<T>(&self, run: impl FnOnce(&Connection) -> Read<T>) -> Read<T> {
        let connection = connect(
            self.os.as_ref(),
            &self.home,
            "history",
            &[("thread_turns", TURN_COLUMNS), ("thread_items", ITEM_COLUMNS)],
        )?;
        run(&connection)
    }

    /// `latest(thread_id)`: the latest turn of the conversation and the kinds of item it left, or none.
    pub fn latest(&self, thread_id: &Value) -> Read<Option<Turn>> {
        if !Self::uuid(thread_id) {
            return Err(unavailable("not a conversation"));
        }
        let thread = thread_id_text(thread_id);
        let chain = self.chain(&thread)?;
        self.read(|connection| {
            let failed = caught("the turn history cannot be read");
            let mut found = None;
            for index in (0..chain.len()).rev() {
                if let Some(row) = sql::first(connection, LATEST, &[text_param(&chain[index])]).map_err(&failed)? {
                    found = Some((index, row));
                    break;
                }
            }
            let Some((index, row)) = found else {
                return Ok(None);
            };
            let turn_id = row.at(0).value();
            let ordinal = match row.at(5) {
                Cell::Int(number) => Some(*number),
                _ => None,
            };
            let (true, Some(ordinal)) = (Self::uuid(&turn_id), ordinal) else {
                return Err(unavailable("a turn of no shape this knows"));
            };
            let turn_id = thread_id_text(&turn_id);
            let mut kinds: Vec<(String, i64)> = Vec::new();
            for each in sql::query(connection, KINDS, &[text_param(&chain[index]), text_param(&turn_id)]).map_err(&failed)? {
                let word = kind_word(each.at(0));
                let count = match each.at(1) {
                    Cell::Int(number) => *number,
                    _ => 0,
                };
                match kinds.iter_mut().find(|(seen, _)| *seen == word) {
                    Some(slot) => slot.1 += count,
                    None => kinds.push((word, count)),
                }
            }
            let status = match row.at(1) {
                Cell::Text(text) if TURN_STATUSES.contains(&text.as_str()) => text.clone(),
                _ => "other".to_owned(),
            };
            let completed = match row.at(3) {
                Cell::Int(number) if *number > 0 => Some(*number),
                _ => None,
            };
            let started = row.at(6).value();
            let (low, high) = states::EPOCH_STORE;
            let started = states::epoch(&started, low, high, false, true)
                .map_err(Failure::Raised)?
                .then_some(started);
            Ok(Some(Turn {
                turn_id,
                status,
                errored: row.at(2).truthy(),
                completed_at: completed,
                final_agent: row.at(4).truthy(),
                ordinal: index as i128 * SPAN + i128::from(ordinal),
                kinds,
                started_at: started,
            }))
        })
    }

    /// `turn_code(thread_id, turn_id)`: Codex's code for the error of a turn (core's `failures.shape`), or none.
    pub fn turn_code(&self, thread_id: &Value, turn_id: &Value) -> Read<Value> {
        if !Self::uuid(thread_id) || !Self::uuid(turn_id) {
            return Err(unavailable("not a turn"));
        }
        let (thread, turn) = (thread_id_text(thread_id), thread_id_text(turn_id));
        let raw = self.read(|connection| {
            Ok(sql::first(connection, ERROR, &[text_param(&thread), text_param(&turn)])
                .map_err(caught("the turn history cannot be read"))?
                .map(|row| row.at(0).value()))
        })?;
        let error = match raw {
            Some(text @ Value::Str(_)) => car_codex::values::json_of(&text),
            _ => None,
        };
        let info = match &error {
            Some(Value::Object(map)) => map.get("codexErrorInfo").cloned().unwrap_or(Value::Null),
            _ => Value::Null,
        };
        let shape = car_policy::classify::failures::shape(&info, &Value::Null);
        Ok(match shape {
            Value::Object(map) => map.get("code").cloned().unwrap_or(Value::Null),
            _ => Value::Null,
        })
    }

    /// `status(thread_id, turn_id)`: the status of a turn looked for under every id of the conversation, or none.
    pub fn status(&self, thread_id: &Value, turn_id: &Value) -> Read<Option<String>> {
        if !Self::uuid(thread_id) || !Self::uuid(turn_id) {
            return Err(unavailable("not a turn"));
        }
        let (thread, turn) = (thread_id_text(thread_id), thread_id_text(turn_id));
        let chain = self.chain(&thread)?;
        self.read(|connection| {
            for other in chain.iter().rev() {
                let row = sql::first(connection, STATUS, &[text_param(other), text_param(&turn)])
                    .map_err(caught("the turn history cannot be read"))?;
                if let Some(row) = row {
                    return Ok(Some(match row.at(0) {
                        Cell::Text(text) if TURN_STATUSES.contains(&text.as_str()) => text.clone(),
                        _ => "other".to_owned(),
                    }));
                }
            }
            Ok(None)
        })
    }

    /// `recent(since)`: the conversations with a turn completed at `since` or later, the latest first.
    pub fn recent(&self, since: i64) -> Read<Vec<String>> {
        let rows = self.read(|connection| {
            sql::query(connection, RECENT, &[Param::Int(since), Param::Int(RECENT_LIMIT)])
                .map_err(caught("the turn history cannot be read"))
        })?;
        self.named(rows.iter().map(|row| row.at(0).value()).collect())
    }

    /// `_named(rows)`: each row's conversation, once.
    fn named(&self, ids_found: Vec<Value>) -> Read<Vec<String>> {
        let mut found: Vec<String> = Vec::new();
        for id in ids_found {
            if !Self::uuid(&id) {
                continue;
            }
            let text = thread_id_text(&id);
            let named = self.owner_of(&text)?.filter(|owner| !owner.is_empty()).unwrap_or(text);
            if !found.contains(&named) {
                found.push(named);
            }
        }
        Ok(found)
    }

    /// `running(booted)`: the conversations whose latest turn is running now, one begun before Windows last started
    /// left out.
    pub fn running(&self, booted: &Value) -> Read<Vec<String>> {
        let rows = self.read(|connection| {
            sql::query(connection, RUNNING, &[Param::Int(RECENT_LIMIT)]).map_err(caught("the turn history cannot be read"))
        })?;
        let mut kept = Vec::new();
        for row in rows {
            if !states::ended_by_boot(&row.at(1).value(), booted).map_err(Failure::Raised)? {
                kept.push(row.at(0).value());
            }
        }
        self.named(kept)
    }

    /// `between(thread_id, after, before)`: how many turns lie strictly between the turns at two ordinals.
    pub fn between(&self, thread_id: &Value, after: &Value, before: &Value) -> Read<i64> {
        let (Value::Int(after), Value::Int(before)) = (after, before) else {
            return Err(unavailable("not a conversation"));
        };
        if !Self::uuid(thread_id) {
            return Err(unavailable("not a conversation"));
        }
        // An ordinal is a whole number of any size in the reference; past 128 bits is no ordinal `latest` makes.
        let (Ok(after), Ok(before)) = (after.to_string().parse::<i128>(), before.to_string().parse::<i128>()) else {
            return Err(Failure::Raised("OverflowError"));
        };
        let thread = thread_id_text(thread_id);
        let chain = self.chain(&thread)?;
        let span = SPAN;
        let (first, low) = (after.div_euclid(span), after.rem_euclid(span) as i64);
        let (last, high) = (before.div_euclid(span), before.rem_euclid(span) as i64);
        let length = chain.len() as i128;
        if !(first <= last && last < length) {
            return Err(unavailable("a turn of no shape this knows"));
        }
        // `chain[i]` with Python's negative indexing; past either end it is the IndexError the reference lets out.
        let at = |index: i128| -> Read<String> {
            let real = if index < 0 { index + length } else { index };
            usize::try_from(real)
                .ok()
                .and_then(|real| chain.get(real).cloned())
                .ok_or(Failure::Raised("IndexError"))
        };
        let mut spans: Vec<(String, i64, i64)> = Vec::new();
        if first == last {
            spans.push((at(first)?, low, high));
        } else {
            spans.push((at(first)?, low, SPAN as i64));
            // `chain[first + 1:last]`, a slice as Python takes one.
            let clamp = |index: i128| -> i128 {
                let real = if index < 0 { index + length } else { index };
                real.clamp(0, length)
            };
            for index in clamp(first + 1)..clamp(last) {
                spans.push((chain[index as usize].clone(), -1, SPAN as i64));
            }
            spans.push((at(last)?, -1, high));
        }
        self.read(|connection| {
            let mut total = 0i64;
            for (id, low, high) in &spans {
                let row = sql::first(connection, BETWEEN, &[text_param(id), Param::Int(*low), Param::Int(*high)])
                    .map_err(caught("the turn history cannot be read"))?;
                total += match row.as_ref().map(|row| row.at(0)) {
                    Some(Cell::Int(count)) => *count,
                    _ => 0,
                };
            }
            Ok(total)
        })
    }

    /// `plan_statuses(thread_id)`: the statuses of the newest plan item's steps, each a step status or "unknown"; none
    /// where the conversation has no plan item; a plan item whose steps cannot be read is TurnsUnavailable.
    pub fn plan_statuses(&self, thread_id: &Value) -> Read<Option<Vec<String>>> {
        if !Self::uuid(thread_id) {
            return Err(unavailable("not a conversation"));
        }
        let thread = thread_id_text(thread_id);
        let chain = self.chain(&thread)?;
        self.read(|connection| {
            let failed = caught("the turn history cannot be read");
            let mut held: Vec<&String> = Vec::new();
            for other in &chain {
                let row = sql::first(connection, HAS_PLAN, &[text_param(other), text_param(PLAN_ITEM_TYPE)]).map_err(&failed)?;
                if row.is_some_and(|row| row.at(0).truthy()) {
                    held.push(other);
                }
            }
            let Some(newest) = held.last() else {
                return Ok(None);
            };
            let statuses: Vec<String> = sql::query(connection, PLAN, &[text_param(newest), text_param(PLAN_ITEM_TYPE)])
                .map_err(&failed)?
                .iter()
                .map(|row| match row.at(0) {
                    Cell::Text(text) if STEP_STATUSES.contains(&text.as_str()) => text.clone(),
                    _ => UNKNOWN.to_owned(),
                })
                .collect();
            if statuses.is_empty() {
                return Err(unavailable("a plan item with no steps this reads"));
            }
            Ok(Some(statuses))
        })
    }
}

/// A conversation's or a turn's id, as the text it is (the caller checked it is a UUID).
pub fn thread_id_text(value: &Value) -> String {
    match value {
        Value::Str(text) => text.as_str().unwrap_or("").to_owned(),
        _ => String::new(),
    }
}

/// `{item_type: count}` as a mapping in the order first met.
pub fn kinds_map(kinds: &[(String, i64)]) -> BTreeMap<String, i64> {
    kinds.iter().cloned().collect()
}

/// A failure of car-codex's reader that `_core` turns into TurnsUnavailable: SourceError, sqlite3.Error, OSError and
/// ValueError; the rest leave as they are.
fn core_failure(error: Error) -> Failure {
    match error {
        Error::Source(_) | Error::Sqlite | Error::Os | Error::Python("ValueError") => {
            unavailable("the conversation cannot be read")
        }
        other => raised(other),
    }
}
