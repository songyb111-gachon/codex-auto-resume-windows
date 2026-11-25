//! `codex/protocol`'s ops: `pr.tables`, `pr.reply_to`, `pr.methods_for`, `pr.methods_for_capability`, `pr.grants_nothing`.

use car_adv::codex::protocol;
use car_adv::jsonx::object;
use car_adv::vocabulary::{Measurement, parse};
use car_machine::json::{Map, Value};

use crate::{Context, Failure, Out, arg, text};

fn words<'a>(list: impl IntoIterator<Item = &'a str>) -> Value {
    Value::Array(list.into_iter().map(Value::from).collect())
}

fn sorted<'a>(list: impl IntoIterator<Item = &'a str>) -> Value {
    let mut found: Vec<&str> = list.into_iter().collect();
    found.sort_unstable();
    found.dedup();
    words(found)
}

pub fn run(_context: &Context, op: &str, args: &[Value]) -> Out {
    match op {
        "pr.tables" => {
            let measurements: Map = protocol::MEASUREMENT_METHODS
                .iter()
                .map(|(m, methods)| (m.as_str().into(), words(methods.iter().copied())))
                .collect();
            let capabilities: Map = protocol::CAPABILITY_METHODS
                .iter()
                .map(|(c, methods)| ((*c).into(), words(methods.iter().copied())))
                .collect();
            let declines: Map = protocol::DECLINED_REQUESTS
                .iter()
                .map(|method| {
                    (
                        (*method).into(),
                        protocol::decline_answer(method).unwrap_or(Value::Null),
                    )
                })
                .collect();
            Ok(object([
                ("measurement", Value::Object(measurements)),
                ("capability", Value::Object(capabilities)),
                (
                    "forbidden",
                    sorted(protocol::FORBIDDEN_METHODS.iter().copied()),
                ),
                ("declines", Value::Object(declines)),
                (
                    "accepting",
                    sorted(protocol::ACCEPTING_WORDS.iter().copied()),
                ),
                ("measured", sorted(protocol::measured_methods())),
                ("advanced", sorted(protocol::advanced_methods())),
                ("rejection", Value::from(protocol::REJECTION)),
            ]))
        }
        "pr.reply_to" => Ok(protocol::reply_to(arg(args, 0))),
        "pr.grants_nothing" => Ok(Value::Bool(protocol::grants_nothing(arg(args, 0)))),
        "pr.methods_for" => {
            let measurement = parse::<Measurement>(&text(arg(args, 0))?)
                .ok_or_else(|| Failure::new("ValueError"))?;
            Ok(sorted(protocol::methods_for(measurement)))
        }
        "pr.methods_for_capability" => Ok(sorted(protocol::methods_for_capability(&text(arg(
            args, 0,
        ))?))),
        _ => Err(Failure::new("UnknownOp")),
    }
}
