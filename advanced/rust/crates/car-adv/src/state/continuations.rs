//! The edition's own continuations, and the conversations kept going (`state/continuations.py`).

use car_machine::json::Value;
use rusqlite::Connection;

use super::errors::{Error, Result};
use super::py;
use super::schema::CONTINUATION_CAPABILITIES;
use super::seam::words_gen::{
    continuation_kind, continuation_reason, keep_reason, keep_state, record_state, refusal,
};
use super::session::AdvancedState;
use super::sql::{self, Row, float, int, string};

pub const KEEP_GOING: &str = "keep_going";
pub const CONTINUATION_WORDS: usize = 2000;

/// `_ENDS`: how a record's move ends its continuation - the reason, and the record's state then.
fn ends(movement: &str) -> Option<(&'static str, &'static str)> {
    Some(match movement {
        "delivered" => (continuation_reason::DELIVERED, record_state::FINISHED),
        "unproven" => (continuation_reason::UNKNOWN, record_state::FINISHED),
        "superseded" => (continuation_reason::SUPERSEDED, record_state::FINISHED),
        "handed_over" => (continuation_reason::HANDED_OVER, record_state::FINISHED),
        "withdrawn" => (continuation_reason::WITHDRAWN, record_state::CANCELLED),
        _ => return None,
    })
}

/// `_capability(value)`: one of the continuation capabilities, or `StateError("invalid capability")`.
fn capability_of(value: &Value) -> Result<Value> {
    if !py::is_word(value, CONTINUATION_CAPABILITIES) {
        return Err(Error::state("invalid capability"));
    }
    Ok(value.clone())
}

/// `_words(value)`: 1 to 2000 characters, or `StateError("invalid words")`.
fn words_of(value: &Value) -> Result<()> {
    if !py::length(value).is_some_and(|length| 0 < length && length <= CONTINUATION_WORDS) {
        return Err(Error::state("invalid words"));
    }
    Ok(())
}

fn ordinal_chain(ordinal: &Value, chain: &Value) -> Result<()> {
    let ordinal_ok = matches!(ordinal, Value::Int(number) if !number.to_string().starts_with('-'));
    let chain_ok = matches!(chain, Value::Int(number) if !number.to_string().starts_with('-') && number.as_i64() != Some(0));
    if !ordinal_ok || !chain_ok {
        return Err(Error::state("invalid continuation"));
    }
    Ok(())
}

const SELECT: &str = "SELECT n.*, c.state AS record_state, c.claimed_at AS claimed_at, c.queue_id AS queue_id, \
    c.withdraw AS withdraw FROM continuations n LEFT JOIN records c ON c.record_id = n.record_id";

impl AdvancedState {
    fn taken_key(connection: &Connection, key: &Value) -> Result<bool> {
        sql::exists(
            connection,
            "SELECT 1 FROM continuations WHERE answer_id=? UNION SELECT 1 FROM records WHERE record_id=?",
            &[key.clone(), key.clone()],
        )
    }

    /// `add_continuation(key, capability, kind, thread_id, words, ordinal=..., chain=1, at=None)`: false where
    /// that turn was answered already.
    #[allow(clippy::too_many_arguments)]
    pub fn add_continuation(
        &self,
        key: &Value,
        capability: &Value,
        kind: &Value,
        thread_id: &Value,
        words: &Value,
        ordinal: &Value,
        chain: &Value,
        at: &Value,
    ) -> Result<bool> {
        py::key(key, "continuation key")?;
        capability_of(capability)?;
        let kind = py::closed(kind, continuation_kind::ALL, "kind")?;
        py::thread(thread_id)?;
        words_of(words)?;
        ordinal_chain(ordinal, chain)?;
        let now = self.now(at)?;
        self.writing(|connection| {
            if Self::taken_key(connection, key)? {
                return Ok(false);
            }
            sql::exec(
                connection,
                "INSERT INTO records (record_id, capability, thread_id, state, created_at, claims) VALUES (?,?,?,?,?,0)",
                &[key.clone(), capability.clone(), thread_id.clone(), string(record_state::WAITING), float(now)],
            )?;
            sql::exec(
                connection,
                "INSERT INTO continuations (answer_id, capability, kind, thread_id, record_id, ordinal, words, chain, \
                 created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                &[
                    key.clone(),
                    capability.clone(),
                    string(kind),
                    thread_id.clone(),
                    key.clone(),
                    ordinal.clone(),
                    words.clone(),
                    chain.clone(),
                    float(now),
                ],
            )?;
            Ok(true)
        })
    }

    /// `add_held_continuation(key, capability, kind, thread_id, ordinal=..., chain=1, at=None)`: one kept waiting
    /// with no words of its own.
    #[allow(clippy::too_many_arguments)]
    pub fn add_held_continuation(
        &self,
        key: &Value,
        capability: &Value,
        kind: &Value,
        thread_id: &Value,
        ordinal: &Value,
        chain: &Value,
        at: &Value,
    ) -> Result<bool> {
        py::key(key, "continuation key")?;
        capability_of(capability)?;
        let kind = py::closed(kind, continuation_kind::ALL, "kind")?;
        py::thread(thread_id)?;
        ordinal_chain(ordinal, chain)?;
        let now = self.now(at)?;
        self.writing(|connection| {
            if Self::taken_key(connection, key)? {
                return Ok(false);
            }
            sql::exec(
                connection,
                "INSERT INTO records (record_id, capability, thread_id, state, created_at, claims) VALUES (?,?,?,?,?,0)",
                &[key.clone(), capability.clone(), thread_id.clone(), string(record_state::WAITING), float(now)],
            )?;
            sql::exec(
                connection,
                "INSERT INTO continuations (answer_id, capability, kind, thread_id, record_id, ordinal, words, chain, \
                 created_at) VALUES (?,?,?,?,?,?,NULL,?,?)",
                &[
                    key.clone(),
                    capability.clone(),
                    string(kind),
                    thread_id.clone(),
                    key.clone(),
                    ordinal.clone(),
                    chain.clone(),
                    float(now),
                ],
            )?;
            Ok(true)
        })
    }

    /// `note_continuation(key, capability, kind, thread_id, reason, ordinal=None, chain=0, at=None)`: a turn the
    /// edition decided not to answer, kept so it is decided once.
    #[allow(clippy::too_many_arguments)]
    pub fn note_continuation(
        &self,
        key: &Value,
        capability: &Value,
        kind: &Value,
        thread_id: &Value,
        reason: &Value,
        ordinal: &Value,
        chain: &Value,
        at: &Value,
    ) -> Result<bool> {
        py::key(key, "continuation key")?;
        capability_of(capability)?;
        let kind = py::closed(kind, continuation_kind::ALL, "kind")?;
        py::thread(thread_id)?;
        let reason = py::closed(reason, continuation_reason::ALL, "reason")?;
        let now = self.now(at)?;
        self.writing(|connection| {
            if sql::exists(connection, "SELECT 1 FROM continuations WHERE answer_id=?", &[key.clone()])? {
                return Ok(false);
            }
            sql::exec(
                connection,
                "INSERT INTO continuations (answer_id, capability, kind, thread_id, ordinal, chain, created_at, \
                 finished_at, reason) VALUES (?,?,?,?,?,?,?,?,?)",
                &[
                    key.clone(),
                    capability.clone(),
                    string(kind),
                    thread_id.clone(),
                    ordinal.clone(),
                    chain.clone(),
                    float(now),
                    float(now),
                    string(reason),
                ],
            )?;
            Ok(true)
        })
    }

    /// `continuation(key)`: one continuation's row, with its record's state.
    pub fn continuation(&self, key: &Value) -> Result<Option<Row>> {
        py::key(key, "continuation key")?;
        self.read(|connection| match connection {
            None => Ok(None),
            Some(connection) => sql::one(
                connection,
                &format!("{SELECT} WHERE n.answer_id=?"),
                &[key.clone()],
            ),
        })
    }

    /// `continuations(capability=None, thread_id=None, pending=True)`: oldest first.
    pub fn continuations(
        &self,
        capability: &Value,
        thread_id: &Value,
        pending: &Value,
    ) -> Result<Vec<Row>> {
        let mut clauses: Vec<&str> = Vec::new();
        let mut values: Vec<Value> = Vec::new();
        if !matches!(capability, Value::Null) {
            clauses.push("n.capability=?");
            values.push(capability_of(capability)?);
        }
        if !matches!(thread_id, Value::Null) {
            clauses.push("n.thread_id=?");
            values.push(py::word(py::thread(thread_id)?));
        }
        match pending {
            Value::Bool(true) => clauses.push("n.finished_at IS NULL"),
            Value::Bool(false) => clauses.push("n.finished_at IS NOT NULL"),
            _ => {}
        }
        self.read(|connection| match connection {
            None => Ok(Vec::new()),
            Some(connection) => {
                let filter = if clauses.is_empty() {
                    String::new()
                } else {
                    format!(" WHERE {}", clauses.join(" AND "))
                };
                sql::all(
                    connection,
                    &format!("{SELECT}{filter} ORDER BY n.created_at, n.answer_id"),
                    &values,
                )
            }
        })
    }

    /// `last_continuation(thread_id, capability)`: the newest of `capability` in `thread_id`, finished or not.
    pub fn last_continuation(&self, thread_id: &Value, capability: &Value) -> Result<Option<Row>> {
        Ok(self
            .continuations(capability, thread_id, &Value::Null)?
            .pop())
    }

    /// `continuation_moved(record_id, move, at=None, queue_id=None)`: what core told of a continuation's record.
    pub fn continuation_moved(
        &self,
        record_id: &Value,
        movement: &Value,
        at: &Value,
        queue_id: &Value,
    ) -> Result<Option<Row>> {
        py::key(record_id, "record id")?;
        let now = self.now(at)?;
        self.transaction(false, |connection| {
            let Some(connection) = connection else {
                return Ok(None);
            };
            let row = sql::one(
                connection,
                "SELECT n.capability, n.finished_at, c.state AS record_state FROM continuations n \
                 JOIN records c ON c.record_id = n.record_id WHERE n.record_id=?",
                &[record_id.clone()],
            )?;
            let Some(row) = row else { return Ok(None) };
            if !matches!(sql::get(&row, "finished_at"), Value::Null) {
                return Ok(None);
            }
            let movement = py::py_str(movement);
            if movement == "sent" {
                sql::exec(
                    connection,
                    "UPDATE continuations SET words=NULL WHERE record_id=?",
                    &[record_id.clone()],
                )?;
                if py::length(queue_id) == Some(36) {
                    sql::exec(
                        connection,
                        "UPDATE records SET queue_id=? WHERE record_id=?",
                        &[queue_id.clone(), record_id.clone()],
                    )?;
                }
            } else if movement == "released" || movement == "not_started" {
                sql::exec(
                    connection,
                    "UPDATE records SET state=?, finished_at=NULL WHERE record_id=? AND state=?",
                    &[string(record_state::WAITING), record_id.clone(), string(record_state::IN_FLIGHT)],
                )?;
                sql::exec(
                    connection,
                    "UPDATE continuations SET launching_at=NULL WHERE record_id=?",
                    &[record_id.clone()],
                )?;
            } else if let Some((reason, state)) = ends(&movement) {
                sql::exec(
                    connection,
                    "UPDATE continuations SET words=NULL, finished_at=?, reason=? WHERE record_id=?",
                    &[float(now), string(reason), record_id.clone()],
                )?;
                sql::exec(
                    connection,
                    "UPDATE records SET state=?, finished_at=?, withdraw=0 WHERE record_id=?",
                    &[string(state), float(now), record_id.clone()],
                )?;
            } else if movement == "withdraw_refused" {
                sql::exec(
                    connection,
                    "UPDATE records SET withdraw=0 WHERE record_id=?",
                    &[record_id.clone()],
                )?;
            } else if movement != "waiting" {
                return Ok(None);
            }
            Ok(Some(super::resets::moved(
                sql::get(&row, "capability").clone(),
                movement == "unproven",
            )))
        })
    }

    /// `hold_continuation(answer_id, capability)`: a waiting continuation kept from now on with no words.
    pub fn hold_continuation(&self, answer_id: &Value, capability: &Value) -> Result<bool> {
        py::key(answer_id, "answer id")?;
        self.transaction(false, |connection| match connection {
            None => Ok(false),
            Some(connection) => Ok(sql::exec(
                connection,
                "UPDATE continuations SET words=NULL WHERE answer_id=? AND capability=? AND finished_at IS NULL",
                &[answer_id.clone(), capability_of(capability)?],
            )? == 1),
        })
    }

    /// `doubt_continuation(answer_id, capability, at=None)`: a continuation whose carry may not have reached the
    /// app, marked in `launching_at`, its words gone.
    pub fn doubt_continuation(
        &self,
        answer_id: &Value,
        capability: &Value,
        at: &Value,
    ) -> Result<bool> {
        py::key(answer_id, "answer id")?;
        let now = self.now(at)?;
        self.transaction(false, |connection| match connection {
            None => Ok(false),
            Some(connection) => Ok(sql::exec(
                connection,
                "UPDATE continuations SET launching_at=coalesce(launching_at, ?), words=NULL WHERE answer_id=? \
                 AND capability=? AND finished_at IS NULL",
                &[float(now), answer_id.clone(), capability_of(capability)?],
            )? == 1),
        })
    }

    /// `end_continuations(reason, capability=None, thread_id=None, at=None)`: every one still waiting, ended.
    pub fn end_continuations(
        &self,
        reason: &Value,
        capability: &Value,
        thread_id: &Value,
        at: &Value,
    ) -> Result<i64> {
        let reason = py::closed(reason, continuation_reason::ALL, "reason")?;
        let mut clauses = vec!["n.finished_at IS NULL", "c.state=?"];
        let mut values = vec![string(record_state::WAITING)];
        if !matches!(capability, Value::Null) {
            clauses.push("n.capability=?");
            values.push(capability_of(capability)?);
        }
        if !matches!(thread_id, Value::Null) {
            clauses.push("n.thread_id=?");
            values.push(py::word(py::thread(thread_id)?));
        }
        let now = self.now(at)?;
        self.transaction(false, |connection| {
            let Some(connection) = connection else {
                return Ok(0);
            };
            let keys = sql::tuples(
                connection,
                &format!(
                    "SELECT n.record_id FROM continuations n JOIN records c ON c.record_id = n.record_id WHERE {}",
                    clauses.join(" AND ")
                ),
                &values,
            )?;
            for key in &keys {
                sql::exec(
                    connection,
                    "UPDATE continuations SET words=NULL, finished_at=?, reason=? WHERE record_id=?",
                    &[float(now), string(reason), key[0].clone()],
                )?;
                sql::exec(
                    connection,
                    "UPDATE records SET state=?, finished_at=? WHERE record_id=?",
                    &[string(record_state::CANCELLED), float(now), key[0].clone()],
                )?;
            }
            Ok(keys.len() as i64)
        })
    }

    /// `continuations_in_flight()`: every continuation whose record is in flight.
    pub fn continuations_in_flight(&self) -> Result<Vec<Row>> {
        Ok(self
            .continuations(&Value::Null, &Value::Null, &Value::Bool(true))?
            .into_iter()
            .filter(|row| py::is_word(sql::get(row, "record_state"), &[record_state::IN_FLIGHT]))
            .collect())
    }

    /// `release_unlaunched_continuations(after, at=None)`.
    pub fn release_unlaunched_continuations(&self, after: &Value, at: &Value) -> Result<i64> {
        let now = self.now(at)?;
        self.transaction(false, |connection| match connection {
            None => Ok(0),
            Some(connection) => release_unlaunched(connection, now, after),
        })
    }

    // ------------------------------------------------------------------ keep going
    /// `keep_going(thread_id=None)`: one conversation's row (or None), or with no `thread_id` every row.
    pub fn keep_going(&self, thread_id: &Value) -> Result<Value> {
        self.read(|connection| {
            let Some(connection) = connection else {
                return Ok(if matches!(thread_id, Value::Null) {
                    Value::Array(Vec::new())
                } else {
                    Value::Null
                });
            };
            if !matches!(thread_id, Value::Null) {
                let thread = py::word(py::thread(thread_id)?);
                let row = sql::one(
                    connection,
                    "SELECT * FROM keep_going WHERE thread_id=?",
                    &[thread],
                )?;
                return Ok(row.map_or(Value::Null, Value::Object));
            }
            Ok(Value::Array(
                sql::all(
                    connection,
                    "SELECT * FROM keep_going ORDER BY armed_at DESC, thread_id",
                    &[],
                )?
                .into_iter()
                .map(Value::Object)
                .collect(),
            ))
        })
    }

    /// `set_keep_going(thread_id, count, at=None)`: a conversation kept going for `count` continuations.
    pub fn set_keep_going(&self, thread_id: &Value, count: &Value, at: &Value) -> Result<()> {
        py::thread(thread_id)?;
        if !py::small(count).is_some_and(|count| (1..11).contains(&count)) {
            return Err(Error::refused(refusal::KEEP_COUNT_INVALID));
        }
        let now = self.now(at)?;
        self.writing(|connection| {
            sql::exec(
                connection,
                "INSERT OR REPLACE INTO keep_going (thread_id, count, used, armed_at, state) VALUES (?,?,0,?,?)",
                &[thread_id.clone(), count.clone(), float(now), string(keep_state::ON)],
            )?;
            Ok(())
        })
    }

    /// `keep_going_used(thread_id, at=None)`: one more continuation counted.
    pub fn keep_going_used(&self, thread_id: &Value, at: &Value) -> Result<bool> {
        py::thread(thread_id)?;
        let now = self.now(at)?;
        self.transaction(false, |connection| {
            let Some(connection) = connection else {
                return Ok(false);
            };
            let row = sql::one(
                connection,
                "SELECT count, used FROM keep_going WHERE thread_id=? AND state=?",
                &[thread_id.clone(), string(keep_state::ON)],
            )?;
            let Some(row) = row else { return Ok(false) };
            let (count, used) = (sql::get(&row, "count"), sql::get(&row, "used"));
            if car_machine::pyval::less_or_equal(count, used)
                .map_err(|class| Error::python(class, "'>='"))?
            {
                return Ok(false);
            }
            let used = py::plus_one(used)?;
            let spent = car_machine::pyval::less_or_equal(count, &used)
                .map_err(|class| Error::python(class, "'>='"))?;
            sql::exec(
                connection,
                "UPDATE keep_going SET used=?, state=?, reason=?, finished_at=? WHERE thread_id=?",
                &[
                    used,
                    string(if spent {
                        keep_state::DONE
                    } else {
                        keep_state::ON
                    }),
                    if spent {
                        string(keep_reason::COUNT_SPENT)
                    } else {
                        Value::Null
                    },
                    if spent { float(now) } else { Value::Null },
                    thread_id.clone(),
                ],
            )?;
            Ok(true)
        })
    }

    /// `stop_keep_going(reason, thread_id=None, at=None)`: every conversation kept going - or one - stopped.
    pub fn stop_keep_going(&self, reason: &Value, thread_id: &Value, at: &Value) -> Result<i64> {
        let reason = py::closed(reason, keep_reason::ALL, "reason")?;
        let now = self.now(at)?;
        self.transaction(false, |connection| {
            let Some(connection) = connection else {
                return Ok(0);
            };
            let count = if matches!(thread_id, Value::Null) {
                sql::exec(
                    connection,
                    "UPDATE keep_going SET state=?, reason=?, finished_at=? WHERE state=?",
                    &[string(keep_state::DONE), string(reason), float(now), string(keep_state::ON)],
                )?
            } else {
                let thread = py::word(py::thread(thread_id)?);
                sql::exec(
                    connection,
                    "UPDATE keep_going SET state=?, reason=?, finished_at=? WHERE state=? AND thread_id=?",
                    &[string(keep_state::DONE), string(reason), float(now), string(keep_state::ON), thread],
                )?
            };
            Ok(count as i64)
        })
    }
}

/// `prune(connection, now, max_age, limit)`.
pub fn prune(connection: &Connection, now: f64, max_age: f64, limit: i64) -> Result<()> {
    let old = now - max_age;
    sql::exec(
        connection,
        "DELETE FROM continuations WHERE finished_at IS NOT NULL AND finished_at < ?",
        &[float(old)],
    )?;
    let excess = sql::number(connection, "SELECT count(*) FROM continuations", &[])? - limit;
    if excess > 0 {
        sql::exec(
            connection,
            "DELETE FROM continuations WHERE answer_id IN (SELECT answer_id FROM continuations WHERE finished_at \
             IS NOT NULL ORDER BY finished_at LIMIT ?)",
            &[int(excess)],
        )?;
    }
    sql::exec(
        connection,
        "DELETE FROM keep_going WHERE state=? AND finished_at < ?",
        &[string(keep_state::DONE), float(old)],
    )?;
    Ok(())
}

/// `end_pending(connection, capabilities, now, kept=True)`: every continuation still waiting of `capabilities`
/// ended (turned_off), and for keep_going with `kept` every conversation kept going stopped.
pub fn end_pending(
    connection: &Connection,
    capabilities: &[Value],
    now: f64,
    kept: bool,
) -> Result<()> {
    let ended: Vec<Value> = capabilities
        .iter()
        .filter(|capability| py::is_word(capability, CONTINUATION_CAPABILITIES))
        .cloned()
        .collect();
    if ended.is_empty() {
        return Ok(());
    }
    let mut parameters = ended.clone();
    parameters.push(string(record_state::WAITING));
    let rows = sql::tuples(
        connection,
        &format!(
            "SELECT n.record_id FROM continuations n JOIN records c ON c.record_id = n.record_id WHERE n.capability \
             IN ({}) AND n.finished_at IS NULL AND c.state=?",
            sql::marks(ended.len())
        ),
        &parameters,
    )?;
    for row in rows {
        sql::exec(
            connection,
            "UPDATE continuations SET words=NULL, finished_at=?, reason=? WHERE record_id=?",
            &[
                float(now),
                string(continuation_reason::TURNED_OFF),
                row[0].clone(),
            ],
        )?;
        sql::exec(
            connection,
            "UPDATE records SET state=?, finished_at=? WHERE record_id=?",
            &[string(record_state::CANCELLED), float(now), row[0].clone()],
        )?;
    }
    if kept
        && ended
            .iter()
            .any(|capability| py::is_word(capability, &[KEEP_GOING]))
    {
        sql::exec(
            connection,
            "UPDATE keep_going SET state=?, reason=?, finished_at=? WHERE state=?",
            &[
                string(keep_state::DONE),
                string(keep_reason::TURNED_OFF),
                float(now),
                string(keep_state::ON),
            ],
        )?;
    }
    Ok(())
}

/// `release_unlaunched(connection, now, after)`: every continuation claimed `after` seconds ago or more whose launch
/// never began, handed back; how many.
pub fn release_unlaunched(connection: &Connection, now: f64, after: &Value) -> Result<i64> {
    let after = py::minus_operand(after)?;
    let keys = sql::tuples(
        connection,
        "SELECT c.record_id FROM continuations n JOIN records c ON c.record_id = n.record_id WHERE n.finished_at IS NULL \
         AND n.launching_at IS NULL AND n.words IS NOT NULL AND c.state=? AND c.claimed_at IS NOT NULL \
         AND c.claimed_at <= ?",
        &[string(record_state::IN_FLIGHT), float(now - after)],
    )?;
    for key in &keys {
        sql::exec(
            connection,
            "UPDATE records SET state=? WHERE record_id=? AND state=?",
            &[
                string(record_state::WAITING),
                key[0].clone(),
                string(record_state::IN_FLIGHT),
            ],
        )?;
    }
    Ok(keys.len() as i64)
}
