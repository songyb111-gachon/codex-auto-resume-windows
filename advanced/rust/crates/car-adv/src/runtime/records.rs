//! `Runtime.records` (P2) and the edition's own records' other points (`runtime.py`).

use std::collections::BTreeSet;

use car_machine::json::Value;
use car_policy::plug::hands::RECORDS_LIMIT;
use car_policy::plug::{Point, View};

use super::ask::{hook, null_answer};
use super::{Py, Runtime, caught, field, key_value, number};
use crate::capabilities::Said;
use crate::engine::chat::CAPABILITY as CHAT;
use crate::engine::promptqueue::CAPABILITY as PROMPT_QUEUE;
use crate::state::resets::UNLAUNCHED_AFTER;
use crate::vocabulary::{ArmingState, ContinuationReason, JournalCode, KeepReason, PromptReason};

impl Runtime {
    /// `records(view)`: the records of this edition's own that core is to try, or to watch - every message in flight
    /// (handed back first where its launch never began), then what each capability that is on answers.
    pub fn records(&self, view: &dyn View) -> Py<Vec<Value>> {
        let now = |runtime: &Runtime| Value::Float(runtime.now());
        let after = Value::Float(UNLAUNCHED_AFTER);
        // A claim whose launch never began is handed back first (state/resets.release_unlaunched); tried again at the
        // next P2 where the state refuses.
        let released = (|| -> Result<(), crate::state::Error> {
            self.state.release_unlaunched(&now(self))?;
            self.state
                .release_unlaunched_continuations(&after, &now(self))?;
            self.state.release_unlaunched_prompts(&after, &now(self))?;
            self.state.release_unlaunched_chats(&after, &now(self))?;
            Ok(())
        })();
        caught(released)?;
        let flying = (|| -> Result<Vec<Option<Value>>, crate::state::Error> {
            let mut flying: Vec<Option<Value>> = Vec::new();
            for rule in self.state.messages_in_flight()? {
                flying.push(crate::engine::resetmessage::handed(&rule));
            }
            for row in self.state.continuations_in_flight()? {
                flying.push(crate::engine::continued::handed(&Value::Object(row)));
            }
            for row in self.state.prompts_in_flight()? {
                flying.push(crate::engine::promptqueue::handed(&Value::Object(row)));
            }
            // v0.6.19: the chat's messages in flight - none taken back in a queue the forced stop paused (v0.6.26, M1).
            for row in self.state.chats_in_flight()? {
                let thread = row.get("thread_id").cloned().unwrap_or(Value::Null);
                let stops: Vec<Value> = self
                    .state
                    .continuations(&Value::Null, &thread, &Value::Null)?
                    .into_iter()
                    .map(Value::Object)
                    .collect();
                flying.push(crate::engine::chat::watched(
                    &Value::Object(row),
                    self.now(),
                    &stops,
                ));
            }
            Ok(flying)
        })();
        let flying = caught(flying)?.unwrap_or_default();
        // P2's eight: the longest in flight first, from a place that moves on each tick when there are more than core
        // takes; then one due of each capability in the registry's order, then the rest.
        let mut flying: Vec<Value> = flying.into_iter().flatten().collect();
        let sent_at = |record: &Value| {
            number(field(record, "sent_at"))
                .filter(|at| *at != 0.0)
                .unwrap_or(0.0)
        };
        flying.sort_by(|a, b| {
            sent_at(a)
                .partial_cmp(&sent_at(b))
                .unwrap_or(std::cmp::Ordering::Equal)
        });
        if flying.len() > RECORDS_LIMIT {
            let start = (self.records_turn.get() * RECORDS_LIMIT) % flying.len();
            flying.rotate_left(start);
        }
        self.records_turn.set(self.records_turn.get() + 1);
        let states = self.states(false, &[]);
        let mut due: Vec<Vec<Value>> = Vec::new();
        for definition in self.registry.at(Point::Records) {
            let state = states.state_of(&definition.id);
            if state == ArmingState::Shadow {
                self.watched_records(definition, view)?;
                continue;
            }
            if state != ArmingState::Armed {
                continue;
            }
            let answer = match self.call(definition, |code| code.records(view)) {
                Ok(answer) => answer,
                Err(raised) => {
                    self.tripped(definition, None, &raised);
                    continue;
                }
            };
            match answer {
                Said::Value(Value::Array(found)) | Said::Tuple(found) => due.push(found),
                _ => {}
            }
        }
        let firsts: Vec<Value> = due
            .iter()
            .filter_map(|answer| answer.first().cloned())
            .collect();
        let rest: Vec<Value> = due
            .iter()
            .flat_map(|answer| answer.iter().skip(1).cloned())
            .collect();
        let held = self.holders(&states)?;
        let mut seen: BTreeSet<String> = BTreeSet::new();
        let mut found = Vec::new();
        for answer in [flying, firsts, rest] {
            for record in answer {
                let key = match &record {
                    Value::Object(map) => map
                        .get("record_id")
                        .filter(|key| !matches!(key, Value::Null))
                        .map(key_value),
                    _ => None,
                };
                let Some(key) = key else {
                    continue;
                };
                if self.held(&held, &record) {
                    continue; // held back this tick (usage_pause's `holds`)
                }
                if seen.insert(key) {
                    found.push(record);
                }
            }
        }
        Ok(found)
    }

    /// `_holders(states)`: the `holds` of every capability on (v0.6.16-beta.3, usage_pause); each says whether a record
    /// of the edition's own waiting is held back this tick, True only. One that raises holds nothing; a code without
    /// `holds` answers None and holds nothing. The codes are made here, as `_own(self._code_of(definition), ...)` is.
    fn holders(&self, states: &crate::arming::States) -> Py<Vec<String>> {
        let mut found = Vec::new();
        for definition in self.registry.iter() {
            if states.state_of(&definition.id) != ArmingState::Armed {
                continue;
            }
            if let Err(raised) = self.code_of(definition) {
                return Err(super::Raise(super::ask::class_of(&raised)));
            }
            found.push(definition.id.clone());
        }
        Ok(found)
    }

    /// Whether one of `holders` holds `record` back this tick (`holds(dict(record)) is True`).
    fn held(&self, holders: &[String], record: &Value) -> bool {
        holders.iter().any(|id| {
            self.registry.get(id).is_some_and(|definition| {
                matches!(
                    self.call_own(definition, |code| code.holds(record)),
                    Ok(Some(Ok(Value::Bool(true))))
                )
            })
        })
    }

    /// `_watched_records(definition, view)`: P2 for a watched capability - each row it would hand core now, as its
    /// code decides it (`watched_due`, looked up with `getattr`), journalled once as what it would have sent.
    fn watched_records(
        &self,
        definition: &crate::registry::CapabilityDef,
        view: &dyn View,
    ) -> Py<()> {
        let keys = match self.call_own(definition, |code| code.watched_due(view)) {
            Err(raised) => return Err(super::Raise(super::ask::class_of(&raised))),
            Ok(None) => return Ok(()),
            Ok(Some(Err(_))) => return Ok(()), // a watched one's look costs nothing, and trips nothing
            Ok(Some(Ok(keys))) => keys,
        };
        // `for key in keys or ()`: a false answer is none; one that is not iterable raises out of P2.
        let keys: Vec<Value> = if !keys.truthy() {
            Vec::new()
        } else {
            match keys {
                Said::Value(Value::Array(items)) | Said::Tuple(items) | Said::Set(items) => items,
                Said::Value(Value::Object(map)) => {
                    map.keys().map(|key| Value::Str(key.clone())).collect()
                }
                Said::Value(Value::Str(text)) => text
                    .as_str()
                    .unwrap_or_default()
                    .chars()
                    .map(|each| Value::Str(each.to_string().into()))
                    .collect(),
                _ => return Err(super::Raise("TypeError")),
            }
        };
        for key in keys {
            if let Value::Str(_) = key {
                let mut record = car_machine::json::Map::new();
                record.insert("interruption_id".into(), key);
                let record = Value::Object(record);
                self.once(
                    JournalCode::WouldHave,
                    definition,
                    Point::Records,
                    Point::Records.as_str(),
                    Some(&record),
                )?;
            }
        }
        Ok(())
    }

    /// `conversation_off(thread_id)`: every message, continuation, keep going and prompt waiting there ends at once.
    pub fn conversation_off(&self, thread_id: &Value) -> Py<()> {
        let ended = (|| -> Result<(), crate::state::Error> {
            self.state
                .end_messages_in(thread_id, &Value::Float(self.now()))?;
            self.state.end_continuations(
                &Value::Str(ContinuationReason::ConversationOff.as_str().into()),
                &Value::Null,
                thread_id,
                &Value::Float(self.now()),
            )?;
            self.state.stop_keep_going(
                &Value::Str(KeepReason::ConversationOff.as_str().into()),
                thread_id,
                &Value::Float(self.now()),
            )?;
            self.state.end_prompts(
                &Value::Str(PromptReason::ConversationOff.as_str().into()),
                thread_id,
                &Value::Float(self.now()),
            )?;
            Ok(())
        })();
        caught(ended)?;
        Ok(())
    }

    /// `_own_record_answer(point, arguments)`: P5 and P15 for a record of this edition's own - the prompt queue's
    /// pictures, the chat's own channel while chat is on, and NULL's answer for everything else.
    pub(crate) fn own_record_answer(&self, point: Point, args: &[&Value]) -> Py<Said> {
        let record = args.first().copied().unwrap_or(&Value::Null);
        if let Some(pictured) = self.pictured_answer(point, args) {
            return Ok(pictured);
        }
        let armed = self.states(false, &[]).state_of(CHAT) == ArmingState::Armed;
        if point == Point::Delivery || (point == Point::Sender && armed) {
            let definition = self.registry.get(CHAT);
            let owned = definition.is_some()
                && matches!(
                    caught(self.state.chat_by_record(field(record, "record_id"))),
                    Ok(Some(Some(_)))
                );
            if let (true, Some(definition)) = (owned, definition) {
                return match self.call(definition, |code| hook(code, point, args)) {
                    Ok(said) => Ok(said),
                    Err(raised) => Err(super::Raise(super::ask::class_of(&raised))),
                };
            }
        }
        Ok(null_answer(point))
    }

    /// `_pictured_answer(point, arguments)`: P5 and P15 for a scheduled message with pictures (v0.6.20).
    fn pictured_answer(&self, point: Point, args: &[&Value]) -> Option<Said> {
        if !matches!(point, Point::Sender | Point::Delivery) {
            return None;
        }
        let definition = self.registry.get(PROMPT_QUEUE)?;
        if point == Point::Sender
            && self.states(false, &[]).state_of(PROMPT_QUEUE) != ArmingState::Armed
        {
            return None;
        }
        let record = args.first().copied().unwrap_or(&Value::Null);
        // `if not code.images_of(record)`: inside the reference's try, so a raise - or no code - is None.
        match self.call_own(definition, |code| code.images_of(record)) {
            Ok(Some(Ok(images))) if images.truthy() => {}
            _ => return None,
        }
        self.call(definition, |code| hook(code, point, args)).ok()
    }
}
