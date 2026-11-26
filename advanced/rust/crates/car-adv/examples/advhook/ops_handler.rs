//! The handler's ops (`handler.*`): the input read through its allow-list, `stop_of`, `continues`, `decide` and `main` over
//! the hands of a case - whether the capability is on, the person's settings, Codex's latest turn of a conversation, the shared
//! claim and the clock, each answering from the case, and the claim written down when it is made.

use std::io::Cursor;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Duration;

use car_adv::hook::handler::{self, Hands};
use car_adv::jsonx::object;
use car_adv::vocabulary::HookOutcome;
use car_machine::json::{Map, Str, Value};

use crate::util::{Failure, Out, arg, list, map, tagged_float, text};

fn field<'a>(case: &'a Map, name: &str) -> &'a Value {
    static NULL: Value = Value::Null;
    case.get(name).unwrap_or(&NULL)
}

fn raise_of(item: &Value) -> Option<String> {
    match item {
        Value::Object(found) => match found.get("raise") {
            Some(Value::Str(class)) => class.as_str().map(str::to_owned),
            _ => None,
        },
        _ => None,
    }
}

struct Scripted {
    case: Map,
    ticks: AtomicUsize,
    log: Mutex<Vec<Value>>,
}

impl Scripted {
    fn pause(&self, name: &str) {
        if let Ok(seconds) = tagged_float(field(&self.case, name))
            && seconds > 0.0
        {
            std::thread::sleep(Duration::from_secs_f64(seconds));
        }
    }
}

impl Hands for Scripted {
    fn armed(&self) -> Result<bool, String> {
        let item = field(&self.case, "armed");
        match raise_of(item) {
            Some(class) => Err(class),
            None => Ok(matches!(item, Value::Bool(true))),
        }
    }

    fn settings(&self) -> Result<Value, String> {
        let item = field(&self.case, "settings");
        raise_of(item).map_or_else(|| Ok(item.clone()), Err)
    }

    fn latest(&self, thread: &str) -> Result<Value, String> {
        self.pause("delay_latest");
        let latest = field(&self.case, "latest");
        let item = match latest {
            Value::Object(found) => found
                .get(thread)
                .or_else(|| found.get("*"))
                .cloned()
                .unwrap_or(Value::Null),
            _ => Value::Null,
        };
        raise_of(&item).map_or(Ok(item), Err)
    }

    fn claim(
        &self,
        failure: &Map,
        turn_key: &str,
        now: f64,
    ) -> Result<Option<HookOutcome>, String> {
        self.log
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .push(Value::Array(vec![
                Value::Object(failure.clone()),
                Value::from(turn_key),
                Value::Float(now),
            ]));
        self.pause("delay_claim");
        let item = field(&self.case, "claim");
        if let Some(class) = raise_of(item) {
            return Err(class);
        }
        Ok(match item {
            Value::Str(word) => word.as_str().and_then(HookOutcome::parse),
            _ => None,
        })
    }

    fn clock(&self) -> f64 {
        let (start, step) = match field(&self.case, "clock") {
            Value::Object(clock) => (
                tagged_float(field(clock, "start")).unwrap_or(0.0),
                tagged_float(field(clock, "step")).unwrap_or(0.0),
            ),
            _ => (0.0, 0.0),
        };
        start + step * self.ticks.fetch_add(1, Ordering::SeqCst) as f64
    }

    fn variable(&self, _name: &str) -> Option<String> {
        None
    }

    fn languages(&self) -> Vec<String> {
        Vec::new()
    }
}

/// An input as a case writes it: text, a list of bytes, or `{"repeat": [byte, count]}`.
fn bytes_of(value: &Value) -> Result<Vec<u8>, Failure> {
    match value {
        Value::Str(each) => Ok(each
            .as_str()
            .ok_or_else(crate::util::bad)?
            .as_bytes()
            .to_vec()),
        Value::Array(items) => items
            .iter()
            .map(|each| match each {
                Value::Int(byte) => byte
                    .as_i64()
                    .and_then(|byte| u8::try_from(byte).ok())
                    .ok_or_else(crate::util::bad),
                _ => Err(crate::util::bad()),
            })
            .collect(),
        Value::Object(found) => {
            let pair = list(found.get("repeat").ok_or_else(crate::util::bad)?)?;
            let (byte, many) = (
                crate::util::number(arg(pair, 0)?)?,
                crate::util::number(arg(pair, 1)?)?,
            );
            Ok(vec![
                u8::try_from(byte).map_err(|_| crate::util::bad())?;
                many as usize
            ])
        }
        _ => Err(crate::util::bad()),
    }
}

pub fn run(op: &str, args: &[Value]) -> Out {
    match op {
        "handler.read_input" => {
            Ok(handler::read_input(&bytes_of(arg(args, 0)?)?).map_or(Value::Null, Value::Object))
        }
        "handler.pick" => Ok(handler::pick(arg(args, 0)?).map_or(Value::Null, Value::Object)),
        "handler.stop_of" => Ok(handler::stop_of(map(arg(args, 0)?)?).map_or(
            Value::Null,
            |(thread, turn)| {
                Value::Array(vec![
                    Value::from(thread),
                    turn.map_or(Value::Null, Value::from),
                ])
            },
        )),
        "handler.turn_key" => Ok(Value::from(handler::turn_key(text(arg(args, 0)?)?))),
        "handler.continues" => Ok(Value::Bool(handler::continues(
            map(arg(args, 0)?)?,
            arg(args, 1)?,
        ))),
        "handler.decide" | "handler.main" => {
            let case = map(arg(args, 0)?)?.clone();
            let scripted = Arc::new(Scripted {
                case: case.clone(),
                ticks: AtomicUsize::new(0),
                log: Mutex::new(Vec::new()),
            });
            let mut shown = Map::new();
            if op == "handler.decide" {
                let picked = map(field(&case, "picked"))?;
                let claiming = std::sync::atomic::AtomicBool::new(false);
                let started = match field(&case, "started") {
                    Value::Null => None,
                    other => Some(tagged_float(other)?),
                };
                let decided = handler::decide(picked, &*scripted, started, Some(&claiming));
                shown.insert(
                    Str::from("result"),
                    match decided {
                        Ok(reason) => reason.map_or(Value::Null, Value::from),
                        Err(class) => object([("error", Value::from(class))]),
                    },
                );
                shown.insert(
                    Str::from("claiming"),
                    Value::Bool(claiming.load(Ordering::SeqCst)),
                );
            } else {
                let argv: Vec<String> = list(field(&case, "argv"))?
                    .iter()
                    .map(|each| text(each).map(str::to_owned))
                    .collect::<Result<_, _>>()?;
                let data = bytes_of(field(&case, "input"))?;
                let mut out = Vec::new();
                let code = handler::main(
                    &argv,
                    Box::new(Cursor::new(data)),
                    &mut out,
                    Some(scripted.clone()),
                    None,
                );
                shown.insert(Str::from("code"), Value::from(i64::from(code)));
                shown.insert(
                    Str::from("stdout"),
                    Value::from(String::from_utf8_lossy(&out).into_owned()),
                );
            }
            shown.insert(
                Str::from("claims"),
                Value::Array(
                    scripted
                        .log
                        .lock()
                        .unwrap_or_else(std::sync::PoisonError::into_inner)
                        .clone(),
                ),
            );
            Ok(Value::Object(shown))
        }
        _ => Err(Failure::new("UnknownOp")),
    }
}
