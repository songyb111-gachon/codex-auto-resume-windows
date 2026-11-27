//! `control/account.py` (seat S7.3a): the account card (account_switch, v0.6.20) - which account is signed in, and
//! Codex's own sign-out and sign-in started on a thread of its own, then Restart or Not now. The Dashboard's alone.
//! What it asks of Codex - the account read, the switch, the restart and why Codex is busy - is the entry points'
//! [`crate::surfaces::World`]; the switch's and the restart's states live for the life of the process, per home.

use std::collections::HashMap;
use std::sync::{Mutex, OnceLock, PoisonError};

use car_machine::json::{Map, Str, Value};

use super::resets::{Result, field, object, refusal, standing, text, verdict};
use crate::codex::account::{
    self as codex_account, CANCELLED, FAILED, OUTCOMES, SIGNED_IN, TIMED_OUT,
};
use crate::codex::restart as restarts;
use crate::runtime::Runtime;
use crate::vocabulary::{ArmingState, Measurement, Refusal};

pub const CAPABILITY: &str = codex_account::CAPABILITY;
pub const WAITING: &str = "waiting";
pub const ASK: &str = "ask";
pub const NOT_NOW: &str = "not_now";
pub const RESTARTING: &str = "restarting";
/// The states Restart may be pressed in.
pub const RESTARTABLE: [&str; 5] = [
    ASK,
    NOT_NOW,
    restarts::NOT_ENDED,
    restarts::NOT_STARTED,
    restarts::FAILED,
];

/// `COUNTED[outcome]`.
fn counted(outcome: &str) -> &'static str {
    match outcome {
        SIGNED_IN => "signed_in",
        CANCELLED => "not_signed_in",
        TIMED_OUT | FAILED => "switch_failed",
        _ => "switch_failed",
    }
}

/// `RESTART_COUNTED[outcome]`.
fn restart_counted(outcome: &str) -> &'static str {
    match outcome {
        restarts::RESTARTED | restarts::SIGNED_OUT => "restarted",
        restarts::NOT_RUNNING => "restart_not_needed",
        _ => "restart_failed",
    }
}

/// `ENDED_COUNTED.get(how)`.
fn ended_counted(how: Option<&str>) -> Option<&'static str> {
    match how {
        Some(restarts::CLOSED) => Some("codex_closed"),
        Some(restarts::ENDED) => Some("codex_ended"),
        _ => None,
    }
}

#[derive(Default)]
struct Held {
    switches: HashMap<String, String>,
    restarts: HashMap<String, String>,
    shown: HashMap<String, Value>,
}

fn held() -> std::sync::MutexGuard<'static, Held> {
    static HELD: OnceLock<Mutex<Held>> = OnceLock::new();
    HELD.get_or_init(|| Mutex::new(Held::default()))
        .lock()
        .unwrap_or_else(PoisonError::into_inner)
}

fn home(runtime: &Runtime) -> String {
    runtime.paths.home.clone()
}

/// `switching(runtime)`: WAITING while a switch waits, else the last one's outcome word, or None.
pub fn switching(runtime: &Runtime) -> Option<String> {
    held().switches.get(&home(runtime)).cloned()
}

/// `restarting(runtime)`.
pub fn restarting(runtime: &Runtime) -> Option<String> {
    held().restarts.get(&home(runtime)).cloned()
}

fn armed(runtime: &Runtime) -> bool {
    runtime.states(true, &[]).state_of(CAPABILITY) == ArmingState::Armed
}

/// `offered(runtime)`: the capability on and MALR passed on the Codex in force.
pub fn offered(runtime: &Runtime) -> bool {
    armed(runtime) && verdict(runtime, Measurement::Malr) == Some("pass")
}

/// `failed(runtime)`: MALR failed.
pub fn failed(runtime: &Runtime) -> bool {
    verdict(runtime, Measurement::Malr) == Some("fail")
}

/// `_shown(found)`: {present, plan, kind, mask} - never the address.
pub fn shown_of(found: &Value) -> Value {
    let present = match found {
        Value::Object(_) => field(found, "present"),
        _ => Value::Null,
    };
    let on = car_machine::pyval::truthy(&present);
    object(vec![
        ("present", present),
        (
            "plan",
            if on {
                field(found, "plan_word")
            } else {
                Value::Null
            },
        ),
        (
            "kind",
            if on {
                field(found, "kind")
            } else {
                Value::Null
            },
        ),
        (
            "mask",
            if on {
                codex_account::mask(&field(found, "email"))
            } else {
                Value::Null
            },
        ),
    ])
}

fn word(found: Option<&str>) -> Value {
    found.map_or(Value::Null, text)
}

/// `view(runtime)`: advanced-account.
pub fn view(runtime: &Runtime) -> Result<Value> {
    if !standing(runtime, CAPABILITY) {
        return Ok(refusal(Refusal::NotOn));
    }
    let state = switching(runtime);
    let asked = restarting(runtime);
    let world = crate::surfaces::world();
    let restartable = asked
        .as_deref()
        .is_some_and(|asked| RESTARTABLE.contains(&asked));
    let shown = if state.as_deref() == Some(WAITING) {
        shown_of(&codex_account::parse(&Value::Null))
    } else if restartable || asked.as_deref() == Some(RESTARTING) {
        let kept = held().shown.get(&home(runtime)).cloned();
        kept.filter(car_machine::pyval::truthy)
            .unwrap_or_else(|| shown_of(&codex_account::parse(&Value::Null)))
    } else {
        shown_of(&(world.account_read)(&runtime.paths))
    };
    let button = offered(runtime);
    let mut found = Map::new();
    found.insert(Str::new("done"), Value::Bool(true));
    found.insert(Str::new("refusal"), Value::Null);
    if let Value::Object(shown) = shown {
        found.extend(shown);
    }
    found.insert(Str::new("button"), Value::Bool(button));
    found.insert(Str::new("measurement_failed"), Value::Bool(failed(runtime)));
    found.insert(Str::new("switch"), word(state.as_deref()));
    found.insert(
        Str::new("restart"),
        if button {
            word(asked.as_deref())
        } else {
            Value::Null
        },
    );
    found.insert(Str::new("busy"), Value::Array(Vec::new()));
    if button && restartable {
        let busy = (world.restart_busy)(&runtime.paths);
        found.insert(
            Str::new("busy"),
            Value::Array(busy.into_iter().map(text).collect()),
        );
    }
    Ok(Value::Object(found))
}

/// `_count(runtime, code)`: the journal's count, a failure costing nothing.
fn count(shared: &std::sync::Weak<crate::runtime::Shared>, code: &str) {
    if let Some(shared) = shared.upgrade() {
        shared.enter(|runtime| {
            let _ = super::resets::call(runtime, "counted", &[text(CAPABILITY), text(code)], &[]);
        });
    }
}

fn not_offered(runtime: &Runtime) -> Value {
    if !armed(runtime) {
        refusal(Refusal::NotOn)
    } else {
        refusal(Refusal::SwitchUnmeasured)
    }
}

/// `switch(runtime)`: advanced-account-switch.
pub fn switch(runtime: &Runtime) -> Result<Value> {
    if !offered(runtime) {
        return Ok(not_offered(runtime));
    }
    let home = home(runtime);
    {
        let mut held = held();
        if held.switches.get(&home).map(String::as_str) == Some(WAITING) {
            return Ok(refusal(Refusal::SwitchRunning));
        }
        held.switches.insert(home.clone(), WAITING.into());
        held.restarts.remove(&home);
        held.shown.remove(&home);
    }
    let me = runtime.me.borrow().clone();
    count(&me, "switch_asked");
    let world = crate::surfaces::world();
    let paths = runtime.paths.clone();
    let job_home = home.clone();
    let job_world = world.clone();
    let job = Box::new(move || {
        let outcome = (job_world.account_switch)(&paths);
        let outcome = if OUTCOMES.contains(&outcome) {
            outcome
        } else {
            FAILED
        };
        let shown = (outcome == SIGNED_IN).then(|| shown_of(&(job_world.account_read)(&paths)));
        {
            let mut held = held();
            held.switches.insert(job_home.clone(), outcome.into());
            if let Some(shown) = shown {
                held.shown.insert(job_home.clone(), shown);
                held.restarts.insert(job_home.clone(), ASK.into());
            }
        }
        count(&me, counted(outcome));
    });
    if !(world.spawn)(job) {
        held().switches.insert(home, FAILED.into());
        return Ok(refusal(Refusal::StateUnavailable));
    }
    Ok(object(vec![
        ("done", Value::Bool(true)),
        ("refusal", Value::Null),
        ("switch", text(WAITING)),
    ]))
}

/// `restart(runtime, argument)`: advanced-account-restart.
pub fn restart(runtime: &Runtime, argument: &Map) -> Result<Value> {
    let Some(Value::Bool(now)) = argument.get("now").cloned() else {
        return Ok(refusal(Refusal::InvalidRequest));
    };
    if !offered(runtime) {
        return Ok(not_offered(runtime));
    }
    let home = home(runtime);
    {
        let mut held = held();
        let asked = held.restarts.get(&home).cloned();
        if asked.as_deref() == Some(RESTARTING) {
            return Ok(refusal(Refusal::RestartRunning));
        }
        if !asked
            .as_deref()
            .is_some_and(|asked| RESTARTABLE.contains(&asked))
        {
            return Ok(refusal(Refusal::NothingToRestart));
        }
        if !now {
            held.restarts.insert(home, NOT_NOW.into());
            return Ok(object(vec![
                ("done", Value::Bool(true)),
                ("refusal", Value::Null),
                ("restart", text(NOT_NOW)),
            ]));
        }
    }
    let world = crate::surfaces::world();
    if !(world.restart_busy)(&runtime.paths).is_empty() {
        return Ok(refusal(Refusal::RestartBusy));
    }
    {
        let mut held = held();
        if !held
            .restarts
            .get(&home)
            .is_some_and(|asked| RESTARTABLE.contains(&asked.as_str()))
        {
            return Ok(refusal(Refusal::RestartRunning));
        }
        held.restarts.insert(home.clone(), RESTARTING.into());
    }
    let me = runtime.me.borrow().clone();
    count(&me, "restart_asked");
    let paths = runtime.paths.clone();
    let job_home = home.clone();
    let job_world = world.clone();
    let job = Box::new(move || {
        let (outcome, how) = (job_world.restart_run)(&paths);
        let outcome = if restarts::OUTCOMES.contains(&outcome) {
            outcome
        } else {
            restarts::FAILED
        };
        held().restarts.insert(job_home, outcome.into());
        if let Some(code) = ended_counted(how) {
            count(&me, code);
        }
        count(&me, restart_counted(outcome));
    });
    if !(world.spawn)(job) {
        held().restarts.insert(home, restarts::FAILED.into());
        return Ok(refusal(Refusal::StateUnavailable));
    }
    Ok(object(vec![
        ("done", Value::Bool(true)),
        ("refusal", Value::Null),
        ("restart", text(RESTARTING)),
    ]))
}
