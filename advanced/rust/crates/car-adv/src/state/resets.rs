//! What the reset actions keep (`state/resets.py`): the usage windows they count, the last reading, their rules and
//! their spends. A message's own record is a row of `records`, which the one claim counts with core's rows; its words
//! are here, held only while it is still to be sent.

use car_machine::json::Value;
use rusqlite::Connection;

use super::errors::{Error, Result};
use super::py;
use super::schema::{BUCKETS, RESET_CAPABILITIES, WORDS_MOST};
use super::seam::words_gen::{record_state, refusal, rule_reason, rule_state, spend_outcome};
use super::session::AdvancedState;
use super::sql::{self, Row, float, int, py_eq, string};

pub const CREDIT: &str = "reset_credit";
pub const MESSAGE: &str = "reset_message";
/// A rule still to act: counting, due, or held for a person.
pub const PENDING: &[&str] = &[rule_state::COUNTING, rule_state::READY, rule_state::HELD];
pub const FINISHED: &[&str] = &[rule_state::DONE, rule_state::CANCELLED];
pub const MESSAGES_LIMIT: i64 = 50;
pub const CREDIT_RULES_LIMIT: i64 = 4;
pub const WORDS_LIMIT: i64 = WORDS_MOST;
/// What a rule's row may be changed in, and nothing else of it (`CHANGES`).
pub const CHANGES: &[&str] = &[
    "state",
    "reason",
    "adopted_at",
    "base",
    "ordinal",
    "due_at",
    "launching_at",
    "sent_at",
    "gate",
    "gate_reason",
    "finished_at",
];
pub const TIMES: &[&str] = &[
    "adopted_at",
    "due_at",
    "launching_at",
    "sent_at",
    "finished_at",
];
pub const GATE_WORD_LIMIT: usize = 48;
pub const READING: &[&str] = &[
    "read_at",
    "asked_at",
    "applied_at",
    "signal_at",
    "credits",
    "expiry_known",
    "nearest_expiry",
];
pub const UNLAUNCHED_AFTER: f64 = 600.0;
/// `PACED`: what core tells a record whose claim the ledger held.
pub const PACED: (&str, &str) = ("submission_safe", "held");

fn pending_words() -> Vec<Value> {
    sql::words(PENDING)
}

/// `paced_wait(connection, record_id, gate, reason, now)`: a waiting record the pace held has its `created_at`
/// moved to now.
pub fn paced_wait(
    connection: &Connection,
    record_id: &Value,
    gate: &Value,
    reason: &Value,
    now: f64,
) -> Result<()> {
    if py_eq(gate, &string(PACED.0)) && py_eq(reason, &string(PACED.1)) {
        sql::exec(
            connection,
            "UPDATE records SET created_at=? WHERE record_id=? AND state=?",
            &[float(now), record_id.clone(), string(record_state::WAITING)],
        )?;
    }
    Ok(())
}

/// `_family(bucket, minutes)`: a window's bucket and length, or `StateError("invalid window")`.
pub fn family(bucket: &Value, minutes: &Value) -> Result<(Value, Value)> {
    let fits = py::small(minutes).is_some_and(|minutes| 0 < minutes && minutes <= 10 * 10080);
    if !py::is_word(bucket, BUCKETS) || !fits {
        return Err(Error::state("invalid window"));
    }
    Ok((bucket.clone(), minutes.clone()))
}

/// `_gate_word(value)`: a gate's or a reason's name - ASCII letters, digits and underscores, 1 to 48 - or None.
pub fn gate_word(value: &Value) -> Result<Value> {
    match value {
        Value::Null => Ok(Value::Null),
        Value::Str(text) => {
            let points: Vec<u32> = text.code_points().collect();
            let fine = !points.is_empty()
                && points.len() <= GATE_WORD_LIMIT
                && points.iter().all(|point| {
                    char::from_u32(*point).is_some_and(|c| c.is_ascii_alphanumeric() || c == '_')
                });
            if fine {
                Ok(value.clone())
            } else {
                Err(Error::state("invalid gate word"))
            }
        }
        _ => Err(Error::state("invalid gate word")),
    }
}

/// `_rule(row)`: a rule's row with its flags as booleans.
fn rule(mut row: Row) -> Row {
    for name in ["repeat", "ask_first"] {
        let on = sql::truthy(sql::get(&row, name));
        row.insert(sql::key(name), Value::Bool(on));
    }
    let withdraw = sql::truthy(sql::get(&row, "withdraw"));
    row.insert(sql::key("withdraw"), Value::Bool(withdraw));
    row
}

const RULE_SELECT: &str = "SELECT r.*, c.thread_id AS thread_id, c.state AS record_state, c.queue_id AS queue_id, \
    c.withdraw AS withdraw, c.created_at AS waiting_since FROM reset_rules r LEFT JOIN records c ON c.record_id = r.record_id";

/// The keyword changes of `change_rule`.
pub type Changes = Vec<(String, Value)>;

impl AdvancedState {
    // ------------------------------------------------------------------ windows
    /// `windows()`: {(bucket, minutes): the window's row} for every window counted.
    pub fn windows(&self) -> Result<Vec<((Value, Value), Row)>> {
        let rows = self.read(|connection| match connection {
            None => Ok(Vec::new()),
            Some(connection) => sql::all(connection, "SELECT * FROM windows", &[]),
        })?;
        Ok(keyed(rows))
    }

    /// `save_windows(rows)`: the windows counted, exactly these.
    pub fn save_windows(&self, rows: &Value) -> Result<()> {
        self.transaction(false, |connection| {
            let Some(connection) = connection else {
                return Ok(());
            };
            let mut kept: Vec<(Value, Value)> = Vec::new();
            for row in super::arming::iterate(rows)? {
                let window = family(&py::item(&row, "bucket")?, &py::item(&row, "minutes")?)?;
                kept.push(window.clone());
                let open_full = int(i64::from(sql::truthy(&py::item(&row, "open_full")?)));
                sql::exec(
                    connection,
                    "INSERT OR REPLACE INTO windows (bucket, minutes, open_reset_at, open_full, last_closed_at, \
                     resets, hits, seen_at, misses) VALUES (?,?,?,?,?,?,?,?,?)",
                    &[
                        window.0,
                        window.1,
                        py::item(&row, "open_reset_at")?,
                        open_full,
                        py::item(&row, "last_closed_at")?,
                        py::item(&row, "resets")?,
                        py::item(&row, "hits")?,
                        py::item(&row, "seen_at")?,
                        py::item(&row, "misses")?,
                    ],
                )?;
            }
            for stored in sql::tuples(connection, "SELECT bucket, minutes FROM windows", &[])? {
                if !kept
                    .iter()
                    .any(|(bucket, minutes)| py_eq(bucket, &stored[0]) && py_eq(minutes, &stored[1]))
                {
                    sql::exec(
                        connection,
                        "DELETE FROM windows WHERE bucket=? AND minutes=?",
                        &[stored[0].clone(), stored[1].clone()],
                    )?;
                }
            }
            Ok(())
        })
    }

    // ------------------------------------------------------------------ the last reading
    /// `reading()`: the one row of `readings`, or its empty form with no file.
    pub fn reading(&self) -> Result<Row> {
        let row = self.read(|connection| match connection {
            None => Ok(None),
            Some(connection) => sql::one(connection, "SELECT * FROM readings", &[]),
        })?;
        Ok(match row {
            None => READING
                .iter()
                .map(|name| (sql::key(name), Value::Null))
                .collect(),
            Some(mut row) => {
                row.shift_remove("singleton");
                row
            }
        })
    }

    /// `set_reading(**values)`: some fields of the last reading written, and nothing else of it.
    pub fn set_reading(&self, values: &[(String, Value)]) -> Result<()> {
        if values.is_empty()
            || !values
                .iter()
                .all(|(name, _)| READING.contains(&name.as_str()))
        {
            return Err(Error::state("invalid reading"));
        }
        let mut sorted: Vec<&(String, Value)> = values.iter().collect();
        sorted.sort_by(|a, b| a.0.cmp(&b.0));
        self.transaction(false, |connection| {
            let Some(connection) = connection else {
                return Ok(());
            };
            let sets: Vec<String> = sorted.iter().map(|(name, _)| format!("{name}=?")).collect();
            let parameters: Vec<Value> = sorted.iter().map(|(_, value)| value.clone()).collect();
            sql::exec(
                connection,
                &format!("UPDATE readings SET {} WHERE singleton=1", sets.join(", ")),
                &parameters,
            )?;
            Ok(())
        })
    }

    // ------------------------------------------------------------------ rules
    /// `reset_rules(capability=None, pending=True)`: still to act (`pending`), all (None) or the finished.
    pub fn reset_rules(&self, capability: &Value, pending: &Value) -> Result<Vec<Row>> {
        let mut clauses: Vec<String> = Vec::new();
        let mut arguments: Vec<Value> = Vec::new();
        if !matches!(capability, Value::Null) {
            clauses.push("capability=?".into());
            arguments.push(capability.clone());
        }
        if !matches!(pending, Value::Null) {
            let states = if sql::truthy(pending) {
                PENDING
            } else {
                FINISHED
            };
            clauses.push(format!("state IN ({})", sql::marks(states.len())));
            arguments.extend(sql::words(states));
        }
        let rows = self.read(|connection| match connection {
            None => Ok(Vec::new()),
            Some(connection) => {
                let filter = if clauses.is_empty() {
                    String::new()
                } else {
                    format!(
                        " WHERE {}",
                        clauses
                            .iter()
                            .map(|clause| format!("r.{clause}"))
                            .collect::<Vec<_>>()
                            .join(" AND ")
                    )
                };
                sql::all(
                    connection,
                    &format!("{RULE_SELECT}{filter} ORDER BY r.rule_id"),
                    &arguments,
                )
            }
        })?;
        Ok(rows.into_iter().map(rule).collect())
    }

    /// `reset_rule(rule_id)`: one rule with its record's, or None.
    pub fn reset_rule(&self, rule_id: &Value) -> Result<Option<Row>> {
        if !py::is_int(rule_id) {
            return Ok(None);
        }
        let row = self.read(|connection| match connection {
            None => Ok(None),
            Some(connection) => sql::one(
                connection,
                &format!("{RULE_SELECT} WHERE r.rule_id=?"),
                std::slice::from_ref(rule_id),
            ),
        })?;
        Ok(row.map(rule))
    }

    /// `add_reset_rule(capability, bucket, minutes, ordinal, ...)`: a new rule, counting; its id.
    #[allow(clippy::too_many_arguments)]
    pub fn add_reset_rule(
        &self,
        capability: &Value,
        bucket: &Value,
        minutes: &Value,
        ordinal: &Value,
        repeat: &Value,
        ask_first: &Value,
        thread_id: &Value,
        words: &Value,
        record_id: &Value,
        at: &Value,
    ) -> Result<i64> {
        if !py::is_word(capability, RESET_CAPABILITIES) {
            return Err(Error::state("unknown reset capability"));
        }
        let (bucket, minutes) = family(bucket, minutes)?;
        let is_credit = py::is_word(capability, &[CREDIT]);
        let ordinal_fits = py::small(ordinal).is_some_and(|ordinal| (0..10).contains(&ordinal));
        if !ordinal_fits || (py::small(ordinal) == Some(0) && !is_credit) {
            return Err(Error::refused(refusal::OCCASION_INVALID));
        }
        let (Value::Bool(repeat), Value::Bool(ask_first)) = (repeat, ask_first) else {
            return Err(Error::state("invalid rule"));
        };
        let message = py::is_word(capability, &[MESSAGE]);
        if message {
            py::thread(thread_id)?;
            py::key(record_id, "record id")?;
            let fits =
                py::length(words).is_some_and(|length| 0 < length && length as i64 <= WORDS_LIMIT);
            if !fits || *repeat {
                return Err(Error::refused(refusal::MESSAGE_REFUSED));
            }
        } else if !matches!(thread_id, Value::Null)
            || !matches!(words, Value::Null)
            || !matches!(record_id, Value::Null)
        {
            return Err(Error::state(
                "a credit's rule holds no conversation and no words",
            ));
        }
        let now = self.now(at)?;
        self.writing(|connection| {
            let mut parameters = vec![capability.clone()];
            parameters.extend(pending_words());
            let waiting = sql::number(
                connection,
                "SELECT count(*) FROM reset_rules WHERE capability=? AND state IN (?,?,?)",
                &parameters,
            )?;
            if waiting >= if message { MESSAGES_LIMIT } else { CREDIT_RULES_LIMIT } {
                return Err(Error::refused(refusal::RESETS_FULL));
            }
            if message {
                let mut parameters = vec![thread_id.clone()];
                parameters.extend(pending_words());
                if sql::exists(
                    connection,
                    "SELECT 1 FROM reset_rules r JOIN records c ON c.record_id = r.record_id WHERE c.thread_id=? \
                     AND r.state IN (?,?,?)",
                    &parameters,
                )? {
                    return Err(Error::refused(refusal::ALREADY_SCHEDULED));
                }
                if sql::exists(connection, "SELECT 1 FROM records WHERE record_id=?", std::slice::from_ref(record_id))? {
                    return Err(Error::state("record id taken"));
                }
                sql::exec(
                    connection,
                    "INSERT INTO records (record_id, capability, thread_id, state, created_at, claims) \
                     VALUES (?,?,?,?,?,0)",
                    &[
                        record_id.clone(),
                        string(MESSAGE),
                        thread_id.clone(),
                        string(record_state::WAITING),
                        float(now),
                    ],
                )?;
            }
            sql::insert(
                connection,
                "INSERT INTO reset_rules (capability, bucket, minutes, ordinal, repeat, ask_first, record_id, words, \
                 created_at, state) VALUES (?,?,?,?,?,?,?,?,?,?)",
                &[
                    capability.clone(),
                    bucket.clone(),
                    minutes.clone(),
                    ordinal.clone(),
                    int(i64::from(*repeat)),
                    int(i64::from(*ask_first)),
                    record_id.clone(),
                    words.clone(),
                    float(now),
                    string(rule_state::COUNTING),
                ],
            )
        })
    }

    /// `change_rule(rule_id, expect=None, **changes)`: some fields of one rule written, only while it is still
    /// `expect`; whether it was.
    pub fn change_rule(&self, rule_id: &Value, expect: &Value, changes: &Changes) -> Result<bool> {
        if !py::is_int(rule_id)
            || changes.is_empty()
            || !changes
                .iter()
                .all(|(name, _)| CHANGES.contains(&name.as_str()))
        {
            return Err(Error::state("invalid rule change"));
        }
        let mut values: Vec<(String, Value)> = changes.clone();
        let set = |values: &mut Vec<(String, Value)>, name: &str, value: Value| {
            if let Some(entry) = values.iter_mut().find(|(each, _)| each == name) {
                entry.1 = value;
            } else {
                values.push((name.to_string(), value));
            }
        };
        let get = |values: &Vec<(String, Value)>, name: &str| {
            values
                .iter()
                .find(|(each, _)| each == name)
                .map(|(_, value)| value.clone())
        };
        if let Some(state) = get(&values, "state") {
            let word = py::closed(&state, rule_state::ALL, "rule state")?;
            set(&mut values, "state", string(word));
        }
        if let Some(reason) = get(&values, "reason")
            && !matches!(reason, Value::Null)
        {
            let word = py::closed(&reason, rule_reason::ALL, "rule reason")?;
            set(&mut values, "reason", string(word));
        }
        for name in ["gate", "gate_reason"] {
            if let Some(value) = get(&values, name) {
                let word = gate_word(&value)?;
                set(&mut values, name, word);
            }
        }
        for name in TIMES {
            if let Some(value) = get(&values, name)
                && !matches!(value, Value::Null)
            {
                let time = py::timestamp(&value, name)?;
                set(&mut values, name, float(time));
            }
        }
        if let Some(base) = get(&values, "base")
            && !matches!(base, Value::Null)
            && !py::small(&base).is_some_and(|base| base >= 0)
            && !(py::is_int(&base) && !base_negative(&base))
        {
            return Err(Error::state("invalid base"));
        }
        if let Some(ordinal) = get(&values, "ordinal")
            && !py::small(&ordinal).is_some_and(|ordinal| (0..10).contains(&ordinal))
        {
            return Err(Error::state("invalid ordinal"));
        }
        if get(&values, "state").is_some_and(|state| py::is_word(&state, FINISHED)) {
            set(&mut values, "words", Value::Null);
        }
        let expected: Vec<Value> = match expect {
            Value::Str(_) => vec![string(&py::py_str(expect))],
            other if sql::truthy(other) => super::arming::iterate(other)?
                .iter()
                .map(|each| string(&py::py_str(each)))
                .collect(),
            _ => pending_words(),
        };
        values.sort_by(|a, b| a.0.cmp(&b.0));
        self.transaction(false, |connection| {
            let Some(connection) = connection else {
                return Ok(false);
            };
            let sets: Vec<String> = values.iter().map(|(name, _)| format!("{name}=?")).collect();
            let mut parameters: Vec<Value> =
                values.iter().map(|(_, value)| value.clone()).collect();
            parameters.push(rule_id.clone());
            parameters.extend(expected.iter().cloned());
            Ok(sql::exec(
                connection,
                &format!(
                    "UPDATE reset_rules SET {} WHERE rule_id=? AND state IN ({})",
                    sets.join(", "),
                    sql::marks(expected.len())
                ),
                &parameters,
            )? == 1)
        })
    }

    /// `end_rule(rule_id, state, reason, at=None)`: a rule finished, its words gone, its message's record with it.
    pub fn end_rule(
        &self,
        rule_id: &Value,
        state: &Value,
        reason: &Value,
        at: &Value,
    ) -> Result<bool> {
        let state = py::closed(state, rule_state::ALL, "rule state")?;
        if !FINISHED.contains(&state) {
            return Err(Error::state("not an end"));
        }
        let reason = py::closed(reason, rule_reason::ALL, "rule reason")?;
        let now = self.now(at)?;
        self.transaction(false, |connection| {
            let Some(connection) = connection else {
                return Ok(false);
            };
            let mut parameters = vec![rule_id.clone()];
            parameters.extend(pending_words());
            let row = sql::one(
                connection,
                "SELECT record_id FROM reset_rules WHERE rule_id=? AND state IN (?,?,?)",
                &parameters,
            )?;
            let Some(row) = row else { return Ok(false) };
            sql::exec(
                connection,
                "UPDATE reset_rules SET state=?, reason=?, words=NULL, finished_at=? WHERE rule_id=?",
                &[string(state), string(reason), float(now), rule_id.clone()],
            )?;
            let record = sql::get(&row, "record_id");
            if !matches!(record, Value::Null) {
                let to = if state == rule_state::DONE {
                    record_state::FINISHED
                } else {
                    record_state::CANCELLED
                };
                sql::exec(
                    connection,
                    "UPDATE records SET state=?, finished_at=? WHERE record_id=? AND state<>?",
                    &[string(to), float(now), record.clone(), string(record_state::FINISHED)],
                )?;
            }
            Ok(true)
        })
    }

    /// `cancel_reset_rule(rule_id, at=None)`: a person's Cancel - "cancelled", or "withdrawing" for a message
    /// already in Codex's queue.
    pub fn cancel_reset_rule(&self, rule_id: &Value, at: &Value) -> Result<&'static str> {
        let now = self.now(at)?;
        self.transaction(false, |connection| {
            let row = match connection {
                None => None,
                Some(connection) => sql::one(
                    connection,
                    "SELECT r.state, r.record_id, r.launching_at, r.sent_at, c.state AS record_state FROM reset_rules r \
                     LEFT JOIN records c ON c.record_id = r.record_id WHERE r.rule_id=?",
                    &[if py::is_int(rule_id) { rule_id.clone() } else { int(-1) }],
                )?,
            };
            let (Some(connection), Some(row)) = (connection, row) else {
                return Err(Error::refused(refusal::UNKNOWN_RULE));
            };
            if !py::is_word(sql::get(&row, "state"), PENDING) {
                return Err(Error::refused(refusal::UNKNOWN_RULE));
            }
            let in_flight = py::is_word(sql::get(&row, "record_state"), &[record_state::IN_FLIGHT]);
            if in_flight && !matches!(sql::get(&row, "sent_at"), Value::Null) {
                sql::exec(
                    connection,
                    "UPDATE records SET withdraw=1 WHERE record_id=? AND state=?",
                    &[sql::get(&row, "record_id").clone(), string(record_state::IN_FLIGHT)],
                )?;
                return Ok("withdrawing");
            }
            if !matches!(sql::get(&row, "launching_at"), Value::Null) || in_flight {
                return Err(Error::refused(refusal::BEING_SENT));
            }
            sql::exec(
                connection,
                "UPDATE reset_rules SET state=?, reason=?, words=NULL, finished_at=? WHERE rule_id=?",
                &[
                    string(rule_state::CANCELLED),
                    string(rule_reason::BY_PERSON),
                    float(now),
                    rule_id.clone(),
                ],
            )?;
            let record = sql::get(&row, "record_id");
            if !matches!(record, Value::Null) {
                sql::exec(
                    connection,
                    "UPDATE records SET state=?, finished_at=? WHERE record_id=?",
                    &[string(record_state::CANCELLED), float(now), record.clone()],
                )?;
            }
            Ok("cancelled")
        })
    }

    /// `end_messages_in(thread_id, at=None)`: every message still to be sent to `thread_id` cancelled; how many.
    pub fn end_messages_in(&self, thread_id: &Value, at: &Value) -> Result<i64> {
        py::thread(thread_id)?;
        let now = self.now(at)?;
        self.transaction(false, |connection| {
            let Some(connection) = connection else {
                return Ok(0);
            };
            let mut parameters = vec![string(MESSAGE), thread_id.clone(), string(record_state::WAITING)];
            parameters.extend(pending_words());
            let rows = sql::tuples(
                connection,
                "SELECT r.rule_id, r.record_id FROM reset_rules r JOIN records c ON c.record_id = r.record_id \
                 WHERE r.capability=? AND c.thread_id=? AND c.state=? AND r.launching_at IS NULL AND r.state IN (?,?,?)",
                &parameters,
            )?;
            for row in &rows {
                sql::exec(
                    connection,
                    "UPDATE reset_rules SET state=?, reason=?, words=NULL, finished_at=? WHERE rule_id=?",
                    &[
                        string(rule_state::CANCELLED),
                        string(rule_reason::CONVERSATION_OFF),
                        float(now),
                        row[0].clone(),
                    ],
                )?;
                sql::exec(
                    connection,
                    "UPDATE records SET state=?, finished_at=? WHERE record_id=?",
                    &[string(record_state::CANCELLED), float(now), row[1].clone()],
                )?;
            }
            Ok(rows.len() as i64)
        })
    }

    /// `record_moved(record_id, move, gate=None, reason=None, at=None, queue_id=None)`: what core told of a
    /// message's record (P14); {capability, trip}, or None where it is no message of this file's.
    #[allow(clippy::too_many_arguments)]
    pub fn record_moved(
        &self,
        record_id: &Value,
        movement: &Value,
        gate: &Value,
        reason: &Value,
        at: &Value,
        queue_id: &Value,
    ) -> Result<Option<Row>> {
        py::key(record_id, "record id")?;
        let movement = py::py_str(movement);
        let now = self.now(at)?;
        self.transaction(false, |connection| {
            let Some(connection) = connection else {
                return Ok(None);
            };
            let row = sql::one(
                connection,
                "SELECT r.rule_id, r.capability, r.state, r.gate, r.gate_reason, r.words, r.launching_at, \
                 c.state AS record_state FROM reset_rules r JOIN records c ON c.record_id = r.record_id \
                 WHERE r.record_id=?",
                std::slice::from_ref(record_id),
            )?;
            let Some(row) = row else { return Ok(None) };
            if !py::is_word(sql::get(&row, "state"), PENDING) {
                return Ok(None);
            }
            let rule_id = sql::get(&row, "rule_id").clone();
            let done = |state: &str, why: &str, record: &str, withdraw: bool| -> Result<()> {
                sql::exec(
                    connection,
                    "UPDATE reset_rules SET state=?, reason=?, words=NULL, finished_at=? WHERE rule_id=?",
                    &[string(state), string(why), float(now), rule_id.clone()],
                )?;
                sql::exec(
                    connection,
                    if withdraw {
                        "UPDATE records SET state=?, finished_at=?, withdraw=0 WHERE record_id=?"
                    } else {
                        "UPDATE records SET state=?, finished_at=? WHERE record_id=?"
                    },
                    &[string(record), float(now), record_id.clone()],
                )?;
                Ok(())
            };
            match movement.as_str() {
                "waiting" => {
                    paced_wait(connection, record_id, gate, reason, now)?;
                    let (gate, reason) = (gate_word(gate)?, gate_word(reason)?);
                    if !(py_eq(sql::get(&row, "gate"), &gate) && py_eq(sql::get(&row, "gate_reason"), &reason)) {
                        sql::exec(
                            connection,
                            "UPDATE reset_rules SET gate=?, gate_reason=? WHERE rule_id=?",
                            &[gate, reason, rule_id.clone()],
                        )?;
                    }
                }
                "released" | "not_started" => {
                    sql::exec(
                        connection,
                        "UPDATE records SET state=?, finished_at=NULL WHERE record_id=? AND state=?",
                        &[
                            string(record_state::WAITING),
                            record_id.clone(),
                            string(record_state::IN_FLIGHT),
                        ],
                    )?;
                    let why = if movement == "not_started" {
                        string(rule_reason::NOT_STARTED)
                    } else {
                        Value::Null
                    };
                    sql::exec(
                        connection,
                        "UPDATE reset_rules SET launching_at=NULL, reason=? WHERE rule_id=?",
                        &[why, rule_id.clone()],
                    )?;
                }
                "sent" => {
                    sql::exec(
                        connection,
                        "UPDATE reset_rules SET words=NULL, sent_at=coalesce(launching_at, ?), \
                         launching_at=coalesce(launching_at, ?) WHERE rule_id=?",
                        &[float(now), float(now), rule_id.clone()],
                    )?;
                    if py::length(queue_id) == Some(36) {
                        sql::exec(
                            connection,
                            "UPDATE records SET queue_id=? WHERE record_id=?",
                            &[queue_id.clone(), record_id.clone()],
                        )?;
                    }
                }
                "handed_over" | "superseded" => {
                    let why = if movement == "handed_over" {
                        rule_reason::HANDED_OVER
                    } else {
                        rule_reason::SUPERSEDED
                    };
                    done(rule_state::DONE, why, record_state::FINISHED, false)?;
                }
                "withdrawn" => done(
                    rule_state::CANCELLED,
                    rule_reason::WITHDRAWN,
                    record_state::CANCELLED,
                    true,
                )?,
                "withdraw_refused" => {
                    sql::exec(
                        connection,
                        "UPDATE reset_rules SET reason=? WHERE rule_id=?",
                        &[string(rule_reason::WITHDRAW_REFUSED), rule_id.clone()],
                    )?;
                    sql::exec(
                        connection,
                        "UPDATE records SET withdraw=0 WHERE record_id=?",
                        std::slice::from_ref(record_id),
                    )?;
                }
                "delivered" | "unproven" => {
                    let why = if movement == "delivered" {
                        rule_reason::DELIVERED
                    } else {
                        rule_reason::UNKNOWN
                    };
                    done(rule_state::DONE, why, record_state::FINISHED, false)?;
                }
                _ => return Ok(None),
            }
            Ok(Some(moved(sql::get(&row, "capability").clone(), movement == "unproven")))
        })
    }

    /// `release_unlaunched(at=None)`: every message claimed UNLAUNCHED_AFTER ago whose launch never began, handed
    /// back; how many.
    pub fn release_unlaunched(&self, at: &Value) -> Result<i64> {
        let now = self.now(at)?;
        self.transaction(false, |connection| {
            let Some(connection) = connection else {
                return Ok(0);
            };
            let keys = sql::tuples(
                connection,
                "SELECT c.record_id FROM reset_rules r JOIN records c ON c.record_id = r.record_id WHERE r.capability=? \
                 AND r.state=? AND r.launching_at IS NULL AND r.sent_at IS NULL AND r.words IS NOT NULL AND c.state=? \
                 AND c.claimed_at IS NOT NULL AND c.claimed_at <= ?",
                &[
                    string(MESSAGE),
                    string(rule_state::READY),
                    string(record_state::IN_FLIGHT),
                    float(now - UNLAUNCHED_AFTER),
                ],
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

    /// `carry_message(rule_id, at=None)`: a message the forced stop's turn carries - its record in flight and its
    /// rule launching, in one transaction.
    pub fn carry_message(&self, rule_id: &Value, at: &Value) -> Result<bool> {
        let now = self.now(at)?;
        let rule_id = if py::is_int(rule_id) {
            rule_id.clone()
        } else {
            int(-1)
        };
        self.transaction(false, |connection| {
            let Some(connection) = connection else {
                return Ok(false);
            };
            let row = sql::one(
                connection,
                "SELECT r.record_id FROM reset_rules r JOIN records c ON c.record_id = r.record_id WHERE r.rule_id=? \
                 AND r.capability=? AND r.state=? AND r.launching_at IS NULL AND r.sent_at IS NULL \
                 AND r.words IS NOT NULL AND c.state=?",
                &[
                    rule_id.clone(),
                    string(MESSAGE),
                    string(rule_state::READY),
                    string(record_state::WAITING),
                ],
            )?;
            let Some(row) = row else { return Ok(false) };
            sql::exec(
                connection,
                "UPDATE records SET state=?, claimed_at=?, claims=claims+1 WHERE record_id=? AND state=?",
                &[
                    string(record_state::IN_FLIGHT),
                    float(now),
                    sql::get(&row, "record_id").clone(),
                    string(record_state::WAITING),
                ],
            )?;
            sql::exec(
                connection,
                "UPDATE reset_rules SET launching_at=? WHERE rule_id=?",
                &[float(now), rule_id.clone()],
            )?;
            Ok(true)
        })
    }

    /// `carried_message(rule_id, started, at=None)`: what came of that launch.
    pub fn carried_message(&self, rule_id: &Value, started: &Value, at: &Value) -> Result<bool> {
        let now = self.now(at)?;
        let original = rule_id.clone();
        let rule_id = if py::is_int(rule_id) {
            rule_id.clone()
        } else {
            int(-1)
        };
        self.transaction(false, |connection| {
            let Some(connection) = connection else {
                return Ok(false);
            };
            let row = sql::one(
                connection,
                "SELECT r.record_id FROM reset_rules r JOIN records c ON c.record_id = r.record_id WHERE r.rule_id=? \
                 AND r.capability=? AND r.state=? AND r.launching_at IS NOT NULL AND c.state=?",
                &[
                    rule_id.clone(),
                    string(MESSAGE),
                    string(rule_state::READY),
                    string(record_state::IN_FLIGHT),
                ],
            )?;
            let Some(row) = row else { return Ok(false) };
            if sql::truthy(started) {
                sql::exec(
                    connection,
                    "UPDATE reset_rules SET words=NULL, sent_at=coalesce(sent_at, launching_at, ?) WHERE rule_id=?",
                    &[float(now), original.clone()],
                )?;
            } else {
                sql::exec(
                    connection,
                    "UPDATE records SET state=?, finished_at=NULL WHERE record_id=? AND state=?",
                    &[
                        string(record_state::WAITING),
                        sql::get(&row, "record_id").clone(),
                        string(record_state::IN_FLIGHT),
                    ],
                )?;
                sql::exec(
                    connection,
                    "UPDATE reset_rules SET launching_at=NULL WHERE rule_id=?",
                    std::slice::from_ref(&original),
                )?;
            }
            Ok(true)
        })
    }

    /// `messages_in_flight()`: every message whose record is in flight.
    pub fn messages_in_flight(&self) -> Result<Vec<Row>> {
        Ok(self
            .reset_rules(&string(MESSAGE), &Value::Bool(true))?
            .into_iter()
            .filter(|rule| py::is_word(sql::get(rule, "record_state"), &[record_state::IN_FLIGHT]))
            .collect())
    }

    // ------------------------------------------------------------------ spends
    /// `add_credit_spend(rule_id, bucket, minutes, occasion, key, at=None)`: its id, or None where this filling of
    /// the window has one already.
    #[allow(clippy::too_many_arguments)]
    pub fn add_credit_spend(
        &self,
        rule_id: &Value,
        bucket: &Value,
        minutes: &Value,
        occasion: &Value,
        key: &Value,
        at: &Value,
    ) -> Result<Option<i64>> {
        let (bucket, minutes) = family(bucket, minutes)?;
        let occasion_ok =
            matches!(occasion, Value::Int(number) if !number.to_string().starts_with('-'));
        if !py::is_int(rule_id) || !occasion_ok {
            return Err(Error::state("invalid spend"));
        }
        if py::length(key) != Some(36) {
            return Err(Error::state("invalid key"));
        }
        let now = self.now(at)?;
        self.writing(|connection| {
            if sql::exists(
                connection,
                "SELECT 1 FROM credit_spends WHERE bucket=? AND minutes=? AND occasion=?",
                &[bucket.clone(), minutes.clone(), occasion.clone()],
            )? {
                return Ok(None);
            }
            Ok(Some(sql::insert(
                connection,
                "INSERT INTO credit_spends (rule_id, bucket, minutes, occasion, attempt_id, created_at, tries) \
                 VALUES (?,?,?,?,?,?,1)",
                &[
                    rule_id.clone(),
                    bucket.clone(),
                    minutes.clone(),
                    occasion.clone(),
                    key.clone(),
                    float(now),
                ],
            )?))
        })
    }

    /// `finish_credit_spend(spend_id, outcome, at=None)`.
    pub fn finish_credit_spend(
        &self,
        spend_id: &Value,
        outcome: &Value,
        at: &Value,
    ) -> Result<bool> {
        let outcome = py::closed(outcome, spend_outcome::ALL, "spend outcome")?;
        let now = self.now(at)?;
        self.transaction(false, |connection| match connection {
            None => Ok(false),
            Some(connection) => Ok(sql::exec(
                connection,
                "UPDATE credit_spends SET outcome=?, finished_at=? WHERE spend_id=? AND outcome IS NULL",
                &[string(outcome), float(now), spend_id.clone()],
            )? == 1),
        })
    }

    /// `retry_credit_spend(spend_id)`: the one retry of a spend whose outcome is not known.
    pub fn retry_credit_spend(&self, spend_id: &Value) -> Result<bool> {
        self.transaction(false, |connection| match connection {
            None => Ok(false),
            Some(connection) => Ok(sql::exec(
                connection,
                "UPDATE credit_spends SET tries=2 WHERE spend_id=? AND tries=1 AND outcome IS NULL",
                std::slice::from_ref(spend_id),
            )? == 1),
        })
    }

    /// `drop_credit_spend(spend_id)`: a spend Codex was never asked for, taken away.
    pub fn drop_credit_spend(&self, spend_id: &Value) -> Result<bool> {
        self.transaction(false, |connection| match connection {
            None => Ok(false),
            Some(connection) => Ok(sql::exec(
                connection,
                "DELETE FROM credit_spends WHERE spend_id=? AND outcome IS NULL AND tries=1",
                std::slice::from_ref(spend_id),
            )? == 1),
        })
    }

    /// `credit_spends(since=None)`: the spends, newest first.
    pub fn credit_spends(&self, since: &Value) -> Result<Vec<Row>> {
        let since = if matches!(since, Value::Null) {
            float(f64::NEG_INFINITY)
        } else {
            since.clone()
        };
        self.read(|connection| match connection {
            None => Ok(Vec::new()),
            Some(connection) => sql::all(
                connection,
                "SELECT * FROM credit_spends WHERE created_at >= ? ORDER BY spend_id DESC",
                &[since],
            ),
        })
    }
}

fn base_negative(base: &Value) -> bool {
    matches!(base, Value::Int(number) if number.to_string().starts_with('-'))
}

/// `{"capability": ..., "trip": ...}` of a record's move.
pub fn moved(capability: Value, trip: bool) -> Row {
    let mut found = Row::new();
    found.insert(sql::key("capability"), capability);
    found.insert(sql::key("trip"), Value::Bool(trip));
    found
}

/// Rows keyed by (bucket, minutes), in their order.
pub fn keyed(rows: Vec<Row>) -> Vec<((Value, Value), Row)> {
    let mut found: Vec<((Value, Value), Row)> = Vec::new();
    for row in rows {
        let key = (
            sql::get(&row, "bucket").clone(),
            sql::get(&row, "minutes").clone(),
        );
        match found
            .iter_mut()
            .find(|(each, _)| py_eq(&each.0, &key.0) && py_eq(&each.1, &key.1))
        {
            Some(entry) => entry.1 = row,
            None => found.push((key, row)),
        }
    }
    found
}

/// `end_pending(connection, capabilities, now)`: every rule still to act of those that are reset actions, cancelled
/// with its words, in the caller's transaction.
pub fn end_pending(connection: &Connection, capabilities: &[Value], now: f64) -> Result<()> {
    let ended: Vec<Value> = capabilities
        .iter()
        .filter(|capability| py::is_word(capability, RESET_CAPABILITIES))
        .cloned()
        .collect();
    if ended.is_empty() {
        return Ok(());
    }
    let mut parameters = ended.clone();
    parameters.extend(pending_words());
    parameters.push(string(record_state::IN_FLIGHT));
    let rows = sql::tuples(
        connection,
        &format!(
            "SELECT r.rule_id, r.record_id FROM reset_rules r LEFT JOIN records c ON c.record_id = r.record_id \
             WHERE r.capability IN ({}) AND r.state IN (?,?,?) AND r.launching_at IS NULL \
             AND (c.state IS NULL OR c.state <> ?)",
            sql::marks(ended.len())
        ),
        &parameters,
    )?;
    for row in rows {
        sql::exec(
            connection,
            "UPDATE reset_rules SET state=?, reason=?, words=NULL, finished_at=? WHERE rule_id=?",
            &[
                string(rule_state::CANCELLED),
                string(rule_reason::TURNED_OFF),
                float(now),
                row[0].clone(),
            ],
        )?;
        if !matches!(row[1], Value::Null) {
            sql::exec(
                connection,
                "UPDATE records SET state=?, finished_at=? WHERE record_id=? AND state<>?",
                &[
                    string(record_state::CANCELLED),
                    float(now),
                    row[1].clone(),
                    string(record_state::FINISHED),
                ],
            )?;
        }
    }
    if ended
        .iter()
        .any(|capability| py::is_word(capability, &[CREDIT]))
    {
        sql::exec(
            connection,
            "UPDATE readings SET credits=NULL, expiry_known=NULL, nearest_expiry=NULL",
            &[],
        )?;
    }
    Ok(())
}

/// `prune(connection, now, max_age, limit)`: the reset actions' bounds, in the journal's one pass.
pub fn prune(connection: &Connection, now: f64, max_age: f64, limit: i64) -> Result<()> {
    let finished = format!(
        "state IN ('{}', '{}')",
        rule_state::DONE,
        rule_state::CANCELLED
    );
    sql::exec(
        connection,
        &format!(
            "DELETE FROM reset_rules WHERE {finished} AND coalesce(finished_at, created_at) < ?"
        ),
        &[float(now - max_age)],
    )?;
    let excess = sql::number(connection, "SELECT count(*) FROM reset_rules", &[])? - limit;
    if excess > 0 {
        sql::exec(
            connection,
            &format!(
                "DELETE FROM reset_rules WHERE rule_id IN (SELECT rule_id FROM reset_rules WHERE {finished} \
                 ORDER BY rule_id LIMIT ?)"
            ),
            &[int(excess)],
        )?;
    }
    let week = now - 7.0 * 86400.0;
    sql::exec(
        connection,
        "DELETE FROM credit_spends WHERE created_at < ? AND created_at < ?",
        &[float(now - max_age), float(week)],
    )?;
    let excess = sql::number(connection, "SELECT count(*) FROM credit_spends", &[])? - limit;
    if excess > 0 {
        sql::exec(
            connection,
            "DELETE FROM credit_spends WHERE spend_id IN (SELECT spend_id FROM credit_spends WHERE created_at < ? \
             ORDER BY spend_id LIMIT ?)",
            &[float(week), int(excess)],
        )?;
    }
    Ok(())
}
