//! `engine/capacity.py` (seat S7.2d): short retries when Codex is at capacity - the advanced edition's answer at P17 and
//! P3 (v0.6.14). It answers CAPACITY for Codex's own `serverOverloaded`, a `server_5xx` failure, for the hours a person
//! chose (one to 24, two by default) counted on the clock from the task's first failure (core's `chain_started_at`);
//! past them, DEFER, and the standard edition's waits and budgets hold the record again.

use car_config::Paths;
use car_machine::json::Value;
use car_policy::plug::Alternative;

use super::usage::{Bound, field, get_of, is_time, number, raised};
use crate::capabilities::{Binding, Code, Raised, Said, Spoke};

pub const CAPABILITY: &str = "capacity_retry";
pub const CODE: &str = "serverOverloaded";
pub const KIND: &str = "server_5xx";
pub const CEILING_HOURS: [i64; 8] = [1, 2, 3, 4, 6, 8, 12, 24];
pub const DEFAULT_HOURS: i64 = 2;
pub const HOUR: i64 = 3600;

/// `CapacityRetry(paths)`: its hooks at P17 and P3; `bind` gives it its own choices and the runtime's clock.
pub struct CapacityRetry {
    pub paths: Paths,
    bound: Option<Bound>,
}

impl CapacityRetry {
    pub fn new(paths: Paths) -> CapacityRetry {
        CapacityRetry { paths, bound: None }
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

    /// `_within(started)`: whether a task that first failed at `started` is still inside the time the person chose.
    fn within(&self, started: &Value) -> Result<bool, Raised> {
        let mut hours = Value::from(DEFAULT_HOURS);
        if let Some(bound) = &self.bound
            && let Some(read) = bound.with(|scoped| scoped.options())
        {
            let options = read.map_err(|error| raised(&error))?;
            if let Some(found) = options.get("ceiling_hours") {
                hours = found.clone();
            }
        }
        if !is_time(started) {
            return Ok(false);
        }
        let Some(hours) = number(&hours) else {
            return Err(Raised::new("TypeError"));
        };
        let started = number(started).unwrap_or(0.0);
        Ok(self.now() - started < hours * HOUR as f64)
    }

    fn capacity_or_defer(within: bool) -> Said {
        if within {
            Said::Word(Alternative::Capacity)
        } else {
            Said::Defer
        }
    }
}

impl Code for CapacityRetry {
    fn bind(&mut self, binding: Binding) -> Option<Result<(), Raised>> {
        self.bound = Some(Bound::of(binding));
        Some(Ok(()))
    }

    /// P17: CAPACITY for Codex at capacity, while its task is inside the time chosen - a first failure always is;
    /// DEFER for anything else.
    fn admission(&mut self, failure: &Value) -> Spoke {
        let category = get_of(failure, "category")?;
        if !super::usage::is_word(category, KIND)
            || !super::usage::is_word(field(failure, "code"), CODE)
        {
            return Ok(Said::Defer);
        }
        let chain = field(failure, "chain");
        if matches!(chain, Value::Null) {
            return Ok(Said::Word(Alternative::Capacity));
        }
        let started = match chain {
            Value::Object(_) => field(chain, "chain_started_at"),
            _ => &Value::Null,
        };
        Ok(Self::capacity_or_defer(self.within(started)?))
    }

    /// P3: at known_failure, CAPACITY again for a record it took up, while its task is inside the time chosen. Every
    /// other gate is core's.
    fn gate(&mut self, name: &Value, record: &Value, _facts: &Value) -> Spoke {
        if !super::usage::is_word(name, "known_failure") {
            return Ok(Said::Defer);
        }
        if !super::usage::is_word(get_of(record, "category")?, KIND) {
            return Ok(Said::Defer);
        }
        Ok(Self::capacity_or_defer(
            self.within(field(record, "chain_started_at"))?,
        ))
    }
}

/// `make(paths)`: the capability's code for one installation.
pub fn make(paths: &Paths) -> Option<Box<dyn Code>> {
    Some(Box::new(CapacityRetry::new(paths.clone())))
}
