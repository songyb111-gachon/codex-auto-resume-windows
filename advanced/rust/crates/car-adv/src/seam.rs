//! The seams `arming` reaches the rest of the advanced edition through (S7.1b).
//!
//! `arming.py` reads the advanced state (`state/`, S7.1a's), the compatibility data and the automatic check's record, and
//! reaches by lazy import into the engine and the control modules (S7.2's and S7.3's: the Stop hook's declaration, core's
//! power action, the saved account, the usage meter's order rules, the wrap-up's wording check). None of those is this seat's;
//! each is named here as a method, so the integration seat replaces the stand-in a diff uses with the real one and nothing in
//! `arming` changes.
//!
//! * [`StatePort`] - every call `Arming` makes of `AdvancedState`, with the faults it can raise ([`StateFault`]: `StateError`,
//!   `StaleGeneration` and `Refused`, the last two being subclasses of the first in the tag, as they are matched here).
//! * [`Edges`] - the rest: what `arming.py` imports inside a function.
//!
//! The diffs run `Arming` over an in-memory `StatePort` and `Edges` of the probe's own, and the tag's `Arming` over a Python
//! stand-in with the same semantics; what they hold equal is every decision `Arming` makes, not the state's storage (S7.1a's).

use std::collections::BTreeMap;

use car_machine::json::Value;

use crate::measured::Table;
use crate::vocabulary::{
    Actor, ArmingState, ArmingWarning, AutoResult, ContinuationReason, Measurement, OffReason,
    OptionKey, OverrideKind, PromptReason, Refusal, RuleReason, RuleState, SteerReason, WordingKey,
};

/// What `AdvancedState` raises: `StateError` (the state cannot be used), `StaleGeneration` (a request made against a
/// generation that is no longer current) and `Refused(why)` (a choice or a rule this edition does not take).
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum StateFault {
    State,
    Stale,
    Refused(Refusal),
}

pub type StateResult<T> = Result<T, StateFault>;

/// What a view, a table or a record reads when it cannot be read (the tag's `except Exception`): nothing more is said.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Unavailable;

/// An arming row as the rest of the edition reads it (`state/arming._row`, with Keep on's two words).
#[derive(Clone, Debug, PartialEq)]
pub struct ArmRow {
    pub state: ArmingState,
    pub since: Option<f64>,
    pub actor: Option<Actor>,
    pub reason: Option<OffReason>,
    pub statement_revision: Option<i64>,
    pub engine_version: Option<String>,
    /// The warnings the person confirmed, in the vocabulary's order.
    pub warnings: Vec<ArmingWarning>,
    pub keep_on: bool,
    pub send_again: bool,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Meta {
    pub generation: i64,
    pub global_hourly: i64,
}

/// `(capability, state, revision, engine_version, warnings)`: one move of `move_set`.
#[derive(Clone, Debug, PartialEq)]
pub struct Move {
    pub capability: String,
    pub state: ArmingState,
    pub revision: Value,
    pub engine_version: Option<String>,
    pub warnings: Vec<ArmingWarning>,
}

/// An override a capability asked of one record (`open_overrides`).
#[derive(Clone, Debug, PartialEq)]
pub struct OverrideRow {
    pub interruption_id: String,
    pub capability: String,
    pub created_at: f64,
}

/// A reset rule the sweep may end (`reset_rules`).
#[derive(Clone, Debug, PartialEq)]
pub struct ResetRule {
    pub rule_id: Value,
    pub capability: String,
    pub launching_at: Option<f64>,
    pub record_state: Option<String>,
}

/// A continuation row (`continuations(pending=True)`).
#[derive(Clone, Debug, PartialEq)]
pub struct ContinuationRow {
    pub capability: String,
    pub record_state: Option<String>,
}

/// Every call `Arming` makes of the advanced state. Times are Unix seconds; a call that cannot be made says why in a fault.
pub trait StatePort {
    /// Every capability of the registry that has a row, in the state's order.
    fn arming(&self) -> StateResult<Vec<(String, ArmRow)>>;
    fn meta(&self) -> StateResult<Meta>;
    fn ever_moved(&self, capability: &str) -> StateResult<bool>;
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
    ) -> StateResult<(bool, i64)>;
    fn move_set(
        &self,
        moves: &[Move],
        actor: Actor,
        generation: i64,
        at: f64,
        keep: &[String],
    ) -> StateResult<(i64, i64)>;
    fn all_off(&self, actor: Actor, reason: OffReason, at: f64) -> StateResult<(i64, i64)>;
    fn set_keep_on(
        &self,
        capability: &str,
        keep_on: bool,
        send_again: bool,
        actor: Actor,
        generation: Option<i64>,
        at: f64,
    ) -> StateResult<i64>;
    fn send_again_off(&self, capability: &str, reason: OffReason, at: f64) -> StateResult<bool>;
    fn note_kept(&self, capability: &str, reason: OffReason, at: f64) -> StateResult<bool>;
    fn set_global_hourly(
        &self,
        value: i64,
        generation: i64,
        actor: Actor,
        at: f64,
    ) -> StateResult<i64>;
    /// `{record: the times of the units it paid}` since `since`, in the state's order.
    fn spends_since(&self, capability: &str, since: f64) -> StateResult<Vec<(String, Vec<f64>)>>;
    fn open_overrides(&self, kind: OverrideKind) -> StateResult<Vec<OverrideRow>>;
    fn use_override(&self, key: &str, capability: &str, at: f64) -> StateResult<()>;
    fn resent(&self, key: &str) -> StateResult<bool>;
    /// `{capability: the times it paid for a send of `key`}`, in the state's order.
    fn payers(&self, key: &str, claimed_at: Option<f64>) -> StateResult<Vec<(String, Vec<f64>)>>;
    fn reset_rules(&self) -> StateResult<Vec<ResetRule>>;
    fn end_rule(
        &self,
        rule_id: &Value,
        state: RuleState,
        reason: RuleReason,
        at: f64,
    ) -> StateResult<()>;
    /// `reading().get("credits") is not None`.
    fn reading_has_credits(&self) -> StateResult<bool>;
    /// `set_reading(credits=None, expiry_known=None, nearest_expiry=None)`.
    fn clear_reading(&self) -> StateResult<()>;
    fn end_prompts(&self, reason: PromptReason, at: f64) -> StateResult<()>;
    fn end_requested_steers(&self, reason: SteerReason, at: f64) -> StateResult<()>;
    fn continuations_pending(&self) -> StateResult<Vec<ContinuationRow>>;
    fn end_continuations(
        &self,
        reason: ContinuationReason,
        capability: &str,
        at: f64,
    ) -> StateResult<()>;
    fn options(&self, capability: &str) -> StateResult<BTreeMap<OptionKey, i64>>;
    fn wordings(&self, capability: &str) -> StateResult<BTreeMap<WordingKey, Option<String>>>;
    fn set_option(
        &self,
        capability: &str,
        key: &Value,
        value: &Value,
        generation: &Value,
        actor: Actor,
        at: f64,
    ) -> StateResult<i64>;
    fn set_wording(
        &self,
        capability: &str,
        key: &Value,
        words: &Value,
        generation: &Value,
        actor: Actor,
        at: f64,
    ) -> StateResult<i64>;
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
    ) -> StateResult<(Value, i64)>;
    fn remove_rule(
        &self,
        rule: &Value,
        generation: &Value,
        actor: Actor,
        at: f64,
    ) -> StateResult<i64>;
    /// The rules, oldest first: each `{"rule_id", "tag", "status_from", "status_to", "category", "known"}`.
    fn rules(&self) -> StateResult<Vec<Value>>;
    /// `{rule_id: how many failures it took up}` since `since`.
    fn rule_hits(&self, since: f64) -> StateResult<Vec<(Value, i64)>>;
    /// The failure samples since `since`: each `{"tag": text or null, ...}`.
    fn failure_samples(&self, since: f64) -> StateResult<Vec<Value>>;
    /// `choices.aggregated(samples)`: what the Dashboard and a diagnostics export show of them.
    fn aggregated(&self, samples: &[Value]) -> Value;
    /// `choices.tag_problem(tag)` is `None`.
    fn tag_is_valid(&self, tag: &str) -> bool;
}

/// What `arming.py` imports inside a function, and the compatibility data and the automatic check's record it reads.
pub trait Edges {
    /// The Compatibility Registry's view, as a surface shows it (`_view_of`), asked when no view was handed in.
    fn default_view(&self) -> Result<Value, Unavailable>;
    /// A fresh check of the Codex here (`_live_view_of`), asked when `live` was not handed in and the view is this machine's.
    fn default_live_view(&self) -> Result<Value, Unavailable>;
    /// The advanced compatibility data laid over this build's table for `engine` (`compatdata.table_for`).
    fn table_for(&self, engine: Option<&str>) -> Result<Table, Unavailable>;
    /// What the automatic check found of exactly this engine (`autocheck.results_for`).
    fn checked_for(
        &self,
        engine: Option<&str>,
    ) -> Result<BTreeMap<Measurement, AutoResult>, Unavailable>;
    /// `runtime.SENDING`'s points: the ones whose answer leads to a send.
    fn sending_points(&self) -> Vec<car_policy::plug::Point>;
    /// The Stop hook's declaration follows its capability's state (`hookplugin.follow`); `armed` is where it stands.
    fn hook_follow(&self, armed: bool);
    /// Core's power action armed for tasks follows `power_after_tasks`' state (`powertasks.follow`).
    fn power_tasks_follow(&self, armed: bool);
    /// `account.forget`: the salt out of Credential Manager and the account seen out of the state - an implementation
    /// calls `engine::account::forget_real` on its state (Integration 10); a fault that returns is one the reference
    /// lets out of the sweep, a caught one is false.
    fn account_forget(&self);
    /// `usage.touched(key)`: the windows whose order an option bears on.
    fn usage_touched(&self, key: OptionKey) -> Vec<i64>;
    /// `usage.order_problem(values, windows)`: (refusal word, warning word).
    fn usage_order_problem(
        &self,
        values: &BTreeMap<String, BTreeMap<OptionKey, i64>>,
        windows: &[i64],
    ) -> (Option<String>, Option<String>);
    /// `usage.previews(state, now)`: what the wrap-up would send for each window now.
    fn usage_previews(&self, now: f64) -> Vec<(i64, Option<String>)>;
    /// `wrapwords.check_custom(words)`: the code of the check a wording fails, or `None`.
    fn wording_problem(&self, words: &Value) -> Option<String>;
    /// `wrapwords.continuation.MAX_CUSTOM_LENGTH`.
    fn wording_limit(&self) -> i64;
    /// `wrapwords.PLACEHOLDERS`.
    fn wording_placeholders(&self) -> Vec<String>;
}

/// The ids of the capabilities whose state other modules follow (`control/hookplugin.CAPABILITY`, `engine/powertasks.CAPABILITY`,
/// `engine/account.CAPABILITY`, `state/resets.CREDIT`, `engine/usage`'s three, and the prompt queue's and steer's).
pub const HOOK_CAPABILITY: &str = "stop_hook_continuation";
pub const POWER_TASKS_CAPABILITY: &str = "power_after_tasks";
pub const ACCOUNT_CAPABILITY: &str = "account_switch";
pub const CREDIT: &str = "reset_credit";
pub const PROMPT_QUEUE: &str = "prompt_queue";
pub const STEER_SEND: &str = "steer_send";
pub const METER: &str = "usage_meter";
pub const WRAP_UP: &str = "usage_wrap_up";
pub const PAUSE: &str = "usage_pause";
/// `state/choices`: the days the samples and rules' hits are read over, a day in seconds, and how many rules there may be.
pub const RECENT_DAYS: i64 = 30;
pub const DAY: i64 = 86_400;
pub const RULES_LIMIT: i64 = 10;
