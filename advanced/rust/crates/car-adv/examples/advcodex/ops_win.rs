//! `win/`'s ops (seat adv72d): `wn.timer`, `wn.stop`, `wn.filetime`, `wn.event_name`. The wake timer, the power
//! settings and the stop event are scripted stand-ins of car-platform's `wake` traits that log every call in the
//! reference fake's words (`tests/rustdiff/advcodexd.py`); the `System*` types are never built here.

use std::collections::BTreeMap;
use std::sync::{Arc, Mutex, PoisonError};

use car_adv::jsonx::object;
use car_adv::win::stopflag::{self, StopFlag};
use car_adv::win::waketimer::{self, WakeTimer};
use car_machine::json::Value;
use car_platform::wake::{Call, EventKernel, Handle, PowerSettings, Raised, Scheme, TimerKernel};

use crate::{Context, Failure, Out, arg, bad, text};

/// A GUID (as `windows::core::GUID::from_u128` holds it) in the bytes a ctypes GUID structure has.
pub fn le_bytes(guid: u128) -> [u8; 16] {
    let mut out = [0u8; 16];
    out[..4].copy_from_slice(&((guid >> 96) as u32).to_le_bytes());
    out[4..6].copy_from_slice(&((guid >> 80) as u16).to_le_bytes());
    out[6..8].copy_from_slice(&((guid >> 64) as u16).to_le_bytes());
    out[8..].copy_from_slice(&(guid as u64).to_be_bytes());
    out
}

fn from_le_bytes(bytes: &[u8]) -> u128 {
    let d1 = u32::from_le_bytes(bytes[..4].try_into().unwrap_or_default());
    let d2 = u16::from_le_bytes(bytes[4..6].try_into().unwrap_or_default());
    let d3 = u16::from_le_bytes(bytes[6..8].try_into().unwrap_or_default());
    let d4 = u64::from_be_bytes(bytes[8..16].try_into().unwrap_or_default());
    (u128::from(d1) << 96) | (u128::from(d2) << 80) | (u128::from(d3) << 64) | u128::from(d4)
}

pub fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|byte| format!("{byte:02x}")).collect()
}

fn unhex(text: &str) -> Vec<u8> {
    (0..text.len() / 2)
        .filter_map(|at| u8::from_str_radix(text.get(at * 2..at * 2 + 2)?, 16).ok())
        .collect()
}

type Log = Arc<Mutex<Vec<Value>>>;

fn push(log: &Log, entry: Vec<Value>) {
    log.lock()
        .unwrap_or_else(PoisonError::into_inner)
        .push(Value::Array(entry));
}

/// The answers per call kind, taken in order (the last repeated); "raise" raises.
#[derive(Clone)]
struct Script {
    answers: Arc<Mutex<BTreeMap<String, Vec<Value>>>>,
}

impl Script {
    fn new(spec: &Value) -> Script {
        let mut answers = BTreeMap::new();
        if let Value::Object(map) = spec {
            for (key, value) in map.iter() {
                if let Value::Array(list) = value {
                    answers.insert(key.as_str().unwrap_or("").to_owned(), list.clone());
                }
            }
        }
        Script {
            answers: Arc::new(Mutex::new(answers)),
        }
    }

    fn answer(&self, kind: &str, default: Value) -> Call<Value> {
        let mut answers = self.answers.lock().unwrap_or_else(PoisonError::into_inner);
        let value = match answers.get_mut(kind) {
            None => default,
            Some(list) if list.is_empty() => default,
            Some(list) if list.len() > 1 => list.remove(0),
            Some(list) => list[0].clone(),
        };
        if matches!(&value, Value::Str(word) if word.as_str() == Some("raise")) {
            return Err(Raised);
        }
        Ok(value)
    }
}

fn int_of(value: &Value) -> i64 {
    match value {
        Value::Int(n) => n.as_i64().unwrap_or(0),
        Value::Bool(b) => i64::from(*b),
        _ => 0,
    }
}

struct FakeTimer {
    script: Script,
    log: Log,
}

impl TimerKernel for FakeTimer {
    fn create_waitable_timer(&mut self, access: u32) -> Call<Handle> {
        push(
            &self.log,
            vec![
                "create".into(),
                Value::Null,
                Value::Null,
                0.into(),
                access.into(),
            ],
        );
        Ok(int_of(&self.script.answer("create", 501.into())?) as Handle)
    }

    fn set_waitable_timer(
        &mut self,
        handle: Handle,
        due: i64,
        period: i32,
        resume: bool,
    ) -> Call<bool> {
        push(
            &self.log,
            vec![
                "set".into(),
                (handle as i64).into(),
                due.into(),
                period.into(),
                Value::Null,
                Value::Null,
                resume.into(),
            ],
        );
        Ok(int_of(&self.script.answer("set", 1.into())?) != 0)
    }

    fn cancel_waitable_timer(&mut self, handle: Handle) -> Call<bool> {
        push(&self.log, vec!["cancel".into(), (handle as i64).into()]);
        Ok(int_of(&self.script.answer("cancel", 1.into())?) != 0)
    }

    fn close_handle(&mut self, handle: Handle) -> Call<bool> {
        push(&self.log, vec!["close".into(), (handle as i64).into()]);
        Ok(int_of(&self.script.answer("close", 1.into())?) != 0)
    }

    fn system_power_status(&mut self) -> Call<Option<u8>> {
        push(&self.log, vec!["status".into()]);
        let found = self.script.answer("status", 1.into())?;
        if matches!(&found, Value::Str(word) if word.as_str() == Some("fail")) {
            return Ok(None);
        }
        Ok(Some(int_of(&found) as u8))
    }

    fn local_free(&mut self, scheme: &Scheme) -> Call<()> {
        push(
            &self.log,
            vec!["free".into(), hex(&le_bytes(scheme.guid)).into()],
        );
        self.script.answer("free", Value::Null).map(|_| ())
    }
}

struct FakePower {
    script: Script,
    log: Log,
}

impl PowerSettings for FakePower {
    fn active_scheme(&mut self) -> Call<(u32, Option<Scheme>)> {
        push(&self.log, vec!["scheme".into()]);
        let found = self.script.answer(
            "scheme",
            Value::Array(vec![0.into(), "00112233445566778899aabbccddeeff".into()]),
        )?;
        let Value::Array(pair) = found else {
            return Err(Raised);
        };
        let code = int_of(pair.first().unwrap_or(&Value::Null)) as u32;
        let scheme = match pair.get(1) {
            Some(Value::Str(guid)) => Some(Scheme {
                pointer: 1,
                guid: from_le_bytes(&unhex(guid.as_str().unwrap_or(""))),
            }),
            _ => None,
        };
        Ok((code, scheme))
    }

    fn read_value_index(
        &mut self,
        dc: bool,
        scheme: &Scheme,
        subgroup: u128,
        setting: u128,
    ) -> Call<(u32, u32)> {
        let which = if dc { "dc" } else { "ac" };
        push(
            &self.log,
            vec![
                "read".into(),
                which.into(),
                hex(&le_bytes(scheme.guid)).into(),
                hex(&le_bytes(subgroup)).into(),
                hex(&le_bytes(setting)).into(),
            ],
        );
        let found = self
            .script
            .answer(which, Value::Array(vec![0.into(), 1.into()]))?;
        let Value::Array(pair) = found else {
            return Err(Raised);
        };
        Ok((
            int_of(pair.first().unwrap_or(&Value::Null)) as u32,
            int_of(pair.get(1).unwrap_or(&Value::Null)) as u32,
        ))
    }
}

struct FakeEvents {
    script: Script,
    log: Log,
}

impl EventKernel for FakeEvents {
    fn create_event(&mut self, manual_reset: bool, initial: bool, name: &str) -> Call<Handle> {
        push(
            &self.log,
            vec![
                "create".into(),
                Value::Null,
                manual_reset.into(),
                initial.into(),
                name.into(),
            ],
        );
        Ok(int_of(&self.script.answer("create", 7.into())?) as Handle)
    }

    fn open_event(&mut self, access: u32, inherit: bool, name: &str) -> Call<Handle> {
        push(
            &self.log,
            vec!["open".into(), access.into(), inherit.into(), name.into()],
        );
        Ok(int_of(&self.script.answer("open", 9.into())?) as Handle)
    }

    fn wait_for_single_object(&mut self, handle: Handle, millis: u32) -> Call<u32> {
        push(
            &self.log,
            vec!["wait".into(), (handle as i64).into(), millis.into()],
        );
        Ok(int_of(&self.script.answer("wait", 258.into())?) as u32)
    }

    fn close_handle(&mut self, handle: Handle) -> Call<bool> {
        push(&self.log, vec!["close".into(), (handle as i64).into()]);
        Ok(int_of(&self.script.answer("close", 1.into())?) != 0)
    }
}

/// A number as the reference's `number()` reads one: a string is `float(text)`.
pub fn number(value: &Value) -> Result<f64, Failure> {
    match value {
        Value::Str(word) => match word.as_str().unwrap_or("") {
            "nan" => Ok(f64::NAN),
            "inf" => Ok(f64::INFINITY),
            "-inf" => Ok(f64::NEG_INFINITY),
            other => other.parse().map_err(|_| Failure::new("ValueError")),
        },
        Value::Int(n) => n.to_string().parse().map_err(|_| bad()),
        other => crate::float(other),
    }
}

fn steps(value: &Value) -> Result<&[Value], Failure> {
    match value {
        Value::Array(list) => Ok(list),
        _ => Err(bad()),
    }
}

fn step_word(step: &Value) -> (String, Value) {
    match step {
        Value::Array(parts) => (
            parts
                .first()
                .and_then(|word| match word {
                    Value::Str(word) => word.as_str().map(str::to_owned),
                    _ => None,
                })
                .unwrap_or_default(),
            parts.get(1).cloned().unwrap_or(Value::Null),
        ),
        _ => (String::new(), Value::Null),
    }
}

fn logged(answers: Vec<Value>, log: &Log) -> Value {
    let calls = log.lock().unwrap_or_else(PoisonError::into_inner).clone();
    object([
        ("answers", Value::Array(answers)),
        ("calls", Value::Array(calls)),
    ])
}

fn raised() -> Value {
    object([("raised", Value::Bool(true))])
}

fn timer(spec: &Value, list: &[Value]) -> Out {
    let script = Script::new(spec);
    let log: Log = Arc::default();
    let mut made = WakeTimer::new(
        Box::new(FakeTimer {
            script: script.clone(),
            log: log.clone(),
        }),
        Box::new(FakePower {
            script,
            log: log.clone(),
        }),
    );
    let mut answers = Vec::new();
    for step in list {
        let (word, value) = step_word(step);
        answers.push(match word.as_str() {
            "set" => Value::Bool(made.set(number(&value)?)),
            "cancel" => Value::Bool(made.cancel()),
            "close" => {
                made.close();
                Value::Null
            }
            "allowed" => Value::Bool(made.allowed()),
            "on_battery" => made.on_battery().map_or_else(|_| raised(), Value::Bool),
            "due" => made.due.map_or(Value::Null, Value::from),
            _ => continue,
        });
    }
    Ok(logged(answers, &log))
}

fn stop(state_dir: &str, spec: &Value, list: &[Value]) -> Out {
    let log: Log = Arc::default();
    let mut flag = StopFlag::new(
        state_dir,
        Box::new(FakeEvents {
            script: Script::new(spec),
            log: log.clone(),
        }),
    )
    .map_err(|error| Failure::coded("AdapterError", &error.0))?;
    let mut answers = Vec::new();
    for step in list {
        let (word, value) = step_word(step);
        answers.push(match word.as_str() {
            "hold" => Value::Bool(flag.hold()),
            "signalled" => Value::Bool(flag.signalled()),
            "wait" => Value::Bool(flag.wait(number(&value)?)),
            "release" => {
                flag.release();
                Value::Null
            }
            "name" => Value::from(flag.name()),
            _ => continue,
        });
    }
    Ok(logged(answers, &log))
}

pub fn run(_context: &Context, op: &str, args: &[Value]) -> Out {
    match op {
        "wn.timer" => timer(arg(args, 0), steps(arg(args, 1))?),
        "wn.stop" => stop(&text(arg(args, 0))?, arg(args, 1), steps(arg(args, 2))?),
        "wn.filetime" => match waketimer::filetime(number(arg(args, 0))?) {
            Some(due) => Ok(Value::from(due)),
            None => Err(Failure::new(if number(arg(args, 0))?.is_nan() {
                "ValueError"
            } else {
                "OverflowError"
            })),
        },
        "wn.event_name" => stopflag::event_name(&text(arg(args, 0))?)
            .map(Value::from)
            .map_err(|error| Failure::coded("AdapterError", &error.0)),
        _ => Err(Failure::new("UnknownOp")),
    }
}
