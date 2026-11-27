//! `arming.py`: who may turn a capability on, who may turn it off, and what turns it off by itself.
//!
//! Every capability starts off, and stays off until a person turns it on, one at a time, in the Dashboard, after its
//! statement. `arm` takes an actor and refuses every actor but the Dashboard; `disarm` and `all_off` take any actor that is a
//! surface and need nothing. What a capability is at this moment (`standing`) is its stored state as seen through what has
//! happened since: the tripwires turn it off, a new Codex turns an armed one off, a policy only reads it down. Keep on (K8)
//! notes in place of turning off; Send again sends a continuation once more under the once-more capability's rules.
//!
//! The decisions are pure functions (`engine_version`, `compat_warning`, `warnings_for`, `standing`, `departs`,
//! `offers_send_again`, `kept_words`, `held_word` and the helpers under them) and the stateful `Arming`, which reaches the
//! advanced state through `seam::StatePort` and the engine and control modules through `seam::Edges`. The words a request
//! carries are JSON values (`serde`-free: car-machine's `Value`), as the wire hands them, so a request of the wrong type is
//! refused the way the tag refuses it. Every method makes the same calls of the state and the edges, in the same order, as
//! the tag's: the diffs hold the whole call log equal.

use std::cell::{Cell, RefCell};
use std::collections::{BTreeMap, BTreeSet};

use car_machine::json::Value;
use car_policy::plug::Point;

use crate::autocheck::{self, Results, Settled};
use crate::jsonx::{int, maybe_int, maybe_text, object, text, texts};
use crate::measured::Table;
use crate::policy::{self, Policy};
use crate::registry::{CapabilityDef, GLOBAL_HOURLY, Registry, shown as shown_in_order};
use crate::seam::{
    ACCOUNT_CAPABILITY, ArmRow, CREDIT, ContinuationRow, DAY, Edges, HOOK_CAPABILITY, METER, Meta,
    Move, PAUSE, POWER_TASKS_CAPABILITY, PROMPT_QUEUE, RECENT_DAYS, RULES_LIMIT, STEER_SEND,
    StateFault, StatePort, StateResult, Unavailable, WRAP_UP,
};
use crate::statement::{Catalogs, Undecodable};
use crate::vocabulary::{
    Actor, ArmingState, ArmingWarning, AutoResult, CapabilityKind, ContinuationReason,
    KEPT_NOTICES, KeepOn, Measurement, OffReason, OptionKey, OverrideKind, PromptReason,
    RecordState, Refusal, RuleReason, RuleState, SteerReason, TRIPWIRES, Verdict, WordingKey,
    parse,
};

/// The actors a person turns a capability off through.
pub const SURFACES: [Actor; 4] = [Actor::Dashboard, Actor::Mcp, Actor::Tray, Actor::Card];
/// What the state of a capability in core's store is when a send it paid for may or may not have reached Codex.
pub const SUBMISSION_UNKNOWN: &str = "submission_unknown";
/// How far apart a unit's time and a claim's may be and still be the one claim.
pub const SAME_CLAIM: f64 = 0.001;
/// What core writes into a record it sent once more whose proof is then found twice.
pub const DUPLICATE: &str = "duplicate_marker";
/// How long a resend is watched for a second copy: core's own window for an uncertain one.
pub const RESEND_WATCH: f64 = 86_400.0;
/// The warnings that, appearing where the person did not confirm them, trip a capability, with their reasons.
pub const TRIPPING: [(ArmingWarning, OffReason); 5] = [
    (ArmingWarning::FailedHere, OffReason::FailedHere),
    (ArmingWarning::LocalCheckFailed, OffReason::LocalCheckFailed),
    (ArmingWarning::Incompatible, OffReason::Incompatible),
    (
        ArmingWarning::MeasurementFailed,
        OffReason::MeasurementFailed,
    ),
    (ArmingWarning::AutoCheckFailed, OffReason::AutoCheckFailed),
];

// ------------------------------------------------------------------------------------------------ the view's words
/// `engine_version(view)`: the version of the Codex the view names, or `None`.
pub fn engine_version(view: &Value) -> Option<String> {
    let Value::Object(view) = view else {
        return None;
    };
    let Some(Value::Object(engine)) = view.get("engine") else {
        return None;
    };
    match engine.get("version") {
        Some(Value::Str(version)) => version.as_str().map(str::to_owned),
        _ => None,
    }
}

fn is_state_word(word: &str) -> bool {
    car_machine::vocab_gen::compat_model::STATES.contains(&word)
}

/// `compat_warning(view, definition)`: the warning the Compatibility Registry's view gives for what `definition` stands on, or
/// `None` for a grade of COMPATIBLE or better. A view that cannot be read is UNKNOWN. An action stands on nothing of Codex's.
pub fn compat_warning(view: &Value, definition: &CapabilityDef) -> Option<ArmingWarning> {
    let compat = definition.compat.as_deref()?;
    let entry = match view {
        Value::Object(view) => match view.get("capabilities") {
            Some(Value::Object(capabilities)) => capabilities.get(compat),
            _ => None,
        },
        _ => None,
    };
    let entry_map = match entry {
        Some(Value::Object(map)) => Some(map),
        _ => None,
    };
    // `state = entry.get("state") if isinstance(entry, dict) else UNKNOWN`
    let state: Option<&Value> = entry_map.and_then(|map| map.get("state"));
    let word = match (entry_map, state) {
        (None, _) => Some("UNKNOWN"),
        (Some(_), Some(Value::Str(held))) => held.as_str(),
        (Some(_), _) => None,
    };
    match word {
        Some("FAILED_HERE") => Some(ArmingWarning::FailedHere),
        Some("INCOMPATIBLE") => {
            let reason = entry_map.and_then(|map| map.get("reason"));
            let local = matches!(reason, Some(Value::Str(held)) if held.as_str() == Some("local_check_failed"));
            Some(if local {
                ArmingWarning::LocalCheckFailed
            } else {
                ArmingWarning::Incompatible
            })
        }
        // `state == UNKNOWN or state not in STATES`: a word the vocabulary does not hold, or no text at all.
        Some("UNKNOWN") => Some(ArmingWarning::CompatUnknown),
        Some(held) if !is_state_word(held) => Some(ArmingWarning::CompatUnknown),
        None => Some(ArmingWarning::CompatUnknown),
        Some(_) => None,
    }
}

/// `_rests_on(definition, parts=)`: the measurements `definition`'s statement warns of: its route's, and with `parts` those
/// only a part rests on.
pub fn rests_on(definition: &CapabilityDef, parts: bool) -> Vec<Measurement> {
    let mut found = definition.measurements.clone();
    if parts {
        found.extend(definition.narrowed_by.iter().copied());
    }
    found
}

/// `warnings_for(definition, view, measured, parts=, checked=)`: every warning `definition`'s statement shows now, in the
/// vocabulary's order. Pure.
pub fn warnings_for(
    definition: &CapabilityDef,
    view: &Value,
    measured: &Table,
    parts: bool,
    checked: &Results,
) -> Vec<ArmingWarning> {
    let version = engine_version(view);
    let mut found: BTreeSet<ArmingWarning> = BTreeSet::new();
    for measurement in rests_on(definition, parts) {
        match autocheck::settled(measurement, version.as_deref(), measured, checked) {
            Settled::Failed => {
                found.insert(ArmingWarning::MeasurementFailed);
                if checked.get(&measurement) == Some(&AutoResult::Fail) {
                    found.insert(ArmingWarning::AutoCheckFailed);
                }
            }
            Settled::Gone => {
                found.insert(ArmingWarning::AutoCheckFailed);
            }
            Settled::Unsettled => {
                found.insert(ArmingWarning::Unmeasured);
            }
            Settled::Here | Settled::StandsIn => {}
        }
    }
    if let Some(warning) = compat_warning(view, definition) {
        found.insert(warning);
    }
    if version.is_none() {
        found.insert(ArmingWarning::EngineUnknown);
    }
    ArmingWarning::ALL
        .iter()
        .copied()
        .filter(|warning| found.contains(warning))
        .collect()
}

/// What `standing` answers: (state now, what must be done to the stored state, the unconfirmed warning that holds it back
/// without changing anything stored, what a kept-on capability notes in place of a turn off).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Standing {
    pub state: ArmingState,
    pub change: Option<OffReason>,
    pub held: Option<ArmingWarning>,
    pub notice: Option<OffReason>,
}

fn standing_of(state: ArmingState) -> Standing {
    Standing {
        state,
        change: None,
        held: None,
        notice: None,
    }
}

/// `standing(definition, row, policy, view, measured, checked)`. Pure. The order is the order of what overrides what: a
/// changed statement, and a warning the person did not confirm that says what it stands on went wrong, turn it off whatever
/// else holds; a policy reads it down; and "on" is on only for the Codex version the person acknowledged.
pub fn standing(
    definition: &CapabilityDef,
    row: Option<&ArmRow>,
    policy: &Policy,
    view: &Value,
    measured: &Table,
    checked: &Results,
) -> Standing {
    let stored = row.map_or(ArmingState::Off, |row| row.state);
    let Some(row) = row else {
        return standing_of(ArmingState::Off);
    };
    if stored == ArmingState::Off {
        return standing_of(ArmingState::Off);
    }
    let kept = row.keep_on;
    let mut notice: Option<OffReason> = None;
    if !kept || policy.admits(&definition.id) {
        // `row.get("statement_revision") != definition.revision`
        if row.statement_revision != Some(definition.revision) {
            notice = Some(OffReason::StatementChanged);
        }
    }
    // Only what its route rests on trips it: a measurement only a part rests on (`narrowed_by`) narrows that part.
    let confirmed: BTreeSet<ArmingWarning> = row.warnings.iter().copied().collect();
    let unconfirmed: BTreeSet<ArmingWarning> =
        warnings_for(definition, view, measured, false, checked)
            .into_iter()
            .filter(|warning| !confirmed.contains(warning))
            .collect();
    if notice.is_none() {
        notice = TRIPPING
            .iter()
            .find(|(warning, _)| unconfirmed.contains(warning))
            .map(|(_, reason)| *reason);
    }
    if notice.is_some() && !kept {
        return Standing {
            state: ArmingState::Off,
            change: notice,
            held: None,
            notice: None,
        };
    }
    if !policy.admits(&definition.id) {
        return standing_of(ArmingState::Off);
    }
    if stored == ArmingState::Armed && policy.force_shadow {
        return standing_of(ArmingState::Shadow);
    }
    if stored == ArmingState::Armed {
        let version = engine_version(view);
        if version != row.engine_version {
            if version.is_none() {
                return Standing {
                    state: ArmingState::Off,
                    change: None,
                    held: Some(ArmingWarning::EngineUnknown),
                    notice: None,
                };
            }
            if !kept {
                return Standing {
                    state: ArmingState::Off,
                    change: Some(OffReason::EngineChanged),
                    held: None,
                    notice: None,
                };
            }
            notice = notice.or(Some(OffReason::EngineChanged));
        }
        if unconfirmed.contains(&ArmingWarning::CompatUnknown) {
            return Standing {
                state: ArmingState::Off,
                change: None,
                held: Some(ArmingWarning::CompatUnknown),
                notice: None,
            };
        }
    }
    Standing {
        state: stored,
        change: None,
        held: None,
        notice,
    }
}

fn once_more() -> &'static CapabilityDef {
    use std::sync::OnceLock;
    static HELD: OnceLock<CapabilityDef> = OnceLock::new();
    HELD.get_or_init(|| {
        crate::registry::definitions()
            .into_iter()
            .find(|each| each.id == "once_more_when_unsure")
            .expect("the once-more capability is in the registry")
    })
}

/// `ONCE_MORE.id`.
pub const ONCE_MORE_ID: &str = "once_more_when_unsure";

/// `departs(definition, row)`: the standards `definition` departs from as a surface lists them: its own, joined - for one kept
/// on with Send again - by the once-more capability's.
pub fn departs(definition: &CapabilityDef, row: Option<&ArmRow>) -> Vec<String> {
    let mut found = definition.departs_from.clone();
    if row.is_some_and(|row| row.send_again) {
        for standard in &once_more().departs_from {
            if !found.contains(standard) {
                found.push(standard.clone());
            }
        }
    }
    found
}

/// `offers_send_again(definition)`: whether Keep on's Send again can ever do anything for `definition`: it answers at a point
/// that leads to a send, but not only at P3, where an answer can hold a record and pays for no send; a capability that resends
/// by itself, or an action, never.
pub fn offers_send_again(definition: &CapabilityDef, sending: &[Point]) -> bool {
    !definition.resends
        && definition.kind != CapabilityKind::Action
        && definition
            .points
            .iter()
            .any(|point| sending.contains(point) && *point != Point::Gates)
}

/// `kept_words(keep_on, send_again)`: the words a person confirms to keep a capability on.
pub fn kept_words(keep_on: bool, send_again: bool) -> Vec<&'static str> {
    KeepOn::ALL
        .iter()
        .filter(|word| {
            (**word == KeepOn::KeepOn && keep_on) || (**word == KeepOn::SendAgain && send_again)
        })
        .map(|word| word.as_str())
        .collect()
}

/// `_rises(held, notice)`: whether `notice` is more serious than the notice a kept-on row holds, so worth writing.
pub fn rises(held: Option<OffReason>, notice: OffReason) -> bool {
    let place = |reason: OffReason| KEPT_NOTICES.iter().position(|each| *each == reason);
    match held.and_then(place) {
        None => true,
        Some(held) => place(notice).is_some_and(|at| at < held),
    }
}

/// `_confirmed(warnings)`: the words a request says the person confirmed, or `None` for a request that does not say it in the
/// vocabulary's words. Saying nothing is confirming none.
pub fn confirmed_of(warnings: &Value) -> Option<BTreeSet<ArmingWarning>> {
    match warnings {
        Value::Null => Some(BTreeSet::new()),
        Value::Array(items) => {
            let mut found = BTreeSet::new();
            for item in items {
                let Value::Str(word) = item else {
                    return None;
                };
                found.insert(parse::<ArmingWarning>(word.as_str()?)?);
            }
            Some(found)
        }
        _ => None,
    }
}

fn number_of(value: &Value) -> Option<f64> {
    match value {
        Value::Int(each) => each
            .as_i64()
            .map(|n| n as f64)
            .or_else(|| each.to_string().parse::<f64>().ok()),
        Value::Float(each) => Some(*each),
        _ => None,
    }
}

/// `_claimed_at(record)`: when the send of `record` that core holds now was claimed - its `last_claim_at` - or `None`.
pub fn claimed_at(record: &Value) -> Option<f64> {
    let Value::Object(record) = record else {
        return None;
    };
    let found = number_of(record.get("last_claim_at")?)?;
    found.is_finite().then_some(found)
}

/// `_carried(spent, key, claimed_at)`: whether the send of record `key` claimed at `claimed` is one a capability paid for.
pub fn carried(spent: &[(String, Vec<f64>)], key: &str, claimed: Option<f64>) -> bool {
    let Some(times) = lookup(spent, key).filter(|times| !times.is_empty()) else {
        return false;
    };
    match claimed {
        None => true,
        Some(claimed) => times.iter().any(|at| (at - claimed).abs() <= SAME_CLAIM),
    }
}

/// Core's records, as `sweep` is handed them: `record(key)` is the record of that interruption as a JSON object, `Null` where
/// core holds none; an error where the view cannot answer.
pub trait CoreView {
    fn get(&self, key: &str) -> Result<Value, Unavailable>;
}

fn lookup<'a>(table: &'a [(String, Vec<f64>)], key: &str) -> Option<&'a Vec<f64>> {
    table
        .iter()
        .find(|(held, _)| held == key)
        .map(|(_, times)| times)
}

fn unknown_claim(core_view: &dyn CoreView, key: &str) -> (bool, Option<f64>) {
    let Ok(record) = core_view.get(key) else {
        return (false, None);
    };
    let held = matches!(&record, Value::Object(map) if matches!(map.get("state"), Some(Value::Str(word)) if word.as_str() == Some(SUBMISSION_UNKNOWN)));
    if held {
        (true, claimed_at(&record))
    } else {
        (false, None)
    }
}

/// `held_word(definition, row, state, change, held, policy)`: why `definition`, stored on or watched in `row`, does not stand on
/// now, as one short word - or `None` where it stands on, or is stored off.
pub fn held_word(
    definition: &CapabilityDef,
    row: Option<&ArmRow>,
    state: ArmingState,
    change: Option<OffReason>,
    held: Option<ArmingWarning>,
    policy: &Policy,
) -> Option<String> {
    if row.map_or(ArmingState::Off, |row| row.state) == ArmingState::Off
        || state == ArmingState::Armed
    {
        return None;
    }
    if let Some(change) = change {
        return Some(change.as_str().to_owned());
    }
    if let Some(held) = held {
        return Some(held.as_str().to_owned());
    }
    if !policy.admits(&definition.id) {
        return Some("policy".to_owned());
    }
    Some(
        if state == ArmingState::Shadow {
            "watched"
        } else {
            "off"
        }
        .to_owned(),
    )
}

// ------------------------------------------------------------------------------------------------ small value helpers
fn is_int(value: &Value) -> bool {
    matches!(value, Value::Int(_))
}

fn int_of(value: &Value) -> Option<i64> {
    match value {
        Value::Int(each) => each.as_i64(),
        _ => None,
    }
}

fn str_of(value: &Value) -> Option<&str> {
    match value {
        Value::Str(each) => each.as_str(),
        _ => None,
    }
}

fn actor_is(value: &Value, wanted: Actor) -> bool {
    str_of(value) == Some(wanted.as_str())
}

fn actor_of(value: &Value) -> Option<Actor> {
    parse::<Actor>(str_of(value)?)
}

fn refusal_value(refusal: Refusal) -> Value {
    text(refusal.as_str())
}

fn warning_texts(warnings: &[ArmingWarning]) -> Value {
    texts(
        &warnings
            .iter()
            .map(|word| word.as_str())
            .collect::<Vec<_>>(),
    )
}

/// The result of an op over a dict of the tag: keys in the order the tag writes them.
fn record<I: IntoIterator<Item = (&'static str, Value)>>(pairs: I) -> Value {
    object(pairs)
}

// ------------------------------------------------------------------------------------------------ the states read
/// `{id: state now}` for every capability of the registry, in the registry's order.
#[derive(Clone, Debug, PartialEq, Eq, Default)]
pub struct States(pub Vec<(String, ArmingState)>);

impl States {
    pub fn get(&self, capability: &str) -> Option<ArmingState> {
        self.0
            .iter()
            .find(|(id, _)| id == capability)
            .map(|(_, state)| *state)
    }

    /// `states.get(id, OFF)`.
    pub fn state_of(&self, capability: &str) -> ArmingState {
        self.get(capability).unwrap_or(ArmingState::Off)
    }

    fn set(&mut self, capability: &str, state: ArmingState) {
        match self.0.iter_mut().find(|(id, _)| id == capability) {
            Some(held) => held.1 = state,
            None => self.0.push((capability.to_owned(), state)),
        }
    }

    pub fn to_json(&self) -> Value {
        object(
            self.0
                .iter()
                .map(|(id, state)| (leak(id), text(state.as_str()))),
        )
    }
}

/// `object` takes `&'static str` keys; ids are the registry's own few dozen words, leaked once each.
fn leak(word: &str) -> &'static str {
    use std::collections::HashSet;
    use std::sync::{Mutex, OnceLock};
    static KEPT: OnceLock<Mutex<HashSet<&'static str>>> = OnceLock::new();
    let mut kept = KEPT
        .get_or_init(|| Mutex::new(HashSet::new()))
        .lock()
        .expect("the keys");
    if let Some(found) = kept.get(word) {
        return found;
    }
    let leaked: &'static str = Box::leak(word.to_owned().into_boxed_str());
    kept.insert(leaked);
    leaked
}

fn row_of<'a>(rows: &'a [(String, ArmRow)], capability: &str) -> Option<&'a ArmRow> {
    rows.iter()
        .find(|(id, _)| id == capability)
        .map(|(_, row)| row)
}

/// What `read` answers: ({id: state now}, {id: since when its stored state has stood, for one that is not off}, whether the
/// state could not be read).
pub struct Read {
    pub states: States,
    pub since: Vec<(String, Option<f64>)>,
    pub failed: bool,
}

pub type ClockFn = Box<dyn Fn() -> f64>;
pub type ViewFn = Box<dyn Fn() -> Result<Value, Unavailable>>;
pub type PolicyFn = Box<dyn Fn() -> Result<Policy, Unavailable>>;
pub type MeasuredFn = Box<dyn Fn() -> Result<Table, Unavailable>>;

/// Everything `Arming.__init__` takes.
pub struct Setup {
    /// `view=`: where the Compatibility Registry's view comes from; `None` is `Edges::default_view`.
    pub view: Option<ViewFn>,
    /// `policy=`: where the administrator's policy is read from (the host's: `policy::read` over the machine's registry).
    pub policy: PolicyFn,
    pub measured: Option<MeasuredFn>,
    pub clock: ClockFn,
    /// `live=`: a fresh check of the Codex here; `None` is `Edges::default_live_view` where no view was handed in, else none.
    pub live: Option<ViewFn>,
}

pub struct Arming<'a> {
    state: &'a dyn StatePort,
    edges: &'a dyn Edges,
    registry: &'a Registry,
    catalogs: &'a Catalogs,
    policy_fn: PolicyFn,
    view_fn: Option<ViewFn>,
    live_fn: Option<ViewFn>,
    live_default: bool,
    measured_fn: Option<MeasuredFn>,
    clock: ClockFn,
    why: RefCell<Vec<(String, String)>>,
    owed: RefCell<BTreeMap<String, (f64, Option<f64>)>>,
}

impl<'a> Arming<'a> {
    pub fn new(
        state: &'a dyn StatePort,
        edges: &'a dyn Edges,
        registry: &'a Registry,
        catalogs: &'a Catalogs,
        setup: Setup,
    ) -> Arming<'a> {
        // `live if live is not None else (None if view else (lambda: _live_view_of(...)))`
        let live_default = setup.live.is_none() && setup.view.is_none();
        Arming {
            state,
            edges,
            registry,
            catalogs,
            policy_fn: setup.policy,
            view_fn: setup.view,
            live_fn: setup.live,
            live_default,
            measured_fn: setup.measured,
            clock: setup.clock,
            why: RefCell::new(Vec::new()),
            owed: RefCell::new(BTreeMap::new()),
        }
    }

    /// `why`: {capability: why it does not stand on now} as the last read that worked found it.
    /// `self.catalogs`: the catalogs the statements are read from (the bridge's advanced-words, S7.3a's surfaces).
    pub fn catalogs(&self) -> &Catalogs {
        self.catalogs
    }

    pub fn why(&self) -> Vec<(String, String)> {
        self.why.borrow().clone()
    }

    pub fn policy(&self) -> Policy {
        (self.policy_fn)().unwrap_or_else(|_| policy::strictest())
    }

    pub fn view(&self) -> Value {
        let found = match &self.view_fn {
            Some(read) => read(),
            None => self.edges.default_view(),
        };
        match found {
            Ok(view @ Value::Object(_)) => view,
            _ => Value::Object(Default::default()),
        }
    }

    pub fn live_view(&self) -> Value {
        let found = match (&self.live_fn, self.live_default) {
            (Some(read), _) => read(),
            (None, true) => self.edges.default_live_view(),
            (None, false) => return Value::Object(Default::default()),
        };
        match found {
            Ok(view @ Value::Object(_)) => view,
            _ => Value::Object(Default::default()),
        }
    }

    /// `measured(view)`: what the measurements found - this build's table with the advanced compatibility data in force laid
    /// over it for the Codex the view names. A table that cannot be read is no measurement at all.
    pub fn measured(&self, view: Option<&Value>) -> Table {
        let found = match &self.measured_fn {
            None => {
                let held;
                let shown = match view {
                    Some(view) => view,
                    None => {
                        held = self.view();
                        &held
                    }
                };
                self.edges.table_for(engine_version(shown).as_deref())
            }
            Some(read) => read(),
        };
        found.unwrap_or_default()
    }

    fn table(&self, view: &Value) -> Table {
        self.measured(Some(view))
    }

    /// `checked(view)`: what the automatic check found of the Codex in force, kept apart from `measured`.
    pub fn checked(&self, view: Option<&Value>) -> Results {
        let held;
        let shown = match view {
            Some(view) => view,
            None => {
                held = self.view();
                &held
            }
        };
        self.edges
            .checked_for(engine_version(shown).as_deref())
            .unwrap_or_default()
    }

    /// `verdict(measurement)`: "pass" where it passed on the Codex in force, "fail" where it failed - on whichever Codex - and
    /// `None` for neither.
    pub fn verdict(&self, measurement: &str) -> Result<Option<&'static str>, Unavailable> {
        let view = self.view();
        let table = self.table(&view);
        // `Measurement(measurement)` is made after the view and the table are read.
        let measurement: Measurement = parse(measurement).ok_or(Unavailable)?;
        let Some((found, measured_on)) = table.get(&measurement) else {
            return Ok(None);
        };
        if *found == Verdict::Fail {
            return Ok(Some("fail"));
        }
        let version = engine_version(&view);
        Ok(
            (*found == Verdict::Pass && version.as_deref() == Some(measured_on.as_str()))
                .then_some("pass"),
        )
    }

    /// `warnings(definition, view)`: the warnings `definition`'s statement shows now.
    pub fn warnings(&self, definition: &CapabilityDef, view: Option<&Value>) -> Vec<ArmingWarning> {
        let held;
        let view = match view {
            Some(view) => view,
            None => {
                held = self.view();
                &held
            }
        };
        let table = self.table(view);
        let checked = self.checked(Some(view));
        warnings_for(definition, view, &table, true, &checked)
    }

    /// `check(definition, view, table=, checked=)`: how `definition` stands for the Codex in force, as a person is told it.
    pub fn check(
        &self,
        definition: &CapabilityDef,
        view: Option<&Value>,
        table: Option<&Table>,
        checked: Option<&Results>,
    ) -> Value {
        let held;
        let view = match view {
            Some(view) => view,
            None => {
                held = self.view();
                &held
            }
        };
        let version = engine_version(view);
        let (own_table, own_checked);
        let table = match table {
            Some(table) => table,
            None => {
                own_table = self.table(view);
                &own_table
            }
        };
        let checked = match checked {
            Some(checked) => checked,
            None => {
                own_checked = self.checked(Some(view));
                &own_checked
            }
        };
        let (word, earlier) = autocheck::grade(
            &rests_on(definition, true),
            version.as_deref(),
            table,
            checked,
        );
        record([
            ("grade", text(word.as_str())),
            ("version", maybe_text(earlier.as_deref())),
        ])
    }

    // ------------------------------------------------------------------------------------------------ now
    /// `current(view, policy)`: `{id: state now}`, carrying out every trip and reset `standing` finds.
    pub fn current(&self, view: Option<&Value>, policy: Option<&Policy>) -> States {
        self.read(view, policy, &[]).states
    }

    /// `read(view=, policy=, live=)`: `current`, with what the runtime needs beside it.
    pub fn read(&self, view: Option<&Value>, policy: Option<&Policy>, live: &[&str]) -> Read {
        if self.registry.is_empty() {
            return Read {
                states: States::default(),
                since: Vec::new(),
                failed: false,
            };
        }
        let (rows, failed) = match self.state.arming() {
            Ok(rows) => (rows, false),
            Err(_) => (Vec::new(), true),
        };
        let since: Vec<(String, Option<f64>)> = rows
            .iter()
            .filter(|(_, row)| row.state != ArmingState::Off)
            .map(|(capability, row)| (capability.clone(), row.since))
            .collect();
        if since.is_empty() {
            if !failed {
                self.why.borrow_mut().clear();
            }
            let states = States(
                self.registry
                    .iter()
                    .map(|each| (each.id.clone(), ArmingState::Off))
                    .collect(),
            );
            return Read {
                states,
                since: Vec::new(),
                failed,
            };
        }
        let mut own_view;
        let view: &Value = match view {
            Some(view) => view,
            None => {
                own_view = self.view();
                let asked = live
                    .iter()
                    .any(|capability| since.iter().any(|(id, _)| id == capability));
                let status_ok = matches!(&own_view, Value::Object(map) if matches!(map.get("status"), Some(Value::Str(word)) if word.as_str() == Some("ok")));
                if asked && !status_ok {
                    let fresh = self.live_view();
                    // `self.live_view() or view`: an empty answer is no answer.
                    if !matches!(&fresh, Value::Object(map) if map.is_empty()) {
                        own_view = fresh;
                    }
                }
                &own_view
            }
        };
        let own_policy;
        let policy = match policy {
            Some(policy) => policy,
            None => {
                own_policy = self.policy();
                &own_policy
            }
        };
        let measured = self.table(view);
        let checked = self.checked(Some(view));
        let mut states = States::default();
        let mut why: Vec<(String, String)> = Vec::new();
        for definition in self.registry.iter() {
            let row = row_of(&rows, &definition.id);
            let found = standing(definition, row, policy, view, &measured, &checked);
            if let Some(change) = found.change {
                self.off(&definition.id, change);
            } else if let Some(notice) = found.notice
                && rises(row.and_then(|row| row.reason), notice)
            {
                self.keep(&definition.id, notice);
            }
            states.0.push((definition.id.clone(), found.state));
            if let Some(word) = held_word(
                definition,
                row,
                found.state,
                found.change,
                found.held,
                policy,
            ) {
                why.push((definition.id.clone(), word));
            }
        }
        self.require_met(&mut states, &rows);
        if !failed {
            *self.why.borrow_mut() = why;
        }
        Read {
            states,
            since,
            failed,
        }
    }

    /// `_require_met(states, rows)`: read down every capability ON whose requirement is not ON now.
    fn require_met(&self, states: &mut States, rows: &[(String, ArmRow)]) {
        let mut changed = true;
        while changed {
            changed = false;
            for definition in self.registry.iter() {
                if definition.requires.is_empty()
                    || states.state_of(&definition.id) != ArmingState::Armed
                {
                    continue;
                }
                if definition
                    .requires
                    .iter()
                    .all(|other| states.get(other) == Some(ArmingState::Armed))
                {
                    continue;
                }
                let row = row_of(rows, &definition.id);
                if row.is_some_and(|row| row.keep_on) {
                    if rises(row.and_then(|row| row.reason), OffReason::RequirementOff) {
                        self.keep(&definition.id, OffReason::RequirementOff);
                    }
                    continue;
                }
                self.off(&definition.id, OffReason::RequirementOff);
                states.set(&definition.id, ArmingState::Off);
                changed = true;
            }
        }
    }

    fn off(&self, capability: &str, reason: OffReason) -> bool {
        self.write_off(capability, reason).unwrap_or(false)
    }

    /// `_write_off(capability, reason)`: `capability` off, with why; a fault where that cannot be written.
    fn write_off(&self, capability: &str, reason: OffReason) -> StateResult<bool> {
        let actor = if TRIPWIRES.contains(&reason) {
            Actor::Tripwire
        } else {
            Actor::EngineChange
        };
        let turned = self
            .state
            .move_to(
                capability,
                ArmingState::Off,
                actor,
                Some(reason),
                None,
                None,
                None,
                None,
                (self.clock)(),
            )?
            .0;
        self.hook_declaration();
        Ok(turned)
    }

    /// `_hook_declaration()`: the Stop hook's declaration follows its capability's stored state; and core's power action armed
    /// for tasks follows `power_after_tasks`'. Never fails.
    fn hook_declaration(&self) {
        self.power_tasks_follow();
        let _ = (|| -> StateResult<()> {
            if self.registry.get(HOOK_CAPABILITY).is_none() {
                if self.state.ever_moved(HOOK_CAPABILITY)? {
                    self.edges.hook_follow(false);
                }
                return Ok(());
            }
            let rows = self.state.arming()?;
            let armed =
                row_of(&rows, HOOK_CAPABILITY).is_some_and(|row| row.state == ArmingState::Armed);
            self.edges.hook_follow(armed);
            Ok(())
        })();
    }

    fn power_tasks_follow(&self) {
        if self.registry.get(POWER_TASKS_CAPABILITY).is_none() {
            return;
        }
        if let Ok(rows) = self.state.arming() {
            let armed = row_of(&rows, POWER_TASKS_CAPABILITY)
                .is_some_and(|row| row.state == ArmingState::Armed);
            self.edges.power_tasks_follow(armed);
        }
    }

    /// `trip(capability, reason)`: a tripwire: `capability` off, with why - or, kept on, noted. Whether it was turned off.
    pub fn trip(&self, capability: &str, reason: OffReason) -> Result<bool, Unavailable> {
        if !TRIPWIRES.contains(&reason) {
            return Err(Unavailable);
        }
        Ok(self.trip_or_keep(capability, reason, None).unwrap_or(false))
    }

    fn keep(&self, capability: &str, reason: OffReason) -> bool {
        self.state
            .note_kept(capability, reason, (self.clock)())
            .unwrap_or(false)
    }

    /// `_trip_or_keep(capability, reason, row)`: a tripwire's `reason` carried out: off, or, for one kept on, its notice.
    fn trip_or_keep(
        &self,
        capability: &str,
        reason: OffReason,
        row: Option<&ArmRow>,
    ) -> StateResult<bool> {
        let fetched;
        let row = match row {
            Some(row) => Some(row),
            None => {
                fetched = self.state.arming()?;
                row_of(&fetched, capability)
            }
        };
        // v0.6.22: no Keep on holds BAD_CODES back.
        if row.is_some_and(|row| row.keep_on) && reason != OffReason::BadCodes {
            if rises(row.and_then(|row| row.reason), reason) {
                self.state.note_kept(capability, reason, (self.clock)())?;
            }
            return Ok(false);
        }
        self.write_off(capability, reason)
    }

    /// `kept(capability)`: whether `capability` is kept on now (K8); not, where the state cannot be read.
    pub fn kept(&self, capability: &str) -> bool {
        match self.state.arming() {
            Ok(rows) => row_of(&rows, capability).is_some_and(|row| row.keep_on),
            Err(_) => false,
        }
    }

    /// `_paid()`: `{capability: (since when it is on, {record: when it paid a send of it} since then, its row)}` for each
    /// capability that is on, or `None` where the state cannot be read.
    #[allow(clippy::type_complexity)]
    fn paid(&self) -> Option<Vec<(String, f64, Vec<(String, Vec<f64>)>, ArmRow)>> {
        let rows = self.state.arming().ok()?;
        let mut found = Vec::new();
        for (capability, row) in rows {
            if row.state == ArmingState::Armed
                && let Some(since) = row.since
            {
                found.push((
                    capability.clone(),
                    since,
                    self.state.spends_since(&capability, since).ok()?,
                    row,
                ));
            }
        }
        Some(found)
    }

    /// `_settle(core_view)`: turn off every capability that is on and paid for the very send core told this plug went into
    /// submission_unknown while it was on - and, with `core_view`, for one core holds so now. Whether any was turned off.
    fn settle(&self, core_view: Option<&dyn CoreView>) -> bool {
        let Some(paid) = self.paid() else {
            return false;
        };
        let (mut tripped, mut failed) = (false, false);
        for (capability, since, spent, row) in &paid {
            let owed = self
                .owed
                .borrow()
                .iter()
                .any(|(key, (told, claimed))| *told >= *since && carried(spent, key, *claimed));
            let held = core_view.is_some_and(|view| {
                spent.iter().map(|(key, _)| key).any(|key| {
                    let (unknown, claimed) = unknown_claim(view, key);
                    unknown && carried(spent, key, claimed)
                })
            });
            if !(owed || held) {
                continue;
            }
            match self.trip_or_keep(capability, OffReason::SubmissionUnknown, Some(row)) {
                Ok(done) => tripped = done || tripped,
                Err(_) => failed = true,
            }
        }
        if !failed {
            self.owed.borrow_mut().clear();
        }
        tripped
    }

    /// `sweep(core_view)`: once a tick: every trip and reset `standing` finds, and a send a capability paid for, since it was
    /// last turned on, that core holds as submission_unknown now; and every continuation sent once more that core found twice,
    /// and every person's request a capability that does not stand on can no longer use.
    pub fn sweep(&self, core_view: &dyn CoreView) {
        let states = self.current(None, None);
        if self.registry.is_empty() {
            return;
        }
        self.settle(Some(core_view));
        self.duplicates(core_view);
        self.void_requests(&states);
        self.end_resets(&states);
        self.end_account(&states);
    }

    fn void_requests(&self, states: &States) {
        let Ok(opened) = self.state.open_overrides(OverrideKind::ForceOnce) else {
            return;
        };
        for item in opened {
            if states.state_of(&item.capability) != ArmingState::Armed {
                self.close(&item.interruption_id, &item.capability);
            }
        }
    }

    fn end_resets(&self, states: &States) {
        let _ = (|| -> StateResult<()> {
            let rules = self.state.reset_rules()?;
            for rule in rules {
                // A watched one keeps its rules; read down to off, they end.
                if states.state_of(&rule.capability) != ArmingState::Off {
                    continue;
                }
                if rule.launching_at.is_some()
                    || rule.record_state.as_deref() == Some(RecordState::InFlight.as_str())
                {
                    continue;
                }
                self.state.end_rule(
                    &rule.rule_id,
                    RuleState::Cancelled,
                    RuleReason::TurnedOff,
                    (self.clock)(),
                )?;
            }
            if states.state_of(CREDIT) != ArmingState::Armed && self.state.reading_has_credits()? {
                self.state.clear_reading()?;
            }
            if states.state_of(PROMPT_QUEUE) == ArmingState::Off {
                self.state
                    .end_prompts(PromptReason::TurnedOff, (self.clock)())?;
            }
            if self.registry.get(STEER_SEND).is_some()
                && states.state_of(STEER_SEND) != ArmingState::Armed
            {
                self.state
                    .end_requested_steers(SteerReason::TurnedOff, (self.clock)())?;
            }
            for row in self.state.continuations_pending()? {
                let ContinuationRow {
                    capability,
                    record_state,
                } = row;
                if states.state_of(&capability) != ArmingState::Armed
                    && record_state.as_deref() == Some(RecordState::Waiting.as_str())
                {
                    self.state.end_continuations(
                        ContinuationReason::TurnedOff,
                        &capability,
                        (self.clock)(),
                    )?;
                }
            }
            Ok(())
        })();
    }

    fn end_account(&self, states: &States) {
        if states.state_of(ACCOUNT_CAPABILITY) == ArmingState::Off
            && self.registry.get(ACCOUNT_CAPABILITY).is_some()
        {
            self.edges.account_forget();
        }
    }

    fn duplicates(&self, core_view: &dyn CoreView) {
        let Ok(watched) = self.state.open_overrides(OverrideKind::ResendOnce) else {
            return;
        };
        if watched.is_empty() {
            return;
        }
        let Ok(rows) = self.state.arming() else {
            return;
        };
        let now = (self.clock)();
        for item in watched {
            let (key, capability) = (&item.interruption_id, &item.capability);
            let Ok(found) = core_view.get(key) else {
                continue; // a view that cannot answer says nothing
            };
            let duplicate = matches!(&found, Value::Object(map) if matches!(map.get("last_error"), Some(Value::Str(word)) if word.as_str() == Some(DUPLICATE)));
            if !duplicate {
                if !matches!(found, Value::Object(_)) || now - item.created_at > RESEND_WATCH {
                    self.close(key, capability);
                }
                continue;
            }
            let row = row_of(&rows, capability);
            let definition = self.registry.get(capability);
            let result = (|| -> StateResult<()> {
                if let Some(row) = row
                    && row.state != ArmingState::Off
                    && row.since.is_some()
                    && item.created_at >= row.since.unwrap_or(f64::INFINITY)
                {
                    if definition.is_some_and(|each| each.resends) {
                        self.write_off(capability, OffReason::DuplicateSeen)?;
                    } else if row.send_again {
                        self.state
                            .send_again_off(capability, OffReason::DuplicateSeen, now)?;
                    }
                }
                Ok(())
            })();
            if result.is_err() {
                continue;
            }
            self.close(key, capability);
        }
    }

    fn close(&self, key: &str, capability: &str) {
        let _ = self.state.use_override(key, capability, (self.clock)());
    }

    /// `resender(record, states)`: (the capability, where it stands) whose Keep on's Send again sends `record` once more, or
    /// `None`. A state that cannot be read sends nothing again.
    pub fn resender(&self, record: &Value, states: &States) -> Option<(String, ArmingState)> {
        let Value::Object(map) = record else {
            return None;
        };
        let key = str_of(map.get("interruption_id")?)?;
        if str_of(map.get("state")?) != Some(SUBMISSION_UNKNOWN) {
            return None;
        }
        if !self.policy().admits(ONCE_MORE_ID) {
            return None;
        }
        let (rows, payers) = (|| -> StateResult<Option<_>> {
            let rows = self.state.arming()?;
            if !rows.iter().any(|(_, row)| row.send_again) || self.state.resent(key)? {
                return Ok(None);
            }
            let payers = self.state.payers(key, claimed_at(record))?;
            Ok(Some((rows, payers)))
        })()
        .ok()
        .flatten()?;
        for definition in self.registry.iter() {
            let row = row_of(&rows, &definition.id);
            let state = states.state_of(&definition.id);
            let Some(row) = row else { continue };
            let Some(since) = row.since else { continue };
            if definition.resends
                || state == ArmingState::Off
                || !row.send_again
                || !lookup(&payers, &definition.id)
                    .is_some_and(|times| times.iter().any(|at| *at >= since))
            {
                continue;
            }
            let channel = |point: &Point| matches!(point, Point::Sender | Point::Unloaded);
            if payers
                .iter()
                .map(|(other, _)| other)
                .filter(|other| **other != definition.id)
                .any(|other| {
                    self.registry
                        .get(other)
                        .is_some_and(|each| each.points.iter().any(channel))
                })
            {
                return None;
            }
            return Some((definition.id.clone(), state));
        }
        None
    }

    /// `moved(record, state)` (P14): core has just moved `record` to `state`. Into submission_unknown, every capability that
    /// paid for that send since it was last turned on is turned off. Whether any was.
    pub fn moved(&self, record: &Value, state: &str) -> bool {
        let key = match record {
            Value::Object(map) => map.get("interruption_id").and_then(str_of),
            _ => None,
        };
        let Some(key) = key else {
            return false;
        };
        if state != SUBMISSION_UNKNOWN || self.registry.is_empty() {
            return false;
        }
        self.owed
            .borrow_mut()
            .insert(key.to_owned(), ((self.clock)(), claimed_at(record)));
        self.settle(None)
    }

    // ------------------------------------------------------------------------------------------------ on
    fn generation(&self) -> i64 {
        self.state.meta().map_or(0, |meta| meta.generation)
    }

    /// `arm(capability, state=, revision=, generation=, acknowledged_version=, warnings=, also=, keep_on=, actor=)`: move
    /// `capability` to watched (SHADOW) or on (ARMED), for a person in the Dashboard.
    ///
    /// A statement catalog that is not UTF-8 ends the call with `UnicodeDecodeError`, where the tag's `complete_in` raises it:
    /// nothing is written and nothing more is asked of the state or the edges (kept: AUDIT-v0628.md).
    pub fn arm(&self, request: &ArmRequest) -> Result<Value, Undecodable> {
        let undecodable = Cell::new(false);
        let answer = self.arm_value(request, &undecodable);
        if undecodable.get() {
            Err(Undecodable)
        } else {
            Ok(answer)
        }
    }

    fn arm_value(&self, request: &ArmRequest, undecodable: &Cell<bool>) -> Value {
        let mut shown: Vec<ArmingWarning> = Vec::new();
        let refuse = |why: Refusal, shown: &[ArmingWarning]| {
            record([
                ("done", Value::Bool(false)),
                ("refusal", refusal_value(why)),
                ("warnings", warning_texts(shown)),
                ("generation", int(self.generation())),
            ])
        };
        if !actor_is(&request.actor, Actor::Dashboard) {
            return refuse(Refusal::NotTheDashboard, &shown);
        }
        let Some(definition) = request.capability_def(self.registry) else {
            return refuse(Refusal::UnknownCapability, &shown);
        };
        let confirmed = confirmed_of(&request.warnings);
        let wanted_state = match str_of(&request.state) {
            Some("shadow") => Some(ArmingState::Shadow),
            Some("armed") => Some(ArmingState::Armed),
            _ => None,
        };
        let version_ok = matches!(request.acknowledged_version, Value::Null | Value::Str(_));
        let also_ok = matches!(request.also, Value::Null | Value::Array(_));
        let keep_flag = match request.keep_on {
            Value::Bool(flag) => Some(flag),
            _ => None,
        };
        let (Some(state), true, true, Some(confirmed), true, true, Some(keep_on)) = (
            wanted_state,
            is_int(&request.revision),
            is_int(&request.generation),
            confirmed,
            version_ok,
            also_ok,
            keep_flag,
        ) else {
            return refuse(Refusal::InvalidRequest, &shown);
        };
        if keep_on && state != ArmingState::Armed {
            return refuse(Refusal::InvalidRequest, &shown);
        }
        let revision = int_of(&request.revision);
        let generation = int_of(&request.generation).unwrap_or(0);
        let acknowledged = str_of(&request.acknowledged_version).map(str::to_owned);
        let view = self.view();
        let policy = self.policy();

        // `check(target, target_revision, target_confirmed, target_version)`: a policy refusal for `target`, or STALE_* where
        // its confirmation is not what holds now, or `None` where it may be armed.
        let check = |target: &CapabilityDef,
                     target_revision: Option<i64>,
                     target_confirmed: &BTreeSet<ArmingWarning>,
                     target_version: &Option<String>|
         -> Result<Option<Refusal>, Undecodable> {
            if policy.forbid {
                return Ok(Some(Refusal::ForbiddenByPolicy));
            }
            if !policy.admits(&target.id) {
                return Ok(Some(Refusal::NotAllowedByPolicy));
            }
            if policy.force_shadow {
                return Ok(Some(Refusal::ShadowForcedByPolicy));
            }
            if target_revision != Some(target.revision) {
                return Ok(Some(Refusal::StaleRevision));
            }
            if !self.catalogs.complete_in(target, "en")? {
                return Ok(Some(Refusal::StatementIncomplete));
            }
            let now: BTreeSet<ArmingWarning> =
                self.warnings(target, Some(&view)).into_iter().collect();
            if target_confirmed != &now || *target_version != engine_version(&view) {
                return Ok(Some(Refusal::StaleConfirmation));
            }
            Ok(None)
        };

        // Watching needs no requirement and forces none on: the single move.
        if state == ArmingState::Shadow {
            if !matches!(&request.also, Value::Null)
                && !matches!(&request.also, Value::Array(items) if items.is_empty())
            {
                return refuse(Refusal::InvalidRequest, &shown);
            }
            if policy.forbid {
                return refuse(Refusal::ForbiddenByPolicy, &shown);
            }
            if !policy.admits(&definition.id) {
                return refuse(Refusal::NotAllowedByPolicy, &shown);
            }
            if revision != Some(definition.revision) {
                return refuse(Refusal::StaleRevision, &shown);
            }
            let complete = match self.catalogs.complete_in(definition, "en") {
                Ok(complete) => complete,
                Err(Undecodable) => {
                    undecodable.set(true);
                    return Value::Null;
                }
            };
            if !complete {
                return refuse(Refusal::StatementIncomplete, &shown);
            }
            shown = self.warnings(definition, Some(&view));
            if confirmed != shown.iter().copied().collect::<BTreeSet<_>>() {
                return refuse(Refusal::StaleConfirmation, &shown);
            }
            let moved = self.state.move_to(
                &definition.id,
                ArmingState::Shadow,
                Actor::Dashboard,
                None,
                Some(&request.revision),
                None,
                Some(&shown),
                Some(generation),
                (self.clock)(),
            );
            return match moved {
                Ok((_moved, after)) => {
                    self.hook_declaration();
                    record([
                        ("done", Value::Bool(true)),
                        ("refusal", Value::Null),
                        ("warnings", warning_texts(&shown)),
                        ("generation", int(after)),
                    ])
                }
                Err(StateFault::Stale) => refuse(Refusal::StaleGeneration, &shown),
                Err(_) => refuse(Refusal::StateUnavailable, &shown),
            };
        }

        // Turning it on. Every requirement that is not ARMED now is turned on with it, one confirmation.
        let states = self.current(Some(&view), Some(&policy));
        // A requirement graded Failed here keeps the dependent off, as a policy on it does: no confirmation turns it on.
        for other in self.registry.requires(&definition.id) {
            if let Some(other_def) = self.registry.get(&other)
                && self
                    .warnings(other_def, Some(&view))
                    .contains(&ArmingWarning::FailedHere)
            {
                return refuse(Refusal::RequirementFailedHere, &shown);
            }
        }
        let needed: Vec<String> = self
            .registry
            .requires(&definition.id)
            .into_iter()
            .filter(|other| states.state_of(other) != ArmingState::Armed)
            .collect();
        let mut entries: Vec<(Option<String>, &car_machine::json::Map)> = Vec::new();
        if let Value::Array(items) = &request.also {
            for entry in items {
                let Value::Object(map) = entry else {
                    return refuse(Refusal::InvalidRequest, &shown);
                };
                let named = map.get("capability").and_then(str_of).map(str::to_owned);
                match entries
                    .iter_mut()
                    .find(|(held, _)| held == &named && named.is_some())
                {
                    Some(held) => held.1 = map,
                    None => entries.push((named, map)),
                }
            }
        }
        let named: BTreeSet<Option<&str>> =
            entries.iter().map(|(each, _)| each.as_deref()).collect();
        let wanted: BTreeSet<Option<&str>> =
            needed.iter().map(|each| Some(each.as_str())).collect();
        if named != wanted || entries.iter().any(|(each, _)| each.is_none()) {
            return refuse(Refusal::RequirementRefused, &shown);
        }

        let reason = match check(definition, revision, &confirmed, &acknowledged) {
            Ok(reason) => reason,
            Err(Undecodable) => {
                undecodable.set(true);
                return Value::Null;
            }
        };
        shown = self.warnings(definition, Some(&view));
        if let Some(reason) = reason {
            return refuse(reason, &shown);
        }
        if keep_on && shown.contains(&ArmingWarning::FailedHere) {
            return refuse(Refusal::FailedHere, &shown);
        }
        let mut moves = vec![Move {
            capability: definition.id.clone(),
            state: ArmingState::Armed,
            revision: request.revision.clone(),
            engine_version: acknowledged.clone(),
            warnings: shown.clone(),
        }];
        let mut kept: Vec<String> = if keep_on {
            vec![definition.id.clone()]
        } else {
            Vec::new()
        };
        for other in &needed {
            let other_def = self.registry.get(other);
            let Some((_, entry)) = entries
                .iter()
                .find(|(each, _)| each.as_deref() == Some(other.as_str()))
            else {
                return refuse(Refusal::RequirementRefused, &shown);
            };
            let other_confirmed = confirmed_of(entry.get("warnings").unwrap_or(&Value::Null));
            let other_revision = entry.get("revision").unwrap_or(&Value::Null);
            let other_version = entry.get("engine_version").unwrap_or(&Value::Null);
            let (Some(other_def), true, Some(other_confirmed), true) = (
                other_def,
                is_int(other_revision),
                other_confirmed,
                matches!(other_version, Value::Null | Value::Str(_)),
            ) else {
                return refuse(Refusal::RequirementRefused, &shown);
            };
            let version = str_of(other_version).map(str::to_owned);
            let reason = match check(
                other_def,
                int_of(other_revision),
                &other_confirmed,
                &version,
            ) {
                Ok(reason) => reason,
                Err(Undecodable) => {
                    undecodable.set(true);
                    return Value::Null;
                }
            };
            if let Some(reason) = reason {
                // A policy on the required one keeps the dependent off; a stale confirmation can be asked again.
                return refuse(reason, &shown);
            }
            let other_shown = self.warnings(other_def, Some(&view));
            if keep_on && !other_shown.contains(&ArmingWarning::FailedHere) {
                kept.push(other.clone());
            }
            moves.push(Move {
                capability: other.clone(),
                state: ArmingState::Armed,
                revision: other_revision.clone(),
                engine_version: version,
                warnings: other_shown,
            });
        }
        match self
            .state
            .move_set(&moves, Actor::Dashboard, generation, (self.clock)(), &kept)
        {
            Ok((_written, after)) => {
                self.hook_declaration();
                record([
                    ("done", Value::Bool(true)),
                    ("refusal", Value::Null),
                    ("warnings", warning_texts(&shown)),
                    ("generation", int(after)),
                ])
            }
            Err(StateFault::Stale) => refuse(Refusal::StaleGeneration, &shown),
            Err(_) => refuse(Refusal::StateUnavailable, &shown),
        }
    }

    // ------------------------------------------------------------------------------------------------ off
    /// `disarm(capability, actor=)`: one capability off, from any surface. Needs nothing, and always wins. What requires this
    /// one and is on or watched now is turned off first, named first in `also_off`.
    pub fn disarm(&self, capability: &Value, actor: &Value) -> Value {
        let answer = |done: bool, refusal: Option<Refusal>, changed: bool, also_off: &[String]| {
            record([
                ("done", Value::Bool(done)),
                ("refusal", refusal.map_or(Value::Null, refusal_value)),
                ("changed", Value::Bool(changed)),
                ("also_off", texts(also_off)),
            ])
        };
        let surface = actor_of(actor).filter(|each| SURFACES.contains(each));
        let Some(actor) = surface else {
            return answer(false, Some(Refusal::InvalidRequest), false, &[]);
        };
        let Some(definition) = registry_get(self.registry, capability) else {
            return answer(false, Some(Refusal::UnknownCapability), false, &[]);
        };
        let mut also_off: Vec<String> = Vec::new();
        let outcome = (|| -> StateResult<bool> {
            let states = self.current(None, None);
            for dependent in self.registry.required_by(&definition.id) {
                if states.state_of(&dependent) != ArmingState::Off {
                    let (turned, _after) = self.state.move_to(
                        &dependent,
                        ArmingState::Off,
                        actor,
                        Some(OffReason::RequirementOff),
                        None,
                        None,
                        None,
                        None,
                        (self.clock)(),
                    )?;
                    if turned {
                        also_off.push(dependent);
                    }
                }
            }
            Ok(self
                .state
                .move_to(
                    &definition.id,
                    ArmingState::Off,
                    actor,
                    Some(OffReason::Disarmed),
                    None,
                    None,
                    None,
                    None,
                    (self.clock)(),
                )?
                .0)
        })();
        match outcome {
            Err(_) => answer(false, Some(Refusal::StateUnavailable), false, &also_off),
            Ok(changed) => {
                self.hook_declaration();
                answer(true, None, changed, &also_off)
            }
        }
    }

    /// `all_off(actor=)`: "All advanced features off": every capability, at once, from any surface.
    pub fn all_off(&self, actor: &Value) -> Value {
        let surface = actor_of(actor).filter(|each| SURFACES.contains(each));
        let Some(actor) = surface else {
            return record([
                ("done", Value::Bool(false)),
                ("refusal", refusal_value(Refusal::InvalidRequest)),
                ("count", int(0)),
            ]);
        };
        match self.state.all_off(actor, OffReason::AllOff, (self.clock)()) {
            Err(_) => record([
                ("done", Value::Bool(false)),
                ("refusal", refusal_value(Refusal::StateUnavailable)),
                ("count", int(0)),
            ]),
            Ok((count, _after)) => {
                self.hook_declaration();
                record([
                    ("done", Value::Bool(true)),
                    ("refusal", Value::Null),
                    ("count", int(count)),
                ])
            }
        }
    }

    /// `edition_entered()`: the installer has just entered this edition: every capability off, whatever an earlier advanced
    /// installation of this home left on.
    pub fn edition_entered(&self) -> StateResult<i64> {
        let count = self
            .state
            .all_off(
                Actor::EditionEntry,
                OffReason::EditionEntered,
                (self.clock)(),
            )?
            .0;
        self.hook_declaration();
        Ok(count)
    }

    // ------------------------------------------------------------------------------------------------ kept on
    /// `set_keep_on(capability, keep_on, send_again=, generation=, confirmed=, actor=)`: keep `capability` on (K8) - with Send
    /// again or without - or let it turn itself off again, for a person in the Dashboard.
    pub fn set_keep_on(&self, request: &KeepRequest) -> Value {
        let refuse = |why: Refusal| {
            record([
                ("done", Value::Bool(false)),
                ("refusal", refusal_value(why)),
                ("generation", int(self.generation())),
            ])
        };
        if !actor_is(&request.actor, Actor::Dashboard) {
            return refuse(Refusal::NotTheDashboard);
        }
        let Some(definition) = registry_get(self.registry, &request.capability) else {
            return refuse(Refusal::UnknownCapability);
        };
        let (Value::Bool(keep_on), Value::Bool(send_again)) =
            (&request.keep_on, &request.send_again)
        else {
            return refuse(Refusal::InvalidRequest);
        };
        let (keep_on, send_again) = (*keep_on, *send_again);
        let generation_ok =
            matches!(request.generation, Value::Null) || is_int(&request.generation);
        if !generation_ok
            || (send_again
                && (!keep_on || definition.resends || definition.kind == CapabilityKind::Action))
        {
            return refuse(Refusal::InvalidRequest);
        }
        let Ok(rows) = self.state.arming() else {
            return refuse(Refusal::StateUnavailable);
        };
        let row = row_of(&rows, &definition.id);
        let sending = self.edges.sending_points();
        if send_again
            && !row.is_some_and(|row| row.send_again)
            && !offers_send_again(definition, &sending)
        {
            return refuse(Refusal::InvalidRequest);
        }
        let wanted = kept_words(keep_on, send_again);
        let held = kept_words(
            row.is_some_and(|row| row.keep_on),
            row.is_some_and(|row| row.send_again),
        );
        let mut generation = int_of(&request.generation);
        if !wanted.iter().all(|word| held.contains(word)) {
            let policy = self.policy();
            if policy.forbid {
                return refuse(Refusal::ForbiddenByPolicy);
            }
            if !policy.admits(&definition.id) || (send_again && !policy.admits(ONCE_MORE_ID)) {
                return refuse(Refusal::NotAllowedByPolicy);
            }
            if policy.force_shadow && row.is_some_and(|row| row.state == ArmingState::Armed) {
                return refuse(Refusal::ShadowForcedByPolicy);
            }
            // v0.6.16-beta.4: kept on is on - one watched or off is turned on and kept on through the arm (`keep_on`).
            if self.current(None, Some(&policy)).state_of(&definition.id) != ArmingState::Armed {
                return refuse(Refusal::NotOn);
            }
            let said = matches!(&request.confirmed, Value::Array(items)
                if items.len() == wanted.len() && items.iter().zip(&wanted).all(|(item, word)| str_of(item) == Some(*word)));
            if !said {
                return refuse(Refusal::StaleConfirmation);
            }
            if generation.is_none() {
                return refuse(Refusal::InvalidRequest);
            }
        } else {
            generation = None; // letting go never waits on a generation
        }
        match self.state.set_keep_on(
            &definition.id,
            keep_on,
            send_again,
            Actor::Dashboard,
            generation,
            (self.clock)(),
        ) {
            Ok(after) => record([
                ("done", Value::Bool(true)),
                ("refusal", Value::Null),
                ("generation", int(after)),
            ]),
            Err(StateFault::Refused(why)) => refuse(why),
            Err(StateFault::Stale) => refuse(Refusal::StaleGeneration),
            Err(StateFault::State) => refuse(Refusal::StateUnavailable),
        }
    }

    // ------------------------------------------------------------------------------------------------ ceiling
    /// `set_global_hourly(value, generation=, actor=)`: lower the one ceiling over every capability together, in the
    /// Dashboard. It can be set anywhere from 1 to GLOBAL_HOURLY, and never above.
    pub fn set_global_hourly(&self, value: &Value, generation: &Value, actor: &Value) -> Value {
        let answer = |done: bool, refusal: Option<Refusal>| {
            record([
                ("done", Value::Bool(done)),
                ("refusal", refusal.map_or(Value::Null, refusal_value)),
            ])
        };
        if !actor_is(actor, Actor::Dashboard) {
            return answer(false, Some(Refusal::NotTheDashboard));
        }
        let (Some(hourly), Some(generation)) = (int_of(value), int_of(generation)) else {
            return answer(false, Some(Refusal::InvalidRequest));
        };
        if !(1..=GLOBAL_HOURLY).contains(&hourly) {
            return answer(false, Some(Refusal::InvalidRequest));
        }
        match self
            .state
            .set_global_hourly(hourly, generation, Actor::Dashboard, (self.clock)())
        {
            Ok(after) => record([
                ("done", Value::Bool(true)),
                ("refusal", Value::Null),
                ("generation", int(after)),
            ]),
            Err(StateFault::Stale) => answer(false, Some(Refusal::StaleGeneration)),
            Err(_) => answer(false, Some(Refusal::StateUnavailable)),
        }
    }

    // ------------------------------------------------------------------------------------------------ choices and rules
    /// `_chosen(write)`: a person's choice or rule written as `write` does it: `{"done", "refusal", and what it gave}`.
    fn chosen(&self, write: impl FnOnce() -> StateResult<Vec<(&'static str, Value)>>) -> Value {
        let failure = |why: Refusal| {
            record([
                ("done", Value::Bool(false)),
                ("refusal", refusal_value(why)),
                ("generation", int(self.generation())),
            ])
        };
        match write() {
            Ok(mut gave) => {
                gave.push(("done", Value::Bool(true)));
                gave.push(("refusal", Value::Null));
                // `dict(write(), done=True, refusal=None)`: what it gave first, then the two (a key given twice keeps its place).
                let mut seen: Vec<(&'static str, Value)> = Vec::new();
                for (key, value) in gave {
                    match seen.iter_mut().find(|(held, _)| *held == key) {
                        Some(held) => held.1 = value,
                        None => seen.push((key, value)),
                    }
                }
                record(seen)
            }
            Err(StateFault::Refused(why)) => failure(why),
            Err(StateFault::Stale) => failure(Refusal::StaleGeneration),
            Err(StateFault::State) => failure(Refusal::StateUnavailable),
        }
    }

    /// `set_option(capability, key, value, generation=, actor=)`: one of a capability's own choices, in the Dashboard.
    pub fn set_option(
        &self,
        capability: &Value,
        key: &Value,
        value: &Value,
        generation: &Value,
        actor: &Value,
    ) -> Value {
        let plain = |why: Refusal| {
            record([
                ("done", Value::Bool(false)),
                ("refusal", refusal_value(why)),
            ])
        };
        if !actor_is(actor, Actor::Dashboard) {
            return plain(Refusal::NotTheDashboard);
        }
        let Some(found) = registry_get(self.registry, capability) else {
            return plain(Refusal::UnknownCapability);
        };
        // v0.6.16-beta.4 (j): the near-limit percentages of a window stay in order - checked as they would be after.
        let mut warned: Vec<(&'static str, Value)> = Vec::new();
        if [METER, WRAP_UP, PAUSE].contains(&found.id.as_str()) {
            let option = str_of(key)
                .and_then(parse::<OptionKey>)
                .and_then(|each| found.option(each));
            let values = (|| -> StateResult<BTreeMap<String, BTreeMap<OptionKey, i64>>> {
                let mut values = BTreeMap::new();
                for other in [METER, WRAP_UP, PAUSE] {
                    if self.registry.get(other).is_some() {
                        values.insert(other.to_owned(), self.state.options(other)?);
                    }
                }
                Ok(values)
            })()
            .ok();
            if let (Some(mut values), Some(option), Some(number)) = (values, option, int_of(value))
                && option.takes(number)
            {
                values
                    .entry(found.id.clone())
                    .or_default()
                    .insert(option.key, number);
                let (problem, warning) = self
                    .edges
                    .usage_order_problem(&values, &self.edges.usage_touched(option.key));
                if problem.is_some() {
                    return record([
                        ("done", Value::Bool(false)),
                        ("refusal", refusal_value(Refusal::OptionOrder)),
                        ("generation", int(self.generation())),
                    ]);
                }
                if let Some(warning) = warning {
                    warned.push(("warning", text(&warning)));
                }
            }
        }
        let id = found.id.clone();
        self.chosen(|| {
            let after = self.state.set_option(
                &id,
                key,
                value,
                generation,
                Actor::Dashboard,
                (self.clock)(),
            )?;
            let mut gave = warned;
            gave.push(("generation", int(after)));
            Ok(gave)
        })
    }

    /// `wordings_view(capability)`: a capability's own wordings as the Dashboard's page shows them, with what they may hold.
    pub fn wordings_view(&self, capability: &Value) -> Value {
        let plain = |why: Refusal| {
            record([
                ("done", Value::Bool(false)),
                ("refusal", refusal_value(why)),
            ])
        };
        let Some(definition) =
            registry_get(self.registry, capability).filter(|each| !each.wordings.is_empty())
        else {
            return plain(Refusal::UnknownCapability);
        };
        let Ok(found) = self.state.wordings(&definition.id) else {
            return plain(Refusal::StateUnavailable);
        };
        // (a): what would be sent for each window, exactly - shown under the wording choice.
        let shown = if definition.id == WRAP_UP {
            self.edges.usage_previews((self.clock)())
        } else {
            Vec::new()
        };
        let wordings = object(definition.wordings.iter().map(|key| {
            (
                leak(key.as_str()),
                found
                    .get(key)
                    .cloned()
                    .flatten()
                    .map_or(Value::Null, |words| text(&words)),
            )
        }));
        let previews =
            object(shown.iter().map(|(minutes, words)| {
                (leak(&minutes.to_string()), maybe_text(words.as_deref()))
            }));
        record([
            ("done", Value::Bool(true)),
            ("refusal", Value::Null),
            ("wordings", wordings),
            ("limit", int(self.edges.wording_limit())),
            ("placeholders", texts(&self.edges.wording_placeholders())),
            ("previews", previews),
            ("generation", int(self.generation())),
        ])
    }

    /// `set_wording(capability, key, words, generation=, actor=)`: a person's own wording set in the Dashboard - or taken away.
    pub fn set_wording(
        &self,
        capability: &Value,
        key: &Value,
        words: &Value,
        generation: &Value,
        actor: &Value,
    ) -> Value {
        let plain = |why: Refusal| {
            record([
                ("done", Value::Bool(false)),
                ("refusal", refusal_value(why)),
            ])
        };
        if !actor_is(actor, Actor::Dashboard) {
            return plain(Refusal::NotTheDashboard);
        }
        let Some(found) = registry_get(self.registry, capability) else {
            return plain(Refusal::UnknownCapability);
        };
        // v0.6.22: fleet_view's alias and folder are no message: they are checked and kept by control/fleet.save alone.
        if matches!(str_of(key), Some(word) if word == WordingKey::FleetAlias.as_str() || word == WordingKey::FleetFolder.as_str())
        {
            return record([
                ("done", Value::Bool(false)),
                ("refusal", refusal_value(Refusal::WordingInvalid)),
                ("generation", int(self.generation())),
            ]);
        }
        if !matches!(words, Value::Null)
            && let Some(problem) = self.edges.wording_problem(words)
        {
            return record([
                ("done", Value::Bool(false)),
                ("refusal", refusal_value(Refusal::WordingInvalid)),
                ("problem", text(&problem)),
                ("generation", int(self.generation())),
            ]);
        }
        let id = found.id.clone();
        self.chosen(|| {
            let after = self.state.set_wording(
                &id,
                key,
                words,
                generation,
                Actor::Dashboard,
                (self.clock)(),
            )?;
            Ok(vec![("generation", int(after))])
        })
    }

    /// `add_rule(tag, status_from, status_to, category, generation=, actor=)`: a rule for one of Codex's error codes.
    #[allow(clippy::too_many_arguments)]
    pub fn add_rule(
        &self,
        tag: &Value,
        status_from: &Value,
        status_to: &Value,
        category: &Value,
        generation: &Value,
        actor: &Value,
    ) -> Value {
        if !actor_is(actor, Actor::Dashboard) {
            return record([
                ("done", Value::Bool(false)),
                ("refusal", refusal_value(Refusal::NotTheDashboard)),
            ]);
        }
        self.chosen(|| {
            let (rule, after) = self.state.add_rule(
                tag,
                status_from,
                status_to,
                category,
                generation,
                Actor::Dashboard,
                (self.clock)(),
            )?;
            Ok(vec![("rule", rule), ("generation", int(after))])
        })
    }

    /// `remove_rule(rule, generation=, actor=)`: a rule removed, in the Dashboard.
    pub fn remove_rule(&self, rule: &Value, generation: &Value, actor: &Value) -> Value {
        if !actor_is(actor, Actor::Dashboard) {
            return record([
                ("done", Value::Bool(false)),
                ("refusal", refusal_value(Refusal::NotTheDashboard)),
            ]);
        }
        self.chosen(|| {
            let after =
                self.state
                    .remove_rule(rule, generation, Actor::Dashboard, (self.clock)())?;
            Ok(vec![("generation", int(after))])
        })
    }

    /// `_options(definition)`: a capability's choices as a surface shows them: the defaults where the state cannot be read.
    fn options_of(&self, definition: &CapabilityDef) -> Value {
        if definition.options.is_empty() {
            return Value::Array(Vec::new());
        }
        let values = self.state.options(&definition.id).unwrap_or_default();
        Value::Array(
            definition
                .options
                .iter()
                .map(|option| {
                    let mut shown = vec![
                        ("key", text(option.key.as_str())),
                        (
                            "choices",
                            Value::Array(option.choices.iter().map(|each| int(*each)).collect()),
                        ),
                        (
                            "value",
                            int(values.get(&option.key).copied().unwrap_or(option.default)),
                        ),
                        ("default", int(option.default)),
                    ];
                    if let Some((low, high)) = option.custom {
                        shown.push(("custom", Value::Array(vec![int(low), int(high)])));
                    }
                    record(shown)
                })
                .collect(),
        )
    }

    /// `rules_view()`: the rules as the Dashboard's editor shows them, oldest first.
    pub fn rules_view(&self) -> Value {
        let since = (self.clock)() - (RECENT_DAYS * DAY) as f64;
        let read = (|| -> StateResult<_> {
            let rules = self.state.rules()?;
            let hits = self.state.rule_hits(since)?;
            let samples = self.state.failure_samples(since)?;
            let meta = self.state.meta()?;
            Ok((rules, hits, samples, meta))
        })();
        let Ok((rules, hits, samples, meta)) = read else {
            return record([
                ("done", Value::Bool(false)),
                ("refusal", refusal_value(Refusal::StateUnavailable)),
            ]);
        };
        let field = |rule: &Value, name: &str| match rule {
            Value::Object(map) => map.get(name).cloned().unwrap_or(Value::Null),
            _ => Value::Null,
        };
        let shown: Vec<Value> = rules
            .iter()
            .map(|rule| {
                let id = field(rule, "rule_id");
                let count = hits
                    .iter()
                    .find(|(held, _)| held == &id)
                    .map_or(0, |(_, count)| *count);
                record([
                    ("rule", id),
                    ("tag", field(rule, "tag")),
                    ("status_from", field(rule, "status_from")),
                    ("status_to", field(rule, "status_to")),
                    ("category", field(rule, "category")),
                    ("known", field(rule, "known")),
                    ("hits", int(count)),
                ])
            })
            .collect();
        let tags: BTreeSet<String> = samples
            .iter()
            .filter_map(|sample| match field(sample, "tag") {
                Value::Str(tag) => tag.as_str().map(str::to_owned),
                _ => None,
            })
            .filter(|tag| self.state.tag_is_valid(tag))
            .collect();
        record([
            ("done", Value::Bool(true)),
            ("generation", int(meta.generation)),
            ("limit", int(RULES_LIMIT)),
            ("rules", Value::Array(shown)),
            ("tags", texts(&tags.into_iter().collect::<Vec<_>>())),
        ])
    }

    /// `samples_view()`: the samples of the last 30 days, as the Dashboard and a diagnostics export show them.
    pub fn samples_view(&self) -> Value {
        match self
            .state
            .failure_samples((self.clock)() - (RECENT_DAYS * DAY) as f64)
        {
            Ok(samples) => record([
                ("done", Value::Bool(true)),
                ("samples", self.state.aggregated(&samples)),
            ]),
            Err(_) => record([
                ("done", Value::Bool(false)),
                ("refusal", refusal_value(Refusal::StateUnavailable)),
            ]),
        }
    }

    // ------------------------------------------------------------------------------------------------ shown
    /// `statement(definition, locale)`: what the Dashboard shows before the choice: the five fields, and above them the
    /// warnings that hold now, with the Codex version an "on" acknowledges.
    pub fn statement(
        &self,
        definition: &CapabilityDef,
        locale: Option<&str>,
    ) -> Result<Value, Undecodable> {
        let view = self.view();
        let warnings = self.warnings(definition, Some(&view));
        let Value::Object(mut statement) =
            self.catalogs.statement(definition, locale, &warnings)?
        else {
            return Ok(Value::Null);
        };
        statement.insert(
            "engine_version".into(),
            maybe_text(engine_version(&view).as_deref()),
        );
        let check = self.check(definition, Some(&view), None, None);
        statement.insert("check".into(), check);
        Ok(Value::Object(statement))
    }

    /// `listing()`: every capability as a surface shows it, in `registry.SHOWN_ORDER`.
    pub fn listing(&self) -> Value {
        let sending = self.edges.sending_points();
        let view = self.view();
        let policy = self.policy();
        let states = self.current(Some(&view), Some(&policy));
        let fallback = Meta {
            generation: 0,
            global_hourly: GLOBAL_HOURLY,
        };
        let (rows, meta) = match self.state.arming() {
            Ok(rows) => match self.state.meta() {
                Ok(meta) => (rows, meta),
                Err(_) => (Vec::new(), fallback),
            },
            Err(_) => (Vec::new(), fallback),
        };
        let mut shown: Vec<Value> = Vec::new();
        // Read once for the whole list, which every snapshot with the page in front reads again.
        let table = self.table(&view);
        let checked = self.checked(Some(&view));
        let mut on = 0;
        for definition in shown_in_order(self.registry) {
            let row = row_of(&rows, &definition.id);
            let off = row.map_or(ArmingState::Off, |row| row.state) == ArmingState::Off;
            let state_now = states.state_of(&definition.id);
            if state_now == ArmingState::Armed {
                on += 1;
            }
            let mut points: Vec<&str> = definition
                .points
                .iter()
                .map(|point| point.as_str())
                .collect();
            points.sort_unstable();
            points.dedup();
            let measurements: Vec<&str> = definition
                .narrowed_by
                .iter()
                .chain(definition.measurements.iter())
                .map(|each| each.as_str())
                .collect();
            shown.push(record([
                ("id", text(&definition.id)),
                (
                    "stored",
                    text(row.map_or(ArmingState::Off, |row| row.state).as_str()),
                ),
                ("state", text(state_now.as_str())),
                (
                    "since",
                    row.and_then(|row| row.since)
                        .map_or(Value::Null, Value::from),
                ),
                (
                    "by",
                    maybe_text(row.and_then(|row| row.actor).map(|actor| actor.as_str())),
                ),
                (
                    "reason",
                    if off {
                        maybe_text(row.and_then(|row| row.reason).map(|reason| reason.as_str()))
                    } else {
                        Value::Null
                    },
                ),
                ("keep_on", Value::Bool(row.is_some_and(|row| row.keep_on))),
                (
                    "send_again",
                    Value::Bool(row.is_some_and(|row| row.send_again)),
                ),
                (
                    "notice",
                    if off {
                        Value::Null
                    } else {
                        maybe_text(row.and_then(|row| row.reason).map(|reason| reason.as_str()))
                    },
                ),
                ("resends", Value::Bool(definition.resends)),
                (
                    "send_again_offered",
                    Value::Bool(offers_send_again(definition, &sending)),
                ),
                ("revision", int(definition.revision)),
                (
                    "read_revision",
                    maybe_int(row.and_then(|row| row.statement_revision)),
                ),
                (
                    "acknowledged_version",
                    maybe_text(row.and_then(|row| row.engine_version.as_deref())),
                ),
                (
                    "warnings",
                    warning_texts(&warnings_for(definition, &view, &table, true, &checked)),
                ),
                (
                    "confirmed_warnings",
                    warning_texts(&row.map(|row| row.warnings.clone()).unwrap_or_default()),
                ),
                // v0.6.22: the grade the statement's line says (autocheck.grade), a closed word.
                (
                    "check",
                    match self.check(definition, Some(&view), Some(&table), Some(&checked)) {
                        Value::Object(map) => map.get("grade").cloned().unwrap_or(Value::Null),
                        _ => Value::Null,
                    },
                ),
                ("kind", text(definition.kind.as_str())),
                ("requires", texts(&definition.requires)),
                (
                    "requires_off",
                    texts(
                        &self
                            .registry
                            .requires(&definition.id)
                            .into_iter()
                            .filter(|other| states.state_of(other) != ArmingState::Armed)
                            .collect::<Vec<_>>(),
                    ),
                ),
                ("departs_from", texts(&departs(definition, row))),
                ("compat", maybe_text(definition.compat.as_deref())),
                ("measurements", texts(&measurements)),
                ("points", texts(&points)),
                (
                    "sends",
                    Value::Bool(match definition.sends {
                        Some(flag) => flag,
                        None => definition
                            .points
                            .iter()
                            .any(|point| sending.contains(point)),
                    }),
                ),
                (
                    "ceilings",
                    match definition.ceilings {
                        None => Value::Null,
                        Some(ceilings) => record([
                            ("per_day", int(ceilings.per_day)),
                            ("per_conversation", int(ceilings.per_conversation)),
                        ]),
                    },
                ),
                ("options", self.options_of(definition)),
                ("rules_editor", Value::Bool(definition.rules_editor)),
                ("samples", Value::Bool(definition.samples)),
            ]));
        }
        record([
            ("generation", int(meta.generation)),
            ("global_hourly", int(meta.global_hourly)),
            ("global_hourly_default", int(GLOBAL_HOURLY)),
            (
                "engine_version",
                maybe_text(engine_version(&view).as_deref()),
            ),
            ("policy", policy.as_json()),
            ("on", int(on)),
            ("capabilities", Value::Array(shown)),
        ])
    }
}

/// `registry.get(capability)` for a wire value: only a text names a capability.
fn registry_get<'r>(registry: &'r Registry, capability: &Value) -> Option<&'r CapabilityDef> {
    str_of(capability).and_then(|id| registry.get(id))
}

/// What `arm` is asked, as the wire hands it: every word a JSON value, checked as the tag checks it.
#[derive(Clone, Debug)]
pub struct ArmRequest {
    pub capability: Value,
    pub state: Value,
    pub revision: Value,
    pub generation: Value,
    pub acknowledged_version: Value,
    pub warnings: Value,
    pub also: Value,
    pub keep_on: Value,
    pub actor: Value,
}

impl ArmRequest {
    fn capability_def<'r>(&self, registry: &'r Registry) -> Option<&'r CapabilityDef> {
        registry_get(registry, &self.capability)
    }
}

/// What `set_keep_on` is asked.
#[derive(Clone, Debug)]
pub struct KeepRequest {
    pub capability: Value,
    pub keep_on: Value,
    pub send_again: Value,
    pub generation: Value,
    pub confirmed: Value,
    pub actor: Value,
}
