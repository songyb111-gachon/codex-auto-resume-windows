//! The scripted world of the probe: everything the S7.2d codes read of the outside, answered from the request's
//! `world` and logged in order, as `tests/rustdiff/advusage.py`'s reference stands it in.

use std::collections::HashMap;
use std::sync::{Arc, Mutex, PoisonError};

use car_adv::capabilities::Raised;
use car_adv::codex::inuse::{self, Looked};
use car_adv::codex::ipc::Gate;
use car_adv::codex::session::{Channel, SessionError};
use car_adv::engine::{usage, usagestop};
use car_adv::jsonx::object;
use car_adv::statement::Catalogs;
use car_config::Paths;
use car_machine::json::{Map, Value};
use car_policy::plug::{HookFailed, ReadFailed, View};

pub fn get<'a>(map: &'a Map, name: &str) -> &'a Value {
    static NULL: Value = Value::Null;
    map.get(name).unwrap_or(&NULL)
}

fn at<'a>(value: &'a Value, name: &str) -> &'a Value {
    static NULL: Value = Value::Null;
    match value {
        Value::Object(map) => map.get(name).unwrap_or(&NULL),
        _ => &NULL,
    }
}

fn text(value: &Value) -> String {
    car_machine::pytext::py_str(value)
}

/// `{"raise": class}`: the class a scripted answer raises, if it is one.
fn raise_of(value: &Value) -> Option<String> {
    match at(value, "raise") {
        Value::Str(class) => Some(class.as_str().unwrap_or_default().to_owned()),
        _ => None,
    }
}

pub struct Shared {
    world: Mutex<Value>,
    log: Mutex<Vec<Value>>,
    cursors: Mutex<HashMap<String, usize>>,
    catalogs: Arc<Catalogs>,
}

impl Shared {
    pub fn new(world: Value, catalogs: Arc<Catalogs>) -> Arc<Shared> {
        let world = match world {
            Value::Object(_) => world,
            _ => Value::Object(Map::new()),
        };
        Arc::new(Shared {
            world: Mutex::new(world),
            log: Mutex::new(Vec::new()),
            cursors: Mutex::new(HashMap::new()),
            catalogs,
        })
    }

    pub fn merge(&self, changes: &Map) {
        let mut held = self.world.lock().unwrap_or_else(PoisonError::into_inner);
        if let Value::Object(map) = &mut *held {
            for (key, value) in changes {
                map.insert(key.clone(), value.clone());
                self.cursors
                    .lock()
                    .unwrap_or_else(PoisonError::into_inner)
                    .retain(|name, _| !name.starts_with(key.as_str().unwrap_or_default()));
            }
        }
    }

    pub fn world(&self) -> Value {
        self.world
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
            .clone()
    }

    pub fn note(&self, entry: Vec<Value>) {
        self.log
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
            .push(Value::Array(entry));
    }

    pub fn take_log(&self) -> Value {
        Value::Array(std::mem::take(
            &mut *self.log.lock().unwrap_or_else(PoisonError::into_inner),
        ))
    }

    /// The next item of the list `world[part][name]`, or None past its end.
    fn next(&self, part: &str, name: &str) -> Option<Value> {
        let world = self.world();
        let Value::Array(items) = at(at(&world, part), name) else {
            return None;
        };
        let key = format!("{part}.{name}");
        let mut cursors = self.cursors.lock().unwrap_or_else(PoisonError::into_inner);
        let index = cursors.entry(key).or_insert(0);
        let found = items.get(*index).cloned();
        *index += 1;
        found
    }

    fn permits(&self) -> bool {
        !matches!(at(&self.world(), "guard"), Value::Bool(false))
    }

    /// Core's errand guard: its answer the world's `guard` (true unless false).
    pub fn guards(
        &self,
    ) -> impl FnMut(&mut dyn FnMut(bool) -> Value) -> Result<Value, HookFailed> + '_ {
        move |body| Ok(body(self.permits()))
    }

    pub fn world_of(self: &Arc<Self>) -> usage::World {
        let codex = Arc::new(ScriptCodex(Arc::clone(self)));
        let home = Arc::clone(self);
        let locale = Arc::clone(self);
        let backend = Arc::clone(self);
        let open = Arc::clone(self);
        let switched = Arc::clone(self);
        let keys = Arc::new(Mutex::new(0u64));
        usage::World {
            catalogs: Arc::clone(&self.catalogs),
            clock: Arc::new(car_platform::localclock::Crt),
            locale: Arc::new(move |_: &Paths| match at(&locale.world(), "locale") {
                Value::Str(found) => Ok(found.as_str().unwrap_or_default().to_owned()),
                _ => Err(()),
            }),
            codex,
            home: Arc::new(move |_: &Paths| {
                let world = home.world();
                let found = at(&world, "home");
                if let Some(class) = raise_of(found) {
                    return Err(Raised::new(Box::leak(class.into_boxed_str())));
                }
                Ok(text(found))
            }),
            backend: Arc::new(move |_: &Paths| {
                let world = backend.world();
                let spec = at(&world, "backend").clone();
                if matches!(spec, Value::Null) {
                    return Err(Raised::new("AdapterError"));
                }
                if let Some(class) = raise_of(&spec) {
                    return Err(Raised::new(Box::leak(class.into_boxed_str())));
                }
                backend.note(vec![Value::from("backend.made")]);
                Ok(Box::new(ScriptBackend {
                    shared: Arc::clone(&backend),
                    spec,
                }) as Box<dyn usage::MeterBackend>)
            }),
            open: Arc::new(move |_: &Paths, capability: &str| {
                open.note(vec![Value::from("session.open"), Value::from(capability)]);
                let world = open.world();
                if raise_of(at(at(&world, "session"), "open")).is_some() {
                    return Err(SessionError::Adapter("backend_unavailable"));
                }
                Ok(Box::new(ScriptSession {
                    shared: Arc::clone(&open),
                    sequence: 0,
                }) as Box<dyn Channel>)
            }),
            keys: Arc::new(move || {
                let mut held = keys.lock().unwrap_or_else(PoisonError::into_inner);
                *held += 1;
                format!("00000000-0000-4000-8000-{held:012}")
            }),
            switched: Arc::new(move |_: &Paths| usage::number(at(&switched.world(), "switched"))),
            ipc: Arc::new(ScriptIpc(Arc::clone(self))),
        }
    }
}

pub struct ScriptView<'a>(pub &'a Arc<Shared>);

impl View for ScriptView<'_> {
    fn records_in(&self, _states: &[&str]) -> Result<Vec<Value>, ReadFailed> {
        let world = self.0.world();
        match at(at(&world, "view"), "records") {
            Value::Array(items) => Ok(items.clone()),
            Value::Str(_) => Err(ReadFailed("RuntimeError")),
            _ => Ok(Vec::new()),
        }
    }
    fn thread_enabled(&self, thread_id: &str) -> Result<bool, ReadFailed> {
        let world = self.0.world();
        match at(at(at(&world, "view"), "enabled"), thread_id) {
            Value::Bool(found) => Ok(*found),
            Value::Str(_) => Err(ReadFailed("RuntimeError")),
            _ => Ok(true),
        }
    }
    fn last_usage(&self) -> Value {
        at(at(&self.0.world(), "view"), "last_usage").clone()
    }
}

struct ScriptCodex(Arc<Shared>);

fn raised(class: String) -> Raised {
    Raised::new(Box::leak(class.into_boxed_str()))
}

impl usage::CodexReads for ScriptCodex {
    fn running(&self, _home: &str, _paths: &Paths) -> Result<Vec<String>, Raised> {
        self.0.note(vec![Value::from("turns.running")]);
        let world = self.0.world();
        let found = at(at(&world, "turns"), "running");
        if let Some(class) = raise_of(found) {
            return Err(raised(class));
        }
        Ok(match found {
            Value::Array(items) => items.iter().map(text).collect(),
            _ => Vec::new(),
        })
    }
    fn latest(&self, _home: &str, thread: &str) -> Result<Option<usage::TurnSeen>, Raised> {
        self.0
            .note(vec![Value::from("turns.latest"), Value::from(thread)]);
        let world = self.0.world();
        let found = at(at(at(&world, "turns"), "latest"), thread);
        if let Some(class) = raise_of(found) {
            return Err(raised(class));
        }
        Ok(match found {
            Value::Object(_) => Some(usage::TurnSeen {
                status: text(at(found, "status")),
                ordinal: at(found, "ordinal").clone(),
                turn_id: at(found, "turn_id").clone(),
            }),
            _ => None,
        })
    }
    fn between(
        &self,
        _home: &str,
        thread: &str,
        after: &Value,
        before: &Value,
    ) -> Result<i64, Raised> {
        self.0.note(vec![
            Value::from("turns.between"),
            Value::from(thread),
            after.clone(),
            before.clone(),
        ]);
        let world = self.0.world();
        let found = at(at(at(&world, "turns"), "between"), thread);
        if let Some(class) = raise_of(found) {
            return Err(raised(class));
        }
        Ok(usage::number(found).unwrap_or(0.0) as i64)
    }
    fn source(&self, _home: &str) -> Result<(), Raised> {
        let world = self.0.world();
        match raise_of(at(at(&world, "source"), "make")) {
            Some(class) => Err(raised(class)),
            None => Ok(()),
        }
    }
    fn source_latest(
        &self,
        _home: &str,
        thread: &str,
        widened: bool,
    ) -> Result<Option<Value>, Raised> {
        self.0.note(vec![
            Value::from("source.latest"),
            Value::from(thread),
            Value::Bool(widened),
        ]);
        let world = self.0.world();
        let found = at(at(at(&world, "source"), "latest"), thread);
        if let Some(class) = raise_of(found) {
            return Err(raised(class));
        }
        Ok(match found {
            Value::Object(_) => Some(found.clone()),
            _ => None,
        })
    }
}

struct ScriptBackend {
    shared: Arc<Shared>,
    spec: Value,
}

impl Looked for ScriptBackend {
    fn codex_exe(&self) -> Option<String> {
        Some(text(at(&self.spec, "codex_exe")))
    }
    fn served_elsewhere(&self) -> Vec<String> {
        match at(&self.spec, "served_elsewhere") {
            Value::Array(items) => items.iter().map(text).collect(),
            _ => Vec::new(),
        }
    }
}

impl usage::MeterBackend for ScriptBackend {
    fn app_identity(&mut self) -> Result<Option<Value>, Raised> {
        self.shared.note(vec![Value::from("backend.identity")]);
        match at(&self.spec, "identity") {
            Value::Str(word) if word.as_str() == Some("raise") => Err(Raised::new("AdapterError")),
            Value::Null => Ok(None),
            other => Ok(Some(other.clone())),
        }
    }
    fn app_look(&self) -> Option<String> {
        match at(&self.spec, "app_look") {
            Value::Str(word) => Some(word.as_str().unwrap_or_default().to_owned()),
            _ => None,
        }
    }
    fn compatible(&mut self) -> Result<(), Raised> {
        let found = self
            .shared
            .next("backend", "compatible")
            .unwrap_or(Value::from("ok"));
        self.shared
            .note(vec![Value::from("backend.compatible"), found.clone()]);
        if matches!(&found, Value::Str(word) if word.as_str() == Some("raise")) {
            return Err(Raised::new("AdapterError"));
        }
        Ok(())
    }
}

struct ScriptSession {
    shared: Arc<Shared>,
    sequence: i64,
}

impl ScriptSession {
    fn reply(&mut self) -> Result<Value, SessionError> {
        let found = self
            .shared
            .next("session", "replies")
            .unwrap_or(Value::Null);
        match raise_of(&found).as_deref() {
            Some("adapter") => {
                let code = text(at(&found, "code"));
                Err(SessionError::Adapter(Box::leak(code.into_boxed_str())))
            }
            Some("bycodex") => Err(SessionError::ByCodex {
                method: String::new(),
                code: at(&found, "code").clone().as_i64(),
            }),
            Some(_) => Err(SessionError::Raised("RuntimeError")),
            None => Ok(at(&found, "reply").clone()),
        }
    }
}

trait AsI64 {
    fn as_i64(&self) -> Option<i64>;
}

impl AsI64 for Value {
    fn as_i64(&self) -> Option<i64> {
        match self {
            Value::Int(int) => int.as_i64(),
            _ => None,
        }
    }
}

impl Channel for ScriptSession {
    fn enter(&mut self) -> Result<(), SessionError> {
        self.shared.note(vec![Value::from("session.enter")]);
        let world = self.shared.world();
        if raise_of(at(at(&world, "session"), "enter")).is_some() {
            return Err(SessionError::Adapter("app_server_failed"));
        }
        Ok(())
    }
    fn submit(&mut self, method: &str, params: Option<Value>) -> Result<i64, SessionError> {
        self.shared.note(vec![
            Value::from("session.submit"),
            Value::from(method),
            params.unwrap_or(Value::Null),
        ]);
        let world = self.shared.world();
        if let Some(class) = raise_of(at(at(&world, "session"), "submit")) {
            return Err(if class == "adapter" {
                SessionError::Adapter("protocol_write_failed")
            } else {
                SessionError::Raised("RuntimeError")
            });
        }
        self.sequence += 1;
        Ok(self.sequence)
    }
    fn receive(
        &mut self,
        method: &str,
        sequence: i64,
        _params: Option<&Value>,
    ) -> Result<Value, SessionError> {
        self.shared.note(vec![
            Value::from("session.receive"),
            Value::from(method),
            Value::from(sequence),
        ]);
        self.reply()
    }
    fn call(&mut self, method: &str, params: Option<Value>) -> Result<Value, SessionError> {
        self.shared.note(vec![
            Value::from("session.call"),
            Value::from(method),
            params.unwrap_or(Value::Null),
        ]);
        self.reply()
    }
    fn drain_events(&mut self) -> Vec<Value> {
        Vec::new()
    }
    fn exit(&mut self) {
        self.shared.note(vec![Value::from("session.exit")]);
    }
}

struct ScriptIpc(Arc<Shared>);

impl ScriptIpc {
    fn ask(
        &self,
        which: &str,
        thread: &Value,
        what: &Value,
        gate: &mut dyn Gate,
    ) -> Result<String, Raised> {
        let word = self
            .0
            .next("ipc", which)
            .map_or_else(|| "stopped".to_owned(), |found| text(&found));
        let word = if which == "start" && word == "stopped" {
            "started".to_owned()
        } else {
            word
        };
        let name = Value::from(format!("ipc.{which}"));
        if word == "raise" {
            self.0.note(vec![
                name,
                thread.clone(),
                what.clone(),
                Value::from("raise"),
            ]);
            return Err(Raised::new("RuntimeError"));
        }
        if let Some(early) = word.strip_prefix('!') {
            self.0.note(vec![
                name,
                thread.clone(),
                what.clone(),
                Value::from(word.as_str()),
            ]);
            return Ok(early.to_owned());
        }
        let permitted = gate.enter().map_err(|_| Raised::new("RuntimeError"))?;
        self.0
            .note(vec![name, thread.clone(), what.clone(), permitted.clone()]);
        let _ = gate.exit();
        if !matches!(permitted, Value::Bool(true)) {
            return Ok("held".to_owned());
        }
        Ok(word)
    }
}

impl usagestop::Ipc for ScriptIpc {
    fn stop_turn(
        &self,
        thread: &Value,
        turn_id: &Value,
        gate: &mut dyn Gate,
    ) -> Result<String, Raised> {
        self.ask("stop", thread, turn_id, gate)
    }
    fn start_turn(
        &self,
        thread: &Value,
        text: &Value,
        gate: &mut dyn Gate,
    ) -> Result<String, Raised> {
        self.ask("start", thread, text, gate)
    }
}

/// `inuse` ops: tell, forget, told, elsewhere.
pub fn inuse_op(paths: &Paths, what: &str, args: &[Value]) -> Value {
    let arg = |index: usize| args.get(index).map(text).unwrap_or_default();
    match what {
        "tell" => {
            let os = car_config::Os::here(false, Arc::new(crate::Links));
            match inuse::tell(&paths.home, &arg(0), &arg(1), &os) {
                Ok(()) => Value::Null,
                Err(_) => object([("raised", Value::from("OSError"))]),
            }
        }
        "forget" => {
            inuse::forget(&paths.home);
            Value::Null
        }
        "told" => inuse::told(Some(&paths.home)).map_or(Value::Null, |(exe, home)| {
            Value::Array(vec![
                Value::from(exe.to_lowercase()),
                Value::from(home.to_lowercase()),
            ])
        }),
        "elsewhere" => Value::Array(
            inuse::elsewhere(Some(&paths.home))
                .into_iter()
                .map(Value::from)
                .collect(),
        ),
        _ => Value::Null,
    }
}
