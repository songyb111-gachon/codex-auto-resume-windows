//! `codex/inuse`'s ops: `iu.tell`, `iu.told`, `iu.forget`, `iu.saw`, `iu.elsewhere`, `iu.home`, `iu.pinned`, `iu.backend`,
//! `iu.reset`; and `iu.meter`, what core's `_served_elsewhere` would be told through the plug after a look.

use std::path::PathBuf;
use std::sync::Arc;

use car_adv::codex::inuse::{self, BackendError, Discovery, Looked};
use car_adv::jsonx::object;
use car_codex::system::System;
use car_machine::json::Value;

use crate::{Context, Failure, Out, arg, maybe_text, text};

/// A backend a look was made through, as a case gives it: `{"codex_exe": path or null, "served_elsewhere": [...]}`.
struct Given(Value);

impl Looked for Given {
    fn codex_exe(&self) -> Option<String> {
        match &self.0 {
            Value::Object(map) => match map.get("codex_exe") {
                Some(Value::Str(exe)) => exe.as_str().map(str::to_owned),
                _ => None,
            },
            _ => None,
        }
    }
    fn served_elsewhere(&self) -> Vec<String> {
        match &self.0 {
            Value::Object(map) => match map.get("served_elsewhere") {
                Some(Value::Array(items)) => items
                    .iter()
                    .filter_map(|item| match item {
                        Value::Str(text) => text.as_str().map(str::to_owned),
                        _ => None,
                    })
                    .collect(),
                _ => Vec::new(),
            },
            _ => Vec::new(),
        }
    }
}

fn set(found: std::collections::BTreeSet<String>) -> Value {
    Value::Array(found.into_iter().map(Value::from).collect())
}

fn env(name: &str) -> Option<String> {
    std::env::var(name).ok()
}

fn settings_file(home: Option<&str>) -> Option<PathBuf> {
    home.map(|home| PathBuf::from(home).join("config").join("settings.json"))
}

pub fn run(context: &Context, op: &str, args: &[Value]) -> Out {
    let home = maybe_text(arg(args, 0))?;
    let home = home.as_deref();
    match op {
        "iu.tell" => {
            let home = home.ok_or_else(crate::bad)?;
            inuse::tell(home, &text(arg(args, 1))?, &text(arg(args, 2))?, &context.world.os)
                .map(|()| Value::Null)
                .map_err(|_| Failure::new("OSError"))
        }
        "iu.told" => Ok(match inuse::told(home) {
            Some((exe, where_)) => Value::Array(vec![Value::from(exe), Value::from(where_)]),
            None => Value::Null,
        }),
        "iu.forget" => {
            inuse::forget(home.ok_or_else(crate::bad)?);
            Ok(Value::Null)
        }
        "iu.saw" => {
            inuse::saw(home, &Given(arg(args, 1).clone()));
            Ok(Value::Null)
        }
        "iu.elsewhere" => Ok(set(inuse::elsewhere(home))),
        "iu.home" => inuse::home(home, &env, &context.world.os)
            .map(Value::from)
            .map_err(Failure::new),
        "iu.pinned" => Ok(inuse::pinned(settings_file(home).as_deref()).map_or(Value::Null, Value::from)),
        "iu.backend" => {
            let discovery = Discovery {
                system: Arc::clone(&context.world) as Arc<dyn System>,
                env: &env,
                os: &context.world.os,
                product_version: context.product_version.clone(),
            };
            match inuse::backend(home, settings_file(home).as_deref(), &discovery) {
                Ok(made) => Ok(object([
                    ("codex_exe", Value::from(made.codex_exe.as_str())),
                    ("codex_home", Value::from(made.codex_home.as_str())),
                    ("engine_version", made.engine_version.clone().map_or(Value::Null, Value::from)),
                ])),
                Err(BackendError::Adapter(code)) | Err(BackendError::Check(code)) => {
                    Err(Failure::coded("AdapterError", &code))
                }
                Err(BackendError::Config(_)) => Err(Failure::new("ConfigError")),
                Err(BackendError::Raised(class)) => Err(Failure::new(class)),
            }
        }
        "iu.reset" => {
            inuse::reset();
            Ok(Value::Null)
        }
        _ => Err(Failure::new("UnknownOp")),
    }
}
