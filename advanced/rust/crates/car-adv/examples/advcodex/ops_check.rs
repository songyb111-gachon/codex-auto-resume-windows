//! `autocheck`'s ops: `ac.checks`, `ac.judge`, `ac.feature_words`, `ac.read_record`, `ac.results_for`, `ac.diagnostics`,
//! `ac.due`, `ac.write`, `ac.engine_key`, `ac.run_engine`, `ac.probe_engine`, `ac.tend`, `ac.reset`.

use std::path::Path;
use std::sync::Arc;

use car_adv::autocheck::{self, Answer, AskError, Clock, TendError, World, WriteError};
use car_adv::jsonx::object;
use car_codex::system::System;
use car_machine::json::{Map, Value};

use crate::{Context, Failure, Out, arg, bad, float, maybe_text, text};

fn paths(home: &str) -> Result<car_config::Paths, Failure> {
    let no_env = |_: &str| None;
    car_config::Paths::new(
        Some(home),
        home,
        &no_env,
        car_config::Os::here(false, Arc::new(Links)),
    )
    .map_err(Failure::new)
}

#[derive(Debug)]
struct Links;

impl car_config::Links for Links {
    fn is_symlink(&self, path: &std::path::Path) -> bool {
        car_platform::links::is_symlink(path)
    }
}

fn words(list: &[&str]) -> Value {
    Value::Array(list.iter().map(|each| Value::from(*each)).collect())
}

fn pairs(list: &[(&str, &str)]) -> Value {
    Value::Array(
        list.iter()
            .map(|(a, b)| Value::Array(vec![Value::from(*a), Value::from(*b)]))
            .collect(),
    )
}

pub fn answer(found: &Answer) -> Value {
    let map: Map = found
        .iter()
        .map(|(measurement, (word, gone))| {
            (
                measurement.as_str().into(),
                Value::Array(vec![
                    Value::from(word.as_str()),
                    Value::Array(gone.iter().map(|name| Value::from(name.as_str())).collect()),
                ]),
            )
        })
        .collect();
    Value::Object(map)
}

fn raised(class: &'static str) -> Failure {
    Failure::new(class)
}

fn world(context: &Context) -> World {
    World {
        system: Arc::clone(&context.world) as Arc<dyn System>,
        product_version: context.product_version.clone(),
    }
}

pub fn run(context: &Context, op: &str, args: &[Value]) -> Out {
    match op {
        "ac.checks" => Ok(Value::Array(
            autocheck::CHECKS
                .iter()
                .map(|(measurement, row)| {
                    Value::Array(vec![
                        Value::from(measurement.as_str()),
                        Value::from(row.reach.as_str()),
                        words(row.methods),
                        pairs(row.params),
                        words(row.requests),
                        pairs(row.fields),
                        pairs(row.words),
                        row.feature.map_or(Value::Null, Value::from),
                    ])
                })
                .collect(),
        )),
        "ac.judge" => {
            let features = maybe_text(arg(args, 1))?;
            autocheck::judge(arg(args, 0), features.as_deref())
                .map(|found| answer(&found))
                .map_err(raised)
        }
        "ac.feature_words" => Ok(
            match autocheck::feature_words(&text(arg(args, 0))?, &text(arg(args, 1))?) {
                Some(found) => Value::Array(found.into_iter().map(Value::from).collect()),
                None => Value::Null,
            },
        ),
        "ac.read_record" => {
            let folder = text(arg(args, 0))?;
            autocheck::read_record(Path::new(&folder))
                .map(|found| found.unwrap_or(Value::Null))
                .map_err(raised)
        }
        "ac.results_for" => {
            let folder = text(arg(args, 0))?;
            let engine = match arg(args, 1) {
                Value::Str(engine) => engine.as_str().map(str::to_owned),
                _ => None,
            };
            let found =
                autocheck::results_for(Path::new(&folder), engine.as_deref()).map_err(raised)?;
            // A mapping its readers look up; written in its keys' order, as the reference's is sorted for the diff.
            let mut pairs: Vec<(&str, &str)> = found
                .iter()
                .map(|(m, word)| (m.as_str(), word.as_str()))
                .collect();
            pairs.sort_unstable();
            Ok(Value::Object(
                pairs
                    .into_iter()
                    .map(|(m, word)| (m.into(), Value::from(word)))
                    .collect(),
            ))
        }
        "ac.diagnostics" => {
            let folder = text(arg(args, 0))?;
            autocheck::diagnostics(Path::new(&folder))
                .map(|found| found.unwrap_or(Value::Null))
                .map_err(raised)
        }
        "ac.due" => {
            let record = match arg(args, 0) {
                Value::Null => None,
                other => Some(other.clone()),
            };
            let key = match arg(args, 1) {
                Value::Null => None,
                other => Some(other.clone()),
            };
            autocheck::due(record.as_ref(), key.as_ref(), float(arg(args, 2))?)
                .map(Value::Bool)
                .map_err(raised)
        }
        "ac.write" => {
            let paths = paths(&text(arg(args, 0))?)?;
            match autocheck::write(&paths, arg(args, 1)) {
                Ok(()) => Ok(Value::Null),
                Err(WriteError::Os) => Err(Failure::new("OSError")),
                Err(WriteError::Config(_)) => Err(Failure::new("ConfigError")),
            }
        }
        "ac.engine_key" => autocheck::engine_key(context.world.as_ref(), &text(arg(args, 0))?)
            .map(|found| found.unwrap_or(Value::Null))
            .map_err(raised),
        "ac.run_engine" => {
            let scratch =
                autocheck::mkdtemp("car-autocheck-").map_err(|_| Failure::new("OSError"))?;
            let done = autocheck::run_engine(&world(context), &text(arg(args, 0))?, &scratch);
            let _ = std::fs::remove_dir_all(&scratch);
            match done {
                Ok(Some((version, found))) => {
                    Ok(Value::Array(vec![Value::from(version), answer(&found)]))
                }
                Ok(None) => Ok(Value::Null),
                Err(AskError::Adapter(code)) => Err(Failure::coded("AdapterError", &code)),
                Err(AskError::Os) => Err(Failure::new("OSError")),
                Err(AskError::Raised(class)) => Err(Failure::new(class)),
            }
        }
        "ac.probe_engine" => Ok(autocheck::probe_engine(
            &world(context),
            &text(arg(args, 0))?,
        )),
        "ac.tend" => {
            let home = text(arg(args, 0))?;
            let paths = paths(&home)?;
            let now = float(arg(args, 1))?;
            let clock: Clock = Arc::new(move || now);
            let started = autocheck::tend(&world(context), &paths, clock);
            autocheck::join(&paths.home);
            match started {
                Ok(started) => Ok(Value::Bool(started)),
                Err(TendError::Raised(class)) => Err(Failure::new(class)),
                Err(TendError::Write(WriteError::Os)) => Err(Failure::new("OSError")),
                Err(TendError::Write(WriteError::Config(_))) => Err(Failure::new("ConfigError")),
            }
        }
        "ac.reset" => {
            autocheck::reset();
            Ok(Value::Null)
        }
        "ac.attempt" => {
            let tries = match arg(args, 1) {
                Value::Int(n) => n.as_i64().ok_or_else(bad)?,
                _ => return Err(bad()),
            };
            Ok(autocheck::attempt(
                arg(args, 0),
                tries,
                float(arg(args, 2))?,
            ))
        }
        "ac.settled_words" => Ok(object([
            ("here", Value::from(autocheck::Settled::Here.word())),
            ("failed", Value::from(autocheck::Settled::Failed.word())),
            ("gone", Value::from(autocheck::Settled::Gone.word())),
            (
                "stands_in",
                Value::from(autocheck::Settled::StandsIn.word()),
            ),
            (
                "unsettled",
                Value::from(autocheck::Settled::Unsettled.word()),
            ),
        ])),
        _ => Err(Failure::new("UnknownOp")),
    }
}
