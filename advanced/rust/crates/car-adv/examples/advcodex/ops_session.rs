//! `protocol.Session` and `submitted`'s op (seat adv72d): `ss.run` opens one session on the diff's fake engine (a
//! car-fake-codex copy in the scratch LOCALAPPDATA's Codex bin folder), runs its steps and closes it; the fake keeps
//! every byte it was sent, which the diff compares.

use std::sync::Arc;

use car_adv::codex::session::{Channel, Session, SessionError, Submitted, submitted};
use car_adv::jsonx::object;
use car_adv::vocabulary::{Measurement, parse};
use car_codex::system::System;
use car_codex::transport::Backend;
use car_machine::json::{Map, Value};

use crate::{Context, Failure, Out, arg, bad, float, maybe_text, text};

fn error_value(error: &SessionError) -> Value {
    let mut map = Map::new();
    map.insert("error".into(), error.class().into());
    if matches!(
        error,
        SessionError::Refused | SessionError::Adapter(_) | SessionError::ByCodex { .. }
    ) {
        map.insert("text".into(), error.text().into());
    }
    if let SessionError::ByCodex { method, code } = error {
        map.insert("method".into(), method.as_str().into());
        map.insert("code".into(), code.map_or(Value::Null, Value::from));
    }
    Value::Object(map)
}

fn params(value: &Value) -> Option<Value> {
    match value {
        Value::Null => None,
        other => Some(other.clone()),
    }
}

fn counts(found: std::collections::BTreeMap<String, i64>) -> Value {
    let mut map = Map::new();
    for (key, value) in found {
        map.insert(key.as_str().into(), value.into());
    }
    Value::Object(map)
}

fn int(value: &Value) -> Result<i64, Failure> {
    match value {
        Value::Int(n) => n.as_i64().ok_or_else(bad),
        _ => Err(bad()),
    }
}

pub fn run(context: &Context, op: &str, args: &[Value]) -> Out {
    if op != "ss.run" {
        return Err(Failure::new("UnknownOp"));
    }
    let exe = text(arg(args, 0))?;
    let home = std::env::var("CODEX_HOME").map_err(|_| bad())?;
    let measurement = match maybe_text(arg(args, 1))? {
        None => None,
        Some(word) => match parse::<Measurement>(&word) {
            Some(found) => Some(found),
            None => return Ok(object([("new", object([("error", "ValueError".into())]))])),
        },
    };
    let capability = maybe_text(arg(args, 2))?;
    let config = match arg(args, 3) {
        Value::Array(pairs) => pairs
            .iter()
            .map(|pair| match pair {
                Value::Array(two) if two.len() == 2 => Ok((text(&two[0])?, text(&two[1])?)),
                _ => Err(bad()),
            })
            .collect::<Result<Vec<_>, _>>()?,
        _ => Vec::new(),
    };
    let backend = Backend::new(
        Arc::clone(&context.world) as Arc<dyn System>,
        &home,
        &exe,
        false,
        &context.product_version,
    );
    let mut session = match Session::new(backend, measurement, capability.as_deref(), config) {
        Ok(session) => session,
        Err(error) => return Ok(object([("new", error_value(&error))])),
    };
    if let Err(error) = session.enter() {
        return Ok(object([("enter", error_value(&error))]));
    }
    let Value::Array(steps) = arg(args, 4) else {
        return Err(bad());
    };
    let mut out = Vec::new();
    let mut pending: Vec<Option<Submitted>> = Vec::new();
    for step in steps {
        let Value::Array(parts) = step else {
            return Err(bad());
        };
        let word = text(arg(parts, 0))?;
        let method = || text(arg(parts, 1));
        let done: Result<Value, SessionError> = match word.as_str() {
            "call" => session.call(&method()?, params(arg(parts, 2))),
            "submit" => session
                .submit(&method()?, params(arg(parts, 2)))
                .map(Value::from),
            "receive" => session.receive_within(
                &method()?,
                int(arg(parts, 2))?,
                params(arg(parts, 3)).as_ref(),
                float(arg(parts, 4))?,
            ),
            "submitted" => {
                pending.push(Some(submitted(
                    &mut session,
                    &method()?,
                    params(arg(parts, 2)),
                )));
                Ok(Value::from((pending.len() - 1) as i64))
            }
            "answer" => {
                let at = int(arg(parts, 1))? as usize;
                match pending.get_mut(at).and_then(Option::take) {
                    Some(found) => found.answer(&mut session),
                    None => return Err(bad()),
                }
            }
            "events" => Ok(Value::Array(session.drain_events())),
            "declined" => Ok(Value::from(session.declined_count())),
            _ => return Err(bad()),
        };
        out.push(match done {
            Ok(value) => object([("ok", value)]),
            Err(error) => error_value(&error),
        });
    }
    session.exit();
    let (declined, refused) = session.counted();
    Ok(object([
        ("steps", Value::Array(out)),
        ("declined", counts(declined)),
        ("refused", counts(refused)),
    ]))
}
