//! What the engine was given, and the policy it was last told (`engine/options.py`).
//!
//! The settings a person chose are re-read at the moment of sending rather than at the moment of failing, so a style or
//! a language changed while a recovery waits applies to that recovery.

use std::collections::BTreeSet;

use car_machine::domain::public::hold_for_tier;
use car_machine::json::{Map, Str, Value};
use car_machine::pyval::Py;
use car_policy::classify::gates::{Limits, OBSERVE_ONLY};
use car_policy::classify::{ladder, projects, quiet};
use car_policy::settings::{self as policy, managed};

use crate::py::{self, get, truthy};
use crate::{Engine, Row};

/// Bounded exponential backoff for proven "queue process never started" failures.
pub const BACKOFF_LADDER: [i64; 4] = [30, 60, 120, 300];
/// A transient failure waits on a bounded ladder, never on a usage reset.
pub const TRANSIENT_BACKOFF: [i64; 5] = [5, 15, 30, 60, 120];
/// How long the watcher waits to see a queued continuation delivered (the owner, 2026-11-10). What the watcher's
/// engines are built with; a bare Engine keeps 180.
pub const DELIVERY_TIMEOUT: i64 = 300;

/// `backoff_delay(retry)`: retry is 1-based: 30s, 1m, 2m, 5m, then 5m forever.
pub fn backoff_delay(retry: i64) -> i64 {
    let index = (retry - 1).clamp(0, BACKOFF_LADDER.len() as i64 - 1);
    BACKOFF_LADDER[index as usize]
}

/// `transient_delay(attempt)`: attempt is 1-based; the ladder is bounded.
pub fn transient_delay(attempt: i64) -> i64 {
    let index = (attempt - 1).clamp(0, TRANSIENT_BACKOFF.len() as i64 - 1);
    TRANSIENT_BACKOFF[index as usize]
}

/// `self.options`: the engine's numbers. Durations are seconds. A count the engine only compares with is a float, as
/// the reference compares whatever number it was given (`max_queue_retries` 2.5 fails at the third launch, not the
/// second); the budgets, the ceiling and the ladder's steps are the numbers given, `int` or `float`, because the
/// continuation's words, the claim and the waits read them as they are.
#[derive(Clone, Debug)]
pub struct Options {
    pub reset_grace_seconds: f64,
    pub conservative_poll_seconds: f64,
    pub state_poll_seconds: f64,
    pub delivery_timeout_seconds: f64,
    pub max_queue_retries: f64,
    pub max_submissions_per_thread_per_day: f64,
    pub thread_cooldown_seconds: f64,
    pub detection_lookback_seconds: f64,
    pub unknown_reconcile_window_seconds: f64,
    pub max_recovery_attempts: Value,
    pub max_no_progress: Value,
    pub max_chain_continuations: Value,
    pub settle_seconds: f64,
    pub projection_grace_seconds: f64,
    pub usage_never_available_seconds: f64,
    pub usage_after_reset_seconds: f64,
    pub loaded_check_seconds: f64,
    pub max_withdraw_attempts: f64,
    pub delete_retry_seconds: f64,
    pub watch_budget_seconds: f64,
    pub retry_ladder: Vec<Value>,
    /// None: every category the classifier can produce.
    pub recoverable_categories: Option<BTreeSet<String>>,
    pub resend_after_seconds: f64,
    pub resend_until_seconds: f64,
    /// v0.6.11: how long a task may keep failing with a temporary error; None (`Value::Null`) is no ceiling.
    pub max_chain_seconds: Value,
}

impl Default for Options {
    fn default() -> Self {
        Options {
            reset_grace_seconds: 60.0,
            conservative_poll_seconds: 900.0,
            state_poll_seconds: 60.0,
            delivery_timeout_seconds: 180.0,
            max_queue_retries: 5.0,
            max_submissions_per_thread_per_day: 5.0,
            thread_cooldown_seconds: 900.0,
            detection_lookback_seconds: 6.0 * 3600.0,
            unknown_reconcile_window_seconds: 24.0 * 3600.0,
            max_recovery_attempts: Value::from(4),
            max_no_progress: Value::from(3),
            max_chain_continuations: Value::from(6),
            settle_seconds: 10.0,
            projection_grace_seconds: 120.0,
            usage_never_available_seconds: 7.0 * 86400.0,
            usage_after_reset_seconds: 24.0 * 3600.0,
            loaded_check_seconds: 5.0,
            max_withdraw_attempts: 5.0,
            delete_retry_seconds: 10.0,
            watch_budget_seconds: 5.0,
            retry_ladder: TRANSIENT_BACKOFF
                .iter()
                .map(|step| Value::from(*step))
                .collect(),
            recoverable_categories: None,
            resend_after_seconds: 900.0,
            resend_until_seconds: 6.0 * 3600.0,
            max_chain_seconds: Value::Null,
        }
    }
}

impl Options {
    /// `{**defaults, **(options or {})}`: each name given replaces its default.
    pub fn apply(&mut self, given: &Map) {
        for (name, value) in given {
            let Some(name) = name.as_str() else { continue };
            let seconds = py::arithmetic(value);
            let number = seconds.map(|_| value.clone());
            match name {
                "reset_grace_seconds" => set(&mut self.reset_grace_seconds, seconds),
                "conservative_poll_seconds" => set(&mut self.conservative_poll_seconds, seconds),
                "state_poll_seconds" => set(&mut self.state_poll_seconds, seconds),
                "delivery_timeout_seconds" => set(&mut self.delivery_timeout_seconds, seconds),
                "max_queue_retries" => set(&mut self.max_queue_retries, seconds),
                "max_submissions_per_thread_per_day" => {
                    set(&mut self.max_submissions_per_thread_per_day, seconds)
                }
                "thread_cooldown_seconds" => set(&mut self.thread_cooldown_seconds, seconds),
                "detection_lookback_seconds" => set(&mut self.detection_lookback_seconds, seconds),
                "unknown_reconcile_window_seconds" => {
                    set(&mut self.unknown_reconcile_window_seconds, seconds)
                }
                "max_recovery_attempts" => set(&mut self.max_recovery_attempts, number),
                "max_no_progress" => set(&mut self.max_no_progress, number),
                "max_chain_continuations" => set(&mut self.max_chain_continuations, number),
                "settle_seconds" => set(&mut self.settle_seconds, seconds),
                "projection_grace_seconds" => set(&mut self.projection_grace_seconds, seconds),
                "usage_never_available_seconds" => {
                    set(&mut self.usage_never_available_seconds, seconds)
                }
                "usage_after_reset_seconds" => set(&mut self.usage_after_reset_seconds, seconds),
                "loaded_check_seconds" => set(&mut self.loaded_check_seconds, seconds),
                "max_withdraw_attempts" => set(&mut self.max_withdraw_attempts, seconds),
                "delete_retry_seconds" => set(&mut self.delete_retry_seconds, seconds),
                "watch_budget_seconds" => set(&mut self.watch_budget_seconds, seconds),
                "resend_after_seconds" => set(&mut self.resend_after_seconds, seconds),
                "resend_until_seconds" => set(&mut self.resend_until_seconds, seconds),
                "retry_ladder" => {
                    if let Value::Array(items) = value {
                        self.retry_ladder = items
                            .iter()
                            .filter(|item| py::arithmetic(item).is_some())
                            .cloned()
                            .collect();
                    }
                }
                "recoverable_categories" => {
                    self.recoverable_categories = match value {
                        Value::Array(items) => Some(
                            items
                                .iter()
                                .filter_map(|item| py::text(item).map(str::to_owned))
                                .collect(),
                        ),
                        _ => None,
                    }
                }
                "max_chain_seconds" => {
                    self.max_chain_seconds = number.unwrap_or(Value::Null);
                }
                _ => {}
            }
        }
    }

    /// `self.options[name]` for the numbers the watch reads.
    pub fn number(&self, name: &str) -> f64 {
        match name {
            "reset_grace_seconds" => self.reset_grace_seconds,
            "conservative_poll_seconds" => self.conservative_poll_seconds,
            "state_poll_seconds" => self.state_poll_seconds,
            "delivery_timeout_seconds" => self.delivery_timeout_seconds,
            "unknown_reconcile_window_seconds" => self.unknown_reconcile_window_seconds,
            "watch_budget_seconds" => self.watch_budget_seconds,
            "delete_retry_seconds" => self.delete_retry_seconds,
            "max_withdraw_attempts" => self.max_withdraw_attempts,
            "settle_seconds" => self.settle_seconds,
            "projection_grace_seconds" => self.projection_grace_seconds,
            "loaded_check_seconds" => self.loaded_check_seconds,
            _ => f64::NAN,
        }
    }
}

fn set<T>(slot: &mut T, value: Option<T>) {
    if let Some(value) = value {
        *slot = value;
    }
}

/// The budgets, as `limits()` gives them: a `dict` the continuation's words and the claim read.
pub type LimitsMap = Map;

/// The budgets a claim or a registration is told (`limits` as the store reads the dict).
pub fn limits_of(limits: &LimitsMap) -> Limits {
    let at = |name: &str| py::arithmetic(get(limits, name));
    Limits {
        max_no_progress: at("max_no_progress").unwrap_or(0.0),
        max_chain_continuations: at("max_chain_continuations").unwrap_or(0.0),
        max_recovery_attempts: at("max_recovery_attempts").unwrap_or(0.0),
        max_chain_seconds: at("max_chain_seconds"),
        managed_max_recovery_attempts: at("managed_max_recovery_attempts"),
    }
}

impl Engine {
    // ------------------------------------------------------------------ policy
    /// `apply_policy(values, managed)`: adopt the user's configurable policy - and, from v0.6.11, an administrator's
    /// policy keys, applied after the coercion, so they can only hold back.
    pub fn apply_policy(&mut self, values: &Value, managed: Option<managed::Managed>) {
        let own = policy::coerce(self.os.as_ref(), values);
        self.managed = managed.unwrap_or_default();
        let values = managed::clamp(&own, &self.managed);
        self.more_quiet = if self.managed.quiet_hours.is_empty() {
            Vec::new()
        } else {
            managed::quiet_sources(&Value::Object(own.clone()), &self.managed)
        };
        self.options.max_recovery_attempts = get(&values, "max_recovery_attempts").clone();
        self.options.max_no_progress = get(&values, "max_no_progress").clone();
        self.options.max_chain_continuations = get(&values, "max_chain_continuations").clone();
        let whole = Value::Object(values.clone());
        self.options.retry_ladder = ladder::ladder(&whole)
            .iter()
            .map(|step| Value::from(*step))
            .collect();
        self.options.detection_lookback_seconds =
            py::arithmetic(get(&values, "detection_lookback_hours")).unwrap_or(0.0) * 3600.0;
        self.options.recoverable_categories = Some(
            policy::CONFIGURABLE_CATEGORIES
                .iter()
                .filter(|category| policy::category_enabled(&whole, category).unwrap_or(false))
                .map(|category| (*category).to_owned())
                .collect(),
        );
        self.options.max_chain_seconds = ladder::ceiling(&whole).map_or(Value::Null, Value::from);
        self.policy_values = values;
    }

    /// The policy values as a `dict` value, for the functions that take one.
    pub fn values(&self) -> Value {
        Value::Object(self.policy_values.clone())
    }

    /// `limits()`.
    pub fn limits(&self) -> LimitsMap {
        let mut found = py::row(vec![
            (
                "max_recovery_attempts",
                self.options.max_recovery_attempts.clone(),
            ),
            ("max_no_progress", self.options.max_no_progress.clone()),
            (
                "max_chain_continuations",
                self.options.max_chain_continuations.clone(),
            ),
        ]);
        if !matches!(self.options.max_chain_seconds, Value::Null) {
            found.insert(
                Str::from("max_chain_seconds"),
                self.options.max_chain_seconds.clone(),
            );
        }
        found
    }

    /// `capacity_limits()`: the budgets of a capacity error the plug vouches for (CAPACITY, v0.6.14).
    pub fn capacity_limits(&self) -> LimitsMap {
        let per_day = Value::from(ladder::CAPACITY_PER_DAY);
        let mut found = py::row(vec![
            ("max_recovery_attempts", per_day.clone()),
            ("max_no_progress", per_day.clone()),
            ("max_chain_continuations", per_day),
        ]);
        if let Some(ceiling) = self.managed.max_recovery_attempts {
            found.insert(
                Str::from("max_recovery_attempts"),
                Value::from(ladder::CAPACITY_PER_DAY.min(ceiling)),
            );
        }
        if !matches!(self.options.max_chain_seconds, Value::Null) {
            found.insert(
                Str::from("max_chain_seconds"),
                self.options.max_chain_seconds.clone(),
            );
        }
        found
    }

    /// `caps(relaxed)`: (claims a day, seconds between two) for one conversation.
    pub fn caps(&self, relaxed: Option<&str>) -> (f64, f64) {
        match relaxed {
            Some("capacity") => (
                ladder::CAPACITY_PER_DAY as f64,
                ladder::CAPACITY_SPACING as f64,
            ),
            // v0.6.22 (#59): a verified reset's day, the spacing kept.
            Some("reset") => (
                ladder::RESET_PER_DAY as f64,
                self.options.thread_cooldown_seconds,
            ),
            _ => (
                self.options.max_submissions_per_thread_per_day,
                self.options.thread_cooldown_seconds,
            ),
        }
    }

    /// `recovers(category)`: whether the user has left this category of failure switched on.
    pub fn recovers(&self, category: &str) -> bool {
        match &self.options.recoverable_categories {
            None => true,
            Some(_) if !policy::CONFIGURABLE_CATEGORIES.contains(&category) => true,
            Some(allowed) => allowed.contains(category),
        }
    }

    /// `delay_for(attempt)`: the configured wait before the next attempt at a transient failure - the ladder's step as
    /// it was given (`int` or `float`).
    pub fn delay_for(&self, attempt: i64) -> Value {
        if self.options.retry_ladder.is_empty() {
            let index = attempt
                .saturating_sub(1)
                .clamp(0, TRANSIENT_BACKOFF.len() as i64 - 1);
            return Value::from(TRANSIENT_BACKOFF[index as usize]);
        }
        let ladder = &self.options.retry_ladder;
        ladder[attempt.saturating_sub(1).clamp(0, ladder.len() as i64 - 1) as usize].clone()
    }

    /// `first_delay(category)`: Codex already retried a rate limit, so its first wait is a minute at least
    /// (`max(60, delay)`: the step only where it is more than 60).
    pub fn first_delay(&self, category: &str) -> Value {
        let delay = self.delay_for(1);
        if category == "rate_limit_transient"
            && !py::arithmetic(&delay).is_some_and(|seconds| seconds > 60.0)
        {
            return Value::from(60);
        }
        delay
    }

    /// `quiet_until(now)`: the end of the quiet hours `now` falls in, or None.
    pub fn quiet_until(&self, now: f64) -> Py<Option<f64>> {
        let now = Value::Float(now);
        if self.more_quiet.is_empty() {
            return quiet::quiet_until(&now, &self.values(), self.local.as_ref());
        }
        let mut ends = Vec::new();
        for source in std::iter::once(self.values()).chain(self.more_quiet.iter().cloned()) {
            if let Some(end) = quiet::quiet_until(&now, &source, self.local.as_ref())? {
                ends.push(end);
            }
        }
        Ok(ends.into_iter().reduce(f64::max))
    }

    /// `errand_held()`: what holds back the one write of P8's errand beyond the store's guard.
    pub fn errand_held(&self) -> Py<bool> {
        Ok(self.managed.disable_auto_resume
            || truthy(get(&self.policy_values, "observe_only"))
            || self.quiet_until(self.now())?.is_some())
    }

    /// `tier(thread_id)`: the tier a conversation has: its own, or the default's.
    pub fn tier(&self, thread_id: &str) -> Py<Value> {
        let own = self.store.thread_tier(thread_id)?;
        Ok(policy::tier_of(&self.values(), &own))
    }

    /// `allowed(row)`: consent, as the last look before a send asks it again.
    pub fn allowed(&self, row: &Row) -> Py<bool> {
        let settings = self.store.settings()?;
        Ok(truthy(get(&settings, "enabled"))
            && self.store.thread_enabled(&py::s(row, "thread_id"))?
            && !truthy(get(row, "cancel_requested"))
            && !self.observing(&settings)
            && matches!(get(row, "hold"), Value::Null))
    }

    /// `observing(settings)`: Observe only - the state's switch, or the setting it is written from.
    pub fn observing(&self, settings: &Row) -> bool {
        truthy(get(settings, "observe_only")) || truthy(get(&self.policy_values, "observe_only"))
    }

    /// `observes(row, vector)`: a record whose consent was refused only for Observe only.
    pub fn observes(row: &Row, consent: &(String, String)) -> bool {
        consent.1 == OBSERVE_ONLY && matches!(get(row, "hold"), Value::Null)
    }

    /// `admission(thread_id, now)`: the hold an interruption of this conversation is detected with (v0.6.11).
    pub fn admission(&mut self, thread_id: &str, now: f64) -> Py<Value> {
        let values = self.values();
        if py::text(get(&self.policy_values, "new_conversation_policy")) == Some("notify_only") {
            self.store
                .enrol_conversation(thread_id, "notify_only", now)?;
        }
        let hold = hold_for_tier(&self.tier(thread_id)?);
        if !matches!(hold, Value::Null) || !projects::asks(&values) {
            return Ok(hold);
        }
        let key = match self.source.project_key(thread_id) {
            Ok(Some(key)) => Value::from(key.as_str()),
            _ => Value::Null,
        };
        Ok(projects::hold_for(&values, &key).map_or(Value::Null, Value::from))
    }
}
