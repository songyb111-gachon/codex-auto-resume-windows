//! [`AdvancedState`] as the state `Arming` asks questions of (`crate::seam::StatePort`, S7.1b's seam; Integration 5).
//!
//! Every method makes the call `arming.py` makes of `AdvancedState` - the same method, the same keywords, the arguments
//! `arming.py` passes (a word is the word of the closed enum, a time the float of the clock) - and reads the answer the way
//! `arming.py` reads it: a row's `state`, `since`, `keep_on` ..., a dict's keys in the state's order.
//!
//! The faults: the reference's `StateError` is [`StateFault::State`], `StaleGeneration` is `Stale` and `Refused(word)` is
//! `Refused`; a class the state does not wrap (a `TypeError` from an unhashable wire value, SQLite's own error outside a
//! transaction) is none of them, and in the reference it leaves `arming.py` untouched. A seam result cannot carry it, so it
//! is raised as a panic carrying [`Raised`] (D15: caught at the boundary that turns an exception into an answer).

use std::collections::BTreeMap;

use car_machine::json::Value;

use super::arming::Move as MoveOptions;
use super::choices::{self, DAY};
use super::errors::Error;
use super::py;
use super::session::AdvancedState;
use super::sql::{self, Row};
use crate::seam::{
    ArmRow, ContinuationRow, Meta, Move, OverrideRow, ResetRule, StateFault, StatePort, StateResult,
};
use crate::vocabulary::{
    Actor, ArmingState, ArmingWarning, ContinuationReason, OffReason, OptionKey, OverrideKind,
    PromptReason, Refusal, RuleReason, RuleState, SteerReason, WordingKey, parse,
};

/// What the state raised that is not a `StateError`: the exception's class and its text, carried by a panic.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Raised {
    pub class: &'static str,
    pub message: String,
}

/// An error of the state as `arming.py` meets it.
fn fault(error: Error) -> StateFault {
    match error {
        Error::State { class, word, .. } => match (class, word) {
            ("StaleGeneration", _) => StateFault::Stale,
            ("Refused", Some(word)) => {
                parse::<Refusal>(&word).map_or(StateFault::State, StateFault::Refused)
            }
            _ => StateFault::State,
        },
        other => std::panic::panic_any(Raised {
            class: other.class(),
            message: other.message(),
        }),
    }
}

fn run<T>(result: super::errors::Result<T>) -> StateResult<T> {
    result.map_err(fault)
}

fn word(each: &'static str) -> Value {
    py::word(each)
}

fn time(at: f64) -> Value {
    Value::from(at)
}

fn words(items: &[ArmingWarning]) -> Value {
    Value::Array(items.iter().map(|each| word(each.as_str())).collect())
}

fn text_of(row: &Row, name: &str) -> Option<String> {
    py::text(sql::get(row, name)).map(str::to_owned)
}

fn number(value: &Value) -> Option<f64> {
    match value {
        Value::Null => None,
        other => py::as_f64(other),
    }
}

fn generation(value: &Value) -> i64 {
    py::small(value).unwrap_or(0)
}

/// `{key: (times...)}` as the pairs `arming.py` iterates, in the order the state gave them.
fn times(row: Row) -> Vec<(String, Vec<f64>)> {
    row.into_iter()
        .map(|(key, value)| {
            let found = match value {
                Value::Array(items) => items.iter().filter_map(py::as_f64).collect(),
                _ => Vec::new(),
            };
            (key.as_str().unwrap_or_default().to_owned(), found)
        })
        .collect()
}

fn object(value: &Value) -> Row {
    match value {
        Value::Object(map) => map.clone(),
        _ => Row::new(),
    }
}

impl StatePort for AdvancedState {
    fn arming(&self) -> StateResult<Vec<(String, ArmRow)>> {
        let rows = run(AdvancedState::arming(self))?;
        Ok(rows
            .into_iter()
            .map(|(capability, row)| {
                let row = object(&row);
                let found = ArmRow {
                    state: py::text(sql::get(&row, "state"))
                        .and_then(ArmingState::parse)
                        .unwrap_or(ArmingState::Off),
                    since: number(sql::get(&row, "since")),
                    actor: py::text(sql::get(&row, "actor")).and_then(Actor::parse),
                    reason: py::text(sql::get(&row, "reason")).and_then(OffReason::parse),
                    statement_revision: py::small(sql::get(&row, "statement_revision")),
                    engine_version: text_of(&row, "engine_version"),
                    warnings: match sql::get(&row, "warnings") {
                        Value::Array(items) => items
                            .iter()
                            .filter_map(|each| py::text(each).and_then(ArmingWarning::parse))
                            .collect(),
                        _ => Vec::new(),
                    },
                    keep_on: matches!(sql::get(&row, "keep_on"), Value::Bool(true)),
                    send_again: matches!(sql::get(&row, "send_again"), Value::Bool(true)),
                };
                (capability.as_str().unwrap_or_default().to_owned(), found)
            })
            .collect())
    }

    fn meta(&self) -> StateResult<Meta> {
        let row = run(AdvancedState::meta(self))?;
        Ok(Meta {
            generation: generation(sql::get(&row, "generation")),
            global_hourly: generation(sql::get(&row, "global_hourly")),
        })
    }

    fn ever_moved(&self, capability: &str) -> StateResult<bool> {
        run(AdvancedState::ever_moved(self, &py::word(capability)))
    }

    #[allow(clippy::too_many_arguments)]
    fn move_to(
        &self,
        capability: &str,
        state: ArmingState,
        actor: Actor,
        reason: Option<OffReason>,
        revision: Option<&Value>,
        engine_version: Option<&str>,
        warnings: Option<&[ArmingWarning]>,
        generation_seen: Option<i64>,
        at: f64,
    ) -> StateResult<(bool, i64)> {
        let options = MoveOptions {
            actor: word(actor.as_str()),
            reason: reason.map_or(Value::Null, |each| word(each.as_str())),
            revision: revision.cloned().unwrap_or(Value::Null),
            engine_version: engine_version.map_or(Value::Null, py::word),
            warnings: warnings.map_or(Value::Null, words),
            generation: generation_seen.map_or(Value::Null, py::int),
            at: time(at),
        };
        let (moved, after) =
            run(self.move_capability(&py::word(capability), &word(state.as_str()), &options))?;
        Ok((moved, generation(&after)))
    }

    fn move_set(
        &self,
        moves: &[Move],
        actor: Actor,
        generation_seen: i64,
        at: f64,
        keep: &[String],
    ) -> StateResult<(i64, i64)> {
        let moves = Value::Array(
            moves
                .iter()
                .map(|each| {
                    Value::Array(vec![
                        py::word(&each.capability),
                        word(each.state.as_str()),
                        each.revision.clone(),
                        each.engine_version.as_deref().map_or(Value::Null, py::word),
                        words(&each.warnings),
                    ])
                })
                .collect(),
        );
        let keep = Value::Array(keep.iter().map(|each| py::word(each)).collect());
        let (written, after) = run(AdvancedState::move_set(
            self,
            &moves,
            &word(actor.as_str()),
            &py::int(generation_seen),
            &time(at),
            &keep,
        ))?;
        Ok((written, generation(&after)))
    }

    fn all_off(&self, actor: Actor, reason: OffReason, at: f64) -> StateResult<(i64, i64)> {
        let (count, after) = run(AdvancedState::all_off(
            self,
            &word(actor.as_str()),
            &word(reason.as_str()),
            &time(at),
        ))?;
        Ok((count, generation(&after)))
    }

    fn set_keep_on(
        &self,
        capability: &str,
        keep_on: bool,
        send_again: bool,
        actor: Actor,
        generation_seen: Option<i64>,
        at: f64,
    ) -> StateResult<i64> {
        let after = run(AdvancedState::set_keep_on(
            self,
            &py::word(capability),
            &Value::Bool(keep_on),
            &Value::Bool(send_again),
            &word(actor.as_str()),
            &generation_seen.map_or(Value::Null, py::int),
            &time(at),
        ))?;
        Ok(generation(&after))
    }

    fn send_again_off(&self, capability: &str, reason: OffReason, at: f64) -> StateResult<bool> {
        run(AdvancedState::send_again_off(
            self,
            &py::word(capability),
            &word(reason.as_str()),
            &time(at),
        ))
    }

    fn note_kept(&self, capability: &str, reason: OffReason, at: f64) -> StateResult<bool> {
        run(AdvancedState::note_kept(
            self,
            &py::word(capability),
            &word(reason.as_str()),
            &time(at),
        ))
    }

    fn set_global_hourly(
        &self,
        value: i64,
        generation_seen: i64,
        actor: Actor,
        at: f64,
    ) -> StateResult<i64> {
        let after = run(AdvancedState::set_global_hourly(
            self,
            &py::int(value),
            &py::int(generation_seen),
            &word(actor.as_str()),
            &time(at),
        ))?;
        Ok(generation(&after))
    }

    fn spends_since(&self, capability: &str, since: f64) -> StateResult<Vec<(String, Vec<f64>)>> {
        Ok(times(run(AdvancedState::spends_since(
            self,
            &py::word(capability),
            &time(since),
        ))?))
    }

    fn open_overrides(&self, kind: OverrideKind) -> StateResult<Vec<OverrideRow>> {
        let rows = run(AdvancedState::open_overrides(
            self,
            &word(kind.as_str()),
            &Value::Null,
        ))?;
        Ok(rows
            .iter()
            .map(|row| OverrideRow {
                interruption_id: text_of(row, "interruption_id").unwrap_or_default(),
                capability: text_of(row, "capability").unwrap_or_default(),
                created_at: number(sql::get(row, "created_at")).unwrap_or(0.0),
            })
            .collect())
    }

    fn use_override(&self, key: &str, capability: &str, at: f64) -> StateResult<()> {
        run(AdvancedState::use_override(
            self,
            &py::word(key),
            &py::word(capability),
            &time(at),
        ))
        .map(|_| ())
    }

    fn resent(&self, key: &str) -> StateResult<bool> {
        run(AdvancedState::resent(self, &py::word(key)))
    }

    fn payers(&self, key: &str, claimed_at: Option<f64>) -> StateResult<Vec<(String, Vec<f64>)>> {
        Ok(times(run(AdvancedState::payers(
            self,
            &py::word(key),
            &claimed_at.map_or(Value::Null, time),
        ))?))
    }

    fn reset_rules(&self) -> StateResult<Vec<ResetRule>> {
        let rows = run(AdvancedState::reset_rules(
            self,
            &Value::Null,
            &Value::Bool(true),
        ))?;
        Ok(rows
            .iter()
            .map(|row| ResetRule {
                rule_id: sql::get(row, "rule_id").clone(),
                capability: text_of(row, "capability").unwrap_or_default(),
                launching_at: number(sql::get(row, "launching_at")),
                record_state: text_of(row, "record_state"),
            })
            .collect())
    }

    fn end_rule(
        &self,
        rule_id: &Value,
        state: RuleState,
        reason: RuleReason,
        at: f64,
    ) -> StateResult<()> {
        run(AdvancedState::end_rule(
            self,
            rule_id,
            &word(state.as_str()),
            &word(reason.as_str()),
            &time(at),
        ))
        .map(|_| ())
    }

    fn reading_has_credits(&self) -> StateResult<bool> {
        let reading = run(self.reading())?;
        Ok(!matches!(sql::get(&reading, "credits"), Value::Null))
    }

    fn clear_reading(&self) -> StateResult<()> {
        run(self.set_reading(&[
            ("credits".to_owned(), Value::Null),
            ("expiry_known".to_owned(), Value::Null),
            ("nearest_expiry".to_owned(), Value::Null),
        ]))
    }

    fn end_prompts(&self, reason: PromptReason, at: f64) -> StateResult<()> {
        run(AdvancedState::end_prompts(
            self,
            &word(reason.as_str()),
            &Value::Null,
            &time(at),
        ))
        .map(|_| ())
    }

    fn end_requested_steers(&self, reason: SteerReason, at: f64) -> StateResult<()> {
        run(AdvancedState::end_requested_steers(
            self,
            &word(reason.as_str()),
            &time(at),
        ))
        .map(|_| ())
    }

    fn continuations_pending(&self) -> StateResult<Vec<ContinuationRow>> {
        let rows = run(self.continuations(&Value::Null, &Value::Null, &Value::Bool(true)))?;
        Ok(rows
            .iter()
            .map(|row| ContinuationRow {
                capability: text_of(row, "capability").unwrap_or_default(),
                record_state: text_of(row, "record_state"),
            })
            .collect())
    }

    fn end_continuations(
        &self,
        reason: ContinuationReason,
        capability: &str,
        at: f64,
    ) -> StateResult<()> {
        run(AdvancedState::end_continuations(
            self,
            &word(reason.as_str()),
            &py::word(capability),
            &Value::Null,
            &time(at),
        ))
        .map(|_| ())
    }

    fn options(&self, capability: &str) -> StateResult<BTreeMap<OptionKey, i64>> {
        let row = run(AdvancedState::options(self, &py::word(capability)))?;
        Ok(row
            .iter()
            .filter_map(|(key, value)| {
                Some((parse::<OptionKey>(key.as_str()?)?, py::small(value)?))
            })
            .collect())
    }

    fn wordings(&self, capability: &str) -> StateResult<BTreeMap<WordingKey, Option<String>>> {
        let row = run(AdvancedState::wordings(self, &py::word(capability)))?;
        Ok(row
            .iter()
            .filter_map(|(key, value)| {
                Some((
                    parse::<WordingKey>(key.as_str()?)?,
                    py::text(value).map(str::to_owned),
                ))
            })
            .collect())
    }

    fn set_option(
        &self,
        capability: &str,
        key: &Value,
        value: &Value,
        generation_seen: &Value,
        actor: Actor,
        at: f64,
    ) -> StateResult<i64> {
        let after = run(AdvancedState::set_option(
            self,
            &py::word(capability),
            key,
            value,
            generation_seen,
            &word(actor.as_str()),
            &time(at),
        ))?;
        Ok(generation(&after))
    }

    fn set_wording(
        &self,
        capability: &str,
        key: &Value,
        words: &Value,
        generation_seen: &Value,
        actor: Actor,
        at: f64,
    ) -> StateResult<i64> {
        let after = run(AdvancedState::set_wording(
            self,
            &py::word(capability),
            key,
            words,
            generation_seen,
            &word(actor.as_str()),
            &time(at),
        ))?;
        Ok(generation(&after))
    }

    #[allow(clippy::too_many_arguments)]
    fn add_rule(
        &self,
        tag: &Value,
        status_from: &Value,
        status_to: &Value,
        category: &Value,
        generation_seen: &Value,
        actor: Actor,
        at: f64,
    ) -> StateResult<(Value, i64)> {
        let (rule, after) = run(AdvancedState::add_rule(
            self,
            tag,
            status_from,
            status_to,
            category,
            generation_seen,
            &word(actor.as_str()),
            &time(at),
        ))?;
        Ok((py::int(rule), generation(&after)))
    }

    fn remove_rule(
        &self,
        rule: &Value,
        generation_seen: &Value,
        actor: Actor,
        at: f64,
    ) -> StateResult<i64> {
        let after = run(AdvancedState::remove_rule(
            self,
            rule,
            generation_seen,
            &word(actor.as_str()),
            &time(at),
        ))?;
        Ok(generation(&after))
    }

    fn rules(&self) -> StateResult<Vec<Value>> {
        Ok(run(AdvancedState::rules(self))?
            .into_iter()
            .map(Value::Object)
            .collect())
    }

    fn rule_hits(&self, since: f64) -> StateResult<Vec<(Value, i64)>> {
        Ok(run(AdvancedState::rule_hits(self, &time(since)))?
            .into_iter()
            .map(|(rule, count)| (rule, generation(&count)))
            .collect())
    }

    fn failure_samples(&self, since: f64) -> StateResult<Vec<Value>> {
        Ok(run(AdvancedState::failure_samples(self, &time(since)))?
            .into_iter()
            .map(Value::Object)
            .collect())
    }

    fn aggregated(&self, samples: &[Value]) -> Value {
        let rows: Vec<Row> = samples.iter().map(object).collect();
        match choices::aggregated(&rows, DAY) {
            Ok(shown) => Value::Array(shown.into_iter().map(Value::Object).collect()),
            Err(error) => std::panic::panic_any(Raised {
                class: error.class(),
                message: error.message(),
            }),
        }
    }

    fn tag_is_valid(&self, tag: &str) -> bool {
        choices::tag_problem(&py::word(tag)).is_none()
    }
}
