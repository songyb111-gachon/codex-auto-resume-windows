//! Records: registering one, reading them back, and the rules a change must obey (store/records.py).

use car_machine::json::Value;
use rusqlite::Connection;

use crate::columns::{MUTABLE, record_columns};
use crate::errors::{Error, Result};
use crate::journal::{Event, event, finite_value};
use crate::seam::gates::{Limits, birth_stop, inherited, was_resent};
use crate::seam::vocab::{STATES, TERMINAL, WAITING};
use crate::seam::{USAGE_LIMIT, has, ids, plain_move_allowed};
use crate::session::Store;
use crate::validate::{is_usage, now as check_now, uuid_text, validated_record};
use crate::value::{
    Row, execute, first, get, int, key, marks, py_eq, set, string, text, text_of, truthy, tuples,
    words,
};

/// `register`'s keywords, at their defaults.
#[derive(Clone, Debug)]
pub struct Register {
    pub state: String,
    pub next_retry_at: Option<f64>,
    pub owner_id: Option<String>,
    /// `failed_turn_progress`: None, or a bool; only `True` itself counts as progress.
    pub failed_turn_progress: Value,
    pub legacy_carry: Value,
    pub limits: Option<Limits>,
    pub hold: Value,
    pub task_print: Value,
    pub context_tokens: Value,
    pub home_key: Value,
}

impl Default for Register {
    fn default() -> Self {
        Register {
            state: "waiting_reset".into(),
            next_retry_at: None,
            owner_id: None,
            failed_turn_progress: Value::Null,
            legacy_carry: Value::Null,
            limits: None,
            hold: Value::Null,
            task_print: Value::Null,
            context_tokens: Value::Null,
            home_key: string(""),
        }
    }
}

/// `update`'s keywords besides the changes.
#[derive(Clone, Debug)]
pub struct Update {
    pub at: Option<f64>,
    pub actor: String,
    pub event: Option<String>,
    pub flags: i64,
}

impl Default for Update {
    fn default() -> Self {
        Update {
            at: None,
            actor: "engine".into(),
            event: None,
            flags: 0,
        }
    }
}

const REQUIRED: &[&str] = &[
    "thread_id",
    "turn_id",
    "completed_at",
    "started_at",
    "ordinal",
    "interruption_id",
    "reset_at",
    "limit_type",
    "uncertain",
];

/// `failure_marks`' states (v0.6.20, standard J14).
pub const FAILED_STATES: &[&str] = &[
    "failed",
    "recovery_turn_failed",
    "retry_budget_exhausted",
    "no_progress_exhausted",
    "handed_over",
];
pub const UNCONFIRMED_STATES: &[&str] = &["submission_unknown", "outcome_unverified"];

impl Store {
    /// `register(record, now, ...)`: the record with its schedule and its chain, in one transaction. False,
    /// without raising, when this failure is known already (the same turn under another identity is journaled).
    pub fn register(&self, record: &Row, now: f64, options: &Register) -> Result<bool> {
        check_now(now)?;
        let keys_ok = REQUIRED.iter().all(|name| record.contains_key(*name))
            && record.keys().all(|name| {
                name.as_str()
                    .is_some_and(|name| REQUIRED.contains(&name) || name == "category")
            });
        if !keys_ok {
            return Err(Error::store("Invalid detection record"));
        }
        if !has(WAITING, &options.state) {
            return Err(Error::store(
                "A new interruption must start in a waiting state",
            ));
        }
        let mut row = Row::new();
        set(&mut row, "category", string(USAGE_LIMIT));
        for (name, value) in record {
            row.insert(name.clone(), value.clone());
        }
        let key_value = get(&row, "interruption_id").clone();
        let record_key = text(&key_value).unwrap_or_default().to_string();
        let defaults: Vec<(&str, Value)> = vec![
            ("detected_at", Value::Float(now)),
            ("state", string(&options.state)),
            ("retry_count", int(0)),
            (
                "next_retry_at",
                Value::Float(options.next_retry_at.unwrap_or(now)),
            ),
            ("resumed_at", Value::Null),
            ("last_error", Value::Null),
            ("marker", string(&ids::short_marker(&record_key))),
            ("queue_id", Value::Null),
            ("submitted_at", Value::Null),
            ("attempt_count", int(0)),
            ("cancel_requested", Value::Bool(false)),
            ("recovery_attempts", int(0)),
            ("no_progress_count", int(0)),
            ("recovery_turn_id", Value::Null),
            ("recovery_client_id", Value::Null),
            ("recovery_turn_status", Value::Null),
            ("user_joined", Value::Bool(false)),
            ("after_user_work", Value::Bool(false)),
            ("legacy", Value::Bool(false)),
            ("withdraw_reason", Value::Null),
            ("withdrawn_at", Value::Null),
            ("withdraw_deleted", Value::Bool(false)),
            ("withdraw_failures", int(0)),
            ("turn_started_at", Value::Null),
            ("outcome_at", Value::Null),
            ("first_queued_at", Value::Null),
            ("last_claim_at", Value::Null),
            ("parent_interruption_id", Value::Null),
            ("chain_origin_id", key_value.clone()),
            ("chain_first_detected_at", Value::Float(now)),
            ("chain_continuations", int(0)),
            ("budget_resets", int(0)),
            ("retry_now_count", int(0)),
            ("usage_unavailable_seconds", Value::Float(0.0)),
            ("usage_probe_at", Value::Null),
            ("gate_eval", Value::Null),
            ("gate_eval_at", Value::Null),
            ("history_hidden_at", Value::Null),
            ("not_before", Value::Null),
            ("hold", options.hold.clone()),
            ("task_print", options.task_print.clone()),
            ("context_tokens", options.context_tokens.clone()),
            ("objection_at", Value::Null),
            ("objection_until", Value::Null),
            ("home_key", options.home_key.clone()),
        ];
        for (name, value) in defaults {
            set(&mut row, name, value);
        }
        validated_record(row.clone())?;
        self.transaction(|connection| {
            if let Some(existing) = self.row(connection, &record_key)? {
                if ["thread_id", "turn_id", "completed_at", "started_at", "ordinal"]
                    .iter()
                    .any(|field| !py_eq(get(&existing, field), get(&row, field)))
                {
                    return Err(Error::store("Interruption identity collision"));
                }
                return Ok(false);
            }
            if first(
                connection,
                "SELECT 1 FROM interruptions WHERE thread_id=? AND marker=? LIMIT 1",
                &[get(&row, "thread_id").clone(), get(&row, "marker").clone()],
            )?
            .is_some()
            {
                set(&mut row, "marker", string(&ids::marker(&record_key)));
            }
            let drift = first(
                connection,
                "SELECT interruption_id FROM interruptions WHERE thread_id=? AND turn_id=? AND home_key=? AND interruption_id<>? LIMIT 1",
                &[get(&row, "thread_id").clone(), get(&row, "turn_id").clone(), options.home_key.clone(), key_value.clone()],
            )?;
            if let Some(drift) = drift {
                let other = self.row(connection, text(&drift[0]).unwrap_or_default())?;
                event(connection, now, "identity_drift", Event { record: other.as_ref(), ..Event::default() })?;
                return Ok(false);
            }
            let parent = self.parent(connection, &row, options.owner_id.as_deref())?;
            for (name, value) in inherited(parent.as_ref(), &options.failed_turn_progress, &options.legacy_carry) {
                set(&mut row, name, value);
            }
            let stop = birth_stop(
                parent.as_ref(),
                &options.failed_turn_progress,
                options.limits.as_ref(),
                is_usage(&row),
                now,
                &options.legacy_carry,
            );
            let mut reason = None;
            if let Some((state, why)) = stop {
                set(&mut row, "state", string(state));
                reason = Some(why);
                if why == "parent_cancelled" {
                    set(&mut row, "cancel_requested", Value::Bool(true));
                }
            }
            set(&mut row, "last_error", crate::value::optional(reason));
            let row = validated_record(row.clone())?;
            let columns = record_columns();
            let values: Vec<Value> = columns.iter().map(|name| get(&row, name).clone()).collect();
            execute(
                connection,
                &format!("INSERT INTO interruptions ({}) VALUES ({})", columns.join(","), marks(columns.len())),
                &values,
            )?;
            event(connection, now, "detected", Event {
                record: Some(&row),
                to_state: text_of(&row, "state"),
                reason: crate::value::optional(reason),
                turn_ref: Some("failed"),
                ..Event::default()
            })?;
            Ok(true)
        })
    }

    /// `claimed_on_thread(thread_id)`: records that may have put a continuation into this thread.
    pub fn claimed_on_thread(&self, thread_id: &str) -> Result<Vec<Row>> {
        uuid_text(thread_id, "thread_id")?;
        self.read(|connection| {
            self.records(
                connection,
                " WHERE thread_id=? AND (last_claim_at IS NOT NULL OR submitted_at IS NOT NULL OR legacy=1) ORDER BY detected_at",
                &[string(thread_id)],
            )
        })
    }

    /// `chain_parent(thread_id, turn_id, owner_id)`: the record `register` would continue, nothing written.
    pub fn chain_parent(
        &self,
        thread_id: &str,
        turn_id: &str,
        owner_id: Option<&str>,
    ) -> Result<Option<Row>> {
        self.read(|connection| {
            self.find_parent(connection, &string(thread_id), &string(turn_id), owner_id)
        })
    }

    fn find_parent(
        &self,
        connection: &Connection,
        thread_id: &Value,
        turn_id: &Value,
        owner_id: Option<&str>,
    ) -> Result<Option<Row>> {
        let found = self.records(
            connection,
            " WHERE thread_id=? AND recovery_turn_id=?",
            &[thread_id.clone(), turn_id.clone()],
        )?;
        if let Some(found) = found.into_iter().next() {
            return Ok(Some(found));
        }
        let Some(owner_id) = owner_id else {
            return Ok(None);
        };
        match self.row(connection, owner_id)? {
            Some(owner) if py_eq(get(&owner, "thread_id"), thread_id) => Ok(Some(owner)),
            _ => Ok(None),
        }
    }

    fn parent(
        &self,
        connection: &Connection,
        row: &Row,
        owner_id: Option<&str>,
    ) -> Result<Option<Row>> {
        let owner = self.find_parent(
            connection,
            get(row, "thread_id"),
            get(row, "turn_id"),
            owner_id,
        )?;
        let Some(mut owner) = owner else {
            return Ok(None);
        };
        if text_of(&owner, "interruption_id") != owner_id {
            return Ok(Some(owner));
        }
        if matches!(get(&owner, "recovery_turn_id"), Value::Null) {
            match execute(
                connection,
                "UPDATE interruptions SET recovery_turn_id=? WHERE interruption_id=? AND recovery_turn_id IS NULL",
                &[
                    get(row, "turn_id").clone(),
                    string(owner_id.unwrap_or_default()),
                ],
            ) {
                Ok(_) => set(&mut owner, "recovery_turn_id", get(row, "turn_id").clone()),
                Err(error) => {
                    let error = Error::from(error);
                    if !error.is_integrity() {
                        return Err(error);
                    }
                }
            }
        }
        Ok(Some(owner))
    }

    /// `get(interruption_id)`.
    pub fn get(&self, interruption_id: &str) -> Result<Option<Row>> {
        self.read(|connection| self.row(connection, interruption_id))
    }

    /// `all_records()`, oldest first.
    pub fn all_records(&self) -> Result<Vec<Row>> {
        self.read(|connection| {
            self.records(connection, " ORDER BY detected_at, interruption_id", &[])
        })
    }

    /// `records_in(states, home_key=None)`.
    pub fn records_in(&self, states: &[String], home_key: Option<&str>) -> Result<Vec<Row>> {
        let wanted: Vec<&str> = STATES
            .iter()
            .copied()
            .filter(|state| states.iter().any(|asked| asked == state))
            .collect();
        if wanted.is_empty() {
            return Ok(Vec::new());
        }
        let mut parameters = words(&wanted);
        let home = match home_key {
            Some(home) => {
                parameters.push(string(home));
                " AND home_key=?"
            }
            None => "",
        };
        self.read(|connection| {
            self.records(
                connection,
                &format!(
                    " WHERE state IN ({}){home} ORDER BY detected_at, interruption_id",
                    marks(wanted.len())
                ),
                &parameters,
            )
        })
    }

    /// `home_keys()`: the other Codex homes records waiting now are of, sorted.
    pub fn home_keys(&self) -> Result<Vec<Value>> {
        let waiting = words(WAITING);
        let found = self.read(|connection| {
            Ok(tuples(
                connection,
                &format!("SELECT DISTINCT home_key FROM interruptions WHERE home_key<>'' AND state IN ({})", marks(waiting.len())),
                &waiting,
            )?)
        })?;
        Ok(crate::policy::sorted_set(
            found.into_iter().map(|mut row| row.remove(0)).collect(),
        ))
    }

    /// `cancel_home(home_key, now, reason)`: how many of that home's waiting records were cancelled.
    pub fn cancel_home(&self, home_key: &str, now: f64, reason: &str) -> Result<i64> {
        check_now(now)?;
        if home_key.is_empty() {
            return Err(Error::store("The default Codex home is never removed"));
        }
        let waiting = words(WAITING);
        self.transaction(|connection| {
            let mut parameters = vec![string(home_key)];
            parameters.extend(waiting.iter().cloned());
            let found = self.records(connection, &format!(" WHERE home_key=? AND state IN ({})", marks(waiting.len())), &parameters)?;
            for row in &found {
                execute(
                    connection,
                    "UPDATE interruptions SET state='cancelled', cancel_requested=1, last_error=?, outcome_at=? WHERE interruption_id=?",
                    &[string(reason), Value::Float(now), get(row, "interruption_id").clone()],
                )?;
                event(connection, now, "state", Event {
                    record: Some(row),
                    from_state: text_of(row, "state"),
                    to_state: Some("cancelled"),
                    reason: string(reason),
                    ..Event::default()
                })?;
            }
            Ok(found.len() as i64)
        })
    }

    /// `pending()`: every record not final.
    pub fn pending(&self) -> Result<Vec<Row>> {
        let states: Vec<String> = STATES
            .iter()
            .filter(|state| !TERMINAL.contains(state))
            .map(|state| state.to_string())
            .collect();
        self.records_in(&states, None)
    }

    /// `failure_marks()`: {failed_at, started_at, unconfirmed_at} for the icon.
    pub fn failure_marks(&self) -> Result<Row> {
        let newest = |states: &[&str]| {
            format!(
                "SELECT max(outcome_at) FROM interruptions WHERE state IN ({}) AND outcome_at IS NOT NULL AND history_hidden_at IS NULL",
                marks(states.len())
            )
        };
        let as_words =
            |states: &[&str]| states.iter().map(|state| string(state)).collect::<Vec<_>>();
        let (failed, unconfirmed, started) = self.read(|connection| {
            let failed = crate::value::scalar(connection, &newest(FAILED_STATES), &as_words(FAILED_STATES))?;
            let unconfirmed = crate::value::scalar(connection, &newest(UNCONFIRMED_STATES), &as_words(UNCONFIRMED_STATES))?;
            let started = crate::value::scalar(
                connection,
                "SELECT max(max(coalesce(submitted_at, 0), coalesce(first_queued_at, 0), coalesce(turn_started_at, 0))) FROM interruptions",
                &[],
            )?;
            Ok((failed, unconfirmed, started))
        })?;
        let started = finite_value(&started, None).filter(|started| *started != 0.0);
        let mut marks_found = Row::new();
        marks_found.insert(
            key("failed_at"),
            crate::value::float_or_null(finite_value(&failed, None)),
        );
        marks_found.insert(key("started_at"), crate::value::float_or_null(started));
        marks_found.insert(
            key("unconfirmed_at"),
            crate::value::float_or_null(finite_value(&unconfirmed, None)),
        );
        Ok(marks_found)
    }

    /// `history(include_hidden=False, limit=500)`: records for display, newest first.
    pub fn history(&self, include_hidden: bool, limit: i64) -> Result<Vec<Row>> {
        let limit = limit.clamp(1, 10000);
        let filter = if include_hidden {
            ""
        } else {
            "WHERE history_hidden_at IS NULL"
        };
        self.read(|connection| {
            self.records(
                connection,
                &format!(" {filter} ORDER BY detected_at DESC, interruption_id LIMIT ?"),
                &[int(limit)],
            )
        })
    }

    /// `update(interruption_id, at=None, actor="engine", event=None, flags=0, **changes)`: a change within
    /// the transition table.
    pub fn update(&self, interruption_id: &str, changes: &Row, options: &Update) -> Result<()> {
        if changes.is_empty()
            || !changes
                .keys()
                .all(|name| name.as_str().is_some_and(|name| MUTABLE.contains(&name)))
        {
            return Err(Error::store("Invalid record update"));
        }
        self.transaction(|connection| {
            let Some(old) = self.row(connection, interruption_id)? else {
                return Err(Error::store("Unknown interruption"));
            };
            let mut merged = old.clone();
            for (name, value) in changes {
                merged.insert(name.clone(), value.clone());
            }
            let row = validated_record(merged)?;
            let old_state = text_of(&old, "state").expect("validated");
            let new_state = text_of(&row, "state").expect("validated");
            if !plain_move_allowed(old_state, new_state) {
                if has(TERMINAL, old_state) {
                    return Err(Error::store("Cannot reactivate terminal interruption"));
                }
                return Err(Error::store(format!(
                    "Illegal state transition {old_state} -> {new_state}"
                )));
            }
            let was_sent = !matches!(get(&old, "submitted_at"), Value::Null);
            if was_sent && matches!(get(&row, "submitted_at"), Value::Null) {
                if !(old_state == "submitting"
                    && matches!(new_state, "waiting_retry" | "failed")
                    && matches!(get(&old, "queue_id"), Value::Null))
                {
                    return Err(Error::store("Cannot clear possible submission"));
                }
            } else if old_state == "submitting" && new_state == "waiting_retry" {
                return Err(Error::store(
                    "A claimed record returns to waiting only with its send disproved",
                ));
            }
            let old_turn = get(&old, "recovery_turn_id");
            if !matches!(old_turn, Value::Null) && !py_eq(get(&row, "recovery_turn_id"), old_turn) {
                return Err(Error::store("A recovery turn is written once"));
            }
            if truthy(get(&old, "cancel_requested")) && !truthy(get(&row, "cancel_requested")) {
                return Err(Error::store("A cancellation cannot be withdrawn"));
            }
            if has(WAITING, new_state) && was_resent(&old) {
                return Err(Error::store("A resent continuation never waits again"));
            }
            let names: Vec<&str> = changes.keys().filter_map(|name| name.as_str()).collect();
            let assignments = names
                .iter()
                .map(|name| format!("{name}=?"))
                .collect::<Vec<_>>()
                .join(",");
            let mut values: Vec<Value> = names.iter().map(|name| get(&row, name).clone()).collect();
            values.push(string(interruption_id));
            execute(
                connection,
                &format!("UPDATE interruptions SET {assignments} WHERE interruption_id=?"),
                &values,
            )?;
            let entry = |connection: &Connection, code: &str| -> Result<()> {
                event(
                    connection,
                    self.now(options.at)?,
                    code,
                    Event {
                        record: Some(&row),
                        from_state: Some(old_state),
                        to_state: Some(new_state),
                        reason: get(&row, "last_error").clone(),
                        actor: &options.actor,
                        flags: options.flags,
                        ..Event::default()
                    },
                )
            };
            if let Some(code) = &options.event {
                entry(connection, code)?;
            } else if old_state != new_state
                || !py_eq(get(&old, "last_error"), get(&row, "last_error"))
            {
                entry(connection, "state")?;
            }
            Ok(())
        })
    }
}
