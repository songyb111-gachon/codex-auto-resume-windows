//! `control/earlycheck.py` (seat S7.3a): early_reset's probe as Pending and the Dashboard see it (v0.6.19, issue #50) -
//! its last reading for Pending's Why it is waiting (`view`, the status's `early_check`), and the probe a person's Retry
//! now or Rescan asks for (`check`, advanced-early-check).

use car_machine::json::{Map, Str, Value};
use car_machine::pyval;
use car_policy::classify::gates::{HELD, NOT_CHECKED, PASS, WAIT, decode_gates};

use super::resets::{call, core, get, int, is, number_of, object, plus, text, wake};
use crate::engine::earlyreset::{EARLY_STATES, SPACING, WINDOW};
use crate::runtime::Runtime;
use crate::vocabulary::{ArmingState, OptionKey, Refusal};

pub const CAPABILITY: &str = "early_reset";
pub const READ_AVAILABLE: &str = "available";
pub const READ_LIMITED: &str = "still_limited";
pub const READ_UNKNOWN: &str = "unknown";
pub const READ_NONE: &str = "not_read";
pub const ASKED: &str = "asked";
pub const COALESCED: &str = "coalesced";
pub const NOT_RUNNING: &str = "not_running";
pub const NOTHING_WAITS: &str = "nothing_waits";
/// `failures.USAGE_LIMIT`.
const USAGE_LIMIT: &str = "usage_limit";

fn time(value: &Value) -> Option<f64> {
    match value {
        Value::Int(_) | Value::Float(_) => number_of(value),
        _ => None,
    }
}

fn on(runtime: &Runtime) -> bool {
    runtime.states(true, &[]).state_of(CAPABILITY) == ArmingState::Armed
}

/// `_waiting(store)`: core's records that wait for a usage limit to reset.
fn waiting(store: &car_store::Store) -> Result<Vec<Map>, ()> {
    Ok(store
        .pending()
        .map_err(|_| ())?
        .into_iter()
        .filter(|row| {
            is(&get(row, "category"), USAGE_LIMIT)
                && super::resets::among(&get(row, "state"), &EARLY_STATES)
                && !pyval::truthy(&get(row, "cancel_requested"))
        })
        .collect())
}

/// `_read(rows, checked_at)`: what the probe begun at `checked_at` read, from each waiting record's usage gate.
fn read(rows: &[Map], checked_at: f64) -> &'static str {
    let mut found: Vec<&str> = Vec::new();
    for row in rows {
        let Some(at) = time(&get(row, "gate_eval_at")) else {
            continue;
        };
        if at < checked_at || !pyval::truthy(&get(row, "gate_eval")) {
            continue;
        }
        let gates = decode_gates(&get(row, "gate_eval"));
        let Some((result, reason)) = gates.get("usage").cloned() else {
            continue;
        };
        if reason == NOT_CHECKED {
            continue;
        }
        if result == PASS || (result == WAIT && reason == HELD) {
            found.push(READ_AVAILABLE);
        } else if result == WAIT && reason == "usage_unavailable" {
            found.push(READ_LIMITED);
        } else {
            found.push(READ_UNKNOWN);
        }
    }
    [READ_AVAILABLE, READ_LIMITED, READ_UNKNOWN]
        .into_iter()
        .find(|word| found.contains(word))
        .unwrap_or(READ_NONE)
}

fn stamped(runtime: &Runtime, key: OptionKey) -> super::resets::Result<Value> {
    call(runtime, "stamped", &[text(CAPABILITY), text(key.as_str())], &[])
}

/// `view(runtime, store=None)`: {"early_check": {...}} while early_reset stands on, else {}.
pub fn view(runtime: &Runtime) -> Map {
    let mut answer = Map::new();
    if !on(runtime) {
        return answer;
    }
    let now = runtime.now();
    let keys = [
        OptionKey::CheckedAt,
        OptionKey::AvailableAt,
        OptionKey::LiftedAt,
        OptionKey::CheckAsked,
        OptionKey::FoundAt,
    ];
    let mut times = Vec::new();
    for key in keys {
        match stamped(runtime, key) {
            Ok(found) => times.push(found),
            Err(_) => return answer,
        }
    }
    let rows = core(runtime).ok().and_then(|store| waiting(&store).ok()).unwrap_or_default();
    let (checked, available, lifted, asked, found) =
        (&times[0], &times[1], &times[2], &times[3], &times[4]);
    let read_word = if !pyval::truthy(checked) {
        Value::Null
    } else if pyval::eq(found, checked) {
        text(READ_AVAILABLE)
    } else {
        // `_read(rows, checked)`: a checked time that is no number compares as the reference's `at < checked_at`.
        match number_of(checked) {
            Some(at) => text(read(&rows, at)),
            None => text(READ_NONE),
        }
    };
    let confirm = if pyval::truthy(available) {
        plus(available, &int(SPACING as i64))
    } else {
        Value::Null
    };
    let asked_now = time(asked).is_some_and(|at| {
        0.0 <= now - at
            && now - at < SPACING + 1.0
            && (!pyval::truthy(checked) || pyval::greater(asked, checked).unwrap_or(false))
    });
    let shown = object(vec![
        ("checked_at", checked.clone()),
        ("read", read_word),
        ("available_at", available.clone()),
        ("confirm_at", confirm),
        ("lifted_at", lifted.clone()),
        (
            "lifted",
            Value::Bool(pyval::truthy(checked) && pyval::eq(lifted, checked)),
        ),
        ("waiting", int(rows.len() as i64)),
        ("asked", Value::Bool(asked_now)),
    ]);
    answer.insert(Str::new("early_check"), shown);
    answer
}

fn answered(word: &str) -> Value {
    object(vec![("done", Value::Bool(true)), ("refusal", Value::Null), ("check", text(word))])
}

/// `check(runtime, store=None)`: advanced-early-check.
pub fn check(runtime: &Runtime) -> Value {
    if runtime.registry.get(CAPABILITY).is_none() {
        return super::resets::refusal(Refusal::UnknownCapability);
    }
    if !on(runtime) {
        return super::resets::refusal(Refusal::NotOn);
    }
    let now = runtime.now();
    let unavailable = || super::resets::refusal(Refusal::StateUnavailable);
    let Ok(store) = core(runtime) else {
        return unavailable();
    };
    let Ok(rows) = waiting(&store) else {
        return unavailable();
    };
    if rows.is_empty() {
        return answered(NOTHING_WAITS);
    }
    let (Ok(checked), Ok(asked)) = (stamped(runtime, OptionKey::CheckedAt), stamped(runtime, OptionKey::CheckAsked)) else {
        return unavailable();
    };
    let recent = time(&checked).is_some_and(|at| 0.0 <= now - at && now - at < WINDOW);
    let standing = || {
        time(&asked).is_some_and(|at| {
            0.0 <= now - at
                && now - at < SPACING + 1.0
                && (!pyval::truthy(&checked) || pyval::greater(&asked, &checked).unwrap_or(false))
        }) && store.early_check_asked(now)
    };
    if recent || standing() {
        return answered(COALESCED);
    }
    let stamp = int((now as i64).max(1));
    let stamped_now = match call(
        runtime,
        "stamp",
        &[text(CAPABILITY), text(OptionKey::CheckAsked.as_str()), stamp],
        &[],
    ) {
        Ok(done) => pyval::truthy(&done),
        Err(_) => return unavailable(),
    };
    let asked_core = stamped_now
        && match store.ask_early_check(now) {
            Ok(done) => done,
            Err(_) => return unavailable(),
        };
    if !asked_core {
        if call(runtime, "unstamp", &[text(CAPABILITY), text(OptionKey::CheckAsked.as_str())], &[]).is_err() {
            return unavailable();
        }
        return unavailable();
    }
    if !wake(runtime) {
        store.early_check_taken();
        if call(runtime, "unstamp", &[text(CAPABILITY), text(OptionKey::CheckAsked.as_str())], &[]).is_err() {
            return unavailable();
        }
        return answered(NOT_RUNNING);
    }
    answered(ASKED)
}
