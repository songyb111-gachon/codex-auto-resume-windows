//! The probe's ops over the two capabilities' codes (`engine/account`, `engine/autoswitch`): each code made with
//! scripted seams over a real advanced state in a scratch home (seeded by the same state calls on both sides), driven
//! through its looks, and the state read back by the same calls.

use std::cell::RefCell;
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex};

use car_adv::codex::authfile::Fault;
use car_adv::codex::swap::World;
use car_adv::engine::{account as watch, autoswitch};
use car_adv::jsonx::object;
use car_adv::state::calls::{self, Call};
use car_adv::state::scoped::Scoped;
use car_adv::state::seam::Tokens;
use car_adv::state::session::AdvancedState;
use car_machine::json::{Map, Value};
use car_policy::plug::{ReadFailed, View};

use crate::script::{Counter, Script, log, rel, text};
use crate::{Out, arg, folder};

#[derive(Debug)]
struct Links;

impl car_config::Links for Links {
    fn is_symlink(&self, path: &Path) -> bool {
        car_platform::links::is_symlink(path)
    }
}

static CLOCK: Mutex<f64> = Mutex::new(0.0);

fn now() -> f64 {
    *CLOCK
        .lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner)
}

fn set_now(at: f64) {
    *CLOCK
        .lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner) = at;
}

fn state_of(home: &Path) -> (AdvancedState, car_config::Paths) {
    let no_env = |_: &str| None;
    let text = home.to_string_lossy().into_owned();
    let paths = car_config::Paths::new(
        Some(&text),
        &text,
        &no_env,
        car_config::Os::here(false, Arc::new(Links)),
    )
    .expect("the home's paths");
    let registry = Arc::new(car_adv::registry::shipped(false).expect("the shipped registry"));
    let state = AdvancedState::new(
        paths.clone(),
        registry,
        Box::new(now),
        Arc::new(Counter) as Arc<dyn Tokens>,
    );
    (state, paths)
}

fn method_call(state: &AdvancedState, entry: &Value) -> Result<Value, Fault> {
    let Value::Array(parts) = entry else {
        return Ok(Value::Null);
    };
    let name = car_machine::pytext::py_str(arg(parts, 0));
    let args = match arg(parts, 1) {
        Value::Array(items) => items.clone(),
        _ => Vec::new(),
    };
    let kwargs = match arg(parts, 2) {
        Value::Object(map) => map.clone(),
        _ => Map::new(),
    };
    calls::call(
        state,
        &name,
        Call {
            args: &args,
            kwargs: &kwargs,
        },
    )
    .map_err(|error| Fault::new("StateError", &format!("{error:?}")))
}

fn seed(state: &AdvancedState, seeds: &Value) -> Result<(), Fault> {
    if let Value::Array(entries) = seeds {
        for entry in entries {
            method_call(state, entry)?;
        }
    }
    Ok(())
}

fn reads(state: &AdvancedState, reads: &Value) -> Result<Value, Fault> {
    let mut out = Vec::new();
    if let Value::Array(entries) = reads {
        for entry in entries {
            out.push(method_call(state, entry)?);
        }
    }
    Ok(Value::Array(out))
}

struct ProbeView(RefCell<Script>);

impl View for ProbeView {
    fn records_in(&self, _states: &[&str]) -> Result<Vec<Value>, ReadFailed> {
        log(vec![text("records_in")]);
        match self
            .0
            .borrow_mut()
            .take("records", Value::Array(Vec::new()))
        {
            Ok(Value::Array(rows)) => Ok(rows),
            _ => Err(ReadFailed("RuntimeError")),
        }
    }
    fn settings(&self) -> Result<Value, ReadFailed> {
        log(vec![text("settings")]);
        self.0
            .borrow_mut()
            .take("settings", Value::Null)
            .map_err(|_| ReadFailed("RuntimeError"))
    }
}

struct Secrets(Mutex<Script>);

impl watch::SaltStore for Secrets {
    fn read(&self, capability: &str, name: &str) -> Result<Option<String>, Fault> {
        log(vec![text("secret.read"), text(capability), text(name)]);
        let found = self
            .0
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .take("read", Value::Null)?;
        Ok(match found {
            Value::Str(salt) => salt.as_str().map(str::to_owned),
            _ => None,
        })
    }
    fn write(&self, capability: &str, name: &str, secret: &str) -> Result<(), Fault> {
        log(vec![
            text("secret.write"),
            text(capability),
            text(name),
            text(secret),
        ]);
        self.0
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .take("write", Value::Null)?;
        Ok(())
    }
    fn delete(&self, capability: &str, name: &str) -> Result<bool, Fault> {
        log(vec![text("secret.delete"), text(capability), text(name)]);
        let found = self
            .0
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .take("delete", Value::Bool(true))?;
        Ok(car_machine::pyval::truthy(&found))
    }
}

fn shared(value: &Value) -> Arc<Mutex<Script>> {
    Arc::new(Mutex::new(Script::new(value)))
}

fn take(script: &Arc<Mutex<Script>>, kind: &str, default: Value) -> Result<Value, Fault> {
    script
        .lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner)
        .take(kind, default)
}

fn unknown() -> Value {
    object([
        ("present", Value::Null),
        ("plan_word", Value::Null),
        ("email", Value::Null),
        ("kind", Value::Null),
    ])
}

fn ea_look(args: &[Value]) -> Out {
    let home = folder(arg(args, 0));
    let (state, _paths) = state_of(&home);
    set_now(0.0);
    seed(&state, arg(args, 1))?;
    let script = shared(arg(args, 2));
    let (reading, holding, owning) = (
        Arc::clone(&script),
        Arc::clone(&script),
        Arc::clone(&script),
    );
    let seams = watch::Seams {
        read: Box::new(move || {
            log(vec![text("read")]);
            take(&reading, "read", unknown()).unwrap_or(Value::Null)
        }),
        secrets: Box::new(Secrets(Mutex::new(Script::new(&match arg(args, 2) {
            Value::Object(map) => map.get("secrets").cloned().unwrap_or(Value::Null),
            _ => Value::Null,
        })))),
        hold: Box::new(move |keys: &[String], at: f64| {
            log(vec![
                text("hold"),
                Value::Array(keys.iter().map(|key| text(key)).collect()),
                Value::Float(at),
            ]);
            let found = take(&holding, "hold", Value::from(0))?;
            Ok(car_adv::state::py::small(&found).unwrap_or(0))
        }),
        ours: Box::new(move |identity: &Value, after: &Value| {
            log(vec![text("ours"), identity.clone(), after.clone()]);
            car_machine::pyval::truthy(
                &take(&owning, "ours", Value::Bool(false)).unwrap_or(Value::Null),
            )
        }),
        tokens: Arc::new(Counter),
    };
    let code = watch::AccountWatch::new(seams);
    let view = ProbeView(RefCell::new(Script::new(arg(args, 3))));
    let on = || true;
    let scoped = Scoped {
        state: &state,
        capability: text(watch::CAPABILITY),
        on: Some(&on),
        verdict: None,
        armed: None,
    };
    if let Value::Array(steps) = arg(args, 4) {
        for step in steps {
            let at = car_machine::pytext::to_float(step).unwrap_or(0.0);
            set_now(at);
            if let Err(fault) = code.look(&scoped, &view, at) {
                log(vec![text("raised"), crate::class_of(&fault)]);
            }
        }
    }
    Ok(object([
        ("notice", code.notice_view()),
        ("reads", reads(&state, arg(args, 5))?),
    ]))
}

fn ea_forget(args: &[Value]) -> Out {
    let home = folder(arg(args, 0));
    let (state, _paths) = state_of(&home);
    set_now(0.0);
    seed(&state, arg(args, 1))?;
    let secrets = Secrets(Mutex::new(Script::new(arg(args, 2))));
    let done = watch::forget(&state, &secrets)?;
    Ok(object([
        ("done", Value::Bool(done)),
        ("reads", reads(&state, arg(args, 3))?),
    ]))
}

// ------------------------------------------------------------------------------------------------ autoswitch
/// `swap`'s world for the code: the same stand-ins as `store::with_world`, owned so the code can hold them.
struct ProbeWorld {
    inventory: Box<dyn Fn() -> Option<Vec<Value>> + Send + Sync>,
    running: Box<dyn Fn() -> Option<bool> + Send + Sync>,
    own: Box<dyn Fn() -> Vec<Value> + Send + Sync>,
    clock: Box<dyn Fn() -> f64 + Send + Sync>,
    sleep: Box<dyn Fn(f64) + Send + Sync>,
    system: car_codex::system::Platform,
}

fn pause(seconds: f64) {
    log(vec![text("pause"), Value::Float(seconds)]);
}

fn private(directory: &Path) -> bool {
    log(vec![text("private"), text(&rel(directory))]);
    true
}

impl ProbeWorld {
    fn new(spec: &Value) -> ProbeWorld {
        let script = shared(spec);
        let own = match take(&script, "own", Value::Array(Vec::new())) {
            Ok(Value::Array(items)) => items,
            _ => Vec::new(),
        };
        let clock = Arc::new(Mutex::new(0.0f64));
        let (listing, asking) = (Arc::clone(&script), Arc::clone(&script));
        let (reading, sleeping) = (Arc::clone(&clock), Arc::clone(&clock));
        ProbeWorld {
            inventory: Box::new(move || {
                log(vec![text("inventory")]);
                match take(&listing, "inventory", Value::Array(Vec::new())) {
                    Ok(Value::Array(rows)) => Some(rows),
                    _ => None,
                }
            }),
            running: Box::new(move || {
                log(vec![text("app_running")]);
                match take(&asking, "app_running", Value::Bool(false)) {
                    Ok(Value::Bool(on)) => Some(on),
                    _ => None,
                }
            }),
            own: Box::new(move || own.clone()),
            clock: Box::new(move || {
                *reading
                    .lock()
                    .unwrap_or_else(std::sync::PoisonError::into_inner)
            }),
            sleep: Box::new(move |seconds: f64| {
                log(vec![text("sleep"), Value::Float(seconds)]);
                *sleeping
                    .lock()
                    .unwrap_or_else(std::sync::PoisonError::into_inner) += seconds;
            }),
            system: car_codex::system::Platform::new(),
        }
    }
}

impl autoswitch::Worldly for ProbeWorld {
    fn world(&self) -> World<'_> {
        World {
            tokens: &Counter,
            private: &private,
            pause: &pause,
            inventory: self.inventory.as_ref(),
            own: self.own.as_ref(),
            system: &self.system,
            app_running: self.running.as_ref(),
            clock: self.clock.as_ref(),
            sleep: self.sleep.as_ref(),
        }
    }
}

struct SendSessions(Mutex<Script>);

struct SendSession<'a> {
    script: &'a Mutex<Script>,
    home: Option<PathBuf>,
}

impl car_adv::codex::account::Session for SendSession<'_> {
    fn call(&mut self, method: &str, params: Value) -> Result<Value, Fault> {
        log(vec![text("call"), text(method), params]);
        let mut script = self
            .script
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        let fresh = script.take(&format!("refresh:{method}"), Value::Null)?;
        if let (Some(fresh), Some(home)) = (crate::script::bytes(&fresh), &self.home) {
            std::fs::write(home.join("auth.json"), fresh).map_err(|error| Fault::os(&error))?;
        }
        script.take(method, Value::Null)
    }
}

impl Drop for SendSession<'_> {
    fn drop(&mut self) {
        log(vec![text("exit")]);
    }
}

impl car_adv::codex::account::Opener for SendSessions {
    fn open(
        &self,
        home: Option<&Path>,
    ) -> Result<Box<dyn car_adv::codex::account::Session + '_>, Fault> {
        log(vec![
            text("enter"),
            home.map_or(Value::Null, |home| text(&rel(home))),
        ]);
        self.0
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .take("open", Value::Null)?;
        Ok(Box::new(SendSession {
            script: &self.0,
            home: home.map(Path::to_path_buf),
        }))
    }
}

fn restart_seam(spec: &Value) -> autoswitch::RestartSeam {
    let mut script = Script::new(spec);
    Box::new(move |between: &mut dyn FnMut() -> Result<(), Fault>| {
        log(vec![text("restart")]);
        let mut fallback = Map::new();
        fallback.insert("between".into(), Value::Bool(true));
        fallback.insert(
            "answer".into(),
            Value::Array(vec![text("restarted"), text("closed")]),
        );
        let step = script.take("restart", Value::Object(fallback))?;
        let get = |key: &str| match &step {
            Value::Object(map) => map.get(key).cloned().unwrap_or(Value::Null),
            _ => Value::Null,
        };
        if let Value::Array(both) = get("write")
            && both.len() == 2
        {
            let data = crate::script::bytes(&both[1]).unwrap_or_default();
            std::fs::write(folder(&both[0]).join("auth.json"), data)
                .map_err(|error| Fault::os(&error))?;
        }
        if car_machine::pyval::truthy(&get("between"))
            && let Err(fault) = between()
        {
            log(vec![text("between raised"), crate::class_of(&fault)]);
        }
        Ok(match get("answer") {
            Value::Array(both) if both.len() == 2 => Some((both[0].clone(), both[1].clone())),
            _ => None,
        })
    })
}

fn auto_code(
    args: &[Value],
    paths: &car_config::Paths,
) -> Result<(autoswitch::AutoSwitch, Vec<String>), Fault> {
    let spec = arg(args, 2);
    let (store, ids) = crate::store::store_of(spec)?;
    let seams_spec = arg(args, 3);
    let field = |key: &str| match seams_spec {
        Value::Object(map) => map.get(key).cloned().unwrap_or(Value::Null),
        _ => Value::Null,
    };
    let codex = folder(match spec {
        Value::Object(map) => map.get("codex").unwrap_or(&Value::Null),
        _ => &Value::Null,
    });
    let reader = shared(&field("reader"));
    let idle = shared(&field("idle"));
    let busy = shared(&field("busy"));
    let restart = field("restart");
    let code = autoswitch::AutoSwitch::new(autoswitch::Seams {
        store,
        home: Box::new(move || Ok(codex.clone())),
        session_for: Box::new(SendSessions(Mutex::new(Script::new(&field("session"))))),
        read_real: Box::new(move || {
            log(vec![text("read")]);
            take(&reader, "read", unknown()).unwrap_or(Value::Null)
        }),
        world: Box::new(ProbeWorld::new(&field("world"))),
        hands: autoswitch::Hands {
            restart: if matches!(restart, Value::Null) {
                None
            } else {
                Some(restart_seam(&restart))
            },
            idle: Box::new(move || {
                log(vec![text("idle")]);
                take(&idle, "idle", Value::Float(1000.0)).unwrap_or(Value::Null)
            }),
            busy: Box::new(move || {
                log(vec![text("busy")]);
                let found = take(&busy, "busy", Value::Array(Vec::new()))?;
                Ok(car_machine::pyval::truthy(&found))
            }),
            paths: paths.clone(),
        },
    });
    Ok((code, ids))
}

fn ec_look(args: &[Value]) -> Out {
    let home = folder(arg(args, 0));
    let (state, paths) = state_of(&home);
    set_now(0.0);
    seed(&state, arg(args, 1))?;
    let (code, ids) = auto_code(args, &paths)?;
    let view = ProbeView(RefCell::new(Script::new(arg(args, 4))));
    let on = || true;
    let scoped = Scoped {
        state: &state,
        capability: text(autoswitch::CAPABILITY),
        on: Some(&on),
        verdict: None,
        armed: None,
    };
    let mut scheduled = Vec::new();
    if let Value::Array(steps) = arg(args, 5) {
        for step in steps {
            let (kind, at) = match step {
                Value::Array(parts) => (
                    car_machine::pytext::py_str(arg(parts, 0)),
                    car_machine::pytext::to_float(arg(parts, 1)).unwrap_or(0.0),
                ),
                other => (
                    "look".to_owned(),
                    car_machine::pytext::to_float(other).unwrap_or(0.0),
                ),
            };
            set_now(at);
            let outcome = match kind.as_str() {
                "settle" => code.settle(&scoped),
                "put_in" | "manual" => {
                    let target = match step {
                        Value::Array(parts) => arg(parts, 2).clone(),
                        _ => Value::Null,
                    };
                    let target = match &target {
                        Value::Object(map) if map.contains_key("saved") => {
                            car_adv::state::py::small(&map["saved"])
                                .and_then(|at| ids.get(at as usize).cloned())
                                .map_or(Value::Null, |id| text(&id))
                        }
                        other => other.clone(),
                    };
                    match code.put_in(&target, at, kind == "manual") {
                        Ok((outcome, closed)) => {
                            scheduled.push(Value::Array(vec![text(outcome), Value::Array(closed)]));
                            Ok(())
                        }
                        Err(fault) => Err(fault),
                    }
                }
                "schedule" => {
                    let (record, due) = match step {
                        Value::Array(parts) => (arg(parts, 2).clone(), arg(parts, 3).clone()),
                        _ => (Value::Null, Value::Null),
                    };
                    match code.schedule_in(&scoped, &record, &due) {
                        Ok(said) => {
                            scheduled.push(said.to_value().unwrap_or(text("DEFER")));
                            Ok(())
                        }
                        Err(raised) => {
                            scheduled.push(object([("raised", text(&raised.class))]));
                            Ok(())
                        }
                    }
                }
                _ => code.look(&scoped, &view, at),
            };
            if let Err(fault) = outcome {
                log(vec![text("raised"), crate::class_of(&fault)]);
            }
        }
    }
    Ok(object([
        ("memory", code.memory()),
        ("answers", Value::Array(scheduled)),
        ("reads", reads(&state, arg(args, 6))?),
    ]))
}

pub fn run(op: &str, args: &[Value]) -> Out {
    match op {
        "ea.look" => ea_look(args),
        "ea.forget" => ea_forget(args),
        "ec.look" => ec_look(args),
        _ => Err(Fault::new("UnknownOp", op)),
    }
}
