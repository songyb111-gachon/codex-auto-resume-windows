//! `queue_for_open`'s code (seat S7.2e1b; `engine/foropen.py`): a usage-limited conversation the Codex app does not hold
//! is sent core's ordinary continuation, left in Codex's queue for when the person opens it, for the days they chose
//! (P16's QUEUE_FOR_OPEN).
//!
//! P16 answers QUEUE_FOR_OPEN for a record not queued for opening before (no override yet), and - in core's watch,
//! which hands `queued_since` - keeps one queued while its override is within the Days chosen. Beside an active goal
//! while goal_continuation is on and MQG has not passed, it answers nothing (said once a record in its journal). The
//! goals are read through [`super::goal::GoalLook`] (a goal that cannot be read is none).

use std::collections::BTreeSet;
use std::sync::{Arc, Mutex, PoisonError};

use car_config::Paths;
use car_machine::json::Value;
use car_policy::classify::vocab_gen::failures;
use car_policy::plug::Alternative;

use super::goal::GoalLook;
use crate::capabilities::{Binding, Code, Raised, Said, Spoke};
use crate::state::scoped::Scoped;
use crate::state::sql;
use crate::vocabulary::{GoalStatus, Measurement, OptionKey, OverrideKind};

pub const CAPABILITY: &str = "queue_for_open";
pub const GOAL: &str = "goal_continuation";
/// Why it answered nothing beside an active goal, as its journal says it.
pub const GOAL_UNMEASURED: &str = "goal_unmeasured";
pub const GOAL_TWO_TURNS: &str = "goal_two_turns";
pub const CODES: [&str; 2] = [GOAL_UNMEASURED, GOAL_TWO_TURNS];
/// Records it said that for, forgotten all at once past this many.
pub const NOTED_LIMIT: usize = 4096;
pub const DAYS: [i64; 7] = [3, 4, 5, 6, 7, 14, 30];
pub const DEFAULT_DAYS: i64 = 3;
pub const DAY: f64 = 86400.0;
/// Where core asks P16 for a conversation the running app does not hold (core's engine/delivery.APP_FREE).
pub const APP_FREE: &str = "app_free";

/// `watching(record)`: whether core asks about a continuation already queued for opening (its watch hands
/// `queued_since`), rather than whether to queue one.
pub fn watching(record: &Value) -> bool {
    matches!(record, Value::Object(map) if map.contains_key("queued_since"))
}

fn word(text: &str) -> Value {
    Value::Str(text.into())
}

fn field<'a>(record: &'a Value, name: &str) -> &'a Value {
    static NULL: Value = Value::Null;
    match record {
        Value::Object(map) => map.get(name).unwrap_or(&NULL),
        _ => &NULL,
    }
}

fn is(value: &Value, text: &str) -> bool {
    matches!(value, Value::Str(held) if held.as_str() == Some(text))
}

/// `days if days in DAYS else DEFAULT_DAYS`, as a number of days (`in` is Python's `==`: 3.0 is 3).
fn days_of(days: &Value) -> f64 {
    for each in DAYS {
        if car_machine::pyval::eq(days, &Value::from(each)) {
            return match days {
                Value::Float(number) => *number,
                _ => each as f64,
            };
        }
    }
    DEFAULT_DAYS as f64
}

/// `QueueForOpen(paths, home=None)`.
pub struct QueueForOpen {
    pub paths: Paths,
    binding: Option<Binding>,
    goal: GoalLook,
    noted: Arc<Mutex<BTreeSet<String>>>,
}

impl QueueForOpen {
    pub fn new(paths: Paths, goal: GoalLook) -> QueueForOpen {
        QueueForOpen {
            paths,
            binding: None,
            goal,
            noted: Arc::new(Mutex::new(BTreeSet::new())),
        }
    }

    /// `_active(thread_id)`: whether the conversation's goal is active; one that cannot be read is none.
    fn active(&self, thread: &Value) -> bool {
        matches!(thread, Value::Str(_))
            && (self.goal)(thread).is_some_and(|goal| goal.status == GoalStatus::Active.as_str())
    }

    /// `_for_goal(scoped, record, key)`: whether the conversation's active goal carries it - the goal continuation on,
    /// MQG not passed, the goal active. Said once a record in its journal, with why.
    fn for_goal(&self, scoped: &Scoped<'_>, record: &Value, key: &str) -> bool {
        let mqg = word(Measurement::Mqg.as_str());
        if !scoped.armed(&word(GOAL)) || scoped.passed(&mqg) {
            return false;
        }
        if !self.active(field(record, "thread_id")) {
            return false;
        }
        let failed = scoped.failed(&mqg);
        let mut noted = self.noted.lock().unwrap_or_else(PoisonError::into_inner);
        if !noted.contains(key) {
            if noted.len() >= NOTED_LIMIT {
                noted.clear();
            }
            noted.insert(key.to_owned());
            let _ = scoped.count(&word(if failed {
                GOAL_TWO_TURNS
            } else {
                GOAL_UNMEASURED
            }));
        }
        true
    }

    fn answer(&self, scoped: &Scoped<'_>, record: &Value, key: &Value) -> Said {
        let Value::Str(name) = key else {
            return Said::Defer;
        };
        let name = name.as_str().unwrap_or_default().to_owned();
        let watched = watching(record);
        if !watched && !is(field(record, "holder"), APP_FREE) {
            return Said::Defer;
        }
        if !watched && !is(field(record, "category"), failures::USAGE_LIMIT) {
            return Said::Defer;
        }
        if !watched && self.for_goal(scoped, record, &name) {
            return Said::Defer;
        }
        let Ok(found) = scoped.request(key) else {
            return Said::Defer;
        };
        if !watched {
            return if found.is_some() {
                Said::Defer
            } else {
                Said::Word(Alternative::QueueForOpen)
            };
        }
        let Ok(options) = scoped.options() else {
            return Said::Defer;
        };
        let days = options
            .get(OptionKey::Days.as_str())
            .cloned()
            .unwrap_or(Value::from(DEFAULT_DAYS));
        let now = scoped.now();
        let Some(found) = found else {
            return Said::Defer;
        };
        if !is(
            sql::get(&found, "kind"),
            OverrideKind::QueueForOpen.as_str(),
        ) {
            return Said::Defer;
        }
        let created = match sql::get(&found, "created_at") {
            Value::Int(int) => int.as_i64().unwrap_or(0) as f64,
            Value::Float(number) => *number,
            _ => return Said::Defer,
        };
        if now - created < days_of(&days) * DAY {
            Said::Word(Alternative::QueueForOpen)
        } else {
            Said::Defer
        }
    }
}

impl Code for QueueForOpen {
    fn bind(&mut self, binding: Binding) -> Option<Result<(), Raised>> {
        self.binding = Some(binding);
        Some(Ok(()))
    }

    /// P16: QUEUE_FOR_OPEN to queue a record not queued for opening before, or - in the watch - to keep one queued
    /// while its override is within the Days chosen; DEFER otherwise, and where the state cannot be read.
    fn unloaded(&mut self, record: &Value) -> Spoke {
        let key = field(record, "interruption_id").clone();
        let Some(binding) = &self.binding else {
            return Ok(Said::Defer);
        };
        Ok(binding
            .with(|scoped| self.answer(scoped, record, &key))
            .unwrap_or(Said::Defer))
    }
}

/// `make(paths)`: the capability's code with no goals readable (no Codex home known here).
pub fn make(paths: &Paths) -> Option<Box<dyn Code>> {
    make_with(paths, Arc::new(|_| None))
}

/// `QueueForOpen(paths, home=...)` with an entry point's or a test's own goals.
pub fn make_with(paths: &Paths, goal: GoalLook) -> Option<Box<dyn Code>> {
    Some(Box::new(QueueForOpen::new(paths.clone(), goal)))
}
