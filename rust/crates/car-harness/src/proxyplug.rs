//! The test's plug, asked back (owner Q3 (c), the advanced proxy's completion part 1): the plug a test hands core's
//! `Engine` (`Engine(..., plug=AdvancedPlug(...))`) is the reference's own Python object - an advanced plug whose
//! runtime is car-adv's through the advanced proxy - and car-engine reaches it here, every hook by its name
//! (`{"ask": "plug.<hook>"}`), held by car-policy's own `Guarded` as core holds any plug. What a hook answers with that
//! core runs later (an errand, a channel, a route, a start route) stays the test's object, asked by number; the view a
//! hook is handed and core's errand guards are reached from the Python side by callbacks while the ask waits.

use std::cell::RefCell;

use car_machine::json::{Map, Str, Value};
use car_machine::pyval::Py;
use car_policy::plug::{
    Alternative, Answer, Channel, Edition, Errand, Guards, Hook, HookFailed, Plug, Point, ReadFailed, Route,
    StartRoute, Surface, Unloaded, View,
};

use super::{answered, read_value, write_line};

thread_local! {
    /// The views handed to the hooks being asked, innermost last (a Python view reads the innermost one).
    static VIEWS: RefCell<Vec<*const (dyn View + 'static)>> = const { RefCell::new(Vec::new()) };
}

fn with_view<R>(view: &dyn View, body: impl FnOnce() -> R) -> R {
    let pointer: *const (dyn View + '_) = view;
    // SAFETY: the pointer is read only by `view_call`, from a callback answered inside `body` - while `view` is
    // borrowed for this call - and it is off the stack before this returns.
    let pointer: *const (dyn View + 'static) = unsafe { std::mem::transmute(pointer) };
    VIEWS.with(|views| views.borrow_mut().push(pointer));
    let found = body();
    VIEWS.with(|views| {
        views.borrow_mut().pop();
    });
    found
}

fn word(value: &Value) -> Option<&str> {
    match value {
        Value::Str(found) => found.as_str(),
        _ => None,
    }
}

fn read_failed(failed: ReadFailed) -> &'static str {
    failed.0
}

/// `view.<method>(*args)` on the innermost view handed in.
fn view_call(method: &str, args: &[Value]) -> Py<Value> {
    let pointer = VIEWS.with(|views| views.borrow().last().copied());
    let Some(pointer) = pointer else {
        return Err("RuntimeError");
    };
    // SAFETY: see `with_view`.
    let view = unsafe { &*pointer };
    let text_at = |index: usize| args.get(index).and_then(word).unwrap_or_default().to_owned();
    let number_at = |index: usize| match args.get(index) {
        Some(Value::Int(whole)) => whole.as_i64().map_or(0.0, |each| each as f64),
        Some(Value::Float(each)) => *each,
        _ => 0.0,
    };
    Ok(match method {
        "now" => Value::Float(view.now()),
        "get" => view.get(&text_at(0)).map_err(read_failed)?,
        "records_in" => {
            let states: Vec<String> = match args.first() {
                Some(Value::Array(items)) => items
                    .iter()
                    .filter_map(|each| word(each).map(str::to_owned))
                    .collect(),
                _ => Vec::new(),
            };
            let states: Vec<&str> = states.iter().map(String::as_str).collect();
            Value::Array(view.records_in(&states).map_err(read_failed)?)
        }
        "settings" => view.settings().map_err(read_failed)?,
        "thread_enabled" => Value::Bool(view.thread_enabled(&text_at(0)).map_err(read_failed)?),
        "others_in_flight" => Value::from(
            view.others_in_flight(&text_at(0), &text_at(1))
                .map_err(read_failed)?,
        ),
        "recent_claims" => Value::Array(
            view.recent_claims(&text_at(0), number_at(1))
                .map_err(read_failed)?,
        ),
        "recent_claim_count" => Value::from(
            view.recent_claim_count(&text_at(0), number_at(1))
                .map_err(read_failed)?,
        ),
        "claimed_on_thread" => Value::Array(view.claimed_on_thread(&text_at(0)).map_err(read_failed)?),
        "last_usage" => view.last_usage(),
        _ => return Err("AttributeError"),
    })
}

/// One question to the Python side for the plug, answering its callbacks meanwhile: the view's reads, core's errand
/// guards (`["guard_enter"]` ... `["guard_exit"]`, the guard held while the Python side is inside it) and a route's
/// `still_unloaded`.
fn ask_plug(
    name: &str,
    args: Vec<Value>,
    mut guards: Option<&mut Guards<'_>>,
    still_unloaded: Option<&dyn Fn() -> bool>,
) -> Py<Value> {
    let mut message = Map::new();
    message.insert(Str::new("ask"), Value::from(name));
    message.insert(Str::new("args"), Value::Array(args));
    write_line(&Value::Object(message))?;
    loop {
        let answer = read_value()?;
        if let Some(Value::Array(arguments)) = answer.get("callback") {
            let what = arguments.first().and_then(word).unwrap_or_default();
            if what == "guard_enter" {
                guard_entered(guards.as_deref_mut())?;
                continue;
            }
            let found = match what {
                "view" => {
                    let method = arguments.get(1).and_then(word).unwrap_or_default();
                    let rest = match arguments.get(2) {
                        Some(Value::Array(items)) => items.clone(),
                        _ => Vec::new(),
                    };
                    view_call(method, &rest)
                }
                "still_unloaded" => Ok(Value::Bool(still_unloaded.is_some_and(|asked| asked()))),
                _ => Err("TypeError"),
            };
            write_line(&answered(found))?;
            continue;
        }
        if let Some(Value::Str(raised)) = answer.get("raise") {
            let _ = raised;
            return Err("Exception");
        }
        return Ok(answer.get("value").cloned().unwrap_or(Value::Null));
    }
}

/// `with guard() as permitted:` entered from the Python side: core's guard taken and `permitted` answered, then every
/// callback inside the block answered until `["guard_exit"]`, which leaves it.
fn guard_entered(guards: Option<&mut Guards<'_>>) -> Py<()> {
    let Some(guards) = guards else {
        return write_line(&answered(Err("RuntimeError")));
    };
    let mut entered = false;
    let mut failed: Option<&'static str> = None;
    let taken = guards(&mut |permitted| {
        entered = true;
        if let Err(class) = write_line(&answered(Ok(Value::Bool(permitted)))) {
            failed = Some(class);
            return Value::Null;
        }
        loop {
            let Ok(answer) = read_value() else {
                failed = Some("OSError");
                return Value::Null;
            };
            let Some(Value::Array(arguments)) = answer.get("callback") else {
                failed = Some("RuntimeError");
                return Value::Null;
            };
            let what = arguments.first().and_then(word).unwrap_or_default();
            if what == "guard_exit" {
                let _ = write_line(&answered(Ok(Value::Null)));
                return Value::Null;
            }
            let found = if what == "view" {
                let method = arguments.get(1).and_then(word).unwrap_or_default();
                let rest = match arguments.get(2) {
                    Some(Value::Array(items)) => items.clone(),
                    _ => Vec::new(),
                };
                view_call(method, &rest)
            } else {
                Err("TypeError")
            };
            if write_line(&answered(found)).is_err() {
                failed = Some("OSError");
                return Value::Null;
            }
        }
    });
    if let Some(class) = failed {
        return Err(class);
    }
    if !entered {
        // the guard could not be taken: the Python side's `with` raises, as the reference's guard does
        let _ = taken;
        return write_line(&answered(Err("StoreError")));
    }
    Ok(())
}

// ------------------------------------------------------------------ answers

fn said(found: &Value) -> Option<&Map> {
    match found {
        Value::Object(map) => Some(map),
        _ => None,
    }
}

fn is_defer(found: &Value) -> bool {
    said(found).is_some_and(|map| map.contains_key("defer"))
}

fn alternative(found: Py<Value>) -> Hook<Alternative> {
    let found = found.map_err(|_| HookFailed)?;
    let Some(map) = said(&found) else {
        return Ok(Answer::Defer);
    };
    match map.get("word").and_then(word).and_then(Alternative::parse) {
        Some(word) => Ok(Answer::Is(word)),
        None => Ok(Answer::Defer),
    }
}

fn plain(found: Py<Value>) -> Hook<Value> {
    let found = found.map_err(|_| HookFailed)?;
    if is_defer(&found) {
        return Ok(Answer::Defer);
    }
    match said(&found) {
        Some(map) if map.contains_key("word") => Ok(Answer::Is(map["word"].clone())),
        Some(map) => Ok(Answer::Is(map.get("value").cloned().unwrap_or(Value::Null))),
        None => Ok(Answer::Is(found)),
    }
}

fn unit(found: Py<Value>) -> Hook<()> {
    found.map(|_| Answer::Is(())).map_err(|_| HookFailed)
}

fn list(found: Py<Value>) -> Hook<Vec<Value>> {
    match plain(found)? {
        Answer::Defer => Ok(Answer::Defer),
        Answer::Is(Value::Array(items)) => Ok(Answer::Is(items)),
        Answer::Is(_) => Ok(Answer::Defer),
    }
}

fn object_of(found: &Value) -> Option<(i64, Vec<String>)> {
    let map = said(found)?;
    let number = match map.get("object")? {
        Value::Int(whole) => whole.as_i64()?,
        _ => return None,
    };
    let has = match map.get("has") {
        Some(Value::Array(items)) => items
            .iter()
            .filter_map(|each| word(each).map(str::to_owned))
            .collect(),
        _ => Vec::new(),
    };
    Some((number, has))
}

/// One of the test's objects a hook answered with (an errand, a channel, a route, a start route).
struct Held {
    number: i64,
    has: Vec<String>,
}

impl Held {
    fn call(
        &self,
        method: &str,
        args: Vec<Value>,
        guards: Option<&mut Guards<'_>>,
        still_unloaded: Option<&dyn Fn() -> bool>,
    ) -> Py<Value> {
        ask_plug(
            "plug.object",
            vec![Value::from(self.number), Value::from(method), Value::Array(args)],
            guards,
            still_unloaded,
        )
    }
    fn value(found: Py<Value>) -> Value {
        match found {
            Ok(Value::Object(map)) => map.get("value").cloned().unwrap_or(Value::Null),
            _ => Value::Null,
        }
    }
}

impl Errand for Held {
    fn run(&self, view: &dyn View, guards: &mut Guards<'_>) -> Result<Value, HookFailed> {
        let found = with_view(view, || self.call("run", Vec::new(), Some(guards), None));
        found.map(|found| Held::value(Ok(found))).map_err(|_| HookFailed)
    }
}

impl Channel for Held {
    fn send(&self, thread_id: &str, prompt: &Str, client_id: Option<&str>) -> Value {
        let args = vec![
            Value::from(thread_id),
            Value::Str(prompt.clone()),
            client_id.map_or(Value::Null, Value::from),
        ];
        Held::value(self.call("send", args, None, None))
    }
    fn pools(&self) -> Result<bool, HookFailed> {
        match self.pools_said() {
            Some(Ok(Value::Bool(true))) => Ok(true),
            Some(Err(failed)) => Err(failed),
            _ => Ok(false),
        }
    }
    fn pools_said(&self) -> Option<Result<Value, HookFailed>> {
        if !self.has.iter().any(|each| each == "pools") {
            return None;
        }
        Some(
            self.call("pools", Vec::new(), None, None)
                .map(|found| Held::value(Ok(found)))
                .map_err(|_| HookFailed),
        )
    }
}

impl Route for Held {
    fn resume(
        &self,
        thread_id: &str,
        still_unloaded: Option<&dyn Fn() -> bool>,
        words: Option<&Str>,
        client_id: Option<&str>,
    ) -> Value {
        let args = vec![
            Value::from(thread_id),
            Value::Bool(still_unloaded.is_some()),
            words.map_or(Value::Null, |each| Value::Str(each.clone())),
            client_id.map_or(Value::Null, Value::from),
        ];
        Held::value(self.call("resume", args, None, still_unloaded))
    }
    fn takes_words(&self) -> Result<bool, HookFailed> {
        match self.call("takes_words", Vec::new(), None, None) {
            Ok(found) => Ok(matches!(Held::value(Ok(found)), Value::Bool(true))),
            Err(_) => Err(HookFailed),
        }
    }
}

impl StartRoute for Held {
    fn start(&self, command: &[String]) -> Value {
        let args = vec![Value::Array(command.iter().map(|each| Value::from(each.as_str())).collect())];
        Held::value(self.call("start", args, None, None))
    }
}

fn held(found: Py<Value>, wants: &str) -> Hook<Box<Held>> {
    let found = found.map_err(|_| HookFailed)?;
    match object_of(&found) {
        Some((number, has)) if has.iter().any(|each| each == wants) => Ok(Answer::Is(Box::new(Held { number, has }))),
        _ => Ok(Answer::Defer),
    }
}

// ------------------------------------------------------------------ the plug

/// The test's plug: its edition and badge as it said them when the engine was made, every hook asked back.
pub struct AskPlug {
    pub edition: Edition,
    pub badge: &'static str,
}

fn hook(name: &str, args: Vec<Value>) -> Py<Value> {
    ask_plug(&format!("plug.{name}"), args, None, None)
}

fn viewed(name: &str, view: &dyn View, args: Vec<Value>) -> Py<Value> {
    with_view(view, || hook(name, args))
}

impl Plug for AskPlug {
    fn edition(&self) -> Edition {
        self.edition
    }
    fn badge(&self) -> &'static str {
        self.badge
    }
    fn records(&self, view: &dyn View) -> Hook<Vec<Value>> {
        list(viewed("records", view, Vec::new()))
    }
    fn gate(&self, name: &str, record: &Value, facts: &Value) -> Hook<Alternative> {
        alternative(hook("gate", vec![Value::from(name), record.clone(), facts.clone()]))
    }
    fn text(&self, record: &Value, text: &Str) -> Hook<Str> {
        Ok(match plain(hook("text", vec![record.clone(), Value::Str(text.clone())]))? {
            Answer::Is(Value::Str(words)) => Answer::Is(words),
            _ => Answer::Defer,
        })
    }
    fn sender(&self, record: &Value) -> Hook<Box<dyn Channel>> {
        Ok(match held(hook("sender", vec![record.clone()]), "send")? {
            Answer::Is(made) => Answer::Is(made as Box<dyn Channel>),
            Answer::Defer => Answer::Defer,
        })
    }
    fn outcome(&self, record: &Value, outcome: &str) -> Hook<Alternative> {
        alternative(hook("outcome", vec![record.clone(), Value::from(outcome)]))
    }
    fn schedule(&self, record: &Value, due: &Value) -> Hook<Alternative> {
        alternative(hook("schedule", vec![record.clone(), due.clone()]))
    }
    fn tick(&self, view: &dyn View) -> Hook<Box<dyn Errand>> {
        Ok(match held(viewed("tick", view, Vec::new()), "run")? {
            Answer::Is(made) => Answer::Is(made as Box<dyn Errand>),
            Answer::Defer => Answer::Defer,
        })
    }
    fn start_route(&self, request: &Value) -> Hook<Box<dyn StartRoute>> {
        Ok(match held(hook("start_route", vec![request.clone()]), "start")? {
            Answer::Is(made) => Answer::Is(made as Box<dyn StartRoute>),
            Answer::Defer => Answer::Defer,
        })
    }
    fn surface(&self, name: Surface, facts: &Value) -> Hook<Value> {
        plain(hook("surface", vec![Value::from(name.as_str()), facts.clone()]))
    }
    fn partition(&self, records: &[Value]) -> Hook<Value> {
        plain(hook("partition", vec![Value::Array(records.to_vec())]))
    }
    fn supervise(&self, facts: &Value) -> Hook<Alternative> {
        alternative(hook("supervise", vec![facts.clone()]))
    }
    fn moved(&self, record: &Value, state: &str) -> Hook<()> {
        unit(hook("moved", vec![record.clone(), Value::from(state)]))
    }
    fn delivery(&self, record: &Value) -> Hook<Alternative> {
        alternative(hook("delivery", vec![record.clone()]))
    }
    fn unloaded(&self, record: &Value) -> Hook<Unloaded> {
        let found = hook("unloaded", vec![record.clone()]).map_err(|_| HookFailed)?;
        if let Some((number, has)) = object_of(&found)
            && has.iter().any(|each| each == "resume")
        {
            return Ok(Answer::Is(Unloaded::Route(Box::new(Held { number, has }))));
        }
        Ok(match alternative(Ok(found))? {
            Answer::Is(word) => Answer::Is(Unloaded::Queued(word)),
            Answer::Defer => Answer::Defer,
        })
    }
    fn admission(&self, failure: &Value) -> Hook<Alternative> {
        alternative(hook("admission", vec![failure.clone()]))
    }
    fn sessions(&self) -> Hook<Vec<Value>> {
        list(hook("sessions", Vec::new()))
    }
    fn eligibility(&self) -> Hook<Vec<Value>> {
        list(hook("eligibility", Vec::new()))
    }
    fn notice(&self, facts: &Value) -> Hook<()> {
        unit(hook("notice", vec![facts.clone()]))
    }
    fn power(&self, facts: &Value) -> Hook<Value> {
        plain(hook("power", vec![facts.clone()]))
    }
    fn resident(&self, view: &dyn View) -> Hook<Box<dyn Errand>> {
        Ok(match held(viewed("resident", view, Vec::new()), "run")? {
            Answer::Is(made) => Answer::Is(made as Box<dyn Errand>),
            Answer::Defer => Answer::Defer,
        })
    }
    fn wants(&self, point: Point) -> Result<bool, HookFailed> {
        match plain(hook("wants", vec![Value::from(point.as_str())])) {
            Ok(Answer::Is(Value::Bool(found))) => Ok(found),
            Ok(_) => Ok(false),
            Err(failed) => Err(failed),
        }
    }
    fn edition_changed(&self, previous: Edition) -> Result<(), HookFailed> {
        hook("edition_changed", vec![Value::from(previous.as_str())])
            .map(|_| ())
            .map_err(|_| HookFailed)
    }
    fn codex(&self, codex_exe: &str, codex_home: &str) -> Result<(), HookFailed> {
        hook("codex", vec![Value::from(codex_exe), Value::from(codex_home)])
            .map(|_| ())
            .map_err(|_| HookFailed)
    }
    fn conversation_off(&self, thread_id: &str) -> Result<(), HookFailed> {
        hook("conversation_off", vec![Value::from(thread_id)])
            .map(|_| ())
            .map_err(|_| HookFailed)
    }
    fn start_held(&self) -> Result<Value, HookFailed> {
        plain(hook("start_held", Vec::new())).map(|found| match found {
            Answer::Is(value) => value,
            Answer::Defer => Value::Null,
        })
    }
    fn supervise_held(&self) -> Result<Value, HookFailed> {
        plain(hook("supervise_held", Vec::new())).map(|found| match found {
            Answer::Is(value) => value,
            Answer::Defer => Value::Null,
        })
    }
}

/// The plug a `proxy.open` names (`"plug": {"edition", "badge"}`), or none: the standard edition's.
pub fn named(request: &Map) -> Option<AskPlug> {
    let Some(Value::Object(plug)) = request.get("plug") else {
        return None;
    };
    let edition = plug
        .get("edition")
        .and_then(word)
        .and_then(Edition::parse)
        .unwrap_or(Edition::Advanced);
    let badge = plug.get("badge").and_then(word).unwrap_or("Advanced");
    Some(AskPlug {
        edition,
        badge: Box::leak(badge.to_owned().into_boxed_str()),
    })
}
