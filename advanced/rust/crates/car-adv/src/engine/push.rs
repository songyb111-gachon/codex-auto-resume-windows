//! `engine/push.py` (seat S7.3b): send notices to your phone or inbox (push_notices).
//!
//! At P20 core tells the plug of each notice it hands to the card or the toast - its kind, its category word, its
//! record's place in Pending and when. Here that kind is mapped to a closed event ([`event_of`]; a kind not in the map
//! is not pushed), held to the events the person picked (a bit set in [`EVENTS`]' order) and to the channels switched
//! on, and written to the outbox, one row a channel - only while it stands on and recovery is not paused, and only as
//! far as the outbox's hour leaves room. Watched, nothing is written: the answer says it would have been pushed. At P8
//! the errand starts the courier where a row waits (at most once a minute).

use std::sync::Arc;

use car_config::Paths;
use car_machine::json::Value;
use car_policy::plug::{Errand, Guards, HookFailed, Point, View};

use crate::capabilities::{Binding, Code, Raised, Said, Spoke};
use crate::courier::outbox;
use crate::vocabulary::{CourierChannel, CourierEvent};

pub const CAPABILITY: &str = "push_notices";
pub const USAGE_LIMIT: &str = "usage_limit";
pub const ON: i64 = 1;
pub const OFF: i64 = 2;

/// `EVENTS`: the events a person may pick, in the bit set's order (the test notice is the card's, never picked).
pub fn events() -> Vec<CourierEvent> {
    CourierEvent::ALL
        .iter()
        .copied()
        .filter(|event| *event != CourierEvent::Test)
        .collect()
}

/// `bit(event)`.
pub fn bit(event: CourierEvent) -> i64 {
    let at = events().iter().position(|each| *each == event).unwrap_or(0);
    1 << at
}

/// `DEFAULT_EVENTS`.
pub fn default_events() -> i64 {
    [
        CourierEvent::UsageLimitDetected,
        CourierEvent::Recovered,
        CourierEvent::Failed,
        CourierEvent::NeedsYou,
    ]
    .into_iter()
    .map(bit)
    .sum()
}

/// `KINDS[kind]`: the notifier's kinds as the events they are.
fn kind_event(kind: &str) -> Option<CourierEvent> {
    match kind {
        "resumed" => Some(CourierEvent::Recovered),
        "failed" | "stopped" => Some(CourierEvent::Failed),
        "needs_you" => Some(CourierEvent::NeedsYou),
        "memory_stopped" => Some(CourierEvent::StoppedUnexpectedly),
        "restarted" => Some(CourierEvent::Restarted),
        "update_offered" => Some(CourierEvent::UpdateOffered),
        _ => None,
    }
}

/// `event_of(facts)`: the closed event of a notice core told of, or None.
pub fn event_of(facts: &Value) -> Option<CourierEvent> {
    let Value::Object(facts) = facts else {
        return None;
    };
    let kind = match facts.get("kind") {
        Some(Value::Str(kind)) => kind.as_str()?,
        _ => return None,
    };
    if kind == "interruption" {
        let category = facts.get("category").and_then(crate::state::py::text);
        return (category == Some(USAGE_LIMIT)).then_some(CourierEvent::UsageLimitDetected);
    }
    kind_event(kind)
}

/// `picked(bits, event)`.
pub fn picked(bits: &Value, event: CourierEvent) -> bool {
    match bits {
        Value::Int(bits) => {
            bits.as_i64().is_some_and(|bits| bits & bit(event) != 0)
                || bits.as_i64().is_none() && false
        }
        _ => false,
    }
}

/// Whether recovery is paused (`report.records.paused`: None where it cannot be told), and how the courier is started
/// (`launch.start_due(paths, now)`): the seams a test fills.
pub type Paused = Arc<dyn Fn(&Paths) -> Option<bool> + Send + Sync>;
pub type Launch = Arc<dyn Fn(&Paths, f64) -> bool + Send + Sync>;

/// `PushNotices(paths)`.
pub struct PushNotices {
    pub paths: Paths,
    binding: Option<Binding>,
    paused: Paused,
    launch: Launch,
}

struct StartErrand {
    paths: Paths,
    now: f64,
    launch: Launch,
}

impl Errand for StartErrand {
    fn run(&self, _view: &dyn View, _guards: &mut Guards<'_>) -> Result<Value, HookFailed> {
        (self.launch)(&self.paths, self.now);
        Ok(Value::Null)
    }
}

impl PushNotices {
    pub fn new(paths: Paths, paused: Paused, launch: Launch) -> PushNotices {
        PushNotices {
            paths,
            binding: None,
            paused,
            launch,
        }
    }
}

impl Code for PushNotices {
    fn bind(&mut self, binding: Binding) -> Option<Result<(), Raised>> {
        self.binding = Some(binding);
        Some(Ok(()))
    }

    /// P20: the notice written to the outbox for each channel switched on, while on; NOTICE - what it did or would have
    /// done - or DEFER where it is not one to push.
    fn notice(&mut self, facts: &Value) -> Spoke {
        let Some(binding) = &self.binding else {
            return Ok(Said::Defer);
        };
        let Some(event) = event_of(facts) else {
            return Ok(Said::Defer);
        };
        let paths = self.paths.clone();
        let paused = self.paused.clone();
        let answer = binding.with(|scoped| -> Result<Said, Raised> {
            let options = scoped
                .options()
                .map_err(|error| Raised::new(error.class()))?;
            if !picked(options.get("push_events").unwrap_or(&Value::Null), event) {
                return Ok(Said::Defer);
            }
            let channels: Vec<Value> = CourierChannel::ALL
                .iter()
                .filter(|channel| {
                    crate::state::sql::py_eq(
                        options.get(channel.as_str()).unwrap_or(&Value::Null),
                        &Value::from(ON),
                    )
                })
                .map(|channel| Value::from(channel.as_str()))
                .collect();
            if channels.is_empty() {
                return Ok(Said::Defer);
            }
            if !scoped.armed(&Value::from(CAPABILITY)) {
                return Ok(Said::Value(Value::from(Point::Notice.as_str())));
            }
            if paused(&paths) != Some(false) {
                return Ok(Said::Defer);
            }
            let Value::Object(facts) = facts else {
                return Ok(Said::Defer);
            };
            let category = match facts.get("category") {
                Some(Value::Str(text)) => Value::Str(text.clone()),
                _ => Value::Null,
            };
            let at = match facts.get("at") {
                Some(at @ (Value::Int(_) | Value::Float(_))) => {
                    crate::state::py::as_f64(at).unwrap_or(f64::NAN)
                }
                _ => scoped.now(),
            };
            let task = outbox::alias(facts.get("alias_index").unwrap_or(&Value::Null));
            let written = scoped
                .outbox()
                .enqueue(
                    &channels,
                    &Value::from(event.as_str()),
                    &category,
                    &task,
                    at,
                )
                .map_err(|error| Raised::new(error.class()))?;
            Ok(if written != 0 {
                Said::Value(Value::from(Point::Notice.as_str()))
            } else {
                Said::Defer
            })
        });
        answer.unwrap_or(Ok(Said::Defer))
    }

    /// P8: the courier started where a row of the outbox waits (at most once a minute).
    fn tick(&mut self, _view: &dyn View) -> Spoke {
        let Some(binding) = &self.binding else {
            return Ok(Said::Defer);
        };
        let found = binding.with(|scoped| {
            let now = scoped.now();
            match scoped.outbox().waiting(now) {
                Ok(true) => Some(now),
                _ => None,
            }
        });
        Ok(match found.flatten() {
            Some(now) => Said::Errand(Box::new(StartErrand {
                paths: self.paths.clone(),
                now,
                launch: self.launch.clone(),
            })),
            None => Said::Defer,
        })
    }
}

/// `make(paths)`.
pub fn make(paths: &Paths) -> Option<Box<dyn Code>> {
    Some(Box::new(PushNotices::new(
        paths.clone(),
        Arc::new(|paths: &Paths| crate::report::reading::paused(paths)),
        Arc::new(|paths: &Paths, now: f64| {
            crate::courier::launch::start_due(paths, Some(now), &[])
        }),
    )))
}
