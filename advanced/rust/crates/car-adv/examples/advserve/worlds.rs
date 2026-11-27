//! The worlds of the shipped codes (owner Q3 (c), completion part 1): what a code made by car-adv's own `make` reads of
//! the outside world - Codex's home and files, the app's channel, the backend and its sessions, the settings' locale -
//! asked back of the test, each seam by its name (`{"ask": "world", "capability", "seam", "args"}`). The test answers
//! with the reference's own function for it at the time of the ask (tests/rustdiff/advproxy/worlds.py), so what a test
//! patched or set on the code (`code._stop = ...`, `patch.object(inuse, "home", ...)`) is what car-adv meets; what the
//! code decides is car-adv's.
//!
//! A shipped code this module makes no world for is car-adv's `capabilities::make`; the world those reach (the usage
//! family's installed one) is [`refusing`] here, so nothing in this process ever reaches this PC's Codex.

use std::cell::RefCell;
use std::sync::Arc;

use car_adv::capabilities::{Code, Raised};
use car_adv::codex::inuse::Looked;
use car_adv::codex::ipc::{Gate, GateRaised};
use car_adv::codex::session::{Channel, SessionError};
use car_adv::engine::usage::{self, CodexReads, MeterBackend, TurnSeen};
use car_adv::engine::{credits, resetmessage, usagestop};
use car_adv::registry::CapabilityDef;
use car_adv::statement::Catalogs;
use car_config::Paths;
use car_machine::json::Value;

use crate::proxied::int;
use crate::wire::{self, field, text, word};

// ------------------------------------------------------------------ the gates a seam is handed

thread_local! {
    /// The gates of the seams being asked, innermost last: a test's `with gate() as permitted` enters and leaves the
    /// one its ask was handed, by number (`{"call": "gate"}`), while that ask waits.
    static GATES: RefCell<Vec<*mut (dyn Gate + 'static)>> = const { RefCell::new(Vec::new()) };
}

fn with_gate<R>(gate: &mut dyn Gate, body: impl FnOnce(i64) -> R) -> R {
    let pointer: *mut (dyn Gate + '_) = gate;
    // SAFETY: the pointer is used only by `gate_call`, from a request read while `body` waits for its answer - inside
    // this call, where `gate` is borrowed - and it is taken off the stack before this returns.
    let pointer: *mut (dyn Gate + 'static) = unsafe { std::mem::transmute(pointer) };
    let number = GATES.with(|gates| {
        let mut gates = gates.borrow_mut();
        gates.push(pointer);
        gates.len() as i64 - 1
    });
    let found = body(number);
    GATES.with(|gates| gates.borrow_mut().truncate(number as usize));
    found
}

/// `{"call": "gate", "gate": n, "method": "enter" | "exit"}`: the gate a waiting seam was handed, entered or left.
pub fn gate_call(number: i64, method: &str) -> Result<Value, String> {
    let pointer = GATES.with(|gates| gates.borrow().get(number as usize).copied());
    let Some(pointer) = pointer else {
        return Err("no such gate".to_owned());
    };
    // SAFETY: see `with_gate` - the gate is alive and borrowed for the ask this request is made inside.
    let gate = unsafe { &mut *pointer };
    match method {
        "enter" => gate.enter().map_err(|GateRaised| "Exception".to_owned()),
        "exit" => gate
            .exit()
            .map(|()| Value::Null)
            .map_err(|GateRaised| "Exception".to_owned()),
        _ => Err("AttributeError".to_owned()),
    }
}

// ------------------------------------------------------------------ asking

#[derive(Clone)]
struct Asker {
    session: i64,
    capability: String,
}

impl Asker {
    fn ask(&self, seam: &str, args: Vec<Value>) -> Result<Value, Raised> {
        wire::ask(
            "world",
            vec![
                ("session", int(self.session)),
                ("capability", text(&self.capability)),
                ("seam", text(seam)),
                ("args", Value::Array(args)),
            ],
        )
    }
}

fn leak(class: &str) -> &'static str {
    Box::leak(class.to_owned().into_boxed_str())
}

fn strings(found: &Value) -> Vec<String> {
    match found {
        Value::Array(items) => items
            .iter()
            .filter_map(|item| word(item).map(str::to_owned))
            .collect(),
        _ => Vec::new(),
    }
}

fn number(found: &Value) -> Option<f64> {
    match found {
        Value::Int(whole) => whole.as_i64().map(|each| each as f64),
        Value::Float(each) => Some(*each),
        _ => None,
    }
}

// ------------------------------------------------------------------ Codex's files: Turns and LocalSource, the test's

struct AskCodex(Asker);

impl CodexReads for AskCodex {
    fn running(&self, home: &str, _paths: &Paths) -> Result<Vec<String>, Raised> {
        Ok(strings(&self.0.ask("running", vec![text(home)])?))
    }
    fn latest(&self, home: &str, thread: &str) -> Result<Option<TurnSeen>, Raised> {
        let found = self.0.ask("latest", vec![text(home), text(thread)])?;
        if matches!(found, Value::Null) {
            return Ok(None);
        }
        Ok(Some(TurnSeen {
            status: word(field(&found, "status")).unwrap_or_default().to_owned(),
            ordinal: field(&found, "ordinal").clone(),
            turn_id: field(&found, "turn_id").clone(),
        }))
    }
    fn between(
        &self,
        home: &str,
        thread: &str,
        after: &Value,
        before: &Value,
    ) -> Result<i64, Raised> {
        let found = self.0.ask(
            "between",
            vec![text(home), text(thread), after.clone(), before.clone()],
        )?;
        Ok(number(&found).map_or(0, |each| each as i64))
    }
    fn source(&self, home: &str) -> Result<(), Raised> {
        self.0.ask("source", vec![text(home)]).map(|_| ())
    }
    fn source_latest(
        &self,
        home: &str,
        thread: &str,
        widened: bool,
    ) -> Result<Option<Value>, Raised> {
        let found = self.0.ask(
            "source_latest",
            vec![text(home), text(thread), Value::Bool(widened)],
        )?;
        Ok((!matches!(found, Value::Null)).then_some(found))
    }
}

// ------------------------------------------------------------------ the app's channel: ipc's stop and start

struct AskIpc(Asker);

impl AskIpc {
    fn turn(
        &self,
        seam: &str,
        one: &Value,
        two: &Value,
        gate: &mut dyn Gate,
    ) -> Result<String, Raised> {
        with_gate(gate, |number| {
            let found = self
                .0
                .ask(seam, vec![one.clone(), two.clone(), int(number)])?;
            Ok(word(&found).unwrap_or_default().to_owned())
        })
    }
}

impl usagestop::Ipc for AskIpc {
    fn stop_turn(
        &self,
        thread: &Value,
        turn_id: &Value,
        gate: &mut dyn Gate,
    ) -> Result<String, Raised> {
        self.turn("stop_turn", thread, turn_id, gate)
    }
    fn start_turn(
        &self,
        thread: &Value,
        text_: &Value,
        gate: &mut dyn Gate,
    ) -> Result<String, Raised> {
        self.turn("start_turn", thread, text_, gate)
    }
}

// ------------------------------------------------------------------ objects the test's world made: a backend, a session

struct AskObject {
    asker: Asker,
    object: i64,
}

impl AskObject {
    fn asked(&self, method: &str, args: Vec<Value>) -> Result<Value, Raised> {
        self.asker.ask(
            "object",
            vec![int(self.object), text(method), Value::Array(args)],
        )
    }
}

fn object_number(found: &Value) -> i64 {
    match field(found, "object") {
        Value::Int(whole) => whole.as_i64().unwrap_or(0),
        _ => 0,
    }
}

impl Looked for AskObject {
    fn codex_exe(&self) -> Option<String> {
        self.asked("codex_exe", Vec::new())
            .ok()
            .and_then(|found| word(&found).map(str::to_owned))
    }
    fn served_elsewhere(&self) -> Vec<String> {
        self.asked("served_elsewhere", Vec::new())
            .map(|found| strings(&found))
            .unwrap_or_default()
    }
}

impl MeterBackend for AskObject {
    fn app_identity(&mut self) -> Result<Option<Value>, Raised> {
        let found = self.asked("app_identity", Vec::new())?;
        Ok((!matches!(found, Value::Null)).then_some(found))
    }
    fn app_look(&self) -> Option<String> {
        self.asked("app_look", Vec::new())
            .ok()
            .and_then(|found| word(&found).map(str::to_owned))
    }
    fn compatible(&mut self) -> Result<(), Raised> {
        self.asked("compatible", Vec::new()).map(|_| ())
    }
}

/// A session's answer: its value, or `{"__session_error__": class, "code", "method"}` - the reference's own raise.
fn session_answer(found: Result<Value, Raised>) -> Result<Value, SessionError> {
    let found = found.map_err(|raised| SessionError::Raised(leak(&raised.class)))?;
    let said = field(&found, "__session_error__");
    let Some(class) = word(said) else {
        return Ok(found);
    };
    Err(match class {
        "SessionRefused" => SessionError::Refused,
        "AdapterError" => {
            SessionError::Adapter(leak(word(field(&found, "code")).unwrap_or("adapter")))
        }
        "RefusedByCodex" => SessionError::ByCodex {
            method: word(field(&found, "method")).unwrap_or_default().to_owned(),
            code: number(field(&found, "number")).map(|each| each as i64),
        },
        other => SessionError::Raised(leak(other)),
    })
}

impl Channel for AskObject {
    fn enter(&mut self) -> Result<(), SessionError> {
        session_answer(self.asked("__enter__", Vec::new())).map(|_| ())
    }
    fn submit(&mut self, method: &str, params: Option<Value>) -> Result<i64, SessionError> {
        let found = session_answer(
            self.asked("submit", vec![text(method), params.unwrap_or(Value::Null)]),
        )?;
        Ok(number(&found).map_or(0, |each| each as i64))
    }
    fn receive(
        &mut self,
        method: &str,
        sequence: i64,
        params: Option<&Value>,
    ) -> Result<Value, SessionError> {
        session_answer(self.asked(
            "receive",
            vec![
                text(method),
                int(sequence),
                params.cloned().unwrap_or(Value::Null),
            ],
        ))
    }
    fn drain_events(&mut self) -> Vec<Value> {
        match self.asked("drain_events", Vec::new()) {
            Ok(Value::Array(items)) => items,
            _ => Vec::new(),
        }
    }
    fn exit(&mut self) {
        let _ = self.asked("__exit__", Vec::new());
    }
}

// ------------------------------------------------------------------ the usage family's world

fn catalogs_of(session: i64, folder: &str) -> Arc<Catalogs> {
    Arc::new(Catalogs::new(
        folder.to_owned(),
        Box::new(move || {
            crate::ask_value(session, "language")
                .ok()
                .and_then(|found| word(&found).map(str::to_owned))
                .unwrap_or_else(|| "en".to_owned())
        }),
    ))
}

/// What a code of the usage family reads (engine/usage.py, usagestop.py, credits.py, resetmessage.py), every seam
/// asked of the test for `capability`.
pub fn usage_world(session: i64, capability: &str, catalogs: &str) -> usage::World {
    let asker = Asker {
        session,
        capability: capability.to_owned(),
    };
    let (locale, home, backend, open, keys, switched) = (
        asker.clone(),
        asker.clone(),
        asker.clone(),
        asker.clone(),
        asker.clone(),
        asker.clone(),
    );
    usage::World {
        catalogs: catalogs_of(session, catalogs),
        clock: Arc::new(car_platform::localclock::Crt),
        locale: Arc::new(move |_: &Paths| match locale.ask("locale", Vec::new()) {
            Ok(Value::Str(found)) => Ok(found.as_str().unwrap_or_default().to_owned()),
            _ => Err(()),
        }),
        codex: Arc::new(AskCodex(asker.clone())),
        home: Arc::new(move |_: &Paths| {
            let found = home.ask("home", Vec::new())?;
            Ok(word(&found).unwrap_or_default().to_owned())
        }),
        backend: Arc::new(move |_: &Paths| {
            let found = backend.ask("backend", Vec::new())?;
            Ok(Box::new(AskObject {
                asker: backend.clone(),
                object: object_number(&found),
            }) as Box<dyn MeterBackend>)
        }),
        open: Arc::new(move |_: &Paths, named: &str| {
            let found = session_answer(open.ask("open", vec![text(named)]))?;
            Ok(Box::new(AskObject {
                asker: open.clone(),
                object: object_number(&found),
            }) as Box<dyn Channel>)
        }),
        keys: Arc::new(move || {
            keys.ask("key", Vec::new())
                .ok()
                .and_then(|found| word(&found).map(str::to_owned))
                .unwrap_or_default()
        }),
        switched: Arc::new(move |_: &Paths| {
            switched
                .ask("switched", Vec::new())
                .ok()
                .and_then(|found| number(&found))
        }),
        ipc: Arc::new(AskIpc(asker)),
    }
}

/// The world `install_world` is given at the start: every seam refuses (no home, no backend, no session, the app's
/// channel answering no), so a code made with car-adv's defaults never reaches this PC's Codex from here.
pub fn refusing() -> usage::World {
    struct Refuse;
    impl CodexReads for Refuse {
        fn running(&self, _: &str, _: &Paths) -> Result<Vec<String>, Raised> {
            Err(Raised::new("TurnsUnavailable"))
        }
        fn latest(&self, _: &str, _: &str) -> Result<Option<TurnSeen>, Raised> {
            Err(Raised::new("TurnsUnavailable"))
        }
        fn between(&self, _: &str, _: &str, _: &Value, _: &Value) -> Result<i64, Raised> {
            Err(Raised::new("TurnsUnavailable"))
        }
        fn source(&self, _: &str) -> Result<(), Raised> {
            Err(Raised::new("SourceError"))
        }
        fn source_latest(&self, _: &str, _: &str, _: bool) -> Result<Option<Value>, Raised> {
            Err(Raised::new("SourceError"))
        }
    }
    impl usagestop::Ipc for Refuse {
        fn stop_turn(&self, _: &Value, _: &Value, _: &mut dyn Gate) -> Result<String, Raised> {
            Ok("refused".to_owned())
        }
        fn start_turn(&self, _: &Value, _: &Value, _: &mut dyn Gate) -> Result<String, Raised> {
            Ok("refused".to_owned())
        }
    }
    usage::World {
        catalogs: Arc::new(Catalogs::new("locales", Box::new(|| "en".to_owned()))),
        clock: Arc::new(car_platform::localclock::Crt),
        locale: Arc::new(|_: &Paths| Err(())),
        codex: Arc::new(Refuse),
        home: Arc::new(|_: &Paths| Err(Raised::new("AdapterError"))),
        backend: Arc::new(|_: &Paths| Err(Raised::new("AdapterError"))),
        open: Arc::new(|_: &Paths, _: &str| Err(SessionError::Adapter("backend_unavailable"))),
        keys: Arc::new(String::new),
        switched: Arc::new(|_: &Paths| None),
        ipc: Arc::new(Refuse),
    }
}

/// A shipped capability's code with its world asked of the test, for the families this module serves; `None` for
/// any other (car-adv's own `capabilities::make` makes it).
pub fn make(
    definition: &CapabilityDef,
    paths: &Paths,
    session: i64,
    catalogs: &str,
) -> Option<Option<Box<dyn Code>>> {
    let world = || usage_world(session, &definition.id, catalogs);
    let made: Box<dyn Code> = match definition.id.as_str() {
        "usage_meter" => Box::new(usage::UsageMeter::new(paths.clone(), world())),
        "usage_wrap_up" => Box::new(usage::UsageWrapUp::new(paths.clone(), world())),
        "usage_pause" => Box::new(usagestop::UsageStop::new(paths.clone(), world())),
        "reset_message" => Box::new(resetmessage::ResetMessage::new(paths.clone(), world().open)),
        "reset_credit" => {
            let made = world();
            Box::new(credits::ResetCredit::new(
                paths.clone(),
                made.open,
                made.keys,
            ))
        }
        _ => return None,
    };
    Some(Some(made))
}
