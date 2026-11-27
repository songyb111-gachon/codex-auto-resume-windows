//! `empty_response`'s code (seat S7.2e1b; `engine/emptyreply.py`): a turn that ended with no reply is continued once,
//! and a chain of them twice, judged only by the kinds of item it left - at P8 and P2.
//!
//! P8's errand, at most once a minute: the conversations with a turn completed in the last hour, each one's latest turn
//! looked at twice, SECOND_LOOK apart, at least SETTLE_AFTER after it completed and the same both times; a goal Codex
//! keeps going (active) or that its loop guard stopped (blocked) is noted `goal_left`; a chain's third is noted
//! `chain_spent`. P2 hands core every continuation waiting, with its words (`continued::handed`).
//!
//! The seams the continuation family shares (here, as the first of them; keepgoing and subagent use them):
//! * [`Looks`]: what the reference reads of the Codex home - `Turns(home)` (`recent`, `latest`, `between`,
//!   `plan_statuses`), `Goals(home).read`, core's `LocalSource(home).latest` judged with P19's widening, and
//!   `Lineage(home).children`. [`LookWorld::bare`] (what `make(paths)` gives) raises on every read; the entry points
//!   (S7.3d) hand the live one through `make_with`.
//! * [`Words`]: `statement.CATALOGS.text(key, locale, **fields)` - the shipped catalogs, whose directory is the host's
//!   to say (`statement::Catalogs::new`). Bare, no words: nothing is added.
//! * [`Continuations`]: the reference's `ContinuationsHandle` (`state/continuations.py`) over one capability's
//!   `Scoped` - the methods car-adv's `Scoped::handle()` (S7.1a's file) lacks: `on`, `get`, `mine`, `last`, `add`,
//!   `note`, `end`, `kept`, `stop_kept`.

use std::collections::BTreeMap;
use std::sync::{Arc, Mutex, PoisonError};

use car_config::Paths;
use car_machine::json::Value;
use car_policy::plug::{Errand, Guards, HookFailed, View};

use crate::capabilities::{Binding, Code, Raised, Said, Spoke};
use crate::codex::lineage::Child;
use crate::codex::turns::Turn;
use crate::engine::continued::{
    answer_key_text as answer_key, handed as continued_handed, words_pass,
};
use crate::engine::usage::EVERY_CONVERSATION;
use crate::state::errors::Result as StateResult;
use crate::state::scoped::Scoped;
use crate::state::sql::{self, Row};
use crate::vocabulary::{ContinuationKind, ContinuationReason, GoalStatus, RecordState};

pub const CAPABILITY: &str = "empty_response";
/// The kinds an empty turn's items may be, and nothing else: the person's message and Codex's reasoning.
pub const EMPTY_KINDS: [&str; 2] = ["userMessage", "reasoning"];
pub const SETTLE_AFTER: f64 = 10.0;
pub const SECOND_LOOK: f64 = 30.0;
pub const LOOK_EVERY: f64 = 60.0;
pub const RECENT: f64 = 3600.0;
pub const CHAIN_LIMIT: i64 = 2;
pub const WORDS_KEY: &str = "continue.empty_response";
/// How many conversations' first looks are remembered at most, before all are forgotten at once.
pub const SEEN_LIMIT: usize = 256;

// ------------------------------------------------------------------ the family's seams

/// A read of the Codex home that raised (`TurnsUnavailable`, `GoalsUnavailable`, or any other exception: every caller
/// here catches them all, or lets them out of the errand alike).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Unreadable;

/// What the continuation family reads of the Codex home.
pub trait Looks: Send + Sync {
    /// `Turns(home).recent(since)`: the conversations with a turn completed since `since`, newest first.
    fn recent(&self, since: f64) -> Result<Vec<Value>, Unreadable>;
    /// `Turns(home).latest(thread_id)`.
    fn latest(&self, thread_id: &Value) -> Result<Option<Turn>, Unreadable>;
    /// `Turns(home).between(thread_id, after, before)`: how many turns lie strictly between two ordinals.
    fn between(&self, thread_id: &Value, after: &Value, before: &Value) -> Result<i64, Unreadable>;
    /// `Turns(home).plan_statuses(thread_id)`: the newest plan's step statuses, or None where there is no plan.
    fn plan_statuses(&self, thread_id: &Value) -> Result<Option<Vec<String>>, Unreadable>;
    /// `Goals(home).read(thread_id)`: the goal's status word, or None where it has none.
    fn goal(&self, thread_id: &Value) -> Result<Option<String>, Unreadable>;
    /// `LocalSource(home).latest(thread_id) is not None`, the reader's `widened` P19's every_desktop or empty.
    fn own(&self, thread_id: &Value, widened: bool) -> Result<bool, Unreadable>;
    /// `Lineage(home).children(parent)`.
    fn children(&self, parent: &Value) -> Result<Vec<Child>, Unreadable>;
}

/// The Codex home of a code made from `paths` alone is not known here: every read raises.
struct NoLooks;

impl Looks for NoLooks {
    fn recent(&self, _since: f64) -> Result<Vec<Value>, Unreadable> {
        Err(Unreadable)
    }
    fn latest(&self, _thread_id: &Value) -> Result<Option<Turn>, Unreadable> {
        Err(Unreadable)
    }
    fn between(&self, _: &Value, _: &Value, _: &Value) -> Result<i64, Unreadable> {
        Err(Unreadable)
    }
    fn plan_statuses(&self, _thread_id: &Value) -> Result<Option<Vec<String>>, Unreadable> {
        Err(Unreadable)
    }
    fn goal(&self, _thread_id: &Value) -> Result<Option<String>, Unreadable> {
        Err(Unreadable)
    }
    fn own(&self, _thread_id: &Value, _widened: bool) -> Result<bool, Unreadable> {
        Err(Unreadable)
    }
    fn children(&self, _parent: &Value) -> Result<Vec<Child>, Unreadable> {
        Err(Unreadable)
    }
}

/// `statement.CATALOGS.text(name, locale, **fields)`: one entry filled in, or None.
pub type Words = Arc<dyn Fn(&str, Option<&str>, &[(&str, String)]) -> Option<String> + Send + Sync>;

/// The seams a continuation code is made with.
#[derive(Clone)]
pub struct LookWorld {
    pub looks: Arc<dyn Looks>,
    pub words: Words,
}

impl LookWorld {
    /// What `make(paths)` gives: no Codex home, no catalogs.
    pub fn bare() -> LookWorld {
        LookWorld {
            looks: Arc::new(NoLooks),
            words: Arc::new(|_, _, _| None),
        }
    }

    /// `statement.CATALOGS.text(key)` as a value: a text, or None.
    pub fn text(&self, key: &str) -> Value {
        (self.words)(key, None, &[]).map_or(Value::Null, |words| word(&words))
    }
}

/// The reference's `ContinuationsHandle` over one capability's `Scoped`: reads always, writes only while on.
pub struct Continuations<'s, 'a> {
    pub scoped: &'s Scoped<'a>,
}

impl Continuations<'_, '_> {
    pub fn on(&self) -> bool {
        self.scoped.handle().is_on()
    }

    /// `get(key)`: one of its own, or None.
    pub fn get(&self, key: &Value) -> StateResult<Option<Row>> {
        self.scoped.handle().continuation(key)
    }

    /// `mine(thread_id=None, pending=True)`.
    pub fn mine(&self) -> StateResult<Vec<Row>> {
        self.scoped
            .state
            .continuations(&self.scoped.capability, &Value::Null, &Value::Bool(true))
    }

    /// `last(thread_id)`.
    pub fn last(&self, thread_id: &Value) -> StateResult<Option<Row>> {
        self.scoped
            .state
            .last_continuation(thread_id, &self.scoped.capability)
    }

    /// `add(key, kind, thread_id, words, *, ordinal, chain=1)`.
    pub fn add(
        &self,
        key: &Value,
        kind: ContinuationKind,
        thread_id: &Value,
        words: &Value,
        ordinal: &Value,
        chain: &Value,
    ) -> StateResult<bool> {
        self.scoped.handle().continuations_writing()?;
        self.scoped.state.add_continuation(
            key,
            &self.scoped.capability,
            &word(kind.as_str()),
            thread_id,
            words,
            ordinal,
            chain,
            &Value::Null,
        )
    }

    /// `note(key, kind, thread_id, reason, *, ordinal=None, chain=0)`.
    pub fn note(
        &self,
        key: &Value,
        kind: ContinuationKind,
        thread_id: &Value,
        reason: ContinuationReason,
        ordinal: &Value,
        chain: &Value,
    ) -> StateResult<bool> {
        self.scoped.handle().continuations_writing()?;
        self.scoped.state.note_continuation(
            key,
            &self.scoped.capability,
            &word(kind.as_str()),
            thread_id,
            &word(reason.as_str()),
            ordinal,
            chain,
            &Value::Null,
        )
    }

    /// `end(reason, *, thread_id=None)`.
    pub fn end(&self, reason: ContinuationReason, thread_id: &Value) -> StateResult<i64> {
        self.scoped.handle().continuations_writing()?;
        self.scoped.state.end_continuations(
            &word(reason.as_str()),
            &self.scoped.capability,
            thread_id,
            &Value::Null,
        )
    }

    /// `kept()`: every conversation kept going (keep_going's own).
    pub fn kept(&self) -> StateResult<Vec<Row>> {
        Ok(match self.scoped.state.keep_going(&Value::Null)? {
            Value::Array(rows) => rows
                .into_iter()
                .filter_map(|row| match row {
                    Value::Object(row) => Some(row),
                    _ => None,
                })
                .collect(),
            _ => Vec::new(),
        })
    }

    /// `stop_kept(reason, *, thread_id=None)`.
    pub fn stop_kept(&self, reason: &str, thread_id: &Value) -> StateResult<i64> {
        self.scoped.handle().continuations_writing()?;
        self.scoped
            .state
            .stop_keep_going(&word(reason), thread_id, &Value::Null)
    }
}

pub(crate) fn word(text: &str) -> Value {
    Value::Str(text.into())
}

/// An int of Python's from a turn's ordinal.
pub(crate) fn int(number: i128) -> Value {
    match i64::try_from(number) {
        Ok(small) => Value::from(small),
        Err(_) => {
            Value::Int(car_machine::json::Int::parse(&number.to_string()).unwrap_or(0.into()))
        }
    }
}

/// A conversation's key in a memory of looks: its text (`str(thread)`).
pub(crate) fn thread_key(thread: &Value) -> String {
    match thread {
        Value::Str(text) => text.as_str().unwrap_or_default().to_owned(),
        other => crate::state::py::py_str(other),
    }
}

/// `str(part)` of a conversation or turn id handed `answer_key`.
pub(crate) fn part(value: &Value) -> String {
    match value {
        Value::Null => "None".to_owned(),
        other => thread_key(other),
    }
}

/// `answer_key(*parts)` as the value a continuation is keyed by.
pub(crate) fn key_of(parts: &[String]) -> Value {
    word(&answer_key(parts))
}

/// `view.thread_enabled(thread)`: None where it raised.
pub(crate) fn enabled(view: &dyn View, thread: &Value) -> Option<bool> {
    view.thread_enabled(&thread_key(thread)).ok()
}

/// `self._scoped.count(code)`, its failure swallowed.
pub(crate) fn count(scoped: &Scoped<'_>, code: &str) {
    let _ = scoped.count(&word(code));
}

/// `self._scoped.armed(EVERY_CONVERSATION) is True`: P19's widening of core's reader.
pub(crate) fn widened(scoped: &Scoped<'_>) -> bool {
    scoped.armed(&word(EVERY_CONVERSATION))
}

/// P2 of every continuation capability: each of its continuations waiting, with its words, or DEFER.
pub(crate) fn waiting_records(binding: Option<&Binding>) -> Spoke {
    let Some(binding) = binding else {
        return Ok(Said::Defer);
    };
    let found = binding.with(|scoped| {
        let rows = Continuations { scoped }.mine().ok()?;
        let records: Vec<Value> = rows
            .into_iter()
            .filter(is_waiting)
            .filter_map(|row| continued_handed(&Value::Object(row)))
            .collect();
        Some(records)
    });
    Ok(match found.flatten() {
        Some(records) if !records.is_empty() => Said::Value(Value::Array(records)),
        _ => Said::Defer,
    })
}

pub(crate) fn is_waiting(row: &Row) -> bool {
    sql::py_eq(
        sql::get(row, "record_state"),
        &word(RecordState::Waiting.as_str()),
    )
}

/// `_not_own` / `_not_taken`: a continuation waiting for a conversation core does not take for one it recovers, ended
/// (withdrawn). The reference walks a set of the conversations (hash order); here they go in the order first met - the
/// same ends, the same reads (AUDIT-v0628.md).
pub(crate) fn withdraw_not_own(handle: &Continuations<'_, '_>, looks: &dyn Looks, widened: bool) {
    let Ok(rows) = handle.mine() else {
        return;
    };
    let mut waiting: Vec<Value> = Vec::new();
    for row in rows.iter().filter(|row| is_waiting(row)) {
        let thread = sql::get(row, "thread_id").clone();
        if !waiting.iter().any(|seen| sql::py_eq(seen, &thread)) {
            waiting.push(thread);
        }
    }
    for thread in waiting {
        if let Ok(false) = looks.own(&thread, widened) {
            let _ = handle.end(ContinuationReason::Withdrawn, &thread);
        }
    }
}

/// `{kind: count}` as `dict(turn.kinds)` holds it: the last count of a kind met twice wins; sorted by kind.
pub(crate) fn kinds_of(turn: &Turn) -> BTreeMap<String, i64> {
    crate::codex::turns::kinds_map(&turn.kinds)
}

/// `empty(turn)`: completed, no error, no final agent item, a message of the person's and nothing but EMPTY_KINDS.
pub fn empty(turn: Option<&Turn>) -> bool {
    let Some(turn) = turn else {
        return false;
    };
    let kinds = kinds_of(turn);
    turn.status == "completed"
        && !turn.errored
        && !turn.final_agent
        && turn.completed_at.is_some()
        && kinds.get("userMessage").copied().unwrap_or(0) > 0
        && kinds
            .keys()
            .all(|kind| EMPTY_KINDS.contains(&kind.as_str()))
}

// ------------------------------------------------------------------ the code

type Shape = (String, Vec<(String, i64)>);

#[derive(Default)]
struct Memory {
    seen: BTreeMap<String, (Shape, f64)>,
    looked: Option<f64>,
}

/// A second hold of the same binding (for an errand, which outlives the hook).
pub(crate) fn rebind(binding: &Binding) -> Binding {
    Binding {
        runtime: binding.runtime.clone(),
        capability: binding.capability.clone(),
    }
}

/// Whether a look `LOOK_EVERY` apart is due: never looked, or the clock moved back, or a minute passed.
pub(crate) fn due(looked: Option<f64>, now: f64, every: f64) -> bool {
    !looked.is_some_and(|looked| (0.0..every).contains(&(now - looked)))
}

/// `EmptyResponse(paths, home=None)`.
pub struct EmptyResponse {
    pub paths: Paths,
    binding: Option<Binding>,
    world: LookWorld,
    memory: Arc<Mutex<Memory>>,
}

/// `_Errand`: the look, run last in the tick.
struct Look {
    binding: Binding,
    world: LookWorld,
    memory: Arc<Mutex<Memory>>,
}

impl Errand for Look {
    fn run(
        &self,
        view: &dyn View,
        _guards: &mut Guards<'_>,
    ) -> std::result::Result<Value, HookFailed> {
        match self.binding.with(|scoped| self.look(scoped, view)) {
            Some(Err(_)) => Err(HookFailed),
            _ => Ok(Value::Null),
        }
    }
}

impl Look {
    /// `look(view)`: the conversations that finished a turn lately, each one's latest turn looked at. Err is a raise
    /// out of the errand (a write or a read of its own state that failed).
    fn look(&self, scoped: &Scoped<'_>, view: &dyn View) -> StateResult<()> {
        let handle = Continuations { scoped };
        if !handle.on() {
            return Ok(());
        }
        let now = scoped.now();
        let mut memory = self.memory.lock().unwrap_or_else(PoisonError::into_inner);
        memory.looked = Some(now);
        let looks = self.world.looks.as_ref();
        let Ok(candidates) = looks.recent(now - RECENT) else {
            return Ok(());
        };
        let wide = widened(scoped);
        withdraw_not_own(&handle, looks, wide);
        if memory.seen.len() > SEEN_LIMIT {
            memory.seen.clear();
        }
        for thread in candidates {
            if enabled(view, &thread) != Some(true) || !matches!(looks.own(&thread, wide), Ok(true))
            {
                continue;
            }
            let Ok(turn) = looks.latest(&thread) else {
                continue;
            };
            let name = thread_key(&thread);
            let turn = match turn {
                Some(turn) if empty(Some(&turn)) => turn,
                _ => {
                    memory.seen.remove(&name);
                    continue;
                }
            };
            let completed = turn.completed_at.unwrap_or_default() as f64;
            if now - completed < SETTLE_AFTER {
                memory.seen.remove(&name);
                continue;
            }
            let shape: Shape = (turn.turn_id.clone(), kinds_of(&turn).into_iter().collect());
            let first = match memory.seen.get(&name) {
                Some((held, at)) if *held == shape => *at,
                _ => {
                    memory.seen.insert(name, (shape, now));
                    continue;
                }
            };
            if now - first < SECOND_LOOK {
                continue;
            }
            memory.seen.remove(&name);
            self.answer(scoped, &handle, &thread, &turn)?;
        }
        Ok(())
    }

    fn answer(
        &self,
        scoped: &Scoped<'_>,
        handle: &Continuations<'_, '_>,
        thread: &Value,
        turn: &Turn,
    ) -> StateResult<()> {
        let key = key_of(&[CAPABILITY.to_owned(), part(thread), turn.turn_id.clone()]);
        if handle.get(&key)?.is_some() {
            return Ok(());
        }
        let Ok(goal) = self.world.looks.goal(thread) else {
            return Ok(());
        };
        let ordinal = int(turn.ordinal);
        if goal.is_some_and(|status| {
            status == GoalStatus::Active.as_str() || status == GoalStatus::Blocked.as_str()
        }) {
            if handle.note(
                &key,
                ContinuationKind::EmptyResponse,
                thread,
                ContinuationReason::GoalLeft,
                &ordinal,
                &Value::from(0),
            )? {
                count(scoped, "goal_left");
            }
            return Ok(());
        }
        let Some(chain) = self.chain(handle, thread, turn)? else {
            return Ok(());
        };
        if chain > CHAIN_LIMIT {
            if handle.note(
                &key,
                ContinuationKind::EmptyResponse,
                thread,
                ContinuationReason::ChainSpent,
                &ordinal,
                &Value::from(chain),
            )? {
                count(scoped, "chain_spent");
            }
            return Ok(());
        }
        let words = self.world.text(WORDS_KEY);
        if !words_pass(&words) {
            return Ok(());
        }
        if handle.add(
            &key,
            ContinuationKind::EmptyResponse,
            thread,
            &words,
            &ordinal,
            &Value::from(chain),
        )? {
            count(scoped, "found");
        }
        Ok(())
    }

    /// `_chain`: 1, or one more than the delivered continuation `turn` is the very next turn after. None where that
    /// cannot be read.
    fn chain(
        &self,
        handle: &Continuations<'_, '_>,
        thread: &Value,
        turn: &Turn,
    ) -> StateResult<Option<i64>> {
        let Some(last) = handle.last(thread)? else {
            return Ok(Some(1));
        };
        let ordinal = sql::get(&last, "ordinal");
        let delivered = sql::py_eq(
            sql::get(&last, "reason"),
            &word(ContinuationReason::Delivered.as_str()),
        );
        let before = match ordinal {
            Value::Int(held) => held
                .to_string()
                .parse::<i128>()
                .ok()
                .filter(|held| *held < turn.ordinal),
            _ => None,
        };
        if matches!(sql::get(&last, "record_id"), Value::Null) || !delivered || before.is_none() {
            return Ok(Some(1));
        }
        let Ok(between) = self
            .world
            .looks
            .between(thread, ordinal, &int(turn.ordinal))
        else {
            return Ok(None);
        };
        if between != 0 {
            return Ok(Some(1));
        }
        match sql::get(&last, "chain") {
            Value::Int(chain) => Ok(chain.as_i64().map(|chain| chain + 1)),
            _ => Err(crate::state::errors::Error::Python(
                "TypeError",
                "unsupported operand type(s) for +".to_owned(),
            )),
        }
    }
}

impl EmptyResponse {
    pub fn new(paths: Paths, world: LookWorld) -> EmptyResponse {
        EmptyResponse {
            paths,
            binding: None,
            world,
            memory: Arc::new(Mutex::new(Memory::default())),
        }
    }
}

impl Code for EmptyResponse {
    fn bind(&mut self, binding: Binding) -> Option<std::result::Result<(), Raised>> {
        self.binding = Some(binding);
        Some(Ok(()))
    }

    /// P8: the look, at most once a minute.
    fn tick(&mut self, _view: &dyn View) -> Spoke {
        let Some(binding) = &self.binding else {
            return Ok(Said::Defer);
        };
        let Some(now) = binding.with(|scoped| scoped.now()) else {
            return Ok(Said::Defer);
        };
        let looked = self
            .memory
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
            .looked;
        if !due(looked, now, LOOK_EVERY) {
            return Ok(Said::Defer);
        }
        Ok(Said::Errand(Box::new(Look {
            binding: rebind(binding),
            world: self.world.clone(),
            memory: self.memory.clone(),
        })))
    }

    /// P2: every continuation of this capability waiting, with its words.
    fn records(&mut self, _view: &dyn View) -> Spoke {
        waiting_records(self.binding.as_ref())
    }
}

/// `make(paths)`: the capability's code with the world a code made from `paths` alone has.
pub fn make(paths: &Paths) -> Option<Box<dyn Code>> {
    make_with(paths, LookWorld::bare())
}

/// `EmptyResponse(paths, home=...)` with an entry point's or a test's own world.
pub fn make_with(paths: &Paths, world: LookWorld) -> Option<Box<dyn Code>> {
    Some(Box::new(EmptyResponse::new(paths.clone(), world)))
}
