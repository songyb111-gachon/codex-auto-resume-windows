//! What a person asks for: stop this, stop the conversation, try now, give the attempts back
//! (store/actions.py).

use car_machine::json::Value;

use crate::errors::{Error, Result};
use crate::journal::{Event, event};
use crate::machine::vocab::{EXHAUSTED, IN_FLIGHT, OBSERVING, REASONS, TERMINAL, WAITING};
use crate::machine::{has, waiting_state};
use crate::session::Store;
use crate::validate::{now as check_now, uuid_text};
use crate::value::{
    Row, execute, get, int, key, marks, or_zero, py_eq, string, text, text_of, truthy, words,
};

pub const MAX_BUDGET_RESETS: i64 = 3;
/// How long an unresolved `submission_unknown` is still being reconciled.
pub const UNKNOWN_WINDOW: f64 = 24.0 * 3600.0;

pub const RETIRED: &str = "retired";
pub const RECHECKED: &str = "rechecked";
pub const UNRESOLVED: &str = "unresolved";
/// The journal word of each rescan finding.
pub const RESCAN_EVENTS: &[(&str, &str)] = &[
    (RETIRED, "rescan_retired"),
    (RECHECKED, "rescan_rechecked"),
    (UNRESOLVED, "rescan_unresolved"),
];
pub const RESCAN_CHANGED: &str = "rescan_changed";
/// What a record must still hold, as the rescan read it, for its finding to be applied.
pub const RESCAN_FIELDS: &[&str] = &[
    "interruption_id",
    "thread_id",
    "turn_id",
    "ordinal",
    "home_key",
    "chain_origin_id",
    "category",
    "state",
    "cancel_requested",
    "submitted_at",
    "queue_id",
    "recovery_client_id",
    "hold",
    "not_before",
    "retry_now_count",
    "budget_resets",
    "attempt_count",
    "recovery_attempts",
];

/// Why a record that is not waiting cannot be acted on, in the retry's words.
pub(crate) fn not_waiting(state: &str) -> &'static str {
    if has(TERMINAL, state) {
        "finished"
    } else if has(OBSERVING, state) {
        "observing"
    } else if has(IN_FLIGHT, state) {
        "in_flight"
    } else {
        "claimed"
    }
}

/// (accepted, detail): the answer of a person's action.
pub type Answer = (bool, Value);

impl Store {
    /// `cancel_interruption(interruption_id, now, actor="gui")`: one recovery stopped, and its whole chain.
    pub fn cancel_interruption(
        &self,
        interruption_id: &str,
        now: f64,
        actor: &str,
    ) -> Result<Option<Row>> {
        check_now(now)?;
        self.transaction(|connection| {
            let Some(row) = self.row(connection, interruption_id)? else { return Ok(None) };
            let chain = self.records(connection, " WHERE chain_origin_id=? ORDER BY detected_at", &[get(&row, "chain_origin_id").clone()])?;
            let mut effects = Row::new();
            let mut changed = false;
            for member in &chain {
                let member_key = get(member, "interruption_id").clone();
                let state = text_of(member, "state").unwrap_or_default();
                let effect = if has(WAITING, state) && matches!(get(member, "submitted_at"), Value::Null) {
                    execute(
                        connection,
                        "UPDATE interruptions SET state='cancelled', cancel_requested=1, last_error='user_cancelled', next_retry_at=?, outcome_at=? WHERE interruption_id=?",
                        &[Value::Float(now), Value::Float(now), member_key.clone()],
                    )?;
                    event(connection, now, "cancel", Event {
                        record: Some(member),
                        from_state: Some(state),
                        to_state: Some("cancelled"),
                        reason: string("user_cancelled"),
                        actor,
                        ..Event::default()
                    })?;
                    changed = true;
                    "cancelled"
                } else if truthy(get(member, "cancel_requested")) {
                    "unchanged"
                } else {
                    execute(connection, "UPDATE interruptions SET cancel_requested=1 WHERE interruption_id=?", std::slice::from_ref(&member_key))?;
                    event(connection, now, "cancel_requested", Event {
                        record: Some(member),
                        from_state: Some(state),
                        to_state: Some(state),
                        actor,
                        ..Event::default()
                    })?;
                    if has(TERMINAL, state) && state != "submission_unknown" {
                        "blocked_future"
                    } else {
                        changed = true;
                        "cancel_requested"
                    }
                };
                if let Value::Str(name) = member_key {
                    effects.insert(name, string(effect));
                }
            }
            let mut answer = Row::new();
            answer.insert(key("changed"), Value::Bool(changed));
            answer.insert(key("effects"), Value::Object(effects));
            Ok(Some(answer))
        })
    }

    /// `cancel_waiting(interruption_ids, now, reason)`: those still waiting and never sent, cancelled; their ids.
    pub fn cancel_waiting(
        &self,
        interruption_ids: &[Value],
        now: f64,
        reason: &str,
    ) -> Result<Vec<Value>> {
        check_now(now)?;
        let keys: Vec<&Value> = interruption_ids
            .iter()
            .filter(|key| matches!(key, Value::Str(_)))
            .collect();
        let waiting = words(WAITING);
        self.transaction(|connection| {
            let mut found = Vec::new();
            for wanted in &keys {
                let mut parameters = vec![(*wanted).clone()];
                parameters.extend(waiting.iter().cloned());
                found.extend(self.records(
                    connection,
                    &format!(" WHERE interruption_id=? AND submitted_at IS NULL AND state IN ({})", marks(waiting.len())),
                    &parameters,
                )?);
            }
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
            Ok(found.iter().map(|row| get(row, "interruption_id").clone()).collect())
        })
    }

    /// `cancel_thread(thread_id, now, actor="gui")`: automatic recovery off for one conversation, and its
    /// records stopped.
    pub fn cancel_thread(&self, thread_id: &str, now: f64, actor: &str) -> Result<()> {
        uuid_text(thread_id, "thread_id")?;
        check_now(now)?;
        self.transaction(|connection| {
            execute(
                connection,
                "INSERT INTO threads (thread_id, enabled) VALUES (?,0) ON CONFLICT(thread_id) DO UPDATE SET enabled=0",
                &[string(thread_id)],
            )?;
            for row in self.records(connection, " WHERE thread_id=?", &[string(thread_id)])? {
                let state = text_of(&row, "state").unwrap_or_default();
                if has(TERMINAL, state) {
                    continue;
                }
                if !matches!(get(&row, "submitted_at"), Value::Null) {
                    if !truthy(get(&row, "cancel_requested")) {
                        execute(connection, "UPDATE interruptions SET cancel_requested=1 WHERE interruption_id=?", &[get(&row, "interruption_id").clone()])?;
                        event(connection, now, "cancel_requested", Event {
                            record: Some(&row),
                            from_state: Some(state),
                            to_state: Some(state),
                            actor,
                            ..Event::default()
                        })?;
                    }
                } else {
                    execute(
                        connection,
                        "UPDATE interruptions SET state='cancelled', cancel_requested=1, last_error='user_cancelled', next_retry_at=?, outcome_at=? WHERE interruption_id=?",
                        &[Value::Float(now), Value::Float(now), get(&row, "interruption_id").clone()],
                    )?;
                    event(connection, now, "cancel", Event {
                        record: Some(&row),
                        from_state: Some(state),
                        to_state: Some("cancelled"),
                        reason: string("user_cancelled"),
                        actor,
                        ..Event::default()
                    })?;
                }
            }
            Ok(())
        })
    }

    /// `restore_budget(interruption_id, now, ...)`.
    pub fn restore_budget(
        &self,
        interruption_id: &str,
        now: f64,
        actor: &str,
        max_resets: i64,
    ) -> Result<bool> {
        Ok(self
            .restore_budget_detailed(interruption_id, now, actor, max_resets)?
            .0)
    }

    /// `restore_budget_detailed(interruption_id, now, actor="gui", max_resets=3)`: (restored, detail).
    pub fn restore_budget_detailed(
        &self,
        interruption_id: &str,
        now: f64,
        actor: &str,
        max_resets: i64,
    ) -> Result<Answer> {
        check_now(now)?;
        self.transaction(|connection| {
            let Some(row) = self.row(connection, interruption_id)? else { return Ok((false, string("unknown_record"))) };
            let state = text_of(&row, "state").unwrap_or_default();
            if !has(EXHAUSTED, state) {
                return Ok((false, string("not_exhausted")));
            }
            if truthy(get(&row, "cancel_requested")) {
                return Ok((false, string("cancel_requested")));
            }
            if !matches!(get(&row, "submitted_at"), Value::Null) || !matches!(get(&row, "queue_id"), Value::Null) {
                return Ok((false, string("possibly_sent")));
            }
            if or_zero(get(&row, "budget_resets")) >= max_resets as f64 {
                return Ok((false, string("reset_limit")));
            }
            let target = waiting_state(&row, now)?;
            execute(
                connection,
                "UPDATE interruptions SET state=?, recovery_attempts=0, no_progress_count=0, retry_count=0, chain_continuations=0, budget_resets=budget_resets+1, chain_first_detected_at=detected_at, last_error='budget_restored', next_retry_at=? WHERE interruption_id=?",
                &[string(target), Value::Float(now), string(interruption_id)],
            )?;
            event(connection, now, "reset_budget", Event {
                record: Some(&row),
                from_state: Some(state),
                to_state: Some(target),
                reason: string("budget_restored"),
                actor,
                ..Event::default()
            })?;
            Ok((true, string(target)))
        })
    }

    /// `request_retry_now(interruption_id, now, actor="gui")`: the next check brought to now.
    pub fn request_retry_now(
        &self,
        interruption_id: &str,
        now: f64,
        actor: &str,
    ) -> Result<Answer> {
        check_now(now)?;
        self.transaction(|connection| {
            let Some(row) = self.row(connection, interruption_id)? else { return Ok((false, string("unknown_record"))) };
            if truthy(get(&row, "cancel_requested")) {
                return Ok((false, string("cancel_requested")));
            }
            let state = text_of(&row, "state").unwrap_or_default();
            if !has(WAITING, state) {
                return Ok((false, string(not_waiting(state))));
            }
            execute(
                connection,
                "UPDATE interruptions SET next_retry_at=?, retry_now_count=retry_now_count+1 WHERE interruption_id=?",
                &[Value::Float(now), string(interruption_id)],
            )?;
            event(connection, now, "retry_now", Event {
                record: Some(&row),
                from_state: Some(state),
                to_state: Some(state),
                reason: string("retry_now"),
                actor,
                ..Event::default()
            })?;
            Ok((true, python_max(&[Value::Float(now), get(&row, "reset_at").clone(), get(&row, "not_before").clone()])))
        })
    }

    /// `rescan_apply(interruption_id, seen, outcome, now, reason=None, actor="gui")`.
    pub fn rescan_apply(
        &self,
        interruption_id: &str,
        seen: &Row,
        outcome: &str,
        now: f64,
        reason: &Value,
        actor: &str,
    ) -> Result<bool> {
        check_now(now)?;
        let Some((_, code)) = RESCAN_EVENTS.iter().find(|(name, _)| *name == outcome) else {
            return Err(Error::Python("ValueError", "not a rescan outcome".into()));
        };
        let reason = match text(reason) {
            Some(word) if has(REASONS, word) => reason.clone(),
            _ if outcome == RETIRED => string("later_turn_exists"),
            _ => Value::Null,
        };
        self.transaction(|connection| {
            let Some(row) = self.row(connection, interruption_id)? else { return Ok(false) };
            let state = text_of(&row, "state").unwrap_or_default();
            let moved = RESCAN_FIELDS.iter().any(|field| !py_eq(get(&row, field), get(seen, field)));
            if moved
                || !has(WAITING, state)
                || truthy(get(&row, "cancel_requested"))
                || !matches!(get(&row, "submitted_at"), Value::Null)
                || !matches!(get(&row, "queue_id"), Value::Null)
            {
                event(connection, now, RESCAN_CHANGED, Event {
                    record: Some(&row),
                    from_state: Some(state),
                    to_state: Some(state),
                    actor,
                    ..Event::default()
                })?;
                return Ok(false);
            }
            let target = if outcome == RETIRED { "superseded_by_user" } else { state };
            if outcome == RETIRED {
                execute(
                    connection,
                    "UPDATE interruptions SET state=?, last_error=?, outcome_at=?, next_retry_at=? WHERE interruption_id=?",
                    &[string(target), reason.clone(), Value::Float(now), Value::Float(now), string(interruption_id)],
                )?;
            }
            event(connection, now, code, Event {
                record: Some(&row),
                from_state: Some(state),
                to_state: Some(target),
                reason: reason.clone(),
                actor,
                ..Event::default()
            })?;
            Ok(true)
        })
    }

    /// `hide_history(now, actor="gui")`: {hidden, kept}. Display only; never deletes a row.
    pub fn hide_history(&self, now: f64, actor: &str) -> Result<Row> {
        check_now(now)?;
        self.transaction(|connection| {
            let (mut hidden, mut kept) = (0i64, 0i64);
            for row in self.records(connection, " WHERE history_hidden_at IS NULL", &[])? {
                let state = text_of(&row, "state").unwrap_or_default();
                if !has(TERMINAL, state) {
                    kept += 1;
                    continue;
                }
                if state == "submission_unknown" {
                    let sent =
                        crate::value::or(get(&row, "submitted_at"), get(&row, "detected_at"));
                    if !matches!(get(&row, "queue_id"), Value::Null)
                        || now - crate::value::arithmetic(&sent).unwrap_or(0.0) < UNKNOWN_WINDOW
                    {
                        kept += 1;
                        continue;
                    }
                }
                execute(
                    connection,
                    "UPDATE interruptions SET history_hidden_at=? WHERE interruption_id=?",
                    &[Value::Float(now), get(&row, "interruption_id").clone()],
                )?;
                hidden += 1;
            }
            if hidden != 0 {
                event(
                    connection,
                    now,
                    "hidden",
                    Event {
                        actor,
                        value: Some(hidden as f64),
                        ..Event::default()
                    },
                )?;
            }
            let mut answer = Row::new();
            answer.insert(key("hidden"), int(hidden));
            answer.insert(key("kept"), int(kept));
            Ok(answer)
        })
    }
}

/// Python's `max(a, b or 0, c or 0)` of the retry's answer: the largest, the first of equals, `x or 0` for
/// each after the first.
fn python_max(values: &[Value]) -> Value {
    let mut best = values[0].clone();
    for value in &values[1..] {
        let candidate = if truthy(value) { value.clone() } else { int(0) };
        if crate::value::arithmetic(&candidate).unwrap_or(0.0)
            > crate::value::arithmetic(&best).unwrap_or(0.0)
        {
            best = candidate;
        }
    }
    best
}
