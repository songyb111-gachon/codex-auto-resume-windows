//! One capability's view of the state, as its code is given it (`state/choices.py`'s `Scoped`, and the handles of
//! every table: `ResetsHandle`, `ContinuationsHandle`, `PromptsHandle`, `MeterHandle`, `RunsHandle`,
//! `AnalyticsHandle`, `RestartsHandle`, `ChatHandle`, `OpensHandle`, `SteersHandle`, `AccountHandle`).
//!
//! Reads always; writes only while the runtime has the capability on (`on() is True`), and some only for the one
//! capability whose table it is. Held by reference, as the reference holds the state in a closure: against a
//! capability's mistakes, not its intent. Scoped's `outbox` and `feed` are the courier's (`courier/outbox.py`,
//! `courier/feed.py`, seat S7.3b): push_notices' outbox, written only while it is on, and the feed's last reading.

use car_machine::json::Value;

use super::ask::RegistryAsked;
use super::errors::{Error, Result};
use super::py;
use super::resets::{CREDIT, MESSAGE};
use super::session::AdvancedState;
use super::sql::{self, Row, string};
use crate::vocabulary::{
    ArmingState, ChatReason, PromptState, RecordState, RuleReason, RuleState, SteerState,
};

/// The runtime's `on()`: whether it has the capability on now (`on is not None and on() is True`).
pub type On<'a> = Option<&'a dyn Fn() -> bool>;
/// `verdict(measurement)`: "pass", "fail", or anything else.
pub type Verdict<'a> = Option<&'a dyn Fn(&Value) -> Value>;
/// `armed(other)`: whether another capability stands on now.
pub type Armed<'a> = Option<&'a dyn Fn(&Value) -> bool>;

fn is_on(on: On<'_>) -> bool {
    on.is_some_and(|on| on())
}

fn not_on() -> Error {
    Error::state("the capability is not on")
}

/// `Scoped(state, capability, on, verdict, armed)`.
pub struct Scoped<'a> {
    pub state: &'a AdvancedState,
    pub capability: Value,
    pub on: On<'a>,
    pub verdict: Verdict<'a>,
    pub armed: Armed<'a>,
}

impl<'a> Scoped<'a> {
    pub fn now(&self) -> f64 {
        self.state.clock_now()
    }

    pub fn options(&self) -> Result<Row> {
        self.state.options(&self.capability)
    }

    pub fn wordings(&self) -> Result<Row> {
        self.state.wordings(&self.capability)
    }

    pub fn options_of(&self, other: &Value) -> Result<Row> {
        self.state.options(other)
    }

    /// `rules()`: the rules, where it is the one they are written for.
    pub fn rules(&self) -> Result<Vec<Row>> {
        let editor = self
            .state
            .registry
            .get_value(&self.capability)
            .is_some_and(|definition| definition.rules_editor);
        if editor {
            self.state.rules()
        } else {
            Ok(Vec::new())
        }
    }

    /// `admission(interruption_id)`: its own admission row, or None.
    pub fn admission(&self, interruption_id: &Value) -> Result<Option<Row>> {
        Ok(self
            .state
            .admission(interruption_id)?
            .filter(|row| sql::py_eq(sql::get(row, "capability"), &self.capability)))
    }

    /// `count(code)`: one of its own codes counted with its journal line, only while on.
    pub fn count(&self, code: &Value) -> Result<bool> {
        Ok(is_on(self.on) && self.state.counted(&self.capability, code, &Value::Null)?)
    }

    /// `sample(code)`: counted today, no journal line, only while on.
    pub fn sample(&self, code: &Value) -> Result<bool> {
        Ok(is_on(self.on) && self.state.sample(&self.capability, code, &Value::Null)?)
    }

    pub fn resent(&self, interruption_id: &Value) -> Result<bool> {
        self.state.resent(interruption_id)
    }

    pub fn channel_paid(&self, interruption_id: &Value, claimed_at: &Value) -> Result<bool> {
        self.state.channel_paid(interruption_id, claimed_at)
    }

    /// `request(interruption_id)`: its own override of one standard record.
    pub fn request(&self, interruption_id: &Value) -> Result<Option<Row>> {
        self.state.override_of(interruption_id, &self.capability)
    }

    /// `since()`: since when it has stood where it stands, None where it is off or has no row.
    pub fn since(&self) -> Result<Value> {
        let arming = self.state.arming()?;
        let row = py::text(&self.capability).and_then(|capability| arming.get(capability));
        Ok(match row {
            Some(Value::Object(row)) => {
                let state = sql::get(row, "state");
                if matches!(state, Value::Null) || py::is_word(state, &[ArmingState::Off.as_str()])
                {
                    Value::Null
                } else {
                    sql::get(row, "since").clone()
                }
            }
            _ => Value::Null,
        })
    }

    pub fn stamped(&self, key: &Value) -> Result<Value> {
        self.state.stamped(&self.capability, key)
    }

    pub fn stamp(&self, key: &Value, value: &Value) -> Result<bool> {
        Ok(is_on(self.on) && self.state.stamp(&self.capability, key, value)?)
    }

    pub fn unstamp(&self, key: &Value) -> Result<bool> {
        Ok(is_on(self.on) && self.state.unstamp(&self.capability, key)?)
    }

    pub fn stamped_of(&self, other: &Value, key: &Value) -> Result<Value> {
        self.state.stamped(other, key)
    }

    pub fn continuations_of(
        &self,
        other: &Value,
        thread_id: &Value,
        pending: &Value,
    ) -> Result<Vec<Row>> {
        self.state.continuations(other, thread_id, pending)
    }

    pub fn counted_since(&self, code: &Value, since: &Value) -> Result<i64> {
        self.state.counted_since(&self.capability, code, since)
    }

    /// `stored_on()`: whether its own stored state is armed now, read afresh.
    pub fn stored_on(&self) -> Result<bool> {
        let arming = self.state.arming()?;
        Ok(py::text(&self.capability)
            .and_then(|capability| arming.get(capability))
            .is_some_and(|row| match row {
                Value::Object(row) => {
                    py::is_word(sql::get(row, "state"), &[ArmingState::Armed.as_str()])
                }
                _ => false,
            }))
    }

    /// `outbox`: push_notices' view of the outbox (`courier/outbox.OutboxHandle`).
    pub fn outbox(&self) -> crate::courier::outbox::OutboxHandle<'_> {
        crate::courier::outbox::OutboxHandle {
            state: self.state,
            capability: &self.capability,
            on: self.on,
        }
    }

    /// `feed()`: the status feed's last reading (`courier/feed.read`), read always.
    pub fn feed(&self) -> Result<Option<Row>> {
        crate::courier::feed::read(self.state)
    }

    pub fn journal_times(&self, other: &Value, word: &Value, since: &Value) -> Result<Vec<Value>> {
        self.state.journal_times(other, word, since)
    }

    pub fn passed(&self, measurement: &Value) -> bool {
        self.verdict
            .is_some_and(|verdict| py::is_word(&verdict(measurement), &["pass"]))
    }

    pub fn failed(&self, measurement: &Value) -> bool {
        self.verdict
            .is_some_and(|verdict| py::is_word(&verdict(measurement), &["fail"]))
    }

    pub fn armed(&self, other: &Value) -> bool {
        self.armed.is_some_and(|armed| armed(other))
    }

    /// The handles (`resets`, `continuations`, ...): each the capability's own view of one table.
    pub fn handle(&self) -> Handle<'_> {
        Handle {
            state: self.state,
            capability: &self.capability,
            on: self.on,
            armed: self.armed,
        }
    }
}

/// What every table's handle holds: the state, the capability, and the runtime's `on` (and, for the analytics,
/// `armed`).
#[derive(Clone, Copy)]
pub struct Handle<'a> {
    pub state: &'a AdvancedState,
    pub capability: &'a Value,
    pub on: On<'a>,
    pub armed: Armed<'a>,
}

impl Handle<'_> {
    pub fn is_on(&self) -> bool {
        is_on(self.on)
    }

    /// `writing(call)`: refused unless on.
    fn writing(&self) -> Result<()> {
        if self.is_on() { Ok(()) } else { Err(not_on()) }
    }

    fn mine(&self, capability: &str) -> bool {
        py::is_word(self.capability, &[capability])
    }

    // ---------------------------------------------------------------- ResetsHandle
    /// `resets.own(call)`: its own rule only, and only while on.
    pub fn resets_own(&self, rule_id: &Value) -> Result<()> {
        self.writing()?;
        let rule = self.state.reset_rule(rule_id)?;
        if !rule.is_some_and(|rule| sql::py_eq(sql::get(&rule, "capability"), self.capability)) {
            return Err(Error::state("not this capability's rule"));
        }
        Ok(())
    }

    /// `resets.writing(call)`.
    pub fn resets_writing(&self) -> Result<()> {
        self.writing()
    }

    /// `resets.carried_message(rule_id, started)`: what came of a carried launch, counted in reset_message's own
    /// words.
    pub fn resets_carried(&self, rule_id: &Value, started: &Value) -> Result<bool> {
        self.writing()?;
        let done = self.state.carried_message(rule_id, started, &Value::Null)?;
        if done && sql::truthy(started) {
            match self
                .state
                .counted(&string(MESSAGE), &string("sent"), &Value::Null)
            {
                Ok(_) | Err(Error::State { .. }) => {}
                Err(other) => return Err(other),
            }
        }
        Ok(done)
    }

    /// `resets.message_expired(rule_id)`: a carried message ended as expired.
    pub fn resets_expired(&self, rule_id: &Value) -> Result<bool> {
        self.writing()?;
        let rule = self.state.reset_rule(rule_id)?;
        let fits = rule.is_some_and(|rule| {
            py::is_word(sql::get(&rule, "capability"), &[MESSAGE])
                && py::is_word(sql::get(&rule, "state"), &[RuleState::Ready.as_str()])
                && py::is_word(
                    sql::get(&rule, "record_state"),
                    &[RecordState::Waiting.as_str()],
                )
        });
        if !fits {
            return Ok(false);
        }
        let done = self.state.end_rule(
            rule_id,
            &string(RuleState::Done.as_str()),
            &string(RuleReason::Expired.as_str()),
            &Value::Null,
        )?;
        if done {
            match self
                .state
                .counted(&string(MESSAGE), &string("expired"), &Value::Null)
            {
                Ok(_) | Err(Error::State { .. }) => {}
                Err(other) => return Err(other),
            }
        }
        Ok(done)
    }

    /// Whether `capability` is a reset action's (`CREDIT` or `MESSAGE`).
    pub fn is_reset(&self) -> bool {
        self.mine(CREDIT) || self.mine(MESSAGE)
    }

    // ---------------------------------------------------------------- ContinuationsHandle
    /// `continuations.get(key)`: one of its own, or None.
    pub fn continuation(&self, key: &Value) -> Result<Option<Row>> {
        Ok(self
            .state
            .continuation(key)?
            .filter(|row| sql::py_eq(sql::get(row, "capability"), self.capability)))
    }

    /// The continuations handle's writes: refused unless on.
    pub fn continuations_writing(&self) -> Result<()> {
        self.writing()
    }

    // ---------------------------------------------------------------- PromptsHandle
    /// `prompts.occur(prompt_id, key, thread_id, due_at)`: a due prompt's occurrence.
    pub fn prompts_occur(
        &self,
        prompt_id: &Value,
        key: &Value,
        thread_id: &Value,
        due_at: &Value,
    ) -> Result<bool> {
        self.writing()?;
        if self
            .state
            .add_record(key, self.capability, thread_id, due_at)?
        {
            self.state.change_prompt(
                prompt_id,
                &[
                    ("state".into(), string(PromptState::Ready.as_str())),
                    ("record_id".into(), key.clone()),
                    ("due_at".into(), due_at.clone()),
                ],
            )?;
            return Ok(true);
        }
        Ok(false)
    }

    /// `prompts.drop(key)`: its occurrence's record cancelled.
    pub fn prompts_drop(&self, key: &Value) -> Result<bool> {
        self.writing()?;
        self.state
            .move_record(key, &string(RecordState::Cancelled.as_str()), &Value::Null)
    }

    /// The prompts handle's other writes.
    pub fn prompts_writing(&self) -> Result<()> {
        self.writing()
    }

    // ---------------------------------------------------------------- MeterHandle
    /// `meter.save(windows)`: only the meter writes a reading, only while on.
    pub fn meter_save(&self, windows: &Value) -> Result<i64> {
        self.meter_writer()?;
        if !self.mine(super::meter::METER) {
            return Err(Error::state("only the meter writes a reading"));
        }
        self.state.save_meter(windows, &Value::Null)
    }

    /// `meter.writing`: the meter and the pause, while on.
    pub fn meter_writer(&self) -> Result<()> {
        if !(self.mine(super::meter::METER) || self.mine("usage_pause")) || !self.is_on() {
            return Err(Error::state("the capability may not write the meter now"));
        }
        Ok(())
    }

    // ---------------------------------------------------------------- RunsHandle
    /// `runs.live()`: its own runs still going.
    pub fn runs_live(&self) -> Result<Vec<Row>> {
        Ok(self
            .state
            .runs(&Value::Bool(true), &py::int(20))?
            .into_iter()
            .filter(|row| sql::py_eq(sql::get(row, "capability"), self.capability))
            .collect())
    }

    // ---------------------------------------------------------------- AnalyticsHandle
    /// `analytics.files()`: usage_analytics' files read so far; nothing for another.
    pub fn analytics_files(&self) -> Result<Row> {
        if self.mine(super::analytics::CAPABILITY) {
            self.state.token_files()
        } else {
            Ok(Row::new())
        }
    }

    /// `analytics.ingest`: usage_analytics' alone, while on.
    pub fn analytics_ingest(&self) -> Result<()> {
        if !self.mine(super::analytics::CAPABILITY) {
            return Err(Error::state("the capability may not write the analytics"));
        }
        if !self.is_on() {
            return Err(Error::state(
                "the capability may not write the analytics now",
            ));
        }
        Ok(())
    }

    /// `analytics.sample(windows)`: the meter's alone, while on and while usage_analytics stands on.
    pub fn analytics_sample(&self, windows: &Value, at: &Value) -> Result<i64> {
        if !self.mine(super::analytics::METER) {
            return Err(Error::state("the capability may not write the analytics"));
        }
        let analytics_on = self
            .armed
            .is_some_and(|armed| armed(&string(super::analytics::CAPABILITY)));
        if !self.is_on() || !analytics_on {
            return Err(Error::state("the meter may not keep samples now"));
        }
        self.state.add_samples(windows, at)
    }

    // ---------------------------------------------------------------- RestartsHandle
    /// `restarts.noted(exit_code, restarted)`: crash_restart's alone, while on.
    pub fn restarts_noted(&self, exit_code: &Value, restarted: &Value) -> Result<bool> {
        if !self.mine(super::small::RESTARTER) || !self.is_on() {
            return Err(Error::state(
                "the capability may not write the restarts now",
            ));
        }
        self.state.restart_noted(exit_code, restarted, &Value::Null)
    }

    // ---------------------------------------------------------------- ChatHandle
    /// `chat.pending()`.
    pub fn chat_pending(&self) -> Result<Vec<Row>> {
        self.state
            .chats(&Value::Null, &Value::Bool(true), &py::int(50))
    }

    /// `chat.conversation_off(record_id)`: chat's alone, while on; 0 otherwise.
    pub fn chat_conversation_off(&self, record_id: &Value) -> Result<i64> {
        if !self.mine(super::chat::CAPABILITY) || !self.is_on() {
            return Ok(0);
        }
        self.state.cancel_chat(
            &string(ChatReason::ConversationOff.as_str()),
            record_id,
            &Value::Null,
            &Value::Null,
        )
    }

    // ---------------------------------------------------------------- OpensHandle, SteersHandle
    /// The opens' and the steers' writes: refused unless on.
    pub fn table_writing(&self) -> Result<()> {
        self.writing()
    }

    /// `steers.settle(steer_id, state, reason=None, at=None)`: a refusal whatever it stands at, anything else only
    /// while on.
    pub fn steers_settle(
        &self,
        steer_id: &Value,
        word: &Value,
        reason: &Value,
        at: &Value,
    ) -> Result<bool> {
        if py::py_str(word) != SteerState::Refused.as_str() && !self.is_on() {
            return Err(not_on());
        }
        self.state.settle_steer(steer_id, word, reason, at)
    }

    // ---------------------------------------------------------------- AccountHandle
    /// `account.seen()` and `account.save(...)`: account_switch's alone, and its writes only while on.
    pub fn account_guard(&self, writes: bool) -> Result<()> {
        if !self.mine(super::small::ACCOUNT) || (writes && !self.is_on()) {
            return Err(Error::state(
                "only account_switch, while on, keeps the account seen",
            ));
        }
        Ok(())
    }
}
