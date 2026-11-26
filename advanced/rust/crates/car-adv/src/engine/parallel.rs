//! `parallel_dispatch`'s code (seat S7.2e1; `engine/parallel.py`): how many sends may wait for their receipts at once
//! (P12) - the person's Workers option, 2 by default, and 2 at most until MQ passed on the Codex in force.

use car_config::Paths;
use car_machine::json::Value;

use crate::capabilities::{Binding, Code, Raised, Said, Spoke};
use crate::vocabulary::{Measurement, OptionKey};

pub const CAPABILITY: &str = "parallel_dispatch";
pub const WORKERS: [i64; 7] = [2, 3, 4, 5, 6, 7, 8];
pub const DEFAULT_WORKERS: i64 = 2;
/// Until MQ passes for the Codex in force, no more than this many at once (the narrowed route; never a refusal, K6).
pub const UNMEASURED_WORKERS: i64 = 2;

/// `value in choices` of a tuple of ints, as Python's `in` compares (`2.0 in (2, 3)` and `True in (1,)` are true).
pub fn chosen_in(value: &Value, choices: &[i64]) -> bool {
    choices
        .iter()
        .any(|choice| car_machine::pyval::eq(value, &Value::from(*choice)))
}

/// `options().get(key, default)`, then `chosen if chosen in choices else default` - the default also where the state
/// cannot be read (`Err`).
pub fn option_in(
    options: Result<crate::state::sql::Row, ()>,
    key: OptionKey,
    choices: &[i64],
    default: i64,
) -> Value {
    let chosen = match options {
        Ok(row) => row
            .get(key.as_str())
            .cloned()
            .unwrap_or(Value::from(default)),
        Err(()) => Value::from(default),
    };
    if chosen_in(&chosen, choices) {
        chosen
    } else {
        Value::from(default)
    }
}

/// `min(a, b)` as Python answers it: the first of two equal values.
fn py_min(a: Value, b: Value) -> Value {
    if car_machine::pyval::less(&b, &a).unwrap_or(false) {
        b
    } else {
        a
    }
}

/// `ParallelDispatch(paths)`: its hook at P12, bound to its view of the state.
pub struct ParallelDispatch {
    pub paths: Paths,
    binding: Option<Binding>,
}

impl Code for ParallelDispatch {
    fn bind(&mut self, binding: Binding) -> Option<Result<(), Raised>> {
        self.binding = Some(binding);
        Some(Ok(()))
    }

    /// P12: the Workers option, held to 2 until MQ passed for the Codex in force; DEFER with fewer than two records
    /// due, or a state that cannot be read.
    fn partition(&mut self, records: &Value) -> Spoke {
        let Some(binding) = &self.binding else {
            return Ok(Said::Defer);
        };
        let Value::Array(items) = records else {
            return Ok(Said::Defer);
        };
        if items.len() < 2 {
            return Ok(Said::Defer);
        }
        let read = binding.with(|scoped| {
            let options = scoped.options().map_err(|_| ())?;
            let measured = scoped.passed(&Value::Str(Measurement::Mq.as_str().into()));
            Ok::<_, ()>((options, measured))
        });
        let Some(Ok((options, measured))) = read else {
            return Ok(Said::Defer);
        };
        let chosen = option_in(Ok(options), OptionKey::Workers, &WORKERS, DEFAULT_WORKERS);
        Ok(Said::Value(if measured {
            chosen
        } else {
            py_min(chosen, Value::from(UNMEASURED_WORKERS))
        }))
    }
}

/// `make(paths)`.
pub fn make(paths: &Paths) -> Option<Box<dyn Code>> {
    Some(Box::new(ParallelDispatch {
        paths: paths.clone(),
        binding: None,
    }))
}
