//! What every op of the probe shares: the case's home, clock and state, the `Scoped` a code is bound to, the scripted
//! stand-ins and how an answer is written (as the reference's `norm`/`said`).

use std::collections::HashMap;
use std::path::Path;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex, PoisonError};

use car_adv::capabilities::{Raised, Said, Spoke};
use car_adv::engine::supervise::{Bound, Direct};
use car_adv::registry;
use car_adv::state::AdvancedState;
use car_adv::state::calls::{self, Call};
use car_adv::state::scoped::Scoped;
use car_adv::state::seam::Tokens;
use car_config::Paths;
use car_machine::json::{Map, Value};

pub fn get<'a>(map: &'a Map, name: &str) -> &'a Value {
    static NULL: Value = Value::Null;
    map.get(name).unwrap_or(&NULL)
}

pub fn text(value: &Value) -> String {
    match value {
        Value::Str(text) => text.as_str().unwrap_or_default().to_owned(),
        _ => String::new(),
    }
}

pub fn object(pairs: Vec<(&str, Value)>) -> Value {
    let mut map = Map::new();
    for (key, value) in pairs {
        map.insert(key.into(), value);
    }
    Value::Object(map)
}

pub fn list(value: &Value) -> Vec<Value> {
    match value {
        Value::Array(items) => items.clone(),
        _ => Vec::new(),
    }
}

pub fn f64_of(value: &Value) -> Option<f64> {
    car_adv::state::py::as_f64(value)
}

pub fn lock<T>(held: &Mutex<T>) -> std::sync::MutexGuard<'_, T> {
    held.lock().unwrap_or_else(PoisonError::into_inner)
}

/// `said(value)` of the reference: DEFER, a word, a value.
pub fn said(found: Spoke) -> Value {
    match found {
        Ok(Said::Defer) => Value::Str("DEFER".into()),
        Ok(Said::Word(word)) => object(vec![("word", Value::Str(word.as_str().into()))]),
        Ok(Said::Value(value)) => object(vec![("value", value)]),
        Ok(Said::Tuple(items)) | Ok(Said::Set(items)) => object(vec![("value", Value::Array(items))]),
        Ok(Said::Errand(_)) => object(vec![("object", Value::Str("errand".into()))]),
        Ok(_) => object(vec![("object", Value::Str("other".into()))]),
        Err(raised) => error(&raised),
    }
}

pub fn error(raised: &Raised) -> Value {
    object(vec![("error", Value::Str(raised.class.as_str().into()))])
}

/// The shared log of every call a case's stand-ins were asked.
pub type Log = Arc<Mutex<Vec<Value>>>;

/// Answers per call kind, taken in order (the last repeated); `{"raise": class}` raises; every call logged.
pub struct Script {
    script: Mutex<HashMap<String, Vec<Value>>>,
    pub log: Log,
}

impl Script {
    pub fn new(script: &Value, log: Log) -> Script {
        let mut kinds = HashMap::new();
        if let Value::Object(map) = script {
            for (key, value) in map.iter() {
                kinds.insert(text(&Value::Str(key.clone())), list(value));
            }
        }
        Script {
            script: Mutex::new(kinds),
            log,
        }
    }

    pub fn answer(&self, kind: &str, default: Value, logged: Vec<Value>) -> Result<Value, Raised> {
        let mut entry = vec![Value::Str(kind.into())];
        entry.extend(logged);
        lock(&self.log).push(Value::Array(entry));
        let mut script = lock(&self.script);
        let Some(found) = script.get_mut(kind) else {
            return Ok(default);
        };
        if found.is_empty() {
            return Ok(default);
        }
        let value = if found.len() > 1 {
            found.remove(0)
        } else {
            found[0].clone()
        };
        if let Value::Object(map) = &value
            && let Some(class) = map.get("raise")
        {
            let class = text(class);
            let known = [
                "ValueError",
                "TypeError",
                "KeyError",
                "RuntimeError",
                "OSError",
                "LookupError",
            ];
            return Err(Raised::new(if known.contains(&class.as_str()) {
                &class
            } else {
                "RuntimeError"
            }));
        }
        Ok(value)
    }
}

#[derive(Debug)]
struct Links;

impl car_config::Links for Links {
    fn is_symlink(&self, path: &Path) -> bool {
        car_platform::links::is_symlink(path)
    }
}

/// `secrets.token_hex(n)` as both sides stand it in: a counter.
struct Counter(Mutex<u64>);

impl Tokens for Counter {
    fn hex(&self, count: usize) -> String {
        let mut held = lock(&self.0);
        *held += 1;
        format!("{:0>width$x}", *held, width = count * 2)
    }
}

pub fn paths_of(home: &str) -> Paths {
    let no_env = |_: &str| None;
    Paths::new(
        Some(home),
        home,
        &no_env,
        car_config::Os::here(false, Arc::new(Links)),
    )
    .expect("the home's paths")
}

/// One case's state and its `Scoped`, as a code is bound to it.
pub struct Held {
    pub state: AdvancedState,
    pub capability: String,
    pub on: AtomicBool,
    pub armed: Mutex<Vec<String>>,
    pub verdicts: Map,
}

impl Direct for Held {
    fn scoped(&self, f: &mut dyn FnMut(&Scoped<'_>)) {
        let on = || self.on.load(Ordering::SeqCst);
        let verdict = |measurement: &Value| match measurement {
            Value::Str(key) => self
                .verdicts
                .get(key.as_str().unwrap_or_default())
                .cloned()
                .unwrap_or(Value::Null),
            _ => Value::Null,
        };
        let armed = |other: &Value| lock(&self.armed).contains(&text(other));
        let scoped = Scoped {
            state: &self.state,
            capability: Value::Str(self.capability.as_str().into()),
            on: Some(&on),
            verdict: Some(&verdict),
            armed: Some(&armed),
        };
        f(&scoped);
    }
}

/// The reference's `Case`: home, clock, state with its setup calls made, and the Scoped a code is bound to.
pub struct Case {
    pub paths: Paths,
    pub clock: Arc<Mutex<f64>>,
    pub held: Arc<Held>,
    pub log: Log,
}

impl Case {
    pub fn new(case: &Map) -> Case {
        let home = text(get(case, "home"));
        let paths = paths_of(&home);
        let clock = Arc::new(Mutex::new(f64_of(get(case, "now")).unwrap_or(1_800_000_000.0)));
        let reading = Arc::clone(&clock);
        let state = AdvancedState::new(
            paths.clone(),
            Arc::new(registry::shipped(false).expect("the shipped registry")),
            Box::new(move || *lock(&reading)),
            Arc::new(Counter(Mutex::new(0))) as Arc<dyn Tokens>,
        );
        for call in list(&homed(get(case, "setup"), &home)) {
            let parts = list(&call);
            call_state(&state, &parts);
        }
        let verdicts = match get(case, "verdicts") {
            Value::Object(map) => map.clone(),
            _ => Map::new(),
        };
        let held = Arc::new(Held {
            state,
            capability: text(get(case, "capability")),
            on: AtomicBool::new(!matches!(get(case, "on"), Value::Bool(false))),
            armed: Mutex::new(list(get(case, "armed")).iter().map(text).collect()),
            verdicts,
        });
        Case {
            paths,
            clock,
            held,
            log: Arc::new(Mutex::new(Vec::new())),
        }
    }

    pub fn bound(&self) -> Bound {
        Bound::Direct(self.held.clone() as Arc<dyn Direct>)
    }

    /// A step every scenario takes; whether it was one.
    pub fn common(&self, step: &[Value]) -> bool {
        match text(step.first().unwrap_or(&Value::Null)).as_str() {
            "clock" => {
                *lock(&self.clock) = f64_of(&step[1]).unwrap_or(0.0);
            }
            "on" => self
                .held
                .on
                .store(matches!(step[1], Value::Bool(true)), Ordering::SeqCst),
            "armed" => *lock(&self.held.armed) = list(&step[1]).iter().map(text).collect(),
            "call" => call_state(&self.held.state, &step[1..]),
            _ => return false,
        }
        true
    }

    pub fn log(&self) -> Value {
        Value::Array(lock(&self.log).clone())
    }

    pub fn close(&self) {
        self.held.state.close();
    }
}

/// `value` with every text's "{home}" made the case's home.
pub fn homed(value: &Value, home: &str) -> Value {
    match value {
        Value::Str(found) => Value::Str(
            found
                .as_str()
                .unwrap_or_default()
                .replace("{home}", home)
                .as_str()
                .into(),
        ),
        Value::Array(items) => Value::Array(items.iter().map(|each| homed(each, home)).collect()),
        Value::Object(map) => {
            let mut made = Map::new();
            for (key, each) in map.iter() {
                made.insert(key.clone(), homed(each, home));
            }
            Value::Object(made)
        }
        other => other.clone(),
    }
}

/// `getattr(state, method)(*arguments, **keywords)`; what it answers is not kept (a setup call).
pub fn call_state(state: &AdvancedState, parts: &[Value]) {
    let method = text(parts.first().unwrap_or(&Value::Null));
    let args = list(parts.get(1).unwrap_or(&Value::Null));
    let kwargs = match parts.get(2) {
        Some(Value::Object(map)) => map.clone(),
        _ => Map::new(),
    };
    let _ = calls::call(
        state,
        &method,
        Call {
            args: &args,
            kwargs: &kwargs,
        },
    );
}
