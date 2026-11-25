//! What the advanced edition says happened, and the counts its sampler keeps - both bounded (`state/journal.py`).
//!
//! Content-free and closed like core's journal: a capability id, a code, and the reason, actor, point and answer
//! as words from closed lists; a word outside them is "other" or nothing, and never fails the move it describes.
//! Everything here is bounded as core's journal is - 5,000 entries or 90 days, pruned every 256 entries - and so is
//! every other table the pass reaches.

use car_machine::json::Value;
use car_policy::plug::vocab_gen::domain_plug::POINTS;
use rusqlite::Connection;

use super::errors::Result;
use super::py;
use super::seam::words_gen::{actor, arming_warning, journal_code, off_reason, record_state};
use super::session::AdvancedState;
use super::sql::{self, Row, float, int, string};

pub const EVENT_LIMIT: i64 = 5000;
pub const WATCH_LIMIT: i64 = 95;
pub const EVENT_MAX_AGE: f64 = 90.0 * 86400.0;
pub const PRUNE_EVERY: i64 = 256;
const DAY: f64 = 86400.0;
pub const SAMPLES_MAX_AGE: f64 = 90.0 * DAY;
pub const SAMPLES_LIMIT: i64 = 20000;
pub const TOKENS_MAX_AGE: f64 = 90.0 * DAY;
pub const OUTBOX_MAX_AGE: f64 = 7.0 * DAY;
pub const OUTBOX_LIMIT: i64 = 500;
pub const OPENS_MAX_AGE: f64 = 7.0 * DAY;
pub const OPENS_LIMIT: i64 = 1000;
pub const RESTARTS_MAX_AGE: f64 = 7.0 * DAY;
pub const HOOK_CLAIMS_MAX_AGE: f64 = 90.0 * DAY;
pub const STEERS_MAX_AGE: f64 = 30.0 * DAY;
pub const STEERS_LIMIT: i64 = 1000;

/// `prune_every(row_id)`: every 256th row.
pub fn prune_every(row_id: i64) -> bool {
    row_id % PRUNE_EVERY == 0
}

/// `prune_every` of a value: only an `int` counts.
pub fn prune_every_value(row_id: &Value) -> bool {
    match row_id {
        Value::Int(number) => number.as_i64().is_some_and(prune_every),
        _ => false,
    }
}

/// `_closed(value, words)`.
fn closed(value: &Value, words: &[&str]) -> Value {
    if py::is_word(value, words) {
        value.clone()
    } else {
        Value::Null
    }
}

/// `_reason(value)`: an off reason, or a statement's warning word.
fn reason(value: &Value) -> Value {
    let found = closed(value, off_reason::ALL);
    if sql::truthy(&found) {
        return found;
    }
    closed(value, arming_warning::ALL)
}

/// `_answer(value)` (the module's): an alternative, or a point's name.
fn answer_word(value: &Value) -> Value {
    let found = closed(value, &py::alternatives());
    if sql::truthy(&found) {
        return found;
    }
    closed(value, POINTS)
}

/// `strftime("%Y-%m-%d", gmtime(seconds))`.
pub fn utc_day(seconds: f64) -> String {
    let stamp = car_store::session::utc_stamp(seconds);
    format!("{}-{}-{}", &stamp[0..4], &stamp[4..6], &stamp[6..8])
}

/// `int(now // _DAY)`: Python's floor division of a float.
pub fn day_number(now: f64) -> i64 {
    py::floordiv(now, DAY) as i64
}

impl AdvancedState {
    /// `_answer(value)` (the mixin's): the module's word, or the id of a capability the registry holds.
    fn answer(&self, value: &Value) -> Value {
        if py::is_str(value) && self.registry.get(value).is_some() {
            return value.clone();
        }
        answer_word(value)
    }

    /// `_code(code, capability)`: `code` if it is the journal's own or one of `capability`'s, else "other".
    pub(crate) fn code(&self, code: &Value, capability: &Value) -> Value {
        if py::is_word(code, journal_code::ALL) {
            return code.clone();
        }
        if let (Some(definition), Some(text)) = (self.registry.get(capability), py::text(code))
            && let Some((prefix, word)) = text.split_once('.')
            && prefix == definition.journal_prefix
            && definition.codes.contains(&word)
        {
            return code.clone();
        }
        string(journal_code::OTHER)
    }

    /// `_note(connection, at, code, ...)`: one journal line inside the caller's transaction.
    #[allow(clippy::too_many_arguments)]
    pub(crate) fn note_in(
        &self,
        connection: &Connection,
        at: f64,
        code: &Value,
        capability: &Value,
        reason_word: &Value,
        actor_word: &Value,
        point: &Value,
        answer: &Value,
    ) -> Result<()> {
        let capability = if self.registry.get(capability).is_some() {
            capability.clone()
        } else {
            Value::Null
        };
        sql::exec(
            connection,
            "INSERT INTO journal (at, capability, code, reason, actor, point, answer) VALUES (?,?,?,?,?,?,?)",
            &[
                float(at),
                capability.clone(),
                self.code(code, &capability),
                reason(reason_word),
                closed(actor_word, actor::ALL),
                closed(point, POINTS),
                self.answer(answer),
            ],
        )?;
        if prune_every(connection.last_insert_rowid()) {
            prune(connection, at)?;
        }
        Ok(())
    }

    /// `note(code, ...)`: one journal line in a transaction of its own, written only where the file is there.
    #[allow(clippy::too_many_arguments)]
    pub fn note(
        &self,
        code: &Value,
        capability: &Value,
        reason_word: &Value,
        actor_word: &Value,
        point: &Value,
        answer: &Value,
        at: &Value,
    ) -> Result<()> {
        let now = self.now(at)?;
        self.transaction(false, |connection| {
            if let Some(connection) = connection {
                self.note_in(
                    connection,
                    now,
                    code,
                    capability,
                    reason_word,
                    actor_word,
                    point,
                    answer,
                )?;
            }
            Ok(())
        })
    }

    /// `journal(capability=None, limit=500)`: lines oldest first, coerced as they are read.
    pub fn journal(&self, capability: &Value, limit: &Value) -> Result<Vec<Row>> {
        let limit = py::clamp(&py::int_of(limit)?, 1, EVENT_LIMIT);
        let (clause, mut arguments) = if sql::truthy(capability) {
            ("WHERE capability=?", vec![capability.clone()])
        } else {
            ("", Vec::new())
        };
        arguments.push(int(limit));
        let rows = self.read(|connection| match connection {
            None => Ok(Vec::new()),
            Some(connection) => sql::all(
                connection,
                &format!(
                    "SELECT * FROM (SELECT * FROM journal {clause} ORDER BY event_id DESC LIMIT ?) ORDER BY event_id"
                ),
                &arguments,
            ),
        })?;
        Ok(rows
            .into_iter()
            .map(|row| {
                let capability = sql::get(&row, "capability");
                let mut line = Row::new();
                line.insert(sql::key("at"), sql::get(&row, "at").clone());
                line.insert(
                    sql::key("capability"),
                    if self.registry.get(capability).is_some() {
                        capability.clone()
                    } else {
                        Value::Null
                    },
                );
                line.insert(
                    sql::key("code"),
                    self.code(sql::get(&row, "code"), capability),
                );
                line.insert(sql::key("reason"), reason(sql::get(&row, "reason")));
                line.insert(
                    sql::key("actor"),
                    closed(sql::get(&row, "actor"), actor::ALL),
                );
                line.insert(sql::key("point"), closed(sql::get(&row, "point"), POINTS));
                line.insert(sql::key("answer"), self.answer(sql::get(&row, "answer")));
                line
            })
            .collect())
    }

    /// `journal_times(capability, word, since)`: when `capability` journalled its own code `word` since `since`.
    pub fn journal_times(
        &self,
        capability: &Value,
        word: &Value,
        since: &Value,
    ) -> Result<Vec<Value>> {
        let Some(code) = self
            .registry
            .get(capability)
            .and_then(|definition| definition.code(word))
        else {
            return Ok(Vec::new());
        };
        self.read(|connection| match connection {
            None => Ok(Vec::new()),
            Some(connection) => Ok(sql::tuples(
                connection,
                "SELECT at FROM journal WHERE capability=? AND code=? AND at>=? ORDER BY at",
                &[
                    capability.clone(),
                    string(&code),
                    float(py::float_of(since)?),
                ],
            )?
            .into_iter()
            .filter_map(|row| row.into_iter().next())
            .collect()),
        })
    }

    // ------------------------------------------------------------------ sampler
    /// `sample(capability, code)`: one of `capability`'s own codes counted today, no journal line.
    pub fn sample(&self, capability: &Value, code: &Value, at: &Value) -> Result<bool> {
        let Some(_definition) = self
            .registry
            .get(capability)
            .filter(|definition| definition.has_code(code))
        else {
            return Ok(false);
        };
        let now = self.now(at)?;
        self.transaction(false, |connection| {
            let Some(connection) = connection else {
                return Ok(false);
            };
            count_today(connection, capability, code, now)?;
            Ok(true)
        })
    }

    /// `counted(capability, code)`: one of `capability`'s own codes counted today, with its journal line.
    pub fn counted(&self, capability: &Value, code: &Value, at: &Value) -> Result<bool> {
        let Some(definition) = self
            .registry
            .get(capability)
            .filter(|definition| definition.has_code(code))
        else {
            return Ok(false);
        };
        let line = definition.code(code).unwrap_or_default();
        let now = self.now(at)?;
        self.transaction(false, |connection| {
            let Some(connection) = connection else {
                return Ok(false);
            };
            count_today(connection, capability, code, now)?;
            self.note_in(
                connection,
                now,
                &string(&line),
                capability,
                &Value::Null,
                &Value::Null,
                &Value::Null,
                &Value::Null,
            )?;
            Ok(true)
        })
    }

    /// `counted_since(capability, code, since)`: how many times its own `code` was counted at `since` or later.
    pub fn counted_since(&self, capability: &Value, code: &Value, since: &Value) -> Result<i64> {
        let Some(definition) = self
            .registry
            .get(capability)
            .filter(|definition| definition.has_code(code))
        else {
            return Ok(0);
        };
        if !py::is_number(since) {
            return Ok(0);
        }
        let line = definition.code(code).unwrap_or_default();
        self.read(|connection| match connection {
            None => Ok(0),
            Some(connection) => sql::number(
                connection,
                "SELECT count(*) FROM journal WHERE capability=? AND code=? AND at>=?",
                &[
                    capability.clone(),
                    string(&line),
                    float(py::float_of(since)?),
                ],
            ),
        })
    }

    /// `samples(capability)`: {code: count} over the days the sampler keeps.
    pub fn samples(&self, capability: &Value) -> Result<Row> {
        let rows = self.read(|connection| match connection {
            None => Ok(Vec::new()),
            Some(connection) => sql::tuples(
                connection,
                "SELECT code, sum(count) FROM sampler WHERE capability=? GROUP BY code",
                std::slice::from_ref(capability),
            ),
        })?;
        let definition = self.registry.get(capability);
        let mut found = Row::new();
        for row in rows {
            if definition.is_some_and(|definition| definition.has_code(&row[0])) {
                let count = py::int_of(&row[1])?;
                found.insert(
                    car_machine::json::Str::new(py::text(&row[0]).unwrap_or_default()),
                    count,
                );
            }
        }
        Ok(found)
    }
}

fn count_today(connection: &Connection, capability: &Value, code: &Value, now: f64) -> Result<()> {
    sql::exec(
        connection,
        "INSERT INTO sampler (capability, code, day, count) VALUES (?,?,?,1) \
         ON CONFLICT (capability, code, day) DO UPDATE SET count = count + 1",
        &[capability.clone(), code.clone(), int(day_number(now))],
    )?;
    Ok(())
}

/// `_prune(connection, now)`: every bounded table, in one pass.
pub fn prune(connection: &Connection, now: f64) -> Result<()> {
    let old = now - EVENT_MAX_AGE;
    sql::exec(
        connection,
        "DELETE FROM journal WHERE at < ?",
        &[float(old)],
    )?;
    let watched = string(journal_code::WOULD_HAVE);
    for row in sql::tuples(
        connection,
        "SELECT DISTINCT capability FROM journal WHERE code=?",
        std::slice::from_ref(&watched),
    )? {
        sql::exec(
            connection,
            "DELETE FROM journal WHERE event_id IN (SELECT event_id FROM journal WHERE code=? AND capability IS ? \
             ORDER BY event_id DESC LIMIT -1 OFFSET ?)",
            &[watched.clone(), row[0].clone(), int(WATCH_LIMIT)],
        )?;
    }
    let excess = sql::number(connection, "SELECT count(*) FROM journal", &[])? - EVENT_LIMIT;
    if excess > 0 {
        sql::exec(
            connection,
            "DELETE FROM journal WHERE event_id IN (SELECT event_id FROM journal ORDER BY code IS ?, event_id LIMIT ?)",
            &[watched.clone(), int(excess)],
        )?;
    }
    sql::exec(
        connection,
        "DELETE FROM sampler WHERE day < ?",
        &[int(day_number(old))],
    )?;
    let excess = sql::number(connection, "SELECT count(*) FROM sampler", &[])? - EVENT_LIMIT;
    if excess > 0 {
        sql::exec(
            connection,
            "DELETE FROM sampler WHERE rowid IN (SELECT rowid FROM sampler ORDER BY day LIMIT ?)",
            &[int(excess)],
        )?;
    }
    let settled = format!(
        "state IN ('{}', '{}')",
        record_state::FINISHED,
        record_state::CANCELLED
    );
    sql::exec(
        connection,
        &format!("DELETE FROM records WHERE {settled} AND coalesce(finished_at, created_at) < ?"),
        &[float(old)],
    )?;
    let excess = sql::number(connection, "SELECT count(*) FROM records", &[])? - EVENT_LIMIT;
    if excess > 0 {
        sql::exec(
            connection,
            &format!(
                "DELETE FROM records WHERE record_id IN (SELECT record_id FROM records WHERE {settled} \
                 ORDER BY created_at LIMIT ?)"
            ),
            &[int(excess)],
        )?;
    }
    sql::exec(
        connection,
        "DELETE FROM overrides WHERE created_at < ?",
        &[float(old)],
    )?;
    let excess = sql::number(connection, "SELECT count(*) FROM overrides", &[])? - EVENT_LIMIT;
    if excess > 0 {
        sql::exec(
            connection,
            "DELETE FROM overrides WHERE rowid IN (SELECT rowid FROM overrides ORDER BY created_at LIMIT ?)",
            &[int(excess)],
        )?;
    }
    sql::exec(
        connection,
        "DELETE FROM admissions WHERE created_at < ?",
        &[float(old)],
    )?;
    let excess = sql::number(connection, "SELECT count(*) FROM admissions", &[])? - EVENT_LIMIT;
    if excess > 0 {
        sql::exec(
            connection,
            "DELETE FROM admissions WHERE interruption_id IN (SELECT interruption_id FROM admissions \
             ORDER BY created_at LIMIT ?)",
            &[int(excess)],
        )?;
    }
    sql::exec(
        connection,
        "DELETE FROM samples WHERE at < ?",
        &[float(old)],
    )?;
    let excess = sql::number(connection, "SELECT count(*) FROM samples", &[])? - EVENT_LIMIT;
    if excess > 0 {
        sql::exec(
            connection,
            "DELETE FROM samples WHERE sample_id IN (SELECT sample_id FROM samples ORDER BY sample_id LIMIT ?)",
            &[int(excess)],
        )?;
    }
    prune_spend(connection, "main", now)?;
    super::resets::prune(connection, now, EVENT_MAX_AGE, EVENT_LIMIT)?;
    super::continuations::prune(connection, now, EVENT_MAX_AGE, EVENT_LIMIT)?;
    super::prompts::prune(connection, now, EVENT_MAX_AGE, EVENT_LIMIT)?;
    bound(
        connection,
        "usage_samples",
        "at",
        now - SAMPLES_MAX_AGE,
        Some(SAMPLES_LIMIT),
        "",
    )?;
    sql::exec(
        connection,
        "DELETE FROM token_days WHERE day < ?",
        &[string(&utc_day(now - TOKENS_MAX_AGE))],
    )?;
    bound(
        connection,
        "token_files",
        "read_at",
        now - TOKENS_MAX_AGE,
        None,
        "",
    )?;
    bound(
        connection,
        "outbox",
        "at",
        now - OUTBOX_MAX_AGE,
        Some(OUTBOX_LIMIT),
        "state = 'waiting', ",
    )?;
    bound(
        connection,
        "opens",
        "at",
        now - OPENS_MAX_AGE,
        Some(OPENS_LIMIT),
        "",
    )?;
    bound(
        connection,
        "restarts",
        "at",
        now - RESTARTS_MAX_AGE,
        None,
        "",
    )?;
    bound(
        connection,
        "hook_claims",
        "at",
        now - HOOK_CLAIMS_MAX_AGE,
        None,
        "",
    )?;
    super::small::prune_steers(connection, now, STEERS_MAX_AGE, STEERS_LIMIT)?;
    Ok(())
}

/// `_bound(connection, table, column, before, limit, first)`.
fn bound(
    connection: &Connection,
    table: &str,
    column: &str,
    before: f64,
    limit: Option<i64>,
    first: &str,
) -> Result<()> {
    sql::exec(
        connection,
        &format!("DELETE FROM {table} WHERE {column} < ?"),
        &[float(before)],
    )?;
    let excess = sql::number(connection, &format!("SELECT count(*) FROM {table}"), &[])?
        - limit.unwrap_or(0);
    if let Some(limit) = limit
        && limit != 0
        && excess > 0
    {
        sql::exec(
            connection,
            &format!(
                "DELETE FROM {table} WHERE rowid IN (SELECT rowid FROM {table} ORDER BY {first}{column} LIMIT ?)"
            ),
            &[int(excess)],
        )?;
    }
    Ok(())
}

/// `_prune_spend(connection, schema, now)`: spends older than 90 days, then the oldest beyond 5,000 - never one
/// from the last day.
pub fn prune_spend(connection: &Connection, schema: &str, now: f64) -> Result<()> {
    sql::exec(
        connection,
        &format!("DELETE FROM {schema}.spend WHERE at < ?"),
        &[float(now - EVENT_MAX_AGE)],
    )?;
    let excess = sql::number(
        connection,
        &format!("SELECT count(*) FROM {schema}.spend"),
        &[],
    )? - EVENT_LIMIT;
    if excess > 0 {
        sql::exec(
            connection,
            &format!(
                "DELETE FROM {schema}.spend WHERE spend_id IN (SELECT spend_id FROM {schema}.spend \
                 WHERE at < ? ORDER BY spend_id LIMIT ?)"
            ),
            &[float(now - DAY), int(excess)],
        )?;
    }
    Ok(())
}
