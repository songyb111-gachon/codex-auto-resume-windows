//! What a test made a state method raise, for the advanced proxy (seat S7.2a3): `patch.object(runtime.state, "arming",
//! side_effect=StateError(...))` reaches car-adv's runtime as a name in [`Faults`], and every call the runtime and its
//! `Arming` make of that method raises the state's fault instead (`StateError`) - what the reference meets when the
//! test's mock raises. Empty in the product: [`Faulted`] then hands every call on unchanged.

use std::collections::{BTreeMap, BTreeSet};
use std::sync::{Mutex, PoisonError};

use car_machine::json::Value;

use crate::seam::{
    ArmRow, ContinuationRow, Meta, Move, OverrideRow, ResetRule, StateFault, StatePort, StateResult,
};
use crate::vocabulary::{
    Actor, ArmingState, ArmingWarning, ContinuationReason, OffReason, OptionKey, OverrideKind,
    PromptReason, RuleReason, RuleState, SteerReason, WordingKey,
};

/// The state methods that raise, by name.
#[derive(Default)]
pub struct Faults(Mutex<BTreeSet<String>>);

impl Faults {
    /// `method` raises from now on (`true`) or no more (`false`).
    pub fn set(&self, method: &str, raises: bool) {
        let mut held = self.0.lock().unwrap_or_else(PoisonError::into_inner);
        if raises {
            held.insert(method.to_owned());
        } else {
            held.remove(method);
        }
    }

    /// Whether `method` raises now.
    pub fn raises(&self, method: &str) -> bool {
        let held = self.0.lock().unwrap_or_else(PoisonError::into_inner);
        !held.is_empty() && held.contains(method)
    }
}

/// The state as `Arming` reaches it: the runtime's own, with the methods [`Faults`] names raising.
pub struct Faulted<'a> {
    pub inner: &'a dyn StatePort,
    pub faults: &'a Faults,
}

impl Faulted<'_> {
    fn check(&self, method: &str) -> StateResult<()> {
        if self.faults.raises(method) {
            return Err(StateFault::State);
        }
        Ok(())
    }
}

impl StatePort for Faulted<'_> {
    fn arming(&self) -> StateResult<Vec<(String, ArmRow)>> {
        self.check("arming")?;
        self.inner.arming()
    }

    fn meta(&self) -> StateResult<Meta> {
        self.check("meta")?;
        self.inner.meta()
    }

    fn ever_moved(&self, capability: &str) -> StateResult<bool> {
        self.check("ever_moved")?;
        self.inner.ever_moved(capability)
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
        generation: Option<i64>,
        at: f64,
    ) -> StateResult<(bool, i64)> {
        self.check("move_to")?;
        self.inner.move_to(
            capability,
            state,
            actor,
            reason,
            revision,
            engine_version,
            warnings,
            generation,
            at,
        )
    }

    fn move_set(
        &self,
        moves: &[Move],
        actor: Actor,
        generation: i64,
        at: f64,
        keep: &[String],
    ) -> StateResult<(i64, i64)> {
        self.check("move_set")?;
        self.inner.move_set(moves, actor, generation, at, keep)
    }

    fn all_off(&self, actor: Actor, reason: OffReason, at: f64) -> StateResult<(i64, i64)> {
        self.check("all_off")?;
        self.inner.all_off(actor, reason, at)
    }

    fn set_keep_on(
        &self,
        capability: &str,
        keep_on: bool,
        send_again: bool,
        actor: Actor,
        generation: Option<i64>,
        at: f64,
    ) -> StateResult<i64> {
        self.check("set_keep_on")?;
        self.inner
            .set_keep_on(capability, keep_on, send_again, actor, generation, at)
    }

    fn send_again_off(&self, capability: &str, reason: OffReason, at: f64) -> StateResult<bool> {
        self.check("send_again_off")?;
        self.inner.send_again_off(capability, reason, at)
    }

    fn note_kept(&self, capability: &str, reason: OffReason, at: f64) -> StateResult<bool> {
        self.check("note_kept")?;
        self.inner.note_kept(capability, reason, at)
    }

    fn set_global_hourly(
        &self,
        value: i64,
        generation: i64,
        actor: Actor,
        at: f64,
    ) -> StateResult<i64> {
        self.check("set_global_hourly")?;
        self.inner.set_global_hourly(value, generation, actor, at)
    }

    fn spends_since(&self, capability: &str, since: f64) -> StateResult<Vec<(String, Vec<f64>)>> {
        self.check("spends_since")?;
        self.inner.spends_since(capability, since)
    }

    fn open_overrides(&self, kind: OverrideKind) -> StateResult<Vec<OverrideRow>> {
        self.check("open_overrides")?;
        self.inner.open_overrides(kind)
    }

    fn use_override(&self, key: &str, capability: &str, at: f64) -> StateResult<()> {
        self.check("use_override")?;
        self.inner.use_override(key, capability, at)
    }

    fn resent(&self, key: &str) -> StateResult<bool> {
        self.check("resent")?;
        self.inner.resent(key)
    }

    fn payers(&self, key: &str, claimed_at: Option<f64>) -> StateResult<Vec<(String, Vec<f64>)>> {
        self.check("payers")?;
        self.inner.payers(key, claimed_at)
    }

    fn reset_rules(&self) -> StateResult<Vec<ResetRule>> {
        self.check("reset_rules")?;
        self.inner.reset_rules()
    }

    fn end_rule(
        &self,
        rule_id: &Value,
        state: RuleState,
        reason: RuleReason,
        at: f64,
    ) -> StateResult<()> {
        self.check("end_rule")?;
        self.inner.end_rule(rule_id, state, reason, at)
    }

    fn reading_has_credits(&self) -> StateResult<bool> {
        self.check("reading_has_credits")?;
        self.inner.reading_has_credits()
    }

    fn clear_reading(&self) -> StateResult<()> {
        self.check("clear_reading")?;
        self.inner.clear_reading()
    }

    fn end_prompts(&self, reason: PromptReason, at: f64) -> StateResult<()> {
        self.check("end_prompts")?;
        self.inner.end_prompts(reason, at)
    }

    fn end_requested_steers(&self, reason: SteerReason, at: f64) -> StateResult<()> {
        self.check("end_requested_steers")?;
        self.inner.end_requested_steers(reason, at)
    }

    fn continuations_pending(&self) -> StateResult<Vec<ContinuationRow>> {
        self.check("continuations_pending")?;
        self.inner.continuations_pending()
    }

    fn end_continuations(
        &self,
        reason: ContinuationReason,
        capability: &str,
        at: f64,
    ) -> StateResult<()> {
        self.check("end_continuations")?;
        self.inner.end_continuations(reason, capability, at)
    }

    fn options(&self, capability: &str) -> StateResult<BTreeMap<OptionKey, i64>> {
        self.check("options")?;
        self.inner.options(capability)
    }

    fn wordings(&self, capability: &str) -> StateResult<BTreeMap<WordingKey, Option<String>>> {
        self.check("wordings")?;
        self.inner.wordings(capability)
    }

    fn set_option(
        &self,
        capability: &str,
        key: &Value,
        value: &Value,
        generation: &Value,
        actor: Actor,
        at: f64,
    ) -> StateResult<i64> {
        self.check("set_option")?;
        self.inner
            .set_option(capability, key, value, generation, actor, at)
    }

    fn set_wording(
        &self,
        capability: &str,
        key: &Value,
        words: &Value,
        generation: &Value,
        actor: Actor,
        at: f64,
    ) -> StateResult<i64> {
        self.check("set_wording")?;
        self.inner
            .set_wording(capability, key, words, generation, actor, at)
    }

    #[allow(clippy::too_many_arguments)]
    fn add_rule(
        &self,
        tag: &Value,
        status_from: &Value,
        status_to: &Value,
        category: &Value,
        generation: &Value,
        actor: Actor,
        at: f64,
    ) -> StateResult<(Value, i64)> {
        self.check("add_rule")?;
        self.inner
            .add_rule(tag, status_from, status_to, category, generation, actor, at)
    }

    fn remove_rule(
        &self,
        rule: &Value,
        generation: &Value,
        actor: Actor,
        at: f64,
    ) -> StateResult<i64> {
        self.check("remove_rule")?;
        self.inner.remove_rule(rule, generation, actor, at)
    }

    fn rules(&self) -> StateResult<Vec<Value>> {
        self.check("rules")?;
        self.inner.rules()
    }

    fn rule_hits(&self, since: f64) -> StateResult<Vec<(Value, i64)>> {
        self.check("rule_hits")?;
        self.inner.rule_hits(since)
    }

    fn failure_samples(&self, since: f64) -> StateResult<Vec<Value>> {
        self.check("failure_samples")?;
        self.inner.failure_samples(since)
    }

    fn aggregated(&self, samples: &[Value]) -> Value {
        self.inner.aggregated(samples)
    }

    fn tag_is_valid(&self, tag: &str) -> bool {
        self.inner.tag_is_valid(tag)
    }
}
