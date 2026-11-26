//! `advserve` (seat S7.2a3, the advanced proxy, owner Q3 (c)): car-adv's runtime, state and arming served over a pipe,
//! one session per object the test made, so `advanced/tests` run unedited on Rust (`tests/rustdiff/advproxy/`).
//!
//! The model is car-harness's `serve` for the scenario proxy (S4.2): one process per test process, a JSON line each
//! way. A request is `{"id", "call", ...}` and its reply `{"id", "reply": {"ok": value} | {"raised": class,
//! "message", "word"}}`. While a call runs, car-adv asks the test back (`wire::ask`): the clock, the policy, the view
//! and the measurements the test handed in, a capability's `make` and every hook of the code it made, the objects
//! those hooks answered with, the view core handed a tick, and the edges of `Arming` into modules not ported yet.
//!
//! Calls: `open` (`kind`: `runtime` or `state`), `close`, `runtime` (a `Runtime` method by its Python name), `state`
//! (an `AdvancedState` method, car-adv `state::calls`), `scoped` (a code's own `Scoped`, through its binding),
//! `arming` (an `Arming` method), `object` (a Rust object handed to the test: the errands of a tick), `told` (a
//! code's `acted_when_told`), `op` (advprobe's pure ops: the registry, statements, vocabulary, policy). Every home is
//! the test's scratch folder; nothing else is read or written, and no window, process or network is touched.

#[path = "../advprobe/defs.rs"]
#[allow(dead_code)]
mod defs;
#[path = "../advprobe/ops_arming.rs"]
#[allow(dead_code)]
mod ops_arming;
#[path = "../advprobe/ops_pure.rs"]
#[allow(dead_code)]
mod ops_pure;
#[path = "../advprobe/ops_registry.rs"]
#[allow(dead_code)]
mod ops_registry;
#[path = "../advprobe/ops_statement.rs"]
#[allow(dead_code)]
mod ops_statement;
#[path = "../advprobe/ops_words.rs"]
#[allow(dead_code)]
mod ops_words;
mod proxied;
#[path = "../advprobe/util.rs"]
#[allow(dead_code)]
mod util;
mod wire;

use std::cell::{Cell, RefCell};
use std::collections::{BTreeSet, HashMap};
use std::path::Path;
use std::rc::Rc;
use std::sync::Arc;

use car_adv::arming::{ArmRequest, KeepRequest};
use car_adv::capabilities::{Code, Said};
use car_adv::registry::{CapabilityDef, Registry};
use car_adv::runtime::{Options, Shared};
use car_adv::state::AdvancedState;
use car_adv::state::calls::{self, Call};
use car_adv::statement::Catalogs;
use car_adv::vocabulary::OffReason;
use car_machine::json::{Map, Str, Value};
use car_policy::plug::{Channel, Errand, Point, Route, StartRoute};

use proxied::{AskEdges, ProxyCode, ProxyView, VIEWS, int, object_of};
use wire::{field, text, word};

// ------------------------------------------------------------------ sessions

enum Kind {
    Runtime(Arc<Shared>),
    State(Box<AdvancedState>),
}

enum Held {
    Errand(Box<dyn Errand>),
    Channel(Box<dyn Channel>),
    Route(Box<dyn Route>),
    Start(Box<dyn StartRoute>),
}

struct Session {
    id: i64,
    kind: Kind,
    objects: RefCell<HashMap<i64, Held>>,
    next: Cell<i64>,
}

impl Session {
    fn keep(&self, held: Held, kind: &str) -> Value {
        let number = self.next.get() + 1;
        self.next.set(number);
        self.objects.borrow_mut().insert(number, held);
        object([("rust", int(number)), ("kind", text(kind))])
    }

    fn state(&self) -> Result<&AdvancedState, Fault> {
        match &self.kind {
            Kind::State(state) => Ok(state),
            Kind::Runtime(_) => Err(Fault::new(
                "TypeError",
                "a runtime's state is reached by `runtime`",
            )),
        }
    }
}

thread_local! {
    static SESSIONS: RefCell<HashMap<i64, Rc<Session>>> = RefCell::new(HashMap::new());
}

fn session(line: &Value) -> Result<Rc<Session>, Fault> {
    let id = integer(field(line, "session"));
    SESSIONS
        .with(|sessions| sessions.borrow().get(&id).cloned())
        .ok_or_else(|| Fault::new("RuntimeError", "no such session"))
}

// ------------------------------------------------------------------ values

fn object<const N: usize>(pairs: [(&str, Value); N]) -> Value {
    let mut map = Map::new();
    for (name, value) in pairs {
        map.insert(Str::new(name), value);
    }
    Value::Object(map)
}

fn integer(value: &Value) -> i64 {
    match value {
        Value::Int(number) => number.as_i64().unwrap_or(0),
        Value::Float(number) => *number as i64,
        _ => 0,
    }
}

fn float(value: &Value) -> f64 {
    match value {
        Value::Float(number) => *number,
        Value::Int(number) => number
            .as_i64()
            .map_or(f64::INFINITY, |number| number as f64),
        _ => 0.0,
    }
}

fn list(value: &Value) -> Vec<Value> {
    match value {
        Value::Array(items) => items.clone(),
        _ => Vec::new(),
    }
}

fn words(value: &Value) -> Vec<String> {
    list(value)
        .iter()
        .filter_map(|each| word(each).map(str::to_owned))
        .collect()
}

/// A raise the test re-raises as the reference's own class.
#[derive(Debug)]
pub struct Fault {
    class: String,
    message: String,
    word: Option<String>,
}

impl Fault {
    fn new(class: &str, message: &str) -> Fault {
        Fault {
            class: class.to_owned(),
            message: message.to_owned(),
            word: None,
        }
    }

    fn class(class: &str) -> Fault {
        Fault::new(class, "")
    }
}

impl From<car_adv::state::Error> for Fault {
    fn from(error: car_adv::state::Error) -> Fault {
        Fault {
            class: error.class().to_owned(),
            message: error.message(),
            word: error.word().map(str::to_owned),
        }
    }
}

impl From<car_adv::runtime::Raise> for Fault {
    fn from(raise: car_adv::runtime::Raise) -> Fault {
        Fault::class(raise.0)
    }
}

impl From<util::Failure> for Fault {
    fn from(failure: util::Failure) -> Fault {
        Fault::class(&failure.class)
    }
}

// ------------------------------------------------------------------ the loop

fn main() {
    while let Some(line) = wire::read() {
        let reply = handle(&line);
        wire::write(&reply);
    }
}

/// One request, answered: its reply line. A panic is caught here (D15) and said as `RustPanic`.
pub fn handle(line: &Value) -> Value {
    let id = field(line, "id").clone();
    let reply = match car_machine::caught::catch(|| dispatch(line)) {
        Ok(Ok(value)) => object([("ok", value)]),
        Ok(Err(fault)) => object([
            ("raised", text(&fault.class)),
            ("message", text(&fault.message)),
            ("word", fault.word.as_deref().map_or(Value::Null, text)),
        ]),
        Err(payload) => {
            let message = payload
                .downcast_ref::<String>()
                .cloned()
                .or_else(|| {
                    payload
                        .downcast_ref::<&str>()
                        .map(|each| (*each).to_owned())
                })
                .unwrap_or_default();
            object([
                ("raised", text("RustPanic")),
                ("message", text(&message)),
                ("word", Value::Null),
            ])
        }
    };
    object([("id", id), ("reply", reply)])
}

fn dispatch(line: &Value) -> Result<Value, Fault> {
    let call = word(field(line, "call")).unwrap_or_default();
    let args = list(field(line, "args"));
    let kwargs = match field(line, "kwargs") {
        Value::Object(map) => map.clone(),
        _ => Map::new(),
    };
    let method = word(field(line, "method")).unwrap_or_default().to_owned();
    match call {
        "open" => open(line),
        "close" => {
            for id in list(field(line, "sessions")) {
                let id = integer(&id);
                let gone = SESSIONS.with(|sessions| sessions.borrow_mut().remove(&id));
                proxied::BINDINGS
                    .with(|bindings| bindings.borrow_mut().retain(|key, _| key.0 != id));
                drop(gone);
            }
            Ok(Value::Null)
        }
        "runtime" => {
            let session = session(line)?;
            let Kind::Runtime(shared) = &session.kind else {
                return Err(Fault::class("TypeError"));
            };
            let shared = shared.clone();
            runtime_call(&session, &shared, &method, &args, &kwargs, line)
        }
        "state" => {
            let session = session(line)?;
            let c = Call {
                args: &args,
                kwargs: &kwargs,
            };
            match &session.kind {
                Kind::State(state) => Ok(calls::call(state, &method, c)?),
                Kind::Runtime(shared) => {
                    let shared = shared.clone();
                    Ok(shared.enter(|runtime| calls::call(&runtime.state, &method, c))?)
                }
            }
        }
        "scoped" => {
            let session = session(line)?;
            let capability = word(field(line, "capability"))
                .unwrap_or_default()
                .to_owned();
            let c = Call {
                args: &args,
                kwargs: &kwargs,
            };
            // The binding is taken out while the call runs (a code's `Scoped` may call back in), then put back.
            let binding = proxied::BINDINGS
                .with(|bindings| {
                    bindings
                        .borrow_mut()
                        .remove(&(session.id, capability.clone()))
                })
                .ok_or_else(|| Fault::class("RuntimeError"))?;
            let found = binding.with(|scoped| calls::scoped_call(scoped, &method, c));
            proxied::BINDINGS.with(|bindings| {
                bindings
                    .borrow_mut()
                    .insert((session.id, capability), binding)
            });
            match found {
                Some(found) => Ok(found?),
                None => Ok(Value::Null),
            }
        }
        "arming" => {
            let session = session(line)?;
            let Kind::Runtime(shared) = &session.kind else {
                return Err(Fault::class("TypeError"));
            };
            let shared = shared.clone();
            shared.enter(|runtime| arming_call(runtime, &method, &args, &kwargs))
        }
        "object" => {
            let session = session(line)?;
            object_call(&session, integer(field(line, "object")), &method, line)
        }
        "told" => {
            let number = integer(field(line, "told"));
            let told = proxied::TOLD.with(|held| held.borrow_mut().1.remove(&number));
            if let Some(told) = told {
                told();
            }
            Ok(Value::Null)
        }
        "op" => {
            let op = word(field(line, "op")).unwrap_or_default().to_owned();
            ops(&op, &args)
        }
        _ => Err(Fault::new("AttributeError", call)),
    }
}

fn ops(op: &str, args: &[Value]) -> Result<Value, Fault> {
    let family = op.split('.').next().unwrap_or("");
    Ok(match family {
        "vocab" | "standards" | "measured" | "policy" => ops_words::run(op, args)?,
        "registry" => ops_registry::run(op, args)?,
        "statement" => ops_statement::run(op, args)?,
        "arming" if op.starts_with("arming.pure.") => ops_pure::run(op, args)?,
        "arming" => ops_arming::run(op, args)?,
        _ => return Err(Fault::class("UnknownOp")),
    })
}

// ------------------------------------------------------------------ open

#[derive(Debug)]
struct Links;

impl car_config::Links for Links {
    fn is_symlink(&self, path: &Path) -> bool {
        car_platform::links::is_symlink(path)
    }
}

fn paths_of(line: &Value) -> Result<car_config::Paths, Fault> {
    let home = word(field(line, "home")).unwrap_or_default().to_owned();
    car_config::Paths::new(
        Some(&home),
        &home,
        &|_| None,
        car_config::Os::here(false, Arc::new(Links)),
    )
    .map_err(Fault::class)
}

fn registry_of(line: &Value) -> Result<(Registry, BTreeSet<String>), Fault> {
    let mut definitions: Vec<CapabilityDef> = Vec::new();
    let mut shipped = BTreeSet::new();
    for item in list(field(line, "definitions")) {
        let made =
            defs::from_json(&item).map_err(|failure| Fault::new("ValueError", &failure.class))?;
        if field(&item, "make") == &text("shipped") {
            shipped.insert(made.id.clone());
        }
        definitions.push(made);
    }
    let registry = Registry::new(definitions)
        .map_err(|error| Fault::new("RegistryError", &format!("{error:?}")))?;
    Ok((registry, shipped))
}

fn ask_value(session: i64, name: &str) -> Result<Value, car_adv::capabilities::Raised> {
    wire::ask(
        "source",
        vec![("session", int(session)), ("name", text(name))],
    )
    .map(|found| proxied::plain_of(&found))
}

fn clock_of(session: i64) -> impl Fn() -> f64 + Send + Sync + Clone + 'static {
    move || ask_value(session, "clock").map_or(0.0, |now| float(&now))
}

fn policy_of(found: &Value) -> car_adv::policy::Policy {
    car_adv::policy::Policy {
        forbid: matches!(field(found, "forbid"), Value::Bool(true)),
        force_shadow: matches!(field(found, "force_shadow"), Value::Bool(true)),
        allowed: match field(found, "allowed") {
            Value::Null => None,
            other => Some(words(other).into_iter().collect()),
        },
    }
}

fn open(line: &Value) -> Result<Value, Fault> {
    let id = integer(field(line, "session"));
    let paths = paths_of(line)?;
    let (registry, shipped) = registry_of(line)?;
    let registry = Arc::new(registry);
    let kind = word(field(line, "kind")).unwrap_or_default();
    let made = match kind {
        "state" => {
            let clock = clock_of(id);
            Kind::State(Box::new(AdvancedState::new(
                paths,
                registry,
                Box::new(clock),
                Arc::new(car_adv::credentials::SystemTokens),
            )))
        }
        "runtime" => {
            let has = |name: &str| matches!(field(line, name), Value::Bool(true));
            let source = move |name: &'static str| -> car_adv::runtime::ViewSource {
                Arc::new(move || ask_value(id, name).map_err(|_| car_adv::seam::Unavailable))
            };
            let catalogs = word(field(line, "catalogs"))
                .map(str::to_owned)
                .unwrap_or_default();
            let options = Options {
                registry,
                clock: Arc::new(clock_of(id)),
                policy: Arc::new(move || {
                    ask_value(id, "policy")
                        .map(|found| policy_of(&found))
                        .map_err(|_| car_adv::seam::Unavailable)
                }),
                view: has("view").then(|| source("view")),
                measured: has("measured").then(|| -> car_adv::runtime::MeasuredSource {
                    Arc::new(move || {
                        ask_value(id, "measured")
                            .map(|found| proxied::table_of(&found))
                            .map_err(|_| car_adv::seam::Unavailable)
                    })
                }),
                live: has("live").then(|| source("live")),
                catalogs: Catalogs::new(
                    catalogs,
                    Box::new(move || {
                        ask_value(id, "language")
                            .ok()
                            .and_then(|found| word(&found).map(str::to_owned))
                            .unwrap_or_else(|| "en".to_owned())
                    }),
                ),
                edges: Box::new(AskEdges { session: id }),
                maker: Arc::new(
                    move |definition: &CapabilityDef, paths: &car_config::Paths| {
                        if shipped.contains(&definition.id) {
                            return car_adv::capabilities::make(definition, paths);
                        }
                        let answer = wire::ask(
                            "make",
                            vec![("session", int(id)), ("capability", text(&definition.id))],
                        )
                        .ok()?;
                        if matches!(answer, Value::Null) {
                            return None;
                        }
                        let code: Box<dyn Code> = Box::new(ProxyCode {
                            session: id,
                            capability: definition.id.clone(),
                            own: words(field(&answer, "own")),
                        });
                        Some(code)
                    },
                ),
                tokens: Arc::new(car_adv::credentials::SystemTokens),
                log: Some(Arc::new(move |said: &str| {
                    let _ = wire::ask("log", vec![("session", int(id)), ("line", text(said))]);
                })),
                auto_check: Some(Arc::new(move || {
                    let _ = wire::ask(
                        "edge",
                        vec![
                            ("session", int(id)),
                            ("name", text("auto_check")),
                            ("args", Value::Array(Vec::new())),
                        ],
                    );
                })),
            };
            Kind::Runtime(Shared::new(paths, options))
        }
        _ => return Err(Fault::new("ValueError", "kind")),
    };
    let session = Rc::new(Session {
        id,
        kind: made,
        objects: RefCell::new(HashMap::new()),
        next: Cell::new(0),
    });
    SESSIONS.with(|sessions| sessions.borrow_mut().insert(id, session));
    Ok(Value::Null)
}

// ------------------------------------------------------------------ the runtime

fn said_reply(session: &Session, said: Said) -> Value {
    match said {
        Said::Defer => object([("defer", Value::Bool(true))]),
        Said::Backend => object([("backend", Value::Bool(true))]),
        Said::Word(word) => object([("word", text(word.as_str()))]),
        Said::Value(value) => object([("value", value)]),
        Said::Tuple(items) => object([("tuple", Value::Array(items))]),
        Said::Set(items) => object([("set", Value::Array(items))]),
        Said::Channel(boxed) => match object_of(&*boxed) {
            Some(id) => object([("object", int(id))]),
            None => session.keep(Held::Channel(boxed), "channel"),
        },
        Said::Route(boxed) => match object_of(&*boxed) {
            Some(id) => object([("object", int(id))]),
            None => session.keep(Held::Route(boxed), "route"),
        },
        Said::Errand(boxed) => match object_of(&*boxed) {
            Some(id) => object([("object", int(id))]),
            None => session.keep(Held::Errand(boxed), "errand"),
        },
        Said::StartRoute(boxed) => match object_of(&*boxed) {
            Some(id) => object([("object", int(id))]),
            None => session.keep(Held::Start(boxed), "start"),
        },
    }
}

fn point_of(value: &Value) -> Result<Point, Fault> {
    word(value)
        .and_then(Point::parse)
        .ok_or_else(|| Fault::new("ValueError", "not a point"))
}

/// The view the test handed this call, by its id, while the call runs.
fn with_view<R>(view: Value, body: impl FnOnce() -> R) -> R {
    VIEWS.with(|views| views.borrow_mut().push(view));
    struct Pop;
    impl Drop for Pop {
        fn drop(&mut self) {
            let _ = VIEWS.try_with(|views| views.borrow_mut().pop());
        }
    }
    let _pop = Pop;
    body()
}

fn states_pairs(states: &car_adv::arming::States) -> Value {
    Value::Array(
        states
            .0
            .iter()
            .map(|(id, state)| Value::Array(vec![text(id), text(state.as_str())]))
            .collect(),
    )
}

fn maybe_words(found: Option<Vec<String>>) -> Value {
    match found {
        None => object([("defer", Value::Bool(true))]),
        Some(found) => object([(
            "value",
            Value::Array(found.iter().map(|each| text(each)).collect()),
        )]),
    }
}

fn runtime_call(
    session: &Session,
    shared: &Arc<Shared>,
    method: &str,
    args: &[Value],
    kwargs: &Map,
    line: &Value,
) -> Result<Value, Fault> {
    let c = Call { args, kwargs };
    let view = || ProxyView {
        session: session.id,
        id: field(line, "view").clone(),
    };
    let errands =
        |found: Result<Option<car_adv::runtime::tick::Errands>, car_adv::runtime::Raise>| {
            Ok::<Value, Fault>(match found? {
                Some(errands) => session.keep(Held::Errand(Box::new(errands)), "errands"),
                None => object([("defer", Value::Bool(true))]),
            })
        };
    let viewed = field(line, "view").clone();
    match method {
        "states" => {
            let fresh = car_machine::pyval::truthy(&c.or(None, "fresh", Value::Bool(false)));
            let live = words(&c.opt(None, "live"));
            let live: Vec<&str> = live.iter().map(String::as_str).collect();
            Ok(shared.enter(|runtime| states_pairs(&runtime.states(fresh, &live))))
        }
        "wants" => {
            let point = point_of(&c.need(Some(0), "point")?)?;
            Ok(Value::Bool(shared.enter(|runtime| runtime.wants(point))))
        }
        "ask" => {
            let point = point_of(&c.need(Some(0), "point")?)?;
            let rest: Vec<&Value> = args.iter().skip(1).collect();
            let said = shared.enter(|runtime| runtime.ask(point, &rest))?;
            Ok(said_reply(session, said))
        }
        "start_route" => {
            let said = shared.enter(|runtime| runtime.start_route(&c.opt(Some(0), "request")))?;
            Ok(said_reply(session, said))
        }
        "start_held" => Ok(shared.enter(|runtime| runtime.start_held())),
        "supervise" => {
            let said = shared.enter(|runtime| runtime.supervise(&c.opt(Some(0), "facts")))?;
            Ok(said_reply(session, said))
        }
        "supervise_held" => Ok(shared.enter(|runtime| runtime.supervise_held())),
        "tick" => with_view(viewed, || {
            errands(shared.enter(|runtime| runtime.tick(&view())))
        }),
        "resident" => with_view(viewed, || {
            errands(shared.enter(|runtime| runtime.resident(&view())))
        }),
        "records" => with_view(viewed, || {
            let found = shared.enter(|runtime| runtime.records(&view()))?;
            Ok(if found.is_empty() {
                object([("defer", Value::Bool(true))])
            } else {
                object([("value", Value::Array(found))])
            })
        }),
        "partition" => {
            let found = shared.enter(|runtime| runtime.partition(&c.opt(Some(0), "records")))?;
            Ok(match found {
                Some(found) => object([("value", found)]),
                None => object([("defer", Value::Bool(true))]),
            })
        }
        "moved" => {
            let state = c.opt(Some(1), "state");
            shared.enter(|runtime| {
                runtime.moved(&c.opt(Some(0), "record"), word(&state).unwrap_or_default())
            })?;
            Ok(object([("defer", Value::Bool(true))]))
        }
        "sessions" => Ok(maybe_words(shared.enter(|runtime| runtime.sessions())?)),
        "eligibility" => Ok(maybe_words(shared.enter(|runtime| runtime.eligibility())?)),
        "conversation_off" => {
            shared.enter(|runtime| runtime.conversation_off(&c.opt(Some(0), "thread_id")))?;
            Ok(Value::Null)
        }
        "make" => {
            let capability = c.need(Some(0), "capability")?;
            shared
                .enter(|runtime| runtime.make(word(&capability).unwrap_or_default()))
                .map_err(|raised| Fault::class(&raised.class))?;
            Ok(Value::Null)
        }
        "action" => {
            let capability = c.need(Some(0), "capability")?;
            shared
                .enter(|runtime| {
                    runtime
                        .action(word(&capability).unwrap_or_default())
                        .map(|_| ())
                })
                .map_err(|why| Fault::new("ValueError", why))?;
            Ok(Value::Null)
        }
        _ => Err(Fault::new("AttributeError", method)),
    }
}

fn object_call(session: &Session, number: i64, method: &str, line: &Value) -> Result<Value, Fault> {
    let objects = session.objects.borrow();
    let held = objects
        .get(&number)
        .ok_or_else(|| Fault::class("RuntimeError"))?;
    // The object stays in the table while it runs: take a raw pointer, so a nested call can reach the table.
    let held: *const Held = held;
    drop(objects);
    // SAFETY: an object is removed only by `close` of its session, which the test never sends while a call of that
    // session is waiting on it; the table's other entries may be added meanwhile (a HashMap keeps each boxed value's
    // contents in place: the box's heap address does not move when the map grows).
    let held = unsafe { &*held };
    let args = list(field(line, "args"));
    let arg = |index: usize| args.get(index).cloned().unwrap_or(Value::Null);
    let view = ProxyView {
        session: session.id,
        id: field(line, "view").clone(),
    };
    match (held, method) {
        (Held::Errand(errand), "run") => with_view(field(line, "view").clone(), || {
            let mut guards = |body: &mut dyn FnMut(bool) -> Value| Ok(body(true));
            errand
                .run(&view, &mut guards)
                .map_err(|_| Fault::class("Exception"))
        }),
        (Held::Channel(channel), "send") => {
            let prompt = match arg(1) {
                Value::Str(prompt) => prompt,
                _ => Str::new(""),
            };
            let client = arg(2);
            Ok(channel.send(word(&arg(0)).unwrap_or_default(), &prompt, word(&client)))
        }
        (Held::Channel(channel), "pools") => match channel.pools_said() {
            Some(Ok(value)) => Ok(value),
            Some(Err(_)) => Err(Fault::class("Exception")),
            None => Err(Fault::class("AttributeError")),
        },
        (Held::Route(route), "resume") => {
            let words_ = match arg(1) {
                Value::Str(words_) => Some(words_),
                _ => None,
            };
            let client = arg(2);
            Ok(route.resume(
                word(&arg(0)).unwrap_or_default(),
                None,
                words_.as_ref(),
                word(&client),
            ))
        }
        (Held::Start(start), "start") => Ok(start.start(&words(&arg(0)))),
        _ => Err(Fault::new("AttributeError", method)),
    }
}

// ------------------------------------------------------------------ arming

fn definition_of(registry: &Registry, value: &Value) -> Result<CapabilityDef, Fault> {
    if let Some(id) = word(value) {
        return registry
            .get(id)
            .cloned()
            .ok_or_else(|| Fault::class("AttributeError"));
    }
    defs::from_json(value).map_err(|_| Fault::class("AttributeError"))
}

fn arming_call(
    runtime: &car_adv::runtime::Runtime,
    method: &str,
    args: &[Value],
    kwargs: &Map,
) -> Result<Value, Fault> {
    let c = Call { args, kwargs };
    let engine = runtime.arming();
    let undecodable = |_| Fault::class(car_adv::statement::Undecodable::CLASS);
    let maybe = |value: Value| match value {
        Value::Null => None,
        other => Some(other),
    };
    Ok(match method {
        "arm" => engine
            .arm(&ArmRequest {
                capability: c.need(Some(0), "capability")?,
                state: c.need(None, "state")?,
                revision: c.need(None, "revision")?,
                generation: c.need(None, "generation")?,
                acknowledged_version: c.opt(None, "acknowledged_version"),
                warnings: c.opt(None, "warnings"),
                also: c.opt(None, "also"),
                keep_on: c.or(None, "keep_on", Value::Bool(false)),
                actor: c.need(None, "actor")?,
            })
            .map_err(undecodable)?,
        "disarm" => engine.disarm(&c.need(Some(0), "capability")?, &c.need(None, "actor")?),
        "all_off" => engine.all_off(&c.need(None, "actor")?),
        "edition_entered" => int(engine.edition_entered()?),
        "set_keep_on" => engine.set_keep_on(&KeepRequest {
            capability: c.need(Some(0), "capability")?,
            keep_on: c.need(Some(1), "keep_on")?,
            send_again: c.or(None, "send_again", Value::Bool(false)),
            generation: c.need(None, "generation")?,
            confirmed: c.opt(None, "confirmed"),
            actor: c.need(None, "actor")?,
        }),
        "set_global_hourly" => engine.set_global_hourly(
            &c.need(Some(0), "value")?,
            &c.need(None, "generation")?,
            &c.need(None, "actor")?,
        ),
        "set_option" => engine.set_option(
            &c.need(Some(0), "capability")?,
            &c.need(Some(1), "key")?,
            &c.need(Some(2), "value")?,
            &c.need(None, "generation")?,
            &c.need(None, "actor")?,
        ),
        "wordings_view" => engine.wordings_view(&c.need(Some(0), "capability")?),
        "set_wording" => engine.set_wording(
            &c.need(Some(0), "capability")?,
            &c.need(Some(1), "key")?,
            &c.need(Some(2), "words")?,
            &c.need(None, "generation")?,
            &c.need(None, "actor")?,
        ),
        "add_rule" => engine.add_rule(
            &c.need(Some(0), "tag")?,
            &c.need(Some(1), "status_from")?,
            &c.need(Some(2), "status_to")?,
            &c.need(Some(3), "category")?,
            &c.need(None, "generation")?,
            &c.need(None, "actor")?,
        ),
        "remove_rule" => engine.remove_rule(
            &c.need(Some(0), "rule")?,
            &c.need(None, "generation")?,
            &c.need(None, "actor")?,
        ),
        "rules_view" => engine.rules_view(),
        "samples_view" => engine.samples_view(),
        "listing" => engine.listing(),
        "statement" => {
            let definition = definition_of(&runtime.registry, &c.need(Some(0), "definition")?)?;
            let locale = c.opt(Some(1), "locale");
            engine
                .statement(&definition, word(&locale))
                .map_err(undecodable)?
        }
        "check" => {
            let definition = definition_of(&runtime.registry, &c.need(Some(0), "definition")?)?;
            let view = maybe(c.opt(Some(1), "view"));
            let table = maybe(c.opt(None, "table")).map(|table| proxied::table_of(&table));
            engine.check(&definition, view.as_ref(), table.as_ref(), None)
        }
        "warnings" => {
            let definition = definition_of(&runtime.registry, &c.need(Some(0), "definition")?)?;
            let view = maybe(c.opt(Some(1), "view"));
            Value::Array(
                engine
                    .warnings(&definition, view.as_ref())
                    .iter()
                    .map(|warning| text(warning.as_str()))
                    .collect(),
            )
        }
        "verdict" => {
            let measurement = c.need(Some(0), "measurement")?;
            match engine.verdict(word(&measurement).unwrap_or_default()) {
                Ok(found) => found.map_or(Value::Null, text),
                Err(_) => return Err(Fault::class("ValueError")),
            }
        }
        "current" => {
            let view = maybe(c.opt(None, "view"));
            let policy = maybe(c.opt(None, "policy")).map(|found| policy_of(&found));
            states_pairs(&engine.current(view.as_ref(), policy.as_ref()))
        }
        "read" => {
            let view = maybe(c.opt(None, "view"));
            let policy = maybe(c.opt(None, "policy")).map(|found| policy_of(&found));
            let live = words(&c.opt(None, "live"));
            let live: Vec<&str> = live.iter().map(String::as_str).collect();
            let found = engine.read(view.as_ref(), policy.as_ref(), &live);
            Value::Array(vec![
                states_pairs(&found.states),
                Value::Array(
                    found
                        .since
                        .iter()
                        .map(|(id, since)| {
                            Value::Array(vec![text(id), since.map_or(Value::Null, Value::Float)])
                        })
                        .collect(),
                ),
                Value::Bool(found.failed),
            ])
        }
        "trip" => {
            let capability = c.need(Some(0), "capability")?;
            let reason = c.need(Some(1), "reason")?;
            let reason = word(&reason)
                .and_then(car_adv::vocabulary::parse::<OffReason>)
                .ok_or_else(|| Fault::class("ValueError"))?;
            match engine.trip(word(&capability).unwrap_or_default(), reason) {
                Ok(done) => Value::Bool(done),
                Err(_) => return Err(Fault::class("ValueError")),
            }
        }
        "kept" => {
            let capability = c.need(Some(0), "capability")?;
            Value::Bool(engine.kept(word(&capability).unwrap_or_default()))
        }
        "moved" => {
            let state = c.need(Some(1), "state")?;
            Value::Bool(engine.moved(
                &c.need(Some(0), "record")?,
                word(&state).unwrap_or_default(),
            ))
        }
        "view" => engine.view(),
        "live_view" => engine.live_view(),
        "measured" => {
            let view = maybe(c.opt(Some(0), "view"));
            Value::Array(
                engine
                    .measured(view.as_ref())
                    .iter()
                    .map(|(m, (v, e))| {
                        Value::Array(vec![text(m.as_str()), text(v.as_str()), text(e)])
                    })
                    .collect(),
            )
        }
        "checked" => {
            let view = maybe(c.opt(Some(0), "view"));
            Value::Array(
                engine
                    .checked(view.as_ref())
                    .iter()
                    .map(|(m, r)| Value::Array(vec![text(m.as_str()), text(r.as_str())]))
                    .collect(),
            )
        }
        "policy" => engine.policy().as_json(),
        "why" => Value::Array(
            engine
                .why()
                .iter()
                .map(|(id, word)| Value::Array(vec![text(id), text(word)]))
                .collect(),
        ),
        _ => return Err(Fault::new("AttributeError", method)),
    })
}

impl From<car_adv::seam::StateFault> for Fault {
    fn from(fault: car_adv::seam::StateFault) -> Fault {
        match fault {
            car_adv::seam::StateFault::State => Fault::class("StateError"),
            car_adv::seam::StateFault::Stale => Fault::class("StaleGeneration"),
            car_adv::seam::StateFault::Refused(why) => Fault {
                class: "Refused".to_owned(),
                message: String::new(),
                word: Some(why.as_str().to_owned()),
            },
        }
    }
}
