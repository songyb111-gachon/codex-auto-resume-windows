//! The Dashboard's chat messages (`state/chat.py`): their words only until sent.

use car_machine::json::Value;
use rusqlite::Connection;

use super::errors::{Error, Result};
use super::py;
use super::schema::CHAT_WORDS;
use super::seam::words_gen::{chat_reason, chat_state, record_state};
use super::session::AdvancedState;
use super::sql::{self, Row, float, string};

pub const CAPABILITY: &str = "codex_chat";
const COLUMNS: &str =
    "chat_id, thread_id, words, state, reason, record_id, created_at, sent_at, finished_at";

/// `_ENDS`: how a record's move ends its message.
fn ends(movement: &str) -> Option<(&'static str, &'static str)> {
    Some(match movement {
        "delivered" | "superseded" | "handed_over" => {
            (chat_reason::DELIVERED, record_state::FINISHED)
        }
        "unproven" => (chat_reason::UNKNOWN, record_state::FINISHED),
        "withdrawn" => (chat_reason::WITHDRAWN, record_state::CANCELLED),
        "not_taken" => (chat_reason::NOT_TAKEN, record_state::CANCELLED),
        _ => return None,
    })
}

fn words_of(value: &Value) -> Result<()> {
    if !py::length(value).is_some_and(|length| 0 < length && length as i64 <= CHAT_WORDS) {
        return Err(Error::state("invalid words"));
    }
    Ok(())
}

impl AdvancedState {
    /// `add_chat(thread_id, words, record_id, at=None)`: a message waiting, its record waiting with it; its id.
    pub fn add_chat(
        &self,
        thread_id: &Value,
        words: &Value,
        record_id: &Value,
        at: &Value,
    ) -> Result<i64> {
        py::thread(thread_id)?;
        words_of(words)?;
        py::key(record_id, "record id")?;
        let now = self.now(at)?;
        self.writing(|connection| {
            if sql::exists(connection, "SELECT 1 FROM records WHERE record_id=?", &[record_id.clone()])? {
                return Err(Error::state("record id taken"));
            }
            sql::exec(
                connection,
                "INSERT INTO records (record_id, capability, thread_id, state, created_at, claims) VALUES (?,?,?,?,?,0)",
                &[
                    record_id.clone(),
                    string(CAPABILITY),
                    thread_id.clone(),
                    string(record_state::WAITING),
                    float(now),
                ],
            )?;
            sql::insert(
                connection,
                "INSERT INTO chat_messages (thread_id, words, state, record_id, created_at) VALUES (?,?,?,?,?)",
                &[
                    thread_id.clone(),
                    words.clone(),
                    string(chat_state::WAITING),
                    record_id.clone(),
                    float(now),
                ],
            )
        })
    }

    /// `chats(thread_id=None, pending=False, limit=50)`: oldest first.
    pub fn chats(&self, thread_id: &Value, pending: &Value, limit: &Value) -> Result<Vec<Row>> {
        let mut clauses: Vec<String> = Vec::new();
        let mut values: Vec<Value> = Vec::new();
        if !matches!(thread_id, Value::Null) {
            py::thread(thread_id)?;
            clauses.push("thread_id=?".into());
            values.push(thread_id.clone());
        }
        if sql::truthy(pending) {
            clauses.push(format!(
                "state IN ('{}', '{}')",
                chat_state::WAITING,
                chat_state::IN_FLIGHT
            ));
        }
        let filter = if clauses.is_empty() {
            String::new()
        } else {
            format!(" WHERE {}", clauses.join(" AND "))
        };
        let mut rows = self.read(|connection| match connection {
            None => Ok(Vec::new()),
            Some(connection) => {
                values.push(py::int_of(limit)?);
                sql::all(
                    connection,
                    &format!(
                        "SELECT {COLUMNS} FROM chat_messages{filter} ORDER BY chat_id DESC LIMIT ?"
                    ),
                    &values,
                )
            }
        })?;
        rows.reverse();
        Ok(rows)
    }

    /// `chat_by_record(record_id)`.
    pub fn chat_by_record(&self, record_id: &Value) -> Result<Option<Row>> {
        py::key(record_id, "record id")?;
        self.read(|connection| match connection {
            None => Ok(None),
            Some(connection) => sql::one(
                connection,
                &format!("SELECT {COLUMNS} FROM chat_messages WHERE record_id=?"),
                &[record_id.clone()],
            ),
        })
    }

    /// `chat_sent(record_id, at=None)`: its send began - in flight, its words gone.
    pub fn chat_sent(&self, record_id: &Value, at: &Value) -> Result<bool> {
        py::key(record_id, "record id")?;
        let now = self.now(at)?;
        self.writing(|connection| {
            let moved = sql::exec(
                connection,
                "UPDATE chat_messages SET state=?, words=NULL, sent_at=? WHERE record_id=? AND state=?",
                &[
                    string(chat_state::IN_FLIGHT),
                    float(now),
                    record_id.clone(),
                    string(chat_state::WAITING),
                ],
            )? == 1;
            if moved {
                sql::exec(
                    connection,
                    "UPDATE records SET state=?, claimed_at=? WHERE record_id=?",
                    &[string(record_state::IN_FLIGHT), float(now), record_id.clone()],
                )?;
            }
            Ok(moved)
        })
    }

    /// `chat_released(record_id)`: a claim given back before its send began.
    pub fn chat_released(&self, record_id: &Value) -> Result<bool> {
        py::key(record_id, "record id")?;
        self.writing(|connection| {
            Ok(sql::exec(
                connection,
                "UPDATE records SET state=? WHERE record_id=? AND state=? AND EXISTS \
                 (SELECT 1 FROM chat_messages WHERE record_id=? AND state=?)",
                &[
                    string(record_state::WAITING),
                    record_id.clone(),
                    string(record_state::IN_FLIGHT),
                    record_id.clone(),
                    string(chat_state::WAITING),
                ],
            )? == 1)
        })
    }

    /// `chat_ended(record_id, move, at=None)`: a sent message's end, as core's move says it.
    pub fn chat_ended(&self, record_id: &Value, movement: &Value, at: &Value) -> Result<bool> {
        py::key(record_id, "record id")?;
        if matches!(movement, Value::Array(_) | Value::Object(_)) {
            return Err(Error::type_error("unhashable type"));
        }
        let Some((reason, state)) = py::text(movement).and_then(ends) else {
            return Err(Error::state("invalid move"));
        };
        let now = self.now(at)?;
        self.writing(|connection| {
            let ended = sql::exec(
                connection,
                "UPDATE chat_messages SET state=?, reason=?, words=NULL, finished_at=? WHERE record_id=? AND state IN \
                 (?, ?)",
                &[
                    string(if state == record_state::FINISHED {
                        chat_state::DONE
                    } else {
                        chat_state::CANCELLED
                    }),
                    string(reason),
                    float(now),
                    record_id.clone(),
                    string(chat_state::WAITING),
                    string(chat_state::IN_FLIGHT),
                ],
            )? == 1;
            if ended {
                sql::exec(
                    connection,
                    "UPDATE records SET state=?, finished_at=? WHERE record_id=?",
                    &[string(state), float(now), record_id.clone()],
                )?;
            }
            Ok(ended)
        })
    }

    /// `chat_moved(record_id, move, reason=None, at=None)`: what core told of a chat message's record (P14).
    pub fn chat_moved(
        &self,
        record_id: &Value,
        movement: &Value,
        reason: &Value,
        at: &Value,
    ) -> Result<Option<Row>> {
        py::key(record_id, "record id")?;
        let movement = py::py_str(movement);
        if self.chat_by_record(record_id)?.is_none() {
            return Ok(None);
        }
        match movement.as_str() {
            "sent" => {
                self.chat_sent(record_id, at)?;
            }
            "released" | "not_started" => {
                self.chat_released(record_id)?;
            }
            "withdrawn" => {
                let end = if py::is_word(reason, &["paused"]) {
                    "withdrawn"
                } else {
                    "not_taken"
                };
                self.chat_ended(record_id, &string(end), at)?;
            }
            other if ends(other).is_some() => {
                self.chat_ended(record_id, &string(other), at)?;
            }
            "waiting" | "withdraw_refused" => {}
            _ => return Ok(None),
        }
        Ok(Some(super::resets::moved(
            string(CAPABILITY),
            movement == "unproven",
        )))
    }

    /// `chats_in_flight()`.
    pub fn chats_in_flight(&self) -> Result<Vec<Row>> {
        Ok(self
            .chats(&Value::Null, &Value::Bool(true), &py::int(50))?
            .into_iter()
            .filter(|row| py::is_word(sql::get(row, "state"), &[chat_state::IN_FLIGHT]))
            .collect())
    }

    /// `release_unlaunched_chats(after, at=None)`.
    pub fn release_unlaunched_chats(&self, after: &Value, at: &Value) -> Result<i64> {
        let now = self.now(at)?;
        self.transaction(false, |connection| {
            let Some(connection) = connection else {
                return Ok(0);
            };
            let after = py::minus_operand(after)?;
            let keys = sql::tuples(
                connection,
                "SELECT c.record_id FROM chat_messages m JOIN records c ON c.record_id = m.record_id WHERE m.state=? \
                 AND m.sent_at IS NULL AND c.state=? AND c.claimed_at IS NOT NULL AND c.claimed_at <= ?",
                &[string(chat_state::WAITING), string(record_state::IN_FLIGHT), float(now - after)],
            )?;
            for key in &keys {
                sql::exec(
                    connection,
                    "UPDATE records SET state=? WHERE record_id=? AND state=?",
                    &[string(record_state::WAITING), key[0].clone(), string(record_state::IN_FLIGHT)],
                )?;
            }
            Ok(keys.len() as i64)
        })
    }

    /// `cancel_chat(reason, record_id=None, thread_id=None, at=None)`: waiting messages cancelled; how many.
    pub fn cancel_chat(
        &self,
        reason: &Value,
        record_id: &Value,
        thread_id: &Value,
        at: &Value,
    ) -> Result<i64> {
        let reason = py::closed(reason, chat_reason::ALL, "reason")?;
        let mut clauses = vec!["state=?"];
        let mut values = vec![string(chat_state::WAITING)];
        if !matches!(record_id, Value::Null) {
            clauses.push("record_id=?");
            values.push(py::word(py::key(record_id, "record id")?));
        }
        if !matches!(thread_id, Value::Null) {
            clauses.push("thread_id=?");
            values.push(py::word(py::thread(thread_id)?));
        }
        let now = self.now(at)?;
        self.transaction(false, |connection| {
            let Some(connection) = connection else {
                return Ok(0);
            };
            let keys = sql::tuples(
                connection,
                &format!("SELECT record_id FROM chat_messages WHERE {}", clauses.join(" AND ")),
                &values,
            )?;
            for key in &keys {
                sql::exec(
                    connection,
                    "UPDATE chat_messages SET state=?, reason=?, words=NULL, finished_at=? WHERE record_id=?",
                    &[string(chat_state::CANCELLED), string(reason), float(now), key[0].clone()],
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
}

/// `end_pending(connection, capabilities, now)`: every chat message still waiting cancelled (turned_off).
pub fn end_pending(connection: &Connection, capabilities: &[Value], now: f64) -> Result<()> {
    if !capabilities
        .iter()
        .any(|capability| sql::py_eq(capability, &string(CAPABILITY)))
    {
        return Ok(());
    }
    let rows = sql::tuples(
        connection,
        "SELECT record_id FROM chat_messages WHERE state=?",
        &[string(chat_state::WAITING)],
    )?;
    for row in rows {
        sql::exec(
            connection,
            "UPDATE chat_messages SET state=?, reason=?, words=NULL, finished_at=? WHERE record_id=?",
            &[
                string(chat_state::CANCELLED),
                string(chat_reason::TURNED_OFF),
                float(now),
                row[0].clone(),
            ],
        )?;
        sql::exec(
            connection,
            "UPDATE records SET state=?, finished_at=? WHERE record_id=? AND state<>?",
            &[
                string(record_state::CANCELLED),
                float(now),
                row[0].clone(),
                string(record_state::FINISHED),
            ],
        )?;
    }
    Ok(())
}
