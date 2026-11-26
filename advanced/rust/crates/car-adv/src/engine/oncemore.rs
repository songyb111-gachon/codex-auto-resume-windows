//! `once_more_when_unsure`'s code (seat S7.2e1; `engine/oncemore.py`): at P7, RESEND for an uncertain submission core
//! could send once more, that this edition never resent and no channel paid for.

use car_config::Paths;
use car_machine::json::Value;
use car_policy::plug::Alternative;

use crate::capabilities::{Binding, Code, Raised, Said, Spoke};

pub const CAPABILITY: &str = "once_more_when_unsure";
pub const UNKNOWN: &str = "submission_unknown";
pub const WINDOW: (f64, f64) = (900.0, 6.0 * 3600.0);

/// `claimed_at(record)`: when the send core holds now was claimed - Ok(None) where it cannot be read, Err where Python's
/// `math.isfinite` raises (an int too large for a float: the caller's try takes it).
pub fn claimed_at(record: &Value) -> Result<Value, ()> {
    let at = match record {
        Value::Object(map) => map.get("last_claim_at").cloned().unwrap_or(Value::Null),
        _ => return Ok(Value::Null),
    };
    match &at {
        Value::Float(number) if number.is_finite() => Ok(at),
        Value::Float(_) => Ok(Value::Null),
        Value::Int(int) => {
            // `float(int)` overflows past about 1.8e308 (309 digits and more): OverflowError.
            if int.as_i64().is_some() || int.to_string().parse::<f64>().is_ok_and(f64::is_finite) {
                Ok(at)
            } else {
                Err(())
            }
        }
        _ => Ok(Value::Null),
    }
}

/// `resendable(record, now)`: whether core could send `record` once more now (`machine.resend_candidate`).
pub fn resendable(record: &Value, now: f64) -> bool {
    let Value::Object(map) = record else {
        return false;
    };
    if !car_machine::pyval::eq(
        map.get("state").unwrap_or(&Value::Null),
        &Value::Str(UNKNOWN.into()),
    ) {
        return false;
    }
    car_policy::classify::gates::resend_candidate(map, now, WINDOW)
}

/// `OnceMore(paths)`: its hook at P7, bound to the runtime's clock and the two reads it asks.
pub struct OnceMore {
    pub paths: Paths,
    binding: Option<Binding>,
}

impl Code for OnceMore {
    fn bind(&mut self, binding: Binding) -> Option<Result<(), Raised>> {
        self.binding = Some(binding);
        Some(Ok(()))
    }

    /// P7: RESEND, or DEFER for everything else (a state that cannot be read resends nothing).
    fn schedule(&mut self, record: &Value, _due: &Value) -> Spoke {
        let Some(binding) = &self.binding else {
            return Ok(Said::Defer);
        };
        let answer = binding.with(|scoped| {
            if !resendable(record, scoped.now()) {
                return false;
            }
            let key = match record {
                Value::Object(map) => map.get("interruption_id").cloned().unwrap_or(Value::Null),
                _ => Value::Null,
            };
            match scoped.resent(&key) {
                Ok(true) => return false,
                Ok(false) => {}
                Err(_) => return false,
            }
            let Ok(at) = claimed_at(record) else {
                return false;
            };
            matches!(scoped.channel_paid(&key, &at), Ok(false))
        });
        Ok(if answer == Some(true) {
            Said::Word(Alternative::Resend)
        } else {
            Said::Defer
        })
    }
}

/// `make(paths)`.
pub fn make(paths: &Paths) -> Option<Box<dyn Code>> {
    Some(Box::new(OnceMore {
        paths: paths.clone(),
        binding: None,
    }))
}
