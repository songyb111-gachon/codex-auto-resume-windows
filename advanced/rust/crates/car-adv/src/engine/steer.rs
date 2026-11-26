//! `steer_send`'s code (seat S7.2e1b; `engine/steer.py`): a line a person wrote, added at once to the turn running in a
//! conversation the Codex app holds, through the app's own IPC pipe - at P8, as an errand with core's guards.
//!
//! For each steer still requested, oldest first: refused `turned_off`, `expired` (asked more than EXPIRES ago),
//! `conversation_off`, `no_turn` (the latest turn not running, or begun after the steer was asked, or when unknown),
//! `not_held` (nobody holds the writer lock, or the app does not hold the conversation); else claimed
//! (`requested -> sending`) and written once: accepted, unconfirmed, or refused with the pipe's word.
//!
//! Its seams ([`SteerWorld`]): the write (`codex/ipc.steer_turn` with core's guard - the live bridge from car-policy's
//! `Guards` to `ipc::Gate` is the entry points', S7.3d), the latest turn's status and start (`codex/turns.py`), the
//! writer lock's holders (core's `windows.resource_users`) and core's loaded check.

use std::sync::Arc;

use car_config::Paths;
use car_machine::json::Value;
use car_policy::plug::{Errand, Guards, HookFailed, View};

use super::emptyreply::{enabled, rebind, word};
use crate::capabilities::{Binding, Code, Raised, Said, Spoke};
use crate::codex::ipc::{STEERED, Stop};
use crate::state::scoped::Scoped;
use crate::state::sql::{self, Row};
use crate::vocabulary::{SteerReason, SteerState};

pub const CAPABILITY: &str = "steer_send";
/// How long a steer may wait for the watcher, in seconds, before it is refused as expired.
pub const EXPIRES: f64 = 120.0;
pub const PER_CONVERSATION: i64 = 60;
pub const PER_DAY: i64 = 120;
pub const DAY: f64 = 86400.0;
pub const RUNNING: &str = "inProgress";

/// `outcome(word)`: (state, reason) for `ipc.steer_turn`'s word; anything else it can say is the app refusing it.
pub fn outcome(said: &str) -> (SteerState, Option<SteerReason>) {
    match said {
        STEERED => (SteerState::Accepted, None),
        _ if said == Stop::Unconfirmed.as_str() => (SteerState::Unconfirmed, None),
        _ if said == Stop::Held.as_str() => (SteerState::Refused, Some(SteerReason::Held)),
        _ if said == Stop::NoPipe.as_str() => (SteerState::Refused, Some(SteerReason::NoPipe)),
        _ if said == Stop::NoClient.as_str() => (SteerState::Refused, Some(SteerReason::NotHeld)),
        _ => (SteerState::Refused, Some(SteerReason::AppRefused)),
    }
}

/// The journal's word for each outcome.
pub fn code(state: SteerState) -> &'static str {
    match state {
        SteerState::Accepted => "accepted",
        SteerState::Unconfirmed => "unconfirmed",
        _ => "refused",
    }
}

/// `steer(thread, words, message=client_id, gate=guard)`: the pipe's word, or Err where it raised.
pub type SteerFn =
    Arc<dyn Fn(&Value, &Value, &Value, &mut Guards<'_>) -> Result<String, ()> + Send + Sync>;

/// The seams the code is made with.
#[derive(Clone)]
pub struct SteerWorld {
    pub steer: SteerFn,
    /// `latest_status(home, thread)`.
    pub status: Arc<dyn Fn(&Value) -> Option<String> + Send + Sync>,
    /// `latest_started(home, thread)`: when the latest turn began, as the history says it (an int, or anything else).
    pub started: Arc<dyn Fn(&Value) -> Value + Send + Sync>,
    /// `holders(home, thread)`: how many hold the writer lock, or None.
    pub holders: Arc<dyn Fn(&Value) -> Option<i64> + Send + Sync>,
    /// `held_by_app(paths, thread)`.
    pub app_holds: Arc<dyn Fn(&Value) -> bool + Send + Sync>,
}

impl SteerWorld {
    /// What `make(paths)` gives: no Codex home and no pipe known here - every steer is refused (`no_turn`).
    pub fn bare() -> SteerWorld {
        SteerWorld {
            steer: Arc::new(|_, _, _, _| Ok(Stop::NoPipe.as_str().to_owned())),
            status: Arc::new(|_| None),
            started: Arc::new(|_| Value::Null),
            holders: Arc::new(|_| None),
            app_holds: Arc::new(|_| false),
        }
    }
}

/// `SteerSend(paths, steer=None, status=None, count_holders=None, app_holds=None, home=None)`.
pub struct SteerSend {
    pub paths: Paths,
    binding: Option<Binding>,
    world: SteerWorld,
}

struct Look {
    binding: Binding,
    world: SteerWorld,
}

impl Errand for Look {
    fn run(&self, view: &dyn View, guards: &mut Guards<'_>) -> Result<Value, HookFailed> {
        self.binding
            .with(|scoped| self.steer_waiting(scoped, view, guards));
        Ok(Value::Null)
    }
}

fn number(value: &Value) -> Option<f64> {
    match value {
        Value::Int(int) => int.as_i64().map(|int| int as f64),
        Value::Float(number) => Some(*number),
        Value::Bool(flag) => Some(f64::from(u8::from(*flag))),
        _ => None,
    }
}

impl Look {
    /// `steer_waiting(view, guard)`: each steer still requested, checked and - where every check passes - claimed and
    /// written once.
    fn steer_waiting(&self, scoped: &Scoped<'_>, view: &dyn View, guards: &mut Guards<'_>) {
        if scoped.state.settle_cut_short(&Value::Null).is_err() {
            return;
        }
        let Ok(rows) = scoped.state.waiting_steers() else {
            return;
        };
        for row in rows.into_iter().filter(|row| {
            sql::py_eq(
                sql::get(row, "state"),
                &word(SteerState::Requested.as_str()),
            )
        }) {
            let _ = self.one(scoped, view, guards, &row);
        }
    }

    /// `_one`: Err is the reference's raise (the next tick looks again).
    fn one(
        &self,
        scoped: &Scoped<'_>,
        view: &dyn View,
        guards: &mut Guards<'_>,
        row: &Row,
    ) -> Result<(), ()> {
        let steer_id = sql::get(row, "steer_id").clone();
        let thread = sql::get(row, "thread_id").clone();
        if let Some(reason) = self.refusal(scoped, view, row)? {
            return settle(scoped, &steer_id, SteerState::Refused, Some(reason));
        }
        scoped.handle().table_writing().map_err(|_| ())?;
        if !scoped.state.claim_steer(&steer_id).map_err(|_| ())? {
            return Ok(());
        }
        let said = (self.world.steer)(
            &thread,
            sql::get(row, "words"),
            sql::get(row, "client_id"),
            guards,
        )
        .unwrap_or_else(|()| Stop::Unconfirmed.as_str().to_owned());
        let (state, why) = outcome(&said);
        settle(scoped, &steer_id, state, why)
    }

    /// `_refusal(view, handle, row)`: why `row` may not be written now, or None. Err where the row cannot be read.
    fn refusal(
        &self,
        scoped: &Scoped<'_>,
        view: &dyn View,
        row: &Row,
    ) -> Result<Option<SteerReason>, ()> {
        if !scoped.handle().is_on() {
            return Ok(Some(SteerReason::TurnedOff));
        }
        let now = scoped.now();
        let created = number(sql::get(row, "created_at")).ok_or(())?;
        if !(0.0..=EXPIRES).contains(&(now - created)) {
            return Ok(Some(SteerReason::Expired));
        }
        let thread = sql::get(row, "thread_id").clone();
        if enabled(view, &thread) == Some(false) {
            return Ok(Some(SteerReason::ConversationOff));
        }
        if (self.world.status)(&thread).as_deref() != Some(RUNNING) {
            return Ok(Some(SteerReason::NoTurn));
        }
        let later = match (self.world.started)(&thread) {
            Value::Int(started) => match started.as_i64() {
                Some(started) => started as f64 > created,
                None => true,
            },
            _ => true,
        };
        if later {
            return Ok(Some(SteerReason::NoTurn));
        }
        if !(self.world.holders)(&thread).is_some_and(|count| count != 0) {
            return Ok(Some(SteerReason::NotHeld));
        }
        if !(self.world.app_holds)(&thread) {
            return Ok(Some(SteerReason::NotHeld));
        }
        Ok(None)
    }
}

/// `_settle(handle, steer_id, state, reason)`: settled now, and counted in the journal's word when it was.
fn settle(
    scoped: &Scoped<'_>,
    steer_id: &Value,
    state: SteerState,
    reason: Option<SteerReason>,
) -> Result<(), ()> {
    let reason = reason.map_or(Value::Null, |reason| word(reason.as_str()));
    let settled = scoped
        .handle()
        .steers_settle(
            steer_id,
            &word(state.as_str()),
            &reason,
            &Value::Float(scoped.now()),
        )
        .map_err(|_| ())?;
    if settled {
        let _ = scoped.count(&word(code(state)));
    }
    Ok(())
}

impl SteerSend {
    pub fn new(paths: Paths, world: SteerWorld) -> SteerSend {
        SteerSend {
            paths,
            binding: None,
            world,
        }
    }
}

impl Code for SteerSend {
    fn bind(&mut self, binding: Binding) -> Option<Result<(), Raised>> {
        self.binding = Some(binding);
        Some(Ok(()))
    }

    /// P8: the errand, while a steer waits.
    fn tick(&mut self, _view: &dyn View) -> Spoke {
        let Some(binding) = &self.binding else {
            return Ok(Said::Defer);
        };
        let waits = binding.with(|scoped| {
            scoped
                .state
                .waiting_steers()
                .is_ok_and(|rows| !rows.is_empty())
        });
        if waits != Some(true) {
            return Ok(Said::Defer);
        }
        Ok(Said::Errand(Box::new(Look {
            binding: rebind(binding),
            world: self.world.clone(),
        })))
    }
}

/// `make(paths)`: the capability's code with the world a code made from `paths` alone has.
pub fn make(paths: &Paths) -> Option<Box<dyn Code>> {
    make_with(paths, SteerWorld::bare())
}

/// `SteerSend(paths, ...)` with an entry point's or a test's own world.
pub fn make_with(paths: &Paths, world: SteerWorld) -> Option<Box<dyn Code>> {
    Some(Box::new(SteerSend::new(paths.clone(), world)))
}
