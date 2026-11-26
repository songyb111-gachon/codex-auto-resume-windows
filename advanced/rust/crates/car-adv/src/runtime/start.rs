//! `Runtime.start_route` (P9), `Runtime.supervise` (P13) and `_held_start` (`runtime.py`).

use car_machine::json::Value;
use car_policy::plug::Point;

use super::ask::{StrValue, null_answer};
use super::{HELD_WORDS, Py, Runtime, caught, field};
use crate::capabilities::Said;
use crate::registry::CapabilityDef;
use crate::vocabulary::{ArmingState, OffReason};

impl Runtime {
    /// `start_route(request)`: P9, asked where Codex has just started this plugin's MCP server. What every capability
    /// here stands at is read afresh, with a fresh check of Codex for those stored on or watched; where none names a
    /// route, why is kept for core's line (`start_held`).
    pub fn start_route(&self, request: &Value) -> Py<Said> {
        let definitions = self.registry.at(Point::StartRoute);
        *self.start_held.borrow_mut() = Value::Null;
        if definitions.is_empty() {
            return Ok(null_answer(Point::StartRoute));
        }
        let live: Vec<&str> = definitions
            .iter()
            .map(|definition| definition.id.as_str())
            .collect();
        self.states(true, &live);
        let answer = self.ask(Point::StartRoute, &[request])?;
        if answer.is_defer() {
            *self.start_held.borrow_mut() = self.held_start(&definitions)?;
        }
        Ok(answer)
    }

    /// `start_held()`.
    pub fn start_held(&self) -> Value {
        self.start_held.borrow().clone()
    }

    /// `supervise(facts)`: P13, asked by the launcher before it runs the watcher and once a watcher it ran has ended.
    pub fn supervise(&self, facts: &Value) -> Py<Said> {
        let definitions = self.registry.at(Point::Supervision);
        *self.supervise_held.borrow_mut() = Value::Null;
        if definitions.is_empty() {
            return Ok(null_answer(Point::Supervision));
        }
        let live: Vec<&str> = definitions
            .iter()
            .map(|definition| definition.id.as_str())
            .collect();
        self.states(true, &live);
        let answer = self.ask(Point::Supervision, &[facts])?;
        if answer.is_defer() && field(facts, "phase").as_str_value() == Some("start") {
            *self.supervise_held.borrow_mut() = self.held_start(&definitions)?;
        }
        Ok(answer)
    }

    /// `supervise_held()`.
    pub fn supervise_held(&self) -> Value {
        self.supervise_held.borrow().clone()
    }

    /// `_held_start(definitions)`: why no capability named a route, as one word, for the first stored on or watched at
    /// the read; None where every one was stored off. One only held back gets its `held` line here.
    fn held_start(&self, definitions: &[&CapabilityDef]) -> Py<Value> {
        if self.unreadable.get() {
            return Ok(Value::Str("unreadable".into()));
        }
        let why = self.arming.why();
        for definition in definitions {
            let word = match why.iter().find(|(id, _)| id == &definition.id) {
                Some((_, word)) => word.clone(),
                None => {
                    if self.since_of(&definition.id).is_none() {
                        continue; // stored off: nothing of it was on
                    }
                    if self.standing(&definition.id) == ArmingState::Armed {
                        "refused".to_owned() // asked, and named nothing core can carry out
                    } else {
                        OffReason::HookException.as_str().to_owned() // tripped off as it was asked
                    }
                }
            };
            if HELD_WORDS.contains(&word.as_str()) {
                caught(self.state.counted(
                    &Value::Str(definition.id.as_str().into()),
                    &Value::Str("held".into()),
                    &Value::Float(self.now()),
                ))?;
            }
            return Ok(Value::Str(word.into()));
        }
        Ok(Value::Null)
    }
}
