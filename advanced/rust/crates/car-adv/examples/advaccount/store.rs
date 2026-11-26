//! The probe's ops over the saved accounts (`swap`'s): a store of the reference's own shape - S7.1a's stand-in seal,
//! a scripted lock, the shared token counter, a pinned clock - and `swap`'s world as scripted stand-ins.

use std::cell::{Cell, RefCell};
use std::path::Path;
use std::sync::{Arc, Mutex};

use car_adv::codex::authfile::Fault;
use car_adv::codex::swap::{self, World};
use car_adv::profiles::Profiles;
use car_adv::state::seam::Tokens;
use car_adv::state::seam::accounts::{Failure, Host};
use car_machine::json::Value;

use crate::script::{Counter, Script, log, rel, text, unhex};
use crate::{Out, Sessions, arg, folder, root};

/// The saved accounts' host of the diff: `SEALED:` and the bytes, a lock that answers from the script, the private
/// access list logged, the token counter.
pub struct ProbeHost {
    locks: Mutex<Vec<String>>,
}

struct Unlock;

impl Drop for Unlock {
    fn drop(&mut self) {
        log(vec![text("unlock")]);
    }
}

impl Host for ProbeHost {
    fn seal(&self, data: &[u8]) -> Result<Vec<u8>, Failure> {
        let mut sealed = b"SEALED:".to_vec();
        sealed.extend_from_slice(data);
        Ok(sealed)
    }
    fn open(&self, blob: &[u8]) -> Result<Vec<u8>, Failure> {
        blob.strip_prefix(b"SEALED:")
            .map(<[u8]>::to_vec)
            .ok_or_else(|| Failure("not sealed".into()))
    }
    fn lock(&self, _directory: &Path, seconds: f64) -> Result<Box<dyn std::any::Any>, Failure> {
        let word = {
            let mut locks = self
                .locks
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner);
            if locks.len() > 1 {
                locks.remove(0)
            } else {
                locks.first().cloned().unwrap_or_else(|| "free".to_owned())
            }
        };
        log(vec![text("lock?"), Value::Float(seconds)]);
        if word == "held" {
            return Err(Failure("held".into()));
        }
        log(vec![text("lock")]);
        Ok(Box::new(Unlock))
    }
    fn private(&self, directory: &Path) {
        log(vec![text("private"), text(&rel(directory))]);
    }
    fn sweep(&self, _directory: &Path, _codex_home: Option<&Path>) {}
    fn unwind(&self, _intent: &Value, _codex_home: Option<&Path>) -> bool {
        true
    }
    fn token(&self, count: usize) -> String {
        Counter.hex(count)
    }
}

fn get<'a>(value: &'a Value, key: &str) -> &'a Value {
    static NULL: Value = Value::Null;
    match value {
        Value::Object(map) => map.get(key).unwrap_or(&NULL),
        _ => &NULL,
    }
}

fn ids_at(ids: &[String], value: &Value) -> Value {
    match value {
        Value::Int(_) => car_adv::state::py::small(value)
            .and_then(|at| ids.get(at as usize))
            .map_or(Value::Null, |id| text(id)),
        other => other.clone(),
    }
}

/// `store_of(spec)`: the store, every account of `saved` saved, every update made, the intent begun; the log emptied.
pub fn store_of(spec: &Value) -> Result<(Profiles, Vec<String>), Fault> {
    let locks = match get(spec, "lock") {
        Value::Array(items) => items.iter().map(car_machine::pytext::py_str).collect(),
        _ => vec!["free".to_owned()],
    };
    let store = Profiles::new(
        &folder(get(spec, "home")),
        Arc::new(ProbeHost {
            locks: Mutex::new(locks),
        }),
        Box::new(crate::script::clock),
    );
    if let Value::Object(raw) = get(spec, "raw") {
        std::fs::create_dir_all(&store.directory).map_err(|error| Fault::os(&error))?;
        for (name, data) in raw {
            let data = crate::script::bytes(data).unwrap_or_default();
            std::fs::write(
                store.directory.join(name.as_str().unwrap_or_default()),
                data,
            )
            .map_err(|error| Fault::os(&error))?;
        }
    }
    let mut ids = Vec::new();
    if let Value::Array(saved) = get(spec, "saved") {
        for each in saved {
            let Value::Array(parts) = each else { continue };
            let data = crate::script::bytes(arg(parts, 2)).unwrap_or_default();
            ids.push(store.save(&data, arg(parts, 0), arg(parts, 1))?);
        }
    }
    if let Value::Array(updates) = get(spec, "updates") {
        for each in updates {
            let Value::Array(parts) = each else { continue };
            let id = ids_at(&ids, arg(parts, 0));
            let fields: Vec<(String, Value)> = match unhex(arg(parts, 1)) {
                Value::Object(map) => map
                    .iter()
                    .map(|(key, value)| {
                        (key.as_str().unwrap_or_default().to_owned(), value.clone())
                    })
                    .collect(),
                _ => Vec::new(),
            };
            store.update(&id, &fields)?;
        }
    }
    let intent = get(spec, "intent");
    if !matches!(intent, Value::Null) {
        let field = |key: &str, default: Value| match get(intent, key) {
            Value::Null if !matches!(intent, Value::Object(map) if map.contains_key(key)) => {
                default
            }
            other => unhex(other),
        };
        store.begin(
            &ids_at(&ids, get(intent, "from")),
            &ids_at(&ids, get(intent, "to")),
            &field("step", text("swap")),
            &field("tries", Value::from(0)),
            &field("put_in", Value::Null),
            &field("previous", Value::Null),
            &field("to_email", Value::Null),
        )?;
    }
    crate::script::take_log();
    Ok((store, ids))
}

fn target_of(value: &Value, ids: &[String]) -> Value {
    match get(value, "saved") {
        Value::Null => value.clone(),
        at => ids_at(ids, at),
    }
}

/// `swap`'s world from a script: the process list, whether the app runs, this process's own servers, the clock.
pub fn with_world<T>(spec: &Value, body: impl FnOnce(&World) -> T) -> T {
    let script = RefCell::new(Script::new(spec));
    let clock = Cell::new(0.0f64);
    let own = match script.borrow_mut().take("own", Value::Array(Vec::new())) {
        Ok(Value::Array(items)) => items,
        _ => Vec::new(),
    };
    let system = car_codex::system::Platform::new();
    let inventory = || {
        log(vec![text("inventory")]);
        match script
            .borrow_mut()
            .take("inventory", Value::Array(Vec::new()))
        {
            Ok(Value::Array(rows)) => Some(rows),
            _ => None,
        }
    };
    let running = || {
        log(vec![text("app_running")]);
        match script.borrow_mut().take("app_running", Value::Bool(false)) {
            Ok(Value::Bool(on)) => Some(on),
            _ => None,
        }
    };
    let own_pids = || own.clone();
    let now = || clock.get();
    let sleep = |seconds: f64| {
        log(vec![text("sleep"), Value::Float(seconds)]);
        clock.set(clock.get() + seconds);
    };
    let pause = |seconds: f64| log(vec![text("pause"), Value::Float(seconds)]);
    let private = |directory: &Path| {
        log(vec![text("private"), text(&rel(directory))]);
        true
    };
    let world = World {
        tokens: &Counter,
        private: &private,
        pause: &pause,
        inventory: &inventory,
        own: &own_pids,
        system: &system,
        app_running: &running,
        clock: &now,
        sleep: &sleep,
    };
    body(&world)
}

type Between<'a> = &'a mut dyn FnMut() -> Result<(), Fault>;

/// `restart_of(script)`: a restart that logs, calls `between` where the step says (logging what it raised) and answers
/// the step's (outcome, how) or None.
fn restart_of(script: &Value) -> impl FnMut(Between) -> Result<Option<(Value, Value)>, Fault> {
    let mut script = Script::new(script);
    move |between: Between| {
        log(vec![text("restart")]);
        let mut fallback = car_machine::json::Map::new();
        fallback.insert("between".into(), Value::Bool(true));
        fallback.insert(
            "answer".into(),
            Value::Array(vec![text("restarted"), text("closed")]),
        );
        let step = script.take("restart", Value::Object(fallback))?;
        if let Value::Array(both) = get(&step, "write")
            && both.len() == 2
        {
            let data = crate::script::bytes(&both[1]).unwrap_or_default();
            std::fs::write(folder(&both[0]).join("auth.json"), data)
                .map_err(|error| Fault::os(&error))?;
        }
        if car_machine::pyval::truthy(get(&step, "between"))
            && let Err(fault) = between()
        {
            log(vec![text("between raised"), crate::class_of(&fault)]);
        }
        Ok(match get(&step, "answer") {
            Value::Array(both) if both.len() == 2 => Some((both[0].clone(), both[1].clone())),
            _ => None,
        })
    }
}

fn number(value: &Value) -> Option<f64> {
    match value {
        Value::Null => None,
        other => car_machine::pytext::to_float(other).ok(),
    }
}

pub fn run(op: &str, args: &[Value]) -> Out {
    match op {
        "sw.other_engines" => {
            let rows = match arg(args, 0) {
                Value::Array(items) => Some(items.clone()),
                _ => None,
            };
            let own = match arg(args, 2) {
                Value::Array(items) => items.clone(),
                _ => Vec::new(),
            };
            let system = car_codex::system::Platform::new();
            Ok(Value::Bool(swap::other_engines(
                rows.as_deref(),
                car_machine::pyval::truthy(arg(args, 1)),
                &own,
                &system,
            )?))
        }
        "sw.engines_gone" => with_world(arg(args, 0), |world| {
            Ok(Value::Bool(swap::engines_gone(
                world,
                number(arg(args, 1)).unwrap_or(0.0),
            )?))
        }),
        "sw.read_answer" => with_world(arg(args, 0), |world| {
            let read = crate::reader(std::rc::Rc::new(RefCell::new(Script::new(arg(args, 1)))));
            let tries = car_adv::state::py::small(arg(args, 2)).unwrap_or(0).max(0) as usize;
            swap::read_answer(world, &read, tries)
        }),
        "sw.read_profile" => {
            let (store, ids) = store_of(arg(args, 0))?;
            with_world(arg(args, 4), |world| {
                let sessions = Sessions(RefCell::new(Script::new(arg(args, 2))));
                Ok(Value::Object(swap::read_profile(
                    world,
                    &store,
                    &target_of(arg(args, 1), &ids),
                    &sessions,
                    number(arg(args, 3)),
                )?))
            })
        }
        "sw.switch" => {
            let spec = arg(args, 0);
            let (store, ids) = store_of(spec)?;
            with_world(arg(args, 5), |world| {
                let mut restart = restart_of(arg(args, 2));
                let read = crate::reader(std::rc::Rc::new(RefCell::new(Script::new(arg(args, 3)))));
                let outcome = swap::switch(
                    world,
                    &store,
                    &folder(get(spec, "codex")),
                    &target_of(arg(args, 1), &ids),
                    &mut restart,
                    &read,
                    number(arg(args, 4)),
                )?;
                Ok(text(outcome))
            })
        }
        "sw.recover" => {
            let spec = arg(args, 0);
            let (store, _ids) = store_of(spec)?;
            with_world(arg(args, 3), |world| {
                let read = crate::reader(std::rc::Rc::new(RefCell::new(Script::new(arg(args, 1)))));
                let mut restart = restart_of(arg(args, 2));
                let hand: Option<&mut swap::Restart> = if matches!(arg(args, 2), Value::Null) {
                    None
                } else {
                    Some(&mut restart)
                };
                let outcome =
                    swap::recover(world, &store, &folder(get(spec, "codex")), &read, hand)?;
                Ok(outcome.map_or(Value::Null, text))
            })
        }
        "sw.unwind" => {
            let spec = arg(args, 0);
            let (store, _ids) = store_of(spec)?;
            with_world(arg(args, 1), |world| {
                let home = match get(spec, "codex") {
                    Value::Null => None,
                    other => Some(folder(other)),
                };
                Ok(Value::Bool(swap::unwind(world, &store, home.as_deref())?))
            })
        }
        "sw.save_current" => {
            let spec = arg(args, 0);
            let (store, _ids) = store_of(spec)?;
            let read = crate::reader(std::rc::Rc::new(RefCell::new(Script::new(arg(args, 1)))));
            Ok(
                swap::save_current(&store, &folder(get(spec, "codex")), &read)?
                    .map_or(Value::Null, |id| text(&id)),
            )
        }
        "sw.add_by_login" => {
            let spec = arg(args, 0);
            let (store, _ids) = store_of(spec)?;
            with_world(&Value::Null, |world| {
                let made = std::rc::Rc::new(RefCell::new(Script::new(arg(args, 1))));
                let backend_for = BackendFor(made);
                let sessions = Sessions(RefCell::new(Script::new(arg(args, 3))));
                let runner = crate::Runner(RefCell::new(Script::new(arg(args, 2))));
                Ok(swap::add_by_login(
                    world,
                    &store,
                    &backend_for,
                    &sessions,
                    &runner,
                    number(arg(args, 4)),
                )?
                .map_or(Value::Null, |id| text(&id)))
            })
        }
        _ => Err(Fault::new("UnknownOp", op)),
    }
}

struct BackendFor(std::rc::Rc<RefCell<Script>>);

impl swap::BackendFor for BackendFor {
    fn backend(
        &self,
        home: &Path,
    ) -> Result<Box<dyn car_adv::codex::account::Backend + '_>, Fault> {
        log(vec![text("backend"), text(&rel(home))]);
        self.0.borrow_mut().take("make", Value::Null)?;
        Ok(Box::new(crate::Backend {
            script: std::rc::Rc::clone(&self.0),
            home: Some(home.to_path_buf()),
        }))
    }
}

#[allow(dead_code)]
fn unused() -> std::path::PathBuf {
    root()
}
