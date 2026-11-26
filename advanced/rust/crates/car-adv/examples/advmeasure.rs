//! The measurement harness's differential probe (seat S7.4): never shipped, built on demand
//! (`cargo build --release -p car-adv --example advmeasure`, from `advanced/rust`).
//!
//! `advmeasure` reads one request on stdin, `{"cases": [...]}`, and writes `{"results": [...]}`: for each case what
//! `tests/rustdiff/advmeasure.py`'s reference script writes for it - the answer or the class raised, and every call
//! the fakes saw, in order (the session's opens, enters, calls, drains and exits, the clock's readings and sleeps, the
//! random ids, the hands, the CLI, the IPC look and the launcher). Nothing real is ever asked: the session, the
//! launcher, the hands and the clock are the case's script.

use std::cell::RefCell;
use std::collections::BTreeMap;
use std::io::Read;
use std::path::{Path, PathBuf};
use std::rc::Rc;

use car_adv::evidence::{self, Envelope};
use car_adv::measure::{
    self, BackendView, Hand, MeasureSession, Raised, Request, Res, SessionFactory, Timing, World,
};
use car_adv::vocabulary::{Measurement, NoteCode, Verdict, parse};
use car_machine::json::{Map, Options, Str, Value, from_slice, to_string};

type Log = Rc<RefCell<Vec<Value>>>;

fn s(text: &str) -> Value {
    Value::Str(Str::new(text))
}

fn note(log: &Log, entry: Vec<Value>) {
    log.borrow_mut().push(Value::Array(entry));
}

fn get<'a>(value: &'a Value, name: &str) -> Option<&'a Value> {
    measure::get(value, name)
}

fn text_of(value: Option<&Value>) -> Option<String> {
    match value {
        Some(Value::Str(found)) => found.as_str().map(str::to_owned),
        _ => None,
    }
}

/// An answer of the script: a value, or `{"$raise": {"class", "code", "method"}}`.
fn answer(spec: &Value) -> Res<Value> {
    let Some(raise) = get(spec, "$raise") else {
        return Ok(spec.clone());
    };
    let class = text_of(get(raise, "class")).unwrap_or_else(|| "ValueError".into());
    Err(match class.as_str() {
        "SessionRefused" => Raised::Refused,
        "EvidenceUnavailable" => Raised::Unavailable("stand-in"),
        "AdapterError" | "RefusedByCodex" => Raised::Adapter {
            method: text_of(get(raise, "method")),
            code: get(raise, "code").cloned().unwrap_or(Value::Null),
            class,
        },
        _ => Raised::Other(class),
    })
}

/// Answers taken in order, the last repeated; none answers `default`.
struct Queue(Vec<Value>, usize);

impl Queue {
    fn of(value: Option<&Value>) -> Queue {
        match value {
            Some(Value::Array(items)) => Queue(items.clone(), 0),
            Some(other) => Queue(vec![other.clone()], 0),
            None => Queue(vec![], 0),
        }
    }

    fn next(&mut self, default: Value) -> Res<Value> {
        if self.0.is_empty() {
            return Ok(default);
        }
        let at = self.1.min(self.0.len() - 1);
        self.1 += 1;
        answer(&self.0[at])
    }
}

struct FakeSession {
    allowed: std::collections::BTreeSet<&'static str>,
    replies: BTreeMap<String, Queue>,
    events: Vec<Value>,
    declined: Value,
    enter: Option<Value>,
    log: Log,
}

impl MeasureSession for FakeSession {
    fn enter(&mut self) -> Res<()> {
        note(&self.log, vec![s("enter")]);
        match &self.enter {
            Some(spec) => answer(spec).map(|_| ()),
            None => Ok(()),
        }
    }

    fn call(&mut self, method: &str, params: Option<Value>) -> Res<Value> {
        note(
            &self.log,
            vec![s("call"), s(method), params.clone().unwrap_or(Value::Null)],
        );
        if !self.allowed.contains(method) {
            return Err(Raised::Refused);
        }
        match self.replies.get_mut(method) {
            Some(queue) => queue.next(Value::Object(Map::new())),
            None => Ok(Value::Object(Map::new())),
        }
    }

    fn drain_events(&mut self) -> Vec<Value> {
        note(&self.log, vec![s("drain")]);
        if self.events.is_empty() {
            return vec![];
        }
        match self.events.remove(0) {
            Value::Array(batch) => batch,
            other => vec![other],
        }
    }

    fn declined_count(&mut self) -> Value {
        note(&self.log, vec![s("declined")]);
        self.declined.clone()
    }

    fn exit(&mut self) {
        note(&self.log, vec![s("exit")]);
    }
}

struct Factory {
    script: Value,
    log: Log,
}

impl SessionFactory for Factory {
    fn open(
        &mut self,
        measurement: Measurement,
        home: Option<&Path>,
        config: Option<Vec<String>>,
    ) -> Res<Box<dyn MeasureSession>> {
        note(
            &self.log,
            vec![
                s("open"),
                s(measurement.as_str()),
                home.map_or(Value::Null, |found| s(&found.to_string_lossy())),
                config.map_or(Value::Null, |found| {
                    Value::Array(found.iter().map(|each| s(each)).collect())
                }),
            ],
        );
        if let Some(spec) = get(&self.script, "open_raises") {
            answer(spec)?;
        }
        let mut replies = BTreeMap::new();
        if let Some(Value::Object(found)) = get(&self.script, "replies") {
            for (method, answers) in found {
                replies.insert(found_key(method), Queue::of(Some(answers)));
            }
        }
        let events = match get(&self.script, "events") {
            Some(Value::Array(found)) => found.clone(),
            _ => vec![],
        };
        Ok(Box::new(FakeSession {
            allowed: car_adv::codex::protocol::methods_for(measurement),
            replies,
            events,
            declined: get(&self.script, "declined")
                .cloned()
                .unwrap_or(Value::from(0i64)),
            enter: get(&self.script, "enter_raises").cloned(),
            log: self.log.clone(),
        }))
    }

    fn takes_home(&self) -> bool {
        matches!(get(&self.script, "takes_home"), Some(Value::Bool(true)))
    }

    fn takes_config(&self) -> bool {
        matches!(get(&self.script, "takes_config"), Some(Value::Bool(true)))
    }
}

fn found_key(key: &Str) -> String {
    key.as_str().unwrap_or_default().to_owned()
}

/// The pinned clock both sides use: `sleep` moves both clocks on; every reading is logged.
struct Clock {
    time: f64,
    monotonic: f64,
    ids: u64,
    log: Log,
}

impl World for Clock {
    fn time(&mut self) -> f64 {
        note(&self.log, vec![s("time")]);
        self.time
    }
    fn monotonic(&mut self) -> f64 {
        note(&self.log, vec![s("monotonic")]);
        self.monotonic
    }
    fn sleep(&mut self, seconds: f64) {
        note(&self.log, vec![s("sleep"), Value::from(seconds)]);
        self.time += seconds;
        self.monotonic += seconds;
    }
    fn uuid4(&mut self) -> String {
        note(&self.log, vec![s("uuid")]);
        self.ids += 1;
        format!("00000000-0000-4000-8000-{:012x}", self.ids)
    }
}

fn number(value: Option<&Value>, default: f64) -> f64 {
    match value {
        Some(Value::Float(found)) => *found,
        Some(Value::Int(found)) => found.as_i64().map_or(default, |each| each as f64),
        _ => default,
    }
}

fn timing(case: &Value) -> Timing {
    let mut found = Timing::default();
    let given = get(case, "timing").cloned().unwrap_or(Value::Null);
    let pick = |name: &str, default: f64| number(get(&given, name), default);
    found.m2b_queue = pick("m2b_queue", found.m2b_queue);
    found.m2b_poll = pick("m2b_poll", found.m2b_poll);
    found.m6_turn = pick("m6_turn", found.m6_turn);
    found.m6_interrupt = pick("m6_interrupt", found.m6_interrupt);
    found.m6_poll = pick("m6_poll", found.m6_poll);
    found.mu_spacing = pick("mu_spacing", found.mu_spacing);
    found
}

fn backend(case: &Value) -> Option<BackendView> {
    let found = get(case, "backend")?;
    if matches!(found, Value::Null) {
        return None;
    }
    Some(BackendView {
        engine_version: get(found, "engine_version").cloned().unwrap_or(Value::Null),
        codex_home: text_of(get(found, "codex_home")).map(PathBuf::from),
    })
}

fn seams(case: &Value, log: &Log) -> measure::Seams {
    let mut seams = measure::Seams {
        backend: backend(case),
        ..measure::Seams::default()
    };
    if let Some(script) = get(case, "session").filter(|found| !matches!(found, Value::Null)) {
        seams.session_factory = Some(Box::new(Factory {
            script: script.clone(),
            log: log.clone(),
        }));
    }
    if let Some(spec) = get(case, "launcher").filter(|found| !matches!(found, Value::Null)) {
        let mut queue = Queue::of(Some(spec));
        let log = log.clone();
        seams.launcher = Some(Box::new(move || {
            note(&log, vec![s("launcher")]);
            queue.next(Value::Null)
        }));
    }
    if let Some(spec) = get(case, "cli").filter(|found| !matches!(found, Value::Null)) {
        let spec = spec.clone();
        let log = log.clone();
        seams.cli = Some(Box::new(move |arguments: &[String]| {
            let joined = arguments.join(" ");
            note(&log, vec![s("cli"), s(&joined)]);
            match get(&spec, &joined) {
                Some(found) => answer(found),
                None => Ok(Value::Null),
            }
        }));
    }
    if let Some(spec) = get(case, "ipc").filter(|found| !matches!(found, Value::Null)) {
        let spec = spec.clone();
        let log = log.clone();
        seams.ipc = Some(Box::new(move || {
            note(&log, vec![s("ipc")]);
            answer(&spec)
        }));
    }
    if let Some(Value::Object(hands)) = get(case, "hands") {
        for (name, spec) in hands {
            let name = found_key(name);
            let mut queue = Queue::of(Some(spec));
            let log = log.clone();
            let label = name.clone();
            let hand: Hand = Box::new(move |arguments: &[Value]| {
                note(
                    &log,
                    vec![s("hand"), s(&label), Value::Array(arguments.to_vec())],
                );
                queue.next(Value::Null)
            });
            seams.hands.insert(name, hand);
        }
    }
    seams
}

fn raised(error: &Raised) -> Value {
    let mut map = Map::new();
    map.insert(Str::new("raised"), s(&error.class()));
    Value::Object(map)
}

fn word<W: car_adv::vocabulary::ClosedWord>(case: &Value, name: &str) -> Result<W, Value> {
    text_of(get(case, name))
        .and_then(|found| parse::<W>(&found))
        .ok_or_else(|| raised(&Raised::Other("ValueError".into())))
}

fn ok(value: Value) -> Value {
    let mut map = Map::new();
    map.insert(Str::new("ok"), value);
    Value::Object(map)
}

fn directory(case: &Value) -> Option<PathBuf> {
    text_of(get(case, "dir")).map(PathBuf::from)
}

fn one(case: &Value, log: &Log) -> Value {
    let op = text_of(get(case, "op")).unwrap_or_default();
    let clock_spec = get(case, "clock").cloned().unwrap_or(Value::Null);
    let mut clock = Clock {
        time: number(get(&clock_spec, "time"), 1_790_000_000.0),
        monotonic: number(get(&clock_spec, "monotonic"), 1000.0),
        ids: 0,
        log: log.clone(),
    };
    let folder = directory(case);
    let versions = match get(case, "versions") {
        Some(Value::Object(found)) => Some(found.clone()),
        _ => None,
    };
    let product = text_of(get(case, "product_version")).unwrap_or_else(|| "0.6.26".into());
    let windows = text_of(get(case, "windows_build"));
    let outcome = match op.as_str() {
        "run" => {
            let measurement = match word::<Measurement>(case, "measurement") {
                Ok(found) => found,
                Err(error) => return error,
            };
            let thread = get(case, "thread").filter(|found| !matches!(found, Value::Null));
            let request = Request {
                versions,
                product_version: &product,
                windows_build: windows.as_deref(),
                thread,
                may_spend: matches!(get(case, "may_spend"), Some(Value::Bool(true))),
                directory: folder.as_deref(),
                timing: timing(case),
            };
            measure::run(measurement, &mut seams(case, log), request, &mut clock).map(Value::Object)
        }
        "complete" => {
            let measurement = match word::<Measurement>(case, "measurement") {
                Ok(found) => found,
                Err(error) => return error,
            };
            let verdict = match word::<Verdict>(case, "verdict") {
                Ok(found) => found,
                Err(error) => return error,
            };
            let request = Request {
                versions,
                product_version: &product,
                windows_build: windows.as_deref(),
                thread: None,
                may_spend: false,
                directory: folder.as_deref(),
                timing: Timing::default(),
            };
            let given = backend(case);
            measure::complete(
                measurement,
                verdict,
                &text_of(get(case, "note")).unwrap_or_default(),
                given.as_ref(),
                request,
                &mut clock,
            )
            .map(Value::Object)
        }
        "ev_complete" => {
            let measurement = match word::<Measurement>(case, "measurement") {
                Ok(found) => found,
                Err(error) => return error,
            };
            let verdict = match word::<Verdict>(case, "verdict") {
                Ok(found) => found,
                Err(error) => return error,
            };
            let _ = word::<NoteCode>;
            evidence::complete(
                measurement,
                verdict,
                &text_of(get(case, "note")).unwrap_or_default(),
                get(case, "codex_version").unwrap_or(&Value::Null),
                &text_of(get(case, "recorded_at")).unwrap_or_default(),
                folder.as_deref(),
            )
            .map(|path| s(&path.to_string_lossy()))
            .map_err(Raised::Evidence)
        }
        "build" | "build_write" => {
            let measurement = match word::<Measurement>(case, "measurement") {
                Ok(found) => found,
                Err(error) => return error,
            };
            let verdict = match word::<Verdict>(case, "verdict") {
                Ok(found) => found,
                Err(error) => return error,
            };
            let field = |name: &str| get(case, name).cloned().unwrap_or(Value::Null);
            let (product, codex, windows, at) = (
                field("product_version"),
                field("codex_version"),
                field("windows_build"),
                field("recorded_at"),
            );
            let note = get(case, "note").filter(|found| !matches!(found, Value::Null));
            evidence::build(
                measurement,
                verdict,
                get(case, "observed").unwrap_or(&Value::Null),
                &Envelope {
                    product_version: &product,
                    codex_version: &codex,
                    windows_build: &windows,
                    recorded_at: &at,
                },
                note,
            )
            .map_err(Raised::Evidence)
            .and_then(|record| {
                if op == "build" {
                    Ok(Value::Object(record))
                } else {
                    evidence::write(&record, folder.as_deref())
                        .map(|path| s(&path.to_string_lossy()))
                        .map_err(Raised::Evidence)
                }
            })
        }
        "outcome" => Ok(
            match evidence::outcome(get(case, "record").unwrap_or(&Value::Null)) {
                Some((verdict, version)) => Value::Array(vec![s(verdict.as_str()), s(&version)]),
                None => Value::Null,
            },
        ),
        "content_free" => Ok(Value::Bool(evidence::content_free(
            get(case, "value").unwrap_or(&Value::Null),
        ))),
        "no_content" => Ok(Value::Bool(evidence::no_content(
            &text_of(get(case, "value")).unwrap_or_default(),
        ))),
        "iso" => measure::iso(number(get(case, "value"), 0.0)).map(|found| s(&found)),
        "threads_valid" => {
            let measurement = match word::<Measurement>(case, "measurement") {
                Ok(found) => found,
                Err(error) => return error,
            };
            Ok(Value::Bool(measure::threads_valid(
                measurement,
                get(case, "value").unwrap_or(&Value::Null),
            )))
        }
        "completed_status" => {
            let events = match get(case, "events") {
                Some(Value::Array(found)) => found.clone(),
                _ => vec![],
            };
            Ok(measure::completed_status(
                &events,
                &text_of(get(case, "thread")).unwrap_or_default(),
                text_of(get(case, "turn")).as_deref(),
            )
            .map_or(Value::Null, |found| s(&found)))
        }
        "goal_status" => Ok(
            measure::goal_status(get(case, "value").unwrap_or(&Value::Null))
                .map_or(Value::Null, |found| s(&found)),
        ),
        other => Err(Raised::Other(format!("unknown op {other}"))),
    };
    match outcome {
        Ok(value) => ok(value),
        Err(error) => raised(&error),
    }
}

fn main() {
    let mut input = Vec::new();
    if std::io::stdin().read_to_end(&mut input).is_err() {
        std::process::exit(2);
    }
    let request = from_slice(&input).unwrap_or(Value::Null);
    let cases = match get(&request, "cases") {
        Some(Value::Array(found)) => found.clone(),
        _ => vec![],
    };
    let mut results = Vec::new();
    for case in &cases {
        let log: Log = Rc::new(RefCell::new(Vec::new()));
        let answer = one(case, &log);
        let mut entry = Map::new();
        entry.insert(Str::new("answer"), answer);
        entry.insert(Str::new("log"), Value::Array(log.borrow().clone()));
        results.push(Value::Object(entry));
    }
    let mut out = Map::new();
    out.insert(Str::new("results"), Value::Array(results));
    let written = to_string(&Value::Object(out), &Options::new()).unwrap_or_default();
    println!("{written}");
}
