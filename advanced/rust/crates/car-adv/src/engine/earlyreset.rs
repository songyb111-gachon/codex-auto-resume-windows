//! `engine/earlyreset.py` (seat S7.2d): notice a usage limit that lifts early - the advanced edition's answer at P7 and
//! P3 (v0.6.14).
//!
//! At P7, asked by core before a usage-limited record's time, it answers EARLY while a probe is open (one every five
//! minutes, for every waiting record together); at P3 `usage`, which core reaches only when that reading said usage is
//! available, it holds the record on a first yes and lets core go on only on a second yes at least five minutes later.
//! Its memory is the process's; the times it keeps for Pending are stamps (`checked_at`, `available_at`, `found_at`,
//! `lifted_at`), and a person's Retry now or Rescan (`check_asked`) opens the next probe at once.

use car_config::Paths;
use car_machine::json::Value;
use car_policy::plug::Alternative;

use super::usage::{Bound, field, is_time, is_word, number};
use crate::capabilities::{Binding, Code, Raised, Said, Spoke};

/// The waits a record may be looked at early in.
pub const EARLY_STATES: [&str; 2] = ["waiting_reset", "waiting_poll"];
/// Five minutes between two probes, and at least as much between the two answers that lift a limit.
pub const SPACING: f64 = 300.0;
/// A probe's first seconds, in which every waiting record is looked at with it.
pub const WINDOW: f64 = 30.0;
pub const USAGE: &str = "usage";
/// `machine.gate(machine.PASS, machine.PLUGGED)`.
pub const LOOKED_EARLY: [&str; 2] = ["PASS", "plugged"];
pub const USAGE_LIMIT: &str = "usage_limit";

/// `EarlyReset(paths)`: the probe now open, whether it reached the usage gate, the first yes, the last lift and the
/// records released into this probe.
pub struct EarlyReset {
    pub paths: Paths,
    bound: Option<Bound>,
    pub probe_at: Option<f64>,
    pub reached: bool,
    pub first_available_at: Option<f64>,
    pub lifted_at: Option<f64>,
    pub released: Vec<Value>,
}

/// `hash(value)` as a set takes it: a list or a dict is not hashable.
fn hashable(value: &Value) -> Result<(), Raised> {
    match value {
        Value::Array(_) | Value::Object(_) => Err(Raised::new("TypeError")),
        _ => Ok(()),
    }
}

/// `tuple(value or ())` compared with LOOKED_EARLY; TypeError where `value` cannot be iterated.
fn looked_early(value: &Value) -> Result<bool, Raised> {
    if !car_machine::pyval::truthy(value) {
        return Ok(false);
    }
    match value {
        Value::Array(items) => Ok(items.len() == 2
            && is_word(&items[0], LOOKED_EARLY[0])
            && is_word(&items[1], LOOKED_EARLY[1])),
        // A text is a tuple of one-character texts, a dict a tuple of its keys: neither is ("PASS", "plugged").
        Value::Str(_) | Value::Object(_) => Ok(false),
        _ => Err(Raised::new("TypeError")),
    }
}

impl EarlyReset {
    pub fn new(paths: Paths) -> EarlyReset {
        EarlyReset {
            paths,
            bound: None,
            probe_at: None,
            reached: false,
            first_available_at: None,
            lifted_at: None,
            released: Vec::new(),
        }
    }

    /// `bind(scoped)`, from a probe's scope.
    pub fn bind_to(&mut self, bound: Bound) {
        self.bound = Some(bound);
    }

    fn now(&self) -> f64 {
        self.bound
            .as_ref()
            .and_then(|bound| bound.with(|scoped| scoped.now()))
            .unwrap_or_else(crate::state::session::wall_clock)
    }

    /// `_stamp(key, at)`: a time written (`max(1, int(at))`) or taken away; a time that cannot be written changes nothing.
    fn stamp(&self, key: &str, at: Option<f64>) {
        if let Some(bound) = &self.bound {
            bound.with(|scoped| {
                let key = Value::from(key);
                let _ = match at {
                    None => scoped.unstamp(&key),
                    Some(at) => scoped.stamp(&key, &Value::from((at.trunc() as i64).max(1))),
                };
            });
        }
    }

    /// `_asked(opened, now)`: whether a person's click asks for a probe that has not begun since.
    fn asked(&self, opened: Option<f64>, now: f64) -> bool {
        let Some(bound) = &self.bound else {
            return false;
        };
        let asked = match bound.with(|scoped| scoped.stamped(&Value::from("check_asked"))) {
            None => Value::Null,
            Some(Ok(found)) => found,
            Some(Err(_)) => return false,
        };
        if !is_time(&asked) {
            return false;
        }
        let asked = number(&asked).unwrap_or(0.0);
        let since = now - asked;
        (0.0..SPACING + 1.0).contains(&since) && opened.is_none_or(|opened| asked > opened.trunc())
    }

    fn count(&self, code: &str) {
        if let Some(bound) = &self.bound {
            bound.with(|scoped| {
                let _ = scoped.count(&Value::from(code));
            });
        }
    }

    fn released_holds(&self, id: &Value) -> bool {
        self.released
            .iter()
            .any(|held| car_machine::pyval::eq(held, id))
    }
}

impl Code for EarlyReset {
    fn bind(&mut self, binding: Binding) -> Option<Result<(), Raised>> {
        self.bound = Some(Bound::of(binding));
        Some(Ok(()))
    }

    /// P7: EARLY while a probe is open - one begins five minutes after the last - and DEFER for anything else.
    fn schedule(&mut self, record: &Value, eligible_at: &Value) -> Spoke {
        let now = self.now();
        let Value::Object(_) = record else {
            return Ok(Said::Defer);
        };
        let state = field(record, "state");
        let not_before = field(record, "not_before");
        if !is_word(field(record, "category"), USAGE_LIMIT)
            || !EARLY_STATES.iter().any(|word| is_word(state, word))
            || !is_time(eligible_at)
            || number(eligible_at).unwrap_or(0.0) <= now
            || (is_time(not_before) && number(not_before).unwrap_or(0.0) > now)
        {
            return Ok(Said::Defer);
        }
        let opened = self.probe_at;
        if opened.is_none_or(|opened| !(0.0..WINDOW).contains(&(now - opened))) {
            if let Some(opened) = opened
                && (0.0..SPACING).contains(&(now - opened))
                && !self.asked(Some(opened), now)
            {
                return Ok(Said::Defer);
            }
            if !self.reached && self.first_available_at.is_some() {
                self.first_available_at = None;
                self.stamp("available_at", None);
            }
            self.probe_at = Some(now);
            self.reached = false;
            self.released.clear();
            self.stamp("checked_at", Some(now));
            self.stamp("check_asked", None);
        }
        let id = field(record, "interruption_id").clone();
        hashable(&id)?;
        if !self.released_holds(&id) {
            self.released.push(id);
        }
        Ok(Said::Word(Alternative::Early))
    }

    /// `not_taken(record)`: another capability's P7 answer was taken for `record`; it is not one released into this
    /// probe.
    fn not_taken(&mut self, record: &Value) -> Option<Result<(), Raised>> {
        if let Value::Object(_) = record {
            let id = field(record, "interruption_id");
            if let Err(error) = hashable(id) {
                return Some(Err(error));
            }
            self.released
                .retain(|held| !car_machine::pyval::eq(held, id));
        }
        Some(Ok(()))
    }

    /// P3 `usage` for a record it released into this probe: HOLD on a first yes, DEFER on a second at least five
    /// minutes after it. Every other gate, and every record looked at in its own time, is core's.
    fn gate(&mut self, name: &Value, record: &Value, facts: &Value) -> Spoke {
        if !is_word(name, USAGE)
            || !matches!(record, Value::Object(_))
            || !matches!(facts, Value::Object(_))
        {
            return Ok(Said::Defer);
        }
        let id = field(record, "interruption_id");
        hashable(id)?;
        if !self.released_holds(id) || !looked_early(field(facts, "schedule"))? {
            return Ok(Said::Defer);
        }
        let probe_at = self.probe_at;
        if !self.reached {
            self.stamp("found_at", probe_at);
        }
        self.reached = true;
        let Some(first) = self.first_available_at else {
            self.first_available_at = probe_at;
            self.stamp("available_at", probe_at);
            self.count("probed");
            return Ok(Said::Word(Alternative::Hold));
        };
        let Some(probe) = probe_at else {
            return Err(Raised::new("TypeError"));
        };
        if probe - first < SPACING {
            return Ok(Said::Word(Alternative::Hold));
        }
        if self.lifted_at != Some(probe) {
            self.lifted_at = Some(probe);
            self.count("lifted");
            self.stamp("lifted_at", Some(probe));
        }
        Ok(Said::Defer)
    }
}

/// `make(paths)`: the capability's code for one installation.
pub fn make(paths: &Paths) -> Option<Box<dyn Code>> {
    Some(Box::new(EarlyReset::new(paths.clone())))
}
