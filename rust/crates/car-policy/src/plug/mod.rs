//! The plug: the one way an edition's own code reaches core, and what core does with none (`domain/plug.py`).
//!
//! Core never names the advanced edition's code. It asks a [`Plug`] at a fixed list of points (P2-P22; there is no P1),
//! and in the standard edition the plug is [`NullPlug`], which answers every question the way core answers it alone.
//! Core holds a plug only as [`Guarded`], which asks every hook through one `consult` and checks every value a hook
//! hands back before core takes it:
//!
//! * Only core acts. A hook answers; at a decision point it answers [`Answer::Defer`] or a member of that point's closed
//!   set ([`alternatives`]), and core carries the member out itself.
//! * A hook that fails costs its own answer and nothing else: an `Err` or a panic (caught here, D15) puts NULL's
//!   answer in its place and counts in `failures`.
//! * A hook is handed borrows: what core reads again after asking is never the value a hook could change.
//!
//! # How the advanced edition plugs in (D2)
//!
//! This workspace never names the advanced edition's crate or folder (check_groundwork.py holds it to that); the
//! advanced workspace depends on car-policy by path, never the other way round (PLAN 1.1, 1.4). The advanced edition's
//! one library crate implements this trait on its own type (`impl car_policy::plug::Plug for AdvancedPlug`),
//! overriding only the hooks its capabilities use - every other hook keeps the trait's default, which is NULL's answer -
//! and hands [`edition::load`] an [`edition::Factory`] with the PLUG_API it was written for and the function that makes
//! its plug; a factory that fails, or makes no advanced plug, becomes a [`DamagedPlug`] ("Advanced - not loaded"). The
//! advanced binaries pass that factory; the standard binaries pass none (or call [`Guarded::null`]) and link no
//! advanced code at all, so their bytes are the same with the advanced folder deleted.
//!
//! What a hook is handed that core owns and car-policy cannot name - the engine's view of its store (P2, P8, P22),
//! the claim's connection (P11) - is a trait object of this module ([`View`], [`Ledger`]), which car-engine and
//! car-store implement; what a plug names that core carries out - a channel (P5), a route (P16), an errand (P8, P22),
//! a start route (P9) - is a trait object the plug implements ([`Channel`], [`Route`], [`Errand`], [`StartRoute`]).

pub mod edition;
pub mod hands;
#[rustfmt::skip]
pub mod vocab_gen;

use std::panic::{AssertUnwindSafe, catch_unwind};
use std::sync::atomic::{AtomicU64, Ordering};

use car_machine::json::{Str, Value};
use car_machine::vocab::Node;

pub use vocab_gen::domain_plughands::{RecordMove, RecordPurpose, SessionKind, Widening};
pub use vocab_gen::domain_plugwords::{
    Alternative, Edition, FailureForm, PlugFailure, Point, Surface,
};

/// The interface's version: the advanced crate writes the number it was written for, and core takes its plug only
/// when the two agree. 8 (v0.6.22): P22.
pub const PLUG_API: i64 = 8;
/// P21's words, and how many conversations its answer may name at most.
pub const POWER_TASKS: &[&str] = vocab_gen::domain_plug::POWER_TASKS;
pub const POWER_THREADS: usize = hands::POWER_THREADS;
/// The key a surface puts a plug's fields under. NULL never adds any.
pub const EXTRA: &str = vocab_gen::domain_plug::EXTRA;

/// An answer of a hook: DEFER - core decides, as if there were no plug - or the plug's own.
#[derive(Debug, Clone, PartialEq)]
pub enum Answer<T> {
    Defer,
    Is(T),
}

/// A hook that raised: it costs its own answer.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct HookFailed;

/// What a hook returns.
pub type Hook<T> = Result<Answer<T>, HookFailed>;

/// A read through a [`View`] or a [`Ledger`] that failed: the class of the exception the reference raises there.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ReadFailed(pub &'static str);

/// The engine's view of its store, as P2, P8 and P22 hand it (`engine/storeview.py`'s `StoreView`; car-engine
/// implements it): the moment it was shown and the reads of `VIEW_READS`, each the store's own, and nothing that writes.
/// NULL reads nothing through it; every read's default is the reference's AttributeError of a view that has none.
pub trait View {
    /// `view.now`.
    fn now(&self) -> f64 {
        0.0
    }
    /// `view.get(interruption_id)`: core's record, or None.
    fn get(&self, _interruption_id: &str) -> Result<Value, ReadFailed> {
        Err(ReadFailed("AttributeError"))
    }
    /// `view.records_in(states)`: this home's records in `states`.
    fn records_in(&self, _states: &[&str]) -> Result<Vec<Value>, ReadFailed> {
        Err(ReadFailed("AttributeError"))
    }
    /// `view.settings()`.
    fn settings(&self) -> Result<Value, ReadFailed> {
        Err(ReadFailed("AttributeError"))
    }
    /// `view.thread_enabled(thread_id)`.
    fn thread_enabled(&self, _thread_id: &str) -> Result<bool, ReadFailed> {
        Err(ReadFailed("AttributeError"))
    }
    /// `view.others_in_flight(thread_id, exclude)`.
    fn others_in_flight(&self, _thread_id: &str, _exclude: &str) -> Result<i64, ReadFailed> {
        Err(ReadFailed("AttributeError"))
    }
    /// `view.recent_claims(thread_id, since)`.
    fn recent_claims(&self, _thread_id: &str, _since: f64) -> Result<Vec<Value>, ReadFailed> {
        Err(ReadFailed("AttributeError"))
    }
    /// `view.recent_claim_count(thread_id, since)`.
    fn recent_claim_count(&self, _thread_id: &str, _since: f64) -> Result<i64, ReadFailed> {
        Err(ReadFailed("AttributeError"))
    }
    /// `view.claimed_on_thread(thread_id)`: this home's records that may have put a continuation there.
    fn claimed_on_thread(&self, _thread_id: &str) -> Result<Vec<Value>, ReadFailed> {
        Err(ReadFailed("AttributeError"))
    }
    /// `view.last_usage()`: (when, the windows) of the engine's own last usage reading, or None.
    fn last_usage(&self) -> Value {
        Value::Null
    }
}

/// The claim's own connection, as P11 hands it (`store/ledger.py`'s `_LedgerConnection`): `execute`, under the claim's
/// authorizer, savepoint and transaction, and nothing else (car-store implements it). Writes reach the plug's own
/// database only; core's schemas and the claim's transaction are refused by the authorizer, not by this trait.
pub trait Ledger {
    /// `connection.execute(statement, parameters)`, its rows read out whole.
    fn execute(
        &mut self,
        _statement: &str,
        _parameters: &[Value],
    ) -> Result<Vec<Vec<Value>>, ReadFailed> {
        Err(ReadFailed("ProgrammingError"))
    }
    /// The same connection as SQLite's own handle (`sqlite3*`), for a plug built over the same SQLite library as core:
    /// valid during this call only, and under the same authorizer. None where there is none.
    fn sqlite(&mut self) -> Option<*mut std::ffi::c_void> {
        None
    }
}

/// A channel a plug named at P5: core calls `send` once, after its claim and inside its launch guard.
pub trait Channel: Send {
    fn send(&self, thread_id: &str, prompt: &Str, client_id: Option<&str>) -> Value;
    /// Whether this send may wait for its receipt on a worker beside others (P12); held to `true` itself.
    fn pools(&self) -> Result<bool, HookFailed> {
        Ok(false)
    }
    /// What `pools()` itself answered, for the plug's own runtime (`runtime._alone` reads a warning word there): None
    /// where the channel has no `pools`. Core reads `pools` alone.
    fn pools_said(&self) -> Option<Result<Value, HookFailed>> {
        None
    }
}

/// A route a plug named at P16: core calls `resume` once, after its claim and its pre-send look.
pub trait Route: Send {
    fn resume(
        &self,
        thread_id: &str,
        still_unloaded: Option<&dyn Fn() -> bool>,
        words: Option<&Str>,
        client_id: Option<&str>,
    ) -> Value;
    /// Whether the route takes core's words (v0.6.16-beta.4).
    fn takes_words(&self) -> Result<bool, HookFailed> {
        Ok(false)
    }
}

/// The guards an errand may ask for (`with guard() as permitted:`, `store.errand_guard(held=engine.errand_held)`): each
/// call runs `body` once inside one guard, with `permitted` read under the store's write lock, and answers what `body`
/// answered - or the failure of a guard that could not be taken, which the errand lets go on as the reference's raise.
pub type Guards<'a> = dyn FnMut(&mut dyn FnMut(bool) -> Value) -> Result<Value, HookFailed> + 'a;

/// An errand a plug answered at P8 or P22: core runs it once, last in the tick, with the tick's view of its store (the
/// one the hook was handed, which a Python errand keeps) and a way to ask for guards. An `Err` is the reference's raise:
/// core logs `plug_errand_failed` and goes on.
pub trait Errand: Send {
    fn run(&self, view: &dyn View, guards: &mut Guards<'_>) -> Result<Value, HookFailed>;
}

/// A route that starts the watcher outside Codex's job (P9): core calls `start` with the command line it built.
pub trait StartRoute: Send {
    fn start(&self, command: &[String]) -> Value;
}

/// What P16 answers beside DEFER: a route, or one of the two queued answers core carries out as its ordinary send.
pub enum Unloaded {
    Route(Box<dyn Route>),
    Queued(Alternative),
}

/// Every hook core calls, each answering as core would with no plug at all.
///
/// [`NullPlug`] is this trait's defaults and nothing more. An edition's plug overrides only the hooks its
/// capabilities use. Each hook is given what core holds at its point, and NULL reads none of it.
pub trait Plug: Send + Sync {
    fn edition(&self) -> Edition {
        Edition::Standard
    }

    fn badge(&self) -> &'static str {
        "Standard"
    }

    /// Why an advanced installation's plug could not be made, for a [`DamagedPlug`] alone.
    fn damaged(&self) -> Option<PlugFailure> {
        None
    }

    /// P2: records of the advanced store due now, and those in flight (`hands::records_of` holds them).
    fn records(&self, _view: &dyn View) -> Hook<Vec<Value>> {
        Ok(Answer::Defer)
    }

    /// P3: a gate's answer for one record, once core's own evaluation of that gate passed.
    fn gate(&self, _name: &str, _record: &Value, _facts: &Value) -> Hook<Alternative> {
        Ok(Answer::Defer)
    }

    /// P4: what the continuation says; `text` is core's own.
    fn text(&self, _record: &Value, _text: &Str) -> Hook<Str> {
        Ok(Answer::Defer)
    }

    /// P5: what the one send is handed to - core's own backend (DEFER) unless a channel says otherwise.
    fn sender(&self, _record: &Value) -> Hook<Box<dyn Channel>> {
        Ok(Answer::Defer)
    }

    /// P6: what follows a turn that has ended.
    fn outcome(&self, _record: &Value, _outcome: &str) -> Hook<Alternative> {
        Ok(Answer::Defer)
    }

    /// P7: when a record is looked at next.
    fn schedule(&self, _record: &Value, _due: &Value) -> Hook<Alternative> {
        Ok(Answer::Defer)
    }

    /// P8: once a tick, after everything has been observed: an errand, or DEFER.
    fn tick(&self, _view: &dyn View) -> Hook<Box<dyn Errand>> {
        Ok(Answer::Defer)
    }

    /// P9: how the watcher is started for Codex.
    fn start_route(&self, _request: &Value) -> Hook<Box<dyn StartRoute>> {
        Ok(Answer::Defer)
    }

    /// P10: what one surface shows beyond core's own fields (`hands::fields` holds them).
    fn surface(&self, _name: Surface, _facts: &Value) -> Hook<Value> {
        Ok(Answer::Defer)
    }

    /// P11: what the one claim counts beside core's own rows, inside the claim's own transaction.
    fn claim_ledger(
        &self,
        _connection: &mut dyn Ledger,
        _record: &Value,
        _now: f64,
        _carried: &[Point],
    ) -> Hook<Alternative> {
        Ok(Answer::Defer)
    }

    /// P12: how many sends may wait for their receipts at once (`hands::workers`).
    fn partition(&self, _records: &[Value]) -> Hook<Value> {
        Ok(Answer::Defer)
    }

    /// P13: what the launcher does about the watcher.
    fn supervise(&self, _facts: &Value) -> Hook<Alternative> {
        Ok(Answer::Defer)
    }

    /// P14: a record core holds has just moved to `state`. Its answer is not read.
    fn moved(&self, _record: &Value, _state: &str) -> Hook<()> {
        Ok(Answer::Defer)
    }

    /// P15: how a continuation is carried and how its arrival is proven.
    fn delivery(&self, _record: &Value) -> Hook<Alternative> {
        Ok(Answer::Defer)
    }

    /// P16: what continues a record while the app does not hold its conversation.
    fn unloaded(&self, _record: &Value) -> Hook<Unloaded> {
        Ok(Answer::Defer)
    }

    /// P17: whether core takes up a failure it would not recover alone.
    fn admission(&self, _failure: &Value) -> Hook<Alternative> {
        Ok(Answer::Defer)
    }

    /// P18: which conversations besides the Codex app's core watches - a set of SessionKind words.
    fn sessions(&self) -> Hook<Vec<Value>> {
        Ok(Answer::Defer)
    }

    /// P19: which conversations besides a person's own core takes up - a set of Widening words.
    fn eligibility(&self) -> Hook<Vec<Value>> {
        Ok(Answer::Defer)
    }

    /// P20: a notice core raised. Its answer is not read.
    fn notice(&self, _facts: &Value) -> Hook<()> {
        Ok(Answer::Defer)
    }

    /// P21: how the tasks a person armed the power action for stand.
    fn power(&self, _facts: &Value) -> Hook<Value> {
        Ok(Answer::Defer)
    }

    /// P22: while recovery is paused, an errand that keeps a resident running which sends nothing.
    fn resident(&self, _view: &dyn View) -> Hook<Box<dyn Errand>> {
        Ok(Answer::Defer)
    }

    /// Not a point: whether a capability may answer at `point` now. NULL wants nothing.
    fn wants(&self, _point: Point) -> Result<bool, HookFailed> {
        Ok(false)
    }

    /// Not a point: the installer has just replaced an installation of edition `previous` with this one.
    fn edition_changed(&self, _previous: Edition) -> Result<(), HookFailed> {
        Ok(())
    }

    /// Not a point: the Codex this process drives. Its answer is not read.
    fn codex(&self, _codex_exe: &str, _codex_home: &str) -> Result<(), HookFailed> {
        Ok(())
    }

    /// Not a point: a person has just switched a conversation off.
    fn conversation_off(&self, _thread_id: &str) -> Result<(), HookFailed> {
        Ok(())
    }

    /// Not a point: why P9 just named no route, from a plug that says.
    fn start_held(&self) -> Result<Value, HookFailed> {
        Ok(Value::Null)
    }

    /// Not a point: why P13 named no supervisor, from a plug that says.
    fn supervise_held(&self) -> Result<Value, HookFailed> {
        Ok(Value::Null)
    }

    /// Not a point (v0.6.26 final, S5): the codex.exe paths the plug's own looks last found the app main running
    /// instead of the engine this process drives, which core reads where its own pairing found none. NULL none.
    fn served_elsewhere(&self) -> Result<Vec<String>, HookFailed> {
        Ok(Vec::new())
    }
}

/// NULL: the standard edition's plug, the trait's defaults and nothing more.
#[derive(Debug, Clone, Copy, Default)]
pub struct NullPlug;

impl Plug for NullPlug {}

/// `NULL`.
pub static NULL: NullPlug = NullPlug;

/// An advanced installation whose plug could not be made: it does everything NULL does and says why.
#[derive(Debug, Clone, Copy)]
pub struct DamagedPlug {
    pub reason: PlugFailure,
}

impl Plug for DamagedPlug {
    fn edition(&self) -> Edition {
        Edition::Advanced
    }

    fn badge(&self) -> &'static str {
        "Advanced - not loaded"
    }

    fn damaged(&self) -> Option<PlugFailure> {
        Some(self.reason)
    }
}

/// `HOOKS[point]`: the name of the hook each point calls.
pub fn hook_name(point: Point) -> &'static str {
    match &vocab_gen::domain_plug::HOOKS {
        Node::Map(pairs) => pairs
            .iter()
            .find(|(name, _)| *name == point.as_str())
            .and_then(|(_, hook)| hook.as_str())
            .unwrap_or(""),
        _ => "",
    }
}

/// `ALTERNATIVES[point]`: what a decision point accepts besides DEFER; None for a value point.
pub fn alternatives(point: Point) -> Option<Vec<Alternative>> {
    let Node::Map(pairs) = &vocab_gen::domain_plug::ALTERNATIVES else {
        return None;
    };
    let (_, Node::List(words)) = pairs.iter().find(|(name, _)| *name == point.as_str())? else {
        return None;
    };
    Some(
        words
            .iter()
            .filter_map(|word| word.as_str().and_then(Alternative::parse))
            .collect(),
    )
}

/// `PACED_AS[word]`: the temporary kind each AS_ word waits, counts and is switched off as.
pub fn paced_as(word: Alternative) -> Option<&'static str> {
    match &vocab_gen::domain_plug::PACED_AS {
        Node::Map(pairs) => pairs
            .iter()
            .find(|(name, _)| *name == word.as_str())
            .and_then(|(_, kind)| kind.as_str()),
        _ => None,
    }
}

/// The plug core holds: NULL itself, or an edition's.
enum Held {
    Null,
    Plug(Box<dyn Plug>),
}

/// A plug as core holds it (`Guarded`): every hook asked through one consult, every value checked before core takes
/// it. `failures` counts the hooks that raised, over every caller on every thread.
pub struct Guarded {
    held: Held,
    failures: AtomicU64,
}

/// What `Guarded.sender` answers: core's own backend, or the plug's channel held to the launch guard.
pub enum Sender {
    Backend,
    Channel {
        channel: Box<dyn Channel>,
        concurrent: bool,
    },
}

/// What `Guarded.unloaded` answers.
pub enum UnloadedAnswer {
    Defer,
    Queued(Alternative),
    Route { route: Box<dyn Route>, words: bool },
}

impl Guarded {
    /// The standard edition's plug: core does exactly what it does with no plug at all.
    pub fn null() -> Guarded {
        Guarded {
            held: Held::Null,
            failures: AtomicU64::new(0),
        }
    }

    /// An edition's plug.
    pub fn new(plug: Box<dyn Plug>) -> Guarded {
        Guarded {
            held: Held::Plug(plug),
            failures: AtomicU64::new(0),
        }
    }

    fn plug(&self) -> &dyn Plug {
        match &self.held {
            Held::Null => &NULL,
            Held::Plug(plug) => plug.as_ref(),
        }
    }

    /// Whether this is the standard edition's plug.
    pub fn is_null(&self) -> bool {
        matches!(self.held, Held::Null)
    }

    pub fn edition(&self) -> Edition {
        self.plug().edition()
    }

    pub fn badge(&self) -> &'static str {
        self.plug().badge()
    }

    /// The plug held, for `edition::shown`.
    pub fn held(&self) -> &dyn Plug {
        self.plug()
    }

    /// How many hooks raised so far.
    pub fn failures(&self) -> u64 {
        self.failures.load(Ordering::Relaxed)
    }

    fn failed(&self) {
        self.failures.fetch_add(1, Ordering::Relaxed);
    }

    /// `consult`: ask the plug at one point. A hook that fails (an `Err`, or a panic) gets NULL's answer in its place
    /// and is counted; NULL itself is asked directly.
    fn ask<T>(
        &self,
        call: impl FnOnce(&dyn Plug) -> Hook<T>,
        null: impl FnOnce() -> Hook<T>,
    ) -> (Answer<T>, bool) {
        let Held::Plug(plug) = &self.held else {
            return (null().unwrap_or(Answer::Defer), false);
        };
        match catch_unwind(AssertUnwindSafe(|| call(plug.as_ref()))) {
            Ok(Ok(answer)) => (answer, false),
            _ => {
                self.failed();
                (null().unwrap_or(Answer::Defer), true)
            }
        }
    }

    /// A decision point's answer: DEFER, or a member of the point's closed set; another word is DEFER.
    fn decided(
        &self,
        point: Point,
        call: impl FnOnce(&dyn Plug) -> Hook<Alternative>,
    ) -> (Answer<Alternative>, bool) {
        let (answer, broke) = self.ask(call, || Ok(Answer::Defer));
        match answer {
            Answer::Is(word)
                if alternatives(point).is_some_and(|accepted| accepted.contains(&word)) =>
            {
                (Answer::Is(word), broke)
            }
            _ => (Answer::Defer, broke),
        }
    }

    fn quietly<T>(&self, call: impl FnOnce(&dyn Plug) -> Result<T, HookFailed>, null: T) -> T {
        if self.is_null() {
            return null;
        }
        match catch_unwind(AssertUnwindSafe(|| call(self.plug()))) {
            Ok(Ok(found)) => found,
            _ => {
                self.failed();
                null
            }
        }
    }

    /// P2: the records the plug hands over that core can carry out. The Python's exception class where its check
    /// raises one (a time too large for a float).
    pub fn records(&self, view: &dyn View) -> Result<Vec<Value>, &'static str> {
        match self.ask(|plug| plug.records(view), || NULL.records(view)).0 {
            Answer::Is(found) => hands::records_of(Some(&found)),
            Answer::Defer => Ok(Vec::new()),
        }
    }

    /// P3.
    pub fn gate(&self, name: &str, record: &Value, facts: &Value) -> Answer<Alternative> {
        self.decided(Point::Gates, |plug| plug.gate(name, record, facts))
            .0
    }

    /// P4: words, or DEFER.
    pub fn text(&self, record: &Value, text: &Str) -> Answer<Str> {
        self.ask(|plug| plug.text(record, text), || NULL.text(record, text))
            .0
    }

    /// P5: core's backend, or the channel the plug named.
    pub fn sender(&self, record: &Value) -> Sender {
        match self
            .ask(|plug| plug.sender(record), || NULL.sender(record))
            .0
        {
            Answer::Defer => Sender::Backend,
            Answer::Is(channel) => {
                let concurrent = catch_unwind(AssertUnwindSafe(|| channel.pools()))
                    .is_ok_and(|pools| pools == Ok(true));
                Sender::Channel {
                    channel,
                    concurrent,
                }
            }
        }
    }

    /// P6.
    pub fn outcome(&self, record: &Value, outcome: &str) -> Answer<Alternative> {
        self.decided(Point::Outcome, |plug| plug.outcome(record, outcome))
            .0
    }

    /// P7.
    pub fn schedule(&self, record: &Value, due: &Value) -> Answer<Alternative> {
        self.decided(Point::Schedule, |plug| plug.schedule(record, due))
            .0
    }

    /// P8: the errand the plug answered, or DEFER.
    pub fn tick(&self, view: &dyn View) -> Answer<Box<dyn Errand>> {
        self.ask(|plug| plug.tick(view), || NULL.tick(view)).0
    }

    /// P22: the errand the plug answered while recovery is paused, or DEFER.
    pub fn resident(&self, view: &dyn View) -> Answer<Box<dyn Errand>> {
        self.ask(|plug| plug.resident(view), || NULL.resident(view))
            .0
    }

    /// P9: a route to start the watcher outside Codex's job, or DEFER.
    pub fn start_route(&self, request: &Value) -> Answer<Box<dyn StartRoute>> {
        self.ask(
            |plug| plug.start_route(request),
            || NULL.start_route(request),
        )
        .0
    }

    /// P10: fields for one surface, or DEFER.
    pub fn surface(&self, name: Surface, facts: &Value) -> Answer<Value> {
        match self
            .ask(
                |plug| plug.surface(name, facts),
                || NULL.surface(name, facts),
            )
            .0
        {
            Answer::Is(found) => hands::fields(&found).map_or(Answer::Defer, Answer::Is),
            Answer::Defer => Answer::Defer,
        }
    }

    /// P11 as the claim asks it: the answer, and whether this very call raised.
    pub fn claim_ledger_checked(
        &self,
        connection: &mut dyn Ledger,
        record: &Value,
        now: f64,
        carried: &[Point],
    ) -> (Answer<Alternative>, bool) {
        self.decided(Point::ClaimLedger, |plug| {
            plug.claim_ledger(connection, record, now, carried)
        })
    }

    pub fn claim_ledger(
        &self,
        connection: &mut dyn Ledger,
        record: &Value,
        now: f64,
        carried: &[Point],
    ) -> Answer<Alternative> {
        self.claim_ledger_checked(connection, record, now, carried)
            .0
    }

    /// P12: how many sends may wait for their receipts at once.
    pub fn partition(&self, records: &[Value]) -> i64 {
        match self
            .ask(|plug| plug.partition(records), || NULL.partition(records))
            .0
        {
            Answer::Is(found) => hands::workers(Some(&found)),
            Answer::Defer => hands::workers(None),
        }
    }

    /// P13.
    pub fn supervise(&self, facts: &Value) -> Answer<Alternative> {
        self.decided(Point::Supervision, |plug| plug.supervise(facts))
            .0
    }

    /// P20: told only while the plug wants it; `facts` made only then. Its answer is not read.
    pub fn notice(&self, facts: &dyn Fn() -> Option<Value>) {
        if self.wants(Point::Notice)
            && let Ok(Some(made)) = catch_unwind(AssertUnwindSafe(facts))
        {
            let _ = self.ask(|plug| plug.notice(&made), || NULL.notice(&made));
        }
    }

    /// P21: `{"tasks", "threads"}` or None - NULL's, a plug that does not want P21 now, a hook that raised, and any
    /// answer not exactly that shape.
    pub fn power(&self, facts: &Value) -> Option<Value> {
        if !self.wants(Point::Power) {
            return None;
        }
        match self.ask(|plug| plug.power(facts), || NULL.power(facts)).0 {
            Answer::Is(found) => hands::power_of(&found),
            Answer::Defer => None,
        }
    }

    /// P14. Its answer is not read.
    pub fn moved(&self, record: &Value, state: &str) {
        let _ = self.ask(
            |plug| plug.moved(record, state),
            || NULL.moved(record, state),
        );
    }

    /// P15.
    pub fn delivery(&self, record: &Value) -> Answer<Alternative> {
        self.decided(Point::Delivery, |plug| plug.delivery(record))
            .0
    }

    /// P16: the route the plug names, a queued answer, or DEFER (core's own wait).
    pub fn unloaded(&self, record: &Value) -> UnloadedAnswer {
        match self
            .ask(|plug| plug.unloaded(record), || NULL.unloaded(record))
            .0
        {
            Answer::Defer => UnloadedAnswer::Defer,
            Answer::Is(Unloaded::Queued(word)) if QUEUED.contains(&word) => {
                UnloadedAnswer::Queued(word)
            }
            Answer::Is(Unloaded::Queued(_)) => UnloadedAnswer::Defer,
            Answer::Is(Unloaded::Route(route)) => {
                match catch_unwind(AssertUnwindSafe(|| route.takes_words())) {
                    Ok(Ok(words)) => UnloadedAnswer::Route { route, words },
                    _ => UnloadedAnswer::Defer,
                }
            }
        }
    }

    /// P17.
    pub fn admission(&self, failure: &Value) -> Answer<Alternative> {
        self.decided(Point::Admission, |plug| plug.admission(failure))
            .0
    }

    /// P19: the plug's Widening words, sorted; none for anything else.
    pub fn eligibility(&self) -> Vec<String> {
        match self.ask(|plug| plug.eligibility(), || NULL.eligibility()).0 {
            Answer::Is(found) => hands::widening_of(Some(&found)),
            Answer::Defer => Vec::new(),
        }
    }

    /// P18: the plug's SessionKind words, sorted; none otherwise.
    pub fn sessions(&self) -> Vec<String> {
        match self.ask(|plug| plug.sessions(), || NULL.sessions()).0 {
            Answer::Is(found) => hands::kinds_of(Some(&found)),
            Answer::Defer => Vec::new(),
        }
    }

    /// Plug.wants, true only if it says true: NULL and a failure want nothing.
    pub fn wants(&self, point: Point) -> bool {
        self.quietly(|plug| plug.wants(point), false)
    }

    pub fn start_held(&self) -> Value {
        self.quietly(|plug| plug.start_held(), Value::Null)
    }

    pub fn supervise_held(&self) -> Value {
        self.quietly(|plug| plug.supervise_held(), Value::Null)
    }

    /// `plug.served_elsewhere`, read as `runtime/app.py` reads it (the plug's own property, not through `consult`):
    /// NULL's none, and none where it raised - which is not counted among the hooks that failed.
    pub fn served_elsewhere(&self) -> Vec<String> {
        if self.is_null() {
            return Vec::new();
        }
        match catch_unwind(AssertUnwindSafe(|| self.plug().served_elsewhere())) {
            Ok(Ok(found)) => found,
            _ => Vec::new(),
        }
    }

    /// Tell the plug which Codex this process drives: NULL is told nothing.
    pub fn codex(&self, codex_exe: &str, codex_home: &str) {
        self.quietly(|plug| plug.codex(codex_exe, codex_home), ());
    }

    /// Plug.conversation_off, as `codex` is told.
    pub fn conversation_off(&self, thread_id: &str) {
        self.quietly(|plug| plug.conversation_off(thread_id), ());
    }
}

/// `QUEUED`: P16's two answers core carries out as its ordinary send.
pub const QUEUED: &[Alternative] = &[Alternative::QueueForOpen, Alternative::ToSession];

/// `guard(plug)`: NULL for none.
pub fn guard(plug: Option<Box<dyn Plug>>) -> Guarded {
    plug.map_or_else(Guarded::null, Guarded::new)
}
