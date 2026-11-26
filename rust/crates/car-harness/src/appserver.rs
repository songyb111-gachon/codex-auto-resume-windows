//! car-codex's app-server half and the registry (S3.3), one way in: `codexapp.script`.
//!
//! A case is a stand-in world - the process list, who holds which file, the identities of live processes, the
//! signers of files, the four variables the pairing reads, this process's pid, the clock and the Restart Manager -
//! and a list of operations named as `tests/rustdiff/appserverdiff.py`'s reference script names them. The module
//! state of car-codex (the inventory, the signers, our own servers, the helper's results, the reported table) is
//! cleared before each case, as a fresh process starts. Nothing here decides anything: every answer is car-codex's.
//!
//! The world never reaches this machine's processes, holders or signatures. Files are real, in the diff's scratch
//! folder; processes started are only `car-fake-codex` copies there (transport and app server, `CREATE_NO_WINDOW`).

use std::sync::{Arc, Mutex};

use car_codex::errors::Error;
use car_codex::layout::{self, Watch};
use car_codex::pairing;
use car_codex::system::System;
use car_codex::transport::{Backend, LaunchGuard, Raised};
use car_codex::{appserver, transport};
use car_machine::json::{Map, Str, Value};
use car_machine::pyval;

use crate::object;

/// The stand-in world of one case.
pub struct World {
    pub state: Mutex<Value>,
    pub clock: Mutex<f64>,
    config: car_config::Os,
}

const MANAGED: [&str; 4] = [
    "LOCALAPPDATA",
    "ProgramW6432",
    "ProgramFiles",
    "USERPROFILE",
];

fn field<'a>(value: &'a Value, key: &str) -> &'a Value {
    static NULL: Value = Value::Null;
    match value {
        Value::Object(map) => map.get(key).unwrap_or(&NULL),
        _ => &NULL,
    }
}

fn raise_of(spec: &Value) -> Error {
    match pyval::text(spec) {
        Some("OSError") => Error::Os,
        Some("ValueError") => Error::Python("ValueError"),
        Some("TypeError") => Error::Python("TypeError"),
        Some("RuntimeError") => Error::Python("RuntimeError"),
        Some(code) => Error::Adapter(Box::leak(code.to_owned().into_boxed_str())),
        None => Error::Adapter("process_inventory_unavailable"),
    }
}

fn basename_lower(path: &str) -> String {
    car_codex::paths::name_of(path).to_lowercase()
}

impl World {
    pub fn new(state: Value) -> World {
        let clock = pyval::Num::of(field(&state, "clock"))
            .map(pyval::Num::as_f64)
            .unwrap_or(1000.0);
        World {
            state: Mutex::new(state),
            clock: Mutex::new(clock),
            config: car_config::Os::here(false, crate::links::for_config()),
        }
    }

    fn read(&self) -> Value {
        self.state
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner())
            .clone()
    }

    /// Merge `changes` into the world (`world` op).
    pub fn change(&self, changes: &Value) {
        let mut held = self
            .state
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        if let (Value::Object(map), Value::Object(changes)) = (&mut *held, changes) {
            for (key, value) in changes {
                map.insert(key.clone(), value.clone());
            }
        }
    }

    pub fn advance(&self, by: f64) {
        *self.clock.lock().unwrap_or_else(|p| p.into_inner()) += by;
    }
}

impl System for World {
    fn env(&self, name: &str) -> Option<String> {
        if let Some(managed) = MANAGED.iter().find(|each| each.eq_ignore_ascii_case(name)) {
            return pyval::text(field(field(&self.read(), "env"), managed)).map(str::to_owned);
        }
        std::env::var_os(name).map(|value| value.to_string_lossy().into_owned())
    }

    fn processes_named(
        &self,
        _names: &[&str],
        _families: &[&str],
    ) -> car_codex::Result<Vec<Value>> {
        match field(&self.read(), "processes") {
            Value::Array(rows) => Ok(rows.clone()),
            Value::Object(spec) => Err(raise_of(spec.get("raise").unwrap_or(&Value::Null))),
            _ => Ok(Vec::new()),
        }
    }

    fn resource_users(&self, paths: &[String]) -> car_codex::Result<Vec<Value>> {
        let world = self.read();
        let holders = field(&world, "holders");
        if let Value::Str(_) = field(holders, "raise") {
            return Err(raise_of(field(holders, "raise")));
        }
        let mut found = Vec::new();
        for path in paths {
            let key = basename_lower(path);
            let listed = match field(holders, &key) {
                Value::Array(items) => items.clone(),
                _ => match field(holders, "*") {
                    Value::Array(items) => items.clone(),
                    _ => Vec::new(),
                },
            };
            found.extend(listed);
        }
        Ok(found)
    }

    fn process_identity(&self, pid: &Value) -> car_codex::Result<Value> {
        let world = self.read();
        if let Value::Array(known) = field(&world, "identities") {
            for each in known {
                if pyval::eq(field(each, "pid"), pid) {
                    if let Value::Str(_) = field(each, "raise") {
                        return Err(raise_of(field(each, "raise")));
                    }
                    return Ok(object([
                        ("pid", field(each, "pid").clone()),
                        ("path", field(each, "path").clone()),
                        ("created", field(each, "created").clone()),
                    ]));
                }
            }
        }
        Err(Error::Adapter("process_exited"))
    }

    fn signer(&self, path: &str) -> Result<String, Option<&'static str>> {
        let world = self.read();
        let key = path.to_lowercase();
        let signers = field(&world, "signers");
        let found = match signers {
            Value::Object(map) => map
                .iter()
                .find(|(name, _)| name.as_str().is_some_and(|name| name.to_lowercase() == key))
                .map(|(_, value)| value.clone()),
            _ => None,
        };
        match found {
            None => Err(Some("unsigned")),
            Some(Value::Str(name)) => Ok(name.as_str().unwrap_or_default().to_owned()),
            Some(spec) => match field(&spec, "raise") {
                Value::Str(code) => Err(Some(Box::leak(
                    code.as_str()
                        .unwrap_or_default()
                        .to_owned()
                        .into_boxed_str(),
                ))),
                _ => Err(None),
            },
        }
    }

    fn own_pid(&self) -> i64 {
        match field(&self.read(), "pid") {
            Value::Int(number) => number.as_i64().unwrap_or(999_999),
            _ => 999_999,
        }
    }

    fn monotonic(&self) -> f64 {
        *self.clock.lock().unwrap_or_else(|p| p.into_inner())
    }

    fn resolve(&self, text: &str) -> Option<String> {
        car_codex::system::Platform {
            config: self.config.clone(),
        }
        .resolve(text)
    }

    fn restart_manager_available(&self) -> bool {
        !matches!(field(&self.read(), "restart_manager"), Value::Bool(false))
    }
}

/// What one operation answered.
pub fn failed(error: &Error) -> Value {
    match error {
        Error::Adapter(code) => object([
            ("error", Value::from("AdapterError")),
            ("code", Value::from(*code)),
        ]),
        other => object([("error", Value::from(other.class()))]),
    }
}

fn ok(value: Value) -> Value {
    object([("ok", value)])
}

fn text_of(value: &Value) -> String {
    match value {
        Value::Str(text) => text.as_str().unwrap_or_default().to_owned(),
        _ => String::new(),
    }
}

fn option_text(value: &Value) -> Option<String> {
    pyval::text(value).map(str::to_owned)
}

fn texts(items: &[String]) -> Value {
    Value::Array(
        items
            .iter()
            .map(|each| Value::from(each.as_str()))
            .collect(),
    )
}

fn rows_of(value: &Value) -> Vec<Value> {
    match value {
        Value::Array(rows) => rows.clone(),
        _ => Vec::new(),
    }
}

fn answer(found: car_codex::Result<Value>) -> Value {
    match found {
        Ok(value) => ok(value),
        Err(error) => failed(&error),
    }
}

fn results_value(results: &appserver::Results) -> Value {
    let mut map = Map::new();
    for (method, (code, sequence)) in results {
        map.insert(
            Str::from(method.as_str()),
            Value::Array(vec![
                Value::from(code.as_str()),
                Value::from(*sequence as i64),
            ]),
        );
    }
    Value::Object(map)
}

fn results_of(value: &Value) -> appserver::Results {
    match value {
        Value::Object(map) => map
            .iter()
            .filter_map(|(method, entry)| match entry {
                Value::Array(parts) if parts.len() == 2 => Some((
                    method.as_str().unwrap_or_default().to_owned(),
                    (
                        text_of(&parts[0]),
                        pyval::Num::of(&parts[1]).map_or(0, |n| n.as_f64() as u64),
                    ),
                )),
                _ => None,
            })
            .collect(),
        _ => Vec::new(),
    }
}

struct Guard {
    spec: Value,
}

impl LaunchGuard for Guard {
    fn enter(&mut self) -> Result<Value, Raised> {
        match field(&self.spec, "enter") {
            Value::Str(text) if text.as_str() == Some("raise") => Err(Raised),
            other => Ok(other.clone()),
        }
    }

    fn exit(&mut self) -> Result<(), Raised> {
        match field(&self.spec, "exit") {
            Value::Str(text) if text.as_str() == Some("raise") => Err(Raised),
            _ => Ok(()),
        }
    }
}

/// The same stand-in guard in the engine's shape (`store.submission_guard`, car-engine's `LaunchGuard`): entered, the
/// body run with whether it permits (`enter` is True), left. `"raise"` raises entering or leaving, as `Guard` does.
struct ScopeGuard {
    spec: Value,
}

impl car_engine::LaunchGuard for ScopeGuard {
    fn enter(&self, body: &mut dyn FnMut(bool) -> Value) -> car_machine::pyval::Py<Value> {
        let raises = |name: &str| matches!(field(&self.spec, name), Value::Str(text) if text.as_str() == Some("raise"));
        if raises("enter") {
            return Err("RuntimeError");
        }
        let found = body(matches!(field(&self.spec, "enter"), Value::Bool(true)));
        if raises("exit") {
            return Err("RuntimeError");
        }
        Ok(found)
    }
}

/// A case's state between its operations.
pub struct Case {
    pub world: Arc<World>,
    pub backend: Option<Backend>,
    watch: Option<Watch>,
    said: Arc<Mutex<Vec<String>>>,
    last_found: Option<Arc<Value>>,
    pub registry: crate::registry::State,
}

fn backend_state(backend: &Backend) -> Value {
    let mut served = backend.served_elsewhere.clone();
    served.sort();
    object([
        ("codex_home", Value::from(backend.codex_home.as_str())),
        ("codex_exe", Value::from(backend.codex_exe.as_str())),
        (
            "engine_version",
            backend
                .engine_version
                .as_deref()
                .map_or(Value::Null, Value::from),
        ),
        ("engine_verified", Value::Bool(backend.engine_verified)),
        (
            "queue_remote_supported",
            Value::Bool(backend.queue_remote_supported),
        ),
        ("served_elsewhere", texts(&served)),
        (
            "app_look",
            backend.app_look.map_or(Value::Null, Value::from),
        ),
        (
            "app_look_why",
            backend.app_look_why.map_or(Value::Null, Value::from),
        ),
        ("looked", Value::Bool(backend.app_looked_at.is_some())),
        (
            "server_holds",
            backend.server_holds.map_or(Value::Null, Value::Bool),
        ),
        (
            "layout",
            backend.layout.as_deref().cloned().unwrap_or(Value::Null),
        ),
        ("protocol_results", results_value(&backend.protocol_results)),
        (
            "session_holder",
            backend
                .session_holder
                .as_ref()
                .map_or(Value::Null, |(pid, created)| {
                    Value::Array(vec![pid.clone(), created.clone()])
                }),
        ),
        (
            "last_checks",
            backend.last_checks().map_or(Value::Null, Value::Object),
        ),
        ("reason", Value::from(backend.app_unmatched_reason())),
    ])
}

impl Case {
    fn new(world: Value) -> Case {
        Case {
            world: Arc::new(World::new(world)),
            backend: None,
            watch: None,
            said: Arc::new(Mutex::new(Vec::new())),
            last_found: None,
            registry: crate::registry::State::default(),
        }
    }

    fn take_said(&self) -> Value {
        let lines: Vec<String> = std::mem::take(
            &mut *self
                .said
                .lock()
                .unwrap_or_else(|poisoned| poisoned.into_inner()),
        );
        texts(&lines)
    }

    fn backend(&mut self) -> car_codex::Result<&mut Backend> {
        self.backend.as_mut().ok_or(Error::Python("AttributeError"))
    }

    fn run(&mut self, op: &str, args: &[Value]) -> Value {
        let arg = |at: usize| args.get(at).cloned().unwrap_or(Value::Null);
        let system = Arc::clone(&self.world);
        let system: &dyn System = system.as_ref();
        match op {
            "world" => {
                self.world.change(&arg(0));
                ok(Value::Null)
            }
            "advance" => {
                self.world
                    .advance(pyval::Num::of(&arg(0)).map_or(0.0, pyval::Num::as_f64));
                ok(Value::Null)
            }
            // ---------------------------------------------------------------------------------------- pairing
            "engine_row" => ok(Value::Bool(pairing::engine_row(system, &arg(0)))),
            "app_process" => ok(Value::Bool(pairing::app_process(system, &arg(0)))),
            "windows_apps" => ok(Value::from(pairing::windows_apps(system).as_str())),
            "package_app" => ok(Value::Bool(pairing::package_app(system, &text_of(&arg(0))))),
            "package_file" => ok(Value::Bool(pairing::package_file(
                system,
                &text_of(&arg(0)),
            ))),
            "main_slot" => ok(Value::Bool(pairing::main_slot(system, &text_of(&arg(0))))),
            "main_place" => ok(Value::Bool(pairing::main_place(system, &text_of(&arg(0))))),
            "extension_engine" => ok(Value::Bool(pairing::extension_engine(
                system,
                &text_of(&arg(0)),
            ))),
            "at_official_location" => ok(Value::Bool(pairing::at_official_location(
                system,
                &text_of(&arg(0)),
            ))),
            "official_engine" => {
                let (official, why) = pairing::official_engine(system, &text_of(&arg(0)));
                ok(Value::Array(vec![
                    Value::Bool(official),
                    Value::from(why.as_str()),
                ]))
            }
            "app_mains" => {
                let rows = rows_of(&arg(0));
                answer(pairing::app_mains(system, &rows).map(|mains| {
                    Value::Array(
                        rows.iter()
                            .enumerate()
                            .filter(|(_, row)| mains.iter().any(|each| std::ptr::eq(*each, *row)))
                            .map(|(index, _)| Value::from(index as i64))
                            .collect(),
                    )
                }))
            }
            "under_app" => {
                let rows = rows_of(&arg(0));
                let row = match &arg(1) {
                    Value::Int(index) => rows
                        .get(index.as_i64().unwrap_or(-1) as usize)
                        .cloned()
                        .unwrap_or(Value::Null),
                    other => other.clone(),
                };
                answer(pairing::under_app(system, &rows, &row, &arg(2)).map(Value::Bool))
            }
            "server_engines" => answer(
                pairing::server_engines(system, &rows_of(&arg(0))).map(|found| texts(&found)),
            ),
            "engines_instead" => answer(
                pairing::engines_instead(system, &rows_of(&arg(0)), &text_of(&arg(1)))
                    .map(|found| texts(&found)),
            ),
            "app_running" => {
                answer(pairing::app_running(system, &rows_of(&arg(0))).map(Value::Bool))
            }
            "app_running_now" => {
                ok(pairing::app_running_now(system).map_or(Value::Null, Value::Bool))
            }
            "app_engines" => answer(pairing::app_engines(system).map(|found| texts(&found))),
            "inventory" => answer(pairing::inventory(system).map(Value::Array)),
            "forget_inventory" => {
                pairing::forget_inventory();
                ok(Value::Null)
            }
            "session_kind" => {
                let rows = match &arg(0) {
                    Value::Array(rows) => Some(rows.clone()),
                    _ => None,
                };
                answer(
                    pairing::session_kind(system, rows.as_deref(), &arg(1), &text_of(&arg(2)))
                        .map(Value::Bool),
                )
            }
            "database_holders" => {
                let home = option_text(&arg(0));
                answer(pairing::database_holders(system, home.as_deref()).map(Value::Array))
            }
            "desktop_pair" => {
                let rows = rows_of(&arg(0));
                let home = option_text(&arg(2));
                let mut seen = Map::new();
                let with_seen = pyval::truthy(&arg(4));
                let found = pairing::desktop_pair(
                    system,
                    &rows,
                    &text_of(&arg(1)),
                    home.as_deref(),
                    pyval::truthy(&arg(3)),
                    with_seen.then_some(&mut seen),
                );
                match found {
                    Ok(paired) => ok(object([("paired", paired), ("seen", Value::Object(seen))])),
                    Err(error) => {
                        let mut out = failed(&error);
                        if let (Error::Adapter(_), Value::Object(map)) = (&error, &mut out) {
                            map.insert(Str::from("seen"), Value::Object(seen));
                        }
                        out
                    }
                }
            }
            "own_server" => answer(pairing::own_server(system, &arg(0)).map(|mark| {
                mark.map_or(Value::Null, |(pid, created)| {
                    Value::Array(vec![pid, created])
                })
            })),
            "own_server_gone" => {
                let mark = match &arg(0) {
                    Value::Array(parts) if parts.len() == 2 => (parts[0].clone(), parts[1].clone()),
                    _ => (Value::Null, Value::Null),
                };
                pairing::own_server_gone(&mark);
                ok(Value::Null)
            }
            "own_holder" => answer(pairing::own_holder(&arg(0)).map(Value::Bool)),
            // ---------------------------------------------------------------------------------------- layout
            "snapshot" => {
                let rows = match &arg(0) {
                    Value::Array(rows) => Some(rows.clone()),
                    _ => None,
                };
                let seen = match &arg(2) {
                    Value::Object(map) => Some(map.clone()),
                    _ => None,
                };
                let exe = option_text(&arg(1));
                ok(layout::snapshot(
                    system,
                    rows.as_deref(),
                    exe.as_deref(),
                    seen.as_ref(),
                ))
            }
            "catalogued" => ok(Value::Bool(layout::catalogued(&arg(0)))),
            "layout.read" => ok(layout::read(&text_of(&arg(0))).unwrap_or(Value::Null)),
            "file" => ok(std::fs::read(text_of(&arg(0)))
                .map_or(Value::Null, |bytes| Value::from(hex(&bytes).as_str()))),
            "watch.new" => {
                let said = Arc::clone(&self.said);
                let world = Arc::clone(&self.world);
                self.watch = Some(Watch::new(
                    &text_of(&arg(0)),
                    &arg(1),
                    Box::new(move |line: &str| {
                        said.lock()
                            .unwrap_or_else(|poisoned| poisoned.into_inner())
                            .push(line.to_owned());
                    }),
                    Box::new(move || world.monotonic()),
                    std::process::id(),
                ));
                let said = self.take_said();
                let updated = self
                    .watch
                    .as_ref()
                    .map_or(Value::Null, |watch| watch.updated_from.clone());
                ok(object([("said", said), ("updated_from", updated)]))
            }
            "watch.look" => {
                let found = match &arg(0) {
                    Value::Str(text) if text.as_str() == Some("again") => self.last_found.clone(),
                    Value::Null => None,
                    other => {
                        let fresh = Arc::new(other.clone());
                        self.last_found = Some(Arc::clone(&fresh));
                        Some(fresh)
                    }
                };
                let Some(watch) = self.watch.as_mut() else {
                    return failed(&Error::Python("AttributeError"));
                };
                let kept = watch.look(found.as_ref(), &arg(1), &arg(2));
                let updated = watch.updated_from.clone();
                let said = self.take_said();
                match kept {
                    Ok(kept) => ok(object([
                        ("kept", kept.unwrap_or(Value::Null)),
                        ("said", said),
                        ("updated_from", updated),
                    ])),
                    Err(error) => failed(&error),
                }
            }
            // ---------------------------------------------------------------------------------------- the helper
            "unknown" => ok(Value::Bool(appserver::unknown(&arg(0), &text_of(&arg(1))))),
            "last_result" => {
                let results = results_of(&arg(1));
                ok(appserver::last_result(&text_of(&arg(0)), Some(&results))
                    .map_or(Value::Null, |code| Value::from(code.as_str())))
            }
            "messages" => {
                let Ok(bytes) = std::fs::read(text_of(&arg(0))) else {
                    return failed(&Error::Os);
                };
                let mut reader = appserver::TextReader::new(&bytes[..]);
                let mut found = Vec::new();
                let mut said: Vec<String> = Vec::new();
                loop {
                    let message = appserver::next_message(&mut reader, &mut |line: &str| {
                        said.push(line.to_owned())
                    });
                    match message {
                        Ok(appserver::Message::End) => break,
                        Ok(appserver::Message::Skipped) => found.push(Value::from("skipped")),
                        Ok(appserver::Message::Value(map)) => {
                            found.push(crate::leaves::shallow(Value::Object(map)))
                        }
                        Ok(appserver::Message::TooDeep) => {
                            found.push(Value::from("RecursionError"));
                            break;
                        }
                        Err(_) => {
                            found.push(Value::from("OSError"));
                            break;
                        }
                    }
                }
                ok(object([
                    ("messages", Value::Array(found)),
                    ("said", texts(&said)),
                ]))
            }
            "offers" => ok(Value::Bool(transport::offers(
                &text_of(&arg(0)),
                &text_of(&arg(1)),
            ))),
            "results" => ok(results_value(&appserver::results())),
            "said" => {
                let lines: Vec<String> = std::mem::take(
                    &mut *appserver::SAID
                        .lock()
                        .unwrap_or_else(|poisoned| poisoned.into_inner()),
                );
                ok(texts(&lines))
            }
            // ---------------------------------------------------------------------------------------- the backend
            "backend.new" => {
                let mut backend = Backend::new(
                    Arc::clone(&self.world) as Arc<dyn System>,
                    &text_of(&arg(0)),
                    &text_of(&arg(1)),
                    pyval::truthy(&arg(2)),
                    &text_of(&arg(3)),
                );
                backend.bundled = option_text(&arg(4));
                self.backend = Some(backend);
                ok(Value::Null)
            }
            "backend.set" => match self.backend() {
                Ok(backend) => {
                    backend.named_engine = pyval::truthy(field(&arg(0), "named_engine"));
                    ok(Value::Null)
                }
                Err(error) => failed(&error),
            },
            "backend.state" => match self.backend() {
                Ok(backend) => ok(backend_state(backend)),
                Err(error) => failed(&error),
            },
            "backend.engine_checks" => match self.backend() {
                Ok(backend) => ok(Value::Object(backend.engine_checks())),
                Err(error) => failed(&error),
            },
            "backend.compatible" => match self.backend() {
                Ok(backend) => answer(backend.compatible().map(|()| Value::Null)),
                Err(error) => failed(&error),
            },
            "backend.app_identity" => match self.backend() {
                Ok(backend) => answer(
                    backend
                        .app_identity()
                        .map(|found| found.unwrap_or(Value::Null)),
                ),
                Err(error) => failed(&error),
            },
            "backend.loaded" => match self.backend() {
                Ok(backend) => answer(backend.loaded(&text_of(&arg(0)), &arg(1)).map(Value::from)),
                Err(error) => failed(&error),
            },
            "backend.holder" => match self.backend() {
                Ok(backend) => answer(backend.holder(&text_of(&arg(0))).map(Value::from)),
                Err(error) => failed(&error),
            },
            "backend.usage" => {
                let started = std::time::Instant::now();
                match self.backend() {
                    Ok(backend) => {
                        let found = backend.usage();
                        let seconds = started.elapsed().as_secs_f64();
                        match found {
                            Ok(map) => ok(object([
                                ("usage", Value::Object(map)),
                                ("seconds", Value::Float(seconds)),
                            ])),
                            Err(error) => failed(&error),
                        }
                    }
                    Err(error) => failed(&error),
                }
            }
            "backend.delete_queue" => match self.backend() {
                Ok(backend) => answer(
                    backend
                        .delete_queue(&text_of(&arg(0)), &text_of(&arg(1)))
                        .map(Value::Bool),
                ),
                Err(error) => failed(&error),
            },
            "backend.send" => {
                let guard_spec = arg(2);
                match self.backend() {
                    Ok(backend) => {
                        let mut guard = Guard {
                            spec: guard_spec.clone(),
                        };
                        let launch: Option<&mut dyn LaunchGuard> =
                            if matches!(guard_spec, Value::Null) {
                                None
                            } else {
                                Some(&mut guard)
                            };
                        ok(Value::Object(backend.send(
                            &text_of(&arg(0)),
                            &arg(1),
                            launch,
                        )))
                    }
                    Err(error) => failed(&error),
                }
            }
            // Integration 6: the send as the engine makes it, through car-engine's `Transport` over this backend and
            // a guard of the engine's shape; the reference answers it with the same `send` and `Guard`.
            "backend.send_scoped" => match self.backend.take() {
                Some(backend) => {
                    use car_engine::Backend as _;
                    let transport = car_engine::transport::Transport::new(backend);
                    let guard = ScopeGuard { spec: arg(2) };
                    let prompt = match arg(1) {
                        Value::Str(text) => text,
                        _ => Str::from(""),
                    };
                    let answered = transport.send(&text_of(&arg(0)), &prompt, &guard);
                    self.backend = Some(transport.into_inner());
                    match answered {
                        Ok(value) => ok(value),
                        Err(class) => object([("error", Value::from(class))]),
                    }
                }
                None => failed(&Error::Python("AttributeError")),
            },
            "backend.queue_daemon_remote" => match self.backend() {
                Ok(backend) => answer(backend.queue_daemon_remote().map(Value::Bool)),
                Err(error) => failed(&error),
            },
            other if other.starts_with("registry.") => crate::registry::run(self, other, args),
            other => object([("error", Value::from(format!("NotPorted:{other}").as_str()))]),
        }
    }
}

/// A value the wire can carry: a NaN or an infinity as the marker the reference script writes for it.
pub fn finite(value: Value) -> Value {
    match value {
        Value::Float(x) if x.is_nan() => Value::from("NaN-float"),
        Value::Float(x) if x.is_infinite() => {
            Value::from(if x > 0.0 { "inf-float" } else { "-inf-float" })
        }
        Value::Array(items) => Value::Array(items.into_iter().map(finite).collect()),
        Value::Object(map) => Value::Object(map.into_iter().map(|(k, v)| (k, finite(v))).collect()),
        other => other,
    }
}

pub fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|byte| format!("{byte:02x}")).collect()
}

/// Every module state of car-codex this half has, as a fresh process has it.
pub fn reset() {
    pairing::reset();
    appserver::reset();
    transport::reset();
    car_codex::compat::reported::reset();
    appserver::SAID
        .lock()
        .unwrap_or_else(|poisoned| poisoned.into_inner())
        .clear();
}

/// `codexapp.script`: every case, in order; each answers `{"results": [...]}` with one entry per operation.
pub fn script(cases: &Value) -> Value {
    let Value::Array(cases) = cases else {
        return Value::Null;
    };
    let mut answers = Vec::with_capacity(cases.len());
    for case in cases {
        reset();
        let mut state = Case::new(field(case, "world").clone());
        let mut results = Vec::new();
        if let Value::Array(ops) = field(case, "ops") {
            for op in ops {
                let name = text_of(field(op, "op"));
                let args = match field(op, "args") {
                    Value::Array(args) => args.clone(),
                    _ => Vec::new(),
                };
                results.push(finite(state.run(&name, &args)));
            }
        }
        answers.push(object([("results", Value::Array(results))]));
    }
    Value::Array(answers)
}
