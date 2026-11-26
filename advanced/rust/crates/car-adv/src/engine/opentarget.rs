//! `open_to_send`'s code (seat S7.2e1b; `engine/opentarget.py`): a recovery or a scheduled message that waits only
//! because the Codex app does not have its conversation open gets that exact conversation opened, once, through Codex's
//! own link - at P8, as an errand, inside core's errand guard.
//!
//! A candidate is core's record whose last gate vector fails thread_available alone (notLoaded; with Also start Codex,
//! also the app closed), one queue_for_open queued in Codex that the app does not hold now, or a message of the edition's
//! own waiting at that gate. It opens only while the PC has been idle the minutes chosen, Windows has a `codex:` handler
//! and the app runs (unless Also start Codex), within the caps kept in the state (`opens`). The next looks settle each
//! open: loaded, or not_loaded after LOOKS looks.
//!
//! Its seams ([`OpenWorld`]): the idle time (core's `win/powerdown.idle_seconds`), the `codex:` handler
//! (`control/opencodex.handler_registered`, S7.3a's), the app running (core's `codex/pairing.app_running_now`), the link
//! handed to Windows (core's `codex_link`), and the app's hold of one conversation (`inuse.backend(paths).loaded`).

use std::collections::{BTreeMap, BTreeSet};
use std::sync::{Arc, Mutex, PoisonError};

use car_config::Paths;
use car_machine::json::Value;
use car_machine::vocab_gen::domain_states as states;
use car_policy::classify::gates::{PASS, UNKNOWN, WAIT, decode_gates};
use car_policy::plug::{Errand, Guards, HookFailed, View};

use super::emptyreply::{rebind, word};
use crate::capabilities::{Binding, Code, Raised, Said, Spoke};
use crate::state::scoped::Scoped;
use crate::state::sql::{self, Row};
use crate::vocabulary::{
    OpenOutcome, OptionKey, PromptReason, PromptState, RecordState, RuleState,
};

pub const CAPABILITY: &str = "open_to_send";
pub const IDLE_MINUTES: [i64; 3] = [2, 5, 15];
pub const DEFAULT_IDLE: i64 = 5;
pub const ON: i64 = 1;
pub const OFF: i64 = 2;
pub const GAP: f64 = 600.0;
pub const PER_CONVERSATION: f64 = 3600.0;
pub const PER_RECORD: usize = 3;
pub const PER_DAY: usize = 24;
pub const DAY: f64 = 86400.0;
/// How many looks after an open still find its record waiting for the conversation before it is not_loaded.
pub const LOOKS: i64 = 2;
pub const NOT_LOADED: &str = "notLoaded";
pub const APP_CLOSED: &str = "desktop_app_unavailable";
pub const GATE: &str = "thread_available";
pub const RESET_MESSAGE: &str = "reset_message";
const NOT_CHECKED: &str = "not_checked";

/// Core's records that may be candidates: waiting, and those a queue item holds (queue_for_open's).
pub fn looked_at() -> Vec<&'static str> {
    states::WAITING
        .iter()
        .chain(states::IN_FLIGHT)
        .chain(states::OBSERVING)
        .chain(states::CLAIMED)
        .copied()
        .collect()
}

/// `record_of(kind, identity)`: the 64-hex record id an open is kept under - the edition's own record id as it is, a
/// digest of core's interruption id.
pub fn record_of(kind: &str, identity: &Value) -> String {
    if kind != "core"
        && let Value::Str(text) = identity
        && text.len() == 64
        && let Some(text) = text.as_str()
    {
        return text.to_owned();
    }
    let shown = super::emptyreply::thread_key(identity);
    car_machine::hash::sha256(format!("{kind}:{shown}").as_bytes())
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect()
}

fn text_of<'a>(row: &'a Row, name: &str) -> Option<&'a str> {
    match sql::get(row, name) {
        Value::Str(text) => text.as_str(),
        _ => None,
    }
}

/// `core_candidate(row, start_codex)`: "for_open", "waiting", or None.
pub fn core_candidate(row: &Value, start_codex: bool) -> Option<&'static str> {
    let Value::Object(row) = row else {
        return None;
    };
    match car_engine::Engine::for_open(row) {
        Ok(true) => return Some("for_open"),
        Ok(false) => {}
        Err(_) => return None,
    }
    if !text_of(row, "state").is_some_and(|state| states::WAITING.contains(&state)) {
        return None;
    }
    let gates = decode_gates(sql::get(row, "gate_eval"));
    let wanted = |gate: &(String, String)| {
        gate.0 == WAIT && (gate.1 == NOT_LOADED || (start_codex && gate.1 == APP_CLOSED))
    };
    if !gates.get(GATE).is_some_and(wanted) {
        return None;
    }
    for (name, (result, reason)) in &gates.0 {
        if name != GATE && result != PASS && !(result == UNKNOWN && reason == NOT_CHECKED) {
            return None;
        }
    }
    Some("waiting")
}

/// `own_candidate(row, start_codex)`: a message of the edition's own waiting for its conversation to be opened alone.
pub fn own_candidate(row: &Row, start_codex: bool) -> bool {
    let reason = text_of(row, "gate_reason");
    text_of(row, "record_state") == Some(RecordState::Waiting.as_str())
        && text_of(row, "gate") == Some(GATE)
        && reason
            .is_some_and(|reason| reason == NOT_LOADED || (start_codex && reason == APP_CLOSED))
        && text_of(row, "reason") != Some(PromptReason::TurnRunning.as_str())
}

/// A look at one conversation (`thread`) a seam answers.
pub type ThreadLook<T> = Arc<dyn Fn(&Value) -> T + Send + Sync>;

/// The seams the code is made with.
#[derive(Clone)]
pub struct OpenWorld {
    /// `idle_seconds()`: seconds since anybody last used the PC, or None.
    pub idle_seconds: Arc<dyn Fn() -> Option<f64> + Send + Sync>,
    /// `handler_registered()`.
    pub handler_registered: Arc<dyn Fn() -> bool + Send + Sync>,
    /// `app_running()`: True, False, or None where it cannot be read.
    pub app_running: Arc<dyn Fn() -> Option<bool> + Send + Sync>,
    /// `open_link(thread_id)`: whether the link was handed; Err where it raised.
    pub open_link: ThreadLook<Result<bool, ()>>,
    /// `app_holds(paths, thread)`: True, False, or None where that cannot be told.
    pub app_holds: ThreadLook<Option<bool>>,
}

impl OpenWorld {
    /// What `make(paths)` gives: nothing known of the PC or the app - no idle time (never opens), no handler.
    pub fn bare() -> OpenWorld {
        OpenWorld {
            idle_seconds: Arc::new(|| None),
            handler_registered: Arc::new(|| false),
            app_running: Arc::new(|| None),
            open_link: Arc::new(|_| Ok(false)),
            app_holds: Arc::new(|_| None),
        }
    }
}

impl crate::seam_p7::OpenTarget for OpenWorld {
    fn idle_seconds(&self) -> Option<f64> {
        (self.idle_seconds)()
    }
}

/// An open not settled yet: its kind, its identity, the looks since.
type Pending = BTreeMap<i64, (String, Value, i64)>;

#[derive(Default)]
struct Memory {
    pending: Pending,
    for_open: BTreeSet<String>,
}

type Candidate = (String, Value, Value);

fn start_codex(options: &Row) -> bool {
    car_machine::pyval::eq(
        options
            .get(OptionKey::OpenStartCodex.as_str())
            .unwrap_or(&Value::Null),
        &Value::from(ON),
    )
}

/// `candidates(view, start_codex)`: every candidate now, oldest first - core's records first, then the queued prompts
/// and the reset messages. Notes which of core's are queued for open.
fn candidates(
    scoped: &Scoped<'_>,
    view: &dyn View,
    start: bool,
    memory: &mut Memory,
) -> Vec<Candidate> {
    let mut found = Vec::new();
    memory.for_open.clear();
    if let Ok(rows) = view.records_in(&looked_at()) {
        for row in rows {
            let Some(kind) = core_candidate(&row, start) else {
                continue;
            };
            let Value::Object(map) = &row else {
                continue;
            };
            let key = sql::get(map, "interruption_id").clone();
            found.push((
                "core".to_owned(),
                key.clone(),
                sql::get(map, "thread_id").clone(),
            ));
            if kind == "for_open" {
                memory.for_open.insert(super::emptyreply::thread_key(&key));
            }
        }
    }
    if let Ok(rows) = scoped.state.prompts(&Value::Null, &Value::Bool(true)) {
        for row in rows {
            if text_of(&row, "state") == Some(PromptState::Ready.as_str())
                && sql::truthy(sql::get(&row, "record_id"))
                && own_candidate(&row, start)
            {
                found.push((
                    "prompt".to_owned(),
                    sql::get(&row, "record_id").clone(),
                    sql::get(&row, "thread_id").clone(),
                ));
            }
        }
    }
    if let Ok(rows) = scoped
        .state
        .reset_rules(&word(RESET_MESSAGE), &Value::Bool(true))
    {
        for row in rows {
            if text_of(&row, "state") == Some(RuleState::Ready.as_str())
                && sql::truthy(sql::get(&row, "record_id"))
                && own_candidate(&row, start)
            {
                found.push((
                    "reset".to_owned(),
                    sql::get(&row, "record_id").clone(),
                    sql::get(&row, "thread_id").clone(),
                ));
            }
        }
    }
    found
}

fn number(value: &Value) -> Option<f64> {
    match value {
        Value::Int(int) => int.as_i64().map(|int| int as f64),
        Value::Float(number) => Some(*number),
        Value::Bool(flag) => Some(f64::from(u8::from(*flag))),
        _ => None,
    }
}

/// `OpenTarget(paths)`.
pub struct OpenTarget {
    pub paths: Paths,
    binding: Option<Binding>,
    world: OpenWorld,
    memory: Arc<Mutex<Memory>>,
}

struct Look {
    binding: Binding,
    world: OpenWorld,
    memory: Arc<Mutex<Memory>>,
}

impl Errand for Look {
    fn run(&self, view: &dyn View, guards: &mut Guards<'_>) -> Result<Value, HookFailed> {
        match self.binding.with(|scoped| self.look(scoped, view, guards)) {
            Some(Err(())) => Err(HookFailed),
            _ => Ok(Value::Null),
        }
    }
}

impl Look {
    /// `look(view, guard)`: Err is a raise out of the errand.
    fn look(
        &self,
        scoped: &Scoped<'_>,
        view: &dyn View,
        guards: &mut Guards<'_>,
    ) -> Result<(), ()> {
        let handle = scoped.handle();
        if !handle.is_on() {
            return Ok(());
        }
        let options = scoped.options().map_err(|_| ())?;
        let start = start_codex(&options);
        let mut memory = self.memory.lock().unwrap_or_else(PoisonError::into_inner);
        let found = candidates(scoped, view, start, &mut memory);
        let now = scoped.now();
        settle(scoped, &mut memory, &found);
        let made: Vec<Row> = scoped
            .state
            .opens(&Value::from(0))
            .map_err(|_| ())?
            .into_iter()
            .filter(|row| text_of(row, "outcome") != Some(OpenOutcome::Refused.as_str()))
            .collect();
        let at = |row: &Row| number(sql::get(row, "at")).ok_or(());
        let mut today = 0usize;
        for row in &made {
            if at(row)? > now - DAY {
                today += 1;
            }
        }
        if today >= PER_DAY {
            return Ok(());
        }
        for row in &made {
            if now - at(row)? < GAP {
                return Ok(());
            }
        }
        let mut chosen = None;
        'found: for (kind, identity, thread) in &found {
            let record = record_of(kind, identity);
            let same = made
                .iter()
                .filter(|row| text_of(row, "record_id") == Some(record.as_str()))
                .count();
            if same >= PER_RECORD {
                continue;
            }
            for row in &made {
                if sql::py_eq(sql::get(row, "thread_id"), thread)
                    && now - at(row)? < PER_CONVERSATION
                {
                    continue 'found;
                }
            }
            if kind == "core"
                && memory
                    .for_open
                    .contains(&super::emptyreply::thread_key(identity))
                && (self.world.app_holds)(thread) != Some(false)
            {
                continue;
            }
            chosen = Some((kind.clone(), identity.clone(), thread.clone(), record));
            break;
        }
        let Some((kind, identity, thread, record)) = chosen else {
            return Ok(());
        };
        let idle = (self.world.idle_seconds)();
        let minutes = options
            .get(OptionKey::OpenIdleMinutes.as_str())
            .cloned()
            .unwrap_or(Value::from(DEFAULT_IDLE));
        let minutes = number(&minutes).ok_or(())?;
        if idle.is_none_or(|idle| idle < 60.0 * minutes) || !(self.world.handler_registered)() {
            return Ok(());
        }
        if !start && (self.world.app_running)() != Some(true) {
            return Ok(());
        }
        handle.table_writing().map_err(|_| ())?;
        let opened = scoped
            .state
            .add_open(&thread, &word(&record), &Value::Float(now))
            .map_err(|_| ())?;
        let link = self.world.open_link.clone();
        let mut handed = false;
        let mut body = |permitted: bool| {
            handed = permitted && matches!(link(&thread), Ok(true));
            Value::Null
        };
        guards(&mut body).map_err(|_| ())?;
        if !handed {
            handle.table_writing().map_err(|_| ())?;
            scoped
                .state
                .settle_open(&Value::from(opened), &word(OpenOutcome::Refused.as_str()))
                .map_err(|_| ())?;
            return Ok(());
        }
        memory.pending.insert(opened, (kind, identity, 0));
        let _ = scoped.count(&word("opened"));
        Ok(())
    }
}

/// `_settle(handle, found)`: each open not settled yet, looked at again.
fn settle(scoped: &Scoped<'_>, memory: &mut Memory, found: &[Candidate]) {
    let waiting = |kind: &str, identity: &Value| {
        found
            .iter()
            .any(|(held, key, _)| held == kind && sql::py_eq(key, identity))
    };
    let opened: Vec<i64> = memory.pending.keys().copied().collect();
    for open in opened {
        let Some((kind, identity, looks)) = memory.pending.get(&open).cloned() else {
            continue;
        };
        let (outcome, code) = if !waiting(&kind, &identity) {
            (OpenOutcome::Loaded, "loaded")
        } else if looks + 1 >= LOOKS {
            (OpenOutcome::NotLoaded, "not_loaded")
        } else {
            if let Some(entry) = memory.pending.get_mut(&open) {
                entry.2 = looks + 1;
            }
            continue;
        };
        memory.pending.remove(&open);
        let settled = scoped.handle().table_writing().and_then(|()| {
            scoped
                .state
                .settle_open(&Value::from(open), &word(outcome.as_str()))
        });
        if settled.is_err() {
            continue;
        }
        let _ = scoped.count(&word(code));
    }
}

impl OpenTarget {
    pub fn new(paths: Paths, world: OpenWorld) -> OpenTarget {
        OpenTarget {
            paths,
            binding: None,
            world,
            memory: Arc::new(Mutex::new(Memory::default())),
        }
    }
}

impl Code for OpenTarget {
    fn bind(&mut self, binding: Binding) -> Option<Result<(), Raised>> {
        self.binding = Some(binding);
        Some(Ok(()))
    }

    /// P8: the errand, where there is an open to settle or a candidate.
    fn tick(&mut self, view: &dyn View) -> Spoke {
        let Some(binding) = &self.binding else {
            return Ok(Said::Defer);
        };
        let wanted = binding.with(|scoped| {
            let options = scoped.options().ok()?;
            let start = start_codex(&options);
            let mut memory = self.memory.lock().unwrap_or_else(PoisonError::into_inner);
            Some(
                !memory.pending.is_empty()
                    || !candidates(scoped, view, start, &mut memory).is_empty(),
            )
        });
        if wanted.flatten() != Some(true) {
            return Ok(Said::Defer);
        }
        Ok(Said::Errand(Box::new(Look {
            binding: rebind(binding),
            world: self.world.clone(),
            memory: self.memory.clone(),
        })))
    }
}

/// `make(paths)`: the capability's code with the world a code made from `paths` alone has.
pub fn make(paths: &Paths) -> Option<Box<dyn Code>> {
    make_with(paths, OpenWorld::bare())
}

/// `OpenTarget(paths)` with an entry point's or a test's own world.
pub fn make_with(paths: &Paths, world: OpenWorld) -> Option<Box<dyn Code>> {
    Some(Box::new(OpenTarget::new(paths.clone(), world)))
}
