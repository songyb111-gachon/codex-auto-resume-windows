//! `flow.run`: one program of commands put to the report's flow over a scratch home, a scripted runtime, a scripted home
//! mutex and a scripted gh, each answering from the case, the way the tag's own flow tests hand them theirs.
//!
//! The case: `{"home", "codex", "view", "product_version", "windows", "clock": {"start", "step"}, "tokens", "find",
//! "runtime": {"policy": [...], "state": [...], "stored": [...], "sql": {"<policy call>": "..."}, "note_raises"},
//! "mutex": [...], "gate", "script": [...recorded gh...]}` and the program. The answer is everything the flow did that
//! can be seen: each step's answer, the journal's lines, the trips, gh's calls, its sleeps, the mutex's life and how many
//! times each seam was asked.

use std::path::PathBuf;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::{Arc, Condvar, Mutex};

use car_adv::jsonx::object;
use car_adv::policy::Policy;
use car_adv::registry::{self, CapabilityDef};
use car_adv::report::document::Facts;
use car_adv::report::flow::{Config, Flow};
use car_adv::report::reading::WatcherView;
use car_adv::report::seam::{Busy, CodexHome, HomeMutex, Runtime};
use car_adv::state::seam::Tokens;
use car_adv::vocabulary::{ArmingState, OffReason};
use car_codex::system::PolicyOs;
use car_machine::json::{Map, Str, Value};
use car_platform::localclock::Crt;

use crate::ops_github::{Gate, Scripted, call_value, release};
use crate::ops_records::paths_of;
use crate::util::{Failure, Out, arg, list, map, number, tagged_float, text};

fn locked<T>(mutex: &Mutex<T>) -> std::sync::MutexGuard<'_, T> {
    mutex
        .lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner)
}

fn field<'a>(case: &'a Map, name: &str) -> &'a Value {
    static NULL: Value = Value::Null;
    case.get(name).unwrap_or(&NULL)
}

/// An item of a per-call script: the call's own, or the last one repeated.
fn pick(items: &Value, call: usize) -> Value {
    match items {
        Value::Array(items) if !items.is_empty() => items[call.min(items.len() - 1)].clone(),
        _ => Value::Null,
    }
}

fn raise_of(item: &Value) -> Option<String> {
    match item {
        Value::Object(map) => match map.get("raise") {
            Some(Value::Str(class)) => class.as_str().map(str::to_owned),
            _ => None,
        },
        _ => None,
    }
}

fn state_word(item: &Value) -> Option<ArmingState> {
    match item {
        Value::Str(word) => word.as_str().and_then(ArmingState::parse),
        _ => None,
    }
}

/// The runtime of a case.
struct Stub {
    script: Map,
    home: PathBuf,
    policy_calls: AtomicUsize,
    state_calls: AtomicUsize,
    stored_calls: AtomicUsize,
    journal: Mutex<Vec<Value>>,
    trips: Mutex<Vec<Value>>,
}

impl Runtime for Stub {
    fn policy(&self) -> Result<Policy, String> {
        let call = self.policy_calls.fetch_add(1, Ordering::SeqCst);
        if let Value::Object(sql) = field(&self.script, "sql")
            && let Some(Value::Str(statement)) = sql.get(call.to_string().as_str())
            && let Ok(db) =
                rusqlite::Connection::open(self.home.join("config").join("state.sqlite"))
        {
            let _ = db.execute_batch(statement.as_str().unwrap_or_default());
        }
        let item = pick(field(&self.script, "policy"), call);
        if let Some(class) = raise_of(&item) {
            return Err(class);
        }
        let Value::Object(item) = item else {
            return Ok(Policy::default());
        };
        Ok(Policy {
            forbid: matches!(item.get("forbid"), Some(Value::Bool(true))),
            force_shadow: matches!(item.get("force_shadow"), Some(Value::Bool(true))),
            allowed: match item.get("allowed") {
                Some(Value::Array(ids)) => Some(
                    ids.iter()
                        .filter_map(|each| match each {
                            Value::Str(id) => id.as_str().map(str::to_owned),
                            _ => None,
                        })
                        .collect(),
                ),
                _ => None,
            },
        })
    }

    fn state_of(&self, _id: &str) -> Result<Option<ArmingState>, String> {
        let call = self.state_calls.fetch_add(1, Ordering::SeqCst);
        let item = pick(field(&self.script, "state"), call);
        match raise_of(&item) {
            Some(class) => Err(class),
            None => Ok(state_word(&item)),
        }
    }

    fn stored_state(&self, _id: &str) -> Result<Option<ArmingState>, String> {
        let call = self.stored_calls.fetch_add(1, Ordering::SeqCst);
        let item = pick(field(&self.script, "stored"), call);
        match raise_of(&item) {
            Some(class) => Err(class),
            None => Ok(state_word(&item)),
        }
    }

    fn trip(&self, id: &str, reason: OffReason) {
        locked(&self.trips).push(Value::Array(vec![
            Value::from(id),
            Value::from(reason.as_str()),
        ]));
    }

    fn note(&self, definition: &CapabilityDef, code: &str, at: f64) -> Result<(), String> {
        let Some(full) = definition.code(code) else {
            return Err("ValueError".to_owned());
        };
        locked(&self.journal).push(Value::Array(vec![
            Value::from(full),
            Value::from(definition.id.as_str()),
            Value::Float(at),
        ]));
        if matches!(field(&self.script, "note_raises"), Value::Bool(true)) {
            return Err("OSError".to_owned());
        }
        Ok(())
    }
}

struct StubMutex {
    script: Value,
    calls: AtomicUsize,
    log: Arc<Mutex<Vec<Value>>>,
}

impl HomeMutex for StubMutex {
    fn take(&self) -> Result<bool, Busy> {
        let call = self.calls.fetch_add(1, Ordering::SeqCst);
        let item = pick(&self.script, call);
        let word = match &item {
            Value::Str(word) => word.as_str().unwrap_or("free").to_owned(),
            _ => "free".to_owned(),
        };
        locked(&self.log).push(Value::Array(vec![
            Value::from("take"),
            Value::from(word.as_str()),
        ]));
        match word.as_str() {
            "free" => Ok(false),
            "abandoned" => Ok(true),
            "raise" => panic!("the mutex could not be made"),
            _ => Err(Busy),
        }
    }

    fn give(&self) {
        locked(&self.log).push(Value::Array(vec![Value::from("give")]));
    }
}

struct View(Value);

impl WatcherView for View {
    fn view(&self) -> Option<Value> {
        Some(self.0.clone())
    }
}

struct Nothing;

impl WatcherView for Nothing {
    fn view(&self) -> Option<Value> {
        None
    }
}

struct Named;

impl Facts for Named {
    fn product_version(&self) -> String {
        "unasked".to_owned()
    }
    fn windows_version(&self) -> Option<String> {
        None
    }
}

struct Homes;

impl CodexHome for Homes {
    fn home(&self, _paths: &car_config::Paths) -> PathBuf {
        PathBuf::from("unasked")
    }
}

struct Counter(Mutex<u64>);

impl Tokens for Counter {
    fn hex(&self, count: usize) -> String {
        let mut held = locked(&self.0);
        *held += 1;
        format!("{:0>width$x}", *held, width = count * 2)
    }
}

/// `$dir` in every text of an argument: the folder this side's homes are in.
fn put_in(value: &Value, root: &str) -> Value {
    match value {
        Value::Str(text) => text.as_str().map_or_else(
            || value.clone(),
            |text| Value::from(text.replace("$dir", root)),
        ),
        Value::Array(items) => Value::Array(items.iter().map(|each| put_in(each, root)).collect()),
        Value::Object(map) => {
            let mut found = Map::new();
            for (name, each) in map {
                found.insert(name.clone(), put_in(each, root));
            }
            Value::Object(found)
        }
        other => other.clone(),
    }
}

pub fn run(op: &str, args: &[Value]) -> Out {
    if op != "flow.run" {
        return Err(Failure::new("UnknownOp"));
    }
    let case = map(arg(args, 0)?)?;
    let program = list(arg(args, 1)?)?;
    let home = text(field(case, "home"))?.to_owned();
    let codex = PathBuf::from(text(field(case, "codex"))?);
    let paths = paths_of(&home);
    let definition = Arc::new(
        registry::shipped(false)
            .map_err(|_| Failure::new("RegistryError"))?
            .get("compat_report")
            .cloned()
            .ok_or_else(|| Failure::new("KeyError"))?,
    );
    let stub = Arc::new(Stub {
        script: match field(case, "runtime") {
            Value::Object(script) => script.clone(),
            _ => Map::new(),
        },
        home: PathBuf::from(&home),
        policy_calls: AtomicUsize::new(0),
        state_calls: AtomicUsize::new(0),
        stored_calls: AtomicUsize::new(0),
        journal: Mutex::new(Vec::new()),
        trips: Mutex::new(Vec::new()),
    });
    let runtime: Arc<dyn Runtime> = stub.clone();
    let mutex_log = Arc::new(Mutex::new(Vec::new()));
    let mutex_script = field(case, "mutex").clone();
    let (made_log, take_log) = (Arc::clone(&mutex_log), Arc::clone(&mutex_log));
    let gate: Option<Gate> = matches!(field(case, "gate"), Value::Bool(true))
        .then(|| Arc::new((Mutex::new(false), Condvar::new())));
    let runner = Arc::new(Scripted::new(field(case, "script"), gate.clone())?);
    let sleeps = Arc::new(Mutex::new(Vec::<f64>::new()));
    let sleeps_in = Arc::clone(&sleeps);
    let clock_calls = Arc::new(AtomicUsize::new(0));
    let (start, step) = match field(case, "clock") {
        Value::Object(clock) => (
            tagged_float(field(clock, "start"))?,
            tagged_float(field(clock, "step"))?,
        ),
        _ => (0.0, 0.0),
    };
    let ticking = Arc::clone(&clock_calls);
    let exe = match field(case, "find") {
        Value::Str(exe) => exe.as_str().map(str::to_owned),
        _ => None,
    };
    let view: Arc<dyn WatcherView + Send + Sync> = Arc::new(View(field(case, "view").clone()));
    let config = Config {
        runner: runner.clone(),
        find: Some(Arc::new(move || exe.clone())),
        make_mutex: Box::new(move |_| {
            locked(&made_log).push(Value::Array(vec![Value::from("made")]));
            Box::new(StubMutex {
                script: mutex_script.clone(),
                calls: AtomicUsize::new(0),
                log: Arc::clone(&take_log),
            })
        }),
        sleep: Arc::new(move |seconds| locked(&sleeps_in).push(seconds)),
        clock: Arc::new(move || start + step * ticking.fetch_add(1, Ordering::SeqCst) as f64),
        product_version: match field(case, "product_version") {
            Value::Str(version) => version.as_str().map(str::to_owned),
            _ => None,
        },
        windows: match field(case, "windows") {
            Value::Str(version) => version.as_str().map(str::to_owned),
            _ => None,
        },
        codex_home: Some(codex),
        view: Some(view),
        watcher: Arc::new(Nothing),
        facts: Arc::new(Named),
        homes: Arc::new(Homes),
        os: Arc::new(PolicyOs),
        local_clock: Arc::new(Crt),
        tokens: Arc::new(Counter(Mutex::new(
            number(field(case, "tokens")).unwrap_or(0) as u64,
        ))),
        unsafe_extra: Vec::new(),
    };
    let root = text(field(case, "root"))?.to_owned();
    let flow = Flow::new(paths, config);
    let mut steps = Vec::new();
    let mut last: Option<String> = None;
    for step in program {
        let parts = list(step)?;
        match text(arg(parts, 0)?)? {
            "answer" => {
                let argument = put_in(arg(parts, 2)?, &root);
                let shown =
                    match flow.answer(&runtime, &definition, text(arg(parts, 1)?)?, &argument) {
                        Ok(found) => {
                            if let Value::Object(map) = &found
                                && matches!(map.get("done"), Some(Value::Bool(true)))
                                && let Some(Value::Str(job)) = map.get("job")
                            {
                                last = job.as_str().map(str::to_owned);
                            }
                            found
                        }
                        Err(class) => object([("error", Value::from(class))]),
                    };
                steps.push(shown);
            }
            "wait" => steps.push(flow.wait(last.as_deref().unwrap_or(""), 30.0)),
            "job" => {
                let which = match arg(parts, 1)? {
                    Value::Str(word) if word.as_str() == Some("last") => {
                        Value::from(last.clone().unwrap_or_default())
                    }
                    other => other.clone(),
                };
                steps.push(flow.job(&which));
            }
            "release" => {
                if let Some(gate) = &gate {
                    release(gate);
                }
            }
            "sql" => {
                if let Ok(db) = rusqlite::Connection::open(
                    PathBuf::from(&home).join("config").join("state.sqlite"),
                ) {
                    let _ = db.execute_batch(text(arg(parts, 1)?)?);
                }
            }
            "file" => {
                let bytes = std::fs::read(text(arg(parts, 1)?)?.replace("$dir", &root));
                steps.push(match bytes {
                    Ok(bytes) => object([
                        ("exists", Value::Bool(true)),
                        (
                            "sha256",
                            Value::from(car_machine::hash::hex(&car_machine::hash::sha256(&bytes))),
                        ),
                    ]),
                    Err(_) => object([("exists", Value::Bool(false)), ("sha256", Value::Null)]),
                });
            }
            _ => return Err(Failure::new("BadArgument")),
        }
    }
    let calls: Vec<Value> = {
        let _ = &call_value;
        locked(&runner.calls).clone()
    };
    let numbers = |value: &AtomicUsize| Value::from(value.load(Ordering::SeqCst) as i64);
    let mut shown = Map::new();
    shown.insert(Str::from("steps"), Value::Array(steps));
    shown.insert(
        Str::from("journal"),
        Value::Array(locked(&stub.journal).clone()),
    );
    shown.insert(
        Str::from("trips"),
        Value::Array(locked(&stub.trips).clone()),
    );
    shown.insert(Str::from("calls"), Value::Array(calls));
    shown.insert(
        Str::from("sleeps"),
        Value::Array(locked(&sleeps).iter().copied().map(Value::Float).collect()),
    );
    shown.insert(Str::from("mutex"), Value::Array(locked(&mutex_log).clone()));
    shown.insert(
        Str::from("asked"),
        object([
            ("policy", numbers(&stub.policy_calls)),
            ("state", numbers(&stub.state_calls)),
            ("stored", numbers(&stub.stored_calls)),
            ("clock", numbers(&clock_calls)),
        ]),
    );
    Ok(Value::Object(shown))
}
