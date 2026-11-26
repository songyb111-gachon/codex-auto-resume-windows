//! The scripted capability of a trace: every hook answers what the scenario's script says, call by call, and says it
//! was asked (`advplug.REFERENCE`'s `Scripted`, the same rules on both sides).

use std::collections::HashMap;
use std::sync::{Arc, Mutex, PoisonError};

use car_adv::capabilities::{Binding, Code, Raised, Said, Spoke};
use car_machine::json::{Map, Value};
use car_policy::plug::{
    Alternative, Channel, Errand, Guards, HookFailed, Point, Route, StartRoute, View,
};

/// The hooks asked so far, in order, of every code: `[capability, hook]` (and an errand's `[capability, "errand.run"]`,
/// `[capability, "errand.permitted", permitted]`).
pub type Asked = Arc<Mutex<Vec<Value>>>;

fn text(word: &str) -> Value {
    Value::Str(word.into())
}

fn note(asked: &Asked, entry: Vec<Value>) {
    asked
        .lock()
        .unwrap_or_else(PoisonError::into_inner)
        .push(Value::Array(entry));
}

fn get<'a>(value: &'a Value, name: &str) -> Option<&'a Value> {
    match value {
        Value::Object(map) => map.get(name),
        _ => None,
    }
}

pub struct Scripted {
    capability: String,
    script: Value,
    asked: Asked,
    calls: HashMap<String, usize>,
}

struct Thing {
    capability: String,
    spec: Value,
    asked: Asked,
}

impl Channel for Thing {
    fn send(
        &self,
        _thread_id: &str,
        _prompt: &car_machine::json::Str,
        _client_id: Option<&str>,
    ) -> Value {
        let mut map = Map::new();
        map.insert("ok".into(), Value::Bool(true));
        Value::Object(map)
    }
    fn pools(&self) -> Result<bool, HookFailed> {
        match self.pools_said() {
            Some(Ok(Value::Bool(true))) => Ok(true),
            Some(Err(failed)) => Err(failed),
            _ => Ok(false),
        }
    }
    fn pools_said(&self) -> Option<Result<Value, HookFailed>> {
        let spec = get(&self.spec, "pools")?;
        Some(match spec {
            Value::Object(map) if map.contains_key("raise") => Err(HookFailed),
            Value::Object(map) => Ok(map.get("value").cloned().unwrap_or(Value::Null)),
            other => Ok(other.clone()),
        })
    }
}

impl Route for Thing {
    fn resume(
        &self,
        _thread_id: &str,
        _still_unloaded: Option<&dyn Fn() -> bool>,
        _words: Option<&car_machine::json::Str>,
        _client_id: Option<&str>,
    ) -> Value {
        let mut map = Map::new();
        map.insert("ok".into(), Value::Bool(true));
        Value::Object(map)
    }
    fn takes_words(&self) -> Result<bool, HookFailed> {
        Ok(matches!(get(&self.spec, "words"), Some(Value::Bool(true))))
    }
}

impl StartRoute for Thing {
    fn start(&self, _command: &[String]) -> Value {
        Value::Null
    }
}

impl Errand for Thing {
    fn run(&self, _view: &dyn View, guards: &mut Guards<'_>) -> Result<Value, HookFailed> {
        note(
            &self.asked,
            vec![text(&self.capability), text("errand.run")],
        );
        if get(&self.spec, "raise").is_some() {
            return Err(HookFailed);
        }
        let asked = self.asked.clone();
        let capability = self.capability.clone();
        guards(&mut |permitted| {
            note(
                &asked,
                vec![
                    text(&capability),
                    text("errand.permitted"),
                    Value::Bool(permitted),
                ],
            );
            Value::Null
        })?;
        Ok(get(&self.spec, "returns").cloned().unwrap_or(Value::Null))
    }
}

impl Scripted {
    pub fn new(capability: &str, script: Value, asked: Asked) -> Scripted {
        Scripted {
            capability: capability.to_owned(),
            script,
            asked,
            calls: HashMap::new(),
        }
    }

    fn has(&self, hook: &str) -> bool {
        get(&self.script, hook).is_some()
    }

    /// The hook `hook` asked with `arguments` (views and the backend left out): what its spec says.
    fn answer(
        &mut self,
        hook: &str,
        arguments: &[&Value],
        told: Option<Box<dyn FnOnce() + Send>>,
    ) -> Spoke {
        note(&self.asked, vec![text(&self.capability), text(hook)]);
        let Some(spec) = get(&self.script, hook).cloned() else {
            return Err(Raised::missing());
        };
        self.said(hook, spec, arguments, told)
    }

    fn said(
        &mut self,
        hook: &str,
        mut spec: Value,
        arguments: &[&Value],
        told: Option<Box<dyn FnOnce() + Send>>,
    ) -> Spoke {
        if let Some(Value::Array(items)) = get(&spec, "seq").cloned() {
            let index = self.calls.entry(hook.to_owned()).or_insert(0);
            let chosen = items
                .get((*index).min(items.len().saturating_sub(1)))
                .cloned()
                .unwrap_or(Value::Null);
            *index += 1;
            spec = chosen;
        }
        if let Some(Value::Int(by)) = get(&spec, "by") {
            let chosen = by
                .as_i64()
                .and_then(|by| arguments.get(by as usize).copied())
                .cloned()
                .unwrap_or(Value::Null);
            let key = match &chosen {
                Value::Str(word) => word.as_str().unwrap_or_default().to_owned(),
                other => car_machine::json::to_string(other, &car_machine::json::Options::new())
                    .unwrap_or_default(),
            };
            let cases = get(&spec, "cases").cloned().unwrap_or(Value::Null);
            spec = get(&cases, &key)
                .cloned()
                .or_else(|| get(&spec, "else").cloned())
                .unwrap_or(text("DEFER"));
        }
        match &spec {
            Value::Str(word) if word.as_str() == Some("DEFER") => return Ok(Said::Defer),
            Value::Str(word) if word.as_str() == Some("BACKEND") => return Ok(Said::Backend),
            Value::Object(_) => {}
            other => return Ok(Said::Value(other.clone())),
        }
        if let Some(Value::Str(word)) = get(&spec, "word") {
            return Ok(match word.as_str().and_then(Alternative::parse) {
                Some(word) => Said::Word(word),
                None => Said::Value(Value::Str(word.clone())),
            });
        }
        if let Some(found) = get(&spec, "value") {
            return Ok(Said::Value(found.clone()));
        }
        if let Some(Value::Array(items)) = get(&spec, "tuple") {
            return Ok(Said::Tuple(items.clone()));
        }
        if let Some(Value::Array(items)) = get(&spec, "set") {
            let mut unique: Vec<Value> = Vec::new();
            for item in items {
                if !unique.contains(item) {
                    unique.push(item.clone());
                }
            }
            return Ok(Said::Set(unique));
        }
        if let Some(Value::Str(class)) = get(&spec, "raise") {
            return Err(Raised::new(class.as_str().unwrap_or("RuntimeError")));
        }
        if get(&spec, "call").is_some() {
            if let Some(told) = told {
                told();
            }
            return Ok(Said::Value(Value::Null));
        }
        for kind in ["channel", "route", "errand", "start"] {
            if let Some(inner) = get(&spec, kind) {
                let thing = Thing {
                    capability: self.capability.clone(),
                    spec: inner.clone(),
                    asked: self.asked.clone(),
                };
                return Ok(match kind {
                    "channel" => Said::Channel(Box::new(thing)),
                    "route" => Said::Route(Box::new(thing)),
                    "errand" => Said::Errand(Box::new(thing)),
                    _ => Said::StartRoute(Box::new(thing)),
                });
            }
        }
        Ok(Said::Value(spec))
    }

    fn optional(&mut self, hook: &str, arguments: &[&Value]) -> Option<Spoke> {
        if !self.has(hook) {
            return None;
        }
        Some(self.answer(hook, arguments, None))
    }
}

fn plain(spoke: Spoke) -> Result<Value, Raised> {
    spoke.map(|said| match said {
        Said::Word(word) => text(word.as_str()),
        Said::Value(value) => value,
        Said::Tuple(items) | Said::Set(items) => Value::Array(items),
        _ => Value::Null,
    })
}

impl Code for Scripted {
    fn records(&mut self, _view: &dyn View) -> Spoke {
        self.answer("records", &[&Value::Null], None)
    }
    fn gate(&mut self, name: &Value, record: &Value, facts: &Value) -> Spoke {
        self.answer("gate", &[name, record, facts], None)
    }
    fn text(&mut self, record: &Value, said: &Value) -> Spoke {
        self.answer("text", &[record, said], None)
    }
    fn sender(&mut self, record: &Value) -> Spoke {
        self.answer("sender", &[record], None)
    }
    fn outcome(&mut self, record: &Value, outcome: &Value) -> Spoke {
        self.answer("outcome", &[record, outcome], None)
    }
    fn schedule(&mut self, record: &Value, due: &Value) -> Spoke {
        self.answer("schedule", &[record, due], None)
    }
    fn tick(&mut self, _view: &dyn View) -> Spoke {
        self.answer("tick", &[&Value::Null], None)
    }
    fn start_route(&mut self, request: &Value) -> Spoke {
        self.answer("start_route", &[request], None)
    }
    fn partition(&mut self, records: &Value) -> Spoke {
        self.answer("partition", &[records], None)
    }
    fn supervise(&mut self, facts: &Value) -> Spoke {
        self.answer("supervise", &[facts], None)
    }
    fn delivery(&mut self, record: &Value) -> Spoke {
        self.answer("delivery", &[record], None)
    }
    fn unloaded(&mut self, record: &Value) -> Spoke {
        self.answer("unloaded", &[record], None)
    }
    fn admission(&mut self, failure: &Value) -> Spoke {
        self.answer("admission", &[failure], None)
    }
    fn sessions(&mut self) -> Spoke {
        self.answer("sessions", &[], None)
    }
    fn eligibility(&mut self) -> Spoke {
        self.answer("eligibility", &[], None)
    }
    fn notice(&mut self, facts: &Value) -> Spoke {
        self.answer("notice", &[facts], None)
    }
    fn power(&mut self, facts: &Value) -> Spoke {
        self.answer("power", &[facts], None)
    }
    fn resident(&mut self, _view: &dyn View) -> Spoke {
        self.answer("resident", &[&Value::Null], None)
    }
    fn bind(&mut self, _binding: Binding) -> Option<Result<(), Raised>> {
        None
    }
    fn rule_for(&mut self, facts: &Value, answer: &Value) -> Option<Result<Value, Raised>> {
        self.optional("rule_for", &[facts, answer]).map(plain)
    }
    fn taken(
        &mut self,
        point: Point,
        answer: &Value,
        arguments: &[&Value],
    ) -> Option<Result<Value, Raised>> {
        let point = text(point.as_str());
        let mut all: Vec<&Value> = vec![&point, answer];
        all.extend_from_slice(arguments);
        self.optional("taken", &all).map(plain)
    }
    fn carries(&mut self, word: &Value) -> Option<Result<Value, Raised>> {
        self.optional("carries", &[word]).map(plain)
    }
    fn not_taken(&mut self, record: &Value) -> Option<Result<(), Raised>> {
        self.optional("not_taken", &[record])
            .map(|spoke| spoke.map(|_| ()))
    }
    fn holds(&mut self, record: &Value) -> Option<Result<Value, Raised>> {
        self.optional("holds", &[record]).map(plain)
    }
    fn watched_due(&mut self, _view: &dyn View) -> Option<Spoke> {
        self.optional("watched_due", &[&Value::Null])
    }
    fn words_sent(&mut self, record: &Value) -> Option<Result<(), Raised>> {
        self.optional("words_sent", &[record])
            .map(|spoke| spoke.map(|_| ()))
    }
    fn acted_when_told(&mut self, told: Box<dyn FnOnce() + Send>) -> Option<Result<(), Raised>> {
        if !self.has("acted_when_told") {
            return None;
        }
        Some(
            self.answer("acted_when_told", &[&Value::Null], Some(told))
                .map(|_| ()),
        )
    }
    fn tend(&mut self, _view: &dyn View) -> Option<Spoke> {
        self.optional("tend", &[&Value::Null])
    }
    fn images_of(&mut self, record: &Value) -> Option<Spoke> {
        self.optional("images_of", &[record])
    }
}
