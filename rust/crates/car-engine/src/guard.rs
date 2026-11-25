//! The guards and the waits of v0.6.11, as the engine asks them: each reads nothing at the defaults
//! (`engine/guard.py`).
//!
//! When an interruption is detected, `detected_facts` takes what the two guards keep on its record and
//! `detection_wait` says how long it waits before its first look. When the recovery falls due, `guarded` takes the
//! task's digest again: under Hold a change keeps the record for a person (the store's `hold_changed`); under Tell it
//! goes on and its continuation's notice says the task changed. Neither guard sends anything or makes anything sooner.

use car_machine::json::{Map, Value};
use car_machine::pyval::Py;
use car_policy::classify::gates::{HELD, Vector, WAIT, gate};
use car_policy::classify::{guards, ladder};

use crate::py::{self, get, row, s, text_of, with};
use crate::{Engine, Row};

impl Engine {
    /// `draw()`: a number in [0, 1) for jitter - asked only when jitter is on.
    pub fn draw(&mut self) -> f64 {
        (self.draw_source)()
    }

    /// `_next_attempt(thread_id, turn_id, owner)`: which attempt at its task an interruption is.
    fn next_attempt(&self, thread_id: &str, turn_id: &str, owner: Option<&str>) -> Py<Value> {
        for row in self.claimed(thread_id)? {
            if text_of(&row, "recovery_turn_id") == Some(turn_id)
                || owner.is_some_and(|owner| text_of(&row, "interruption_id") == Some(owner))
            {
                return py::plus_one(get(&row, "recovery_attempts"));
            }
        }
        Ok(Value::from(1))
    }

    /// `detection_wait(category, ...)`: how long a temporary failure waits once detected.
    pub fn detection_wait(
        &mut self,
        category: &str,
        thread_id: &str,
        turn_id: &str,
        owner: Option<&str>,
        retry_after: &Value,
    ) -> Py<f64> {
        let values = self.values();
        let mut delay = if ladder::walks(&values) {
            let attempt = self.next_attempt(thread_id, turn_id, owner)?;
            Value::from(ladder::wait_before(
                &values,
                &attempt,
                &Value::from(category),
            )?)
        } else {
            Value::from(self.first_delay(category))
        };
        if let Value::Int(after) = retry_after
            && car_machine::pyval::greater(retry_after, &delay)?
        {
            delay = Value::Int(after.clone());
        }
        if matches!(get(&self.policy_values, "retry_jitter"), Value::Bool(true)) {
            let draw = self.draw();
            delay = ladder::jittered(&delay, &values, &Value::Float(draw))?;
        }
        py::num(&delay)
    }

    /// `detected_facts(thread_id)`: what the guards keep on a new record - each None while its guard is off.
    pub fn detected_facts(&self, thread_id: &str) -> Map {
        let values = self.values();
        let (watch, count) = (
            guards::watches_task(&values),
            guards::counts_tokens(&values),
        );
        if !(watch || count) {
            return row(vec![
                ("task_print", Value::Null),
                ("context_tokens", Value::Null),
            ]);
        }
        let facts = self
            .source
            .task_facts(thread_id, watch, count)
            .unwrap_or_else(|_| row(vec![("print", Value::Null), ("tokens", Value::Null)]));
        let found = get(&facts, "print");
        let task_print = if !watch {
            Value::Null
        } else if guards::is_print(found) {
            found.clone()
        } else {
            Value::from(guards::UNREADABLE)
        };
        let context_tokens = if count {
            guards::tokens(get(&facts, "tokens")).map_or(Value::Null, Value::from)
        } else {
            Value::Null
        };
        row(vec![
            ("task_print", task_print),
            ("context_tokens", context_tokens),
        ])
    }

    /// `_told_of(row)`: what the notice of a continuation just sent adds - that its task changed, under Tell.
    pub(crate) fn told_of(&mut self, row: &Row) -> Map {
        let key = s(row, "interruption_id");
        if !self.told.remove(&key) {
            return Map::new();
        }
        py::row(vec![("task_changed", Value::Bool(true))])
    }

    /// `_guarded(row, vector, now)`: at the moment of sending, True if the task-changed guard held this record.
    pub(crate) fn guarded(&mut self, row: &Row, vector: &mut Vector, now: f64) -> Py<bool> {
        let values = self.values();
        if !guards::watches_task(&values) || matches!(get(row, "task_print"), Value::Null) {
            return Ok(false);
        }
        let thread = s(row, "thread_id");
        let found = self
            .source
            .task_facts(&thread, true, false)
            .map(|facts| get(&facts, "print").clone())
            .unwrap_or(Value::Null);
        if !guards::changed(get(row, "task_print"), &found) {
            return Ok(false);
        }
        let key = s(row, "interruption_id");
        if guards::task_mode(&values) == "tell" {
            if !self.told.contains(&key) {
                if self.told.len() > 1024 {
                    self.told.clear();
                }
                self.told.insert(key);
                self.log(Some(&thread), "task_changed_told", Value::Null);
            }
            return Ok(false);
        }
        let print = if guards::is_print(&found) {
            found
        } else {
            Value::from(guards::UNREADABLE)
        };
        if self.store.hold_changed(&key, &print, now)? {
            vector.set("consent", gate(WAIT, HELD));
            self.store.record_gates(&key, vector, now)?;
            self.log(
                Some(&thread),
                &format!("held_by_guard_{}", guards::TASK_HOLD),
                Value::Null,
            );
            let held = with(row, vec![("hold", Value::from(guards::TASK_HOLD))]);
            let detail = py::row(vec![
                ("hold", Value::from(guards::TASK_HOLD)),
                ("state", Value::from("held")),
            ]);
            self.announce("interruption", &held, detail);
        }
        // A record that could not be held has moved, and sends nothing on this tick either.
        Ok(true)
    }
}
