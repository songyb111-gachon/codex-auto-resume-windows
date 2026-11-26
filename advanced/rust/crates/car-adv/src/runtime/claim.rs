//! `Runtime.claim` (P11) and `Runtime.partition` (P12) (`runtime.py`).

use std::collections::BTreeMap;

use car_machine::json::{Map, Value};
use car_policy::plug::hands::workers;
use car_policy::plug::{Alternative, Ledger, Point};
use rusqlite::Connection;

use super::ask::own_record;
use super::{ANSWER_WORDS, Py, Raise, Runtime, key_of, object, vouched_by};
use crate::capabilities::Said;
use crate::ledger::Answer;
use crate::vocabulary::{ArmingState, JournalCode};

/// The claim's connection as the ledger reads it: SQLite's own handle, borrowed for this call (never closed here).
fn connection_of(ledger: &mut dyn Ledger) -> Option<Connection> {
    let handle = ledger.sqlite()?;
    // SAFETY: car-store hands the handle of the connection whose claim is asking, valid for this call and under its
    // authorizer; `from_handle` never closes it, and the Connection made here is dropped before the call returns.
    unsafe { Connection::from_handle(handle.cast()).ok() }
}

impl Runtime {
    /// `claim(connection, record, now, carried)`: P11 - the ledger, told which capabilities' answers this claim
    /// carries. A ledger that breaks costs its answer on a claim of core's own and holds a claim that carries one of
    /// the plug's.
    pub fn claim(
        &self,
        ledger: &mut dyn Ledger,
        record: &Value,
        now: f64,
        carried: &[Point],
    ) -> Py<Option<Alternative>> {
        let connection = connection_of(ledger);
        if own_record(record) && object(record).is_some_and(|map| map.contains_key("phase")) {
            let answered = match &connection {
                Some(connection) => self.ledger().record(connection, record, now).ok(),
                None => None,
            };
            return Ok(match answered {
                Some(Answer::Defer) => None,
                _ => Some(Alternative::Hold), // a record that cannot be paid for is not sent
            });
        }
        let key = key_of(record);
        let entries: Vec<super::Acted> = self
            .acted
            .borrow_mut()
            .remove(&key)
            .map(|entries| entries.into_iter().collect())
            .unwrap_or_default();
        if carried.contains(&Point::Concurrency)
            && !entries.iter().any(|entry| entry.0 == Point::Concurrency)
        {
            return Ok(Some(Alternative::Hold)); // pooled, and nothing left to pay for it: one poll
        }
        let verified_word = Alternative::VerifiedReset.as_str();
        let vouched: Vec<&String> = entries
            .iter()
            .filter(|entry| {
                entry.0 == Point::Gates
                    && carried.contains(&entry.0)
                    && entry.2.as_deref() == Some(verified_word)
            })
            .map(|entry| &entry.1)
            .collect();
        let carrying: Vec<&String> = entries
            .iter()
            .filter(|entry| vouched_by(entry.0) && carried.contains(&entry.0))
            .map(|entry| &entry.1)
            .collect();
        let mut acted: BTreeMap<String, Vec<Value>> = BTreeMap::new();
        let mut order: Vec<String> = Vec::new();
        for (point, capability, word) in &entries {
            if carried.contains(point)
                && !(word.as_deref() == Some(verified_word) && !carrying.contains(&capability))
            {
                if !acted.contains_key(capability) {
                    order.push(capability.clone());
                }
                let words = acted.entry(capability.clone()).or_default();
                if let Some(word) = word.as_deref().filter(|word| ANSWER_WORDS.contains(word)) {
                    let word = Value::Str(word.into());
                    if !words.contains(&word) {
                        words.push(word);
                    }
                }
            }
        }
        let mut acted_value = Map::new();
        for capability in &order {
            let mut words = acted.remove(capability).unwrap_or_default();
            words.sort_by(|a, b| format!("{a:?}").cmp(&format!("{b:?}")));
            acted_value.insert(capability.as_str().into(), Value::Array(words));
        }
        let verified: Vec<Value> = {
            let mut both: Vec<&String> = vouched
                .iter()
                .copied()
                .filter(|each| carrying.contains(each))
                .collect();
            both.sort();
            both.dedup();
            both.into_iter()
                .map(|each| Value::Str(each.as_str().into()))
                .collect()
        };
        let unvouched = vouched.iter().any(|each| !carrying.contains(each));
        let answered = match &connection {
            Some(connection) => self
                .ledger()
                .claim(
                    connection,
                    record,
                    now,
                    &Value::Object(acted_value.clone()),
                    &Value::Array(verified),
                    unvouched,
                )
                .map_err(|error| error.class()),
            None => Err("ProgrammingError"),
        };
        let held = match answered {
            Ok(Answer::Hold) => true,
            Ok(Answer::Defer) => false,
            Err(class) => {
                if !acted_value.is_empty() {
                    return Ok(Some(Alternative::Hold));
                }
                return Err(Raise(class));
            }
        };
        if carried.contains(&Point::Text) && !held {
            let texted: Vec<String> = entries
                .iter()
                .filter(|entry| entry.0 == Point::Text)
                .map(|entry| entry.1.clone())
                .collect();
            self.texted.borrow_mut().insert(key.clone(), texted);
        }
        if carried.contains(&Point::Concurrency) && !held {
            // Journalled once the claim committed (`moved`): this runs inside its transaction.
            let pooled: Vec<String> = entries
                .iter()
                .filter(|entry| entry.0 == Point::Concurrency)
                .map(|entry| entry.1.clone())
                .collect();
            self.pooled.borrow_mut().insert(key, pooled);
        }
        Ok(held.then_some(Alternative::Hold))
    }

    /// `partition(records)`: P12 - how many sends may wait for their receipts at once: an armed capability's whole
    /// number, or DEFER (None). Each due record its ceilings leave a unit for is remembered as acted at CONCURRENCY.
    pub fn partition(&self, records: &Value) -> Py<Option<Value>> {
        let definitions = self.registry.at(Point::Concurrency);
        let Value::Array(items) = records else {
            return Ok(None);
        };
        if definitions.is_empty() {
            return Ok(None);
        }
        let states = self.states(false, &[]);
        for definition in definitions {
            let state = states.state_of(&definition.id);
            if state == ArmingState::Off {
                continue;
            }
            let answer = match self.call(definition, |code| code.partition(records)) {
                Ok(answer) => answer,
                Err(raised) => {
                    self.tripped(definition, None, &raised);
                    continue;
                }
            };
            let value = match &answer {
                Said::Value(value) => Some(value.clone()),
                _ => None,
            };
            if workers(value.as_ref()) == 1 {
                continue;
            }
            let word = Point::Concurrency.as_str();
            if state == ArmingState::Shadow {
                self.once(
                    JournalCode::WouldHave,
                    definition,
                    Point::Concurrency,
                    word,
                    None,
                )?;
                continue;
            }
            let mut paid = Vec::new();
            for record in items {
                if object(record).is_none() || self.is_skipped(&definition.id, &key_of(record)) {
                    continue;
                }
                if !self.ceiling(definition, record, false)? {
                    paid.push(key_of(record));
                }
            }
            if paid.is_empty() {
                self.once(
                    JournalCode::Ceiling,
                    definition,
                    Point::Concurrency,
                    word,
                    None,
                )?;
                continue;
            }
            for key in paid {
                self.acted.borrow_mut().entry(key).or_default().insert((
                    Point::Concurrency,
                    definition.id.clone(),
                    None,
                ));
            }
            return Ok(value);
        }
        Ok(None)
    }
}
