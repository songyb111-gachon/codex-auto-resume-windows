//! `codex/ipc`'s ops (seat adv72d): `ip.run` (a stop, a start or a steer on a pipe of the diff's own name, never the
//! Desktop's: refused here and by car-platform under CAR_NO_REAL_IPC), `ip.filled` and `ip.version` (the shapes). The
//! request ids count up from 1, as the reference's `uuid4` is made to.

use car_adv::codex::ipc::{self, Gate};
use car_adv::jsonx::object;
use car_machine::json::{Str, Value};

use crate::{Context, Failure, Out, arg, bad, text};

struct Guard {
    enter: Vec<Value>,
    exit: Vec<Value>,
    log: Vec<Value>,
}

fn take(list: &mut Vec<Value>, default: Value) -> Value {
    match list.len() {
        0 => default,
        1 => list[0].clone(),
        _ => list.remove(0),
    }
}

fn is_raise(value: &Value) -> bool {
    matches!(value, Value::Str(word) if word.as_str() == Some("raise"))
}

impl Gate for Guard {
    fn enter(&mut self) -> Result<Value, ()> {
        self.log.push("enter".into());
        let found = take(&mut self.enter, Value::Bool(true));
        if is_raise(&found) { Err(()) } else { Ok(found) }
    }
    fn exit(&mut self) -> Result<(), ()> {
        self.log.push("exit".into());
        if is_raise(&take(&mut self.exit, "ok".into())) {
            Err(())
        } else {
            Ok(())
        }
    }
}

fn list(spec: &Value, key: &str) -> Vec<Value> {
    match spec {
        Value::Object(map) => match map.get(key) {
            Some(Value::Array(items)) => items.clone(),
            _ => Vec::new(),
        },
        _ => Vec::new(),
    }
}

pub fn run(_context: &Context, op: &str, args: &[Value]) -> Out {
    match op {
        "ip.run" => {
            let kind = text(arg(args, 0))?;
            let name = text(arg(args, 1))?;
            if name.to_lowercase().contains("codex-ipc") {
                return Err(Failure::new("AssertionError"));
            }
            let mut counter = 0u64;
            let mut ids = move || {
                counter += 1;
                format!("00000000-0000-4000-8000-{counter:012x}")
            };
            let gate_spec = arg(args, 5);
            let mut guard = Guard {
                enter: list(gate_spec, "enter"),
                exit: list(gate_spec, "exit"),
                log: Vec::new(),
            };
            let gate: Option<&mut dyn Gate> = if matches!(gate_spec, Value::Null) {
                None
            } else {
                Some(&mut guard)
            };
            let (thread, extra) = (arg(args, 2), arg(args, 3));
            let word = match kind.as_str() {
                "stop" => ipc::stop_turn(thread, extra, Some(&name), gate, &mut ids),
                "start" => ipc::start_turn(thread, extra, Some(&name), gate, &mut ids),
                _ => ipc::steer_turn(thread, extra, arg(args, 4), Some(&name), gate, &mut ids),
            };
            Ok(object([
                ("word", word.into()),
                ("gate", Value::Array(guard.log)),
            ]))
        }
        "ip.filled" => {
            let shape = ipc::request_shape(
                &text(arg(args, 0))?,
                matches!(arg(args, 1), Value::Bool(true)),
            )
            .ok_or_else(|| Failure::new("KeyError"))?;
            let Value::Object(fields) = arg(args, 2) else {
                return Err(bad());
            };
            let owned: Vec<(String, Value)> = fields
                .iter()
                .map(|(key, value): (&Str, &Value)| {
                    (key.as_str().unwrap_or("").to_owned(), value.clone())
                })
                .collect();
            let borrowed: Vec<(&str, Value)> = owned
                .iter()
                .map(|(key, value)| (key.as_str(), value.clone()))
                .collect();
            Ok(ipc::filled(&shape.1, &borrowed))
        }
        "ip.version" => ipc::request_shape(
            &text(arg(args, 0))?,
            matches!(arg(args, 1), Value::Bool(true)),
        )
        .map(|(version, _)| Value::from(version))
        .ok_or_else(|| Failure::new("KeyError")),
        _ => Err(Failure::new("UnknownOp")),
    }
}
