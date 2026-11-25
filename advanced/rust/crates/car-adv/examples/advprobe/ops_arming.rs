//! `arming.scenario`: a scenario run through car-adv's `Arming` over an in-memory stand-in for the advanced state and stubs for
//! what arming reaches through `seam::Edges` - the same stand-ins, with the same semantics, that tests/rustdiff/arming_scenarios.py
//! writes in Python. The answer is `{"results": [...], "log": [...], "state": {...}}`; the diff holds all three equal.

use std::cell::RefCell;
use std::collections::{BTreeMap, BTreeSet};
use std::path::{Path, PathBuf};
use std::rc::Rc;
use std::sync::Arc;

use car_adv::arming::{
    self, ArmRequest, Arming, CoreView, KeepRequest, Setup, States, engine_version,
};
use car_adv::autocheck::Results;
use car_adv::jsonx::{int, text, texts};
use car_adv::measured::Table;
use car_adv::policy::Policy;
use car_adv::registry::{self, CapabilityDef, Registry};
use car_adv::seam::{
    ArmRow, ContinuationRow, Edges, Meta, Move, OverrideRow, ResetRule, StateFault, StatePort,
    StateResult, Unavailable,
};
use car_adv::state::seam::Tokens;
use car_adv::state::session::AdvancedState;
use car_adv::statement::Catalogs;
use car_adv::vocabulary::{
    Actor, ArmingState, ArmingWarning, AutoResult, ContinuationReason, Measurement, OffReason,
    OptionKey, OverrideKind, PromptReason, Refusal, RuleReason, RuleState, SteerReason, Verdict,
    WordingKey, parse,
};
use car_machine::json::{Map, Str, Value};
use car_policy::plug::Point;

use crate::util::{Failure, Out, arg, bad, list, map, text as as_text};

type Log = Rc<RefCell<Vec<Value>>>;

fn push(log: &Log, items: Vec<Value>) {
    log.borrow_mut().push(Value::Array(items));
}

fn opt_f(value: Option<f64>) -> Value {
    value.map_or(Value::Null, Value::from)
}

fn opt_s(value: Option<&str>) -> Value {
    value.map_or(Value::Null, text)
}

fn get<'m>(map: &'m Map, name: &str) -> &'m Value {
    map.get(name).unwrap_or(&Value::Null)
}

fn float_of(value: &Value) -> f64 {
    match value {
        Value::Float(each) => *each,
        Value::Int(each) => each.as_i64().map_or(0.0, |n| n as f64),
        _ => 0.0,
    }
}

fn obj(pairs: Vec<(&str, Value)>) -> Value {
    let mut map = Map::new();
    for (key, value) in pairs {
        map.insert(Str::from(key), value);
    }
    Value::Object(map)
}

// ------------------------------------------------------------------------------------------------ the environment
struct Env {
    value: Map,
    clock: f64,
}

type Shared = Rc<RefCell<Env>>;

fn table_of(rows: &Value) -> Table {
    let mut table = Table::new();
    if let Value::Array(rows) = rows {
        for row in rows {
            if let Value::Array(parts) = row
                && let (Some(Value::Str(m)), Some(Value::Str(v)), Some(Value::Str(e))) =
                    (parts.first(), parts.get(1), parts.get(2))
                && let (Some(m), Some(v)) = (
                    m.as_str().and_then(parse::<Measurement>),
                    v.as_str().and_then(parse::<Verdict>),
                )
            {
                table.insert(m, (v, e.as_str().unwrap_or("").to_owned()));
            }
        }
    }
    table
}

fn results_of(rows: &Value) -> Results {
    let mut found = Results::new();
    if let Value::Array(rows) = rows {
        for row in rows {
            if let Value::Array(parts) = row
                && let (Some(Value::Str(m)), Some(Value::Str(r))) = (parts.first(), parts.get(1))
                && let (Some(m), Some(r)) = (
                    m.as_str().and_then(parse::<Measurement>),
                    r.as_str().and_then(parse::<AutoResult>),
                )
            {
                found.insert(m, r);
            }
        }
    }
    found
}

struct FakeEdges {
    env: Shared,
    log: Log,
}

impl FakeEdges {
    fn setting(&self, name: &str) -> Value {
        get(&self.env.borrow().value, name).clone()
    }
}

fn raises(value: &Value) -> bool {
    matches!(value, Value::Str(each) if each.as_str() == Some("raises"))
}

impl Edges for FakeEdges {
    fn default_view(&self) -> Result<Value, Unavailable> {
        push(&self.log, vec![text("default_view")]);
        let found = self.setting("default_view");
        if raises(&found) {
            Err(Unavailable)
        } else {
            Ok(found)
        }
    }

    fn default_live_view(&self) -> Result<Value, Unavailable> {
        push(&self.log, vec![text("default_live_view")]);
        let found = self.setting("default_live");
        if raises(&found) {
            Err(Unavailable)
        } else {
            Ok(found)
        }
    }

    fn table_for(&self, engine: Option<&str>) -> Result<Table, Unavailable> {
        push(&self.log, vec![text("table_for"), opt_s(engine)]);
        let found = self.setting("table_for");
        if raises(&found) {
            Err(Unavailable)
        } else {
            Ok(table_of(&found))
        }
    }

    fn checked_for(&self, engine: Option<&str>) -> Result<Results, Unavailable> {
        push(&self.log, vec![text("checked_for"), opt_s(engine)]);
        let found = self.setting("checked");
        if raises(&found) {
            Err(Unavailable)
        } else {
            Ok(results_of(&found))
        }
    }

    fn sending_points(&self) -> Vec<Point> {
        match self.setting("sending") {
            Value::Array(items) => items
                .iter()
                .filter_map(|each| match each {
                    Value::Str(word) => word.as_str().and_then(Point::parse),
                    _ => None,
                })
                .collect(),
            _ => Vec::new(),
        }
    }

    fn hook_follow(&self, armed: bool) {
        push(&self.log, vec![text("hook_follow"), Value::Bool(armed)]);
    }

    fn power_tasks_follow(&self, armed: bool) {
        push(
            &self.log,
            vec![text("power_tasks_follow"), Value::Bool(armed)],
        );
    }

    fn account_forget(&self) {
        push(&self.log, vec![text("account_forget")]);
    }

    fn usage_touched(&self, key: OptionKey) -> Vec<i64> {
        push(&self.log, vec![text("usage_touched"), text(key.as_str())]);
        let word = key.as_str();
        if word.contains("five") {
            vec![300]
        } else if word.contains("weekly") {
            vec![10080]
        } else {
            Vec::new()
        }
    }

    fn usage_order_problem(
        &self,
        values: &BTreeMap<String, BTreeMap<OptionKey, i64>>,
        windows: &[i64],
    ) -> (Option<String>, Option<String>) {
        let shown: Vec<Value> = values
            .iter()
            .map(|(cap, options)| {
                let mut pairs: Vec<(&str, i64)> = options
                    .iter()
                    .map(|(key, value)| (key.as_str(), *value))
                    .collect();
                pairs.sort();
                Value::Array(vec![
                    text(cap),
                    Value::Array(
                        pairs
                            .into_iter()
                            .map(|(key, value)| Value::Array(vec![text(key), int(value)]))
                            .collect(),
                    ),
                ])
            })
            .collect();
        push(
            &self.log,
            vec![
                text("usage_order_problem"),
                Value::Array(shown),
                Value::Array(windows.iter().map(|each| int(*each)).collect()),
            ],
        );
        match self.setting("order") {
            Value::Str(word) if word.as_str() == Some("order") => (Some("order".to_owned()), None),
            Value::Str(word) if word.as_str() == Some("warn") => {
                (None, Some("stop_before_words".to_owned()))
            }
            _ => (None, None),
        }
    }

    fn usage_previews(&self, now: f64) -> Vec<(i64, Option<String>)> {
        push(&self.log, vec![text("usage_previews"), Value::from(now)]);
        vec![(300, Some("five words".to_owned())), (10080, None)]
    }

    fn wording_problem(&self, words: &Value) -> Option<String> {
        push(&self.log, vec![text("wording_problem"), words.clone()]);
        match words {
            Value::Str(each) => {
                let each = each.as_str().unwrap_or("");
                if car_machine::pytext::strip(each).is_empty() {
                    Some("empty".to_owned())
                } else if each.chars().count() > 30 {
                    Some("too_long".to_owned())
                } else if each.contains("bad") {
                    Some("marker".to_owned())
                } else {
                    None
                }
            }
            _ => Some("empty".to_owned()),
        }
    }

    fn wording_limit(&self) -> i64 {
        match self.setting("wording_limit") {
            Value::Int(each) => each.as_i64().unwrap_or(0),
            _ => 0,
        }
    }

    fn wording_placeholders(&self) -> Vec<String> {
        match self.setting("placeholders") {
            Value::Array(items) => items
                .iter()
                .filter_map(|each| match each {
                    Value::Str(word) => word.as_str().map(str::to_owned),
                    _ => None,
                })
                .collect(),
            _ => Vec::new(),
        }
    }
}

// ------------------------------------------------------------------------------------------------ the state stand-in
struct Inner {
    rows: Vec<(String, Map)>,
    generation: i64,
    hourly: i64,
    faults: BTreeMap<String, String>,
    spends: Vec<(String, String, f64)>,
    overrides: Vec<Map>,
    resent: BTreeSet<String>,
    payers: BTreeMap<String, Vec<(String, f64)>>,
    reset_rules: Vec<Map>,
    credits: bool,
    continuations: Vec<Map>,
    options: Map,
    wordings: Map,
    rules: Vec<Map>,
    hits: Vec<(i64, i64)>,
    samples: Vec<Value>,
    ever: BTreeSet<String>,
    next_rule: i64,
}

struct FakeState {
    inner: RefCell<Inner>,
    registry: Rc<Registry>,
    log: Log,
}

fn fault_of(word: &str) -> Option<StateFault> {
    match word {
        "state" => Some(StateFault::State),
        "stale" => Some(StateFault::Stale),
        other => other
            .strip_prefix("refused:")
            .and_then(parse::<Refusal>)
            .map(StateFault::Refused),
    }
}

fn words_of(warnings: &[ArmingWarning]) -> Value {
    texts(
        &warnings
            .iter()
            .map(|word| word.as_str())
            .collect::<Vec<_>>(),
    )
}

impl FakeState {
    fn call(&self, name: &str, args: Vec<Value>) -> StateResult<()> {
        let mut entry = vec![text(name)];
        entry.extend(args);
        push(&self.log, entry);
        match self
            .inner
            .borrow()
            .faults
            .get(name)
            .and_then(|word| fault_of(word))
        {
            Some(fault) => Err(fault),
            None => Ok(()),
        }
    }

    fn stale(&self, generation: Option<i64>) -> StateResult<()> {
        match generation {
            Some(wanted) if wanted != self.inner.borrow().generation => Err(StateFault::Stale),
            _ => Ok(()),
        }
    }

    /// `generation is not None and generation != self.generation`, for a generation of any type.
    fn stale_value(&self, generation: &Value) -> StateResult<()> {
        match generation {
            Value::Null => Ok(()),
            Value::Int(each) if each.as_i64() == Some(self.inner.borrow().generation) => Ok(()),
            _ => Err(StateFault::Stale),
        }
    }

    #[allow(clippy::too_many_arguments)]
    fn write(
        &self,
        cap: &str,
        state: &str,
        actor: &str,
        reason: Option<&str>,
        revision: &Value,
        engine: Option<&str>,
        warnings: Value,
        at: f64,
        keep: bool,
    ) {
        let on = state != "off";
        let row = obj(vec![
            ("state", text(state)),
            ("since", if on { Value::from(at) } else { Value::Null }),
            ("actor", text(actor)),
            ("reason", opt_s(reason)),
            (
                "statement_revision",
                if on { revision.clone() } else { Value::Null },
            ),
            (
                "engine_version",
                if on { opt_s(engine) } else { Value::Null },
            ),
            (
                "warnings",
                if on {
                    warnings
                } else {
                    Value::Array(Vec::new())
                },
            ),
            ("keep_on", Value::Bool(keep)),
            ("send_again", Value::Bool(false)),
        ]);
        let Value::Object(row) = row else { return };
        let mut inner = self.inner.borrow_mut();
        match inner.rows.iter_mut().find(|(held, _)| held == cap) {
            Some(held) => held.1 = row,
            None => inner.rows.push((cap.to_owned(), row)),
        }
        inner.ever.insert(cap.to_owned());
    }

    fn row_state(&self, cap: &str) -> Option<String> {
        self.inner
            .borrow()
            .rows
            .iter()
            .find(|(held, _)| held == cap)
            .and_then(|(_, row)| match get(row, "state") {
                Value::Str(word) => word.as_str().map(str::to_owned),
                _ => None,
            })
    }

    fn dump(&self) -> Value {
        let inner = self.inner.borrow();
        obj(vec![
            (
                "rows",
                Value::Array(
                    inner
                        .rows
                        .iter()
                        .map(|(cap, row)| Value::Array(vec![text(cap), Value::Object(row.clone())]))
                        .collect(),
                ),
            ),
            ("generation", int(inner.generation)),
            ("global_hourly", int(inner.hourly)),
            (
                "overrides",
                Value::Array(
                    inner
                        .overrides
                        .iter()
                        .map(|each| Value::Object(each.clone()))
                        .collect(),
                ),
            ),
            ("credits", Value::Bool(inner.credits)),
            ("options", Value::Object(inner.options.clone())),
            ("wordings", Value::Object(inner.wordings.clone())),
            (
                "rules",
                Value::Array(
                    inner
                        .rules
                        .iter()
                        .map(|each| Value::Object(each.clone()))
                        .collect(),
                ),
            ),
            (
                "ever",
                texts(&inner.ever.iter().cloned().collect::<Vec<_>>()),
            ),
        ])
    }
}

fn f(value: f64) -> Value {
    Value::from(value)
}

/// What a scenario's runner asks of the state it runs over: the port `Arming` is given, the generation `@gen` means, and
/// the state left.
trait Probe {
    fn port(&self) -> &dyn StatePort;
    fn generation(&self) -> i64;
    fn dump(&self) -> Value;
}

impl Probe for FakeState {
    fn port(&self) -> &dyn StatePort {
        self
    }

    fn generation(&self) -> i64 {
        self.inner.borrow().generation
    }

    fn dump(&self) -> Value {
        FakeState::dump(self)
    }
}

#[derive(Debug)]
struct Links;

impl car_config::Links for Links {
    fn is_symlink(&self, path: &Path) -> bool {
        car_platform::links::is_symlink(path)
    }
}

/// The tokens `Arming` never asks the state for: a counter, as the diffs of the store stand them in.
struct Counter(std::sync::Mutex<u64>);

impl Tokens for Counter {
    fn hex(&self, count: usize) -> String {
        let mut held = self
            .0
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        *held += 1;
        format!("{:0>width$x}", *held, width = count * 2)
    }
}

/// Integration 5: the real `AdvancedState` on a home of its own (`<home>/rs`, where the reference uses `<home>/py`),
/// `Arming` over it as the tag's runs over the tag's, and the state left as the state's own readers say it.
struct Real {
    state: AdvancedState,
    ids: Vec<String>,
}

impl Real {
    fn new(home: &str, registry: &Registry, clock: f64) -> Result<Real, Failure> {
        let home = PathBuf::from(home).join("rs");
        std::fs::create_dir_all(&home).map_err(|_| Failure::new("OSError"))?;
        let no_env = |_: &str| None;
        let paths = car_config::Paths::new(
            Some(&home.to_string_lossy()),
            &home.to_string_lossy(),
            &no_env,
            car_config::Os::here(false, Arc::new(Links)),
        )
        .map_err(|_| Failure::new("ConfigError"))?;
        let state = AdvancedState::new(
            paths,
            Arc::new(registry.clone()),
            Box::new(move || clock),
            Arc::new(Counter(std::sync::Mutex::new(0))),
        );
        let ids = registry
            .definitions
            .iter()
            .map(|each| each.id.clone())
            .collect();
        Ok(Real { state, ids })
    }
}

impl Probe for Real {
    fn port(&self) -> &dyn StatePort {
        &self.state
    }

    fn generation(&self) -> i64 {
        match self.state.meta() {
            Ok(row) => match row.get("generation") {
                Some(Value::Int(each)) => each.as_i64().unwrap_or(0),
                _ => 0,
            },
            Err(_) => 0,
        }
    }

    fn dump(&self) -> Value {
        let state = &self.state;
        let one = |name: &str, found: Result<Map, car_adv::state::errors::Error>| {
            (
                name.to_owned(),
                found.map_or_else(|error| text(error.class()), Value::Object),
            )
        };
        let many = |found: Result<Vec<Map>, car_adv::state::errors::Error>| {
            found.map_or_else(
                |error| text(error.class()),
                |rows| Value::Array(rows.into_iter().map(Value::Object).collect()),
            )
        };
        let keyed = |each: &dyn Fn(&Value) -> Result<Map, car_adv::state::errors::Error>| {
            Value::Object(
                self.ids
                    .iter()
                    .map(|id| {
                        (
                            Str::from(id.as_str()),
                            each(&text(id)).map_or_else(|error| text(error.class()), Value::Object),
                        )
                    })
                    .collect(),
            )
        };
        let (_, arming) = one("arming", state.arming());
        let (_, meta) = one("meta", state.meta());
        // READING is a frozenset in the reference: with no file its keys come in a hash order no run repeats.
        let (_, reading) = one(
            "reading",
            state.reading().map(|row| {
                let mut sorted: Vec<(Str, Value)> = row.into_iter().collect();
                sorted.sort_by(|a, b| a.0.cmp(&b.0));
                sorted.into_iter().collect()
            }),
        );
        obj(vec![
            ("arming", arming),
            ("meta", meta),
            ("options", keyed(&|id| state.options(id))),
            ("wordings", keyed(&|id| state.wordings(id))),
            ("rules", many(state.rules())),
            ("journal", many(state.journal(&Value::Null, &int(500)))),
            ("reading", reading),
        ])
    }
}

impl StatePort for FakeState {
    fn arming(&self) -> StateResult<Vec<(String, ArmRow)>> {
        self.call("arming", vec![])?;
        let inner = self.inner.borrow();
        let mut found = Vec::new();
        for (cap, row) in &inner.rows {
            if self.registry.get(cap).is_none() {
                continue;
            }
            let word = |name: &str| match get(row, name) {
                Value::Str(each) => each.as_str().map(str::to_owned),
                _ => None,
            };
            found.push((
                cap.clone(),
                ArmRow {
                    state: word("state")
                        .and_then(|w| parse::<ArmingState>(&w))
                        .unwrap_or(ArmingState::Off),
                    since: match get(row, "since") {
                        Value::Null => None,
                        other => Some(float_of(other)),
                    },
                    actor: word("actor").and_then(|w| parse::<Actor>(&w)),
                    reason: word("reason").and_then(|w| parse::<OffReason>(&w)),
                    statement_revision: match get(row, "statement_revision") {
                        Value::Int(each) => each.as_i64(),
                        _ => None,
                    },
                    engine_version: word("engine_version"),
                    warnings: match get(row, "warnings") {
                        Value::Array(items) => items
                            .iter()
                            .filter_map(|each| match each {
                                Value::Str(w) => w.as_str().and_then(parse::<ArmingWarning>),
                                _ => None,
                            })
                            .collect(),
                        _ => Vec::new(),
                    },
                    keep_on: matches!(get(row, "keep_on"), Value::Bool(true)),
                    send_again: matches!(get(row, "send_again"), Value::Bool(true)),
                },
            ));
        }
        Ok(found)
    }

    fn meta(&self) -> StateResult<Meta> {
        self.call("meta", vec![])?;
        let inner = self.inner.borrow();
        Ok(Meta {
            generation: inner.generation,
            global_hourly: inner.hourly,
        })
    }

    fn ever_moved(&self, capability: &str) -> StateResult<bool> {
        self.call("ever_moved", vec![text(capability)])?;
        Ok(self.inner.borrow().ever.contains(capability))
    }

    fn move_to(
        &self,
        capability: &str,
        state: ArmingState,
        actor: Actor,
        reason: Option<OffReason>,
        revision: Option<&Value>,
        engine_version: Option<&str>,
        warnings: Option<&[ArmingWarning]>,
        generation: Option<i64>,
        at: f64,
    ) -> StateResult<(bool, i64)> {
        self.call(
            "move",
            vec![
                text(capability),
                text(state.as_str()),
                text(actor.as_str()),
                opt_s(reason.map(|each| each.as_str())),
                revision.cloned().unwrap_or(Value::Null),
                opt_s(engine_version),
                warnings.map_or(Value::Null, words_of),
                generation.map_or(Value::Null, int),
                f(at),
            ],
        )?;
        self.stale(generation)?;
        let held = self.row_state(capability);
        if state == ArmingState::Off {
            if held.is_none() || held.as_deref() == Some("off") {
                return Ok((false, self.inner.borrow().generation));
            }
            self.write(
                capability,
                "off",
                actor.as_str(),
                reason.map(|each| each.as_str()),
                &Value::Null,
                None,
                Value::Null,
                at,
                false,
            );
        } else {
            self.write(
                capability,
                state.as_str(),
                actor.as_str(),
                None,
                revision.unwrap_or(&Value::Null),
                engine_version,
                words_of(warnings.unwrap_or(&[])),
                at,
                false,
            );
        }
        let mut inner = self.inner.borrow_mut();
        inner.generation += 1;
        Ok((true, inner.generation))
    }

    fn move_set(
        &self,
        moves: &[Move],
        actor: Actor,
        generation: i64,
        at: f64,
        keep: &[String],
    ) -> StateResult<(i64, i64)> {
        let shown: Vec<Value> = moves
            .iter()
            .map(|each| {
                Value::Array(vec![
                    text(&each.capability),
                    text(each.state.as_str()),
                    each.revision.clone(),
                    opt_s(each.engine_version.as_deref()),
                    words_of(&each.warnings),
                ])
            })
            .collect();
        self.call(
            "move_set",
            vec![
                Value::Array(shown),
                text(actor.as_str()),
                int(generation),
                f(at),
                texts(keep),
            ],
        )?;
        self.stale(Some(generation))?;
        for each in moves {
            self.write(
                &each.capability,
                each.state.as_str(),
                actor.as_str(),
                None,
                &each.revision,
                each.engine_version.as_deref(),
                words_of(&each.warnings),
                at,
                keep.contains(&each.capability),
            );
        }
        let mut inner = self.inner.borrow_mut();
        inner.generation += 1;
        Ok((moves.len() as i64, inner.generation))
    }

    fn all_off(&self, actor: Actor, reason: OffReason, at: f64) -> StateResult<(i64, i64)> {
        self.call(
            "all_off",
            vec![text(actor.as_str()), text(reason.as_str()), f(at)],
        )?;
        let caps: Vec<String> = self
            .inner
            .borrow()
            .rows
            .iter()
            .filter(|(_, row)| !matches!(get(row, "state"), Value::Str(word) if word.as_str() == Some("off")))
            .map(|(cap, _)| cap.clone())
            .collect();
        for cap in &caps {
            self.write(
                cap,
                "off",
                actor.as_str(),
                Some(reason.as_str()),
                &Value::Null,
                None,
                Value::Null,
                at,
                false,
            );
        }
        let mut inner = self.inner.borrow_mut();
        if !caps.is_empty() {
            inner.generation += 1;
        }
        Ok((caps.len() as i64, inner.generation))
    }

    fn set_keep_on(
        &self,
        capability: &str,
        keep_on: bool,
        send_again: bool,
        actor: Actor,
        generation: Option<i64>,
        at: f64,
    ) -> StateResult<i64> {
        self.call(
            "set_keep_on",
            vec![
                text(capability),
                Value::Bool(keep_on),
                Value::Bool(send_again),
                text(actor.as_str()),
                generation.map_or(Value::Null, int),
                f(at),
            ],
        )?;
        self.stale(generation)?;
        let held = self.row_state(capability);
        if held.is_none() || held.as_deref() == Some("off") {
            return Err(StateFault::Refused(Refusal::NotOn));
        }
        let mut inner = self.inner.borrow_mut();
        if let Some((_, row)) = inner.rows.iter_mut().find(|(held, _)| held == capability) {
            row.insert(Str::from("keep_on"), Value::Bool(keep_on));
            row.insert(Str::from("send_again"), Value::Bool(keep_on && send_again));
        }
        inner.generation += 1;
        Ok(inner.generation)
    }

    fn send_again_off(&self, capability: &str, reason: OffReason, at: f64) -> StateResult<bool> {
        self.call(
            "send_again_off",
            vec![text(capability), text(reason.as_str()), f(at)],
        )?;
        let mut inner = self.inner.borrow_mut();
        let Some((_, row)) = inner.rows.iter_mut().find(|(held, _)| held == capability) else {
            return Ok(false);
        };
        if !matches!(get(row, "send_again"), Value::Bool(true)) {
            return Ok(false);
        }
        row.insert(Str::from("send_again"), Value::Bool(false));
        row.insert(Str::from("reason"), text(reason.as_str()));
        Ok(true)
    }

    fn note_kept(&self, capability: &str, reason: OffReason, at: f64) -> StateResult<bool> {
        self.call(
            "note_kept",
            vec![text(capability), text(reason.as_str()), f(at)],
        )?;
        let mut inner = self.inner.borrow_mut();
        let Some((_, row)) = inner.rows.iter_mut().find(|(held, _)| held == capability) else {
            return Ok(false);
        };
        if matches!(get(row, "state"), Value::Str(word) if word.as_str() == Some("off")) {
            return Ok(false);
        }
        row.insert(Str::from("reason"), text(reason.as_str()));
        Ok(true)
    }

    fn set_global_hourly(
        &self,
        value: i64,
        generation: i64,
        actor: Actor,
        at: f64,
    ) -> StateResult<i64> {
        self.call(
            "set_global_hourly",
            vec![int(value), int(generation), text(actor.as_str()), f(at)],
        )?;
        self.stale(Some(generation))?;
        let mut inner = self.inner.borrow_mut();
        inner.hourly = value;
        inner.generation += 1;
        Ok(inner.generation)
    }

    fn spends_since(&self, capability: &str, since: f64) -> StateResult<Vec<(String, Vec<f64>)>> {
        self.call("spends_since", vec![text(capability), f(since)])?;
        let mut found: Vec<(String, Vec<f64>)> = Vec::new();
        for (cap, record, time) in &self.inner.borrow().spends {
            if cap == capability && *time >= since {
                match found.iter_mut().find(|(held, _)| held == record) {
                    Some(held) => held.1.push(*time),
                    None => found.push((record.clone(), vec![*time])),
                }
            }
        }
        Ok(found)
    }

    fn open_overrides(&self, kind: OverrideKind) -> StateResult<Vec<OverrideRow>> {
        self.call("open_overrides", vec![text(kind.as_str())])?;
        Ok(self
            .inner
            .borrow()
            .overrides
            .iter()
            .filter(|each| {
                matches!(get(each, "kind"), Value::Str(word) if word.as_str() == Some(kind.as_str()))
                    && !matches!(get(each, "used"), Value::Bool(true))
            })
            .map(|each| OverrideRow {
                interruption_id: match get(each, "interruption_id") {
                    Value::Str(word) => word.as_str().unwrap_or("").to_owned(),
                    _ => String::new(),
                },
                capability: match get(each, "capability") {
                    Value::Str(word) => word.as_str().unwrap_or("").to_owned(),
                    _ => String::new(),
                },
                created_at: float_of(get(each, "created_at")),
            })
            .collect())
    }

    fn use_override(&self, key: &str, capability: &str, at: f64) -> StateResult<()> {
        self.call("use_override", vec![text(key), text(capability), f(at)])?;
        let mut inner = self.inner.borrow_mut();
        for each in inner.overrides.iter_mut() {
            let same = matches!(get(each, "interruption_id"), Value::Str(word) if word.as_str() == Some(key))
                && matches!(get(each, "capability"), Value::Str(word) if word.as_str() == Some(capability))
                && !matches!(get(each, "used"), Value::Bool(true));
            if same {
                each.insert(Str::from("used"), Value::Bool(true));
                break;
            }
        }
        Ok(())
    }

    fn resent(&self, key: &str) -> StateResult<bool> {
        self.call("resent", vec![text(key)])?;
        Ok(self.inner.borrow().resent.contains(key))
    }

    fn payers(&self, key: &str, claimed_at: Option<f64>) -> StateResult<Vec<(String, Vec<f64>)>> {
        self.call("payers", vec![text(key), opt_f(claimed_at)])?;
        let mut found: Vec<(String, Vec<f64>)> = Vec::new();
        for (cap, time) in self.inner.borrow().payers.get(key).into_iter().flatten() {
            match found.iter_mut().find(|(held, _)| held == cap) {
                Some(held) => held.1.push(*time),
                None => found.push((cap.clone(), vec![*time])),
            }
        }
        Ok(found)
    }

    fn reset_rules(&self) -> StateResult<Vec<ResetRule>> {
        self.call("reset_rules", vec![])?;
        Ok(self
            .inner
            .borrow()
            .reset_rules
            .iter()
            .map(|each| ResetRule {
                rule_id: get(each, "rule_id").clone(),
                capability: match get(each, "capability") {
                    Value::Str(word) => word.as_str().unwrap_or("").to_owned(),
                    _ => String::new(),
                },
                launching_at: match get(each, "launching_at") {
                    Value::Null => None,
                    other => Some(float_of(other)),
                },
                record_state: match get(each, "record_state") {
                    Value::Str(word) => word.as_str().map(str::to_owned),
                    _ => None,
                },
            })
            .collect())
    }

    fn end_rule(
        &self,
        rule_id: &Value,
        state: RuleState,
        reason: RuleReason,
        at: f64,
    ) -> StateResult<()> {
        self.call(
            "end_rule",
            vec![
                rule_id.clone(),
                text(state.as_str()),
                text(reason.as_str()),
                f(at),
            ],
        )
    }

    fn reading_has_credits(&self) -> StateResult<bool> {
        self.call("reading", vec![])?;
        Ok(self.inner.borrow().credits)
    }

    fn clear_reading(&self) -> StateResult<()> {
        self.call(
            "set_reading",
            vec![Value::Array(vec![
                Value::Array(vec![text("credits"), Value::Null]),
                Value::Array(vec![text("expiry_known"), Value::Null]),
                Value::Array(vec![text("nearest_expiry"), Value::Null]),
            ])],
        )?;
        self.inner.borrow_mut().credits = false;
        Ok(())
    }

    fn end_prompts(&self, reason: PromptReason, at: f64) -> StateResult<()> {
        self.call("end_prompts", vec![text(reason.as_str()), f(at)])
    }

    fn end_requested_steers(&self, reason: SteerReason, at: f64) -> StateResult<()> {
        self.call("end_requested_steers", vec![text(reason.as_str()), f(at)])
    }

    fn continuations_pending(&self) -> StateResult<Vec<ContinuationRow>> {
        self.call("continuations", vec![Value::Bool(true)])?;
        Ok(self
            .inner
            .borrow()
            .continuations
            .iter()
            .map(|each| ContinuationRow {
                capability: match get(each, "capability") {
                    Value::Str(word) => word.as_str().unwrap_or("").to_owned(),
                    _ => String::new(),
                },
                record_state: match get(each, "record_state") {
                    Value::Str(word) => word.as_str().map(str::to_owned),
                    _ => None,
                },
            })
            .collect())
    }

    fn end_continuations(
        &self,
        reason: ContinuationReason,
        capability: &str,
        at: f64,
    ) -> StateResult<()> {
        self.call(
            "end_continuations",
            vec![text(reason.as_str()), text(capability), f(at)],
        )
    }

    fn options(&self, capability: &str) -> StateResult<BTreeMap<OptionKey, i64>> {
        self.call("options", vec![text(capability)])?;
        let mut found = BTreeMap::new();
        if let Value::Object(held) = get(&self.inner.borrow().options, capability) {
            for (key, value) in held {
                if let (Some(key), Value::Int(value)) =
                    (key.as_str().and_then(parse::<OptionKey>), value)
                    && let Some(value) = value.as_i64()
                {
                    found.insert(key, value);
                }
            }
        }
        Ok(found)
    }

    fn wordings(&self, capability: &str) -> StateResult<BTreeMap<WordingKey, Option<String>>> {
        self.call("wordings", vec![text(capability)])?;
        let mut found = BTreeMap::new();
        if let Value::Object(held) = get(&self.inner.borrow().wordings, capability) {
            for (key, value) in held {
                if let Some(key) = key.as_str().and_then(parse::<WordingKey>) {
                    found.insert(
                        key,
                        match value {
                            Value::Str(words) => words.as_str().map(str::to_owned),
                            _ => None,
                        },
                    );
                }
            }
        }
        Ok(found)
    }

    fn set_option(
        &self,
        capability: &str,
        key: &Value,
        value: &Value,
        generation: &Value,
        actor: Actor,
        at: f64,
    ) -> StateResult<i64> {
        self.call(
            "set_option",
            vec![
                text(capability),
                key.clone(),
                value.clone(),
                generation.clone(),
                text(actor.as_str()),
                f(at),
            ],
        )?;
        self.stale_value(generation)?;
        let option = match key {
            Value::Str(word) => word.as_str().and_then(parse::<OptionKey>).and_then(|each| {
                self.registry
                    .get(capability)
                    .and_then(|def| def.option(each))
            }),
            _ => None,
        };
        let taken = match (option, value) {
            (Some(option), Value::Int(number)) => number
                .as_i64()
                .filter(|n| option.takes(*n))
                .map(|n| (option.key, n)),
            _ => None,
        };
        let Some((key, number)) = taken else {
            return Err(StateFault::Refused(Refusal::OptionInvalid));
        };
        let mut inner = self.inner.borrow_mut();
        let held = inner
            .options
            .entry(Str::from(capability))
            .or_insert_with(|| Value::Object(Map::new()));
        if let Value::Object(held) = held {
            held.insert(Str::from(key.as_str()), int(number));
        }
        inner.generation += 1;
        Ok(inner.generation)
    }

    fn set_wording(
        &self,
        capability: &str,
        key: &Value,
        words: &Value,
        generation: &Value,
        actor: Actor,
        at: f64,
    ) -> StateResult<i64> {
        self.call(
            "set_wording",
            vec![
                text(capability),
                key.clone(),
                words.clone(),
                generation.clone(),
                text(actor.as_str()),
                f(at),
            ],
        )?;
        self.stale_value(generation)?;
        let allowed = self
            .registry
            .get(capability)
            .is_some_and(|def| matches!(key, Value::Str(word) if def.wordings.iter().any(|each| Some(each.as_str()) == word.as_str())));
        if !allowed {
            return Err(StateFault::Refused(Refusal::OptionInvalid));
        }
        let mut inner = self.inner.borrow_mut();
        let held = inner
            .wordings
            .entry(Str::from(capability))
            .or_insert_with(|| Value::Object(Map::new()));
        if let (Value::Object(held), Value::Str(name)) = (held, key) {
            held.insert(name.clone(), words.clone());
        }
        inner.generation += 1;
        Ok(inner.generation)
    }

    fn add_rule(
        &self,
        tag: &Value,
        status_from: &Value,
        status_to: &Value,
        category: &Value,
        generation: &Value,
        actor: Actor,
        at: f64,
    ) -> StateResult<(Value, i64)> {
        self.call(
            "add_rule",
            vec![
                tag.clone(),
                status_from.clone(),
                status_to.clone(),
                category.clone(),
                generation.clone(),
                text(actor.as_str()),
                f(at),
            ],
        )?;
        self.stale_value(generation)?;
        if !matches!(tag, Value::Str(word) if !word.is_empty()) {
            return Err(StateFault::Refused(Refusal::RuleShape));
        }
        let mut inner = self.inner.borrow_mut();
        if inner.rules.len() >= 10 {
            return Err(StateFault::Refused(Refusal::RulesFull));
        }
        inner.next_rule += 1;
        let rule = obj(vec![
            ("rule_id", int(inner.next_rule)),
            ("tag", tag.clone()),
            ("status_from", status_from.clone()),
            ("status_to", status_to.clone()),
            ("category", category.clone()),
            ("known", Value::Bool(false)),
        ]);
        if let Value::Object(map) = &rule {
            inner.rules.push(map.clone());
        }
        inner.generation += 1;
        Ok((rule, inner.generation))
    }

    fn remove_rule(
        &self,
        rule: &Value,
        generation: &Value,
        actor: Actor,
        at: f64,
    ) -> StateResult<i64> {
        self.call(
            "remove_rule",
            vec![
                rule.clone(),
                generation.clone(),
                text(actor.as_str()),
                f(at),
            ],
        )?;
        self.stale_value(generation)?;
        let mut inner = self.inner.borrow_mut();
        let before = inner.rules.len();
        inner.rules.retain(|each| get(each, "rule_id") != rule);
        if inner.rules.len() == before {
            return Err(StateFault::Refused(Refusal::UnknownRule));
        }
        inner.generation += 1;
        Ok(inner.generation)
    }

    fn rules(&self) -> StateResult<Vec<Value>> {
        self.call("rules", vec![])?;
        Ok(self
            .inner
            .borrow()
            .rules
            .iter()
            .map(|each| Value::Object(each.clone()))
            .collect())
    }

    fn rule_hits(&self, since: f64) -> StateResult<Vec<(Value, i64)>> {
        self.call("rule_hits", vec![f(since)])?;
        Ok(self
            .inner
            .borrow()
            .hits
            .iter()
            .map(|(rule, count)| (int(*rule), *count))
            .collect())
    }

    fn failure_samples(&self, since: f64) -> StateResult<Vec<Value>> {
        self.call("failure_samples", vec![f(since)])?;
        Ok(self.inner.borrow().samples.clone())
    }

    fn aggregated(&self, samples: &[Value]) -> Value {
        push(
            &self.log,
            vec![text("aggregated"), Value::Array(samples.to_vec())],
        );
        let tags: BTreeSet<String> = samples
            .iter()
            .filter_map(|sample| match sample {
                Value::Object(map) => match get(map, "tag") {
                    Value::Str(tag) => tag.as_str().map(str::to_owned),
                    _ => None,
                },
                _ => None,
            })
            .collect();
        obj(vec![
            ("count", int(samples.len() as i64)),
            ("tags", texts(&tags.into_iter().collect::<Vec<_>>())),
        ])
    }

    fn tag_is_valid(&self, tag: &str) -> bool {
        let mut chars = tag.chars();
        let Some(first) = chars.next() else {
            return false;
        };
        tag.chars().count() <= 64
            && first.is_ascii_alphabetic()
            && tag.chars().all(|each| each.is_ascii_alphanumeric())
    }
}

struct Core {
    records: Map,
    log: Log,
}

impl CoreView for Core {
    fn get(&self, key: &str) -> Result<Value, Unavailable> {
        push(&self.log, vec![text("core_get"), text(key)]);
        match self.records.get(key) {
            Some(Value::Str(word)) if word.as_str() == Some("raises") => Err(Unavailable),
            Some(found) => Ok(found.clone()),
            None => Ok(Value::Null),
        }
    }
}

// ------------------------------------------------------------------------------------------------ the interpreter
struct Run<'r> {
    env: Shared,
    state: &'r dyn Probe,
    registry: &'r Registry,
    view_given: bool,
    measured_given: bool,
}

impl Run<'_> {
    fn setting(&self, name: &str) -> Value {
        get(&self.env.borrow().value, name).clone()
    }

    fn plain_view(&self) -> Value {
        let held = self.setting(if self.view_given {
            "view"
        } else {
            "default_view"
        });
        if matches!(held, Value::Object(_)) {
            held
        } else {
            Value::Object(Map::new())
        }
    }

    fn table_now(&self) -> Table {
        let held = self.setting(if self.measured_given {
            "measured"
        } else {
            "table_for"
        });
        if raises(&held) {
            Table::new()
        } else {
            table_of(&held)
        }
    }

    fn checked_now(&self) -> Results {
        let held = self.setting("checked");
        if raises(&held) {
            Results::new()
        } else {
            results_of(&held)
        }
    }

    fn tick(&self) -> f64 {
        let mut env = self.env.borrow_mut();
        env.clock += 1.0;
        env.clock
    }

    fn resolve(&self, value: &Value) -> Value {
        match value {
            Value::Str(word) if word.as_str().is_some_and(|w| w.starts_with('@')) => {
                let word = word.as_str().unwrap_or("");
                let generation = self.state.generation();
                match word {
                    "@gen" => int(generation),
                    "@gen+1" => int(generation + 1),
                    "@gen-1" => int(generation - 1),
                    "@ver" => {
                        engine_version(&self.plain_view()).map_or(Value::Null, |each| text(&each))
                    }
                    "@now" => f(self.tick()),
                    other => {
                        if let Some(id) = other.strip_prefix("@rev:") {
                            self.registry
                                .get(id)
                                .map_or(Value::Null, |def| int(def.revision))
                        } else if let Some(id) = other.strip_prefix("@warn:") {
                            match self.registry.get(id) {
                                Some(def) => words_of(&arming::warnings_for(
                                    def,
                                    &self.plain_view(),
                                    &self.table_now(),
                                    true,
                                    &self.checked_now(),
                                )),
                                None => Value::Null,
                            }
                        } else {
                            value.clone()
                        }
                    }
                }
            }
            Value::Array(items) => {
                Value::Array(items.iter().map(|each| self.resolve(each)).collect())
            }
            Value::Object(map) => Value::Object(
                map.iter()
                    .map(|(key, each)| (key.clone(), self.resolve(each)))
                    .collect(),
            ),
            other => other.clone(),
        }
    }
}

/// The class the reference raises for a catalog that is not UTF-8.
fn error_class(_: car_adv::statement::Undecodable) -> &'static str {
    car_adv::statement::Undecodable::CLASS
}

fn fault_class(fault: &StateFault) -> &'static str {
    match fault {
        StateFault::State => "StateError",
        StateFault::Stale => "StaleGeneration",
        StateFault::Refused(_) => "Refused",
    }
}

fn definition_of(registry: &Registry, id: &Value) -> Result<CapabilityDef, Failure> {
    match id {
        Value::Str(word) => word
            .as_str()
            .and_then(|each| registry.get(each))
            .cloned()
            .ok_or_else(|| Failure::new("AttributeError")),
        _ => Err(Failure::new("AttributeError")),
    }
}

fn made_registry() -> Registry {
    let shipped = registry::definitions();
    let lone = |at: usize, id: &str, prefix: &str, requires: &[&str], resends: Option<bool>| {
        let mut each = shipped[at].clone();
        each.id = id.to_owned();
        each.journal_prefix = prefix.to_owned();
        each.requires = requires.iter().map(|word| (*word).to_owned()).collect();
        if let Some(flag) = resends {
            each.resends = flag;
        }
        each
    };
    Registry::new(vec![
        lone(0, "alpha_cap", "alp", &[], None),
        lone(1, "beta_cap", "bet", &["alpha_cap"], None),
        lone(2, "gamma_cap", "gam", &["beta_cap", "alpha_cap"], None),
        lone(3, "delta_cap", "del", &[], Some(false)),
    ])
    .expect("the test-made registry")
}

fn actor_default(map: &Map, key: &str) -> Value {
    map.get(key).cloned().unwrap_or_else(|| text("dashboard"))
}

pub fn run(op: &str, args: &[Value]) -> Out {
    match op {
        "arming.scenario" => scenario(map(arg(args, 0)?)?),
        _ => Err(Failure::new("UnknownOp")),
    }
}

fn scenario(sc: &Map) -> Out {
    let log: Log = Rc::new(RefCell::new(Vec::new()));
    let env_map = match get(sc, "env") {
        Value::Object(each) => each.clone(),
        _ => return Err(bad()),
    };
    let clock = float_of(get(&env_map, "clock"));
    let env: Shared = Rc::new(RefCell::new(Env {
        value: env_map,
        clock,
    }));
    let flag = |name: &str| matches!(get(sc, name), Value::Bool(true));
    let (view_given, live_given, measured_given) = (
        flag("view_given"),
        flag("live_given"),
        flag("measured_given"),
    );
    let registry = Rc::new(match get(sc, "registry") {
        Value::Str(word) if word.as_str() == Some("shipped") => {
            registry::registry_for(&table_of(get(sc, "shipped_table")), false)
                .map_err(|_| Failure::new("RegistryError"))?
        }
        _ => made_registry(),
    });
    let spec = map(get(sc, "state"))?;
    let rows: Vec<(String, Map)> = match get(spec, "rows") {
        Value::Array(items) => items
            .iter()
            .filter_map(|item| match item {
                Value::Array(pair) => match (pair.first(), pair.get(1)) {
                    (Some(Value::Str(cap)), Some(Value::Object(row))) => {
                        cap.as_str().map(|cap| (cap.to_owned(), row.clone()))
                    }
                    _ => None,
                },
                _ => None,
            })
            .collect(),
        _ => Vec::new(),
    };
    let objects = |name: &str| -> Vec<Map> {
        match get(spec, name) {
            Value::Array(items) => items
                .iter()
                .filter_map(|each| match each {
                    Value::Object(map) => Some(map.clone()),
                    _ => None,
                })
                .collect(),
            _ => Vec::new(),
        }
    };
    let strings = |name: &str| -> Vec<String> {
        match get(spec, name) {
            Value::Array(items) => items
                .iter()
                .filter_map(|each| match each {
                    Value::Str(word) => word.as_str().map(str::to_owned),
                    _ => None,
                })
                .collect(),
            _ => Vec::new(),
        }
    };
    let mut faults = BTreeMap::new();
    if let Value::Object(held) = get(spec, "faults") {
        for (name, word) in held {
            if let (Some(name), Value::Str(word)) = (name.as_str(), word) {
                faults.insert(name.to_owned(), word.as_str().unwrap_or("").to_owned());
            }
        }
    }
    let mut payers: BTreeMap<String, Vec<(String, f64)>> = BTreeMap::new();
    if let Value::Object(held) = get(spec, "payers") {
        for (key, value) in held {
            if let (Some(key), Value::Array(pairs)) = (key.as_str(), value) {
                let each = pairs
                    .iter()
                    .filter_map(|pair| match pair {
                        Value::Array(parts) => match (parts.first(), parts.get(1)) {
                            (Some(Value::Str(cap)), Some(time)) => {
                                cap.as_str().map(|cap| (cap.to_owned(), float_of(time)))
                            }
                            _ => None,
                        },
                        _ => None,
                    })
                    .collect();
                payers.insert(key.to_owned(), each);
            }
        }
    }
    let spends: Vec<(String, String, f64)> = match get(spec, "spends") {
        Value::Array(items) => items
            .iter()
            .filter_map(|item| match item {
                Value::Array(parts) => match (parts.first(), parts.get(1), parts.get(2)) {
                    (Some(Value::Str(cap)), Some(Value::Str(record)), Some(time)) => Some((
                        cap.as_str()?.to_owned(),
                        record.as_str()?.to_owned(),
                        float_of(time),
                    )),
                    _ => None,
                },
                _ => None,
            })
            .collect(),
        _ => Vec::new(),
    };
    let hits: Vec<(i64, i64)> = match get(spec, "hits") {
        Value::Object(held) => held
            .iter()
            .filter_map(|(key, value)| match value {
                Value::Int(count) => Some((key.as_str()?.parse::<i64>().ok()?, count.as_i64()?)),
                _ => None,
            })
            .collect(),
        _ => Vec::new(),
    };
    let object_of = |name: &str| match get(spec, name) {
        Value::Object(each) => each.clone(),
        _ => Map::new(),
    };
    let real_state;
    let fake_state;
    let state: &dyn Probe = if flag("real") {
        real_state = Real::new(as_text(get(sc, "home"))?, &registry, clock)?;
        &real_state
    } else {
        fake_state = FakeState {
            inner: RefCell::new(Inner {
                rows,
                generation: match get(spec, "generation") {
                    Value::Int(each) => each.as_i64().unwrap_or(1),
                    _ => 1,
                },
                hourly: match get(spec, "global_hourly") {
                    Value::Int(each) => each.as_i64().unwrap_or(24),
                    _ => 24,
                },
                faults,
                spends,
                overrides: objects("overrides"),
                resent: strings("resent").into_iter().collect(),
                payers,
                reset_rules: objects("reset_rules"),
                credits: matches!(get(spec, "credits"), Value::Bool(true)),
                continuations: objects("continuations"),
                options: object_of("options"),
                wordings: object_of("wordings"),
                rules: objects("rules"),
                hits,
                samples: match get(spec, "samples") {
                    Value::Array(items) => items.clone(),
                    _ => Vec::new(),
                },
                ever: strings("ever").into_iter().collect(),
                next_rule: 100,
            }),
            registry: Rc::clone(&registry),
            log: Rc::clone(&log),
        };
        &fake_state
    };
    let edges = FakeEdges {
        env: Rc::clone(&env),
        log: Rc::clone(&log),
    };
    let locale = match get(sc, "locale") {
        Value::Str(word) => word.as_str().unwrap_or("en").to_owned(),
        _ => "en".to_owned(),
    };
    let directory = as_text(get(sc, "directory"))?.to_owned();
    let catalogs = Catalogs::new(directory, Box::new(move || locale.clone()));

    let setting =
        |env: &Shared, name: &'static str| -> Value { get(&env.borrow().value, name).clone() };
    let view_closure = |name: &'static str, log_name: &'static str| -> arming::ViewFn {
        let (env, log) = (Rc::clone(&env), Rc::clone(&log));
        Box::new(move || {
            push(&log, vec![text(log_name)]);
            let found = setting(&env, name);
            match &found {
                Value::Str(word) if word.as_str() == Some("raises") => Err(Unavailable),
                Value::Str(word) if word.as_str() == Some("notdict") => {
                    Ok(Value::Array(vec![text("not")]))
                }
                _ => Ok(found),
            }
        })
    };
    let policy_closure: arming::PolicyFn = {
        let (env, log) = (Rc::clone(&env), Rc::clone(&log));
        Box::new(move || {
            push(&log, vec![text("policy")]);
            policy_of(&setting(&env, "policy"))
        })
    };
    let measured_closure: arming::MeasuredFn = {
        let (env, log) = (Rc::clone(&env), Rc::clone(&log));
        Box::new(move || {
            push(&log, vec![text("measured")]);
            let found = setting(&env, "measured");
            if raises(&found) {
                Err(Unavailable)
            } else {
                Ok(table_of(&found))
            }
        })
    };
    let tick: arming::ClockFn = {
        let env = Rc::clone(&env);
        Box::new(move || {
            let mut env = env.borrow_mut();
            env.clock += 1.0;
            env.clock
        })
    };
    let engine = Arming::new(
        state.port(),
        &edges,
        &registry,
        &catalogs,
        Setup {
            view: view_given.then(|| view_closure("view", "view")),
            policy: policy_closure,
            measured: measured_given.then_some(measured_closure),
            clock: tick,
            live: live_given.then(|| view_closure("live", "live")),
        },
    );
    let run = Run {
        env: Rc::clone(&env),
        state,
        registry: &registry,
        view_given,
        measured_given,
    };
    let mut results = Vec::new();
    let steps = match get(sc, "steps") {
        Value::Array(items) => items.clone(),
        _ => Vec::new(),
    };
    for each in &steps {
        let Value::Array(parts) = each else { continue };
        let name = match parts.first() {
            Some(Value::Str(word)) => word.as_str().unwrap_or(""),
            _ => "",
        };
        let args: Vec<Value> = parts[1..].iter().map(|part| run.resolve(part)).collect();
        let done = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
            step(&engine, &run, &registry, &log, name, &args)
        }));
        results.push(match done {
            Ok(Ok(value)) => obj(vec![("ok", value)]),
            Ok(Err(failure)) => obj(vec![("error", text(&failure.class))]),
            Err(_) => obj(vec![("error", text("Panic"))]),
        });
    }
    Ok(obj(vec![
        ("results", Value::Array(results)),
        ("log", Value::Array(log.borrow().clone())),
        ("state", state.dump()),
    ]))
}

fn policy_of(value: &Value) -> Result<Policy, Unavailable> {
    match value {
        Value::Object(held) => Ok(Policy {
            forbid: matches!(get(held, "forbid"), Value::Bool(true)),
            force_shadow: matches!(get(held, "force_shadow"), Value::Bool(true)),
            allowed: match get(held, "allowed") {
                Value::Array(items) => Some(
                    items
                        .iter()
                        .filter_map(|each| match each {
                            Value::Str(word) => word.as_str().map(str::to_owned),
                            _ => None,
                        })
                        .collect(),
                ),
                _ => None,
            },
        }),
        _ => Err(Unavailable),
    }
}

fn states_json(states: &States) -> Value {
    states.to_json()
}

fn step(
    engine: &Arming<'_>,
    run: &Run<'_>,
    registry: &Registry,
    log: &Log,
    name: &str,
    args: &[Value],
) -> Out {
    let a = |at: usize| args.get(at).cloned().unwrap_or(Value::Null);
    let first_map = || match args.first() {
        Some(Value::Object(each)) => each.clone(),
        _ => Map::new(),
    };
    Ok(match name {
        "arm" => {
            let body = first_map();
            engine
                .arm(&ArmRequest {
                    capability: get(&body, "capability").clone(),
                    state: get(&body, "state").clone(),
                    revision: get(&body, "revision").clone(),
                    generation: get(&body, "generation").clone(),
                    acknowledged_version: get(&body, "acknowledged_version").clone(),
                    warnings: get(&body, "warnings").clone(),
                    also: get(&body, "also").clone(),
                    keep_on: body.get("keep_on").cloned().unwrap_or(Value::Bool(false)),
                    actor: actor_default(&body, "actor"),
                })
                .map_err(|error| Failure::new(error_class(error)))?
        }
        "disarm" => engine.disarm(&a(0), &a(1)),
        "all_off" => engine.all_off(&a(0)),
        "edition_entered" => int(engine
            .edition_entered()
            .map_err(|fault| Failure::new(fault_class(&fault)))?),
        "keep" => {
            let body = first_map();
            engine.set_keep_on(&KeepRequest {
                capability: get(&body, "capability").clone(),
                keep_on: get(&body, "keep_on").clone(),
                send_again: body
                    .get("send_again")
                    .cloned()
                    .unwrap_or(Value::Bool(false)),
                generation: get(&body, "generation").clone(),
                confirmed: get(&body, "confirmed").clone(),
                actor: actor_default(&body, "actor"),
            })
        }
        "hourly" => engine.set_global_hourly(&a(0), &a(1), &a(2)),
        "option" => engine.set_option(&a(0), &a(1), &a(2), &a(3), &a(4)),
        "wordings_view" => engine.wordings_view(&a(0)),
        "wording" => engine.set_wording(&a(0), &a(1), &a(2), &a(3), &a(4)),
        "add_rule" => engine.add_rule(&a(0), &a(1), &a(2), &a(3), &a(4), &a(5)),
        "remove_rule" => engine.remove_rule(&a(0), &a(1), &a(2)),
        "rules_view" => engine.rules_view(),
        "samples_view" => engine.samples_view(),
        "listing" => engine.listing(),
        "statement" => {
            let locale = match args.get(1) {
                Some(Value::Str(word)) => word.as_str(),
                _ => None,
            };
            engine
                .statement(&definition_of(registry, &a(0))?, locale)
                .map_err(|error| Failure::new(error_class(error)))?
        }
        "check" => engine.check(&definition_of(registry, &a(0))?, None, None, None),
        "warnings" => words_of(&engine.warnings(&definition_of(registry, &a(0))?, None)),
        "verdict" => {
            let held = a(0);
            let word = as_text(&held)?;
            match engine.verdict(word) {
                Ok(found) => opt_s(found),
                Err(_) => return Err(Failure::new("ValueError")),
            }
        }
        "current" => states_json(&engine.current(None, None)),
        "read" => {
            let body = first_map();
            let live: Vec<String> = match get(&body, "live") {
                Value::Array(items) => items
                    .iter()
                    .filter_map(|each| match each {
                        Value::Str(word) => word.as_str().map(str::to_owned),
                        _ => None,
                    })
                    .collect(),
                _ => Vec::new(),
            };
            let live_refs: Vec<&str> = live.iter().map(String::as_str).collect();
            let view = match get(&body, "view") {
                Value::Null => None,
                other => Some(other.clone()),
            };
            let found = engine.read(view.as_ref(), None, &live_refs);
            obj(vec![
                ("states", states_json(&found.states)),
                (
                    "since",
                    Value::Object(
                        found
                            .since
                            .iter()
                            .map(|(id, since)| (Str::from(id.as_str()), opt_f(*since)))
                            .collect(),
                    ),
                ),
                ("failed", Value::Bool(found.failed)),
            ])
        }
        "sweep" => {
            let records = first_map();
            engine.sweep(&Core {
                records,
                log: Rc::clone(log),
            });
            Value::Null
        }
        "moved" => {
            let (held, record) = (a(1), a(0));
            let state = as_text(&held)?;
            Value::Bool(engine.moved(&record, state))
        }
        "resender" => {
            let states = engine.current(None, None);
            match engine.resender(&a(0), &states) {
                Some((id, state)) => Value::Array(vec![text(&id), text(state.as_str())]),
                None => Value::Null,
            }
        }
        "trip" => {
            let capability = match a(0) {
                Value::Str(word) => word.as_str().unwrap_or("").to_owned(),
                _ => String::new(),
            };
            let reason =
                parse::<OffReason>(as_text(&a(1))?).ok_or_else(|| Failure::new("ValueError"))?;
            match engine.trip(&capability, reason) {
                Ok(done) => Value::Bool(done),
                Err(_) => return Err(Failure::new("ValueError")),
            }
        }
        "kept" => {
            let capability = match a(0) {
                Value::Str(word) => word.as_str().unwrap_or("").to_owned(),
                _ => String::new(),
            };
            Value::Bool(engine.kept(&capability))
        }
        "view" => engine.view(),
        "live_view" => engine.live_view(),
        "measured" => {
            let mut rows: Vec<(String, String, String)> = engine
                .measured(None)
                .iter()
                .map(|(m, (v, e))| (m.as_str().to_owned(), v.as_str().to_owned(), e.clone()))
                .collect();
            rows.sort();
            Value::Array(
                rows.iter()
                    .map(|(m, v, e)| texts(&[m.as_str(), v.as_str(), e.as_str()]))
                    .collect(),
            )
        }
        "checked" => {
            let mut rows: Vec<(String, String)> = engine
                .checked(None)
                .iter()
                .map(|(m, r)| (m.as_str().to_owned(), r.as_str().to_owned()))
                .collect();
            rows.sort();
            Value::Array(
                rows.iter()
                    .map(|(m, r)| texts(&[m.as_str(), r.as_str()]))
                    .collect(),
            )
        }
        "policy" => engine.policy().as_json(),
        "why" => Value::Object(
            engine
                .why()
                .iter()
                .map(|(id, word)| (Str::from(id.as_str()), text(word)))
                .collect(),
        ),
        "set_env" => {
            if let Value::Object(change) = a(0) {
                let mut env = run.env.borrow_mut();
                for (key, value) in change {
                    env.value.insert(key, value);
                }
            }
            Value::Null
        }
        "constants" => constants(),
        _ => return Err(Failure::new("AssertionError")),
    })
}

fn constants() -> Value {
    use car_adv::seam;
    let surfaces: Vec<&str> = {
        let mut each: Vec<&str> = arming::SURFACES
            .iter()
            .map(|actor| actor.as_str())
            .collect();
        each.sort_unstable();
        each
    };
    obj(vec![
        ("SURFACES", texts(&surfaces)),
        (
            "TRIPPING",
            Value::Array(
                arming::TRIPPING
                    .iter()
                    .map(|(warning, reason)| texts(&[warning.as_str(), reason.as_str()]))
                    .collect(),
            ),
        ),
        ("SUBMISSION_UNKNOWN", text(arming::SUBMISSION_UNKNOWN)),
        ("SAME_CLAIM", Value::from(arming::SAME_CLAIM)),
        ("DUPLICATE", text(arming::DUPLICATE)),
        ("RESEND_WATCH", int(arming::RESEND_WATCH as i64)),
        ("CREDIT", text(seam::CREDIT)),
        ("ACCOUNT", text(seam::ACCOUNT_CAPABILITY)),
        ("HOOK", text(seam::HOOK_CAPABILITY)),
        ("POWER", text(seam::POWER_TASKS_CAPABILITY)),
        ("RULES_LIMIT", int(seam::RULES_LIMIT)),
        ("RECENT_DAYS", int(seam::RECENT_DAYS)),
        ("DAY", int(seam::DAY)),
        ("METER", text(seam::METER)),
        ("WRAP_UP", text(seam::WRAP_UP)),
        ("PAUSE", text(seam::PAUSE)),
        ("ONCE_MORE", text(arming::ONCE_MORE_ID)),
        ("GLOBAL_HOURLY", int(registry::GLOBAL_HOURLY)),
    ])
}

#[allow(dead_code)]
fn unused(_: &Rc<Registry>, _: Option<&Value>, _: &[Value]) {
    let _ = list(&Value::Null);
}
