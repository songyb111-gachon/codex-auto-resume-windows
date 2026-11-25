//! Reading how a recovered turn ended, and what that costs the budgets (`engine/outcome.py`).
//!
//! Progress is the measure: a turn that ran and produced nothing is not a success, and a usage limit met again is a
//! wait rather than a failure.

use car_machine::domain::states::{BOOT_MARGIN, ended_by_boot};
use car_machine::json::Value;
use car_machine::pyval::{self, Py};
use car_machine::vocab_gen::domain_states::OBSERVING;

use crate::impossible::usage_reason;
use crate::py::{self, field, get, s, text, text_of, truthy};
use crate::{Engine, Row};

/// A Windows start this many seconds after the turn was seen starting ended it.
pub const CUT_OFF_BOOT_MARGIN: f64 = BOOT_MARGIN;

impl Engine {
    // ----------------------------------------------------------- the outcome
    /// `observe(row)`: follow our own recovery turn to its end, reading that turn only.
    pub fn observe(&mut self, row: &Row) -> Py<()> {
        let now = self.now();
        let proof = self.proof(row);
        let seen = self
            .source
            .turn_observation(
                &s(row, "thread_id"),
                text_of(row, "recovery_turn_id").unwrap_or_default(),
                &proof,
            )
            .ok();
        let deadline = py::or_number(get(row, "turn_started_at"), now)?
            + self.options.unknown_reconcile_window_seconds;
        let status_of = |status: &Value| row_status(status);
        let Some(seen) = seen.filter(|seen| !seen.is_empty() && truthy(get(seen, "found"))) else {
            // Unreadable is unknown, never "no progress". It is retried until the deadline.
            if now >= deadline {
                self.transition(
                    row,
                    "outcome_unverified",
                    Some("outcome_deadline"),
                    None,
                    None,
                    Row::new(),
                )?;
            }
            return Ok(());
        };
        let status = get(&seen, "status").clone();
        let status_word = status_of(&status);
        let foreign = pyval::greater(get(&seen, "foreign_user_messages"), &Value::from(0))?;
        let with_status = |status: &Value| py::row(vec![("recovery_turn_status", status.clone())]);
        let state = s(row, "state");
        if foreign && matches!(get(&seen, "progress_before_foreign"), Value::Bool(true)) {
            // Our continuation worked, then a person's message entered the turn: a recovery.
            if state == "turn_started" {
                self.transition(
                    row,
                    "turn_completed",
                    None,
                    None,
                    None,
                    with_status(&status),
                )?;
            } else {
                self.transition(
                    row,
                    "recovered",
                    Some("progress_then_user_joined"),
                    None,
                    None,
                    with_status(&status),
                )?;
            }
        } else if foreign {
            // A person joined before the turn did anything: theirs, handed over at once.
            self.transition(
                row,
                "handed_over",
                Some("user_joined"),
                None,
                None,
                py::row(vec![
                    ("user_joined", Value::Bool(true)),
                    ("recovery_turn_status", status.clone()),
                ]),
            )?;
        } else if status_word == "other" {
            self.transition(
                row,
                "outcome_unverified",
                Some("unknown_turn_status"),
                None,
                None,
                py::row(vec![("recovery_turn_status", Value::from("other"))]),
            )?;
        } else if status_word == "inProgress" {
            if self.cut_off(row, &seen)? {
                // The row can never finish; judged as a failed turn is.
                if !truthy(get(&seen, "progress")) {
                    self.transition(
                        row,
                        "outcome_unverified",
                        Some("stale_turn_row"),
                        None,
                        None,
                        Row::new(),
                    )?;
                } else if state == "turn_started" {
                    self.transition(
                        row,
                        "turn_completed",
                        None,
                        None,
                        None,
                        with_status(&status),
                    )?;
                } else {
                    self.transition(
                        row,
                        "recovered",
                        Some("progress_then_turn_cut_off"),
                        None,
                        None,
                        with_status(&status),
                    )?;
                }
            } else if now >= deadline {
                self.transition(
                    row,
                    "outcome_unverified",
                    Some("outcome_deadline"),
                    None,
                    None,
                    Row::new(),
                )?;
            } else if text_of(row, "recovery_turn_status") != Some("inProgress") {
                self.store.update(
                    &s(row, "interruption_id"),
                    &py::row(vec![("recovery_turn_status", Value::from("inProgress"))]),
                    Some(now),
                    None,
                    0,
                )?;
            }
        } else if state == "turn_started" {
            self.transition(
                row,
                "turn_completed",
                None,
                None,
                None,
                with_status(&status),
            )?;
        } else {
            let completed = py::or(
                get(&seen, "completed_at"),
                py::or(get(row, "turn_started_at"), Value::Float(now)),
            );
            if now < py::num(&completed)? + self.options.settle_seconds {
                return Ok(());
            }
            let progress = truthy(get(&seen, "progress"));
            match status_word.as_str() {
                "completed" if progress => self.transition(
                    row,
                    "recovered",
                    Some("progress_observed"),
                    None,
                    None,
                    with_status(&status),
                )?,
                "completed" => self.transition(
                    row,
                    "completed_no_progress",
                    Some("no_progress_observed"),
                    None,
                    None,
                    with_status(&status),
                )?,
                // A recovery turn that ran and then failed is not a failed recovery (the next usage limit).
                "failed" if progress => self.transition(
                    row,
                    "recovered",
                    Some("progress_then_turn_failed"),
                    None,
                    None,
                    with_status(&status),
                )?,
                "failed" => self.transition(
                    row,
                    "recovery_turn_failed",
                    Some("turn_failed"),
                    None,
                    None,
                    with_status(&status),
                )?,
                "interrupted" => self.transition(
                    row,
                    "stopped_by_user",
                    Some("turn_interrupted"),
                    None,
                    None,
                    with_status(&status),
                )?,
                _ => {}
            }
        }
        Ok(())
    }

    /// `_cut_off(row, seen)`: whether a recovery turn whose row still says inProgress can no longer finish.
    fn cut_off(&self, row: &Row, seen: &Row) -> Py<bool> {
        let later = match seen.get("later_started") {
            Some(value) => value.clone(),
            None => get(seen, "later_terminal").clone(),
        };
        if truthy(&later) {
            return Ok(true);
        }
        let started = get(row, "turn_started_at");
        if !truthy(started) {
            return Ok(false);
        }
        let Ok(status) = self.store.watcher_status() else {
            return Ok(false);
        };
        let booted = status.map_or(Value::Null, |status| get(&status, "booted_at").clone());
        ended_by_boot(started, &booted)
    }

    /// `observe_all()`: every record following its recovery turn, each one's failure its own.
    pub fn observe_all(&mut self) -> Py<()> {
        for row in self.records(OBSERVING)? {
            if self.observe(&row).is_err() {
                self.log(
                    Some(&s(&row, "thread_id")),
                    "outcome_check_unavailable",
                    Value::Null,
                );
            }
        }
        Ok(())
    }

    // --------------------------------------------------------------- attempt
    /// `_usage_wait(row, limits, now)`: wait for usage, and give up on a limit that is never going to lift. Only time
    /// between two probes that both said "unavailable, no reset known" is counted, capped per interval.
    pub(crate) fn usage_wait(&mut self, row: &Row, limits: &Value, now: f64) -> Py<()> {
        let available = field(limits, "available")?.clone();
        let probe_reset = field(limits, "reset_at")?.clone();
        let candidates: Vec<&Value> = [get(row, "reset_at"), &probe_reset]
            .into_iter()
            .filter(|value| truthy(value))
            .collect();
        let reset = if candidates.is_empty() {
            None
        } else {
            Some(pyval::max(&candidates)?.clone())
        };
        let unavailable = matches!(available, Value::Bool(false));
        let poll = self.options.conservative_poll_seconds;
        let extra;
        if unavailable && reset.is_none() {
            let mut gap = 0.0;
            let probed = get(row, "usage_probe_at");
            if truthy(probed) {
                gap = (now - py::num(probed)?).max(0.0).min(1.5 * poll);
            }
            let total = py::num(get(row, "usage_unavailable_seconds"))? + gap;
            if total >= self.options.usage_never_available_seconds {
                return self.transition(
                    row,
                    "terminal_failure",
                    Some("usage_never_available"),
                    None,
                    None,
                    py::row(vec![
                        ("usage_unavailable_seconds", Value::Float(total)),
                        ("usage_probe_at", Value::Null),
                    ]),
                );
            }
            extra = py::row(vec![
                ("usage_unavailable_seconds", Value::Float(total)),
                ("usage_probe_at", Value::Float(now)),
            ]);
        } else {
            extra = if truthy(get(row, "usage_probe_at")) {
                py::row(vec![("usage_probe_at", Value::Null)])
            } else {
                Row::new()
            };
            if unavailable
                && let Some(reset) = &reset
                && now >= py::num(reset)? + self.options.usage_after_reset_seconds
            {
                return self.transition(
                    row,
                    "terminal_failure",
                    Some("usage_not_restored_after_reset"),
                    None,
                    None,
                    extra,
                );
            }
        }
        let wait = if truthy(&probe_reset) {
            60.0_f64.max(py::num(&probe_reset)? + self.options.reset_grace_seconds - now)
        } else {
            poll
        };
        // v0.6.26: and a read that said neither says which way it broke, where the helper's last answer names it.
        let reason = if unavailable {
            "usage_unavailable".to_owned()
        } else {
            usage_reason(limits, &self.backend.protocol_results())
        };
        self.transition(
            row,
            "waiting_for_usage",
            Some(&reason),
            Some(wait),
            None,
            extra,
        )
    }
}

/// A turn's status word, as observe compares it (`status == "..."`).
fn row_status(status: &Value) -> String {
    text(status).unwrap_or("\u{0}").to_owned()
}
