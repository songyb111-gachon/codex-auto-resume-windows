//! A person's queued prompts (`state/prompts.py`): after the turn now running, at a time, or on a schedule - their
//! words only while one is still to go.

use car_machine::json::Value;
use car_machine::pyval;
use rusqlite::Connection;

use super::errors::{Error, Result};
use super::py;
use super::resets::{gate_word, paced_wait};
use super::schema::{PROMPT_SPAN, WORDS_MOST};
use super::session::AdvancedState;
use super::sql::{self, Row, float, int, py_eq, string};
use crate::vocabulary::{
    PromptEvery, PromptReason, PromptState, PromptTrigger, RecordState, Refusal, WhileRunning,
};

pub const PROMPT_QUEUE: &str = "prompt_queue";
pub const PENDING: &[&str] = &[
    PromptState::Waiting.as_str(),
    PromptState::Ready.as_str(),
    PromptState::Held.as_str(),
];
pub const PROMPTS_LIMIT: usize = 50;
pub const PER_CONVERSATION: usize = 20;
pub const WORDS_LIMIT: i64 = WORDS_MOST;
pub const CHANGES: &[&str] = &[
    "state",
    "reason",
    "record_id",
    "gate",
    "gate_reason",
    "due_at",
    "launching_at",
    "sent_at",
    "finished_at",
    "sent_count",
];
pub const COMPLETED: &[&str] = &[
    PromptReason::Delivered.as_str(),
    PromptReason::HandedOver.as_str(),
];
pub const CLEAR_MOST: usize = 5000;
pub const DAY: i64 = 86400;

/// `PERIODS[PromptEvery(every)]`.
fn period(every: &Value) -> Result<i64> {
    match py::text(every).and_then(PromptEvery::parse) {
        Some(PromptEvery::Day) => Ok(DAY),
        Some(PromptEvery::Week) => Ok(7 * DAY),
        _ => Err(Error::python("ValueError", "not a valid PromptEvery")),
    }
}

/// `_ENDS`: how a move of an occurrence's record ends that occurrence.
fn ends(movement: &str) -> Option<(&'static str, &'static str)> {
    Some(match movement {
        "delivered" => (
            PromptReason::Delivered.as_str(),
            RecordState::Finished.as_str(),
        ),
        "unproven" => (
            PromptReason::Unknown.as_str(),
            RecordState::Finished.as_str(),
        ),
        "superseded" => (
            PromptReason::Superseded.as_str(),
            RecordState::Finished.as_str(),
        ),
        "handed_over" => (
            PromptReason::HandedOver.as_str(),
            RecordState::Finished.as_str(),
        ),
        _ => return None,
    })
}

/// `_prompt(row)`: a prompt's row with its flags as booleans.
fn prompt_row(mut row: Row) -> Row {
    let depends = sql::truthy(sql::get(&row, "depends"));
    row.insert(sql::key("depends"), Value::Bool(depends));
    if row.contains_key("withdraw") {
        let withdraw = sql::truthy(sql::get(&row, "withdraw"));
        row.insert(sql::key("withdraw"), Value::Bool(withdraw));
    }
    row
}

/// `not words.strip()`: whether a text holds only white space.
fn blank(text: &car_machine::json::Str) -> bool {
    text.code_points()
        .all(|point| char::from_u32(point).is_some_and(car_machine::pytext::is_space))
}

/// What `_occasion` gives: (trigger, every, while_running, due, until).
type Occasion = (
    &'static str,
    Option<&'static str>,
    &'static str,
    f64,
    Option<f64>,
);

/// `_occasion(words, trigger, at, every, occurrences, until, while_running, current)`.
#[allow(clippy::too_many_arguments)]
fn occasion(
    words: &Value,
    trigger: &Value,
    at: &Value,
    every: &Value,
    occurrences: &Value,
    until: &Value,
    running: &Value,
    current: f64,
) -> Result<Occasion> {
    let fits = match words {
        Value::Str(text) => !blank(text) && text.len() as i64 <= WORDS_LIMIT,
        _ => false,
    };
    if !fits {
        return Err(Error::refused(Refusal::PromptRefused.as_str()));
    }
    let invalid = || Error::refused(Refusal::OccasionInvalid.as_str());
    let trigger = py::closed(trigger, PromptTrigger::ALL, "trigger").map_err(|_| invalid())?;
    let every = py::closed_or_none(every, PromptEvery::ALL, "every").map_err(|_| invalid())?;
    let running = py::closed(running, WhileRunning::ALL, "while_running").map_err(|_| invalid())?;
    if trigger == PromptTrigger::AfterTurn.as_str() && running != WhileRunning::Queue.as_str() {
        return Err(invalid());
    }
    let (shaped, due) = if trigger == PromptTrigger::AfterTurn.as_str() {
        (
            matches!(at, Value::Null)
                && every.is_none()
                && py_eq(occurrences, &int(1))
                && matches!(until, Value::Null),
            Value::Float(current),
        )
    } else {
        let count = py::small(occurrences).filter(|count| (1..31).contains(count));
        (
            !matches!(at, Value::Null)
                && every.is_some() == (trigger == PromptTrigger::Recurring.as_str())
                && count.is_some()
                && (count == Some(1) || trigger == PromptTrigger::Recurring.as_str()),
            at.clone(),
        )
    };
    let due = match py::timestamp(&due, "time") {
        Ok(due) => due,
        Err(Error::State { .. }) => return Err(invalid()),
        Err(other) => return Err(other),
    };
    let until = match until {
        Value::Null => None,
        other => match py::timestamp(other, "until") {
            Ok(until) => Some(until),
            Err(Error::State { .. }) => return Err(invalid()),
            Err(other) => return Err(other),
        },
    };
    if !shaped
        || (trigger != PromptTrigger::AfterTurn.as_str() && due < current - 60.0)
        || until.is_some_and(|until| !(current < until && until <= current + PROMPT_SPAN as f64))
    {
        return Err(invalid());
    }
    Ok((trigger, every, running, due, until))
}

/// The keywords of `add_prompt` and `edit_prompt` beside the words and the trigger.
#[derive(Clone, Debug)]
pub struct When {
    pub at: Value,
    pub every: Value,
    pub occurrences: Value,
    pub until: Value,
    pub depends: Value,
    pub while_running: Value,
    pub now: Value,
    pub held: Value,
}

impl Default for When {
    fn default() -> When {
        When {
            at: Value::Null,
            every: Value::Null,
            occurrences: int(1),
            until: Value::Null,
            depends: Value::Bool(false),
            while_running: string(WhileRunning::Queue.as_str()),
            now: Value::Null,
            held: Value::Bool(false),
        }
    }
}

const SELECT: &str = "SELECT p.*, c.state AS record_state, c.queue_id AS queue_id, c.withdraw AS withdraw, \
    c.created_at AS waiting_since FROM prompts p LEFT JOIN records c ON c.record_id = p.record_id";

fn pending_words() -> Vec<Value> {
    sql::words(PENDING)
}

impl AdvancedState {
    /// `add_prompt(thread_id, words, trigger, ...)`: a person's prompt, waiting, last in its conversation's queue.
    pub fn add_prompt(
        &self,
        thread_id: &Value,
        words: &Value,
        trigger: &Value,
        when: &When,
    ) -> Result<i64> {
        py::thread(thread_id)?;
        let current = self.now(&when.now)?;
        let (trigger, every, running, due, until) = occasion(
            words,
            trigger,
            &when.at,
            &when.every,
            &when.occurrences,
            &when.until,
            &when.while_running,
            current,
        )?;
        self.writing(|connection| {
            let waiting = sql::tuples(
                connection,
                "SELECT thread_id FROM prompts WHERE state IN (?,?,?)",
                &pending_words(),
            )?;
            let mine = waiting.iter().filter(|row| py_eq(&row[0], thread_id)).count();
            if waiting.len() >= PROMPTS_LIMIT || mine >= PER_CONVERSATION {
                return Err(Error::refused(Refusal::QueueFull.as_str()));
            }
            let last = sql::scalar(
                connection,
                "SELECT max(position) FROM prompts WHERE thread_id=?",
                std::slice::from_ref(thread_id),
            )?;
            if sql::truthy(&when.depends) && matches!(last, Value::Null) {
                return Err(Error::refused(Refusal::DependencyUnknown.as_str()));
            }
            let position = if matches!(last, Value::Null) {
                int(0)
            } else {
                py::plus_one(&last)?
            };
            sql::insert(
                connection,
                "INSERT INTO prompts (thread_id, words, trigger, at, every, occurrences, sent_count, until, depends, \
                 position, state, created_at, due_at, while_running) VALUES (?,?,?,?,?,?,0,?,?,?,?,?,?,?)",
                &[
                    thread_id.clone(),
                    words.clone(),
                    string(trigger),
                    if trigger == PromptTrigger::AfterTurn.as_str() {
                        Value::Null
                    } else {
                        float(due)
                    },
                    py::word_or_null(every),
                    when.occurrences.clone(),
                    until.map_or(Value::Null, float),
                    int(i64::from(sql::truthy(&when.depends))),
                    position,
                    string(if sql::truthy(&when.held) {
                        PromptState::Held.as_str()
                    } else {
                        PromptState::Waiting.as_str()
                    }),
                    float(current),
                    float(due),
                    string(running),
                ],
            )
        })
    }

    /// `edit_prompt(prompt_id, generation, words, trigger, ...)`: a person's edit of one prompt still waiting.
    pub fn edit_prompt(
        &self,
        prompt_id: &Value,
        generation: &Value,
        words: &Value,
        trigger: &Value,
        when: &When,
    ) -> Result<()> {
        if !py::is_int(prompt_id) {
            return Err(Error::refused(Refusal::InvalidRequest.as_str()));
        }
        if !py::is_int(generation) {
            return Err(Error::refused(Refusal::StaleGeneration.as_str()));
        }
        let current = self.now(&when.now)?;
        self.transaction(false, |connection| {
            let Some(connection) = connection else {
                return Err(Error::refused(Refusal::InvalidRequest.as_str()));
            };
            if !py_eq(&sql::scalar(connection, "SELECT generation FROM meta", &[])?, generation) {
                return Err(Error::refused(Refusal::StaleGeneration.as_str()));
            }
            let row = sql::one(
                connection,
                "SELECT thread_id, position, until, sent_count FROM prompts WHERE prompt_id=? AND state=? \
                 AND record_id IS NULL AND launching_at IS NULL AND sent_at IS NULL",
                &[prompt_id.clone(), string(PromptState::Waiting.as_str())],
            )?;
            let Some(row) = row else {
                return Err(Error::refused(Refusal::InvalidRequest.as_str()));
            };
            let until = if py::py_str(trigger) == PromptTrigger::Recurring.as_str() {
                sql::get(&row, "until").clone()
            } else {
                Value::Null
            };
            let (trigger, every, running, due, until) = occasion(
                words,
                trigger,
                &when.at,
                &when.every,
                &when.occurrences,
                &until,
                &when.while_running,
                current,
            )?;
            let sent = sql::get(&row, "sent_count");
            let fewer = pyval::less(&when.occurrences, sent).map_err(|class| Error::python(class, "'<'"))?;
            if fewer || (sql::truthy(sent) && trigger != PromptTrigger::Recurring.as_str()) {
                return Err(Error::refused(Refusal::OccasionInvalid.as_str()));
            }
            if sql::truthy(&when.depends)
                && !sql::exists(
                    connection,
                    "SELECT 1 FROM prompts WHERE thread_id=? AND position<?",
                    &[sql::get(&row, "thread_id").clone(), sql::get(&row, "position").clone()],
                )?
            {
                return Err(Error::refused(Refusal::DependencyUnknown.as_str()));
            }
            sql::exec(
                connection,
                "UPDATE prompts SET words=?, trigger=?, at=?, every=?, occurrences=?, until=?, depends=?, due_at=?, \
                 while_running=?, reason=NULL, gate=NULL, gate_reason=NULL, state=? WHERE prompt_id=?",
                &[
                    words.clone(),
                    string(trigger),
                    if trigger == PromptTrigger::AfterTurn.as_str() {
                        Value::Null
                    } else {
                        float(due)
                    },
                    py::word_or_null(every),
                    when.occurrences.clone(),
                    until.map_or(Value::Null, float),
                    int(i64::from(sql::truthy(&when.depends))),
                    float(due),
                    string(running),
                    string(if sql::truthy(&when.held) {
                        PromptState::Held.as_str()
                    } else {
                        PromptState::Waiting.as_str()
                    }),
                    prompt_id.clone(),
                ],
            )?;
            Ok(())
        })
    }

    /// `placed_prompt(prompt_id)`: a prompt written held while its pictures were placed, waiting now.
    pub fn placed_prompt(&self, prompt_id: &Value) -> Result<bool> {
        if !py::is_int(prompt_id) {
            return Err(Error::state("invalid prompt id"));
        }
        self.transaction(false, |connection| match connection {
            None => Ok(false),
            Some(connection) => Ok(sql::exec(
                connection,
                "UPDATE prompts SET state=? WHERE prompt_id=? AND state=? AND reason IS NULL",
                &[
                    string(PromptState::Waiting.as_str()),
                    prompt_id.clone(),
                    string(PromptState::Held.as_str()),
                ],
            )? == 1),
        })
    }

    /// `prompts(thread_id=None, pending=True)`: the prompts in queue order.
    pub fn prompts(&self, thread_id: &Value, pending: &Value) -> Result<Vec<Row>> {
        let mut clauses: Vec<String> = Vec::new();
        let mut values: Vec<Value> = Vec::new();
        if !matches!(thread_id, Value::Null) {
            clauses.push("p.thread_id=?".into());
            values.push(py::word(py::thread(thread_id)?));
        }
        if !matches!(pending, Value::Null) {
            clauses.push(format!(
                "p.state {} (?,?,?)",
                if sql::truthy(pending) { "IN" } else { "NOT IN" }
            ));
            values.extend(pending_words());
        }
        let rows = self.read(|connection| match connection {
            None => Ok(Vec::new()),
            Some(connection) => {
                let filter = if clauses.is_empty() {
                    String::new()
                } else {
                    format!(" WHERE {}", clauses.join(" AND "))
                };
                sql::all(
                    connection,
                    &format!("{SELECT}{filter} ORDER BY p.thread_id, p.position"),
                    &values,
                )
            }
        })?;
        Ok(rows.into_iter().map(prompt_row).collect())
    }

    /// `prompt(prompt_id)`.
    pub fn prompt(&self, prompt_id: &Value) -> Result<Option<Row>> {
        if !py::is_int(prompt_id) {
            return Err(Error::state("invalid prompt id"));
        }
        let row = self.read(|connection| match connection {
            None => Ok(None),
            Some(connection) => sql::one(
                connection,
                &format!("{SELECT} WHERE p.prompt_id=?"),
                std::slice::from_ref(prompt_id),
            ),
        })?;
        Ok(row.map(prompt_row))
    }

    /// `change_prompt(prompt_id, **changes)`: some of a prompt's fields written - its words never.
    pub fn change_prompt(&self, prompt_id: &Value, changes: &[(String, Value)]) -> Result<()> {
        if !py::is_int(prompt_id)
            || changes.is_empty()
            || !changes
                .iter()
                .all(|(name, _)| CHANGES.contains(&name.as_str()))
        {
            return Err(Error::state("invalid prompt change"));
        }
        let mut values: Vec<(String, Value)> = changes.to_vec();
        for (name, value) in values.iter_mut() {
            match name.as_str() {
                "state" => *value = string(py::closed(value, PromptState::ALL, "state")?),
                "reason" if !matches!(value, Value::Null) => {
                    *value = string(py::closed(value, PromptReason::ALL, "reason")?)
                }
                _ => {}
            }
        }
        if let Some((_, record)) = values.iter().find(|(name, _)| name == "record_id")
            && !matches!(record, Value::Null)
        {
            py::key(record, "record id")?;
        }
        values.sort_by(|a, b| a.0.cmp(&b.0));
        let ending = values.iter().any(|(name, value)| {
            name == "state"
                && py::is_word(
                    value,
                    &[PromptState::Done.as_str(), PromptState::Cancelled.as_str()],
                )
        });
        self.transaction(false, |connection| {
            let Some(connection) = connection else {
                return Ok(());
            };
            let sets: Vec<String> = values.iter().map(|(name, _)| format!("{name}=?")).collect();
            let mut parameters: Vec<Value> =
                values.iter().map(|(_, value)| value.clone()).collect();
            parameters.push(prompt_id.clone());
            sql::exec(
                connection,
                &format!(
                    "UPDATE prompts SET {}{} WHERE prompt_id=?",
                    sets.join(", "),
                    if ending { ", words=NULL" } else { "" }
                ),
                &parameters,
            )?;
            Ok(())
        })
    }

    /// `cancel_prompt(prompt_id, at=None)`: "cancelled", or "withdrawing" for an occurrence already in Codex's queue.
    pub fn cancel_prompt(&self, prompt_id: &Value, at: &Value) -> Result<&'static str> {
        if !py::is_int(prompt_id) {
            return Err(Error::state("invalid prompt id"));
        }
        let now = self.now(at)?;
        self.transaction(false, |connection| {
            let row = match connection {
                None => None,
                Some(connection) => sql::one(
                    connection,
                    "SELECT p.state, p.record_id, p.launching_at, p.sent_at, c.state AS record_state FROM prompts p \
                     LEFT JOIN records c ON c.record_id = p.record_id WHERE p.prompt_id=?",
                    std::slice::from_ref(prompt_id),
                )?,
            };
            let (Some(connection), Some(row)) = (connection, row) else {
                return Err(Error::refused(Refusal::InvalidRequest.as_str()));
            };
            if !py::is_word(sql::get(&row, "state"), PENDING) {
                return Err(Error::refused(Refusal::InvalidRequest.as_str()));
            }
            let in_flight = py::is_word(sql::get(&row, "record_state"), &[RecordState::InFlight.as_str()]);
            if in_flight && !matches!(sql::get(&row, "sent_at"), Value::Null) {
                sql::exec(
                    connection,
                    "UPDATE records SET withdraw=1 WHERE record_id=? AND state=?",
                    &[sql::get(&row, "record_id").clone(), string(RecordState::InFlight.as_str())],
                )?;
                return Ok("withdrawing");
            }
            if !matches!(sql::get(&row, "launching_at"), Value::Null) || in_flight {
                return Err(Error::refused(Refusal::BeingSent.as_str()));
            }
            sql::exec(
                connection,
                "UPDATE prompts SET state=?, reason=?, words=NULL, finished_at=? WHERE prompt_id=?",
                &[
                    string(PromptState::Cancelled.as_str()),
                    string(PromptReason::ByPerson.as_str()),
                    float(now),
                    prompt_id.clone(),
                ],
            )?;
            let record = sql::get(&row, "record_id");
            if !matches!(record, Value::Null) {
                sql::exec(
                    connection,
                    "UPDATE records SET state=?, finished_at=? WHERE record_id=? AND state=?",
                    &[
                        string(RecordState::Cancelled.as_str()),
                        float(now),
                        record.clone(),
                        string(RecordState::Waiting.as_str()),
                    ],
                )?;
            }
            Ok("cancelled")
        })
    }

    /// `go_on_prompt(prompt_id, at=None)`: a person's Go on for a held prompt.
    pub fn go_on_prompt(&self, prompt_id: &Value, at: &Value) -> Result<bool> {
        if !py::is_int(prompt_id) {
            return Err(Error::state("invalid prompt id"));
        }
        let now = self.now(at)?;
        self.transaction(false, |connection| {
            let Some(connection) = connection else {
                return Ok(false);
            };
            let row = sql::one(
                connection,
                "SELECT thread_id, position, due_at, record_id, trigger, every, sent_count, occurrences, until \
                 FROM prompts WHERE prompt_id=? AND state=?",
                &[prompt_id.clone(), string(PromptState::Held.as_str())],
            )?;
            let Some(row) = row else { return Ok(false) };
            let mut parameters = vec![sql::get(&row, "thread_id").clone(), sql::get(&row, "position").clone()];
            parameters.extend(pending_words());
            let behind = sql::exists(
                connection,
                "SELECT 1 FROM prompts WHERE thread_id=? AND position<? AND state IN (?,?,?)",
                &parameters,
            )?;
            let due = sql::get(&row, "due_at");
            let later = !matches!(due, Value::Null)
                && pyval::greater(due, &Value::Float(now)).map_err(|class| Error::python(class, "'>'"))?;
            if matches!(due, Value::Null)
                || later
                || !matches!(sql::get(&row, "record_id"), Value::Null)
                || behind
            {
                return Ok(sql::exec(
                    connection,
                    "UPDATE prompts SET state=?, reason=NULL, depends=0 WHERE prompt_id=? AND state=?",
                    &[string(PromptState::Waiting.as_str()), prompt_id.clone(), string(PromptState::Held.as_str())],
                )? == 1);
            }
            if py::is_word(sql::get(&row, "trigger"), &[PromptTrigger::Recurring.as_str()])
                && !matches!(sql::get(&row, "every"), Value::Null)
            {
                let period = period(sql::get(&row, "every"))?;
                let due_at = py::minus_operand(due)?;
                let late = py::floordiv(now - due_at, period as f64) as i64;
                if late > 0 {
                    let sent = py::small(sql::get(&row, "sent_count")).unwrap_or(0);
                    let occurrences = py::small(sql::get(&row, "occurrences")).unwrap_or(0);
                    let used = (sent + late).min(occurrences);
                    let latest = due_at + (late * period) as f64;
                    let past = match sql::get(&row, "until") {
                        Value::Null => false,
                        until => py::minus_operand(until).is_ok_and(|until| latest > until),
                    };
                    if used >= occurrences || past {
                        return Ok(sql::exec(
                            connection,
                            "UPDATE prompts SET state=?, reason=?, sent_count=?, words=NULL, depends=0, finished_at=? \
                             WHERE prompt_id=? AND state=?",
                            &[
                                string(PromptState::Done.as_str()),
                                string(PromptReason::Missed.as_str()),
                                int(used),
                                float(now),
                                prompt_id.clone(),
                                string(PromptState::Held.as_str()),
                            ],
                        )? == 1);
                    }
                    sql::exec(
                        connection,
                        "UPDATE prompts SET sent_count=?, due_at=? WHERE prompt_id=?",
                        &[int(used), float(latest), prompt_id.clone()],
                    )?;
                }
            }
            let key = self.tokens.hex(32);
            sql::exec(
                connection,
                "INSERT INTO records (record_id, capability, thread_id, state, created_at, claims) VALUES (?,?,?,?,?,0)",
                &[
                    string(&key),
                    string(PROMPT_QUEUE),
                    sql::get(&row, "thread_id").clone(),
                    string(RecordState::Waiting.as_str()),
                    float(now),
                ],
            )?;
            Ok(sql::exec(
                connection,
                "UPDATE prompts SET state=?, reason=NULL, depends=0, record_id=? WHERE prompt_id=? AND state=?",
                &[
                    string(PromptState::Ready.as_str()),
                    string(&key),
                    prompt_id.clone(),
                    string(PromptState::Held.as_str()),
                ],
            )? == 1)
        })
    }

    /// `clear_done(prompt_ids, generation)`: a person's Delete completed - {"deleted", "skipped"}.
    pub fn clear_done(&self, prompt_ids: &Value, generation: &Value) -> Result<Row> {
        let Value::Array(ids) = prompt_ids else {
            return Err(Error::refused(Refusal::InvalidRequest.as_str()));
        };
        let distinct = ids
            .iter()
            .enumerate()
            .all(|(index, one)| ids[..index].iter().all(|other| !py_eq(one, other)));
        if ids.is_empty() || ids.len() > CLEAR_MOST || !ids.iter().all(py::is_int) || !distinct {
            return Err(Error::refused(Refusal::InvalidRequest.as_str()));
        }
        if !py::is_int(generation) {
            return Err(Error::refused(Refusal::StaleGeneration.as_str()));
        }
        let deleted = self.transaction(false, |connection| {
            let Some(connection) = connection else {
                return Err(Error::refused(Refusal::StaleGeneration.as_str()));
            };
            if !py_eq(&sql::scalar(connection, "SELECT generation FROM meta", &[])?, generation) {
                return Err(Error::refused(Refusal::StaleGeneration.as_str()));
            }
            let mut deleted = 0u64;
            for prompt in ids {
                let mut parameters = vec![prompt.clone(), string(PromptState::Done.as_str())];
                parameters.extend(sql::words(COMPLETED));
                deleted += sql::exec(
                    connection,
                    &format!(
                        "DELETE FROM prompts WHERE prompt_id=? AND state=? AND reason IN ({}) AND words IS NULL",
                        sql::tight_marks(COMPLETED.len())
                    ),
                    &parameters,
                )?;
            }
            Ok(deleted as i64)
        })?;
        let mut found = Row::new();
        found.insert(sql::key("deleted"), int(deleted));
        found.insert(sql::key("skipped"), int(ids.len() as i64 - deleted));
        Ok(found)
    }

    /// `end_prompts(reason, thread_id=None, at=None)`: every prompt still to go whose occurrence is not in flight,
    /// ended; how many.
    pub fn end_prompts(&self, reason: &Value, thread_id: &Value, at: &Value) -> Result<i64> {
        let reason = py::closed(reason, PromptReason::ALL, "reason")?;
        let now = self.now(at)?;
        let mut clauses = vec!["p.state IN (?,?,?)", "(c.state IS NULL OR c.state=?)"];
        let mut values = pending_words();
        values.push(string(RecordState::Waiting.as_str()));
        if !matches!(thread_id, Value::Null) {
            clauses.push("p.thread_id=?");
            values.push(py::word(py::thread(thread_id)?));
        }
        self.transaction(false, |connection| {
            let Some(connection) = connection else {
                return Ok(0);
            };
            let rows = sql::tuples(
                connection,
                &format!(
                    "SELECT p.prompt_id, p.record_id FROM prompts p LEFT JOIN records c ON c.record_id = p.record_id \
                     WHERE {}",
                    clauses.join(" AND ")
                ),
                &values,
            )?;
            for row in &rows {
                sql::exec(
                    connection,
                    "UPDATE prompts SET state=?, reason=?, words=NULL, finished_at=? WHERE prompt_id=?",
                    &[string(PromptState::Cancelled.as_str()), string(reason), float(now), row[0].clone()],
                )?;
                if !matches!(row[1], Value::Null) {
                    sql::exec(
                        connection,
                        "UPDATE records SET state=?, finished_at=? WHERE record_id=?",
                        &[string(RecordState::Cancelled.as_str()), float(now), row[1].clone()],
                    )?;
                }
            }
            Ok(rows.len() as i64)
        })
    }

    /// `prompt_moved(record_id, move, at=None, queue_id=None, gate=None, reason=None)`: what core told of a prompt's
    /// occurrence (P14).
    #[allow(clippy::too_many_arguments)]
    pub fn prompt_moved(
        &self,
        record_id: &Value,
        movement: &Value,
        at: &Value,
        queue_id: &Value,
        gate: &Value,
        reason: &Value,
    ) -> Result<Option<Row>> {
        py::key(record_id, "record id")?;
        let now = self.now(at)?;
        let movement = py::py_str(movement);
        self.transaction(false, |connection| {
            let Some(connection) = connection else {
                return Ok(None);
            };
            let row = sql::one(
                connection,
                "SELECT p.*, c.state AS record_state, c.withdraw AS withdraw FROM prompts p \
                 JOIN records c ON c.record_id = p.record_id WHERE p.record_id=?",
                std::slice::from_ref(record_id),
            )?;
            let Some(row) = row else { return Ok(None) };
            if !py::is_word(sql::get(&row, "state"), PENDING) {
                return Ok(None);
            }
            let prompt = sql::get(&row, "prompt_id").clone();
            if movement == "sent" {
                sql::exec(
                    connection,
                    "UPDATE prompts SET sent_at=coalesce(launching_at, ?), launching_at=coalesce(launching_at, ?) \
                     WHERE prompt_id=?",
                    &[float(now), float(now), prompt.clone()],
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
                    &[string(RecordState::Waiting.as_str()), record_id.clone(), string(RecordState::InFlight.as_str())],
                )?;
                sql::exec(
                    connection,
                    "UPDATE prompts SET launching_at=NULL WHERE prompt_id=?",
                    std::slice::from_ref(&prompt),
                )?;
            } else if let Some((why, state)) = ends(&movement) {
                sql::exec(
                    connection,
                    "UPDATE records SET state=?, finished_at=?, withdraw=0 WHERE record_id=?",
                    &[string(state), float(now), record_id.clone()],
                )?;
                let used = py::plus_one(sql::get(&row, "sent_count"))?;
                let mut counted = row.clone();
                counted.insert(sql::key("sent_count"), used.clone());
                let following = if movement == "unproven" {
                    None
                } else {
                    next_slot(&counted)?
                };
                match following {
                    None => {
                        sql::exec(
                            connection,
                            "UPDATE prompts SET state=?, reason=?, words=NULL, sent_count=?, finished_at=? \
                             WHERE prompt_id=?",
                            &[string(PromptState::Done.as_str()), string(why), used, float(now), prompt.clone()],
                        )?;
                    }
                    Some(following) => {
                        sql::exec(
                            connection,
                            "UPDATE prompts SET state=?, reason=?, sent_count=?, record_id=NULL, due_at=?, \
                             launching_at=NULL, sent_at=NULL WHERE prompt_id=?",
                            &[string(PromptState::Waiting.as_str()), string(why), used, following, prompt.clone()],
                        )?;
                    }
                }
            } else if movement == "withdrawn" {
                sql::exec(
                    connection,
                    "UPDATE records SET state=?, finished_at=?, withdraw=0 WHERE record_id=?",
                    &[string(RecordState::Cancelled.as_str()), float(now), record_id.clone()],
                )?;
                if sql::truthy(sql::get(&row, "withdraw")) {
                    sql::exec(
                        connection,
                        "UPDATE prompts SET state=?, reason=?, words=NULL, finished_at=? WHERE prompt_id=?",
                        &[
                            string(PromptState::Cancelled.as_str()),
                            string(PromptReason::Withdrawn.as_str()),
                            float(now),
                            prompt.clone(),
                        ],
                    )?;
                } else {
                    sql::exec(
                        connection,
                        "UPDATE prompts SET state=?, reason=?, record_id=NULL, launching_at=NULL, sent_at=NULL \
                         WHERE prompt_id=?",
                        &[string(PromptState::Held.as_str()), string(PromptReason::Withdrawn.as_str()), prompt.clone()],
                    )?;
                }
            } else if movement == "withdraw_refused" {
                sql::exec(
                    connection,
                    "UPDATE prompts SET reason=? WHERE prompt_id=?",
                    &[string(PromptReason::WithdrawRefused.as_str()), prompt.clone()],
                )?;
                sql::exec(
                    connection,
                    "UPDATE records SET withdraw=0 WHERE record_id=?",
                    std::slice::from_ref(record_id),
                )?;
            } else if movement == "waiting" {
                paced_wait(connection, record_id, gate, reason, now)?;
                let (gate, reason) = (gate_word(gate)?, gate_word(reason)?);
                if !(py_eq(sql::get(&row, "gate"), &gate) && py_eq(sql::get(&row, "gate_reason"), &reason)) {
                    sql::exec(
                        connection,
                        "UPDATE prompts SET gate=?, gate_reason=? WHERE prompt_id=?",
                        &[gate, reason, prompt.clone()],
                    )?;
                }
            } else {
                return Ok(None);
            }
            Ok(Some(super::resets::moved(string(PROMPT_QUEUE), movement == "unproven")))
        })
    }

    /// `prompts_in_flight()`: every prompt whose occurrence is in flight.
    pub fn prompts_in_flight(&self) -> Result<Vec<Row>> {
        Ok(self
            .prompts(&Value::Null, &Value::Bool(true))?
            .into_iter()
            .filter(|row| {
                py::is_word(
                    sql::get(row, "record_state"),
                    &[RecordState::InFlight.as_str()],
                )
            })
            .collect())
    }

    /// `release_unlaunched_prompts(after, at=None)`.
    pub fn release_unlaunched_prompts(&self, after: &Value, at: &Value) -> Result<i64> {
        let now = self.now(at)?;
        self.transaction(false, |connection| {
            let Some(connection) = connection else {
                return Ok(0);
            };
            let after = py::minus_operand(after)?;
            let keys = sql::tuples(
                connection,
                "SELECT c.record_id FROM prompts p JOIN records c ON c.record_id = p.record_id WHERE p.state=? \
                 AND p.launching_at IS NULL AND p.sent_at IS NULL AND c.state=? AND c.claimed_at IS NOT NULL \
                 AND c.claimed_at <= ?",
                &[string(PromptState::Ready.as_str()), string(RecordState::InFlight.as_str()), float(now - after)],
            )?;
            for key in &keys {
                sql::exec(
                    connection,
                    "UPDATE records SET state=? WHERE record_id=? AND state=?",
                    &[string(RecordState::Waiting.as_str()), key[0].clone(), string(RecordState::InFlight.as_str())],
                )?;
            }
            Ok(keys.len() as i64)
        })
    }
}

/// `next_slot(row)`: when a recurring prompt's next occurrence falls, or None where its series ends there.
pub fn next_slot(row: &Row) -> Result<Option<Value>> {
    if !py::is_word(
        sql::get(row, "trigger"),
        &[PromptTrigger::Recurring.as_str()],
    ) {
        return Ok(None);
    }
    if pyval::less_or_equal(sql::get(row, "occurrences"), sql::get(row, "sent_count"))
        .map_err(|class| Error::python(class, "'>='"))?
    {
        return Ok(None);
    }
    let due = sql::get(row, "due_at");
    let step = period(sql::get(row, "every"))?;
    let following = match due {
        Value::Int(number) => match number.as_i64().and_then(|due| due.checked_add(step)) {
            Some(found) => int(found),
            None => return Err(Error::python("OverflowError", "too large")),
        },
        Value::Float(due) => Value::Float(due + step as f64),
        _ => return Err(Error::type_error("unsupported operand type(s) for +")),
    };
    let until = sql::get(row, "until");
    if matches!(until, Value::Null)
        || pyval::less_or_equal(&following, until).map_err(|class| Error::python(class, "'<='"))?
    {
        return Ok(Some(following));
    }
    Ok(None)
}

/// `prune(connection, now, max_age, limit)`: prompts finished `max_age` ago, then the oldest finished beyond `limit`.
pub fn prune(connection: &Connection, now: f64, max_age: f64, limit: i64) -> Result<()> {
    let finished = format!(
        "state IN ('{}', '{}')",
        PromptState::Done.as_str(),
        PromptState::Cancelled.as_str()
    );
    sql::exec(
        connection,
        &format!("DELETE FROM prompts WHERE {finished} AND coalesce(finished_at, created_at) < ?"),
        &[float(now - max_age)],
    )?;
    let excess = sql::number(connection, "SELECT count(*) FROM prompts", &[])? - limit;
    if excess > 0 {
        sql::exec(
            connection,
            &format!(
                "DELETE FROM prompts WHERE prompt_id IN (SELECT prompt_id FROM prompts WHERE {finished} \
                 ORDER BY coalesce(finished_at, created_at) LIMIT ?)"
            ),
            &[int(excess)],
        )?;
    }
    Ok(())
}

/// `end_pending(connection, capabilities, now)`: when prompt_queue moves off on, every prompt still to go whose
/// occurrence is not in flight ended (turned_off) with its words.
pub fn end_pending(connection: &Connection, capabilities: &[Value], now: f64) -> Result<()> {
    if !capabilities
        .iter()
        .any(|capability| py_eq(capability, &string(PROMPT_QUEUE)))
    {
        return Ok(());
    }
    let mut parameters = pending_words();
    parameters.push(string(RecordState::InFlight.as_str()));
    let rows = sql::tuples(
        connection,
        "SELECT p.prompt_id, p.record_id FROM prompts p LEFT JOIN records c ON c.record_id = p.record_id \
         WHERE p.state IN (?,?,?) AND (c.state IS NULL OR c.state <> ?)",
        &parameters,
    )?;
    for row in rows {
        sql::exec(
            connection,
            "UPDATE prompts SET state=?, reason=?, words=NULL, finished_at=? WHERE prompt_id=?",
            &[
                string(PromptState::Cancelled.as_str()),
                string(PromptReason::TurnedOff.as_str()),
                float(now),
                row[0].clone(),
            ],
        )?;
        if !matches!(row[1], Value::Null) {
            sql::exec(
                connection,
                "UPDATE records SET state=?, finished_at=? WHERE record_id=? AND state<>?",
                &[
                    string(RecordState::Cancelled.as_str()),
                    float(now),
                    row[1].clone(),
                    string(RecordState::Finished.as_str()),
                ],
            )?;
        }
    }
    Ok(())
}
