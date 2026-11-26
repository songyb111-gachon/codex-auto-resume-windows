//! `runtime.py` (seat S7.2a): the registry's capabilities, asked at the plug's points, each in the state a person put
//! it in.
//!
//! At every point the plug is asked at, each capability whose code answers there is taken in the registry's order, and
//! what it may do depends only on where it stands (`crate::arming`): off, it is not asked; watched, its answer is
//! journalled as what it would have done and never taken; on, its answer is taken - a restriction (HOLD) at once, any
//! other from the first that gives one, and where it leads to a send of the record it was given only while its ceilings
//! have a unit left (the unit is spent at the claim, `crate::ledger`). The module's docstring at the tag is the
//! specification; every function below names the part it ports.
//!
//! | here | `runtime.py` |
//! |---|---|
//! | this module | `Runtime.__init__`, `states`, `_rearmed_silent`, `_code_of`, `action`, `_tripped`, `_said_raised`, `wants`, `_once`, `_paired`, the module's helpers |
//! | [`ask`] | `ask` and what it calls (`_takes`, `_ceiling`, `_conflict`, `_send_again`, `_alone`, `_remember`, `_first`, ...) |
//! | [`claim`] | `claim` (P11) and `partition` (P12) |
//! | [`records`] | `records` (P2), `_holders`, `_watched_records`, `conversation_off`, `_own_record_answer`, `_pictured_answer` |
//! | [`tick`] | `tick` (P8), `resident` (P22), `_auto_check`, `_Errands` |
//! | [`moved`] | `moved` (P14) and its tripwires, `_record_moved` |
//! | [`start`] | `start_route` (P9), `supervise` (P13), `_held_start` |
//! | [`lists`] | `eligibility` (P19), `sessions` (P18) |
//! | [`measurement`] | `run_measurement`, `complete_measurement` (seat S7.4) |
//!
//! # How it is held
//!
//! Python runs a runtime under the GIL: every caller - the engine's thread, the icon's, a card's - runs one hook at a
//! time, and a hook may call back into the runtime (a code's `Scoped` reads what the runtime has on). Here the runtime is
//! [`Shared`]: its fields are cells, and every entry takes its [`Gil`], a lock its own thread may take again. A code is
//! called with no cell borrowed but its own, so a call back in finds the runtime as Python would.

pub mod ask;
pub mod claim;
pub mod lists;
pub mod measurement;
pub mod moved;
pub mod records;
pub mod start;
pub mod tick;

use std::cell::{Cell, RefCell};
use std::collections::{BTreeMap, BTreeSet, HashSet};
use std::rc::Rc;
use std::sync::{Arc, Condvar, Mutex, PoisonError, Weak};
use std::thread::ThreadId;

use car_config::Paths;
use car_machine::json::{Map, Value};
use car_policy::plug::Point;

use crate::arming::{Arming, CoreView, MeasuredFn, PolicyFn, Setup, States, ViewFn};
use crate::capabilities::{Binding, Code, Maker, Raised, Said};
use crate::registry::{CapabilityDef, Registry};
use crate::seam::{Edges, Unavailable};
use crate::state::scoped::Scoped;
use crate::state::seam::Tokens;
use crate::state::{AdvancedState, Error as StateError};
use crate::statement::Catalogs;
use crate::vocabulary::{ArmingState, CapabilityKind, JournalCode, OffReason};

/// `REFRESH_SECONDS`: how long what every capability stands at is taken as read, between ticks.
pub const REFRESH_SECONDS: f64 = 5.0;
/// `NOTED_LIMIT`: journal lines written once per capability, point, answer and record in a process; forgotten, all at
/// once, past this many.
pub const NOTED_LIMIT: usize = 4096;
/// `KNOWN_FAILURE`: the gate a record taken up at P17 is put to the plug again at.
pub const KNOWN_FAILURE: &str = "known_failure";
/// `SUBMISSION_UNKNOWN`.
pub const SUBMISSION_UNKNOWN: &str = "submission_unknown";
/// `WITHDRAWN_UNCONFIRMED`, `NOT_DELIVERED_ON_OPEN`.
pub const WITHDRAWN_UNCONFIRMED: &str = "withdrawn_unconfirmed";
pub const NOT_DELIVERED_ON_OPEN: &str = "not_delivered_on_open";
/// `KEEP_GOING`.
pub const KEEP_GOING: &str = "keep_going";
/// `HELD_WORDS`: the reasons a start route was not named that nothing else in the journal says.
pub const HELD_WORDS: &[&str] = &[
    "compat_unknown",
    "engine_unknown",
    "policy",
    "refused",
    "off",
];
/// `SPLIT`.
pub const SPLIT: &str = "split";
/// `SUBMITTING`.
pub const SUBMITTING: &str = "submitting";
/// `TENDED`: what is tended while off or watched - the run kinds' clean-up (`state.schema.HEADLESS_CAPABILITIES`) and
/// the automatic account switch's put-back.
pub fn tended(capability: &str) -> bool {
    crate::state::schema::HEADLESS_CAPABILITIES.contains(&capability)
        || capability == "account_auto_switch"
}

/// `SENDING`: the points whose answer, if not a restriction, leads to a send of the record it was given, and which
/// argument the record is.
pub fn sending(point: Point) -> Option<usize> {
    match point {
        Point::Gates => Some(1),
        Point::Text
        | Point::Sender
        | Point::Schedule
        | Point::Outcome
        | Point::Delivery
        | Point::Unloaded
        | Point::Admission => Some(0),
        _ => None,
    }
}

/// `VOUCHED_BY`: the points whose answer carries the send a VERIFIED_RESET at known_failure was answered for.
pub fn vouched_by(point: Point) -> bool {
    matches!(point, Point::Sender | Point::Unloaded)
}

/// `OWN_RECORD_POINTS`: the points core never asks a record of this edition's own at.
pub fn own_record_point(point: Point) -> bool {
    matches!(
        point,
        Point::Text | Point::Sender | Point::Delivery | Point::Unloaded
    )
}

/// A Python exception that escapes a runtime method (and so the plug's hook, which `Guarded` counts as failed).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Raise(pub &'static str);

/// What a runtime method returns where the reference could raise.
pub type Py<T> = Result<T, Raise>;

/// `except StateError:` - a refusal of the state is caught (None); any other exception goes on.
pub(crate) fn caught<T>(result: Result<T, StateError>) -> Py<Option<T>> {
    match result {
        Ok(found) => Ok(Some(found)),
        Err(StateError::Python(class, _)) => Err(Raise(class)),
        Err(_) => Ok(None),
    }
}

// ------------------------------------------------------------------ Python values

/// `isinstance(value, dict)`.
pub(crate) fn object(value: &Value) -> Option<&Map> {
    match value {
        Value::Object(map) => Some(map),
        _ => None,
    }
}

static NULL: Value = Value::Null;

/// `record.get(name)` of a dict (None for anything else, where the reference guards it).
pub(crate) fn field<'a>(value: &'a Value, name: &str) -> &'a Value {
    object(value).and_then(|map| map.get(name)).unwrap_or(&NULL)
}

/// The key a record is held under in the runtime's tables: `record.get("interruption_id")` (None for a record that is
/// not a dict, or has none).
pub(crate) fn key_of(record: &Value) -> String {
    key_value(field(record, "interruption_id"))
}

/// A Python dict key, written so that keys Python takes as one (`1`, `1.0`, `True`) are one.
pub(crate) fn key_value(value: &Value) -> String {
    let write = |value: &Value| {
        car_machine::json::to_string(value, &Default::default()).unwrap_or_default()
    };
    match value {
        Value::Null => "None".into(),
        Value::Str(text) => format!("s{}", String::from_utf8_lossy(text.as_bytes())),
        Value::Bool(flag) => format!("n{}", i64::from(*flag)),
        Value::Int(_) => format!("n{}", write(value)),
        Value::Float(number) if number.fract() == 0.0 && number.abs() < 9.0e15 => {
            format!("n{}", *number as i64)
        }
        other => format!("j{}", write(other)),
    }
}

/// `isinstance(value, (int, float)) and not isinstance(value, bool)`: the number, if it is one.
pub(crate) fn number(value: &Value) -> Option<f64> {
    match value {
        Value::Int(number) => Some(number.as_i64().map_or(f64::INFINITY, |n| n as f64)),
        Value::Float(number) => Some(*number),
        _ => None,
    }
}

/// `answer in words` (equality, so a text equal to a word counts).
pub(crate) fn said_in(said: &Said, words: &[&str]) -> bool {
    said.text().is_some_and(|text| words.contains(&text))
}

/// Every answer word (`domain.plug.ANSWERS`).
pub const ANSWER_WORDS: &[&str] = car_policy::plug::vocab_gen::domain_plug::ANSWERS;

/// `_word(answer, point)`: what the journal may say an answer was - its word if it is one of the answers, else the
/// point it was given at.
pub(crate) fn journal_word(said: &Said, point: Point) -> String {
    match said.text() {
        Some(word) if ANSWER_WORDS.contains(&word) => word.to_owned(),
        _ => point.as_str().to_owned(),
    }
}

// ------------------------------------------------------------------ the lock

/// The runtime's GIL: one thread at a time, and that thread again as often as it calls back in.
#[derive(Default)]
pub struct Gil {
    owner: Mutex<(Option<ThreadId>, usize)>,
    free: Condvar,
}

struct Leave<'a>(&'a Gil);

impl Drop for Leave<'_> {
    fn drop(&mut self) {
        let mut owner = self.0.owner.lock().unwrap_or_else(PoisonError::into_inner);
        owner.1 -= 1;
        if owner.1 == 0 {
            owner.0 = None;
            self.0.free.notify_one();
        }
    }
}

impl Gil {
    pub fn enter<R>(&self, body: impl FnOnce() -> R) -> R {
        let me = std::thread::current().id();
        {
            let mut owner = self.owner.lock().unwrap_or_else(PoisonError::into_inner);
            if owner.0 != Some(me) {
                while owner.0.is_some() {
                    owner = self
                        .free
                        .wait(owner)
                        .unwrap_or_else(PoisonError::into_inner);
                }
                owner.0 = Some(me);
            }
            owner.1 += 1;
        }
        let _leave = Leave(self);
        body()
    }
}

// ------------------------------------------------------------------ the runtime

/// A view or a measurement table as `Arming` is handed one (`view=`, `live=`, `measured=`).
pub type ViewSource = Arc<dyn Fn() -> Result<Value, Unavailable> + Send + Sync>;
pub type PolicySource = Arc<dyn Fn() -> Result<crate::policy::Policy, Unavailable> + Send + Sync>;
pub type MeasuredSource =
    Arc<dyn Fn() -> Result<crate::measured::Table, Unavailable> + Send + Sync>;
pub type ClockSource = Arc<dyn Fn() -> f64 + Send + Sync>;
pub type LogSink = Arc<dyn Fn(&str) + Send + Sync>;

/// Every keyword `Runtime.__init__` takes, and what `Arming` takes through `**arming`.
pub struct Options {
    pub registry: Arc<Registry>,
    pub clock: ClockSource,
    pub policy: PolicySource,
    pub view: Option<ViewSource>,
    pub measured: Option<MeasuredSource>,
    pub live: Option<ViewSource>,
    pub catalogs: Catalogs,
    pub edges: Box<dyn Edges + Send + Sync>,
    /// `definition.make(paths)`: the shipped table (`capabilities::make`) or a test's own.
    pub maker: Arc<Maker>,
    pub tokens: Arc<dyn Tokens>,
    /// The watcher's log (core's logbook at INFO), for `_said_raised`; None writes nothing, as a process with no log.
    pub log: Option<LogSink>,
    /// `autocheck.tend(paths, clock=...)`, the tick's; None asks nothing (a runtime of the tests', S7.2c's seam).
    pub auto_check: Option<Arc<dyn Fn() + Send + Sync>>,
}

type CodeCell = Rc<RefCell<Box<dyn Code>>>;

/// An entry of `_acted`: (point, capability, word) - an answer's word, or None where it was none (P12's).
pub(crate) type Acted = (Point, String, Option<String>);

/// `Runtime`: every field the reference keeps, held as cells under the [`Gil`].
pub struct Runtime {
    // Declared first, so it is dropped first: it borrows the boxes below.
    pub(crate) arming: Arming<'static>,
    pub state: Box<AdvancedState>,
    pub registry: Arc<Registry>,
    _catalogs: Box<Catalogs>,
    _edges: Box<dyn Edges + Send + Sync>,
    pub paths: Paths,
    pub(crate) clock: ClockSource,
    maker: Arc<Maker>,
    log: Option<LogSink>,
    pub(crate) auto_check: Option<Arc<dyn Fn() + Send + Sync>>,
    pub(crate) states: RefCell<States>,
    at: Cell<Option<f64>>,
    pub(crate) since: RefCell<Vec<(String, Option<f64>)>>,
    pub(crate) unreadable: Cell<bool>,
    pub(crate) down_at: RefCell<BTreeMap<String, f64>>,
    code: RefCell<BTreeMap<String, CodeCell>>,
    pub(crate) acted: RefCell<BTreeMap<String, BTreeSet<Acted>>>,
    pub(crate) pooled: RefCell<BTreeMap<String, Vec<String>>>,
    pub(crate) texted: RefCell<BTreeMap<String, Vec<String>>>,
    noted: RefCell<HashSet<String>>,
    pub(crate) skipped: RefCell<HashSet<(String, String)>>,
    pub(crate) records_turn: Cell<usize>,
    pub(crate) start_held: RefCell<Value>,
    pub(crate) supervise_held: RefCell<Value>,
    pub(crate) refused_tripped: Cell<Option<f64>>,
    pub(crate) me: RefCell<Weak<Shared>>,
}

/// A runtime as the plug holds it: the runtime and its lock.
pub struct Shared {
    gil: Gil,
    runtime: Runtime,
}

// SAFETY: every field of `Runtime` is reached only inside `Shared::enter`, which holds the GIL: one thread at a time, as
// Python runs its runtime. The closures handed in are `Send + Sync`; the codes and cells are touched only under the lock.
unsafe impl Send for Shared {}
// SAFETY: as above - a shared reference reaches the fields only under the GIL.
unsafe impl Sync for Shared {}

impl Shared {
    /// `Runtime(paths, **options)`.
    pub fn new(paths: Paths, options: Options) -> Arc<Shared> {
        let clock = options.clock.clone();
        let state_clock = clock.clone();
        let state = Box::new(AdvancedState::new(
            paths.clone(),
            options.registry.clone(),
            Box::new(move || state_clock()),
            options.tokens.clone(),
        ));
        let catalogs = Box::new(options.catalogs);
        let edges = options.edges;
        let registry = options.registry.clone();
        let policy = options.policy.clone();
        let arming_clock = clock.clone();
        let setup = Setup {
            view: options
                .view
                .map(|view| -> ViewFn { Box::new(move || view()) }),
            policy: {
                let made: PolicyFn = Box::new(move || policy());
                made
            },
            measured: options
                .measured
                .map(|measured| -> MeasuredFn { Box::new(move || measured()) }),
            clock: Box::new(move || arming_clock()),
            live: options
                .live
                .map(|live| -> ViewFn { Box::new(move || live()) }),
        };
        // SAFETY: the boxes and the Arc outlive `arming`, which is declared first in `Runtime` and so dropped first, and
        // nothing replaces or moves their contents while the runtime lives.
        let arming = unsafe {
            let state_ref: &'static AdvancedState = &*(state.as_ref() as *const AdvancedState);
            let edges_ref: &'static (dyn Edges + Send + Sync) =
                &*(edges.as_ref() as *const (dyn Edges + Send + Sync));
            let registry_ref: &'static Registry = &*(registry.as_ref() as *const Registry);
            let catalogs_ref: &'static Catalogs = &*(catalogs.as_ref() as *const Catalogs);
            Arming::new(state_ref, edges_ref, registry_ref, catalogs_ref, setup)
        };
        let shared = Arc::new(Shared {
            gil: Gil::default(),
            runtime: Runtime {
                arming,
                state,
                registry,
                _catalogs: catalogs,
                _edges: edges,
                paths,
                clock,
                maker: options.maker,
                log: options.log,
                auto_check: options.auto_check,
                states: RefCell::new(States::default()),
                at: Cell::new(None),
                since: RefCell::new(Vec::new()),
                unreadable: Cell::new(false),
                down_at: RefCell::new(BTreeMap::new()),
                code: RefCell::new(BTreeMap::new()),
                acted: RefCell::new(BTreeMap::new()),
                pooled: RefCell::new(BTreeMap::new()),
                texted: RefCell::new(BTreeMap::new()),
                noted: RefCell::new(HashSet::new()),
                skipped: RefCell::new(HashSet::new()),
                records_turn: Cell::new(0),
                start_held: RefCell::new(Value::Null),
                supervise_held: RefCell::new(Value::Null),
                refused_tripped: Cell::new(None),
                me: RefCell::new(Weak::new()),
            },
        });
        *shared.runtime.me.borrow_mut() = Arc::downgrade(&shared);
        shared
    }

    /// Run `body` with the runtime, under its GIL.
    pub fn enter<R>(&self, body: impl FnOnce(&Runtime) -> R) -> R {
        self.gil.enter(|| body(&self.runtime))
    }
}

/// `f(state.scoped(capability, on=..., verdict=self.arming.verdict, armed=...))` for a code's [`Binding`].
pub(crate) fn scoped_for<R>(
    shared: &Shared,
    capability: &str,
    f: impl FnOnce(&Scoped<'_>) -> R,
) -> R {
    shared.enter(|runtime| {
        let on = || runtime.states.borrow().state_of(capability) == ArmingState::Armed;
        let verdict = |measurement: &Value| -> Value {
            match measurement
                .as_text()
                .map(|text| runtime.arming.verdict(text))
            {
                Some(Ok(Some(word))) => Value::Str(word.into()),
                _ => Value::Null,
            }
        };
        let armed = |other: &Value| -> bool {
            other
                .as_text()
                .is_some_and(|other| runtime.states.borrow().state_of(other) == ArmingState::Armed)
        };
        let scoped = Scoped {
            state: &runtime.state,
            capability: Value::Str(capability.into()),
            on: Some(&on),
            verdict: Some(&verdict),
            armed: Some(&armed),
        };
        f(&scoped)
    })
}

/// A text of a Python-model value.
pub(crate) trait AsText {
    fn as_text(&self) -> Option<&str>;
}

impl AsText for Value {
    fn as_text(&self) -> Option<&str> {
        match self {
            Value::Str(text) => text.as_str(),
            _ => None,
        }
    }
}

/// The engine's view as `Arming.sweep` reads it: `view.get(key)`.
pub(crate) struct Swept<'a>(pub &'a dyn car_policy::plug::View);

impl CoreView for Swept<'_> {
    fn get(&self, key: &str) -> Result<Value, Unavailable> {
        self.0.get(key).map_err(|_| Unavailable)
    }
}

impl Runtime {
    pub fn now(&self) -> f64 {
        (self.clock)()
    }

    /// `self.arming`.
    pub fn arming(&self) -> &Arming<'static> {
        &self.arming
    }

    /// `self.ledger`.
    pub fn ledger(&self) -> crate::ledger::ClaimLedger<'_> {
        crate::ledger::ClaimLedger { state: &self.state }
    }

    /// `states(fresh=False, live=())`: what every capability stands at, read again past REFRESH_SECONDS.
    pub fn states(&self, fresh: bool, live: &[&str]) -> States {
        let now = self.now();
        let stale = match self.at.get() {
            None => true,
            Some(at) => !(0.0 <= now - at && now - at < REFRESH_SECONDS),
        };
        if fresh || stale {
            let read = self.arming.read(None, None, live);
            *self.states.borrow_mut() = read.states;
            *self.since.borrow_mut() = read.since;
            self.unreadable.set(read.failed);
            self.at.set(Some(now));
            if !read.failed {
                let since: Vec<String> = self
                    .since
                    .borrow()
                    .iter()
                    .map(|(id, _)| id.clone())
                    .collect();
                for capability in since {
                    if self.states.borrow().state_of(&capability) != ArmingState::Armed {
                        self.down_at.borrow_mut().insert(capability, now);
                    }
                }
                self.rearmed_silent();
            }
        }
        self.states.borrow().clone()
    }

    /// `self._states.get(capability, OFF)`, as the last read left it.
    pub(crate) fn standing(&self, capability: &str) -> ArmingState {
        self.states.borrow().state_of(capability)
    }

    /// `self._since.get(capability)`: Some(since) for one not stored off (since itself may be None).
    pub(crate) fn since_of(&self, capability: &str) -> Option<Option<f64>> {
        self.since
            .borrow()
            .iter()
            .find(|(id, _)| id == capability)
            .map(|(_, since)| *since)
    }

    /// `_rearmed_silent()`: silent_continuation turned on again since REFUSED_BY_CODEX turned it off is asked again.
    fn rearmed_silent(&self) {
        let Some(tripped) = self.refused_tripped.get() else {
            return;
        };
        let since = self.since_of(crate::seam_p7::SILENT).flatten();
        if self.standing(crate::seam_p7::SILENT) == ArmingState::Armed
            && since.is_some_and(|since| since >= tripped)
        {
            crate::codex::headless::EMPTY_REFUSED.store(false, std::sync::atomic::Ordering::SeqCst);
            self.refused_tripped.set(None);
        }
    }

    /// `_code_of(definition)`: a capability's code, made once, and bound to its own view of the state. A `make` that
    /// gives none is one that raised.
    pub(crate) fn code_of(&self, definition: &CapabilityDef) -> Result<CodeCell, Raised> {
        if let Some(code) = self.code.borrow().get(&definition.id) {
            return Ok(code.clone());
        }
        let Some(mut code) = (self.maker)(definition, &self.paths) else {
            return Err(Raised::new("TypeError"));
        };
        let binding = Binding {
            runtime: self.me.borrow().clone(),
            capability: definition.id.clone(),
        };
        if let Some(bound) = code.bind(binding) {
            bound?;
        }
        let code = Rc::new(RefCell::new(code));
        self.code
            .borrow_mut()
            .insert(definition.id.clone(), code.clone());
        Ok(code)
    }

    /// `_code_of(self.registry.get(capability))`, for a caller that only needs the code made (the advanced proxy's
    /// `_code_of`): an id the registry lacks is Python's AttributeError on None, a `make` that gives none a raise.
    pub fn make(&self, capability: &str) -> Result<(), Raised> {
        let definition = self
            .registry
            .get(capability)
            .ok_or_else(|| Raised::new("AttributeError"))?;
        self.code_of(definition).map(|_| ())
    }

    /// `action(definition)`: the code of an action, made once, for the surface a person starts what it does from.
    pub fn action(&self, capability: &str) -> Result<CodeCell, &'static str> {
        match self.registry.get(capability) {
            Some(definition) if definition.kind == CapabilityKind::Action => self
                .code_of(definition)
                .map_err(|_| "the action's code raised"),
            _ => Err("not an action of this registry"),
        }
    }

    /// `_said_raised(definition)`: one line in the watcher's log for a hook that raised - the capability, the
    /// exception's type (and the type it came from) and this edition's frames it passed. Never its message.
    fn said_raised(&self, definition: &CapabilityDef, raised: &Raised) {
        let Some(log) = &self.log else {
            return;
        };
        let cause = raised
            .cause
            .as_ref()
            .map(|cause| format!(" (from {cause})"))
            .unwrap_or_default();
        let at = raised
            .at
            .as_ref()
            .filter(|at| !at.is_empty())
            .map(|at| format!(" at {at}"))
            .unwrap_or_default();
        log(&format!(
            "advanced {}: a hook raised {}{}{}",
            definition.id, raised.class, cause, at
        ));
    }

    /// `_tripped(definition, record=None)`: a hook raised - off from here on, or, kept on (K8), passed over for
    /// `record` alone; a point with no record skips only the call it raised in.
    pub(crate) fn tripped(
        &self,
        definition: &CapabilityDef,
        record: Option<&Value>,
        raised: &Raised,
    ) {
        self.said_raised(definition, raised);
        let turned = self
            .arming
            .trip(&definition.id, OffReason::HookException)
            .unwrap_or(false);
        if turned || !self.arming.kept(&definition.id) {
            let mut states = self.states.borrow_mut();
            match states.0.iter_mut().find(|(id, _)| id == &definition.id) {
                Some(held) => held.1 = ArmingState::Off,
                None => states.0.push((definition.id.clone(), ArmingState::Off)),
            }
            return;
        }
        if let Some(key @ Value::Str(_)) = record.map(|record| field(record, "interruption_id")) {
            let mut skipped = self.skipped.borrow_mut();
            if skipped.len() >= NOTED_LIMIT {
                skipped.clear();
            }
            skipped.insert((definition.id.clone(), key_value(key)));
        }
    }

    /// Whether `(capability, record)` is passed over (K8).
    pub(crate) fn is_skipped(&self, capability: &str, key: &str) -> bool {
        self.skipped
            .borrow()
            .contains(&(capability.to_owned(), key.to_owned()))
    }

    /// `wants(point)`: whether a capability registered at `point` is on or watched now.
    pub fn wants(&self, point: Point) -> bool {
        let definitions = self.registry.at(point);
        if definitions.is_empty() {
            return false;
        }
        let states = self.states(false, &[]);
        definitions
            .iter()
            .any(|definition| states.state_of(&definition.id) != ArmingState::Off)
    }

    fn noted_once(&self, key: String) -> bool {
        let mut noted = self.noted.borrow_mut();
        if noted.contains(&key) {
            return false;
        }
        if noted.len() >= NOTED_LIMIT {
            noted.clear();
        }
        noted.insert(key);
        true
    }

    /// `_once(code, definition, point, answer, record)`: one journal line per capability, point, answer and record in a
    /// process. `word` is `_word(answer, point)`.
    pub(crate) fn once(
        &self,
        code: JournalCode,
        definition: &CapabilityDef,
        point: Point,
        word: &str,
        record: Option<&Value>,
    ) -> Py<()> {
        let key = record.map_or_else(|| "None".to_owned(), key_of);
        let noted = format!(
            "o{}\u{0}{}\u{0}{}\u{0}{}\u{0}{}",
            code.as_str(),
            definition.id,
            point.as_str(),
            word,
            key
        );
        if !self.noted_once(noted) {
            return Ok(());
        }
        caught(self.state.note(
            &Value::Str(code.as_str().into()),
            &Value::Str(definition.id.as_str().into()),
            &Value::Null,
            &Value::Null,
            &Value::Str(point.as_str().into()),
            &Value::Str(word.into()),
            &Value::Float(self.now()),
        ))?;
        Ok(())
    }

    /// `_paired(code, definition, point, other, record, reason=None)`: once per record, about the capability `other`.
    pub(crate) fn paired(
        &self,
        code: JournalCode,
        definition: &CapabilityDef,
        point: Point,
        other: &str,
        record: &Value,
        reason: Option<&str>,
    ) -> Py<()> {
        let noted = format!(
            "p{}\u{0}{}\u{0}{}\u{0}{}\u{0}{}",
            code.as_str(),
            definition.id,
            point.as_str(),
            other,
            key_of(record)
        );
        if !self.noted_once(noted) {
            return Ok(());
        }
        caught(self.state.note(
            &Value::Str(code.as_str().into()),
            &Value::Str(definition.id.as_str().into()),
            &reason.map_or(Value::Null, |reason| Value::Str(reason.into())),
            &Value::Null,
            &Value::Str(point.as_str().into()),
            &Value::Str(other.into()),
            &Value::Float(self.now()),
        ))?;
        Ok(())
    }

    /// The code of `definition` called with `call`, its cell borrowed for the call alone (a code made here if it is
    /// not yet; one that cannot be made, or is already being called, is one that raised).
    pub(crate) fn call<R>(
        &self,
        definition: &CapabilityDef,
        call: impl FnOnce(&mut dyn Code) -> Result<R, Raised>,
    ) -> Result<R, Raised> {
        let code = self.code_of(definition)?;
        let mut borrowed = code
            .try_borrow_mut()
            .map_err(|_| Raised::new("RecursionError"))?;
        call(borrowed.as_mut())
    }

    /// An optional hook of `definition`'s code (`_own(code, name)`): None where the code has none. Making the code
    /// raises as `_own(self._code_of(definition), ...)` does.
    pub(crate) fn call_own<R>(
        &self,
        definition: &CapabilityDef,
        call: impl FnOnce(&mut dyn Code) -> Option<Result<R, Raised>>,
    ) -> Result<Option<Result<R, Raised>>, Raised> {
        let code = self.code_of(definition)?;
        let mut borrowed = code
            .try_borrow_mut()
            .map_err(|_| Raised::new("RecursionError"))?;
        Ok(call(borrowed.as_mut()))
    }
}
