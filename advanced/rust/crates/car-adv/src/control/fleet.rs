//! `control/fleet.py` (seat S7.3a): See your other PCs, on the Dashboard (fleet_view, v0.6.22) - `advanced-fleet` reads
//! what the watcher's last pass kept (never the synced folder itself), `advanced-fleet-save` keeps the alias and the
//! folder chosen, each checked, looking at the folder on a thread of its own waited on a few seconds at most
//! ([`bounded`], `engine/fleet.py`'s, which S7.2e2 left for this card).

use std::sync::mpsc;
use std::sync::{Mutex, OnceLock, PoisonError};
use std::thread::JoinHandle;
use std::time::{Duration, Instant};

use car_machine::json::{Str, Value};

use super::resets::{Result, call, field, generation, int, object, refused_here, stale, standing, text};
use crate::engine::fleet::{self, CAPABILITY, HELD, LATE, OK, UNSET};
use crate::runtime::Runtime;
use crate::vocabulary::{ArmingState, OptionKey, Refusal, WordingKey};

/// `fleet.BOUND`: how long the save waits for the folder, in seconds.
pub const BOUND: f64 = 5.0;

/// The access before this one, while it may still run.
fn access() -> &'static Mutex<Option<JoinHandle<()>>> {
    static ACCESS: OnceLock<Mutex<Option<JoinHandle<()>>>> = OnceLock::new();
    ACCESS.get_or_init(|| Mutex::new(None))
}

/// `bounded(call, bound=None)`: call()'s answer from a thread of its own waited on `bound` seconds at most; Err (the
/// reference's TimeoutError) where it did not answer in time, or where the access before it is still held past the same
/// bound - at most one is in flight.
pub fn bounded<T: Send + 'static>(call: impl FnOnce() -> T + Send + 'static, bound: Option<f64>) -> std::result::Result<T, ()> {
    let deadline = Instant::now() + Duration::from_secs_f64(bound.unwrap_or(BOUND).max(0.0));
    let (send, receive) = mpsc::channel();
    let mut call = Some(call);
    loop {
        let mut held = access().lock().unwrap_or_else(PoisonError::into_inner);
        let free = held.as_ref().is_none_or(JoinHandle::is_finished);
        if free {
            let call = call.take().expect("started once");
            let send = send.clone();
            let worker = std::thread::Builder::new()
                .name("car-fleet-access".into())
                .spawn(move || {
                    let _ = send.send(call());
                })
                .map_err(|_| ())?;
            *held = Some(worker);
            break;
        }
        drop(held);
        if Instant::now() >= deadline {
            return Err(());
        }
        std::thread::sleep(Duration::from_millis(10));
    }
    let left = deadline.saturating_duration_since(Instant::now());
    receive.recv_timeout(left).map_err(|_| ())
}

fn wording(words: &Value, key: WordingKey) -> Value {
    field(words, key.as_str())
}

/// `view(runtime, now=None)`: advanced-fleet.
pub fn view(runtime: &Runtime) -> Result<Value> {
    let read = || -> Result<(ArmingState, Value, Value)> {
        let state = runtime.states(true, &[]).state_of(CAPABILITY);
        let words = call(runtime, "wordings", &[text(CAPABILITY)], &[])?;
        Ok((state, words, generation(runtime)?))
    };
    let Ok((state, words, generation)) = read() else {
        return Ok(refused_here(Refusal::StateUnavailable, runtime));
    };
    let (alias, folder) = (wording(&words, WordingKey::FleetAlias), wording(&words, WordingKey::FleetFolder));
    let mut found = match object(vec![
        ("done", Value::Bool(true)),
        ("refusal", Value::Null),
        ("state", text(state.as_str())),
        ("alias", alias.clone()),
        ("folder", folder.clone()),
        ("stand", text(UNSET)),
        ("peers", Value::Array(Vec::new())),
        ("ignored", int(0)),
        ("generation", generation),
    ]) {
        Value::Object(map) => map,
        _ => unreachable!("an object"),
    };
    if state != ArmingState::Armed || !fleet::alias_valid(&alias) || !car_machine::pyval::truthy(&folder) {
        return Ok(Value::Object(found));
    }
    let now = runtime.now();
    let stamp = call(runtime, "stamped", &[text(CAPABILITY), text(OptionKey::FleetWaiting.as_str())], &[])?;
    let waiting = fleet::waiting_word(&stamp);
    let seen = fleet::read_seen(&runtime.paths)
        .unwrap_or_else(|| object(vec![("ignored", int(0)), ("held", int(0)), ("peers", Value::Array(Vec::new()))]));
    let stand = waiting.unwrap_or(if car_machine::pyval::truthy(&field(&seen, "held")) { HELD } else { OK });
    let mine = fleet::casefold(&crate::state::py::py_str(&alias));
    let peers: Vec<Value> = match field(&seen, "peers") {
        Value::Array(items) => items
            .iter()
            .filter(|each| fleet::casefold(&crate::state::py::py_str(&field(each, "alias"))) != mine)
            .map(|each| fleet::shown(each, now))
            .collect(),
        _ => Vec::new(),
    };
    found.insert(Str::new("stand"), text(stand));
    found.insert(Str::new("ignored"), field(&seen, "ignored"));
    found.insert(Str::new("peers"), Value::Array(peers));
    Ok(Value::Object(found))
}

/// `save(runtime, alias, folder, generation)`: advanced-fleet-save.
pub fn save(runtime: &Runtime, alias: &Value, folder: &Value, asked: &Value) -> Result<Value> {
    if stale(runtime, asked) {
        return Ok(refused_here(Refusal::StaleGeneration, runtime));
    }
    if !standing(runtime, CAPABILITY) {
        return Ok(refused_here(Refusal::NotOn, runtime));
    }
    let problem = if !fleet::alias_valid(alias) {
        Some("alias")
    } else {
        let guarded = fleet::guarded_homes(&runtime.paths);
        let chosen = folder.clone();
        bounded(move || fleet::folder_problem(&chosen, &guarded), None).unwrap_or(Some(LATE))
    };
    if let Some(problem) = problem {
        let mut found = match refused_here(Refusal::WordingInvalid, runtime) {
            Value::Object(map) => map,
            _ => unreachable!("an object"),
        };
        found.insert(Str::new("problem"), text(problem));
        return Ok(Value::Object(found));
    }
    let wrote = (|| -> Result<(Value, Value)> {
        let words = call(runtime, "wordings", &[text(CAPABILITY)], &[])?;
        let (was_alias, was_folder) = (wording(&words, WordingKey::FleetAlias), wording(&words, WordingKey::FleetFolder));
        let dashboard = text("dashboard");
        let generation = call(
            runtime,
            "set_wording",
            &[text(CAPABILITY), text(WordingKey::FleetAlias.as_str()), alias.clone()],
            &[("generation", asked.clone()), ("actor", dashboard.clone())],
        )?;
        call(
            runtime,
            "set_wording",
            &[text(CAPABILITY), text(WordingKey::FleetFolder.as_str()), folder.clone()],
            &[("generation", generation), ("actor", dashboard)],
        )?;
        for key in [OptionKey::LastFleetWrite, OptionKey::FleetWaiting, OptionKey::FleetWroteAt] {
            call(runtime, "unstamp", &[text(CAPABILITY), text(key.as_str())], &[])?;
        }
        if !car_machine::pyval::eq(&was_folder, folder) {
            fleet::forget_seen(&runtime.paths);
        }
        Ok((was_alias, was_folder))
    })();
    let (was_alias, was_folder) = match wrote {
        Ok(found) => found,
        Err(error) if error.is_state() => return Ok(refused_here(Refusal::StateUnavailable, runtime)),
        Err(error) => return Err(error),
    };
    if car_machine::pyval::truthy(&was_alias)
        && !car_machine::pyval::eq(&was_alias, alias)
        && car_machine::pyval::eq(&was_folder, folder)
        && fleet::alias_valid(&was_alias)
    {
        let (folder, old) = (crate::state::py::py_str(folder), crate::state::py::py_str(&was_alias));
        let _ = bounded(move || fleet::remove_old_name(&folder, &old), None);
    }
    view(runtime)
}
