//! `control/powertasks.py` (seat S7.3a2): the power action after tasks a person picked, on the Dashboard
//! (power_after_tasks, v0.6.20, Discussion #57).
//!
//! `advanced-power-tasks` reads what the card shows: the person's own conversations whose latest turn runs now, with
//! their names, and, while core's power action is armed for tasks, each task and how it stands.
//! `advanced-power-tasks-arm` arms core's own power action (car-control's `Control`) for the conversations a person
//! picked - once - and writes the list the capability answers from (`engine::powertasks`). Both the Dashboard's alone;
//! turning it off is core's, from anywhere. [`follow`] is what `Edges::power_tasks_follow` calls.

use std::collections::BTreeSet;
use std::sync::{Arc, Weak};

use car_config::Paths;
use car_control::Control;
use car_control::error::Failure;
use car_machine::domain::ids;
use car_machine::json::{Map, Str, Value};
use car_policy::plug::{Edition, Guarded, HookFailed, Plug, Point};
use car_policy::settings::poweraction;

use super::resets::{
    Result, class_of, codex_home, codex_os, core, field, generation, int, is, is_bool, object, on,
    refused_here, small, stale, text, with,
};
use crate::codex::threads::Threads;
use crate::codex::turns::Turns;
use crate::engine::powertasks::{self, CAPABILITY, PowerAfterTasks, TurnHistory};
use crate::runtime::{Runtime, Shared};
use crate::state::Error;
use crate::vocabulary::Refusal;

pub const LIMIT: i64 = 200;
pub const ACTIONS: [&str; 3] = ["sleep", "hibernate", "shut_down"];
pub const GRACE_MINUTES: [i64; 5] = [2, 5, 10, 15, 30];

/// A raise of the reference's that is no refusal: escapes as its class.
fn raised(class: &str) -> Error {
    Error::python(class_of(class), "")
}

/// `_offered(runtime)`: [(thread id, name)] of the person's own conversations whose latest turn runs now, newest first.
pub fn offered(runtime: &Runtime) -> Result<Vec<(String, String)>> {
    let store = core(runtime)?;
    let off: BTreeSet<String> = store
        .disabled_threads()
        .map_err(|_| Error::state("cannot read core's state"))?
        .iter()
        .filter_map(|value| match value {
            Value::Str(text) => text.as_str().map(str::to_owned),
            _ => None,
        })
        .collect();
    let booted = match store.watcher_status() {
        Ok(Some(status)) => status.get("booted_at").cloned().unwrap_or(Value::Null),
        Ok(None) => Value::Null,
        Err(_) => return Err(Error::state("cannot read core's state")),
    };
    drop(store);
    let home = codex_home(runtime)?;
    let running: BTreeSet<String> = Turns::new(&home, codex_os())
        .running(&booted)
        .map_err(|_| raised("TurnsUnavailable"))?
        .into_iter()
        .collect();
    let own = Threads {
        home,
        os: codex_os(),
    }
    .own(LIMIT, &off)
    .map_err(|_| raised("TurnsUnavailable"))?;
    Ok(own
        .into_iter()
        .filter(|(thread, _)| running.contains(thread))
        .collect())
}

/// `Control(runtime.paths)` (NULL's plug) or `Control(runtime.paths, plug=...)`.
fn layer(paths: &Paths, plug: Guarded) -> Control {
    Control::new(
        paths.clone(),
        Arc::new(car_control::host::SystemHost::new(&paths.home)),
        Arc::new(plug),
    )
}

/// `_armed(runtime)`: core's arming when it is one for tasks, with its nonce, else None.
pub fn armed_of(paths: &Paths) -> std::result::Result<Value, Failure> {
    let (why, document) = layer(paths, Guarded::null()).read_power_action()?;
    let armed = if why == poweraction::READ_OK {
        field(&document, "armed")
    } else {
        Value::Null
    };
    Ok(if poweraction::for_tasks(&armed) {
        armed
    } else {
        Value::Null
    })
}

fn failure(error: Failure) -> Error {
    match error {
        Failure::Control(_) => raised("ControlError"),
        Failure::Other(class) => raised(&class),
    }
}

/// `powertasks.make(paths)` as the card holds it: the capability's own reading of each task.
pub fn code_of(paths: &Paths) -> PowerAfterTasks {
    let reading = paths.clone();
    let homes = paths.clone();
    PowerAfterTasks::new(
        paths.clone(),
        Box::new(move || powertasks::core_records(&reading)),
        Box::new(move || {
            let home = crate::engine::supervise::codex_home(&homes)?;
            Ok(Box::new(Turns::new(&home, codex_os())) as Box<dyn TurnHistory>)
        }),
    )
}

/// `view(runtime, code=None)`: advanced-power-tasks.
pub fn view(runtime: &Runtime, code: Option<&mut PowerAfterTasks>) -> Result<Value> {
    let read = || -> std::result::Result<(Vec<(String, String)>, Value), ()> {
        let offered = offered(runtime).map_err(|_| ())?;
        let armed = armed_of(&runtime.paths).map_err(|_| ())?;
        Ok((offered, armed))
    };
    let Ok((offered, armed)) = read() else {
        return Ok(refused_here(Refusal::StateUnavailable, runtime));
    };
    let mut shown = Value::Null;
    if !matches!(armed, Value::Null)
        && let Some(document) = powertasks::read(&runtime.paths)
        && field(&document, "nonce") == field(&armed, "nonce")
    {
        let mut made;
        let code = match code {
            Some(code) => code,
            None => {
                made = code_of(&runtime.paths);
                &mut made
            }
        };
        let ends = code
            .stand(&document)
            .map_err(|error| raised(&error.class))?;
        let tasks = match field(&document, "tasks") {
            Value::Array(tasks) => tasks,
            _ => Vec::new(),
        };
        let tasks: Vec<Value> = tasks
            .iter()
            .zip(ends)
            .map(|(task, end)| {
                object(vec![
                    ("thread_id", field(task, "thread_id")),
                    ("end", text(end)),
                ])
            })
            .collect();
        shown = object(vec![
            ("action", field(&armed, "action")),
            ("grace_seconds", field(&armed, "grace_seconds")),
            ("failed", field(&document, "failed")),
            ("interrupted", field(&document, "interrupted")),
            ("tasks", Value::Array(tasks)),
        ]);
    }
    let running = offered
        .iter()
        .map(|(thread, name)| object(vec![("thread_id", text(thread)), ("name", text(name))]))
        .collect();
    let mut found = object(vec![
        ("done", Value::Bool(true)),
        ("refusal", Value::Null),
        ("running", Value::Array(running)),
        ("armed", shown),
    ]);
    if let (Value::Object(map), Ok(generation)) = (&mut found, generation(runtime)) {
        map.insert(Str::new("generation"), generation);
    }
    Ok(found)
}

/// The arguments' shape, as `arm` checks it first.
fn shape_ok(
    threads: &Value,
    action: &Value,
    grace: &Value,
    failed: &Value,
    interrupted: &Value,
) -> bool {
    let Value::Array(threads) = threads else {
        return false;
    };
    if !(1..=powertasks::MOST).contains(&threads.len())
        || !threads
            .iter()
            .all(|thread| matches!(thread, Value::Str(_)) && ids::is_uuid(thread))
    {
        return false;
    }
    let distinct: BTreeSet<&Str> = threads
        .iter()
        .filter_map(|thread| match thread {
            Value::Str(text) => Some(text),
            _ => None,
        })
        .collect();
    distinct.len() == threads.len()
        && ACTIONS.iter().any(|word| is(action, word))
        && small(grace).is_some_and(|minutes| GRACE_MINUTES.contains(&minutes))
        && is_bool(failed)
        && is_bool(interrupted)
}

/// `_plug_of(runtime)`: this edition's plug as the arming is asked through - one whose runtime is this one, so core's
/// check that a plug answers for tasks (P21's `wants`) reads the capability's state as this request does.
struct Bound(Weak<Shared>);

impl Plug for Bound {
    fn edition(&self) -> Edition {
        Edition::Advanced
    }
    fn badge(&self) -> &'static str {
        "Advanced"
    }
    fn wants(&self, point: Point) -> std::result::Result<bool, HookFailed> {
        let shared = self.0.upgrade().ok_or(HookFailed)?;
        Ok(shared.enter(|runtime| runtime.wants(point)))
    }
}

/// `layer.disarm_power_action("dashboard")`, a ControlError passed over.
fn disarm(layer: &Control) -> Result<()> {
    match layer.disarm_power_action("dashboard") {
        Ok(_) | Err(Failure::Control(_)) => Ok(()),
        Err(Failure::Other(class)) => Err(raised(&class)),
    }
}

/// The history `arm` reads each picked conversation's latest turn from (`turns=`).
pub trait Latest {
    /// `(turn_id, status)` of the newest turn, None for none; an `Err` is the reader's raise.
    fn latest(&mut self, thread: &Value) -> std::result::Result<Option<(String, String)>, ()>;
}

impl Latest for Turns {
    fn latest(&mut self, thread: &Value) -> std::result::Result<Option<(String, String)>, ()> {
        Turns::latest(self, thread)
            .map(|found| found.map(|turn| (turn.turn_id, turn.status)))
            .map_err(|_| ())
    }
}

/// What `advanced-power-tasks-arm` hands `arm`.
pub struct ArmRequest<'a> {
    pub threads: &'a Value,
    pub action: &'a Value,
    pub grace_minutes: &'a Value,
    pub failed: &'a Value,
    pub interrupted: &'a Value,
    pub generation: &'a Value,
}

/// `arm(runtime, threads, action, grace_minutes, failed, interrupted, generation, turns=None)`:
/// advanced-power-tasks-arm.
pub fn arm(
    runtime: &Runtime,
    request: &ArmRequest<'_>,
    turns: Option<&mut dyn Latest>,
) -> Result<Value> {
    let ArmRequest {
        threads,
        action,
        grace_minutes: grace,
        failed,
        interrupted,
        generation: asked,
    } = *request;
    if !shape_ok(threads, action, grace, failed, interrupted) {
        return Ok(refused_here(Refusal::InvalidRequest, runtime));
    }
    if stale(runtime, asked) {
        return Ok(refused_here(Refusal::StaleGeneration, runtime));
    }
    if !on(runtime, CAPABILITY) {
        return Ok(refused_here(Refusal::NotOn, runtime));
    }
    let Value::Array(threads) = threads else {
        return Ok(refused_here(Refusal::InvalidRequest, runtime));
    };
    let picked = (|| -> std::result::Result<Option<Vec<Value>>, ()> {
        let offered: BTreeSet<String> = offered(runtime)
            .map_err(|_| ())?
            .into_iter()
            .map(|(thread, _)| thread)
            .collect();
        let mut made;
        let reader: &mut dyn Latest = match turns {
            Some(reader) => reader,
            None => {
                made = Turns::new(&codex_home(runtime).map_err(|_| ())?, codex_os());
                &mut made
            }
        };
        let mut tasks = Vec::new();
        for thread in threads {
            let thread_text = match thread {
                Value::Str(text) => text.as_str().unwrap_or_default().to_owned(),
                _ => String::new(),
            };
            let latest = if offered.contains(&thread_text) {
                reader.latest(thread)?
            } else {
                None
            };
            match latest {
                Some((turn, status)) if status == "inProgress" => tasks.push(object(vec![
                    ("thread_id", thread.clone()),
                    ("turn_id", text(&turn)),
                ])),
                _ => return Ok(None),
            }
        }
        Ok(Some(tasks))
    })();
    let tasks = match picked {
        Ok(Some(tasks)) => tasks,
        Ok(None) => return Ok(refused_here(Refusal::NoTurnRunning, runtime)),
        Err(()) => return Ok(refused_here(Refusal::StateUnavailable, runtime)),
    };
    let me = runtime.me.borrow().clone();
    let layer = layer(&runtime.paths, Guarded::new(Box::new(Bound(me))));
    let choice = object(vec![
        ("action", action.clone()),
        ("after", text("any_end")),
        ("repeat", text("once")),
        ("grace_minutes", grace.clone()),
    ]);
    match layer.arm_power_action(&choice, "dashboard", true) {
        Ok(_) => {}
        Err(Failure::Control(error)) => {
            let found = refused_here(Refusal::PowerRefused, runtime);
            return Ok(with(found, vec![("reason", text(&error.code))]));
        }
        Err(Failure::Other(class)) => return Err(raised(&class)),
    }
    let armed = armed_of(&runtime.paths).map_err(failure)?;
    let present = !matches!(armed, Value::Null);
    let mut document = Map::new();
    document.insert(Str::new("format"), text(powertasks::FORMAT));
    document.insert(
        Str::new("nonce"),
        if present {
            field(&armed, "nonce")
        } else {
            text("")
        },
    );
    document.insert(
        Str::new("armed_at"),
        if present {
            field(&armed, "armed_at")
        } else {
            int(0)
        },
    );
    document.insert(Str::new("failed"), failed.clone());
    document.insert(Str::new("interrupted"), interrupted.clone());
    document.insert(Str::new("tasks"), Value::Array(tasks));
    if !present || !powertasks::write(&runtime.paths, &Value::Object(document)) {
        disarm(&layer)?;
        return Ok(refused_here(Refusal::StateUnavailable, runtime));
    }
    // Turned off while this armed (v0.6.23 audit seatA:B-M8): an arming for tasks never outlives its capability.
    if !on(runtime, CAPABILITY) {
        disarm(&layer)?;
        powertasks::remove(&runtime.paths);
        return Ok(refused_here(Refusal::NotOn, runtime));
    }
    view(runtime, None)
}

/// `follow(paths, armed)`: the capability's stored state moved (arming): while it is not on, core's power action armed
/// for tasks is turned off and the list goes. Never raises. What an `Edges::power_tasks_follow` calls.
pub fn follow(paths: &Paths, armed: bool) {
    if armed {
        return;
    }
    let _ = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        let layer = layer(paths, Guarded::null());
        let Ok((why, document)) = layer.read_power_action() else {
            return;
        };
        if why == poweraction::READ_OK
            && poweraction::for_tasks(&field(&document, "armed"))
            && layer.disarm_power_action("dashboard").is_err()
        {
            return;
        }
        powertasks::remove(paths);
    }));
}
