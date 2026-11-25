//! `claim.run`: the Stop hook's shared claim over a scratch home - core's `state.sqlite` made by the tag's own store, this
//! edition's file attached - one claim after another, each answering what it wrote, with the administrator's policy keys given
//! by the case (never read from the registry) and the files left for the diff to dump.

use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex};

use car_adv::engine::hookclaims::{self, World};
use car_adv::registry;
use car_adv::state::seam::Tokens;
use car_machine::json::{Map, Value};
use car_platform::localclock::Crt;
use car_policy::settings::managed::Managed;

use crate::ops_plugin::paths_of;
use crate::util::{Failure, Out, arg, list, map, tagged_float, text};

struct Counter(Mutex<u64>);

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

fn managed_of(value: &Value) -> Managed {
    let Value::Object(spec) = value else {
        return Managed::default();
    };
    let flag = |name: &str| matches!(spec.get(name), Some(Value::Bool(true)));
    Managed {
        disable_auto_resume: flag("disable_auto_resume"),
        force_observe_only: flag("force_observe_only"),
        max_recovery_attempts: match spec.get("max_recovery_attempts") {
            Some(Value::Int(number)) => number.as_i64(),
            _ => None,
        },
        quiet_hours: match spec.get("quiet_hours") {
            Some(Value::Array(windows)) => windows
                .iter()
                .filter_map(|each| match each {
                    Value::Object(window) => Some(window.clone()),
                    _ => None,
                })
                .collect(),
            _ => Vec::new(),
        },
        ..Managed::default()
    }
}

pub fn run(op: &str, args: &[Value]) -> Out {
    if op != "claim.run" {
        return Err(Failure::new("UnknownOp"));
    }
    let home = text(arg(args, 0)?)?.to_owned();
    let paths = paths_of(&home);
    let registry = Arc::new(registry::shipped(false).map_err(|_| Failure::new("RegistryError"))?);
    let mut out = Vec::new();
    for step in list(arg(args, 1)?)? {
        let parts = list(step)?;
        out.push(match text(arg(parts, 0)?)? {
            "claim" => {
                let failure: Map = map(arg(parts, 1)?)?.clone();
                let key = text(arg(parts, 2)?)?.to_owned();
                let now = tagged_float(arg(parts, 3)?)?;
                let given = managed_of(arg(parts, 4)?);
                let busy = tagged_float(arg(parts, 5)?)?;
                let managed = move || Ok(given.clone());
                let world = World {
                    managed: &managed,
                    clock: &Crt,
                    tokens: Arc::new(Counter(Mutex::new(0))),
                };
                let found = hookclaims::claim(&paths, &failure, &key, now, &registry, busy, &world);
                car_adv::jsonx::object([(
                    "ok",
                    found.map_or(Value::Null, |each| Value::from(each.as_str())),
                )])
            }
            "blocked_at" => car_adv::jsonx::object([(
                "ok",
                hookclaims::blocked_at(&paths, arg(parts, 1)?).map_or(Value::Null, Value::Float),
            )]),
            "sql" => {
                let core = PathBuf::from(&home).join("config").join("state.sqlite");
                if let Ok(db) = rusqlite::Connection::open(Path::new(&core)) {
                    let _ = db.execute_batch(text(arg(parts, 1)?)?);
                }
                Value::Null
            }
            _ => return Err(Failure::new("BadArgument")),
        });
    }
    Ok(Value::Array(out))
}
