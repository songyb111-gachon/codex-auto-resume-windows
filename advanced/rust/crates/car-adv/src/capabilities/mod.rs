//! A capability's code, and the table that makes it (seat S7.2a; `registry.py`'s `make=` of every definition).
//!
//! The registry (`crate::registry`) says what each capability is; its code is what answers at the plug's points. In
//! Python a definition carries `make(paths)`, and the runtime calls the code's hooks by name (`getattr(code,
//! HOOKS[point])`), its optional ones only where the class defines them (`runtime._own`: `bind`, `rule_for`, `taken`,
//! `carries`, `not_taken`, `holds`, `watched_due`, `words_sent`, `acted_when_told`, `tend`, `images_of`). Here a code is a
//! [`Code`]: every hook at a point has a default that is what Python's missing attribute is - a raise, which trips the
//! capability (`Raised`) - and every optional hook's default is `None`, "the class has none". [`make`] maps a registry id
//! to the function of the module that owns it (each module file is its seat's, P7-DESIGN 2.2); a function not yet
//! ported answers `None`, which the runtime takes as a `make` that raised.
//!
//! What a hook may answer is Python's anything: [`Said`] - DEFER, a value (a word, a text, a list of records, a
//! number), core's own backend handed back at P5, or one of the objects core carries out (a channel, a route, an
//! errand, a start route; car-policy's traits). The runtime checks every answer as core would before it counts it.

pub mod report;
pub mod stophook;

use std::sync::Weak;

use car_config::Paths;
use car_machine::json::Value;
use car_policy::plug::{Alternative, Channel, Errand, Point, Route, StartRoute, View};

use crate::registry::CapabilityDef;
use crate::state::scoped::Scoped;

/// A hook that raised (Python: any exception out of a capability's code). It costs its own answer and trips its
/// capability (or, kept on, passes it over for that record: K8). `class` is the exception's type, `cause` the type it
/// was raised from and `at` the edition's frames it passed (`file:line function < ...`), as the watcher's log line
/// says them (`runtime._said_raised`); a Rust code says what it knows of them.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Raised {
    pub class: String,
    pub cause: Option<String>,
    pub at: Option<String>,
}

impl Raised {
    /// An exception of `class`, from nothing, passing no frame of the edition's.
    pub fn new(class: &str) -> Raised {
        Raised {
            class: class.to_owned(),
            cause: None,
            at: None,
        }
    }

    /// What a code that has no hook at a point raises when asked there (Python's AttributeError).
    pub fn missing() -> Raised {
        Raised::new("AttributeError")
    }
}

/// What a hook said.
pub enum Said {
    /// DEFER.
    Defer,
    /// An answer word (`Alternative.X`): equal to its text, and the only answer the reference's `is` checks take.
    Word(Alternative),
    /// A plain value: a text, a number, a list (`Value::Array` is a Python list), an object.
    Value(Value),
    /// A tuple: what P2 takes as a list, and P18/P19 as a set of words.
    Tuple(Vec<Value>),
    /// A set or a frozenset: what P18/P19 take (P2 does not).
    Set(Vec<Value>),
    /// P5: the hook handed `backend` (core's BACKEND) back - core's own send.
    Backend,
    /// P5: a channel core sends through.
    Channel(Box<dyn Channel>),
    /// P16: a route core resumes the conversation with.
    Route(Box<dyn Route>),
    /// P8, P22, a run kind's `tend`: an errand core runs once, last in the tick.
    Errand(Box<dyn Errand>),
    /// P9: a route that starts the watcher outside Codex's job.
    StartRoute(Box<dyn StartRoute>),
}

impl Said {
    /// A plain value.
    pub fn value(value: impl Into<Value>) -> Said {
        Said::Value(value.into())
    }

    /// `answer == word`: the word a hook said, as a word or a text equal to one.
    pub fn text(&self) -> Option<&str> {
        match self {
            Said::Word(word) => Some(word.as_str()),
            Said::Value(Value::Str(text)) => text.as_str(),
            _ => None,
        }
    }

    /// `answer is word`.
    pub fn is(&self, word: Alternative) -> bool {
        matches!(self, Said::Word(said) if *said == word)
    }

    /// What core is handed of a plain answer: a word as its text, a value as it is; None for an object.
    pub fn to_value(&self) -> Option<Value> {
        match self {
            Said::Word(word) => Some(Value::Str(word.as_str().into())),
            Said::Value(value) => Some(value.clone()),
            _ => None,
        }
    }

    /// `bool(answer)` as Python reads it: DEFER and every object true; a value by its own truth.
    pub fn truthy(&self) -> bool {
        match self {
            Said::Value(value) => car_machine::pyval::truthy(value),
            Said::Tuple(items) | Said::Set(items) => !items.is_empty(),
            _ => true,
        }
    }

    /// `answer is DEFER`.
    pub fn is_defer(&self) -> bool {
        matches!(self, Said::Defer)
    }

    /// The plain value said, if it was one.
    pub fn as_value(&self) -> Option<&Value> {
        match self {
            Said::Value(value) => Some(value),
            _ => None,
        }
    }
}

/// What a hook returns.
pub type Spoke = Result<Said, Raised>;

/// What `bind` hands a code: the means to see its own view of the state (`state.Scoped`) whenever it needs it - its
/// choices, rules and admission rows, and its one write, only while the runtime has it on. Held weakly: a code kept
/// past its runtime sees nothing.
pub struct Binding {
    pub(crate) runtime: Weak<crate::runtime::Shared>,
    pub(crate) capability: String,
}

impl Binding {
    /// The capability this binding is for.
    pub fn capability(&self) -> &str {
        &self.capability
    }

    /// `f(scoped)` with this capability's `Scoped` (`state.scoped(capability, on=..., verdict=..., armed=...)`), or
    /// `None` once its runtime is gone.
    pub fn with<R>(&self, f: impl FnOnce(&Scoped<'_>) -> R) -> Option<R> {
        let runtime = self.runtime.upgrade()?;
        Some(crate::runtime::scoped_for(&runtime, &self.capability, f))
    }
}

/// A capability's code: what answers at the plug's points (`advancedcase.Code` is the tests' own).
///
/// Every hook at a point defaults to a raise: the runtime asks a code only at the points its definition names, and a
/// code that has no hook there is one that raises when asked (Python's AttributeError). Every optional hook defaults to
/// `None`: the class defines none, and the runtime goes on as Python's `_own(code, name) is None` does.
pub trait Code {
    // ------------------------------------------------------------------ the points (HOOKS)
    /// P2: records of the edition's own due now (a list), or DEFER.
    fn records(&mut self, _view: &dyn View) -> Spoke {
        Err(Raised::missing())
    }
    /// P3.
    fn gate(&mut self, _name: &Value, _record: &Value, _facts: &Value) -> Spoke {
        Err(Raised::missing())
    }
    /// P4: words, or DEFER.
    fn text(&mut self, _record: &Value, _text: &Value) -> Spoke {
        Err(Raised::missing())
    }
    /// P5: a channel, [`Said::Backend`], or DEFER.
    fn sender(&mut self, _record: &Value) -> Spoke {
        Err(Raised::missing())
    }
    /// P6.
    fn outcome(&mut self, _record: &Value, _outcome: &Value) -> Spoke {
        Err(Raised::missing())
    }
    /// P7.
    fn schedule(&mut self, _record: &Value, _due: &Value) -> Spoke {
        Err(Raised::missing())
    }
    /// P8: an errand, or DEFER.
    fn tick(&mut self, _view: &dyn View) -> Spoke {
        Err(Raised::missing())
    }
    /// P9: a start route, or DEFER.
    fn start_route(&mut self, _request: &Value) -> Spoke {
        Err(Raised::missing())
    }
    /// P12: a number of workers, or DEFER.
    fn partition(&mut self, _records: &Value) -> Spoke {
        Err(Raised::missing())
    }
    /// P13.
    fn supervise(&mut self, _facts: &Value) -> Spoke {
        Err(Raised::missing())
    }
    /// P15.
    fn delivery(&mut self, _record: &Value) -> Spoke {
        Err(Raised::missing())
    }
    /// P16: a route, QUEUE_FOR_OPEN or TO_SESSION, or DEFER.
    fn unloaded(&mut self, _record: &Value) -> Spoke {
        Err(Raised::missing())
    }
    /// P17.
    fn admission(&mut self, _failure: &Value) -> Spoke {
        Err(Raised::missing())
    }
    /// P18: SessionKind words.
    fn sessions(&mut self) -> Spoke {
        Err(Raised::missing())
    }
    /// P19: Widening words.
    fn eligibility(&mut self) -> Spoke {
        Err(Raised::missing())
    }
    /// P20: a notice core raised; the answer is not read.
    fn notice(&mut self, _facts: &Value) -> Spoke {
        Err(Raised::missing())
    }
    /// P21.
    fn power(&mut self, _facts: &Value) -> Spoke {
        Err(Raised::missing())
    }
    /// P22: an errand that sends nothing, or DEFER.
    fn resident(&mut self, _view: &dyn View) -> Spoke {
        Err(Raised::missing())
    }

    // ------------------------------------------------------------------ the optional hooks (`_own`)
    /// `bind(scoped)`: its own view of the state, given once as the code is made.
    fn bind(&mut self, _binding: Binding) -> Option<Result<(), Raised>> {
        None
    }
    /// `rule_for(facts, answer)`: the rule an admission rests on (an int), at P17.
    fn rule_for(&mut self, _facts: &Value, _answer: &Value) -> Option<Result<Value, Raised>> {
        None
    }
    /// `taken(point, answer, *arguments)`: told the first time core goes on with a record it took up; what it keeps.
    fn taken(
        &mut self,
        _point: Point,
        _answer: &Value,
        _arguments: &[&Value],
    ) -> Option<Result<Value, Raised>> {
        None
    }
    /// `carries(word)`: whether its answer can be carried together with an earlier one (True, or a warning word).
    fn carries(&mut self, _word: &Value) -> Option<Result<Value, Raised>> {
        None
    }
    /// `not_taken(record)`: at P7, its answer was not the one taken.
    fn not_taken(&mut self, _record: &Value) -> Option<Result<(), Raised>> {
        None
    }
    /// `holds(record)`: whether a record of the edition's own waiting is held back from core this tick (True only).
    fn holds(&mut self, _record: &Value) -> Option<Result<Value, Raised>> {
        None
    }
    /// `watched_due(view)`: the keys of its rows that would be handed core now, for a watched capability.
    fn watched_due(&mut self, _view: &dyn View) -> Option<Spoke> {
        None
    }
    /// `words_sent(record)`: a claim that carried its words committed.
    fn words_sent(&mut self, _record: &Value) -> Option<Result<(), Raised>> {
        None
    }
    /// `acted_when_told(later)`: at P9, the journal's `acted` line is written when the route says it acted (`told`).
    fn acted_when_told(&mut self, _told: Box<dyn FnOnce() + Send>) -> Option<Result<(), Raised>> {
        None
    }
    /// `tend(view)`: a run kind's clean-up while it stands off or watched (`runtime.TENDED`).
    fn tend(&mut self, _view: &dyn View) -> Option<Spoke> {
        None
    }
    /// `images_of(record)`: the prompt queue's pictures of a scheduled message (empty: none).
    fn images_of(&mut self, _record: &Value) -> Option<Spoke> {
        None
    }

    /// The code itself, for the surface that reaches an action's own type (the report's flow, S7.3a).
    fn as_any(&mut self) -> Option<&mut dyn std::any::Any> {
        None
    }
}

/// How the runtime makes a capability's code: the shipped table ([`make`]) or a test's own (the proxy's).
pub type Maker = dyn Fn(&CapabilityDef, &Paths) -> Option<Box<dyn Code>> + Send + Sync;

/// `definition.make(paths)` for every capability the edition ships, by its registry id; `None` for an id this edition
/// has no code for - `python_choice` (D8, the owner's Q1 (a): kept, never offered, no code) and any id not listed.
pub fn make(definition: &CapabilityDef, paths: &Paths) -> Option<Box<dyn Code>> {
    use crate::{control, engine};
    let id = definition.id.as_str();
    match id {
        "start_with_codex" => control::codexstart::make(paths),
        "crash_restart" => engine::supervise::make(paths),
        "goal_continuation" => engine::goal::make(paths),
        "queue_for_open" => engine::foropen::make(paths),
        "compact_continue" => engine::compact::make(paths),
        "model_fallback" => engine::fallback::make(paths),
        "headless_run" => engine::headless::make(paths),
        "other_sessions" => engine::sessions::make(paths),
        "marker_free_continuation" => engine::markerfree::make(paths),
        "capacity_retry" => engine::capacity::make(paths),
        "structured_rules" => engine::admitted::make_structured_rules(paths),
        "unknown_failure_budget" => engine::admitted::make_unknown_failure_budget(paths),
        "codex_gave_up" => engine::admitted::make_codex_gave_up(paths),
        "sign_in_retry" => engine::admitted::make_sign_in_retry(paths),
        "reset_credit" => engine::credits::make(paths),
        "reset_message" => engine::resetmessage::make(paths),
        "long_reset_message" => engine::resetmessage::make_long(paths),
        "early_reset" => engine::earlyreset::make(paths),
        "once_more_when_unsure" => engine::oncemore::make(paths),
        "send_now" => control::sendnow::make(paths),
        "parallel_dispatch" => engine::parallel::make(paths),
        "prompt_queue" => engine::promptqueue::make(paths),
        "empty_response" => engine::emptyreply::make(paths),
        "subagent_parent" => engine::subagent::make(paths),
        "keep_going" => engine::keepgoing::make(paths),
        "every_conversation" => engine::everyconversation::make(paths),
        "silent_continuation" => engine::silent::make(paths),
        "codex_retry_settings" => engine::retries::make(paths),
        "steer_send" => engine::steer::make(paths),
        "open_to_send" => engine::opentarget::make(paths),
        "open_codex_button" => control::opencodex::make(paths),
        "codex_chat" => engine::chat::make(paths),
        "usage_meter" => engine::usage::make_meter(paths),
        "usage_wrap_up" => engine::usage::make_wrap_up(paths),
        "usage_pause" => engine::usage::make_pause(paths),
        "usage_analytics" => engine::analytics::make(paths),
        "window_anchor" => engine::anchor::make(paths),
        "wake_for_reset" => engine::wake::make(paths),
        "idle_update_check" => engine::updatecheck::make(paths),
        "fleet_view" => engine::fleet::make(paths),
        "power_after_tasks" => engine::powertasks::make(paths),
        "account_switch" => engine::account::make(paths),
        "account_auto_switch" => engine::autoswitch::make(paths),
        "push_notices" => engine::push::make(paths),
        "status_feed" => engine::feed::make(paths),
        "local_api" => engine::remote::make_local_api(paths),
        "telegram_remote" => engine::remote::make_telegram_remote(paths),
        "local_api_actions" | "local_api_lan" | "telegram_continue" => {
            engine::remote::make_widening(paths)
        }
        "stop_hook_continuation" => stophook::make(paths),
        "compat_report" => report::make(paths),
        // D8 / Q1 (a): the definition stays (hidden, waiting), its code is gone.
        "python_choice" => None,
        _ => None,
    }
}

/// Every id [`make`] names, in the registry's order of `registry.py` (the proxy's coverage list, P7-DESIGN 3.4).
pub const MADE: &[&str] = &[
    "start_with_codex",
    "crash_restart",
    "goal_continuation",
    "queue_for_open",
    "compact_continue",
    "model_fallback",
    "headless_run",
    "other_sessions",
    "marker_free_continuation",
    "capacity_retry",
    "structured_rules",
    "unknown_failure_budget",
    "codex_gave_up",
    "sign_in_retry",
    "reset_credit",
    "reset_message",
    "long_reset_message",
    "early_reset",
    "once_more_when_unsure",
    "send_now",
    "parallel_dispatch",
    "prompt_queue",
    "empty_response",
    "subagent_parent",
    "keep_going",
    "every_conversation",
    "silent_continuation",
    "codex_retry_settings",
    "steer_send",
    "open_to_send",
    "open_codex_button",
    "codex_chat",
    "usage_meter",
    "usage_wrap_up",
    "usage_pause",
    "usage_analytics",
    "window_anchor",
    "wake_for_reset",
    "idle_update_check",
    "fleet_view",
    "power_after_tasks",
    "account_switch",
    "account_auto_switch",
    "push_notices",
    "status_feed",
    "local_api",
    "telegram_remote",
    "local_api_actions",
    "local_api_lan",
    "telegram_continue",
    "stop_hook_continuation",
    "compat_report",
    "python_choice",
];

#[cfg(test)]
mod tests {
    use super::MADE;
    use crate::registry;

    /// Every capability the edition can ship (shown, waiting and installed-only) has a row in the `make` table, and
    /// the table names nothing the registry does not define.
    #[test]
    fn the_make_table_covers_the_registry() {
        let mut ids: Vec<String> = registry::definitions()
            .into_iter()
            .chain(
                registry::waiting()
                    .into_iter()
                    .map(|(definition, _)| definition),
            )
            .chain(registry::installed_only())
            .map(|definition| definition.id)
            .collect();
        ids.sort();
        ids.dedup();
        let mut made: Vec<String> = MADE.iter().map(|id| (*id).to_owned()).collect();
        made.sort();
        assert_eq!(ids, made);
    }
}
