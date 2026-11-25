//! The reference's call surface by method name: `AdvancedState`'s methods and its capabilities' views (`Scoped`,
//! the handles), each called with positional and keyword arguments as Python binds them, and its answer as the
//! differential harness writes the reference's (`tests/rustdiff/advstore.py`'s runner): tuples and sets as lists, a
//! dict whose keys are not all words as `{"__pairs__": [[key, value], ...]}`.
//!
//! A method a test or a later seat's shim names is answered by [`call`]; a capability's view by [`scoped_call`].

use car_machine::json::{Map, Str, Value};

use super::errors::{Error, Result};
use super::py;
use super::scoped::{Handle, Scoped};
use super::session::AdvancedState;
use super::sql::Row;

/// One call's arguments: positional, then by keyword.
#[derive(Clone, Copy)]
pub struct Call<'a> {
    pub args: &'a [Value],
    pub kwargs: &'a Map,
}

impl<'a> Call<'a> {
    /// The argument at `index` or named `name`, if given.
    pub fn get(&self, index: Option<usize>, name: &str) -> Option<&'a Value> {
        index
            .and_then(|index| self.args.get(index))
            .or_else(|| self.kwargs.get(name))
    }

    /// A required argument: Python's TypeError where it is missing.
    pub fn need(&self, index: Option<usize>, name: &str) -> Result<Value> {
        self.get(index, name)
            .cloned()
            .ok_or_else(|| Error::type_error(format!("missing required argument: '{name}'")))
    }

    /// An argument with its default.
    pub fn or(&self, index: Option<usize>, name: &str, default: Value) -> Value {
        self.get(index, name).cloned().unwrap_or(default)
    }

    /// An argument whose default is None.
    pub fn opt(&self, index: Option<usize>, name: &str) -> Value {
        self.or(index, name, Value::Null)
    }

    /// The keywords not named in `known` (`**changes`), in the order given.
    pub fn rest(&self, known: &[&str]) -> Vec<(String, Value)> {
        self.kwargs
            .iter()
            .filter(|(name, _)| !known.contains(&name.as_str().unwrap_or_default()))
            .map(|(name, value)| (name.as_str().unwrap_or_default().to_string(), value.clone()))
            .collect()
    }
}

/// A list of rows.
pub fn rows(found: Vec<Row>) -> Value {
    Value::Array(found.into_iter().map(Value::Object).collect())
}

/// None or a row.
pub fn maybe(found: Option<Row>) -> Value {
    found.map_or(Value::Null, Value::Object)
}

/// `{"__pairs__": [[key, value], ...]}`.
pub fn pairs(found: Vec<(Value, Value)>) -> Value {
    let mut map = Map::new();
    map.insert(
        Str::new("__pairs__"),
        Value::Array(
            found
                .into_iter()
                .map(|(key, value)| Value::Array(vec![key, value]))
                .collect(),
        ),
    );
    Value::Object(map)
}

/// Rows keyed by (bucket, minutes) as pairs.
fn keyed(found: Vec<((Value, Value), Row)>) -> Value {
    pairs(
        found
            .into_iter()
            .map(|((bucket, minutes), row)| {
                (Value::Array(vec![bucket, minutes]), Value::Object(row))
            })
            .collect(),
    )
}

fn int(number: i64) -> Value {
    py::int(number)
}

fn boolean(on: bool) -> Value {
    Value::Bool(on)
}

fn pair_of(first: Value, second: Value) -> Value {
    Value::Array(vec![first, second])
}

/// `getattr(state, method)(*args, **kwargs)`.
pub fn call(state: &AdvancedState, method: &str, c: Call<'_>) -> Result<Value> {
    let n = Value::Null;
    let t = Value::Bool(true);
    let f = Value::Bool(false);
    Ok(match method {
        "exists" => boolean(state.exists()),
        "close" => {
            state.close();
            n
        }
        // arming
        "meta" => Value::Object(state.meta()?),
        "arming" => Value::Object(state.arming()?),
        "ever_moved" => boolean(state.ever_moved(&c.need(Some(0), "capability")?)?),
        "move" => {
            let options = super::arming::Move {
                actor: c.need(None, "actor")?,
                reason: c.opt(None, "reason"),
                revision: c.opt(None, "revision"),
                engine_version: c.opt(None, "engine_version"),
                warnings: c.opt(None, "warnings"),
                generation: c.opt(None, "generation"),
                at: c.opt(None, "at"),
            };
            let (moved, generation) = state.move_capability(
                &c.need(Some(0), "capability")?,
                &c.need(Some(1), "state")?,
                &options,
            )?;
            pair_of(boolean(moved), generation)
        }
        "move_set" => {
            let (written, generation) = state.move_set(
                &c.need(Some(0), "moves")?,
                &c.need(None, "actor")?,
                &c.need(None, "generation")?,
                &c.opt(None, "at"),
                &c.or(None, "keep", Value::Array(Vec::new())),
            )?;
            pair_of(int(written), generation)
        }
        "all_off" => {
            let (on, generation) = state.all_off(
                &c.need(None, "actor")?,
                &c.need(None, "reason")?,
                &c.opt(None, "at"),
            )?;
            pair_of(int(on), generation)
        }
        "set_keep_on" => state.set_keep_on(
            &c.need(Some(0), "capability")?,
            &c.need(Some(1), "on")?,
            &c.or(None, "send_again", f),
            &c.need(None, "actor")?,
            &c.opt(None, "generation"),
            &c.opt(None, "at"),
        )?,
        "send_again_off" => boolean(state.send_again_off(
            &c.need(Some(0), "capability")?,
            &c.need(None, "reason")?,
            &c.opt(None, "at"),
        )?),
        "note_kept" => boolean(state.note_kept(
            &c.need(Some(0), "capability")?,
            &c.need(Some(1), "reason")?,
            &c.opt(None, "at"),
        )?),
        "set_global_hourly" => state.set_global_hourly(
            &c.need(Some(0), "value")?,
            &c.need(None, "generation")?,
            &c.need(None, "actor")?,
            &c.opt(None, "at"),
        )?,
        // spend
        "spent" => Value::Object(state.spent(
            &c.need(Some(0), "capability")?,
            &c.need(Some(1), "thread_id")?,
            &c.opt(Some(2), "now"),
        )?),
        "spends_since" => Value::Object(
            state.spends_since(&c.need(Some(0), "capability")?, &c.need(Some(1), "since")?)?,
        ),
        "payers" => Value::Object(state.payers(
            &c.need(Some(0), "interruption_id")?,
            &c.need(Some(1), "claimed_at")?,
        )?),
        "channel_paid" => boolean(state.channel_paid(
            &c.need(Some(0), "interruption_id")?,
            &c.need(Some(1), "claimed_at")?,
        )?),
        // records
        "add_record" => boolean(state.add_record(
            &c.need(Some(0), "record_id")?,
            &c.need(Some(1), "capability")?,
            &c.need(Some(2), "thread_id")?,
            &c.opt(Some(3), "at"),
        )?),
        "move_record" => boolean(state.move_record(
            &c.need(Some(0), "record_id")?,
            &c.need(Some(1), "state")?,
            &c.opt(Some(2), "at"),
        )?),
        "records_on" => rows(state.records_on(&c.need(Some(0), "thread_id")?)?),
        "add_override" => boolean(state.add_override(
            &c.need(Some(0), "interruption_id")?,
            &c.need(Some(1), "capability")?,
            &c.need(Some(2), "kind")?,
            &c.opt(Some(3), "at"),
        )?),
        "overrides_for" => rows(state.overrides_for(&c.need(Some(0), "interruption_id")?)?),
        "use_override" => boolean(state.use_override(
            &c.need(Some(0), "interruption_id")?,
            &c.need(Some(1), "capability")?,
            &c.opt(Some(2), "at"),
        )?),
        "renew_override" => {
            state.renew_override(
                &c.need(Some(0), "interruption_id")?,
                &c.need(Some(1), "capability")?,
                &c.need(Some(2), "kind")?,
                &c.opt(Some(3), "at"),
            )?;
            n
        }
        "override" => maybe(state.override_of(
            &c.need(Some(0), "interruption_id")?,
            &c.need(Some(1), "capability")?,
        )?),
        "resent" => boolean(state.resent(&c.need(Some(0), "interruption_id")?)?),
        "open_overrides" => {
            rows(state.open_overrides(&c.need(Some(0), "kind")?, &c.opt(Some(1), "capability"))?)
        }
        // journal
        "note" => {
            state.note(
                &c.need(Some(0), "code")?,
                &c.opt(None, "capability"),
                &c.opt(None, "reason"),
                &c.opt(None, "actor"),
                &c.opt(None, "point"),
                &c.opt(None, "answer"),
                &c.opt(None, "at"),
            )?;
            n
        }
        "journal" => {
            rows(state.journal(&c.opt(None, "capability"), &c.or(None, "limit", int(500)))?)
        }
        "journal_times" => Value::Array(state.journal_times(
            &c.need(Some(0), "capability")?,
            &c.need(Some(1), "word")?,
            &c.need(Some(2), "since")?,
        )?),
        "sample" => boolean(state.sample(
            &c.need(Some(0), "capability")?,
            &c.need(Some(1), "code")?,
            &c.opt(Some(2), "at"),
        )?),
        "counted" => boolean(state.counted(
            &c.need(Some(0), "capability")?,
            &c.need(Some(1), "code")?,
            &c.opt(Some(2), "at"),
        )?),
        "counted_since" => int(state.counted_since(
            &c.need(Some(0), "capability")?,
            &c.need(Some(1), "code")?,
            &c.need(Some(2), "since")?,
        )?),
        "samples" => Value::Object(state.samples(&c.need(Some(0), "capability")?)?),
        // choices
        "options" => Value::Object(state.options(&c.need(Some(0), "capability")?)?),
        "stamped" => state.stamped(&c.need(Some(0), "capability")?, &c.need(Some(1), "key")?)?,
        "stamp" => boolean(state.stamp(
            &c.need(Some(0), "capability")?,
            &c.need(Some(1), "key")?,
            &c.need(Some(2), "value")?,
        )?),
        "unstamp" => {
            boolean(state.unstamp(&c.need(Some(0), "capability")?, &c.need(Some(1), "key")?)?)
        }
        "set_option" => state.set_option(
            &c.need(Some(0), "capability")?,
            &c.need(Some(1), "key")?,
            &c.need(Some(2), "value")?,
            &c.need(None, "generation")?,
            &c.need(None, "actor")?,
            &c.opt(None, "at"),
        )?,
        "wordings" => Value::Object(state.wordings(&c.need(Some(0), "capability")?)?),
        "set_wording" => state.set_wording(
            &c.need(Some(0), "capability")?,
            &c.need(Some(1), "key")?,
            &c.need(Some(2), "words")?,
            &c.need(None, "generation")?,
            &c.need(None, "actor")?,
            &c.opt(None, "at"),
        )?,
        "rules" => rows(state.rules()?),
        "add_rule" => {
            let (rule_id, generation) = state.add_rule(
                &c.need(Some(0), "tag")?,
                &c.need(Some(1), "status_from")?,
                &c.need(Some(2), "status_to")?,
                &c.need(Some(3), "category")?,
                &c.need(None, "generation")?,
                &c.need(None, "actor")?,
                &c.opt(None, "at"),
            )?;
            pair_of(int(rule_id), generation)
        }
        "remove_rule" => state.remove_rule(
            &c.need(Some(0), "rule_id")?,
            &c.need(None, "generation")?,
            &c.need(None, "actor")?,
            &c.opt(None, "at"),
        )?,
        "rule_hits" => pairs(state.rule_hits(&c.need(Some(0), "since")?)?),
        "admission" => maybe(state.admission(&c.need(Some(0), "interruption_id")?)?),
        "admit" => boolean(state.admit(
            &c.need(Some(0), "interruption_id")?,
            &c.need(Some(1), "capability")?,
            &c.need(Some(2), "answer")?,
            &c.opt(None, "rule_id"),
            &c.opt(None, "shape"),
            &c.opt(None, "at"),
        )?),
        "taken" => boolean(state.taken(
            &c.need(Some(0), "interruption_id")?,
            &c.need(Some(1), "capability")?,
            &c.opt(Some(2), "code"),
            &c.opt(None, "sample"),
            &c.opt(None, "at"),
        )?),
        "failure_samples" => rows(state.failure_samples(&c.need(Some(0), "since")?)?),
        // resets
        "windows" => keyed(state.windows()?),
        "save_windows" => {
            state.save_windows(&c.need(Some(0), "rows")?)?;
            n
        }
        "reading" => Value::Object(state.reading()?),
        "set_reading" => {
            state.set_reading(&c.rest(&[]))?;
            n
        }
        "reset_rules" => {
            rows(state.reset_rules(&c.opt(None, "capability"), &c.or(None, "pending", t))?)
        }
        "reset_rule" => maybe(state.reset_rule(&c.need(Some(0), "rule_id")?)?),
        "add_reset_rule" => int(state.add_reset_rule(
            &c.need(Some(0), "capability")?,
            &c.need(Some(1), "bucket")?,
            &c.need(Some(2), "minutes")?,
            &c.need(Some(3), "ordinal")?,
            &c.or(None, "repeat", f.clone()),
            &c.or(None, "ask_first", f),
            &c.opt(None, "thread_id"),
            &c.opt(None, "words"),
            &c.opt(None, "record_id"),
            &c.opt(None, "at"),
        )?),
        "change_rule" => boolean(state.change_rule(
            &c.need(Some(0), "rule_id")?,
            &c.opt(None, "expect"),
            &c.rest(&["expect"]),
        )?),
        "end_rule" => boolean(state.end_rule(
            &c.need(Some(0), "rule_id")?,
            &c.need(Some(1), "state")?,
            &c.need(Some(2), "reason")?,
            &c.opt(Some(3), "at"),
        )?),
        "cancel_reset_rule" => {
            py::word(state.cancel_reset_rule(&c.need(Some(0), "rule_id")?, &c.opt(Some(1), "at"))?)
        }
        "end_messages_in" => {
            int(state.end_messages_in(&c.need(Some(0), "thread_id")?, &c.opt(Some(1), "at"))?)
        }
        "record_moved" => maybe(state.record_moved(
            &c.need(Some(0), "record_id")?,
            &c.need(Some(1), "move")?,
            &c.opt(None, "gate"),
            &c.opt(None, "reason"),
            &c.opt(None, "at"),
            &c.opt(None, "queue_id"),
        )?),
        "release_unlaunched" => int(state.release_unlaunched(&c.opt(Some(0), "at"))?),
        "carry_message" => {
            boolean(state.carry_message(&c.need(Some(0), "rule_id")?, &c.opt(Some(1), "at"))?)
        }
        "carried_message" => boolean(state.carried_message(
            &c.need(Some(0), "rule_id")?,
            &c.need(Some(1), "started")?,
            &c.opt(Some(2), "at"),
        )?),
        "messages_in_flight" => rows(state.messages_in_flight()?),
        "add_credit_spend" => state
            .add_credit_spend(
                &c.need(Some(0), "rule_id")?,
                &c.need(Some(1), "bucket")?,
                &c.need(Some(2), "minutes")?,
                &c.need(Some(3), "occasion")?,
                &c.need(Some(4), "key")?,
                &c.opt(Some(5), "at"),
            )?
            .map_or(Value::Null, int),
        "finish_credit_spend" => boolean(state.finish_credit_spend(
            &c.need(Some(0), "spend_id")?,
            &c.need(Some(1), "outcome")?,
            &c.opt(Some(2), "at"),
        )?),
        "retry_credit_spend" => boolean(state.retry_credit_spend(&c.need(Some(0), "spend_id")?)?),
        "drop_credit_spend" => boolean(state.drop_credit_spend(&c.need(Some(0), "spend_id")?)?),
        "credit_spends" => rows(state.credit_spends(&c.opt(Some(0), "since"))?),
        // continuations
        "add_continuation" => boolean(state.add_continuation(
            &c.need(Some(0), "key")?,
            &c.need(Some(1), "capability")?,
            &c.need(Some(2), "kind")?,
            &c.need(Some(3), "thread_id")?,
            &c.need(Some(4), "words")?,
            &c.need(None, "ordinal")?,
            &c.or(None, "chain", int(1)),
            &c.opt(None, "at"),
        )?),
        "add_held_continuation" => boolean(state.add_held_continuation(
            &c.need(Some(0), "key")?,
            &c.need(Some(1), "capability")?,
            &c.need(Some(2), "kind")?,
            &c.need(Some(3), "thread_id")?,
            &c.need(None, "ordinal")?,
            &c.or(None, "chain", int(1)),
            &c.opt(None, "at"),
        )?),
        "note_continuation" => boolean(state.note_continuation(
            &c.need(Some(0), "key")?,
            &c.need(Some(1), "capability")?,
            &c.need(Some(2), "kind")?,
            &c.need(Some(3), "thread_id")?,
            &c.need(Some(4), "reason")?,
            &c.opt(None, "ordinal"),
            &c.or(None, "chain", int(0)),
            &c.opt(None, "at"),
        )?),
        "continuation" => maybe(state.continuation(&c.need(Some(0), "key")?)?),
        "continuations" => rows(state.continuations(
            &c.opt(None, "capability"),
            &c.opt(None, "thread_id"),
            &c.or(None, "pending", t),
        )?),
        "last_continuation" => maybe(state.last_continuation(
            &c.need(Some(0), "thread_id")?,
            &c.need(Some(1), "capability")?,
        )?),
        "continuation_moved" => maybe(state.continuation_moved(
            &c.need(Some(0), "record_id")?,
            &c.need(Some(1), "move")?,
            &c.opt(None, "at"),
            &c.opt(None, "queue_id"),
        )?),
        "hold_continuation" => boolean(state.hold_continuation(
            &c.need(Some(0), "answer_id")?,
            &c.need(Some(1), "capability")?,
        )?),
        "doubt_continuation" => boolean(state.doubt_continuation(
            &c.need(Some(0), "answer_id")?,
            &c.need(Some(1), "capability")?,
            &c.opt(Some(2), "at"),
        )?),
        "end_continuations" => int(state.end_continuations(
            &c.need(Some(0), "reason")?,
            &c.opt(None, "capability"),
            &c.opt(None, "thread_id"),
            &c.opt(None, "at"),
        )?),
        "continuations_in_flight" => rows(state.continuations_in_flight()?),
        "release_unlaunched_continuations" => int(state
            .release_unlaunched_continuations(&c.need(Some(0), "after")?, &c.opt(Some(1), "at"))?),
        "keep_going" => state.keep_going(&c.opt(Some(0), "thread_id"))?,
        "set_keep_going" => {
            state.set_keep_going(
                &c.need(Some(0), "thread_id")?,
                &c.need(Some(1), "count")?,
                &c.opt(Some(2), "at"),
            )?;
            n
        }
        "keep_going_used" => {
            boolean(state.keep_going_used(&c.need(Some(0), "thread_id")?, &c.opt(Some(1), "at"))?)
        }
        "stop_keep_going" => int(state.stop_keep_going(
            &c.need(Some(0), "reason")?,
            &c.opt(None, "thread_id"),
            &c.opt(None, "at"),
        )?),
        // prompts
        "add_prompt" => int(state.add_prompt(
            &c.need(Some(0), "thread_id")?,
            &c.need(Some(1), "words")?,
            &c.need(Some(2), "trigger")?,
            &when(c),
        )?),
        "edit_prompt" => {
            state.edit_prompt(
                &c.need(Some(0), "prompt_id")?,
                &c.need(Some(1), "generation")?,
                &c.need(Some(2), "words")?,
                &c.need(Some(3), "trigger")?,
                &when(c),
            )?;
            n
        }
        "placed_prompt" => boolean(state.placed_prompt(&c.need(Some(0), "prompt_id")?)?),
        "prompts" => rows(state.prompts(&c.opt(None, "thread_id"), &c.or(None, "pending", t))?),
        "prompt" => maybe(state.prompt(&c.need(Some(0), "prompt_id")?)?),
        "change_prompt" => {
            state.change_prompt(&c.need(Some(0), "prompt_id")?, &c.rest(&[]))?;
            n
        }
        "cancel_prompt" => {
            py::word(state.cancel_prompt(&c.need(Some(0), "prompt_id")?, &c.opt(Some(1), "at"))?)
        }
        "go_on_prompt" => {
            boolean(state.go_on_prompt(&c.need(Some(0), "prompt_id")?, &c.opt(Some(1), "at"))?)
        }
        "clear_done" => Value::Object(state.clear_done(
            &c.need(Some(0), "prompt_ids")?,
            &c.need(Some(1), "generation")?,
        )?),
        "end_prompts" => int(state.end_prompts(
            &c.need(Some(0), "reason")?,
            &c.opt(None, "thread_id"),
            &c.opt(None, "at"),
        )?),
        "prompt_moved" => maybe(state.prompt_moved(
            &c.need(Some(0), "record_id")?,
            &c.need(Some(1), "move")?,
            &c.opt(None, "at"),
            &c.opt(None, "queue_id"),
            &c.opt(None, "gate"),
            &c.opt(None, "reason"),
        )?),
        "prompts_in_flight" => rows(state.prompts_in_flight()?),
        "release_unlaunched_prompts" => {
            int(state
                .release_unlaunched_prompts(&c.need(Some(0), "after")?, &c.opt(Some(1), "at"))?)
        }
        // meter
        "meter" => keyed(state.meter()?),
        "save_meter" => int(state.save_meter(&c.need(Some(0), "windows")?, &c.opt(None, "at"))?),
        "mark_meter" => boolean(state.mark_meter(
            &c.need(Some(0), "bucket")?,
            &c.need(Some(1), "minutes")?,
            &c.opt(None, "warned_reset_at"),
            &c.opt(None, "paused_reset_at"),
            &c.or(None, "clear_pause", f),
            &c.opt(None, "at"),
        )?),
        // runs
        "run_started" => {
            state.run_started(
                &c.need(Some(0), "key")?,
                &c.need(Some(1), "capability")?,
                &c.need(Some(2), "thread_id")?,
                &c.need(None, "started_at")?,
                &c.need(None, "ends_by")?,
            )?;
            n
        }
        "run_owed" => {
            state.run_owed(
                &c.need(Some(0), "key")?,
                &c.need(Some(1), "capability")?,
                &c.need(Some(2), "thread_id")?,
                &c.need(Some(3), "model")?,
                &c.need(None, "started_at")?,
                &c.need(None, "ends_by")?,
            )?;
            n
        }
        "run_restored" => boolean(state.run_restored(&c.need(Some(0), "key")?)?),
        "runs_owed" => rows(state.runs_owed(&c.need(Some(0), "capability")?)?),
        "run_ended" => boolean(state.run_ended(
            &c.need(Some(0), "key")?,
            &c.need(Some(1), "end")?,
            &c.opt(None, "at"),
        )?),
        "run_stop" => boolean(state.run_stop(&c.need(Some(0), "key")?, &c.opt(None, "at"))?),
        "runs" => rows(state.runs(&c.or(None, "live", t), &c.or(None, "limit", int(20)))?),
        "prune_runs" => {
            int(state.prune_runs(&c.need(Some(0), "before")?, &c.opt(None, "capability"))?)
        }
        // chat
        "add_chat" => int(state.add_chat(
            &c.need(Some(0), "thread_id")?,
            &c.need(Some(1), "words")?,
            &c.need(Some(2), "record_id")?,
            &c.opt(None, "at"),
        )?),
        "chats" => rows(state.chats(
            &c.opt(None, "thread_id"),
            &c.or(None, "pending", f),
            &c.or(None, "limit", int(50)),
        )?),
        "chat_by_record" => maybe(state.chat_by_record(&c.need(Some(0), "record_id")?)?),
        "chat_sent" => {
            boolean(state.chat_sent(&c.need(Some(0), "record_id")?, &c.opt(None, "at"))?)
        }
        "chat_released" => boolean(state.chat_released(&c.need(Some(0), "record_id")?)?),
        "chat_ended" => boolean(state.chat_ended(
            &c.need(Some(0), "record_id")?,
            &c.need(Some(1), "move")?,
            &c.opt(None, "at"),
        )?),
        "chat_moved" => maybe(state.chat_moved(
            &c.need(Some(0), "record_id")?,
            &c.need(Some(1), "move")?,
            &c.opt(None, "reason"),
            &c.opt(None, "at"),
        )?),
        "chats_in_flight" => rows(state.chats_in_flight()?),
        "release_unlaunched_chats" => {
            int(state
                .release_unlaunched_chats(&c.need(Some(0), "after")?, &c.opt(Some(1), "at"))?)
        }
        "cancel_chat" => int(state.cancel_chat(
            &c.need(Some(0), "reason")?,
            &c.opt(None, "record_id"),
            &c.opt(None, "thread_id"),
            &c.opt(None, "at"),
        )?),
        // analytics
        "token_files" => Value::Object(state.token_files()?),
        "ingest_file" => int(state.ingest_file(
            &c.need(Some(0), "file_key")?,
            &c.need(Some(1), "thread_id")?,
            &c.need(None, "size")?,
            &c.need(None, "offset")?,
            &c.need(None, "changed_ns")?,
            &c.need(None, "days")?,
            &c.need(None, "project_key")?,
            &c.opt(None, "at"),
        )?),
        "token_days" => rows(state.token_days(&c.opt(Some(0), "since_day"))?),
        "add_samples" => int(state.add_samples(&c.need(Some(0), "windows")?, &c.opt(None, "at"))?),
        "usage_samples" => rows(state.usage_samples(&c.opt(Some(0), "since"))?),
        // restarts, opens, account, steers
        "restart_noted" => boolean(state.restart_noted(
            &c.need(Some(0), "exit_code")?,
            &c.need(Some(1), "restarted")?,
            &c.opt(None, "at"),
        )?),
        "restarts_since" => rows(state.restarts_since(&c.need(Some(0), "since")?)?),
        "opens" => rows(state.opens(&c.need(Some(0), "since")?)?),
        "add_open" => int(state.add_open(
            &c.need(Some(0), "thread_id")?,
            &c.need(Some(1), "record_id")?,
            &c.opt(Some(2), "at"),
        )?),
        "settle_open" => {
            boolean(state.settle_open(&c.need(Some(0), "open_id")?, &c.need(Some(1), "outcome")?)?)
        }
        "account_seen" => maybe(state.account_seen()?),
        "save_account_seen" => {
            state.save_account_seen(
                &c.need(Some(0), "identity_digest")?,
                &c.need(Some(1), "plan")?,
                &c.opt(None, "at"),
            )?;
            n
        }
        "end_account_seen" => boolean(state.end_account_seen()?),
        "steers" => rows(state.steers(&c.or(Some(0), "since", Value::Float(0.0)))?),
        "waiting_steers" => rows(state.waiting_steers()?),
        "add_steer" => int(state.add_steer(
            &c.need(Some(0), "thread_id")?,
            &c.need(Some(1), "words")?,
            &c.need(Some(2), "client_id")?,
            &c.opt(Some(3), "at"),
            &c.opt(None, "bounds"),
        )?),
        "claim_steer" => boolean(state.claim_steer(&c.need(Some(0), "steer_id")?)?),
        "settle_steer" => boolean(state.settle_steer(
            &c.need(Some(0), "steer_id")?,
            &c.need(Some(1), "state")?,
            &c.opt(Some(2), "reason"),
            &c.opt(Some(3), "at"),
        )?),
        "end_requested_steers" => {
            int(state.end_requested_steers(&c.need(Some(0), "reason")?, &c.opt(Some(1), "at"))?)
        }
        "settle_cut_short" => int(state.settle_cut_short(&c.opt(Some(0), "at"))?),
        // the module functions
        "fn.aggregated" => rows(super::choices::aggregated(
            &rows_of(&c.need(Some(0), "samples")?)?,
            py::as_f64(&c.or(None, "day", int(86400))).unwrap_or(86400.0),
        )?),
        "fn.rule_problem" => py::word_or_null(super::choices::rule_problem(
            &c.need(Some(0), "tag")?,
            &c.need(Some(1), "status_from")?,
            &c.need(Some(2), "status_to")?,
            &c.need(Some(3), "category")?,
            &rows_of(&c.need(Some(4), "rules")?)?,
        )?),
        "fn.tag_problem" => py::word_or_null(super::choices::tag_problem(&c.need(Some(0), "tag")?)),
        _ => {
            return Err(Error::python(
                "AttributeError",
                format!("no method {method}"),
            ));
        }
    })
}

/// A list of dicts handed in (the module functions' samples and rules).
fn rows_of(value: &Value) -> Result<Vec<Row>> {
    match value {
        Value::Array(items) => items
            .iter()
            .map(|item| match item {
                Value::Object(map) => Ok(map.clone()),
                _ => Err(Error::python(
                    "AttributeError",
                    "object has no attribute 'get'",
                )),
            })
            .collect(),
        _ => Err(Error::type_error("not a list of dicts")),
    }
}

fn when(c: Call<'_>) -> super::prompts::When {
    let base = super::prompts::When::default();
    super::prompts::When {
        at: c.or(None, "at", base.at),
        every: c.or(None, "every", base.every),
        occurrences: c.or(None, "occurrences", base.occurrences),
        until: c.or(None, "until", base.until),
        depends: c.or(None, "depends", base.depends),
        while_running: c.or(None, "while_running", base.while_running),
        now: c.or(None, "now", base.now),
        held: c.or(None, "held", base.held),
    }
}

fn scoped_capability<'a>(scoped: &'a Scoped<'_>) -> &'a Value {
    &scoped.capability
}

/// `state.scoped(capability, on, verdict, armed).<name>(...)`, or one of its handles' (`resets.save_windows`, ...).
pub fn scoped_call(scoped: &Scoped<'_>, name: &str, c: Call<'_>) -> Result<Value> {
    let state = scoped.state;
    let handle: Handle<'_> = scoped.handle();
    let mine = scoped_capability(scoped);
    let n = Value::Null;
    let t = Value::Bool(true);
    Ok(match name {
        "now" | "resets.now" | "prompts.now" | "meter.now" => Value::Float(scoped.now()),
        "options" => Value::Object(scoped.options()?),
        "wordings" => Value::Object(scoped.wordings()?),
        "options_of" => Value::Object(scoped.options_of(&c.need(Some(0), "other")?)?),
        "rules" => rows(scoped.rules()?),
        "admission" => maybe(scoped.admission(&c.need(Some(0), "interruption_id")?)?),
        "count" => boolean(scoped.count(&c.need(Some(0), "code")?)?),
        "sample" => boolean(scoped.sample(&c.need(Some(0), "code")?)?),
        "resent" => boolean(scoped.resent(&c.need(Some(0), "interruption_id")?)?),
        "channel_paid" => boolean(scoped.channel_paid(
            &c.need(Some(0), "interruption_id")?,
            &c.need(Some(1), "claimed_at")?,
        )?),
        "request" => maybe(scoped.request(&c.need(Some(0), "interruption_id")?)?),
        "since" => scoped.since()?,
        "stamped" => scoped.stamped(&c.need(Some(0), "key")?)?,
        "stamp" => boolean(scoped.stamp(&c.need(Some(0), "key")?, &c.need(Some(1), "value")?)?),
        "unstamp" => boolean(scoped.unstamp(&c.need(Some(0), "key")?)?),
        "stamped_of" => scoped.stamped_of(&c.need(Some(0), "other")?, &c.need(Some(1), "key")?)?,
        "continuations_of" => rows(scoped.continuations_of(
            &c.need(Some(0), "other")?,
            &c.need(Some(1), "thread_id")?,
            &c.or(Some(2), "pending", t.clone()),
        )?),
        "counted_since" => {
            int(scoped.counted_since(&c.need(Some(0), "code")?, &c.need(Some(1), "since")?)?)
        }
        "stored_on" => boolean(scoped.stored_on()?),
        "journal_times" => Value::Array(scoped.journal_times(
            &c.need(Some(0), "other")?,
            &c.need(Some(1), "word")?,
            &c.need(Some(2), "since")?,
        )?),
        "passed" => boolean(scoped.passed(&c.need(Some(0), "measurement")?)),
        "failed" => boolean(scoped.failed(&c.need(Some(0), "measurement")?)),
        "armed" => boolean(scoped.armed(&c.need(Some(0), "other")?)),
        "resets.on" | "continuations.on" | "prompts.on" | "meter.on" | "runs.on"
        | "analytics.on" | "opens.on" | "steers.on" => boolean(handle.is_on()),
        // resets
        "resets.windows" => keyed(state.windows()?),
        "resets.reading" => Value::Object(state.reading()?),
        "resets.reset_rules" => {
            rows(state.reset_rules(&c.opt(None, "capability"), &c.or(None, "pending", t))?)
        }
        "resets.reset_rule" => maybe(state.reset_rule(&c.need(Some(0), "rule_id")?)?),
        "resets.credit_spends" => rows(state.credit_spends(&c.opt(Some(0), "since"))?),
        "resets.end_rule" => {
            handle.resets_own(&c.need(Some(0), "rule_id")?)?;
            call(state, "end_rule", c)?
        }
        "resets.save_windows"
        | "resets.set_reading"
        | "resets.change_rule"
        | "resets.add_credit_spend"
        | "resets.finish_credit_spend"
        | "resets.retry_credit_spend"
        | "resets.drop_credit_spend"
        | "resets.carry_message" => {
            handle.resets_writing()?;
            call(state, &name["resets.".len()..], c)?
        }
        "resets.carried_message" => boolean(
            handle.resets_carried(&c.need(Some(0), "rule_id")?, &c.need(Some(1), "started")?)?,
        ),
        "resets.message_expired" => boolean(handle.resets_expired(&c.need(Some(0), "rule_id")?)?),
        // continuations
        "continuations.get" => maybe(handle.continuation(&c.need(Some(0), "key")?)?),
        "continuations.mine" => rows(state.continuations(
            mine,
            &c.opt(Some(0), "thread_id"),
            &c.or(Some(1), "pending", t),
        )?),
        "continuations.last" => {
            maybe(state.last_continuation(&c.need(Some(0), "thread_id")?, mine)?)
        }
        "continuations.add" => {
            handle.continuations_writing()?;
            boolean(state.add_continuation(
                &c.need(Some(0), "key")?,
                mine,
                &c.need(Some(1), "kind")?,
                &c.need(Some(2), "thread_id")?,
                &c.need(Some(3), "words")?,
                &c.need(None, "ordinal")?,
                &c.or(None, "chain", int(1)),
                &n,
            )?)
        }
        "continuations.hold" => {
            handle.continuations_writing()?;
            boolean(state.add_held_continuation(
                &c.need(Some(0), "key")?,
                mine,
                &c.need(Some(1), "kind")?,
                &c.need(Some(2), "thread_id")?,
                &c.need(None, "ordinal")?,
                &c.or(None, "chain", int(1)),
                &n,
            )?)
        }
        "continuations.note" => {
            handle.continuations_writing()?;
            boolean(state.note_continuation(
                &c.need(Some(0), "key")?,
                mine,
                &c.need(Some(1), "kind")?,
                &c.need(Some(2), "thread_id")?,
                &c.need(Some(3), "reason")?,
                &c.opt(None, "ordinal"),
                &c.or(None, "chain", int(0)),
                &n,
            )?)
        }
        "continuations.end" => {
            handle.continuations_writing()?;
            int(state.end_continuations(
                &c.need(Some(0), "reason")?,
                mine,
                &c.opt(None, "thread_id"),
                &n,
            )?)
        }
        "continuations.unword" => {
            handle.continuations_writing()?;
            boolean(state.hold_continuation(&c.need(Some(0), "answer_id")?, mine)?)
        }
        "continuations.doubt" => {
            handle.continuations_writing()?;
            boolean(state.doubt_continuation(&c.need(Some(0), "answer_id")?, mine, &n)?)
        }
        "continuations.kept" => state.keep_going(&c.opt(Some(0), "thread_id"))?,
        "continuations.kept_used" => {
            handle.continuations_writing()?;
            call(state, "keep_going_used", c)?
        }
        "continuations.stop_kept" => {
            handle.continuations_writing()?;
            int(state.stop_keep_going(
                &c.need(Some(0), "reason")?,
                &c.opt(None, "thread_id"),
                &n,
            )?)
        }
        // prompts
        "prompts.prompts" => call(state, "prompts", c)?,
        "prompts.prompt" => call(state, "prompt", c)?,
        "prompts.occur" => boolean(handle.prompts_occur(
            &c.need(Some(0), "prompt_id")?,
            &c.need(Some(1), "key")?,
            &c.need(Some(2), "thread_id")?,
            &c.need(Some(3), "due_at")?,
        )?),
        "prompts.change" => {
            handle.prompts_writing()?;
            call(state, "change_prompt", c)?
        }
        "prompts.drop" => boolean(handle.prompts_drop(&c.need(Some(0), "key")?)?),
        "prompts.end" => {
            handle.prompts_writing()?;
            int(state.end_prompts(&c.need(Some(0), "reason")?, &c.opt(None, "thread_id"), &n)?)
        }
        // meter
        "meter.rows" => keyed(state.meter()?),
        "meter.save" => int(handle.meter_save(&c.need(Some(0), "windows")?)?),
        "meter.mark" => {
            handle.meter_writer()?;
            call(state, "mark_meter", c)?
        }
        // runs: written whatever the capability stands at
        "runs.live" => rows(handle.runs_live()?),
        "runs.started" => {
            state.run_started(
                &c.need(Some(0), "key")?,
                mine,
                &c.need(Some(1), "thread_id")?,
                &c.need(None, "started_at")?,
                &c.need(None, "ends_by")?,
            )?;
            n
        }
        "runs.ended" => {
            boolean(state.run_ended(&c.need(Some(0), "key")?, &c.need(Some(1), "end")?, &n)?)
        }
        "runs.owe" => {
            state.run_owed(
                &c.need(Some(0), "key")?,
                mine,
                &c.need(Some(1), "thread_id")?,
                &c.need(Some(2), "model")?,
                &c.need(None, "started_at")?,
                &c.need(None, "ends_by")?,
            )?;
            n
        }
        "runs.restored" => boolean(state.run_restored(&c.need(Some(0), "key")?)?),
        "runs.owed" => rows(state.runs_owed(mine)?),
        "runs.prune" => int(state.prune_runs(&c.need(Some(0), "before")?, mine)?),
        // analytics
        "analytics.files" => Value::Object(handle.analytics_files()?),
        "analytics.ingest" => {
            handle.analytics_ingest()?;
            call(state, "ingest_file", c)?
        }
        "analytics.sample" => {
            int(handle.analytics_sample(&c.need(Some(0), "windows")?, &c.opt(None, "at"))?)
        }
        // restarts
        "restarts.since" => rows(state.restarts_since(&c.need(Some(0), "since")?)?),
        "restarts.noted" => boolean(handle.restarts_noted(
            &c.need(Some(0), "exit_code")?,
            &c.need(Some(1), "restarted")?,
        )?),
        // chat
        "chat.pending" => rows(handle.chat_pending()?),
        "chat.conversation_off" => {
            int(handle.chat_conversation_off(&c.need(Some(0), "record_id")?)?)
        }
        // opens
        "opens.opens" => call(state, "opens", c)?,
        "opens.add_open" => {
            handle.table_writing()?;
            call(state, "add_open", c)?
        }
        "opens.settle_open" => {
            handle.table_writing()?;
            call(state, "settle_open", c)?
        }
        // steers
        "steers.steers" => call(state, "steers", c)?,
        "steers.waiting" => rows(state.waiting_steers()?),
        "steers.claim" => {
            handle.table_writing()?;
            call(state, "claim_steer", c)?
        }
        "steers.settle" => boolean(handle.steers_settle(
            &c.need(Some(0), "steer_id")?,
            &c.need(Some(1), "state_word")?,
            &c.opt(Some(2), "reason"),
            &c.opt(Some(3), "at"),
        )?),
        "steers.cut_short" => int(state.settle_cut_short(&c.opt(Some(0), "at"))?),
        // account
        "account.seen" => {
            handle.account_guard(false)?;
            maybe(state.account_seen()?)
        }
        "account.save" => {
            handle.account_guard(true)?;
            call(state, "save_account_seen", c)?
        }
        _ => return Err(Error::python("AttributeError", name.to_string())),
    })
}
