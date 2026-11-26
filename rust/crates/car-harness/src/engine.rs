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

use car_engine::seam::{Claimed, Codex, Correlate, Withdrawn};
use car_engine::{Backend, Claim, Engine, Given, LaunchGuard, Register};
use car_machine::json::{Map, Options, Str, Value, from_str, to_string};
use car_machine::pyval::Py;
use car_policy::classify::gates::Vector;
use car_policy::plug::Guarded;
use car_store::Store;
use car_store::records::Update;

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

fn py<T>(found: car_store::Result<T>) -> Py<T> {
    found.map_err(|error| error.class())
}

/// car-store's `Store` as the engine holds it; with a scripted plug, every claim says what it was told of the plug's
/// answers (`note.claim`), which nothing else of a trace shows.
pub struct EngineStore(pub Rc<Store>, pub bool);

impl car_scheduler::Store for EngineStore {
    fn get(&self, interruption_id: &str) -> Py<Option<Map>> {
        py(self.0.get(interruption_id))
    }
    fn update(
        &self,
        interruption_id: &str,
        changes: &Map,
        at: Option<f64>,
        event: Option<&str>,
        flags: i64,
    ) -> Py<()> {
        let options = Update {
            at,
            actor: "engine".into(),
            event: event.map(str::to_owned),
            flags,
        };
        py(self.0.update(interruption_id, changes, &options))
    }
    fn thread_enabled(&self, thread_id: &str) -> Py<bool> {
        py(self.0.thread_enabled(thread_id))
    }
    fn settings(&self) -> Py<Map> {
        py(self.0.settings())
    }
    fn correlate(
        &self,
        interruption_id: &str,
        recovery_turn_id: &str,
        now: f64,
        options: &Correlate,
    ) -> Py<bool> {
        let options = car_store::claims::Correlate {
            client_id: options.client_id.clone(),
            status: options.status.clone(),
            state: options.state.clone(),
            reason: options.reason.clone(),
            after_user_work: options.after_user_work,
            user_joined: options.user_joined,
            extra_event: options.extra_event.clone(),
        };
        py(self
            .0
            .correlate(interruption_id, recovery_turn_id, now, &options))
    }
    fn release_withdrawn(&self, interruption_id: &str, now: f64, proofs: &Withdrawn) -> Py<bool> {
        let proofs = car_store::claims::Withdrawn {
            window: proofs.window,
            later_turn: proofs.later_turn,
            marker_rows: proofs.marker_rows,
            row_present: proofs.row_present,
            fresh: proofs.fresh,
            target: proofs.target.clone(),
            next_retry_at: proofs.next_retry_at,
        };
        py(self.0.release_withdrawn(interruption_id, now, &proofs))
    }
    fn records_in(&self, states: &[&str], home_key: Option<&str>) -> Py<Vec<Map>> {
        let states: Vec<String> = states.iter().map(|state| (*state).to_owned()).collect();
        py(self.0.records_in(&states, home_key))
    }
}

impl EngineStore {
    /// `reserve_detailed(...)`, noted for the traces, with the plug's ledger where the engine hands it.
    fn claim_with(
        &self,
        interruption_id: &str,
        now: f64,
        claim: &Claim,
        ledger: Option<&car_policy::plug::Guarded>,
    ) -> Py<Claimed> {
        if self.1 {
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
        let options = car_store::claims::Claim {
            plugged: claim.plugged,
            carried: claim.carried.clone(),
            limits: Some(claim.limits.clone()),
            gates: Some(claim.gates.clone()),
            quiet_until: claim.quiet_until,
            relaxed: claim.relaxed.clone(),
            resend: claim.resend,
            forced: claim.forced,
            caps: Some(claim.caps),
        };
        py(self
            .0
            .reserve_ledgered(interruption_id, now, &options, ledger))
    }
}

impl car_engine::Store for EngineStore {
    fn record_gates(&self, interruption_id: &str, gates: &Vector, now: f64) -> Py<()> {
        py(self.0.record_gates(interruption_id, gates, now))
    }
    fn record_would_send(
        &self,
        interruption_id: &str,
        gates: &Vector,
        now: f64,
        next_retry_at: f64,
    ) -> Py<bool> {
        py(self
            .0
            .record_would_send(interruption_id, gates, now, next_retry_at))
    }
    fn submission_guard(
        &self,
        interruption_id: &str,
        body: &mut dyn FnMut(bool) -> Value,
    ) -> Py<Value> {
        py(self.0.submission_guard(interruption_id, body))
    }
    fn errand_guard(
        &self,
        held: &mut dyn FnMut() -> Py<bool>,
        body: &mut dyn FnMut(bool) -> Value,
    ) -> Py<Value> {
        py(self.0.errand_guard(Some(held), body))
    }
    fn recent_claims(&self, thread_id: &str, since: f64) -> Py<Vec<Value>> {
        py(self.0.recent_claims(thread_id, since))
    }
    fn recent_claim_count(&self, thread_id: &str, since: f64) -> Py<i64> {
        py(self.0.recent_claim_count(thread_id, since))
    }
    fn others_in_flight(&self, thread_id: &str, exclude: &str) -> Py<i64> {
        py(self.0.others_in_flight(thread_id, exclude))
    }
    fn reserve_detailed(&self, interruption_id: &str, now: f64, claim: &Claim) -> Py<Claimed> {
        self.claim_with(interruption_id, now, claim, None)
    }
    fn reserve_ledgered(
        &self,
        interruption_id: &str,
        now: f64,
        claim: &Claim,
        ledger: &car_policy::plug::Guarded,
    ) -> Py<Claimed> {
        self.claim_with(interruption_id, now, claim, Some(ledger))
    }
    fn reserve_record(
        &self,
        record: &Map,
        now: f64,
        ledger: &car_policy::plug::Guarded,
        quiet_until: Option<f64>,
    ) -> Py<Claimed> {
        py(self.0.reserve_record(record, now, ledger, quiet_until))
    }
    fn record_guard(
        &self,
        record: &Map,
        ledger: &car_policy::plug::Guarded,
        now: f64,
        body: &mut dyn FnMut(bool) -> Value,
    ) -> Py<Value> {
        py(self.0.record_guard(record, ledger, now, body))
    }
    fn release_claim(
        &self,
        interruption_id: &str,
        target: &str,
        reason: &str,
        now: f64,
        next_retry_at: Option<f64>,
    ) -> Py<bool> {
        py(self.0.release_claim(
            interruption_id,
            target,
            reason,
            now,
            next_retry_at,
            "engine",
        ))
    }
    fn claimed_on_thread(&self, thread_id: &str) -> Py<Vec<Map>> {
        py(self.0.claimed_on_thread(thread_id))
    }
    fn chain_parent(
        &self,
        thread_id: &str,
        turn_id: &str,
        owner_id: Option<&str>,
    ) -> Py<Option<Map>> {
        py(self.0.chain_parent(thread_id, turn_id, owner_id))
    }
    fn register(&self, detection: &Map, now: f64, options: &Register) -> Py<bool> {
        let options = car_store::records::Register {
            state: options.state.clone(),
            next_retry_at: Some(options.next_retry_at),
            owner_id: options.owner_id.clone(),
            failed_turn_progress: options.failed_turn_progress.clone(),
            legacy_carry: options.legacy_carry.clone(),
            limits: Some(options.limits.clone()),
            hold: options.hold.clone(),
            task_print: options.task_print.clone(),
            context_tokens: options.context_tokens.clone(),
            home_key: Value::from(options.home_key.as_str()),
        };
        py(self.0.register(detection, now, &options))
    }
    fn thread_tier(&self, thread_id: &str) -> Py<Value> {
        py(self.0.thread_tier(thread_id))
    }
    fn enrol_conversation(&self, thread_id: &str, tier: &str, now: f64) -> Py<bool> {
        py(self
            .0
            .enrol_conversation(thread_id, &Value::from(tier), now))
    }
    fn hold_changed(&self, interruption_id: &str, task_print: &Value, now: f64) -> Py<bool> {
        py(self
            .0
            .hold_changed(interruption_id, task_print, now, "engine"))
    }
    fn hold_waiting(&self, interruption_ids: &[String], hold: &str, now: f64) -> Py<i64> {
        py(self.0.hold_waiting(interruption_ids, hold, now, "engine"))
    }
    fn cancel_waiting(
        &self,
        interruption_ids: &[String],
        now: f64,
        reason: &str,
    ) -> Py<Vec<Value>> {
        let keys: Vec<Value> = interruption_ids
            .iter()
            .map(|key| Value::from(key.as_str()))
            .collect();
        py(self.0.cancel_waiting(&keys, now, reason))
    }
    fn open_objection_window(&self, interruption_id: &str, until: f64, now: f64) -> Py<bool> {
        py(self.0.open_objection_window(interruption_id, until, now))
    }
    fn raise_notice(&self, notice_key: &str, thread_id: &str, kind: &str, now: f64) -> Py<bool> {
        py(self.0.raise_notice(notice_key, thread_id, kind, now))
    }
    fn watcher_status(&self) -> Py<Option<Map>> {
        py(self.0.watcher_status())
    }
    fn usage_checks_asked(&self, now: f64) -> Py<Map> {
        py(self.0.usage_checks_asked(now))
    }
    fn usage_not_checked(&self, interruption_id: &str, now: f64, why: &str) -> Py<()> {
        py(self.0.usage_not_checked(interruption_id, now, why))
    }
    fn usage_check_taken(&self, interruption_id: &str) -> Py<Value> {
        Ok(self
            .0
            .usage_check_taken(interruption_id)
            .map_or(Value::Null, |source| Value::from(source.as_str())))
    }
    fn usage_checked(
        &self,
        interruption_id: &str,
        now: f64,
        read: &str,
        source: &Value,
    ) -> Py<Option<Map>> {
        let source = car_policy::classify::value::text(source).unwrap_or_default();
        py(self.0.usage_checked(interruption_id, now, read, source))
    }
    fn early_check_asked(&self, now: f64) -> Py<bool> {
        Ok(self.0.early_check_asked(now))
    }
    fn early_check_taken(&self) -> Py<()> {
        self.0.early_check_taken();
        Ok(())
    }
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
        let mut sent: Py<Value> = Ok(Value::Null);
        launch_guard.enter(&mut |permitted| {
            sent = ask(
                "backend.send",
                vec![
                    Value::from(thread_id),
                    Value::Str(prompt.clone()),
                    Value::Bool(permitted),
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
        plug: if matches!(request.get("plug"), Some(Value::Bool(true))) {
            Guarded::new(Box::new(crate::plugscript::Scripted::asking()))
        } else {
            Guarded::null()
        },
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
        Box::new(EngineStore(store.clone(), scripted)),
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
