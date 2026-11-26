//! `engine/feed.py` (seat S7.3b): show OpenAI's service status (status_feed).
//!
//! At P8, while a recovery core holds waits in a usage limit or a connection failure, the courier is started with
//! `--feed` once the last reading is FEED_MINUTES old (10, 30 or 60). A word to show, never a reason: nothing here
//! answers at a gate or decides anything.

use std::sync::Arc;

use car_config::Paths;
use car_machine::json::Value;
use car_policy::plug::{Errand, Guards, HookFailed, View};

use crate::capabilities::{Binding, Code, Raised, Said, Spoke};

pub const CAPABILITY: &str = "status_feed";
pub const MINUTES: [i64; 3] = [10, 30, 60];
pub const DEFAULT_MINUTES: i64 = 10;
/// `CATEGORIES`: a usage limit and the connection failures (`failures.USAGE_LIMIT | failures.TRANSIENT`).
pub fn categories() -> Vec<&'static str> {
    let mut found = vec![car_policy::classify::vocab_gen::failures::USAGE_LIMIT];
    found.extend(
        car_policy::classify::vocab_gen::failures::TRANSIENT
            .iter()
            .copied(),
    );
    found
}

/// How the courier is started (`launch.start_due(paths, now, "--feed")`): the seam a test fills.
pub type Launch = Arc<dyn Fn(&Paths, f64) -> bool + Send + Sync>;

/// `StatusFeed(paths)`.
pub struct StatusFeed {
    pub paths: Paths,
    binding: Option<Binding>,
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

/// `_waiting(view)`: whether core holds a recovery waiting in a usage limit or a connection failure.
fn waiting(view: &dyn View) -> bool {
    let wanted = categories();
    match view.records_in(car_machine::vocab_gen::domain_states::WAITING) {
        Ok(rows) => rows.iter().any(|row| match row {
            Value::Object(map) => map
                .get("category")
                .and_then(crate::state::py::text)
                .is_some_and(|category| wanted.contains(&category)),
            _ => false,
        }),
        Err(_) => false,
    }
}

impl StatusFeed {
    pub fn new(paths: Paths, launch: Launch) -> StatusFeed {
        StatusFeed {
            paths,
            binding: None,
            launch,
        }
    }
}

impl Code for StatusFeed {
    fn bind(&mut self, binding: Binding) -> Option<Result<(), Raised>> {
        self.binding = Some(binding);
        Some(Ok(()))
    }

    /// P8: the courier started with `--feed` where the last reading is old enough and a recovery waits for a reason the
    /// page could explain.
    fn tick(&mut self, view: &dyn View) -> Spoke {
        let Some(binding) = &self.binding else {
            return Ok(Said::Defer);
        };
        let due = binding.with(|scoped| -> Result<Option<f64>, ()> {
            let now = scoped.now();
            let options = scoped.options().map_err(|_| ())?;
            let minutes = options
                .get("feed_minutes")
                .cloned()
                .unwrap_or(Value::from(DEFAULT_MINUTES));
            let last = scoped.feed().map_err(|_| ())?;
            let last = last.as_ref().and_then(|row| row.get("checked_at")).cloned();
            if let Some(last @ (Value::Int(_) | Value::Float(_))) = last {
                let last = crate::state::py::as_f64(&last).unwrap_or(f64::NAN);
                // `minutes * 60`: a number the choices kept (anything else is the reference's TypeError: DEFER).
                let window = match &minutes {
                    Value::Int(_) | Value::Float(_) => {
                        crate::state::py::as_f64(&minutes).unwrap_or(f64::NAN) * 60.0
                    }
                    _ => return Err(()),
                };
                if 0.0 <= now - last && now - last < window {
                    return Ok(None);
                }
            }
            Ok(Some(now))
        });
        let Some(Ok(Some(now))) = due else {
            return Ok(Said::Defer);
        };
        if !waiting(view) {
            return Ok(Said::Defer);
        }
        Ok(Said::Errand(Box::new(StartErrand {
            paths: self.paths.clone(),
            now,
            launch: self.launch.clone(),
        })))
    }
}

/// `make(paths)`.
pub fn make(paths: &Paths) -> Option<Box<dyn Code>> {
    Some(Box::new(StatusFeed::new(
        paths.clone(),
        Arc::new(|paths: &Paths, now: f64| {
            crate::courier::launch::start_due(paths, Some(now), &["--feed"])
        }),
    )))
}
