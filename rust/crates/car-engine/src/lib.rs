//! car-engine: the part that decides - what to recover, when, and what became of it (`engine/`, PLAN 1.2 row 10,
//! seat S4.1).
//!
//! The reference is one class, `Engine`, composed of nineteen mixins (`engine/__init__.py`). Here it is one struct,
//! [`Engine`], and one `impl Engine` block per mixin, in a module named as the mixin's file:
//!
//! | Python | here |
//! |---|---|
//! | `options.py` | [`options`]: what it was given, and the policy it was last told |
//! | `detect.py` | [`detect`]: turning what Codex recorded into records this product owns |
//! | `freshness.py` | [`freshness`]: whether Codex is in a state worth reading |
//! | `dispatch.py`, `delivery.py` | [`dispatch`], [`delivery`]: sending one continuation, how it is carried |
//! | `routes.py`, `tosession.py`, `foropen.py` | [`routes`], [`tosession`], [`foropen`]: P16's answers |
//! | `kinds.py`, `compaction.py` | [`kinds`], [`compaction`]: P18/P19, and a full context window's compaction |
//! | `reconcile.py` | car-scheduler ([`host`] gives it the engine) |
//! | `outcome.py`, `announce.py` | [`outcome`], [`announce`] |
//! | `guard.py`, `relaxed.py`, `resend.py` | [`guard`], [`relaxed`], [`resend`] |
//! | `plugrecords.py`, `notices.py`, `storeview.py` | [`plugrecords`], [`notices`], [`storeview`] |
//! | `impossible.py` | [`impossible`] (pure: the watcher's judge) |
//! | `launches.py`, `recordchannel.py` | not ported (P12's pool and P2's channel: the advanced plug's alone; see GROUNDWORK) |
//!
//! What the engine is handed is [`seam`]'s: its store, its reader, its backend (S3.3's seam) and the watcher's
//! questions. The plug is car-policy's [`Guarded`]; the standard edition's is `Guarded::null()`.
//!
//! The port rule: the implementation is replaced, not the behaviour. A record is the store's `dict` (car-machine's
//! [`Map`]), read and written with Python's operators ([`py`]); an error is the class of the exception the reference
//! would raise, caught exactly where it catches one.

pub mod announce;
pub mod caught;
pub mod compaction;
pub mod delivery;
pub mod detect;
pub mod dispatch;
pub mod foropen;
pub mod freshness;
pub mod guard;
pub mod host;
pub mod impossible;
pub mod kinds;
pub mod notices;
pub mod options;
pub mod outcome;
pub mod plugrecords;
pub mod py;
pub mod relaxed;
pub mod resend;
pub mod routes;
pub mod seam;
pub mod storeview;
pub mod tosession;
pub mod transport;

use std::collections::{BTreeSet, HashMap, HashSet};
use std::sync::{Arc, Mutex};

use car_machine::json::{Map, Value};
use car_machine::pyval::Py;
use car_machine::vocab_gen::domain_skips::RECOVERY_OFF;
use car_machine::vocab_gen::domain_states::WAITING;
use car_policy::classify::clock::LocalClock;
use car_policy::plug::{Alternative, Answer, Guarded, Point};
use car_policy::settings::managed::Managed;
use car_policy::settings::os::Os;

pub use options::{
    BACKOFF_LADDER, DELIVERY_TIMEOUT, Options, TRANSIENT_BACKOFF, backoff_delay, transient_delay,
};
pub use seam::{Backend, Claim, LaunchGuard, OnceWords, Register, Row, Source, Store};

/// `UNSENT` (engine/reconcile.py): the states a record may be sent from.
pub const UNSENT: &[&str] = WAITING;

/// `log(thread_id, event, detail)`.
pub type Log = Box<dyn FnMut(Option<&str>, &str, &Value)>;
/// `notify(event, payload)`: a failure is the notifier's, and is logged.
pub type Notify = Box<dyn FnMut(&str, &Map) -> Py<()>>;
/// `os.environ.get(name)`.
pub type Environ = Box<dyn Fn(&str) -> Option<String>>;

/// What the engine is given beside its store, reader and backend (`Engine(..., *, keyword=...)`), each defaulting as
/// the reference's keyword does.
pub struct Given {
    pub dispatch_lock: Option<Arc<Mutex<()>>>,
    pub clock: Box<dyn Fn() -> f64>,
    pub log: Option<Log>,
    pub options: Map,
    pub notify: Option<Notify>,
    pub language: Option<String>,
    pub home_lock: Option<Box<dyn Fn() -> Py<bool>>>,
    pub engine_state: Option<Box<dyn Fn() -> Py<Value>>>,
    pub plug: Arc<Guarded>,
    pub connectivity: Option<Box<dyn Fn() -> Py<Value>>>,
    pub home_key: String,
    /// `open_store`: whether a worker could open a store of its own (P12's pool is not ported: always inline).
    pub open_store: bool,
    pub once_words: Option<Box<dyn OnceWords>>,
    /// The draw jitter asks (`random.Random().random()`), only while jitter is on.
    pub draw: Box<dyn FnMut() -> f64>,
    /// What `time.localtime`/`time.mktime` read: quiet hours and a reset's time in a continuation.
    pub local: Box<dyn LocalClock>,
    /// `os.environ.get` and Windows' preferred UI languages, as a continuation's language is resolved.
    pub environ: Environ,
    pub windows_languages: Box<dyn Fn() -> Vec<String>>,
    /// What the settings' coercion reads of the machine.
    pub os: Arc<dyn Os + Send + Sync>,
}

/// The part that decides.
pub struct Engine {
    pub store: Box<dyn Store>,
    pub source: Box<dyn Source>,
    pub backend: Box<dyn Backend>,
    pub plug: Arc<Guarded>,
    pub dispatch_lock: Option<Arc<Mutex<()>>>,
    pub clock: Box<dyn Fn() -> f64>,
    pub log_sink: Log,
    pub notify_sink: Notify,
    pub language: String,
    pub home_lock: Box<dyn Fn() -> Py<bool>>,
    pub engine_state: Box<dyn Fn() -> Py<Value>>,
    pub connectivity: Box<dyn Fn() -> Py<Value>>,
    /// v0.6.15-beta: the Codex home this engine recovers in - '' for the default - and whether that home was taken out
    /// of Settings, after which it only watches what it sent until that settles.
    pub home_key: String,
    pub retiring: bool,
    pub open_store: bool,
    pub once_words: Option<Box<dyn OnceWords>>,
    pub policy_values: Map,
    pub managed: Managed,
    pub options: Options,
    /// v0.6.26: whether this tick's detection could read Codex's history (None: it did not try).
    pub detection_failed: Option<bool>,
    /// v0.6.26 (review V6): what each record the plug handed over this tick waits for, by conversation.
    pub handed_waits: Map,
    pub(crate) draw_source: Box<dyn FnMut() -> f64>,
    pub(crate) local: Box<dyn LocalClock>,
    pub(crate) environ: Environ,
    pub(crate) windows_languages: Box<dyn Fn() -> Vec<String>>,
    pub(crate) os: Arc<dyn Os + Send + Sync>,
    pub(crate) more_quiet: Vec<Value>,
    pub(crate) usage_cache: Option<(f64, Value)>,
    pub(crate) told: HashSet<String>,
    pub(crate) declined: HashSet<String>,
    pub(crate) skips_told: py::Kept<(String, String)>,
    pub(crate) passed_known: py::Kept<String>,
    pub(crate) seen_failed: Option<Value>,
    pub(crate) off_told: bool,
    pub(crate) passed_since: Option<f64>,
    pub(crate) unadmitted: HashMap<String, f64>,
    pub(crate) early_look: Option<String>,
    pub(crate) early_at: Option<f64>,
    pub(crate) schedule_said: Option<Answer<Alternative>>,
    pub(crate) announced: HashSet<String>,
    pub(crate) stale_since: HashMap<String, f64>,
    pub(crate) stale_seen: HashMap<String, f64>,
    pub(crate) watching_since: f64,
    pub(crate) stale_cleared_at: f64,
    pub(crate) no_trace: indexed::Indexed,
    pub(crate) seen_queued: HashSet<String>,
    pub(crate) seen_queued_cleared_at: f64,
    pub(crate) resent_looked_at: Option<f64>,
    pub(crate) loaded_cache: HashMap<String, (f64, Value)>,
    pub(crate) watch_offset: u64,
    pub(crate) once_sent: HashMap<String, Value>,
    pub(crate) once_seen: HashMap<String, Value>,
    pub(crate) once_doubted: HashSet<String>,
    pub(crate) session_holders: HashMap<String, Value>,
    pub(crate) session_kinds: Option<BTreeSet<String>>,
    pub(crate) widened: Option<BTreeSet<String>>,
    pub(crate) loaded_since: HashMap<String, f64>,
    pub(crate) for_open_seen: HashMap<String, f64>,
    pub(crate) wrap_ups: HashMap<String, BTreeSet<String>>,
}

/// The uncertain submissions a look found no trace of, in the order found (`_no_trace`, a `dict`).
pub(crate) mod indexed {
    #[derive(Debug, Default)]
    pub struct Indexed(pub Vec<(String, f64)>);

    impl Indexed {
        pub fn pop(&mut self, key: &str) {
            self.0.retain(|(each, _)| each != key);
        }
        pub fn insert(&mut self, key: &str, at: f64) {
            match self.0.iter_mut().find(|(each, _)| each == key) {
                Some(slot) => slot.1 = at,
                None => self.0.push((key.to_owned(), at)),
            }
        }
    }
}

impl Engine {
    /// `Engine(store, source, backend, **given)`.
    pub fn new(
        store: Box<dyn Store>,
        source: Box<dyn Source>,
        backend: Box<dyn Backend>,
        given: Given,
    ) -> Engine {
        let clock = given.clock;
        let watching_since = clock();
        let mut options = Options::default();
        options.apply(&given.options);
        // D15: a panic inside a seam is the exception the reference meets at that call (caught.rs).
        Engine {
            store: Box::new(caught::Caught(store)),
            source: Box::new(caught::Caught(source)),
            backend: Box::new(caught::Caught(backend)),
            plug: given.plug,
            dispatch_lock: given.dispatch_lock,
            clock,
            log_sink: given.log.unwrap_or_else(|| Box::new(|_, _, _| {})),
            notify_sink: given.notify.unwrap_or_else(|| Box::new(|_, _| Ok(()))),
            language: given.language.unwrap_or_else(|| "en".into()),
            home_lock: given.home_lock.unwrap_or_else(|| Box::new(|| Ok(true))),
            engine_state: given
                .engine_state
                .unwrap_or_else(|| Box::new(|| Ok(Value::from("verified")))),
            connectivity: given
                .connectivity
                .unwrap_or_else(|| Box::new(|| Ok(Value::Null))),
            home_key: given.home_key,
            retiring: false,
            open_store: given.open_store,
            once_words: given
                .once_words
                .map(|words| Box::new(caught::Caught(words)) as Box<dyn OnceWords>),
            policy_values: car_policy::settings::defaults(),
            managed: Managed::default(),
            options,
            detection_failed: None,
            handed_waits: Map::new(),
            draw_source: given.draw,
            local: given.local,
            environ: given.environ,
            windows_languages: given.windows_languages,
            os: given.os,
            more_quiet: Vec::new(),
            usage_cache: None,
            told: HashSet::new(),
            declined: HashSet::new(),
            skips_told: py::Kept::new(),
            passed_known: py::Kept::new(),
            seen_failed: None,
            off_told: false,
            passed_since: None,
            unadmitted: HashMap::new(),
            early_look: None,
            early_at: None,
            schedule_said: None,
            announced: HashSet::new(),
            stale_since: HashMap::new(),
            stale_seen: HashMap::new(),
            watching_since,
            stale_cleared_at: f64::NEG_INFINITY,
            no_trace: indexed::Indexed::default(),
            seen_queued: HashSet::new(),
            seen_queued_cleared_at: f64::NEG_INFINITY,
            resent_looked_at: None,
            loaded_cache: HashMap::new(),
            watch_offset: 0,
            once_sent: HashMap::new(),
            once_seen: HashMap::new(),
            once_doubted: HashSet::new(),
            session_holders: HashMap::new(),
            session_kinds: None,
            widened: None,
            loaded_since: HashMap::new(),
            for_open_seen: HashMap::new(),
            wrap_ups: HashMap::new(),
        }
    }

    /// `self.clock()`.
    pub fn now(&self) -> f64 {
        (self.clock)()
    }

    /// `self.log(thread_id, event, detail)`.
    pub fn log(&mut self, thread_id: Option<&str>, event: &str, detail: Value) {
        (self.log_sink)(thread_id, event, &detail);
    }

    // ------------------------------------------------------------------ tick
    /// `tick()`: one pass of the loop. v0.6.19 (issue #50): a person's usage check is served at this tick's looks or
    /// said not checked at its end.
    pub fn tick(&mut self) -> Py<()> {
        let now = self.now();
        let before = self.store.usage_checks_asked(now).unwrap_or_default();
        // `try: self._tick() finally: self._usage_checks_left(before)`: run however the tick ends, a panic included,
        // which then goes on to the caller as the exception would.
        let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| self.tick_once()));
        self.usage_checks_left(&before);
        match result {
            Ok(result) => result,
            Err(panic) => std::panic::resume_unwind(panic),
        }
    }

    fn tick_once(&mut self) -> Py<()> {
        self.detection_failed = None;
        self.handed_waits = Map::new();
        // The watch and outcome observation continue when recovery is paused: taking back a queued continuation is
        // exactly what a Pause asks for.
        if self.observe_projections().is_err() {
            self.log(None, "projection_check_unavailable", Value::Null);
        }
        car_scheduler::watch::watch(self)?;
        self.observe_all()?;
        self.watch_resent()?; // v0.6.14: a resend found twice; nothing for the standard edition
        self.prune_once_words(); // v0.6.16-beta.3
        // v0.6.15-beta: a Codex home taken out of Settings only watches what it sent until that settles.
        if self.retiring {
            return Ok(());
        }
        // v0.6.11: an administrator's DisableAutoResume is a Pause here too.
        let settings = self.store.settings()?;
        if !py::truthy(py::get(&settings, "enabled")) || self.managed.disable_auto_resume {
            if !self.off_told {
                self.off_told = true;
                self.log(None, RECOVERY_OFF, Value::Null);
            }
            self.paused_records();
            self.paused_residents();
            return Ok(());
        }
        self.off_told = false;
        // P19 and P18: which conversations detection takes up from here on (engine/kinds.py).
        self.session_kinds()?;
        let view = storeview::StoreView;
        let errand = self.plug.tick(&view);
        let result = self.tick_recover(&view);
        if let Answer::Is(errand) = errand {
            self.errand(errand);
        }
        result
    }

    fn tick_recover(&mut self, view: &storeview::StoreView) -> Py<()> {
        if self.collect().is_err() {
            self.detection_failed = Some(true);
            self.log(None, "detection_unavailable_no_submission", Value::Null);
            return Ok(());
        }
        self.detection_failed = Some(false);
        let due = self.records(UNSENT)?;
        // P12: how many sends may wait for their receipts at once. The pool is not ported: every send is inline,
        // which is what the reference does for the answer every plug but the advanced one gives (1).
        let _workers = self.workers(&due);
        for row in &due {
            if car_scheduler::caught(|| self.attempt(row)).is_err() {
                let thread = py::s(row, "thread_id");
                self.log(
                    Some(&thread),
                    "eligibility_check_failed_no_submission",
                    Value::Null,
                );
            }
        }
        // v0.6.14: what the watch found no trace of, put to the plug for one more send (P7).
        if !self.plug.is_null() {
            self.resend_uncertain();
        }
        // P2: the records of the advanced store that are due (engine/plugrecords.py).
        self.plug_records(view);
        Ok(())
    }

    /// `_paused_residents()` (P22, v0.6.22): while paused, the one question asked - only of a plug that wants it.
    fn paused_residents(&mut self) {
        if self.plug.is_null() || !self.plug.wants(Point::Resident) {
            return;
        }
        if let Answer::Is(errand) = self.plug.resident(&storeview::StoreView) {
            self.errand(errand);
        }
    }

    /// `_errand(errand)` (P8, v0.6.14): run once, last in the tick. The errand's guards (store/claims.py
    /// `errand_guard`) are the advanced store's and not ported (S7.2): an errand here is one that raised.
    fn errand(&mut self, _errand: Box<dyn car_policy::plug::Errand>) {
        self.log(None, "plug_errand_failed", Value::Null);
    }

    /// `_records(states)`: this engine's own home's records in `states` (v0.6.15-beta): never another home's.
    pub fn records(&self, states: &[&str]) -> Py<Vec<Row>> {
        self.store.records_in(states, Some(&self.home_key))
    }

    /// `_claimed(thread_id)`: this home's records that may have put a continuation into `thread_id`.
    pub fn claimed(&self, thread_id: &str) -> Py<Vec<Row>> {
        Ok(self
            .store
            .claimed_on_thread(thread_id)?
            .into_iter()
            .filter(|row| py::text_of(row, "home_key") == Some(self.home_key.as_str()))
            .collect())
    }
}
