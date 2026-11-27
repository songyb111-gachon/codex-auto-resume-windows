//! car-engine's sessions (S4.1): one engine kept across requests, driven step by step by `tests/rustdiff`'s engine
//! traces, and the calls of the outside world it makes asked back over the same pipe (PLAN 4.2).
//!
//! * `engine.open` {session, state, codex, clock, options, home_key, environ, notify_raises, engine_state, home_lock,
//!   connectivity}: car-store's `Store` on `state` (its clock the session's), car-codex's `LocalSource` on `codex`, and
//!   an `Engine` with the NULL plug (the standard edition), no words for this time, quiet hours read in UTC.
//! * `engine.step` {session, op, ...}: `clock` {value}, `tick`, `watch`, `policy` {values}, `store` {method, args,
//!   kwargs} (a person's action, through `store::call`), `after_sleep` {since, slept}, `retiring` {value}, `facts`.
//!   The reply is {result, log, notify}: the step's value (or `{"raised": class}`), and the engine's log lines and
//!   notifications since the last step.
//! * `engine.close` {session}.
//!
//! What the engine asks of the outside - the backend's five calls and jitter's draw - goes out as one line
//! `{"ask": name, "args": [...]}`, answered by one line `{"value": v}` or `{"raise": class}`, before the reply. The
//! launch guard of a send is entered here, on car-store's own write lock, exactly as `codexsim.SimBackend.send` enters
//! the reference's; only then is the send asked back.

use std::cell::RefCell;
use std::collections::HashMap;
use std::io::{BufRead, Write};
use std::panic::{AssertUnwindSafe, catch_unwind};
use std::path::Path;
use std::rc::Rc;
use std::sync::Arc;
use std::sync::atomic::{AtomicU64, Ordering};

use car_engine::seam::Codex;
use car_engine::{Backend, Claim, Engine, Given, LaunchGuard};
use car_machine::json::{Map, Options, Str, Value, from_str, to_string};
use car_machine::pyval::Py;
use car_policy::plug::Guarded;
use car_store::Store;

use crate::classify::Zone;
use crate::object;
use crate::policy::PlatformOs;

/// A Python exception class as a `'static` word.
fn class(name: &str) -> &'static str {
    match name {
        "OSError" => "OSError",
        "RuntimeError" => "RuntimeError",
        "ValueError" => "ValueError",
        "TypeError" => "TypeError",
        "KeyError" => "KeyError",
        "AttributeError" => "AttributeError",
        "StoreError" => "StoreError",
        other => Box::leak(other.to_owned().into_boxed_str()),
    }
}

/// One question to the Python side: written as a line, answered by the next line on stdin.
pub fn ask(name: &str, args: Vec<Value>) -> Py<Value> {
    let request = object([("ask", Value::from(name)), ("args", Value::Array(args))]);
    let text = to_string(&request, &Options::wire())
        .or_else(|_| to_string(&request, &Options::new()))
        .map_err(|_| "ValueError")?;
    {
        let mut out = std::io::stdout().lock();
        writeln!(out, "{text}").map_err(|_| "OSError")?;
        out.flush().map_err(|_| "OSError")?;
    }
    let mut line = String::new();
    std::io::stdin()
        .lock()
        .read_line(&mut line)
        .map_err(|_| "OSError")?;
    match from_str(line.trim()) {
        Ok(Value::Object(answer)) => {
            if let Some(Value::Str(raised)) = answer.get("raise") {
                return Err(class(raised.as_str().unwrap_or("Exception")));
            }
            Ok(answer.get("value").cloned().unwrap_or(Value::Null))
        }
        _ => Err("OSError"),
    }
}

pub use car_watcher::join::store::EngineStore;

/// With a scripted plug, every claim says what it was told of the plug's answers (`note.claim`).
fn note_claim(claim: &Claim) {
    let number = |found: Option<f64>| found.map_or(Value::Null, Value::Float);
    let pair = |found: Option<(f64, f64)>| {
        found.map_or(Value::Null, |(a, b)| {
            Value::Array(vec![Value::Float(a), Value::Float(b)])
        })
    };
    let _ = ask(
        "note.claim",
        vec![
            Value::Array(
                claim
                    .carried
                    .iter()
                    .map(|point| Value::from(point.as_str()))
                    .collect::<Vec<_>>(),
            ),
            claim.relaxed.as_deref().map_or(Value::Null, Value::from),
            pair(claim.resend),
            Value::Bool(claim.forced),
            pair(Some(claim.caps)),
            number(claim.quiet_until),
            Value::Bool(claim.plugged),
        ],
    );
}

/// The Codex processes, asked back: `codexsim.SimBackend` on the Python side answers.
pub struct AskBackend;

impl Backend for AskBackend {
    fn app_identity(&self) -> Py<Value> {
        ask("backend.app_identity", Vec::new())
    }
    fn loaded(&self, thread_id: &str, app_identity: &Value) -> Py<Value> {
        ask(
            "backend.loaded",
            vec![Value::from(thread_id), app_identity.clone()],
        )
    }
    fn usage(&self) -> Py<Value> {
        ask("backend.usage", Vec::new())
    }
    fn send(&self, thread_id: &str, prompt: &Str, launch_guard: &dyn LaunchGuard) -> Py<Value> {
        // `with launch_guard as permitted: <launch>` - the launch is the guard's body, as codex/transport.py starts
        // `codex queue` inside it (store/claims.py: a Cancel, a Pause and a conversation switched off take the same
        // write lock, so a launch never uses consent withdrawn a moment before). The stand-in is asked while car-store's
        // write lock is held, told what the guard found, and refuses as SimBackend refuses. A product backend does the
        // same: its launch inside `enter`'s body, never after it.
        // The stand-in writes the send down where it is called, before its guard is entered, as the reference's
        // recording backend does: a guard that asks the plug's ledger (a record's `record_guard`, seat S7.2a2) puts
        // that question after the send in both traces.
        ask(
            "backend.send_noted",
            vec![Value::from(thread_id), Value::Str(prompt.clone())],
        )?;
        let mut sent: Py<Value> = Ok(Value::Null);
        launch_guard.enter(&mut |permitted| {
            sent = ask(
                "backend.send",
                vec![
                    Value::from(thread_id),
                    Value::Str(prompt.clone()),
                    Value::Bool(permitted),
                    Value::Bool(true),
                ],
            );
            Value::Null
        })?;
        sent
    }
    fn delete_queue(&self, thread_id: &str, queue_id: &str) -> Py<Value> {
        ask(
            "backend.delete_queue",
            vec![Value::from(thread_id), Value::from(queue_id)],
        )
    }
    // The attributes read with getattr(backend, name, None), asked of the stand-in (review 6, S4).
    fn app_look(&self) -> Value {
        attribute("app_look")
    }
    fn app_unmatched_reason(&self) -> Value {
        attribute("app_unmatched_reason")
    }
    fn protocol_results(&self) -> Value {
        attribute("protocol_results")
    }
    fn session_holder(&self) -> Value {
        attribute("session_holder")
    }
    fn engine_version(&self) -> Value {
        attribute("engine_version")
    }
    fn holder(&self, thread_id: &str) -> Option<Py<Value>> {
        match ask("backend.holder", vec![Value::from(thread_id)]) {
            Ok(Value::Array(pair))
                if pair
                    .first()
                    .is_some_and(car_policy::classify::value::truthy) =>
            {
                Some(Ok(pair.get(1).cloned().unwrap_or(Value::Null)))
            }
            Ok(_) => None,
            Err(raised) => Some(Err(raised)),
        }
    }
}

fn attribute(name: &str) -> Value {
    ask("backend.getattr", vec![Value::from(name)]).unwrap_or(Value::Null)
}

/// One engine kept across requests.
struct Session {
    engine: Engine,
    /// Whether the engine's plug is the scripted one (`engine.open`'s `plug`): its failures are part of the facts.
    scripted: bool,
    store: Rc<Store>,
    clock: Arc<AtomicU64>,
    logs: Rc<RefCell<Vec<Value>>>,
    notes: Rc<RefCell<Vec<Value>>>,
}

thread_local! {
    static SESSIONS: RefCell<HashMap<i64, Session>> = RefCell::new(HashMap::new());
}

fn raised(class: &str) -> Value {
    object([("raised", Value::from(class))])
}

fn unit(found: Py<()>) -> Value {
    match found {
        Ok(()) => Value::Null,
        Err(class) => raised(class),
    }
}

fn number(request: &Map, name: &str) -> f64 {
    request
        .get(name)
        .and_then(car_policy::classify::value::arithmetic)
        .unwrap_or(0.0)
}

fn text<'a>(request: &'a Map, name: &str) -> &'a str {
    request
        .get(name)
        .and_then(car_policy::classify::value::text)
        .unwrap_or_default()
}

fn open(request: &Map) -> Result<Session, String> {
    let clock = Arc::new(AtomicU64::new(number(request, "clock").to_bits()));
    let state = Path::new(text(request, "state"));
    let at = clock.clone();
    let options = car_store::Options {
        migrate: false,
        check: true,
        clock: Box::new(move || f64::from_bits(at.load(Ordering::SeqCst))),
        links: crate::links::for_store(),
    };
    let store = Rc::new(
        Store::open_with(state, options)
            .map_err(|error| format!("{}: {}", error.class(), error.message()))?,
    );
    let source =
        car_codex::source::LocalSource::new(Arc::new(PlatformOs), text(request, "codex"), None)
            .map_err(|error| error.class().to_owned())?;
    let logs = Rc::new(RefCell::new(Vec::new()));
    let notes = Rc::new(RefCell::new(Vec::new()));
    let (log_into, note_into) = (logs.clone(), notes.clone());
    let notify_raises = matches!(request.get("notify_raises"), Some(Value::Bool(true)));
    let scripted = matches!(request.get("plug"), Some(Value::Bool(true)));
    let engine_state = request
        .get("engine_state")
        .cloned()
        .unwrap_or_else(|| Value::from("verified"));
    let home_lock = !matches!(request.get("home_lock"), Some(Value::Bool(false)));
    let connectivity = request.get("connectivity").cloned().unwrap_or(Value::Null);
    let environ = match request.get("environ") {
        Some(Value::Object(environ)) => environ.clone(),
        _ => Map::new(),
    };
    let at = clock.clone();
    let given = Given {
        dispatch_lock: None,
        clock: Box::new(move || f64::from_bits(at.load(Ordering::SeqCst))),
        log: Some(Box::new(move |thread, event, detail| {
            log_into.borrow_mut().push(Value::Array(vec![
                thread.map_or(Value::Null, Value::from),
                Value::from(event),
                detail.clone(),
            ]));
        })),
        options: match request.get("options") {
            Some(Value::Object(options)) => options.clone(),
            _ => Map::new(),
        },
        notify: Some(Box::new(move |event, payload| {
            note_into.borrow_mut().push(Value::Array(vec![
                Value::from(event),
                Value::Object(payload.clone()),
            ]));
            if notify_raises {
                Err("RuntimeError")
            } else {
                Ok(())
            }
        })),
        language: None,
        home_lock: Some(Box::new(move || Ok(home_lock))),
        engine_state: Some(Box::new(move || Ok(engine_state.clone()))),
        plug: Arc::new(if matches!(request.get("plug"), Some(Value::Bool(true))) {
            Guarded::new(Box::new(crate::plugscript::Scripted::asking()))
        } else {
            Guarded::null()
        }),
        connectivity: Some(Box::new(move || Ok(connectivity.clone()))),
        home_key: text(request, "home_key").to_owned(),
        open_store: false,
        once_words: None,
        draw: Box::new(|| {
            ask("draw", Vec::new())
                .ok()
                .and_then(|value| car_policy::classify::value::arithmetic(&value))
                .unwrap_or(0.0)
        }),
        local: Box::new(Zone::of(&Value::Array(vec![
            Value::from(0),
            Value::from(0),
            Value::from(0),
            Value::from(0),
        ]))),
        environ: Box::new(move |name| {
            environ
                .get(name)
                .and_then(car_policy::classify::value::text)
                .map(str::to_owned)
        }),
        windows_languages: Box::new(Vec::new),
        os: Arc::new(PlatformOs),
    };
    let engine = Engine::new(
        Box::new(EngineStore(
            store.clone(),
            scripted.then_some(note_claim as fn(&Claim)),
        )),
        Box::new(Codex(source)),
        Box::new(AskBackend),
        given,
    );
    Ok(Session {
        engine,
        scripted: matches!(request.get("plug"), Some(Value::Bool(true))),
        store,
        clock,
        logs,
        notes,
    })
}

fn step(session: &mut Session, request: &Map) -> Value {
    let engine = &mut session.engine;
    match text(request, "op") {
        "clock" => {
            session
                .clock
                .store(number(request, "value").to_bits(), Ordering::SeqCst);
            Value::Null
        }
        "tick" => unit(engine.tick()),
        "watch" => unit(engine.watch()),
        "policy" => {
            let values = request.get("values").cloned().unwrap_or(Value::Null);
            let managed = request.get("managed").and_then(crate::proxy::managed);
            engine.apply_policy(&values, managed);
            Value::Null
        }
        "store" => crate::store::call(&session.store, request),
        "after_sleep" => {
            match engine.after_sleep(number(request, "since"), number(request, "slept")) {
                Ok(held) => Value::from(held),
                Err(class) => raised(class),
            }
        }
        "retiring" => {
            engine.retiring = matches!(request.get("value"), Some(Value::Bool(true)));
            Value::Null
        }
        "facts" => {
            let mut facts = match object([
                (
                    "detection_failed",
                    engine.detection_failed.map_or(Value::Null, Value::Bool),
                ),
                (
                    "watch_needed",
                    match engine.watch_needed() {
                        Ok(found) => Value::Bool(found),
                        Err(class) => raised(class),
                    },
                ),
                ("activity", {
                    let threads: Vec<String> = match request.get("threads") {
                        Some(Value::Array(items)) => items
                            .iter()
                            .filter_map(|item| {
                                car_policy::classify::value::text(item).map(str::to_owned)
                            })
                            .collect(),
                        _ => Vec::new(),
                    };
                    Value::Object(engine.activity(&threads))
                }),
                (
                    "last_usage",
                    engine.last_usage().map_or(Value::Null, |(at, windows)| {
                        Value::Array(vec![Value::Float(at), Value::Array(windows)])
                    }),
                ),
            ]) {
                Value::Object(facts) => facts,
                _ => Map::new(),
            };
            // How many of the scripted plug's hooks failed (an `Err` or a panic), as `Guarded.failures` counts them.
            if session.scripted {
                facts.insert(
                    "plug_failures".into(),
                    Value::from(i64::try_from(engine.plug.failures()).unwrap_or(i64::MAX)),
                );
            }
            Value::Object(facts)
        }
        "judge" => crate::judge::run(request),
        _ => raised("not_ported"),
    }
}

/// `engine.open`, `engine.step`, `engine.close`: the reply's value.
pub fn answer(call: &str, request: &Map) -> Value {
    let id = request
        .get("session")
        .and_then(|value| match value {
            Value::Int(number) => number.as_i64(),
            _ => None,
        })
        .unwrap_or(0);
    match call {
        "engine.open" => match catch_unwind(AssertUnwindSafe(|| open(request))) {
            Ok(Ok(session)) => {
                SESSIONS.with(|sessions| sessions.borrow_mut().insert(id, session));
                Value::Null
            }
            Ok(Err(why)) => object([("raised", Value::from(why.as_str()))]),
            Err(_) => raised("panic"),
        },
        "engine.close" => {
            SESSIONS.with(|sessions| sessions.borrow_mut().remove(&id));
            Value::Null
        }
        "engine.step" => SESSIONS.with(|sessions| {
            let mut sessions = sessions.borrow_mut();
            let Some(session) = sessions.get_mut(&id) else {
                return raised("no_session");
            };
            // D15: a panic is caught at the boundary, and said.
            let result = catch_unwind(AssertUnwindSafe(|| step(session, request)))
                .unwrap_or_else(|_| raised("panic"));
            let log = std::mem::take(&mut *session.logs.borrow_mut());
            let notify = std::mem::take(&mut *session.notes.borrow_mut());
            object([
                ("result", result),
                ("log", Value::Array(log)),
                ("notify", Value::Array(notify)),
            ])
        }),
        _ => raised("not_ported"),
    }
}

/// Whether a line is one of this module's calls.
pub fn is_engine_call(line: &str) -> bool {
    line.contains("\"engine.")
}

/// Read one request line from stdin, the way the serve loop and the asker share it.
pub fn read_line() -> Option<String> {
    let mut line = String::new();
    match std::io::stdin().lock().read_line(&mut line) {
        Ok(0) | Err(_) => None,
        Ok(_) => Some(line),
    }
}
