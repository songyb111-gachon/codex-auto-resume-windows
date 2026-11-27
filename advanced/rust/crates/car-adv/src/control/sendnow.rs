//! `control/sendnow.py` (seat S7.3a): Send now - one waiting recovery a person chose, sent at the watcher's next look
//! (v0.6.14). The request (`request`, the bridge's advanced-send-now) is a FORCE_ONCE override of that record, renewed
//! by a second click, that lapses after LIFETIME; the hook at P7 answers SEND_NOW only for a record core holds as
//! waiting with such a request made since the capability last stood where it stands ([`fresh`], which the claim
//! ledger checks again: `ledger.rs`).

use car_config::Paths;
use car_machine::domain::ids;
use car_machine::json::Value;
use car_policy::plug::Alternative;

use super::resets::{field, is, object, text};
use crate::capabilities::{Binding, Code, Raised, Said, Spoke};
use crate::runtime::Runtime;
use crate::vocabulary::{ArmingState, OverrideKind, Refusal};

pub const CAPABILITY: &str = "send_now";
/// How long a request stands, in seconds.
pub const LIFETIME: i64 = 900;
pub const REQUESTED: &str = "requested";

/// `fresh(override, since, now)`: whether a FORCE_ONCE `override` is one a send may still use at `now` - unused,
/// younger than LIFETIME and made at or after `since`. Pure.
pub fn fresh(found: &Value, since: &Value, now: f64) -> bool {
    let Value::Object(_) = found else {
        return false;
    };
    if !matches!(field(found, "used_at"), Value::Null) {
        return false;
    }
    if !is(&field(found, "kind"), OverrideKind::ForceOnce.as_str()) {
        return false;
    }
    let made = field(found, "created_at");
    let numbers = [&made, since]
        .iter()
        .all(|value| matches!(value, Value::Int(_) | Value::Float(_)));
    if !numbers {
        return false;
    }
    let (Some(made), Some(since)) = (super::resets::number_of(&made), super::resets::number_of(since)) else {
        return false;
    };
    made >= since && (0.0..LIFETIME as f64).contains(&(now - made))
}

/// `fresh` over the three columns the claim ledger reads (`kind, created_at, used_at`).
pub fn fresh_columns(kind: &Value, created_at: &Value, used_at: &Value, since: &Value, now: f64) -> bool {
    let found = object(vec![
        ("kind", kind.clone()),
        ("created_at", created_at.clone()),
        ("used_at", used_at.clone()),
    ]);
    fresh(&found, since, now)
}

/// `wake(paths)`: wake the watcher, as Retry now does (core's control/actions.py); Err where the event cannot be
/// made, as the reference raises.
pub fn wake(paths: &Paths) -> Result<bool, ()> {
    let name = &paths.state_dir;
    car_platform::sync::WakeEvent::new(name)
        .map(|found| found.signal())
        .map_err(|_| ())
}

/// `request(runtime, interruption_id)`: advanced-send-now.
pub fn request(runtime: &Runtime, interruption_id: &Value) -> super::resets::Result<Value> {
    let refusal = |refusal: Refusal| Ok(super::resets::refusal(refusal));
    if !ids::is_interruption_id(interruption_id, false) {
        return refusal(Refusal::InvalidRequest);
    }
    if runtime.registry.get(CAPABILITY).is_none() {
        return refusal(Refusal::UnknownCapability);
    }
    if runtime.states(true, &[]).state_of(CAPABILITY) != ArmingState::Armed {
        return refusal(Refusal::NotOn);
    }
    let now = runtime.now();
    let at = Value::Float(now);
    let wrote = super::resets::call(
        runtime,
        "renew_override",
        &[
            interruption_id.clone(),
            text(CAPABILITY),
            text(OverrideKind::ForceOnce.as_str()),
        ],
        &[("at", at.clone())],
    )
    .and_then(|_| {
        super::resets::call(
            runtime,
            "counted",
            &[text(CAPABILITY), text(REQUESTED)],
            &[("at", at)],
        )
    });
    match wrote {
        Ok(_) => {}
        Err(error) if error.is_state() => return refusal(Refusal::StateUnavailable),
        Err(error) => return Err(error),
    }
    let _ = wake(&runtime.paths);
    Ok(object(vec![
        ("done", Value::Bool(true)),
        ("refusal", Value::Null),
        ("expires_at", Value::Float(now + LIFETIME as f64)),
    ]))
}

/// `SendNow(paths)`: the capability's code, its hook at P7.
pub struct SendNow {
    pub paths: Paths,
    binding: Option<Binding>,
}

impl Code for SendNow {
    fn bind(&mut self, binding: Binding) -> Option<Result<(), Raised>> {
        self.binding = Some(binding);
        Some(Ok(()))
    }

    /// P7: SEND_NOW for a record core holds as waiting that a person asked to send now, with a request still fresh.
    fn schedule(&mut self, record: &Value, _due: &Value) -> Spoke {
        let Some(binding) = &self.binding else {
            return Ok(Said::Defer);
        };
        let Value::Object(_) = record else {
            return Ok(Said::Defer);
        };
        let key = field(record, "interruption_id");
        if !super::resets::among(
            &field(record, "state"),
            car_machine::vocab_gen::domain_states::WAITING,
        ) || !ids::is_interruption_id(&key, false)
        {
            return Ok(Said::Defer);
        }
        let answer = binding.with(|scoped| {
            let asked = scoped.request(&key).ok()?;
            let since = scoped.since().ok()?;
            let now = scoped.now();
            let asked = asked.map_or(Value::Null, Value::Object);
            Some(fresh(&asked, &since, now))
        });
        Ok(if answer.flatten() == Some(true) {
            Said::Word(Alternative::SendNow)
        } else {
            Said::Defer
        })
    }
}

/// `make(paths)`: the capability's factory.
pub fn make(paths: &Paths) -> Option<Box<dyn Code>> {
    Some(Box::new(SendNow {
        paths: paths.clone(),
        binding: None,
    }))
}
