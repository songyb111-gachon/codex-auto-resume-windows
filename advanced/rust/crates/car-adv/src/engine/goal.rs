//! `goal_continuation`'s code (seat S7.2e1b; `engine/goal.py`): a conversation's goal Codex paused at a usage limit set
//! active again - at P16 (a route, while the running app does not hold it), P3 (thread_available's hold while the goal
//! carries it on; known_failure's VERIFIED_RESET) and P5 (a channel, where M2b passed for the Codex in force).
//!
//! What it never does: create a goal, touch its words, or decide - every gate, the claim, the pre-send look and the
//! launch guard are core's. Core holds the launch guard around the whole route or send here (car-policy's `Route` and
//! `Channel` take none), so the reference's "consent refused" answer never arises (AUDIT-v0628.md).
//!
//! Its seams ([`GoalWorld`]): the app-server session (`session=`), the goals reader (`home=`: a goal that cannot be read
//! is no goal), M2b's verdict for the Codex in force (`view=`, `measured=`), and the clock.

use std::collections::BTreeMap;
use std::sync::{Arc, Mutex, PoisonError};

use car_config::Paths;
use car_machine::domain::ids;
use car_machine::json::{Map, Str, Value};
use car_policy::classify::failures::reset_verified_value;
use car_policy::classify::vocab_gen::failures;
use car_policy::plug::{Alternative, Channel, Route};

use super::markerfree::{Open, no_session, not_started, prompt_passes, queue_id, text_input};
use crate::capabilities::{Code, Raised, Said, Spoke};
use crate::codex::session::{self, SessionError};
use crate::vocabulary::GoalStatus;

pub const CAPABILITY: &str = "goal_continuation";
pub const SET: &str = "thread/goal/set";
pub const ADD: &str = "thread/queue/add";
/// How long the standard continuation is held back while a conversation's goal is active, from the first time the app
/// was found holding it so.
pub const HOLD_SECONDS: f64 = 600.0;
/// Records remembered for that, forgotten all at once past this many.
pub const SEEN_LIMIT: usize = 4096;
/// Where core asks P16 for a conversation the running app does not hold (core's engine/delivery.APP_FREE).
pub const APP_FREE: &str = "app_free";

/// A conversation's goal as this reads it: its id and its status word.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct GoalSeen {
    pub goal_id: String,
    pub status: String,
}

/// `Goals(home).read(thread_id)`, every failure None (`_goal`: a goal that cannot be read is no goal).
pub type GoalLook = Arc<dyn Fn(&Value) -> Option<GoalSeen> + Send + Sync>;

/// The seams the code is made with.
#[derive(Clone)]
pub struct GoalWorld {
    pub open: Open,
    pub goal: GoalLook,
    /// `_m2b()`: M2b's recorded verdict a pass for the Codex in force (any failure: no).
    pub m2b: Arc<dyn Fn() -> bool + Send + Sync>,
    pub clock: Arc<dyn Fn() -> f64 + Send + Sync>,
}

impl GoalWorld {
    /// What `make(paths)` gives: no session, no goals (no Codex home known here), no M2b, the system clock.
    pub fn bare() -> GoalWorld {
        GoalWorld {
            open: no_session(),
            goal: Arc::new(|_| None),
            m2b: Arc::new(|| false),
            clock: Arc::new(crate::state::session::wall_clock),
        }
    }
}

/// `m2b_passed(view, measured)`: a pass on the very version the Compatibility Registry's view names. `entry` is
/// `measured.get(Measurement.M2B)` as (verdict, version), where it is a pair.
pub fn m2b_passed(version: Option<&str>, entry: Option<(&str, &str)>) -> bool {
    matches!((version, entry), (Some(version), Some((verdict, on))) if verdict == "pass" && on == version)
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

/// `_usage_record(record)`: a usage limit of a conversation with a canonical id.
fn usage_record(record: &Value) -> bool {
    matches!(record, Value::Object(_))
        && is(field(record, "category"), failures::USAGE_LIMIT)
        && ids::is_uuid(field(record, "thread_id"))
}

fn answer(pairs: &[(&str, Value)]) -> Value {
    let mut map = Map::new();
    for (name, value) in pairs {
        map.insert((*name).into(), value.clone());
    }
    Value::Object(map)
}

fn unknown(error: &SessionError) -> Value {
    answer(&[
        ("outcome", word("unknown")),
        (
            "error_code",
            word(if error.text() == "protocol_timeout" {
                "queue_timeout"
            } else {
                "queue_result_unknown"
            }),
        ),
    ])
}

fn result_unknown() -> Value {
    answer(&[
        ("outcome", word("unknown")),
        ("error_code", word("queue_result_unknown")),
    ])
}

fn set_params(thread_id: &str) -> Value {
    answer(&[
        ("threadId", word(thread_id)),
        ("status", word(GoalStatus::Active.as_str())),
    ])
}

/// What the route and the channel do (`resume`, `send`), over the code's seams.
#[derive(Clone)]
pub struct GoalHands {
    world: GoalWorld,
}

impl GoalHands {
    fn goal(&self, thread: &Value) -> Option<GoalSeen> {
        (self.world.goal)(thread)
    }

    /// `_limited(record)`: the goal of `record`'s conversation where it is paused by the usage limit.
    fn limited(&self, record: &Value) -> Option<GoalSeen> {
        if !usage_record(record) {
            return None;
        }
        self.goal(field(record, "thread_id"))
            .filter(|goal| goal.status == GoalStatus::UsageLimited.as_str())
    }

    /// `_opened()`: a session entered, or what core is told (nothing was asked of Codex).
    fn opened(&self) -> Result<Box<dyn session::Channel>, Value> {
        let opened = {
            let mut open = self
                .world
                .open
                .lock()
                .unwrap_or_else(PoisonError::into_inner);
            (open)(CAPABILITY)
        };
        let Ok(mut channel) = opened else {
            return Err(not_started("queue_spawn_failed"));
        };
        if channel.enter().is_err() {
            return Err(not_started("queue_spawn_failed"));
        }
        Ok(channel)
    }

    /// `resume(thread_id, still_unloaded=...)`: the paused goal set active again; never raises.
    pub fn resume(&self, thread_id: &str, still_unloaded: Option<&dyn Fn() -> bool>) -> Value {
        let thread = word(thread_id);
        if !ids::is_uuid(&thread) {
            return not_started("queue_preflight_failed");
        }
        let Some(before) = self
            .goal(&thread)
            .filter(|goal| goal.status == GoalStatus::UsageLimited.as_str())
        else {
            return not_started("queue_preflight_failed");
        };
        let mut channel = match self.opened() {
            Ok(channel) => channel,
            Err(told) => return told,
        };
        let yes = |look: Option<&dyn Fn() -> bool>| look.is_none_or(|look| look());
        if !yes(still_unloaded) {
            channel.exit();
            return not_started("queue_preflight_failed");
        }
        match channel.call(SET, Some(set_params(thread_id))) {
            Ok(_) => {}
            Err(SessionError::Refused) => {
                channel.exit();
                return not_started("queue_preflight_failed");
            }
            Err(error) => {
                if error.method() == Some(SET) {
                    let after = self.goal(&thread);
                    if after.is_none_or(|after| after.status != GoalStatus::Active.as_str()) {
                        channel.exit();
                        return not_started("queue_preflight_failed");
                    }
                }
                channel.exit();
                return unknown(&error);
            }
        }
        channel.exit();
        let after = self.goal(&thread);
        if after.is_none_or(|after| {
            after.goal_id != before.goal_id || after.status != GoalStatus::Active.as_str()
        }) {
            return result_unknown();
        }
        if !yes(still_unloaded) {
            return result_unknown();
        }
        answer(&[("outcome", word("accepted")), ("queue_id", Value::Null)])
    }

    /// `send(thread_id, prompt, client_id=None)`: the goal set active, then the words added to the queue; never
    /// raises.
    pub fn send(&self, thread_id: &str, prompt: &Str, client_id: Option<&str>) -> Value {
        let thread = word(thread_id);
        if !ids::is_uuid(&thread)
            || !prompt_passes(prompt)
            || !client_id.is_none_or(|client| ids::is_uuid(&word(client)))
        {
            return not_started("queue_preflight_failed");
        }
        let client = client_id.map_or_else(car_platform::ipc_pipe::uuid4, str::to_owned);
        let params = answer(&[
            ("threadId", thread.clone()),
            ("input", text_input(prompt)),
            ("clientUserMessageId", word(&client)),
        ]);
        let Some(before) = self
            .goal(&thread)
            .filter(|goal| goal.status == GoalStatus::UsageLimited.as_str())
        else {
            return not_started("queue_preflight_failed");
        };
        let mut channel = match self.opened() {
            Ok(channel) => channel,
            Err(told) => return told,
        };
        let pending = session::submitted(channel.as_mut(), SET, Some(set_params(thread_id)));
        let told = match pending.answer(channel.as_mut()) {
            Err(SessionError::Refused) => Some(not_started("queue_preflight_failed")),
            Err(error) => {
                let after = self.goal(&thread);
                if error.method() == Some(SET)
                    && after.is_some_and(|after| {
                        after.goal_id == before.goal_id
                            && after.status == GoalStatus::UsageLimited.as_str()
                    })
                {
                    Some(not_started("queue_preflight_failed"))
                } else {
                    Some(unknown(&error))
                }
            }
            Ok(_) => {
                let after = self.goal(&thread);
                if after.is_none_or(|after| {
                    after.goal_id != before.goal_id || after.status != GoalStatus::Active.as_str()
                }) {
                    Some(result_unknown())
                } else {
                    None
                }
            }
        };
        if let Some(told) = told {
            channel.exit();
            return told;
        }
        let result = channel.call(ADD, Some(params));
        channel.exit();
        match result {
            Ok(result) => answer(&[
                ("outcome", word("accepted")),
                ("queue_id", queue_id(&result)),
            ]),
            Err(error) => unknown(&error),
        }
    }
}

/// The route core resumes the conversation with (P16).
pub struct GoalRoute(GoalHands);

impl Route for GoalRoute {
    fn resume(
        &self,
        thread_id: &str,
        still_unloaded: Option<&dyn Fn() -> bool>,
        _words: Option<&Str>,
        _client_id: Option<&str>,
    ) -> Value {
        self.0.resume(thread_id, still_unloaded)
    }
}

/// The channel core sends through (P5).
pub struct GoalChannel(GoalHands);

impl Channel for GoalChannel {
    fn send(&self, thread_id: &str, prompt: &Str, client_id: Option<&str>) -> Value {
        self.0.send(thread_id, prompt, client_id)
    }
}

/// `GoalContinuation(paths, session=None, home=None, view=None, measured=None, clock=time.time)`.
pub struct GoalContinuation {
    pub paths: Paths,
    hands: GoalHands,
    seen: Arc<Mutex<BTreeMap<String, f64>>>,
}

impl GoalContinuation {
    pub fn new(paths: Paths, world: GoalWorld) -> GoalContinuation {
        GoalContinuation {
            paths,
            hands: GoalHands { world },
            seen: Arc::new(Mutex::new(BTreeMap::new())),
        }
    }

    fn now(&self) -> f64 {
        (self.hands.world.clock)()
    }
}

impl Code for GoalContinuation {
    /// P16: this is the route for a conversation the running app does not hold, where its goal is paused by the usage
    /// limit; DEFER anywhere else.
    fn unloaded(&mut self, record: &Value) -> Spoke {
        if !matches!(record, Value::Object(_)) || !is(field(record, "holder"), APP_FREE) {
            return Ok(Said::Defer);
        }
        Ok(match self.hands.limited(record) {
            Some(_) => Said::Route(Box::new(GoalRoute(self.hands.clone()))),
            None => Said::Defer,
        })
    }

    /// P3: thread_available's HOLD while the goal is active, for at most HOLD_SECONDS; known_failure's
    /// VERIFIED_RESET for a usage limit whose recorded reset has passed while its goal is paused.
    fn gate(&mut self, name: &Value, record: &Value, _facts: &Value) -> Spoke {
        if is(name, "known_failure") {
            let verified =
                reset_verified_value(record, &Value::Float(self.now())).map_err(Raised::new)?;
            return Ok(if verified && self.hands.limited(record).is_some() {
                Said::Word(Alternative::VerifiedReset)
            } else {
                Said::Defer
            });
        }
        if !is(name, "thread_available") || !usage_record(record) {
            return Ok(Said::Defer);
        }
        let key = super::emptyreply::thread_key(field(record, "interruption_id"));
        let goal = self.hands.goal(field(record, "thread_id"));
        let mut seen = self.seen.lock().unwrap_or_else(PoisonError::into_inner);
        if goal.is_none_or(|goal| goal.status != GoalStatus::Active.as_str()) {
            seen.remove(&key);
            return Ok(Said::Defer);
        }
        let now = self.now();
        if !seen.contains_key(&key) && seen.len() >= SEEN_LIMIT {
            seen.clear();
        }
        let first = *seen.entry(key).or_insert(now);
        Ok(if (0.0..HOLD_SECONDS).contains(&(now - first)) {
            Said::Word(Alternative::Hold)
        } else {
            Said::Defer
        })
    }

    /// P5: the channel only where M2b passed for the Codex in force and the goal is paused by the usage limit.
    fn sender(&mut self, record: &Value) -> Spoke {
        if !(self.hands.world.m2b)() || self.hands.limited(record).is_none() {
            return Ok(Said::Defer);
        }
        Ok(Said::Channel(Box::new(GoalChannel(self.hands.clone()))))
    }
}

/// `make(paths)`: the capability's code with the world a code made from `paths` alone has.
pub fn make(paths: &Paths) -> Option<Box<dyn Code>> {
    make_with(paths, GoalWorld::bare())
}

/// `GoalContinuation(paths, ...)` with an entry point's or a test's own world.
pub fn make_with(paths: &Paths, world: GoalWorld) -> Option<Box<dyn Code>> {
    Some(Box::new(GoalContinuation::new(paths.clone(), world)))
}
