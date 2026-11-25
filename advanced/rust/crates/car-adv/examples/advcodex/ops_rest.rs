//! The S7.2c remainder's other ops (seat adv72d): `bt.booted_of` (turns' read of core's store) and `tk.*`
//! (`codex/tokens`: keys, the watched homes, the rollouts found, `unchanged` and `read` under the process's own TZ,
//! through car-platform's `Crt` as the product's clock).

use std::path::{Path, PathBuf};

use car_adv::codex::{inuse, tokens};
use car_codex::system::PolicyOs;
use car_machine::json::{Int, Map, Value};
use car_platform::localclock::Crt;

use crate::{Context, Failure, Out, arg, bad, float, maybe_text, text};

fn env(name: &str) -> Option<String> {
    std::env::var(name).ok()
}

fn int(value: &Value) -> Result<i64, Failure> {
    match value {
        Value::Int(n) => n.as_i64().ok_or_else(bad),
        _ => Err(bad()),
    }
}

fn big(value: i128) -> Result<Value, Failure> {
    Ok(Value::Int(Int::parse(&value.to_string()).ok_or_else(bad)?))
}

fn rollout_of(value: &Value) -> Result<tokens::Rollout, Failure> {
    let Value::Array(parts) = value else {
        return Err(bad());
    };
    let at = |index: usize| parts.get(index).unwrap_or(&Value::Null);
    let changed = match at(4) {
        Value::Int(n) => n.to_string().parse::<i128>().map_err(|_| bad())?,
        _ => return Err(bad()),
    };
    Ok(tokens::Rollout {
        home: text(at(0))?,
        path: text(at(1))?,
        key: text(at(2))?,
        size: int(at(3))?,
        changed_ns: changed,
    })
}

fn rollout_out(rollout: &tokens::Rollout) -> Result<Value, Failure> {
    Ok(Value::Array(vec![
        rollout.home.as_str().into(),
        rollout.path.as_str().into(),
        rollout.key.as_str().into(),
        rollout.size.into(),
        big(rollout.changed_ns)?,
    ]))
}

fn known_of(value: &Value) -> Option<&Map> {
    match value {
        Value::Object(map) => Some(map),
        _ => None,
    }
}

fn opt(value: &Option<String>) -> Value {
    value.as_deref().map_or(Value::Null, Value::from)
}

pub fn run(context: &Context, op: &str, args: &[Value]) -> Out {
    let os = PolicyOs;
    match op {
        "bt.booted_of" => Ok(car_adv::codex::turns::booted_of(Path::new(&text(arg(
            args, 0,
        ))?))),
        "tk.file_key" => tokens::file_key(&os, &text(arg(args, 0))?)
            .map(Value::from)
            .map_err(|_| Failure::new("OSError")),
        "tk.tell" => inuse::tell(
            &text(arg(args, 0))?,
            &text(arg(args, 1))?,
            &text(arg(args, 2))?,
            &context.world.os,
        )
        .map(|()| Value::Null)
        .map_err(|_| Failure::new("OSError")),
        "tk.watched_homes" => {
            let home = maybe_text(arg(args, 0))?;
            let settings: Option<PathBuf> = home
                .as_deref()
                .map(|home| PathBuf::from(home).join("config").join("settings.json"));
            Ok(Value::Array(
                tokens::watched_homes(
                    home.as_deref(),
                    settings.as_deref(),
                    &env,
                    &context.world.os,
                    &os,
                )
                .into_iter()
                .map(Value::from)
                .collect(),
            ))
        }
        "tk.rollouts" => {
            let Value::Array(homes) = arg(args, 0) else {
                return Err(bad());
            };
            let homes = homes.iter().map(text).collect::<Result<Vec<_>, _>>()?;
            let found = tokens::rollouts(&os, &homes, float(arg(args, 1))?, int(arg(args, 2))?)
                .map_err(Failure::new)?;
            Ok(Value::Array(
                found
                    .iter()
                    .map(rollout_out)
                    .collect::<Result<Vec<_>, _>>()?,
            ))
        }
        "tk.unchanged" => tokens::unchanged(&rollout_of(arg(args, 0))?, known_of(arg(args, 1)))
            .map(Value::Bool)
            .map_err(Failure::new),
        "tk.read" => {
            let done = tokens::read(
                &rollout_of(arg(args, 0))?,
                known_of(arg(args, 1)),
                int(arg(args, 2))?,
                &Crt,
            )
            .map_err(Failure::new)?;
            let mut days = Map::new();
            for (day, numbers) in &done.days {
                days.insert(
                    day.as_str().into(),
                    Value::Array(numbers.iter().map(|n| Value::from(*n)).collect()),
                );
            }
            Ok(Value::Array(vec![
                done.key.as_str().into(),
                opt(&done.thread_id),
                done.size.into(),
                done.offset.into(),
                big(done.changed_ns)?,
                Value::Object(days),
                opt(&done.project_key),
                done.outcome.into(),
                done.consumed.into(),
            ]))
        }
        _ => Err(Failure::new("UnknownOp")),
    }
}
