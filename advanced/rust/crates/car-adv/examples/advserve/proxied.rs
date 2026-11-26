//! What a test hands car-adv's runtime, asked back over the pipe: its capabilities' codes (`ProxyCode`), the objects a
//! hook answers with (`ProxyThing`: a channel, a route, an errand, a start route), core's view (`ProxyView`) and the
//! edges `Arming` reaches into modules not ported yet (`AskEdges`: the reference's own functions, run on the test's
//! side). Each is the test's own Python object; car-adv decides, the test's objects answer.

use std::cell::RefCell;
use std::collections::{BTreeMap, HashMap};

use car_adv::capabilities::{Binding, Code, Raised, Said, Spoke};
use car_adv::measured::Table;
use car_adv::seam::{Edges, Unavailable};
use car_adv::vocabulary::{AutoResult, Measurement, OptionKey, parse};
use car_machine::json::{Map, Str, Value};
use car_policy::plug::{
    Alternative, Channel, Errand, Guards, HookFailed, Point, ReadFailed, Route, StartRoute, View,
};

use crate::wire::{self, field, text, word};

/// A code's `told` callable, held until the test calls it.
pub type Told = Box<dyn FnOnce() + Send>;

thread_local! {
    /// The view ids of the calls in progress, innermost last: the view a hook of theirs is handed.
    pub static VIEWS: RefCell<Vec<Value>> = const { RefCell::new(Vec::new()) };
    /// Every `ProxyThing` alive, by its address: the test's object id it stands for.
    static THINGS: RefCell<HashMap<usize, i64>> = RefCell::new(HashMap::new());
    /// A code's binding, by (session, capability): what its `Scoped` calls are answered through.
    pub static BINDINGS: RefCell<HashMap<(i64, String), Binding>> = RefCell::new(HashMap::new());
    /// `acted_when_told`'s `told`, by number, until the test calls it.
    pub static TOLD: RefCell<(i64, HashMap<i64, Told>)> = RefCell::new((0, HashMap::new()));
}

pub fn int(number: i64) -> Value {
    Value::from(number)
}

/// A static class name for a raise car-policy carries as `&'static str`.
pub fn static_class(class: &str) -> &'static str {
    const KNOWN: &[&str] = &[
        "AttributeError",
        "TypeError",
        "ValueError",
        "KeyError",
        "RuntimeError",
        "OSError",
        "LookupError",
        "IndexError",
        "ZeroDivisionError",
        "sqlite3.OperationalError",
        "OperationalError",
        "ProgrammingError",
        "DatabaseError",
        "RecursionError",
    ];
    KNOWN
        .iter()
        .find(|known| **known == class)
        .copied()
        .unwrap_or("Exception")
}

// ------------------------------------------------------------------ what a hook said

#[derive(Clone, Copy, PartialEq, Eq)]
pub enum Wants {
    Value,
    Channel,
    Route,
    Errand,
    Start,
}

fn has(answer: &Value, name: &str) -> bool {
    match field(answer, "has") {
        Value::Array(items) => items.iter().any(|item| word(item) == Some(name)),
        _ => false,
    }
}

/// The test's encoding of a hook's answer, as car-adv's `Said`.
pub fn said_of(answer: &Value, wants: Wants, session: i64) -> Said {
    let Value::Object(map) = answer else {
        return Said::Value(answer.clone());
    };
    if map.contains_key("defer") {
        return Said::Defer;
    }
    if map.contains_key("backend") {
        return Said::Backend;
    }
    if let Some(said) = map.get("word") {
        return match word(said).and_then(Alternative::parse) {
            Some(alternative) => Said::Word(alternative),
            None => Said::Value(said.clone()),
        };
    }
    if let Some(Value::Array(items)) = map.get("tuple") {
        return Said::Tuple(items.clone());
    }
    if let Some(Value::Array(items)) = map.get("set") {
        return Said::Set(items.clone());
    }
    if let Some(id) = map.get("object") {
        let id = match id {
            Value::Int(number) => number.as_i64().unwrap_or(0),
            _ => 0,
        };
        let thing = |want: Wants| ProxyThing::boxed(session, id, answer, want);
        return match wants {
            Wants::Channel if has(answer, "send") => Said::Channel(thing(Wants::Channel)),
            Wants::Route if has(answer, "resume") => Said::Route(thing(Wants::Route)),
            Wants::Errand if has(answer, "run") => Said::Errand(thing(Wants::Errand)),
            Wants::Start if has(answer, "start") => Said::StartRoute(thing(Wants::Start)),
            _ => Said::Value(text("<object>")),
        };
    }
    Said::Value(map.get("value").cloned().unwrap_or(Value::Null))
}

/// An optional hook's plain answer: a word as its text, DEFER as a text that is no word.
pub fn plain_of(answer: &Value) -> Value {
    match answer {
        Value::Object(map) => {
            if map.contains_key("defer") {
                return text("\u{0}DEFER");
            }
            if let Some(said) = map.get("word") {
                return said.clone();
            }
            for name in ["value", "tuple", "set"] {
                if let Some(found) = map.get(name) {
                    return found.clone();
                }
            }
            if map.contains_key("object") {
                return text("<object>");
            }
            Value::Null
        }
        other => other.clone(),
    }
}

/// The test's object a `Said` stands for, if it is one of its own: `{"object": id}`.
pub fn object_of<T: ?Sized>(boxed: &T) -> Option<i64> {
    let address = boxed as *const T as *const () as usize;
    THINGS.with(|things| things.borrow().get(&address).copied())
}

// ------------------------------------------------------------------ a capability's code

pub struct ProxyCode {
    pub session: i64,
    pub capability: String,
    /// The optional hooks its class defines (`runtime._own`).
    pub own: Vec<String>,
}

fn view_arg() -> Value {
    VIEWS.with(|views| views.borrow().last().cloned().unwrap_or(Value::Null))
}

fn marked(name: &str, value: Value) -> Value {
    let mut map = Map::new();
    map.insert(Str::new(name), value);
    Value::Object(map)
}

impl ProxyCode {
    fn ask(&self, hook: &str, args: Vec<Value>) -> Result<Value, Raised> {
        wire::ask(
            "hook",
            vec![
                ("session", int(self.session)),
                ("capability", text(&self.capability)),
                ("hook", text(hook)),
                ("args", Value::Array(args)),
            ],
        )
    }

    fn spoke(&mut self, hook: &str, args: Vec<Value>, wants: Wants) -> Spoke {
        self.ask(hook, args)
            .map(|answer| said_of(&answer, wants, self.session))
    }

    fn owns(&self, hook: &str) -> bool {
        self.own.iter().any(|name| name == hook)
    }

    fn own_value(&mut self, hook: &str, args: Vec<Value>) -> Option<Result<Value, Raised>> {
        if !self.owns(hook) {
            return None;
        }
        Some(self.ask(hook, args).map(|answer| plain_of(&answer)))
    }

    fn own_unit(&mut self, hook: &str, args: Vec<Value>) -> Option<Result<(), Raised>> {
        self.own_value(hook, args).map(|done| done.map(|_| ()))
    }

    fn own_spoke(&mut self, hook: &str, args: Vec<Value>, wants: Wants) -> Option<Spoke> {
        if !self.owns(hook) {
            return None;
        }
        Some(self.spoke(hook, args, wants))
    }
}

fn view() -> Value {
    marked("__view__", view_arg())
}

impl Code for ProxyCode {
    fn records(&mut self, _view: &dyn View) -> Spoke {
        self.spoke("records", vec![view()], Wants::Value)
    }
    fn gate(&mut self, name: &Value, record: &Value, facts: &Value) -> Spoke {
        self.spoke(
            "gate",
            vec![name.clone(), record.clone(), facts.clone()],
            Wants::Value,
        )
    }
    fn text(&mut self, record: &Value, text: &Value) -> Spoke {
        self.spoke("text", vec![record.clone(), text.clone()], Wants::Value)
    }
    fn sender(&mut self, record: &Value) -> Spoke {
        self.spoke("sender", vec![record.clone()], Wants::Channel)
    }
    fn outcome(&mut self, record: &Value, outcome: &Value) -> Spoke {
        self.spoke(
            "outcome",
            vec![record.clone(), outcome.clone()],
            Wants::Value,
        )
    }
    fn schedule(&mut self, record: &Value, due: &Value) -> Spoke {
        self.spoke("schedule", vec![record.clone(), due.clone()], Wants::Value)
    }
    fn tick(&mut self, _view: &dyn View) -> Spoke {
        self.spoke("tick", vec![view()], Wants::Errand)
    }
    fn start_route(&mut self, request: &Value) -> Spoke {
        self.spoke("start_route", vec![request.clone()], Wants::Start)
    }
    fn partition(&mut self, records: &Value) -> Spoke {
        self.spoke("partition", vec![records.clone()], Wants::Value)
    }
    fn supervise(&mut self, facts: &Value) -> Spoke {
        self.spoke("supervise", vec![facts.clone()], Wants::Value)
    }
    fn delivery(&mut self, record: &Value) -> Spoke {
        self.spoke("delivery", vec![record.clone()], Wants::Value)
    }
    fn unloaded(&mut self, record: &Value) -> Spoke {
        self.spoke("unloaded", vec![record.clone()], Wants::Route)
    }
    fn admission(&mut self, failure: &Value) -> Spoke {
        self.spoke("admission", vec![failure.clone()], Wants::Value)
    }
    fn sessions(&mut self) -> Spoke {
        self.spoke("sessions", Vec::new(), Wants::Value)
    }
    fn eligibility(&mut self) -> Spoke {
        self.spoke("eligibility", Vec::new(), Wants::Value)
    }
    fn notice(&mut self, facts: &Value) -> Spoke {
        self.spoke("notice", vec![facts.clone()], Wants::Value)
    }
    fn power(&mut self, facts: &Value) -> Spoke {
        self.spoke("power", vec![facts.clone()], Wants::Value)
    }
    fn resident(&mut self, _view: &dyn View) -> Spoke {
        self.spoke("resident", vec![view()], Wants::Errand)
    }

    fn bind(&mut self, binding: Binding) -> Option<Result<(), Raised>> {
        if !self.owns("bind") {
            return None;
        }
        BINDINGS.with(|bindings| {
            bindings
                .borrow_mut()
                .insert((self.session, self.capability.clone()), binding)
        });
        let scoped = marked("__scoped__", text(&self.capability));
        self.own_unit("bind", vec![scoped])
    }
    fn rule_for(&mut self, facts: &Value, answer: &Value) -> Option<Result<Value, Raised>> {
        self.own_value("rule_for", vec![facts.clone(), answer.clone()])
    }
    fn taken(
        &mut self,
        point: Point,
        answer: &Value,
        arguments: &[&Value],
    ) -> Option<Result<Value, Raised>> {
        let mut args = vec![text(point.as_str()), answer.clone()];
        args.extend(arguments.iter().map(|each| (*each).clone()));
        self.own_value("taken", args)
    }
    fn carries(&mut self, word: &Value) -> Option<Result<Value, Raised>> {
        self.own_value("carries", vec![word.clone()])
    }
    fn not_taken(&mut self, record: &Value) -> Option<Result<(), Raised>> {
        self.own_unit("not_taken", vec![record.clone()])
    }
    fn holds(&mut self, record: &Value) -> Option<Result<Value, Raised>> {
        self.own_value("holds", vec![record.clone()])
    }
    fn watched_due(&mut self, _view: &dyn View) -> Option<Spoke> {
        self.own_spoke("watched_due", vec![view()], Wants::Value)
    }
    fn words_sent(&mut self, record: &Value) -> Option<Result<(), Raised>> {
        self.own_unit("words_sent", vec![record.clone()])
    }
    fn acted_when_told(&mut self, told: Box<dyn FnOnce() + Send>) -> Option<Result<(), Raised>> {
        if !self.owns("acted_when_told") {
            return None;
        }
        let number = TOLD.with(|held| {
            let mut held = held.borrow_mut();
            held.0 += 1;
            let number = held.0;
            held.1.insert(number, told);
            number
        });
        self.own_unit("acted_when_told", vec![marked("__told__", int(number))])
    }
    fn tend(&mut self, _view: &dyn View) -> Option<Spoke> {
        self.own_spoke("tend", vec![view()], Wants::Errand)
    }
    fn images_of(&mut self, record: &Value) -> Option<Spoke> {
        self.own_spoke("images_of", vec![record.clone()], Wants::Value)
    }
}

// ------------------------------------------------------------------ an object a hook answered with

pub struct ProxyThing {
    session: i64,
    id: i64,
    has: Vec<String>,
}

impl ProxyThing {
    fn boxed(session: i64, id: i64, answer: &Value, _want: Wants) -> Box<ProxyThing> {
        let has = match field(answer, "has") {
            Value::Array(items) => items
                .iter()
                .filter_map(|item| word(item).map(str::to_owned))
                .collect(),
            _ => Vec::new(),
        };
        let thing = Box::new(ProxyThing { session, id, has });
        let address = &*thing as *const ProxyThing as *const () as usize;
        THINGS.with(|things| things.borrow_mut().insert(address, id));
        thing
    }

    fn call(&self, method: &str, args: Vec<Value>) -> Result<Value, Raised> {
        wire::ask(
            "object",
            vec![
                ("session", int(self.session)),
                ("object", int(self.id)),
                ("method", text(method)),
                ("args", Value::Array(args)),
            ],
        )
    }

    fn owns(&self, name: &str) -> bool {
        self.has.iter().any(|each| each == name)
    }
}

impl Drop for ProxyThing {
    fn drop(&mut self) {
        let address = self as *const ProxyThing as *const () as usize;
        let _ = THINGS.try_with(|things| things.borrow_mut().remove(&address));
    }
}

fn str_value(text_: &car_machine::json::Str) -> Value {
    Value::Str(text_.clone())
}

impl Channel for ProxyThing {
    fn send(
        &self,
        thread_id: &str,
        prompt: &car_machine::json::Str,
        client_id: Option<&str>,
    ) -> Value {
        let args = vec![
            text(thread_id),
            str_value(prompt),
            client_id.map_or(Value::Null, text),
        ];
        self.call("send", args)
            .map(|answer| plain_of(&answer))
            .unwrap_or(Value::Null)
    }
    fn pools(&self) -> Result<bool, HookFailed> {
        match self.pools_said() {
            Some(Ok(Value::Bool(true))) => Ok(true),
            Some(Err(failed)) => Err(failed),
            _ => Ok(false),
        }
    }
    fn pools_said(&self) -> Option<Result<Value, HookFailed>> {
        if !self.owns("pools") {
            return None;
        }
        Some(
            self.call("pools", Vec::new())
                .map(|answer| plain_of(&answer))
                .map_err(|_| HookFailed),
        )
    }
}

impl Route for ProxyThing {
    fn resume(
        &self,
        thread_id: &str,
        _still_unloaded: Option<&dyn Fn() -> bool>,
        words: Option<&car_machine::json::Str>,
        client_id: Option<&str>,
    ) -> Value {
        let args = vec![
            text(thread_id),
            words.map_or(Value::Null, str_value),
            client_id.map_or(Value::Null, text),
        ];
        self.call("resume", args)
            .map(|answer| plain_of(&answer))
            .unwrap_or(Value::Null)
    }
    fn takes_words(&self) -> Result<bool, HookFailed> {
        if !self.owns("words") {
            return Ok(false);
        }
        match self.call("words", Vec::new()) {
            Ok(answer) => Ok(matches!(plain_of(&answer), Value::Bool(true))),
            Err(_) => Err(HookFailed),
        }
    }
}

impl Errand for ProxyThing {
    fn run(&self, _view: &dyn View, _guards: &mut Guards<'_>) -> Result<Value, HookFailed> {
        self.call("run", Vec::new())
            .map(|answer| plain_of(&answer))
            .map_err(|_| HookFailed)
    }
}

impl StartRoute for ProxyThing {
    fn start(&self, command: &[String]) -> Value {
        let args = vec![Value::Array(
            command.iter().map(|each| text(each)).collect(),
        )];
        self.call("start", args)
            .map(|answer| plain_of(&answer))
            .unwrap_or(Value::Null)
    }
}

// ------------------------------------------------------------------ core's view

/// The view the test handed a call (`tick`, `resident`, `records`, a sweep), asked back by its id.
pub struct ProxyView {
    pub session: i64,
    pub id: Value,
}

impl ProxyView {
    fn ask(&self, method: &str, args: Vec<Value>) -> Result<Value, ReadFailed> {
        wire::ask(
            "view",
            vec![
                ("session", int(self.session)),
                ("view", self.id.clone()),
                ("method", text(method)),
                ("args", Value::Array(args)),
            ],
        )
        .map(|answer| plain_of(&answer))
        .map_err(|raised| ReadFailed(static_class(&raised.class)))
    }
}

fn number(value: &Value) -> f64 {
    match value {
        Value::Float(number) => *number,
        Value::Int(number) => number.as_i64().unwrap_or(0) as f64,
        _ => 0.0,
    }
}

fn count(value: &Value) -> i64 {
    match value {
        Value::Int(number) => number.as_i64().unwrap_or(0),
        Value::Float(number) => *number as i64,
        Value::Bool(flag) => i64::from(*flag),
        _ => 0,
    }
}

fn rows(value: Value) -> Vec<Value> {
    match value {
        Value::Array(items) => items,
        _ => Vec::new(),
    }
}

impl View for ProxyView {
    fn now(&self) -> f64 {
        self.ask("now", Vec::new())
            .map(|now| number(&now))
            .unwrap_or(0.0)
    }
    fn get(&self, interruption_id: &str) -> Result<Value, ReadFailed> {
        self.ask("get", vec![text(interruption_id)])
    }
    fn records_in(&self, states: &[&str]) -> Result<Vec<Value>, ReadFailed> {
        let states = Value::Array(states.iter().map(|each| text(each)).collect());
        self.ask("records_in", vec![states]).map(rows)
    }
    fn settings(&self) -> Result<Value, ReadFailed> {
        self.ask("settings", Vec::new())
    }
    fn thread_enabled(&self, thread_id: &str) -> Result<bool, ReadFailed> {
        self.ask("thread_enabled", vec![text(thread_id)])
            .map(|found| car_machine::pyval::truthy(&found))
    }
    fn others_in_flight(&self, thread_id: &str, exclude: &str) -> Result<i64, ReadFailed> {
        self.ask("others_in_flight", vec![text(thread_id), text(exclude)])
            .map(|found| count(&found))
    }
    fn recent_claims(&self, thread_id: &str, since: f64) -> Result<Vec<Value>, ReadFailed> {
        self.ask("recent_claims", vec![text(thread_id), Value::Float(since)])
            .map(rows)
    }
    fn recent_claim_count(&self, thread_id: &str, since: f64) -> Result<i64, ReadFailed> {
        self.ask(
            "recent_claim_count",
            vec![text(thread_id), Value::Float(since)],
        )
        .map(|found| count(&found))
    }
    fn claimed_on_thread(&self, thread_id: &str) -> Result<Vec<Value>, ReadFailed> {
        self.ask("claimed_on_thread", vec![text(thread_id)])
            .map(rows)
    }
    fn last_usage(&self) -> Value {
        self.ask("last_usage", Vec::new()).unwrap_or(Value::Null)
    }
}

// ------------------------------------------------------------------ the edges of Arming not ported yet

/// `Arming`'s reach into modules of later seats, answered by the reference's own function on the test's side
/// (`advproxy/runtime.py` EDGES) - each named in the module table as the seat that replaces it.
pub struct AskEdges {
    pub session: i64,
}

impl AskEdges {
    fn ask(&self, name: &str, args: Vec<Value>) -> Result<Value, Raised> {
        wire::ask(
            "edge",
            vec![
                ("session", int(self.session)),
                ("name", text(name)),
                ("args", Value::Array(args)),
            ],
        )
    }
}

pub fn table_of(rows: &Value) -> Table {
    let mut table = Table::new();
    if let Value::Array(rows) = rows {
        for row in rows {
            if let Value::Array(parts) = row
                && let (Some(m), Some(v)) = (parts.first(), parts.get(1))
                && let (Some(m), Some(v)) = (
                    word(m).and_then(parse::<Measurement>),
                    word(v).and_then(parse::<car_adv::vocabulary::Verdict>),
                )
            {
                let evidence = parts.get(2).and_then(word).unwrap_or("").to_owned();
                table.insert(m, (v, evidence));
            }
        }
    }
    table
}

impl Edges for AskEdges {
    fn default_view(&self) -> Result<Value, Unavailable> {
        self.ask("default_view", Vec::new())
            .map(|found| plain_of(&found))
            .map_err(|_| Unavailable)
    }
    fn default_live_view(&self) -> Result<Value, Unavailable> {
        self.ask("default_live_view", Vec::new())
            .map(|found| plain_of(&found))
            .map_err(|_| Unavailable)
    }
    fn table_for(&self, engine: Option<&str>) -> Result<Table, Unavailable> {
        self.ask("table_for", vec![engine.map_or(Value::Null, text)])
            .map(|found| table_of(&plain_of(&found)))
            .map_err(|_| Unavailable)
    }
    fn checked_for(
        &self,
        engine: Option<&str>,
    ) -> Result<BTreeMap<Measurement, AutoResult>, Unavailable> {
        let found = self
            .ask("checked_for", vec![engine.map_or(Value::Null, text)])
            .map_err(|_| Unavailable)?;
        let mut results = BTreeMap::new();
        for row in rows(plain_of(&found)) {
            if let Value::Array(parts) = row
                && let (Some(m), Some(r)) = (parts.first(), parts.get(1))
                && let (Some(m), Some(r)) = (
                    word(m).and_then(parse::<Measurement>),
                    word(r).and_then(parse::<AutoResult>),
                )
            {
                results.insert(m, r);
            }
        }
        Ok(results)
    }
    fn sending_points(&self) -> Vec<Point> {
        [
            Point::Gates,
            Point::Text,
            Point::Sender,
            Point::Schedule,
            Point::Outcome,
            Point::Delivery,
            Point::Unloaded,
            Point::Admission,
        ]
        .into_iter()
        .collect()
    }
    fn hook_follow(&self, armed: bool) {
        let _ = self.ask("hook_follow", vec![Value::Bool(armed)]);
    }
    fn power_tasks_follow(&self, armed: bool) {
        let _ = self.ask("power_tasks_follow", vec![Value::Bool(armed)]);
    }
    fn account_forget(&self) {
        let _ = self.ask("account_forget", Vec::new());
    }
    fn usage_touched(&self, key: OptionKey) -> Vec<i64> {
        self.ask("usage_touched", vec![text(key.as_str())])
            .map(|found| rows(plain_of(&found)).iter().map(count).collect())
            .unwrap_or_default()
    }
    fn usage_order_problem(
        &self,
        values: &BTreeMap<String, BTreeMap<OptionKey, i64>>,
        windows: &[i64],
    ) -> (Option<String>, Option<String>) {
        let mut outer = Map::new();
        for (capability, options) in values {
            let mut inner = Map::new();
            for (key, value) in options {
                inner.insert(Str::new(key.as_str()), int(*value));
            }
            outer.insert(Str::new(capability), Value::Object(inner));
        }
        let windows = Value::Array(windows.iter().map(|each| int(*each)).collect());
        match self.ask("usage_order_problem", vec![Value::Object(outer), windows]) {
            Ok(found) => match plain_of(&found) {
                Value::Array(pair) => (
                    pair.first().and_then(word).map(str::to_owned),
                    pair.get(1).and_then(word).map(str::to_owned),
                ),
                _ => (None, None),
            },
            Err(_) => (None, None),
        }
    }
    fn usage_previews(&self, now: f64) -> Vec<(i64, Option<String>)> {
        self.ask("usage_previews", vec![Value::Float(now)])
            .map(|found| {
                rows(plain_of(&found))
                    .iter()
                    .filter_map(|pair| match pair {
                        Value::Array(parts) => Some((
                            parts.first().map_or(0, count),
                            parts.get(1).and_then(word).map(str::to_owned),
                        )),
                        _ => None,
                    })
                    .collect()
            })
            .unwrap_or_default()
    }
    fn wording_problem(&self, words: &Value) -> Option<String> {
        self.ask("wording_problem", vec![words.clone()])
            .ok()
            .and_then(|found| word(&plain_of(&found)).map(str::to_owned))
    }
    fn wording_limit(&self) -> i64 {
        self.ask("wording_limit", Vec::new())
            .map(|found| count(&plain_of(&found)))
            .unwrap_or(0)
    }
    fn wording_placeholders(&self) -> Vec<String> {
        self.ask("wording_placeholders", Vec::new())
            .map(|found| {
                rows(plain_of(&found))
                    .iter()
                    .filter_map(|each| word(each).map(str::to_owned))
                    .collect()
            })
            .unwrap_or_default()
    }
}
