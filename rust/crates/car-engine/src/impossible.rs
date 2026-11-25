//! Whether recovery cannot work here (v0.6.26, the update-resilience proposals 1 and 3): a judge of the watcher's own
//! looks (`engine/impossible.py`).
//!
//! Each look of the watcher is put here as a handful of facts it already has, and when one of the contradictions has
//! held long enough, one word says so to a person. It never sends, never holds anything back and never decides that a
//! conversation is open. Pure: the facts are handed in, and the clock is the caller's.

use std::collections::{BTreeMap, BTreeSet};

use car_machine::json::Value;
use car_machine::pyval;
pub use car_machine::vocab_gen::domain_public::{DETECTION_RULES, RECOVERY_RULES, WORDS};

use crate::py::{field, text};

/// How long a recovery rule holds before it is said, and (d)'s.
pub const HOLD_SECONDS: f64 = 600.0;
pub const USAGE_HOLD_SECONDS: f64 = 1800.0;
/// Looks further apart than this start the count again.
pub const GAP_SECONDS: f64 = 300.0;
/// The fewest looks a recovery rule must hold on; and the ticks running a detection rule must.
pub const LOOKS: i64 = 5;
pub const TICKS: i64 = 3;
/// How often the watcher looks for the recovery rules.
pub const LOOK_EVERY_SECONDS: f64 = 60.0;

/// The reasons each recovery rule reads on a waiting record.
pub const ELSEWHERE_REASONS: &[&str] = &["held_by_other_session", "loaded_state_unknown"];
pub const NOT_LOADED_REASONS: &[&str] = &["notLoaded"];
pub const LOCKS_UNREAD_REASONS: &[&str] = &["notLoaded", "loaded_state_unknown"];
pub const USAGE_BROKEN_REASONS: &[&str] = &[
    "usage_probe_broken_answer",
    "usage_probe_broken_request",
    "usage_probe_broken_start",
];

const USAGE_BROKEN: &[(&str, &str)] = &[
    ("protocol_home_mismatch", "usage_probe_broken_answer"),
    ("protocol_platform_mismatch", "usage_probe_broken_answer"),
    ("protocol_reply_unknown", "usage_probe_broken_answer"),
    ("protocol_method_unknown", "usage_probe_broken_request"),
    ("protocol_unavailable", "usage_probe_broken_start"),
    ("protocol_timeout", "usage_probe_broken_start"),
];
pub const USAGE_METHOD: &str = "account/rateLimits/read";

fn item(value: &Value, index: usize) -> Option<&Value> {
    match value {
        Value::Array(items) => items.get(index),
        _ => None,
    }
}

/// `usage_reason(limits, results)`: the reason a record waits on a usage read that said neither available nor not.
pub fn usage_reason(limits: &Value, results: &Value) -> String {
    let reason = field(limits, "reason").ok().and_then(text);
    if reason == Some("usage_snapshot_unknown") {
        return "usage_probe_broken_answer".into();
    }
    let Value::Object(results) = results else {
        return "usage_unknown".into();
    };
    if reason != Some("usage_probe_unavailable") {
        return "usage_unknown".into();
    }
    let mut own = results.get(USAGE_METHOD).cloned().unwrap_or(Value::Null);
    if let Some(start) = results.get("initialize")
        && !matches!(start, Value::Null)
    {
        let not_ok = item(start, 0).is_none_or(|first| !pyval::is(first, "ok"));
        let later = matches!(own, Value::Null)
            || match (item(start, 1), item(&own, 1)) {
                (Some(a), Some(b)) => pyval::greater(a, b).unwrap_or(false),
                _ => false,
            };
        if not_ok && later {
            own = start.clone();
        }
    }
    let word = match &own {
        Value::Array(items) => items.first().and_then(text),
        _ => None,
    };
    word.and_then(|word| USAGE_BROKEN.iter().find(|(key, _)| *key == word))
        .map_or("usage_unknown", |(_, reason)| reason)
        .to_owned()
}

/// What one look read, for the recovery rules.
pub struct Look<'a> {
    pub matched: bool,
    pub server: Option<i64>,
    pub reasons: &'a BTreeSet<String>,
    pub lock_holders: &'a [i64],
    pub database_holders: Option<&'a [i64]>,
    pub locks_folder: Option<bool>,
    pub older_holders: &'a [Vec<i64>],
}

/// `recovery_facts(...)`: {rule: True | False | None} for one look; None is "not judged".
pub fn recovery_facts(look: &Look) -> BTreeMap<&'static str, Option<bool>> {
    let mut facts = BTreeMap::new();
    let (Some(server), Some(holders), true) = (look.server, look.database_holders, look.matched)
    else {
        for rule in &RECOVERY_RULES[..3] {
            facts.insert(*rule, None);
        }
        return facts;
    };
    let holds = holders.contains(&server);
    let any_reason = |group: &[&str]| {
        look.reasons
            .iter()
            .any(|reason| group.contains(&reason.as_str()))
    };
    let elsewhere = any_reason(ELSEWHERE_REASONS)
        && !holds
        && look
            .lock_holders
            .iter()
            .any(|pid| *pid != server && holders.contains(pid));
    let unread = any_reason(LOCKS_UNREAD_REASONS) && holds && look.locks_folder == Some(false);
    let stale = !holds && look.older_holders.iter().any(|pids| pids.contains(&server));
    facts.insert("held_elsewhere", Some(elsewhere));
    facts.insert("locks_unread", Some(unread));
    facts.insert("stale_database", Some(stale));
    facts
}

/// The watcher's judge of its own looks: `look` for the recovery rules, `tick` for the detection rules, and `word`.
#[derive(Debug, Default)]
pub struct Judge {
    since: BTreeMap<&'static str, (f64, i64, f64)>,
    ticks: BTreeMap<&'static str, i64>,
}

impl Judge {
    pub fn new() -> Judge {
        Judge {
            since: BTreeMap::new(),
            ticks: DETECTION_RULES.iter().map(|rule| (*rule, 0)).collect(),
        }
    }

    /// `look(now, app_runs, facts)`: one look for the recovery rules.
    pub fn look(&mut self, now: f64, app_runs: bool, facts: &BTreeMap<&str, Option<bool>>) {
        for rule in RECOVERY_RULES {
            let found = if app_runs {
                facts.get(rule).copied().flatten()
            } else {
                None
            };
            if found != Some(true) {
                self.since.remove(rule);
                continue;
            }
            let (mut first, mut looks, last) =
                self.since.get(rule).copied().unwrap_or((now, 0, now));
            if now - last > GAP_SECONDS || now < last {
                first = now;
                looks = 0;
            }
            self.since.insert(rule, (first, looks + 1, now));
        }
    }

    /// `tick(app_runs, facts)`: one tick for the detection rules.
    pub fn tick(&mut self, app_runs: bool, facts: &BTreeMap<&str, bool>) {
        for rule in DETECTION_RULES {
            let held = app_runs && facts.get(rule).copied() == Some(true);
            let count = self.ticks.entry(rule).or_insert(0);
            *count = if held { *count + 1 } else { 0 };
        }
    }

    /// `word(now)`: "detection_blocked:<rule>" or "recovery_blocked:<rule>", the first of WORDS that holds, or None.
    pub fn word(&self, now: f64) -> Option<String> {
        for rule in DETECTION_RULES {
            if self.ticks.get(rule).copied().unwrap_or(0) >= TICKS {
                return Some(format!("detection_blocked:{rule}"));
            }
        }
        for rule in RECOVERY_RULES {
            let hold = if *rule == "usage_protocol" {
                USAGE_HOLD_SECONDS
            } else {
                HOLD_SECONDS
            };
            if let Some((first, looks, _)) = self.since.get(rule)
                && *looks >= LOOKS
                && now - first >= hold
            {
                return Some(format!("recovery_blocked:{rule}"));
            }
        }
        None
    }
}
