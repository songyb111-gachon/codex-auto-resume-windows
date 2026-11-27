//! The measurement harness's differential probe (seat S7.4): never shipped, built on demand
//! (`cargo build --release -p car-adv --example advmeasure`, from `advanced/rust`).
//!
//! `advmeasure` reads one request on stdin, `{"cases": [...]}`, and writes `{"results": [...]}`: for each case what
//! `tests/rustdiff/advmeasure.py`'s reference script writes for it - the answer or the class raised, and every call
//! the fakes saw, in order (the session's opens, enters, calls, drains and exits, the clock's readings and sleeps, the
//! random ids, the hands, the CLI, the IPC look and the launcher). Nothing real is ever asked: the session, the
//! launcher, the hands and the clock are the case's script.

use std::collections::BTreeMap;
use std::io::Read;
use std::path::{Path, PathBuf};
use std::rc::Rc;
use std::sync::{Arc, Mutex};

use car_adv::evidence::{self, Envelope};
use car_adv::measure::{
    self, BackendView, Hand, MeasureSession, Raised, Request, Res, SessionFactory, Timing, World,
};
use car_adv::vocabulary::{Measurement, NoteCode, Verdict, parse};
use car_machine::json::{Map, Options, Str, Value, from_slice, to_string};

/// Shared with MQP's adds, which run on threads of their own.
type Log = Arc<Mutex<Vec<Value>>>;

fn s(text: &str) -> Value {
    Value::Str(Str::new(text))
}

fn note(log: &Log, entry: Vec<Value>) {
    log.lock()
        .unwrap_or_else(|poisoned| poisoned.into_inner())
        .push(Value::Array(entry));
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
            Some(Value::Null) | None => Queue(vec![], 0),
            Some(other) => Queue(vec![other.clone()], 0),
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

/// The case's script and its log, shared by every session it opens (MQP's on threads of their own).
#[derive(Clone)]
struct Script {
    script: Value,
    log: Log,
    /// `"shared": true`: one set of answers for every session the case opens.
    shared: Option<Arc<Mutex<BTreeMap<String, Queue>>>>,
}

fn replies_of(script: &Value) -> BTreeMap<String, Queue> {
    let mut replies = BTreeMap::new();
    if let Some(Value::Object(found)) = get(script, "replies") {
        for (method, answers) in found {
            replies.insert(found_key(method), Queue::of(Some(answers)));
        }
    }
    replies
}

impl Script {
    fn open(
        &self,
        measurement: Measurement,
        home: Option<&Path>,
        config: Option<Vec<(String, String)>>,
    ) -> Res<FakeSession> {
        note(
            &self.log,
            vec![
                s("open"),
                s(measurement.as_str()),
                home.map_or(Value::Null, |found| s(&found.to_string_lossy())),
                config.map_or(Value::Null, |found| {
                    Value::Array(
                        found
                            .iter()
                            .map(|(name, value)| Value::Array(vec![s(name), s(value)]))
                            .collect(),
                    )
                }),
            ],
        );
        if let Some(spec) = get(&self.script, "open_raises") {
            answer(spec)?;
        }
        if let (Some(home), Some(Value::Bool(true))) = (home, get(&self.script, "writes_config")) {
            let _ = std::fs::write(home.join("config.toml"), b"x");
        }
        let replies = match &self.shared {
            Some(shared) => Replies::Shared(Arc::clone(shared)),
            None => Replies::Own(replies_of(&self.script)),
        };
        let events = match get(&self.script, "events") {
            Some(Value::Array(found)) => found.clone(),
            _ => vec![],
        };
        Ok(FakeSession {
            allowed: car_adv::codex::protocol::methods_for(measurement),
            replies,
            events,
            declined: get(&self.script, "declined")
                .cloned()
                .unwrap_or(Value::from(0i64)),
            enter: get(&self.script, "enter_raises").cloned(),
            log: self.log.clone(),
        })
    }
}

enum Replies {
    Own(BTreeMap<String, Queue>),
    Shared(Arc<Mutex<BTreeMap<String, Queue>>>),
}

struct FakeSession {
    allowed: std::collections::BTreeSet<&'static str>,
    replies: Replies,
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
        let mut held;
        let replies = match &mut self.replies {
            Replies::Own(own) => own,
            Replies::Shared(shared) => {
                held = shared
                    .lock()
                    .unwrap_or_else(|poisoned| poisoned.into_inner());
                &mut *held
            }
        };
        match replies.get_mut(method) {
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

struct Factory(Script);

impl SessionFactory for Factory {
    fn open(
        &mut self,
        measurement: Measurement,
        home: Option<&Path>,
        config: Option<Vec<(String, String)>>,
    ) -> Res<Box<dyn MeasureSession>> {
        Ok(Box::new(self.0.open(measurement, home, config)?))
    }

    fn takes_home(&self) -> bool {
        matches!(get(&self.0.script, "takes_home"), Some(Value::Bool(true)))
    }

    fn takes_config(&self) -> bool {
        matches!(get(&self.0.script, "takes_config"), Some(Value::Bool(true)))
    }

    fn shared(&mut self) -> Option<measure::SharedOpen> {
        let script = self.0.clone();
        Some(Arc::new(move |measurement| {
            let opened: Box<dyn MeasureSession + Send> =
                Box::new(script.open(measurement, None, None)?);
            Ok(opened)
        }))
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
    /// The Codex home changing while a probe watches it (`grow`: at its sleep, history rows and rollout lines).
    grows: Value,
    home: Option<PathBuf>,
    slept: i64,
}

fn param(value: &Value) -> rusqlite::types::Value {
    match value {
        Value::Str(found) => {
            rusqlite::types::Value::Text(found.as_str().unwrap_or_default().to_owned())
        }
        Value::Int(found) => rusqlite::types::Value::Integer(found.as_i64().unwrap_or_default()),
        Value::Float(found) => rusqlite::types::Value::Real(*found),
        Value::Bool(found) => rusqlite::types::Value::Integer(i64::from(*found)),
        _ => rusqlite::types::Value::Null,
    }
}

impl Clock {
    fn grow(&mut self) {
        let (Value::Array(steps), Some(home)) = (&self.grows, &self.home) else {
            return;
        };
        for step in steps {
            if !matches!(get(step, "at"), Some(Value::Int(at)) if at.as_i64() == Some(self.slept)) {
                continue;
            }
            if let Some(Value::Array(statements)) = get(step, "history_sql") {
                for statement in statements {
                    let Value::Array(parts) = statement else {
                        continue;
                    };
                    let Some(sql) = parts.first().and_then(|first| text_of(Some(first))) else {
                        continue;
                    };
                    if let Ok(connection) =
                        rusqlite::Connection::open(home.join("thread_history_1.sqlite"))
                    {
                        let params: Vec<rusqlite::types::Value> =
                            parts[1..].iter().map(param).collect();
                        let _ = connection.execute(&sql, rusqlite::params_from_iter(params));
                    }
                }
            }
            if let Some(Value::Object(appended)) = get(step, "append") {
                for (thread, lines) in appended {
                    let path = home
                        .join("sessions")
                        .join(format!("rollout-{}.jsonl", found_key(thread)));
                    let mut bytes = Vec::new();
                    if let Value::Array(lines) = lines {
                        for line in lines {
                            bytes.extend(python_json(line).into_bytes());
                            bytes.push(b'\n');
                        }
                    }
                    use std::io::Write;
                    if let Ok(mut file) = std::fs::OpenOptions::new()
                        .append(true)
                        .create(true)
                        .open(&path)
                    {
                        let _ = file.write_all(&bytes);
                    }
                }
            }
        }
    }
}

/// `json.dumps(value)` (its default separators, ASCII only) for the lines a step appends.
fn python_json(value: &Value) -> String {
    car_machine::json::to_string(value, &Options::new()).unwrap_or_default()
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
        self.slept += 1;
        self.grow();
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
    found.m4_turn = pick("m4_turn", found.m4_turn);
    found.m4_note = pick("m4_note", found.m4_note);
    found.mc1_queue = pick("mc1_queue", found.mc1_queue);
    found.mc1_start = pick("mc1_start", found.mc1_start);
    found.mc2 = pick("mc2", found.mc2);
    found.mc2_poll = pick("mc2_poll", found.mc2_poll);
    found.mqp_add = pick("mqp_add", found.mqp_add);
    found.mqg_settle = pick("mqg_settle", found.mqg_settle);
    found.mqo_open = pick("mqo_open", found.mqo_open);
    found.mqo_find = pick("mqo_find", found.mqo_find);
    found.mopen = pick("mopen", found.mopen);
    found.mopen_poll = pick("mopen_poll", found.mopen_poll);
    found.mal = pick("mal", found.mal);
    found.mal_poll = pick("mal_poll", found.mal_poll);
    found.msteer_look = pick("msteer_look", found.msteer_look);
    found.msteer_poll = pick("msteer_poll", found.msteer_poll);
    found.manchor_gap = pick("manchor_gap", found.manchor_gap);
    found
}

fn backend(case: &Value, log: &Log) -> Option<BackendView> {
    let found = get(case, "backend")?;
    if matches!(found, Value::Null) {
        return None;
    }
    let app_identity: Option<measure::AppIdentity> = get(found, "app_identity").map(|spec| {
        let spec = spec.clone();
        let log = log.clone();
        let held: measure::AppIdentity = Rc::new(move || {
            note(&log, vec![s("app_identity")]);
            answer(&spec)
        });
        held
    });
    let loaded: Option<measure::Loaded> = get(found, "loaded").map(|spec| {
        let queue = Rc::new(std::cell::RefCell::new(Queue::of(Some(spec))));
        let log = log.clone();
        let held: measure::Loaded = Rc::new(move |thread: &str, identity: &Value| {
            note(&log, vec![s("loaded"), s(thread), identity.clone()]);
            queue.borrow_mut().next(Value::Null)
        });
        held
    });
    Some(BackendView {
        engine_version: get(found, "engine_version").cloned().unwrap_or(Value::Null),
        codex_home: text_of(get(found, "codex_home")).map(PathBuf::from),
        app_identity,
        loaded,
        codex_exe: get(found, "codex_exe").cloned(),
    })
}

fn seams(case: &Value, log: &Log) -> measure::Seams {
    let mut seams = measure::Seams {
        backend: backend(case, log),
        ..measure::Seams::default()
    };
    if let Some(script) = get(case, "session").filter(|found| !matches!(found, Value::Null)) {
        let shared = matches!(get(script, "shared"), Some(Value::Bool(true)))
            .then(|| Arc::new(Mutex::new(replies_of(script))));
        seams.session_factory = Some(Box::new(Factory(Script {
            script: script.clone(),
            log: log.clone(),
            shared,
        })));
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
                files_then(queue.next(Value::Null)?, arguments)
            });
            seams.hands.insert(name, hand);
        }
    }
    // `windows.resource_users` (the reference refuses it where the case names none: a RuntimeError, nothing logged).
    let users = get(case, "users")
        .filter(|found| !matches!(found, Value::Null))
        .cloned();
    let mut users_queue = Queue::of(users.as_ref());
    let users_log = log.clone();
    seams.resource_users = Some(Box::new(move |path: &Path| {
        if users.is_none() {
            return Err(Raised::Other("RuntimeError".into()));
        }
        note(&users_log, vec![s("users"), s(&path.to_string_lossy())]);
        match users_queue.next(Value::Array(vec![]))? {
            Value::Array(found) => Ok(found),
            _ => Err(Raised::Other("TypeError".into())),
        }
    }));
    // `pairing.session_kind(pairing.inventory(), user, ctx.backend.codex_exe)`.
    let mut holder_queue = Queue::of(get(case, "holder"));
    let holder_log = log.clone();
    seams.holder_kind = Some(Box::new(move |user: &Value, exe: Option<&Value>| {
        note(&holder_log, vec![s("inventory")]);
        let Some(exe) = exe else {
            return Err(Raised::Other("AttributeError".into()));
        };
        note(
            &holder_log,
            vec![s("session_kind"), user.clone(), exe.clone()],
        );
        Ok(car_machine::pyval::truthy(
            &holder_queue.next(Value::Bool(false))?,
        ))
    }));
    // The `codex_restart(home, read)` hand: `read()` called `reads` times, each answer logged.
    if let Some(spec) = get(case, "restart").filter(|found| !matches!(found, Value::Null)) {
        let spec = spec.clone();
        let restart_log = log.clone();
        seams.restart = Some(Box::new(
            move |home: Option<&Path>, read: &mut dyn FnMut() -> Res<Value>| {
                note(
                    &restart_log,
                    vec![
                        s("restart"),
                        home.map_or(Value::Null, |found| s(&found.to_string_lossy())),
                    ],
                );
                let reads = match get(&spec, "reads") {
                    Some(Value::Int(count)) => count.as_i64().unwrap_or(0),
                    _ => 0,
                };
                for _ in 0..reads {
                    let found = read()?;
                    note(&restart_log, vec![s("read"), found]);
                }
                answer(get(&spec, "answer").unwrap_or(&Value::Null))
            },
        ));
    }
    seams
}

fn last_text(value: &Value, last: &mut Option<String>) {
    match value {
        Value::Str(found) => *last = found.as_str().map(str::to_owned),
        Value::Array(items) => items.iter().for_each(|item| last_text(item, last)),
        _ => {}
    }
}

/// A hand's answer `{"$files": {name: text}, "$answer": value}`: the files written into the last folder its arguments
/// name (the schema's `--out`), then the answer.
fn files_then(found: Value, arguments: &[Value]) -> Res<Value> {
    let Some(Value::Object(files)) = get(&found, "$files") else {
        return Ok(found);
    };
    let mut last: Option<String> = None;
    arguments.iter().for_each(|each| last_text(each, &mut last));
    if let Some(folder) = last {
        for (name, body) in files {
            let path = Path::new(&folder).join(found_key(name));
            if let Some(parent) = path.parent() {
                let _ = std::fs::create_dir_all(parent);
            }
            let _ = std::fs::write(&path, text_of(Some(body)).unwrap_or_default());
        }
    }
    answer(get(&found, "$answer").unwrap_or(&Value::Null))
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
        grows: get(case, "grow").cloned().unwrap_or(Value::Null),
        home: get(case, "backend")
            .and_then(|found| text_of(get(found, "codex_home")))
            .map(PathBuf::from),
        slept: 0,
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
            let given = backend(case, log);
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
        let log: Log = Arc::new(Mutex::new(Vec::new()));
        let answer = one(case, &log);
        let mut entry = Map::new();
        entry.insert(Str::new("answer"), answer);
        let logged = log
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner())
            .clone();
        entry.insert(Str::new("log"), Value::Array(logged));
        results.push(Value::Object(entry));
    }
    let mut out = Map::new();
    out.insert(Str::new("results"), Value::Array(results));
    let written = to_string(&Value::Object(out), &Options::new()).unwrap_or_default();
    println!("{written}");
}
