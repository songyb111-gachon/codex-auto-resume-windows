//! `codex/restart.py` (seat S7.2b): the Codex restart a person agreed to after Codex's own sign-in (account_switch),
//! and the automatic switch's (account_auto_switch).
//!
//! Measured on codex-cli 0.166: only a full restart of the app - its main process ended, then started again - brings
//! it up signed in as the new account. [`busy`] says when it may not (a turn running or something queued in Codex -
//! core's own judgement, the power action's - or a recovery of core's waiting or running; a reading that fails is
//! busy too). [`restart`] then: finds the app's main as core finds it (none running is NOT_RUNNING, several FAILED);
//! asks Windows to close it and waits END_SECONDS, then ends it only if it is still there and waits KILL_SECONDS
//! (neither: NOT_ENDED); calls `between` once it is gone; starts it again through its own codex: link to the newest own
//! conversation and waits START_SECONDS for its main (NOT_STARTED); and reads the account afresh (RESTARTED or
//! SIGNED_OUT).
//!
//! Each step's hands are a seam ([`Hands`]); a test fills every one and nothing real is asked, ended or started.

use car_codex::system::System;
use car_machine::json::Value;
use car_machine::pyval;

use super::authfile::Fault;
use crate::vocabulary::ObservedWord;

pub const END_SECONDS: f64 = 30.0;
pub const KILL_SECONDS: f64 = 15.0;
pub const START_SECONDS: f64 = 60.0;
pub const LOOK_SECONDS: f64 = 1.0;
pub const RESTARTED: &str = ObservedWord::Restarted.as_str();
pub const SIGNED_OUT: &str = ObservedWord::RestartedSignedOut.as_str();
pub const NOT_RUNNING: &str = ObservedWord::NotRunning.as_str();
pub const NOT_ENDED: &str = ObservedWord::NotEnded.as_str();
pub const NOT_STARTED: &str = ObservedWord::NotStarted.as_str();
pub const FAILED: &str = ObservedWord::RestartFailed.as_str();
pub const OUTCOMES: [&str; 6] = [
    RESTARTED,
    SIGNED_OUT,
    NOT_RUNNING,
    NOT_ENDED,
    NOT_STARTED,
    FAILED,
];
pub const CLOSED: &str = ObservedWord::Closed.as_str();
pub const ENDED: &str = ObservedWord::Ended.as_str();
pub const TURN_RUNNING: &str = "turn_running";
pub const RECOVERY: &str = "recovery";
pub const QUEUED: &str = "queued";
pub const UNKNOWN: &str = "unknown";

/// What `restart` does to the world (the reference's `Hands`): core's process list read afresh, a process's creation
/// time (None where it has ended), Windows' request to close it, its end, the newest own conversation, the link handed
/// to Windows, the account read afresh, and the clock. `system` is what core's pairing rules ask of Windows.
pub trait Hands {
    fn system(&self) -> &dyn System;
    fn inventory(&self) -> Result<Vec<Value>, Fault>;
    fn created(&self, pid: &Value) -> Result<Value, Fault>;
    fn ask_close(&self, pid: &Value, created: &Value) -> Result<Value, Fault>;
    fn end_process(&self, pid: &Value, created: &Value) -> Result<Value, Fault>;
    fn newest_conversation(&self) -> Result<Value, Fault>;
    fn open(&self, link: &str) -> Result<Value, Fault>;
    fn read(&self) -> Result<Value, Fault>;
    fn now(&self) -> f64;
    fn sleep(&self, seconds: f64);
}

/// `LookupError` of `_main`, or what goes on through it.
enum Main {
    Lookup,
    Raised(Fault),
}

fn core(error: car_codex::errors::Error) -> Main {
    use car_codex::errors::Error;
    match error {
        Error::Adapter(_) | Error::Python("KeyError" | "TypeError" | "ValueError") => Main::Lookup,
        Error::Python(class) => Main::Raised(Fault::new(class, "raised by core's pairing")),
        other => Main::Raised(Fault::new("OSError", &format!("{other:?}"))),
    }
}

/// `_main(hands)`: the app's main as (pid, creation time); None where the app does not run.
fn main_of(hands: &dyn Hands) -> Result<Option<(Value, Value)>, Main> {
    let rows = match hands.inventory() {
        Ok(rows) => rows,
        Err(fault) if ["AdapterError", "KeyError", "TypeError", "ValueError"]
            .contains(&fault.class.as_str()) =>
        {
            return Err(Main::Lookup);
        }
        Err(fault) => return Err(Main::Raised(fault)),
    };
    let system = hands.system();
    if !car_codex::pairing::app_running(system, &rows).map_err(core)? {
        return Ok(None);
    }
    let main = car_codex::pairing::app_main(system, &rows).map_err(core)?;
    let Value::Object(map) = main else {
        return Err(Main::Lookup);
    };
    let pid = map.get("pid").cloned().ok_or(Main::Lookup)?;
    let created = hands.created(&pid).map_err(Main::Raised)?;
    if matches!(created, Value::Null) {
        return Err(Main::Lookup);
    }
    Ok(Some((pid, created)))
}

/// `_until(hands, seconds, done)`: whether `done()` came true within `seconds`, looking every LOOK_SECONDS; a `done`
/// that raised is not done.
fn until(hands: &dyn Hands, seconds: f64, done: &dyn Fn() -> Result<bool, ()>) -> bool {
    let deadline = hands.now() + seconds;
    loop {
        if done() == Ok(true) {
            return true;
        }
        if hands.now() >= deadline {
            return false;
        }
        hands.sleep(LOOK_SECONDS);
    }
}

fn is_true(value: &Value) -> bool {
    matches!(value, Value::Bool(true))
}

/// `restart(paths, hands=, between=)`: (what the restart came to - one of OUTCOMES -, how the app ended - CLOSED,
/// ENDED or None). `between` is called once the app is gone and before it is started again; whatever it does or
/// raises, the app is started. What the reference lets go on (a raise of the first look's process list that is not
/// core's, a raise of the account read) goes on.
pub fn restart(
    hands: &dyn Hands,
    between: Option<&mut dyn FnMut()>,
) -> Result<(&'static str, Option<&'static str>), Fault> {
    let main = match main_of(hands) {
        Ok(main) => main,
        Err(Main::Lookup) => return Ok((FAILED, None)),
        Err(Main::Raised(fault)) => return Err(fault),
    };
    let Some((pid, created)) = main.clone() else {
        return Ok((NOT_RUNNING, None));
    };
    let gone = || -> Result<bool, ()> {
        match hands.created(&pid) {
            Ok(now) => Ok(!pyval::eq(&now, &created)),
            Err(_) => Err(()),
        }
    };
    let asked = hands
        .ask_close(&pid, &created)
        .is_ok_and(|answer| is_true(&answer));
    let how = if asked && until(hands, END_SECONDS, &gone) {
        CLOSED
    } else if until(hands, 0.0, &gone) {
        CLOSED // it closed although Windows did not say so
    } else {
        let ended = hands
            .end_process(&pid, &created)
            .is_ok_and(|answer| is_true(&answer));
        if !(ended && until(hands, KILL_SECONDS, &gone)) {
            return Ok((NOT_ENDED, None));
        }
        ENDED
    };
    if let Some(between) = between {
        between();
    }
    let opened = match hands.newest_conversation() {
        Ok(newest) => match car_surface::codex_link::codex_thread_uri(&newest) {
            Some(link) => hands.open(&link).is_ok_and(|answer| is_true(&answer)),
            None => false,
        },
        Err(_) => false,
    };
    if !opened {
        return Ok((NOT_STARTED, Some(how)));
    }
    let back = || -> Result<bool, ()> {
        match main_of(hands) {
            Ok(Some(found)) => Ok(!(pyval::eq(&found.0, &pid) && pyval::eq(&found.1, &created))),
            Ok(None) => Ok(false),
            Err(_) => Err(()),
        }
    };
    if !until(hands, START_SECONDS, &back) {
        return Ok((NOT_STARTED, Some(how)));
    }
    let found = hands.read()?;
    let present = matches!(&found, Value::Object(map) if map.get("present").is_some_and(is_true));
    Ok((if present { RESTARTED } else { SIGNED_OUT }, Some(how)))
}

/// What `busy` reads of core's store: `pending()` and `watcher_status()`, each raising as the store does.
pub trait BusyStore {
    fn pending(&self) -> Result<Vec<Value>, Fault>;
    fn watcher_status(&self) -> Result<Value, Fault>;
}

/// Core's LocalSource as `busy` asks it: `activity((), now, booted=booted)`.
pub trait Activity {
    fn activity(&self, now: &Value, booted: &Value) -> Result<Value, Fault>;
}

fn get<'a>(row: &'a Value, key: &str) -> Option<&'a Value> {
    match row {
        Value::Object(map) => map.get(key),
        _ => None,
    }
}

/// `busy(paths, source=, store=, now=, usage_waiting_ok=)`: why Codex may not be restarted now - (TURN_RUNNING or
/// QUEUED, RECOVERY) as they stand, (UNKNOWN,) where any of them cannot be read - or () when it may. `store` and
/// `source` are what the reference opens (or why it could not), `now` what it was handed or `time.time()`.
pub fn busy(
    store: Result<&dyn BusyStore, Fault>,
    source: Result<&dyn Activity, Fault>,
    now: &Value,
    usage_waiting_ok: bool,
) -> Result<Vec<&'static str>, Fault> {
    let read = (|| -> Result<(Vec<Value>, Option<&'static str>), Fault> {
        let store = store?;
        let rows = store.pending()?;
        let status = store.watcher_status()?;
        let booted = match &status {
            Value::Object(map) => map.get("booted_at").cloned().unwrap_or(Value::Null),
            found if !pyval::truthy(found) => Value::Null,
            _ => return Err(Fault::new("AttributeError", "object has no attribute 'get'")),
        };
        let source = source?;
        let found = source.activity(now, &booted)?;
        Ok((rows, car_policy::settings::poweraction::judge_activity(&found)))
    })();
    let Ok((rows, word)) = read else {
        return Ok(vec![UNKNOWN]);
    };
    let mut found = match word {
        Some("turn_running") => vec![TURN_RUNNING],
        Some("queued_input") => vec![QUEUED],
        None => Vec::new(),
        Some(_) => return Ok(vec![UNKNOWN]),
    };
    let waiting = car_machine::vocab_gen::domain_states::WAITING;
    for row in &rows {
        if !matches!(row, Value::Object(_)) {
            return Err(Fault::new("AttributeError", "object has no attribute 'get'"));
        }
        let truthy = |key: &str| get(row, key).is_some_and(pyval::truthy);
        if truthy("hold") || truthy("cancel_requested") {
            continue;
        }
        let usage_waiting = usage_waiting_ok
            && get(row, "category").is_some_and(|category| pyval::is(category, "usage_limit"))
            && match get(row, "state") {
                Some(Value::Array(_) | Value::Object(_)) => {
                    return Err(Fault::new("TypeError", "unhashable type"));
                }
                Some(state) => pyval::in_tuple(state, waiting),
                None => false,
            };
        if !usage_waiting {
            found.push(RECOVERY);
            break;
        }
    }
    Ok(found)
}
