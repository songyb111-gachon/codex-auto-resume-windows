//! `plug.py` (seat S7.2a): the one module core reaches of this edition - its plug, `AdvancedPlug`, and its kinds of
//! notice.
//!
//! core (car-policy's `edition::load`) takes the plug only when [`PLUG_API`] is the number core was built with, and
//! makes it once for each home ([`create`]). Every hook hands its question to the runtime (`crate::runtime`), which asks
//! the registry's capabilities in the state each one is in; nothing is opened, read or written until a hook needs it,
//! and with no capability on every decision point answers as NULL does. What it adds is on its surfaces (P10,
//! `crate::surfaces::answer`, seat S7.3a).

use std::sync::{Arc, OnceLock};

use car_config::Paths;
use car_machine::json::{Map, Str, Value};
use car_policy::plug::{
    Alternative, Answer, Channel, Edition, Errand, Hook, HookFailed, Ledger, Plug, Point,
    StartRoute, Surface, Unloaded, View,
};

use crate::capabilities::Said;
use crate::runtime::{Options, Raise, Shared};

/// `PLUG_API`: written out rather than read from core - the check is whether this crate was written for the core
/// beside it, and a number taken from that core would agree with any core at all.
pub const PLUG_API: i64 = 8;

/// `NOTICE_KINDS`: this edition's kinds of notice a person can keep on screen until clicked - an id, the notifier kinds
/// it covers, and the key of its words in every language. `python_returned` stays registered and is never raised (D8,
/// the owner's Q1 (a)).
pub const NOTICE_KINDS: &[(&str, &[&str], &str)] = &[
    ("near_limit", &["near_limit"], "msg.toast_near_limit"),
    (
        "near_limit_not_stopped",
        &["near_limit_not_stopped"],
        "msg.toast_near_limit_not_stopped",
    ),
    (
        "near_limit_press_resume",
        &["near_limit_press_resume"],
        "msg.toast_near_limit_press_resume",
    ),
    (
        "near_limit_not_continued",
        &["near_limit_not_continued"],
        "msg.toast_near_limit_not_continued",
    ),
    (
        "update_offered",
        &["update_offered"],
        "msg.toast_update_offered",
    ),
    (
        "restart_gave_up",
        &["restart_gave_up"],
        "msg.toast_restart_gave_up",
    ),
    (
        "account_changed",
        &["account_changed"],
        "msg.toast_account_changed",
    ),
    (
        "accounts_exhausted",
        &["accounts_exhausted"],
        "msg.toast_accounts_exhausted",
    ),
    (
        "python_returned",
        &["python_returned"],
        "msg.toast_python_returned",
    ),
];

/// `register_notice_kinds()`: NOTICE_KINDS registered with core; registering again replaces, so a second plug in one
/// process changes nothing.
pub fn register_notice_kinds() {
    for (kind, notices, key) in NOTICE_KINDS {
        let mut words = Map::new();
        for locale in car_words::l10n::LOCALES {
            let text = car_words::l10n::text(key, locale, &[]).unwrap_or_else(|| (*key).to_owned());
            words.insert((*locale).into(), Value::Str(text.into()));
        }
        let notices = Value::Array(
            notices
                .iter()
                .map(|notice| Value::Str((*notice).into()))
                .collect(),
        );
        let _ = car_policy::settings::notice_kinds::register(
            &Value::Str((*kind).into()),
            &notices,
            &Value::Object(words),
        );
    }
}

/// What the plug's own runtime is made with, asked once, at the first hook that needs it.
pub type MakeOptions = Box<dyn Fn() -> Options + Send + Sync>;

/// What `codex` and `served_elsewhere` reach (car-config's `Os`, for `inuse.tell`'s `Path.resolve()`).
pub type OsSource = Box<dyn Fn() -> car_config::Os + Send + Sync>;

/// `AdvancedPlug(paths, **options)`: the advanced edition's plug. Every capability is off until a person turns it on,
/// and while none is on every decision answers as NULL does.
pub struct AdvancedPlug {
    pub paths: Paths,
    options: MakeOptions,
    os: OsSource,
    runtime: OnceLock<Arc<Shared>>,
}

fn failed<T>(result: Result<T, Raise>) -> Result<T, HookFailed> {
    result.map_err(|_| HookFailed)
}

/// A decision point's answer as core takes it: a word of its closed set, else DEFER (core checks it again).
fn decided(said: Said) -> Answer<Alternative> {
    match said.text().and_then(Alternative::parse) {
        Some(word) => Answer::Is(word),
        None => Answer::Defer,
    }
}

impl AdvancedPlug {
    pub fn new(paths: Paths, options: MakeOptions, os: OsSource) -> AdvancedPlug {
        AdvancedPlug {
            paths,
            options,
            os,
            runtime: OnceLock::new(),
        }
    }

    /// `self.runtime`: made at the first hook that needs it.
    pub fn runtime(&self) -> &Arc<Shared> {
        self.runtime
            .get_or_init(|| Shared::new(self.paths.clone(), (self.options)()))
    }

    /// The runtime if one was made (`self._runtime`).
    pub fn made(&self) -> Option<&Arc<Shared>> {
        self.runtime.get()
    }

    fn ask(&self, point: Point, args: &[&Value]) -> Result<Said, HookFailed> {
        failed(self.runtime().enter(|runtime| runtime.ask(point, args)))
    }
}

impl Plug for AdvancedPlug {
    fn edition(&self) -> Edition {
        Edition::Advanced
    }

    fn badge(&self) -> &'static str {
        "Advanced"
    }

    fn records(&self, view: &dyn View) -> Hook<Vec<Value>> {
        let found = failed(self.runtime().enter(|runtime| runtime.records(view)))?;
        Ok(if found.is_empty() {
            Answer::Defer
        } else {
            Answer::Is(found)
        })
    }

    fn gate(&self, name: &str, record: &Value, facts: &Value) -> Hook<Alternative> {
        Ok(decided(self.ask(
            Point::Gates,
            &[&Value::Str(name.into()), record, facts],
        )?))
    }

    fn text(&self, record: &Value, text: &Str) -> Hook<Str> {
        let said = self.ask(Point::Text, &[record, &Value::Str(text.clone())])?;
        Ok(match said {
            Said::Word(word) => Answer::Is(word.as_str().into()),
            Said::Value(Value::Str(words)) => Answer::Is(words),
            _ => Answer::Defer,
        })
    }

    fn sender(&self, record: &Value) -> Hook<Box<dyn Channel>> {
        Ok(match self.ask(Point::Sender, &[record])? {
            Said::Channel(channel) => Answer::Is(channel),
            _ => Answer::Defer,
        })
    }

    fn outcome(&self, record: &Value, outcome: &str) -> Hook<Alternative> {
        Ok(decided(self.ask(
            Point::Outcome,
            &[record, &Value::Str(outcome.into())],
        )?))
    }

    fn schedule(&self, record: &Value, due: &Value) -> Hook<Alternative> {
        Ok(decided(self.ask(Point::Schedule, &[record, due])?))
    }

    fn tick(&self, view: &dyn View) -> Hook<Box<dyn Errand>> {
        let errands = failed(self.runtime().enter(|runtime| runtime.tick(view)))?;
        Ok(match errands {
            Some(errands) => Answer::Is(Box::new(errands)),
            None => Answer::Defer,
        })
    }

    fn resident(&self, view: &dyn View) -> Hook<Box<dyn Errand>> {
        let errands = failed(self.runtime().enter(|runtime| runtime.resident(view)))?;
        Ok(match errands {
            Some(errands) => Answer::Is(Box::new(errands)),
            None => Answer::Defer,
        })
    }

    fn start_route(&self, request: &Value) -> Hook<Box<dyn StartRoute>> {
        let said = failed(self.runtime().enter(|runtime| runtime.start_route(request)))?;
        Ok(match said {
            Said::StartRoute(route) => Answer::Is(route),
            _ => Answer::Defer,
        })
    }

    fn surface(&self, name: Surface, facts: &Value) -> Hook<Value> {
        // `surfaces.answer(self.runtime, name, facts)` (seat S7.3a); what it lets out is a hook that raised.
        match self
            .runtime()
            .enter(|runtime| crate::surfaces::answer(runtime, name, facts))
        {
            Ok(Some(found)) => Ok(Answer::Is(found)),
            Ok(None) => Ok(Answer::Defer),
            Err(_) => Err(HookFailed),
        }
    }

    fn claim_ledger(
        &self,
        connection: &mut dyn Ledger,
        record: &Value,
        now: f64,
        carried: &[Point],
    ) -> Hook<Alternative> {
        let answer = failed(
            self.runtime()
                .enter(|runtime| runtime.claim(connection, record, now, carried)),
        )?;
        Ok(answer.map_or(Answer::Defer, Answer::Is))
    }

    fn partition(&self, records: &[Value]) -> Hook<Value> {
        let records = Value::Array(records.to_vec());
        let answer = failed(self.runtime().enter(|runtime| runtime.partition(&records)))?;
        Ok(answer.map_or(Answer::Defer, Answer::Is))
    }

    fn supervise(&self, facts: &Value) -> Hook<Alternative> {
        // v0.6.23 (python_choice): which Python the watcher runs under. D8 retired the picker, the owner's Q1 (a): DEFER.
        if let Value::Object(map) = facts
            && matches!(map.get("phase"), Some(Value::Str(phase)) if matches!(phase.as_str(), Some("runtime" | "runtime_failed")))
        {
            return Ok(Answer::Defer);
        }
        Ok(decided(failed(
            self.runtime().enter(|runtime| runtime.supervise(facts)),
        )?))
    }

    fn moved(&self, record: &Value, state: &str) -> Hook<()> {
        failed(self.runtime().enter(|runtime| runtime.moved(record, state)))?;
        Ok(Answer::Defer)
    }

    fn delivery(&self, record: &Value) -> Hook<Alternative> {
        Ok(decided(self.ask(Point::Delivery, &[record])?))
    }

    fn unloaded(&self, record: &Value) -> Hook<Unloaded> {
        Ok(match self.ask(Point::Unloaded, &[record])? {
            Said::Route(route) => Answer::Is(Unloaded::Route(route)),
            said => match said.text().and_then(Alternative::parse) {
                Some(word) => Answer::Is(Unloaded::Queued(word)),
                None => Answer::Defer,
            },
        })
    }

    fn admission(&self, failure: &Value) -> Hook<Alternative> {
        Ok(decided(self.ask(Point::Admission, &[failure])?))
    }

    fn sessions(&self) -> Hook<Vec<Value>> {
        let found = failed(self.runtime().enter(|runtime| runtime.sessions()))?;
        Ok(found.map_or(Answer::Defer, |words| {
            Answer::Is(
                words
                    .into_iter()
                    .map(|word| Value::Str(word.into()))
                    .collect(),
            )
        }))
    }

    fn eligibility(&self) -> Hook<Vec<Value>> {
        let found = failed(self.runtime().enter(|runtime| runtime.eligibility()))?;
        Ok(found.map_or(Answer::Defer, |words| {
            Answer::Is(
                words
                    .into_iter()
                    .map(|word| Value::Str(word.into()))
                    .collect(),
            )
        }))
    }

    fn notice(&self, facts: &Value) -> Hook<()> {
        // P20 (v0.6.20): told to push_notices only while the plug wants it, as Guarded.notice asks first; not read.
        self.ask(Point::Notice, &[facts])?;
        Ok(Answer::Defer)
    }

    fn power(&self, facts: &Value) -> Hook<Value> {
        Ok(match self.ask(Point::Power, &[facts])? {
            Said::Defer => Answer::Defer,
            said => said.to_value().map_or(Answer::Defer, Answer::Is),
        })
    }

    fn wants(&self, point: Point) -> Result<bool, HookFailed> {
        Ok(self.runtime().enter(|runtime| runtime.wants(point)))
    }

    fn edition_changed(&self, _previous: Edition) -> Result<(), HookFailed> {
        // Entering from the standard edition turns every capability off; where no advanced state was ever written,
        // nothing can be on, and nothing is written now.
        self.runtime()
            .enter(|runtime| runtime.arming().edition_entered())
            .map(|_| ())
            .map_err(|_| HookFailed)
    }

    fn codex(&self, codex_exe: &str, codex_home: &str) -> Result<(), HookFailed> {
        // The Codex this installation's watcher drives, kept for the capabilities' own sessions (codex/inuse.py).
        let os = (self.os)();
        crate::codex::inuse::tell(&self.paths.home, codex_exe, codex_home, &os)
            .map_err(|_| HookFailed)
    }

    fn conversation_off(&self, thread_id: &str) -> Result<(), HookFailed> {
        failed(
            self.runtime()
                .enter(|runtime| runtime.conversation_off(&Value::Str(thread_id.into()))),
        )
    }

    fn start_held(&self) -> Result<Value, HookFailed> {
        Ok(self.runtime().enter(|runtime| runtime.start_held()))
    }

    fn supervise_held(&self) -> Result<Value, HookFailed> {
        Ok(self.runtime().enter(|runtime| runtime.supervise_held()))
    }

    fn served_elsewhere(&self) -> Result<Vec<String>, HookFailed> {
        // v0.6.26 final (S5): what a capability's own look last found the app main running instead (codex/inuse.py
        // `elsewhere`); nothing is opened or read here, and anything that goes wrong is the empty set.
        Ok(std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
            crate::codex::inuse::elsewhere(Some(&self.paths.home))
        }))
        .map(|found| found.into_iter().collect())
        .unwrap_or_default())
    }
}

/// `create(paths)`: the plug for the installation whose home is `paths`, and this edition's kinds of notice registered
/// with core as it is made.
pub fn create(paths: Paths, options: MakeOptions, os: OsSource) -> AdvancedPlug {
    register_notice_kinds();
    AdvancedPlug::new(paths, options, os)
}
