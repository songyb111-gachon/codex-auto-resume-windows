//! Where each capability stands, as stored: the arming rows, the generation and the ceiling (`state/arming.py`).
//!
//! This is only the writing; who may move a capability, and when, is `arming.py`'s (seat S7.1b). Each move is one
//! transaction that checks its words, bumps the generation and journals itself. The generation is one number for
//! the whole table, raised by every move: a request to turn something on names the generation it was made
//! against, and is refused if any move came in between; a move to off names none.

use car_machine::json::{Str, Value};
use rusqlite::Connection;

use super::errors::{Error, Result};
use super::py;
use super::schema::{CONTINUATION_CAPABILITIES, RESET_CAPABILITIES};
use super::seam::registry_gen::GLOBAL_HOURLY;
use super::seam::words_gen::{
    KEPT_NOTICES, actor, arming_state, arming_warning, journal_code, keep_on, off_reason, refusal,
};
use super::session::AdvancedState;
use super::sql::{self, Row, float, int, py_eq, string};

/// `_KEPT`: Keep on's rows in `options`, as SQL.
fn kept_clause() -> String {
    format!(
        "choice IN ({})",
        keep_on::ALL
            .iter()
            .map(|word| format!("'{word}'"))
            .collect::<Vec<_>>()
            .join(", ")
    )
}

/// `_joined(warnings)`: the warnings a person confirmed, as the column holds them, or None.
pub(crate) fn joined(warnings: &Value) -> Result<Value> {
    let items = match warnings {
        Value::Null => return Ok(Value::Null),
        Value::Array(items) => items,
        _ => return Err(Error::state("invalid warnings")),
    };
    let mut chosen = Vec::new();
    for item in items {
        chosen.push(py::closed(item, arming_warning::ALL, "warning")?);
    }
    let words: Vec<&str> = arming_warning::ALL
        .iter()
        .copied()
        .filter(|word| chosen.contains(word))
        .collect();
    Ok(if words.is_empty() {
        Value::Null
    } else {
        string(&words.join(","))
    })
}

/// `_confirmed(value)`: the column read back - the vocabulary's words in its order.
fn confirmed(value: &Value) -> Value {
    let words: Vec<&str> = match py::text(value) {
        Some(text) => text.split(',').collect(),
        None => Vec::new(),
    };
    py::word_list(
        arming_warning::ALL
            .iter()
            .copied()
            .filter(|word| words.contains(word)),
    )
}

/// The state of a row as the edition reads it: a word the vocabulary does not hold is off.
fn state_of(row: &Row) -> &'static str {
    py::closed(sql::get(row, "state"), arming_state::ALL, "state").unwrap_or(arming_state::OFF)
}

/// `_row(row)`: an arming row as the rest of the edition reads it.
fn read_row(row: &Row) -> Row {
    let revision = sql::get(row, "statement_revision");
    let version = sql::get(row, "engine_version");
    let mut found = Row::new();
    found.insert(sql::key("state"), string(state_of(row)));
    found.insert(sql::key("since"), sql::get(row, "since").clone());
    found.insert(
        sql::key("actor"),
        if py::is_word(sql::get(row, "actor"), actor::ALL) {
            sql::get(row, "actor").clone()
        } else {
            Value::Null
        },
    );
    found.insert(
        sql::key("reason"),
        if py::is_word(sql::get(row, "reason"), off_reason::ALL) {
            sql::get(row, "reason").clone()
        } else {
            Value::Null
        },
    );
    found.insert(
        sql::key("statement_revision"),
        if py::is_int(revision) {
            revision.clone()
        } else {
            Value::Null
        },
    );
    found.insert(
        sql::key("engine_version"),
        match version {
            Value::Str(text) if text.len() <= 64 => version.clone(),
            _ => Value::Null,
        },
    );
    found.insert(sql::key("warnings"), confirmed(sql::get(row, "warnings")));
    found.insert(sql::key("keep_on"), Value::Bool(false));
    found
}

/// Whether a stored row stands where a move would put it, as it stands: the same state, revision, Codex version and
/// warnings, and no notice.
fn stands(
    before: &Row,
    state: &str,
    revision: &Value,
    engine_version: &Value,
    warnings: &Value,
) -> bool {
    state_of(before) == state
        && py_eq(sql::get(before, "statement_revision"), revision)
        && py_eq(sql::get(before, "engine_version"), engine_version)
        && py_eq(sql::get(before, "warnings"), warnings)
        && matches!(sql::get(before, "reason"), Value::Null)
}

fn generation(connection: &Connection) -> Result<Value> {
    sql::scalar(connection, "SELECT generation FROM meta", &[])
}

/// One stored arming row by its capability, or None.
fn row_of(connection: &Connection, capability: &Value) -> Result<Option<Row>> {
    sql::one(
        connection,
        "SELECT * FROM arming WHERE capability=?",
        std::slice::from_ref(capability),
    )
}

/// `KEPT_NOTICES.index(word)`.
fn rank(word: &Value) -> Option<usize> {
    py::text(word).and_then(|text| KEPT_NOTICES.iter().position(|each| *each == text))
}

/// The arguments of one move (`move`'s keywords).
#[derive(Clone, Debug)]
pub struct Move {
    pub actor: Value,
    pub reason: Value,
    pub revision: Value,
    pub engine_version: Value,
    pub warnings: Value,
    pub generation: Value,
    pub at: Value,
}

impl Default for Move {
    fn default() -> Move {
        Move {
            actor: Value::Null,
            reason: Value::Null,
            revision: Value::Null,
            engine_version: Value::Null,
            warnings: Value::Null,
            generation: Value::Null,
            at: Value::Null,
        }
    }
}

impl AdvancedState {
    /// `meta()`: the generation and the global ceiling; with no file, what a new one starts with.
    pub fn meta(&self) -> Result<Row> {
        let found = self.read(|connection| match connection {
            None => Ok(None),
            Some(connection) => sql::one(
                connection,
                "SELECT generation, global_hourly FROM meta",
                &[],
            ),
        })?;
        let mut meta = Row::new();
        match found {
            None => {
                meta.insert(sql::key("generation"), int(0));
                meta.insert(sql::key("global_hourly"), int(GLOBAL_HOURLY));
            }
            Some(row) => {
                meta.insert(sql::key("generation"), sql::get(&row, "generation").clone());
                meta.insert(
                    sql::key("global_hourly"),
                    sql::get(&row, "global_hourly").clone(),
                );
            }
        }
        Ok(meta)
    }

    /// `arming()`: every capability of the registry that has a row, by id.
    pub fn arming(&self) -> Result<Row> {
        let (rows, kept) = self.read(|connection| match connection {
            None => Ok((Vec::new(), Vec::new())),
            Some(connection) => {
                let rows = sql::all(connection, "SELECT * FROM arming", &[])?;
                let kept = sql::tuples(
                    connection,
                    &format!(
                        "SELECT capability, choice FROM options WHERE {}",
                        kept_clause()
                    ),
                    &[],
                )?;
                Ok((rows, kept))
            }
        })?;
        let mut found = Row::new();
        for row in rows {
            let capability = sql::get(&row, "capability");
            if self.registry.get(capability).is_none() {
                continue;
            }
            let words: Vec<&Value> = if !py_eq(sql::get(&row, "state"), &string(arming_state::OFF))
            {
                kept.iter()
                    .filter(|pair| py_eq(&pair[0], capability))
                    .map(|pair| &pair[1])
                    .collect()
            } else {
                Vec::new()
            };
            let has = |word: &str| words.iter().any(|each| py::is_word(each, &[word]));
            let keep = has(keep_on::KEEP_ON);
            let mut entry = read_row(&row);
            entry.insert(sql::key("keep_on"), Value::Bool(keep));
            entry.insert(
                sql::key("send_again"),
                Value::Bool(keep && has(keep_on::SEND_AGAIN)),
            );
            found.insert(
                Str::new(py::text(capability).unwrap_or_default()),
                Value::Object(entry),
            );
        }
        Ok(found)
    }

    /// `ever_moved(capability)`: whether `capability` has a stored row at all.
    pub fn ever_moved(&self, capability: &Value) -> Result<bool> {
        self.read(|connection| match connection {
            None => Ok(false),
            Some(connection) => sql::exists(
                connection,
                "SELECT 1 FROM arming WHERE capability=?",
                std::slice::from_ref(capability),
            ),
        })
    }

    /// `move(capability, state, ...)`: put one capability in `state`. (moved, generation after).
    pub fn move_capability(
        &self,
        capability: &Value,
        state: &Value,
        options: &Move,
    ) -> Result<(bool, Value)> {
        let state = py::closed(state, arming_state::ALL, "state")?;
        let actor_word = py::closed(&options.actor, actor::ALL, "actor")?;
        let reason = py::closed_or_none(&options.reason, off_reason::ALL, "reason")?;
        let warnings = joined(&options.warnings)?;
        if self.registry.get(capability).is_none() {
            return Err(Error::state("unknown capability"));
        }
        let now = self.now(&options.at)?;
        self.transaction(state != arming_state::OFF, |connection| {
            let Some(connection) = connection else {
                return Ok((false, int(0)));
            };
            let current = generation(connection)?;
            if !matches!(options.generation, Value::Null) && !py_eq(&options.generation, &current) {
                return Err(Error::stale());
            }
            let before = row_of(connection, capability)?;
            if state != arming_state::ARMED {
                sql::exec(
                    connection,
                    &format!("DELETE FROM options WHERE capability=? AND {}", kept_clause()),
                    std::slice::from_ref(capability),
                )?;
            }
            let (revision, engine_version, warnings) = if state == arming_state::OFF {
                if before.as_ref().is_none_or(|before| state_of(before) == arming_state::OFF) {
                    return Ok((false, current));
                }
                (Value::Null, Value::Null, Value::Null)
            } else {
                if before.as_ref().is_some_and(|before| {
                    stands(before, state, &options.revision, &options.engine_version, &warnings)
                }) {
                    return Ok((false, current));
                }
                (options.revision.clone(), options.engine_version.clone(), warnings.clone())
            };
            sql::exec(
                connection,
                "INSERT OR REPLACE INTO arming (capability, state, since, actor, reason, statement_revision, \
                 engine_version, warnings) VALUES (?,?,?,?,?,?,?,?)",
                &[
                    capability.clone(),
                    string(state),
                    float(now),
                    string(actor_word),
                    py::word_or_null(reason),
                    revision,
                    engine_version,
                    warnings,
                ],
            )?;
            let one = std::slice::from_ref(capability);
            if state == arming_state::OFF {
                super::resets::end_pending(connection, one, now)?;
                super::prompts::end_pending(connection, one, now)?;
            }
            if state != arming_state::ARMED {
                super::continuations::end_pending(connection, one, now, state == arming_state::OFF)?;
                if py::is_word(capability, &[super::meter::METER]) {
                    super::meter::end_meter(connection)?;
                }
                super::chat::end_pending(connection, one, now)?;
            }
            sql::exec(connection, "UPDATE meta SET generation = generation + 1", &[])?;
            let code = match state {
                arming_state::ARMED => journal_code::ARMED,
                arming_state::SHADOW => journal_code::WATCHED,
                _ if actor_word == actor::TRIPWIRE => journal_code::TRIPPED,
                _ if actor_word == actor::EDITION_ENTRY || actor_word == actor::ENGINE_CHANGE => {
                    journal_code::RESET
                }
                _ => journal_code::DISARMED,
            };
            self.note_in(
                connection,
                now,
                &string(code),
                capability,
                &py::word_or_null(reason),
                &string(actor_word),
                &Value::Null,
                &Value::Null,
            )?;
            Ok((true, py::plus_one(&current)?))
        })
    }

    /// `move_set(moves, actor=..., generation=..., at=..., keep=())`: a capability and the requirements it carries
    /// turned on in one transaction. (how many were written, generation after).
    pub fn move_set(
        &self,
        moves: &Value,
        actor_word: &Value,
        generation_seen: &Value,
        at: &Value,
        keep: &Value,
    ) -> Result<(i64, Value)> {
        let mut prepared: Vec<(Value, &'static str, Value, Value, Value)> = Vec::new();
        for each in iterate(moves)? {
            let parts = iterate(&each)?;
            if parts.len() != 5 {
                return Err(Error::python(
                    "ValueError",
                    "wrong number of values to unpack",
                ));
            }
            let state = py::closed(&parts[1], arming_state::ALL, "state")?;
            if state == arming_state::OFF || self.registry.get(&parts[0]).is_none() {
                return Err(Error::state("a set only turns capabilities on"));
            }
            prepared.push((
                parts[0].clone(),
                state,
                parts[2].clone(),
                parts[3].clone(),
                joined(&parts[4])?,
            ));
        }
        let keep: Vec<Value> = iterate(keep)?;
        if keep
            .iter()
            .any(|each| matches!(each, Value::Array(_) | Value::Object(_)))
        {
            return Err(Error::type_error("unhashable type"));
        }
        let armed: Vec<&Value> = prepared
            .iter()
            .filter(|(_, state, ..)| *state == arming_state::ARMED)
            .map(|(capability, ..)| capability)
            .collect();
        if !keep
            .iter()
            .all(|each| armed.iter().any(|one| py_eq(one, each)))
        {
            return Err(Error::state(
                "only a capability turned on in the set is kept on",
            ));
        }
        let actor_word = py::closed(actor_word, actor::ALL, "actor")?;
        let now = self.now(at)?;
        self.writing(|connection| {
            let current = generation(connection)?;
            if !py_eq(generation_seen, &current) {
                return Err(Error::stale());
            }
            let mut written = 0;
            for (capability, state, revision, engine_version, warnings) in &prepared {
                let before = row_of(connection, capability)?;
                if before
                    .as_ref()
                    .is_some_and(|before| stands(before, state, revision, engine_version, warnings))
                {
                    continue;
                }
                sql::exec(
                    connection,
                    "INSERT OR REPLACE INTO arming (capability, state, since, actor, reason, statement_revision, \
                     engine_version, warnings) VALUES (?,?,?,?,?,?,?,?)",
                    &[
                        capability.clone(),
                        string(state),
                        float(now),
                        string(actor_word),
                        Value::Null,
                        revision.clone(),
                        engine_version.clone(),
                        warnings.clone(),
                    ],
                )?;
                let code = if *state == arming_state::ARMED {
                    string(journal_code::ARMED)
                } else {
                    string(journal_code::WATCHED)
                };
                self.note_in(
                    connection,
                    now,
                    &code,
                    capability,
                    &Value::Null,
                    &string(actor_word),
                    &Value::Null,
                    &Value::Null,
                )?;
                written += 1;
            }
            for capability in unique(&keep) {
                let held = sql::exists(
                    connection,
                    "SELECT 1 FROM options WHERE capability=? AND choice=?",
                    &[capability.clone(), string(keep_on::KEEP_ON)],
                )?;
                if !held {
                    sql::exec(
                        connection,
                        "INSERT INTO options (capability, choice, value) VALUES (?,?,1)",
                        &[capability.clone(), string(keep_on::KEEP_ON)],
                    )?;
                    self.note_in(
                        connection,
                        now,
                        &string(journal_code::KEEP_ON),
                        &capability,
                        &Value::Null,
                        &string(actor_word),
                        &Value::Null,
                        &Value::Null,
                    )?;
                    written += 1;
                }
            }
            if written > 0 {
                sql::exec(connection, "UPDATE meta SET generation = generation + 1", &[])?;
                return Ok((written, py::plus_one(&current)?));
            }
            Ok((0, current))
        })
    }

    /// `all_off(actor=..., reason=..., at=...)`: every capability off at once. (how many were on, generation).
    pub fn all_off(&self, actor_word: &Value, reason: &Value, at: &Value) -> Result<(i64, Value)> {
        let actor_word = py::closed(actor_word, actor::ALL, "actor")?;
        let reason = py::closed(reason, off_reason::ALL, "reason")?;
        let now = self.now(at)?;
        self.transaction(false, |connection| {
            let Some(connection) = connection else {
                return Ok((0, int(0)));
            };
            let on = sql::number(connection, "SELECT count(*) FROM arming WHERE state <> 'off'", &[])?;
            let current = generation(connection)?;
            sql::exec(connection, &format!("DELETE FROM options WHERE {}", kept_clause()), &[])?;
            if on == 0 {
                return Ok((0, current));
            }
            sql::exec(
                connection,
                "UPDATE arming SET state='off', since=?, actor=?, reason=?, statement_revision=NULL, \
                 engine_version=NULL, warnings=NULL WHERE state <> 'off'",
                &[float(now), string(actor_word), string(reason)],
            )?;
            let words = |list: &[&str]| -> Vec<Value> { list.iter().map(|word| string(word)).collect() };
            super::resets::end_pending(connection, &words(RESET_CAPABILITIES), now)?;
            super::continuations::end_pending(connection, &words(CONTINUATION_CAPABILITIES), now, true)?;
            super::prompts::end_pending(connection, &words(&[super::prompts::PROMPT_QUEUE]), now)?;
            super::meter::end_meter(connection)?;
            super::chat::end_pending(connection, &words(&[super::chat::CAPABILITY]), now)?;
            sql::exec(connection, "UPDATE meta SET generation = generation + 1", &[])?;
            let code = if actor_word == actor::EDITION_ENTRY {
                journal_code::RESET
            } else {
                journal_code::ALL_OFF
            };
            self.note_in(
                connection,
                now,
                &string(code),
                &Value::Null,
                &string(reason),
                &string(actor_word),
                &Value::Null,
                &Value::Null,
            )?;
            Ok((on, py::plus_one(&current)?))
        })
    }

    /// `set_keep_on(capability, on, send_again=False, actor=..., generation=None, at=None)`: the generation after.
    pub fn set_keep_on(
        &self,
        capability: &Value,
        on: &Value,
        send_again: &Value,
        actor_word: &Value,
        generation_seen: &Value,
        at: &Value,
    ) -> Result<Value> {
        let actor_word = py::closed(actor_word, actor::ALL, "actor")?;
        let (Value::Bool(on), Value::Bool(send_again)) = (on, send_again) else {
            return Err(Error::state("invalid keep on"));
        };
        if self.registry.get(capability).is_none() || (*send_again && !*on) {
            return Err(Error::state("invalid keep on"));
        }
        let (on, send_again) = (*on, *send_again);
        let mut wanted: Vec<&str> = Vec::new();
        if on {
            wanted.push(keep_on::KEEP_ON);
        }
        if send_again {
            wanted.push(keep_on::SEND_AGAIN);
        }
        wanted.sort_unstable();
        let now = self.now(at)?;
        self.transaction(false, |connection| {
            let Some(connection) = connection else {
                if on {
                    return Err(Error::refused(refusal::NOT_ON));
                }
                return Ok(int(0));
            };
            let current = generation(connection)?;
            if !matches!(generation_seen, Value::Null) && !py_eq(generation_seen, &current) {
                return Err(Error::stale());
            }
            let held: std::collections::BTreeSet<String> = sql::tuples(
                connection,
                &format!(
                    "SELECT choice FROM options WHERE capability=? AND {}",
                    kept_clause()
                ),
                std::slice::from_ref(capability),
            )?
            .into_iter()
            .map(|row| py::py_str(&row[0]))
            .collect();
            let wanted_set: std::collections::BTreeSet<String> =
                wanted.iter().map(|word| (*word).to_string()).collect();
            if held == wanted_set {
                return Ok(current);
            }
            let adding = !wanted_set.is_subset(&held);
            if adding && !py::is_int(generation_seen) {
                return Err(Error::state("invalid generation"));
            }
            let row = sql::one(
                connection,
                "SELECT state FROM arming WHERE capability=?",
                std::slice::from_ref(capability),
            )?;
            if on
                && row
                    .as_ref()
                    .is_none_or(|row| py::is_word(sql::get(row, "state"), &[arming_state::OFF]))
            {
                return Err(Error::refused(refusal::NOT_ON));
            }
            sql::exec(
                connection,
                &format!(
                    "DELETE FROM options WHERE capability=? AND {}",
                    kept_clause()
                ),
                std::slice::from_ref(capability),
            )?;
            for word in &wanted {
                sql::exec(
                    connection,
                    "INSERT INTO options (capability, choice, value) VALUES (?,?,1)",
                    &[capability.clone(), string(word)],
                )?;
            }
            sql::exec(
                connection,
                "UPDATE meta SET generation = generation + 1",
                &[],
            )?;
            let code = if !on {
                journal_code::KEEP_ON_OFF
            } else if adding {
                journal_code::KEEP_ON
            } else {
                journal_code::SEND_AGAIN_OFF
            };
            self.note_in(
                connection,
                now,
                &string(code),
                capability,
                &Value::Null,
                &string(actor_word),
                &Value::Null,
                &Value::Null,
            )?;
            py::plus_one(&current)
        })
    }

    /// `send_again_off(capability, reason=..., at=None)`: a kept-on capability's Send again taken away by a
    /// tripwire. Whether anything was taken away.
    pub fn send_again_off(&self, capability: &Value, reason: &Value, at: &Value) -> Result<bool> {
        let reason = py::closed(reason, off_reason::ALL, "reason")?;
        let now = self.now(at)?;
        self.transaction(false, |connection| {
            let Some(connection) = connection else {
                return Ok(false);
            };
            if sql::exec(
                connection,
                "DELETE FROM options WHERE capability=? AND choice=?",
                &[capability.clone(), string(keep_on::SEND_AGAIN)],
            )? != 1
            {
                return Ok(false);
            }
            sql::exec(
                connection,
                "UPDATE meta SET generation = generation + 1",
                &[],
            )?;
            self.note_in(
                connection,
                now,
                &string(journal_code::SEND_AGAIN_OFF),
                capability,
                &string(reason),
                &string(actor::TRIPWIRE),
                &Value::Null,
                &Value::Null,
            )?;
            let held = sql::one(
                connection,
                "SELECT state, reason FROM arming WHERE capability=?",
                std::slice::from_ref(capability),
            )?;
            if let Some(held) = held {
                let reason_rank = KEPT_NOTICES.iter().position(|each| *each == reason);
                let held_rank = rank(sql::get(&held, "reason"));
                let rises = match (reason_rank, held_rank) {
                    (None, _) => false,
                    (Some(_), None) => true,
                    (Some(new), Some(old)) => old > new,
                };
                if !py::is_word(sql::get(&held, "state"), &[arming_state::OFF]) && rises {
                    sql::exec(
                        connection,
                        "UPDATE arming SET reason=? WHERE capability=?",
                        &[string(reason), capability.clone()],
                    )?;
                    self.note_in(
                        connection,
                        now,
                        &string(journal_code::KEPT),
                        capability,
                        &string(reason),
                        &string(actor::TRIPWIRE),
                        &Value::Null,
                        &Value::Null,
                    )?;
                }
            }
            Ok(true)
        })
    }

    /// `note_kept(capability, reason, at=None)`: what would have turned a kept-on capability off, noted on its row.
    pub fn note_kept(&self, capability: &Value, reason: &Value, at: &Value) -> Result<bool> {
        let reason = py::closed(reason, off_reason::ALL, "reason")?;
        let Some(new) = KEPT_NOTICES.iter().position(|each| *each == reason) else {
            return Err(Error::state("not a notice"));
        };
        let now = self.now(at)?;
        self.transaction(false, |connection| {
            let Some(connection) = connection else {
                return Ok(false);
            };
            let row = sql::one(
                connection,
                "SELECT state, reason FROM arming WHERE capability=?",
                std::slice::from_ref(capability),
            )?;
            let Some(row) = row else { return Ok(false) };
            if py::is_word(sql::get(&row, "state"), &[arming_state::OFF]) {
                return Ok(false);
            }
            if rank(sql::get(&row, "reason")).is_some_and(|old| old <= new) {
                return Ok(false);
            }
            sql::exec(
                connection,
                "UPDATE arming SET reason=? WHERE capability=? AND state <> 'off'",
                &[string(reason), capability.clone()],
            )?;
            self.note_in(
                connection,
                now,
                &string(journal_code::KEPT),
                capability,
                &string(reason),
                &string(actor::TRIPWIRE),
                &Value::Null,
                &Value::Null,
            )?;
            Ok(true)
        })
    }

    /// `set_global_hourly(value, generation=..., actor=..., at=None)`: the generation after.
    pub fn set_global_hourly(
        &self,
        value: &Value,
        generation_seen: &Value,
        actor_word: &Value,
        at: &Value,
    ) -> Result<Value> {
        if !py::small(value).is_some_and(|value| (1..=GLOBAL_HOURLY).contains(&value)) {
            return Err(Error::state("invalid ceiling"));
        }
        let actor_word = py::closed(actor_word, actor::ALL, "actor")?;
        let now = self.now(at)?;
        self.writing(|connection| {
            let current = generation(connection)?;
            if !py_eq(generation_seen, &current) {
                return Err(Error::stale());
            }
            sql::exec(
                connection,
                "UPDATE meta SET global_hourly=?, generation = generation + 1",
                std::slice::from_ref(value),
            )?;
            self.note_in(
                connection,
                now,
                &string(journal_code::CEILING_CHANGED),
                &Value::Null,
                &Value::Null,
                &string(actor_word),
                &Value::Null,
                &Value::Null,
            )?;
            py::plus_one(&current)
        })
    }
}

/// Iterating a value as Python's `for x in value`: a list's items, a text's characters, a dict's keys;
/// TypeError for anything else.
pub(crate) fn iterate(value: &Value) -> Result<Vec<Value>> {
    match value {
        Value::Array(items) => Ok(items.clone()),
        Value::Str(text) => Ok(text
            .code_points()
            .map(|point| Value::Str(Str::from_code_points([point]).unwrap_or_default()))
            .collect()),
        Value::Object(map) => Ok(map.keys().map(|key| Value::Str(key.clone())).collect()),
        _ => Err(Error::type_error("object is not iterable")),
    }
}

/// The distinct members of `values` in their first order (iterating a Python `set` the caller made of them:
/// what is done for each is the same whatever the order).
fn unique(values: &[Value]) -> Vec<Value> {
    let mut found: Vec<Value> = Vec::new();
    for value in values {
        if !found.iter().any(|each| py_eq(each, value)) {
            found.push(value.clone());
        }
    }
    found
}
