//! The reader's ops: `records.*`, `reading.*` and `evidence.*`.

use std::path::{Path, PathBuf};
use std::sync::Arc;

use car_adv::jsonx::object;
use car_adv::report::evidence::{self, Paid, Reach};
use car_adv::report::reading::{self, Refused};
use car_adv::report::records::{self, World};
use car_codex::system::PolicyOs;
use car_config::Paths;
use car_machine::json::{Map, Str, Value};
use car_platform::localclock::Crt;

use crate::util::{Failure, Out, arg, list, map, number, tagged_float, text, untag};

#[derive(Debug)]
struct Links;

impl car_config::Links for Links {
    fn is_symlink(&self, path: &Path) -> bool {
        car_platform::links::is_symlink(path)
    }
}

/// The paths of a scratch home, as the reference's `config.Paths(home)`.
pub fn paths_of(home: &str) -> Paths {
    let no_env = |_: &str| None;
    Paths::new(
        Some(home),
        home,
        &no_env,
        car_config::Os::here(false, Arc::new(Links)),
    )
    .expect("the home's paths")
}

pub fn refused(error: Refused) -> Failure {
    match error {
        Refused::Code(code) => Failure::coded("ReadRefused", code),
        Refused::Raised(class) => Failure::new(class),
    }
}

fn rows_of(value: &Value) -> Result<Vec<Map>, Failure> {
    list(value)?.iter().map(|each| map(each).cloned()).collect()
}

fn lines_of(value: &Value) -> Result<Vec<(f64, String)>, Failure> {
    list(value)?
        .iter()
        .map(|each| {
            let pair = list(each)?;
            Ok((
                tagged_float(arg(pair, 0)?)?,
                text(arg(pair, 1)?)?.to_owned(),
            ))
        })
        .collect()
}

fn reach_of(value: &Value) -> Result<Option<f64>, Failure> {
    match value {
        Value::Null => Ok(None),
        other => Ok(Some(tagged_float(other)?)),
    }
}

fn rows_value(rows: Vec<Map>) -> Value {
    Value::Array(rows.into_iter().map(Value::Object).collect())
}

fn paid_value(paid: &Paid) -> Value {
    let mut out = Map::new();
    for (key, times) in paid {
        let mut times = times.clone();
        times.sort_by(f64::total_cmp);
        times.dedup();
        out.insert(
            Str::from(key.as_str()),
            Value::Array(times.into_iter().map(Value::Float).collect()),
        );
    }
    Value::Object(out)
}

fn counts_value(counts: &[(&'static str, i64)]) -> Value {
    let mut sorted = counts.to_vec();
    sorted.sort();
    let mut out = Map::new();
    for (code, many) in sorted {
        out.insert(Str::from(code), Value::from(many));
    }
    Value::Object(out)
}

/// `records.read(paths, codex_home, asked, now=, view=)`, over a scratch home and the watcher's report a case brings.
pub fn read(args: &[Value]) -> Result<records::Found, Failure> {
    let home = text(arg(args, 0)?)?;
    let codex = PathBuf::from(text(arg(args, 1)?)?);
    let asked = arg(args, 2)?;
    let now = tagged_float(arg(args, 3)?)?;
    let view = arg(args, 4)?.clone();
    let paths = paths_of(home);
    let unused = || None;
    let world = World {
        os: Arc::new(PolicyOs),
        clock: &Crt,
        watcher: &unused,
    };
    let seen = move || Some(view.clone());
    let asked = match asked {
        Value::Null => None,
        other => Some(other),
    };
    records::read(&paths, &world, &codex, asked, now, Some(&seen)).map_err(refused)
}

pub fn run(op: &str, args: &[Value]) -> Out {
    match op {
        "records.read" => Ok(read(args)?.value()),
        "records.read_text" => {
            // The body as the golden files hold it: car-machine's writer, two-space indent, ASCII.
            let found = read(args)?;
            let text = car_machine::json::to_string(
                &found.body,
                &car_machine::json::Options::new().indent(2),
            )
            .map_err(|_| Failure::new("ValueError"))?;
            Ok(Value::from(text))
        }
        "records.ledger" => {
            let paths = paths_of(text(arg(args, 0)?)?);
            let (schema, paid, reach) =
                records::ledger(&paths, tagged_float(arg(args, 1)?)?).map_err(refused)?;
            Ok(object([
                ("schema", schema.map_or(Value::Null, Value::from)),
                ("paid", paid_value(&paid)),
                ("reach", reach.bound().map_or(Value::Null, untag)),
            ]))
        }
        "records.progress" => {
            let codex = PathBuf::from(text(arg(args, 0)?)?);
            let rows = rows_of(arg(args, 1)?)?;
            let os: Arc<dyn car_policy::settings::os::Os + Send + Sync> = Arc::new(PolicyOs);
            let (history, counts) = records::progress(&os, &codex, &rows);
            Ok(Value::Array(vec![
                Value::from(history.word()),
                Value::Array(
                    counts
                        .into_iter()
                        .map(|each| each.map_or(Value::Null, Value::Object))
                        .collect(),
                ),
            ]))
        }
        "reading.state" => {
            let paths = paths_of(text(arg(args, 0)?)?);
            let (schema, rows, hidden, paused) = reading::state(&paths).map_err(refused)?;
            Ok(Value::Array(vec![
                Value::from(schema),
                rows_value(rows),
                Value::from(hidden),
                paused.map_or(Value::Null, Value::Bool),
            ]))
        }
        "reading.paused" => {
            let paths = paths_of(text(arg(args, 0)?)?);
            Ok(reading::paused(&paths).map_or(Value::Null, Value::Bool))
        }
        "reading.log_lines" => {
            let paths = paths_of(text(arg(args, 0)?)?);
            Ok(Value::Array(
                reading::log_lines(&paths, &Crt)
                    .into_iter()
                    .map(|(when, line)| Value::Array(vec![Value::Float(when), Value::from(line)]))
                    .collect(),
            ))
        }
        "reading.current_engine" => {
            let view = arg(args, 0)?;
            let lines = lines_of(arg(args, 1)?)?;
            let given = Some(view).filter(|each| !matches!(each, Value::Null));
            let (version, source, capabilities) =
                reading::current_engine(given, &lines).map_err(refused)?;
            Ok(Value::Array(vec![
                Value::from(version),
                Value::from(source),
                capabilities.unwrap_or(Value::Null),
            ]))
        }
        "evidence.by_route" => {
            let rows = rows_of(arg(args, 0)?)?;
            let mut paid = Paid::new();
            for (key, times) in map(arg(args, 1)?)? {
                let times = list(times)?
                    .iter()
                    .map(tagged_float)
                    .collect::<Result<Vec<_>, _>>()?;
                paid.insert(key.as_str().unwrap_or_default().to_owned(), times);
            }
            let reach = reach_of(arg(args, 2)?)?;
            let (kept, routed, unknown) = evidence::by_route(rows, &paid, reach);
            Ok(Value::Array(vec![
                rows_value(kept),
                Value::from(routed),
                Value::from(unknown),
            ]))
        }
        "evidence.place" => {
            let rows = rows_of(arg(args, 0)?)?;
            let timeline = lines_of(arg(args, 1)?)?;
            let current = text(arg(args, 2)?)?;
            let version = text(arg(args, 3)?)?;
            let (placed, elsewhere, unplaced) = evidence::place(&rows, &timeline, current, version);
            Ok(Value::Array(vec![
                rows_value(placed),
                Value::from(elsewhere),
                counts_value(&unplaced),
            ]))
        }
        "evidence.body" => {
            let version = text(arg(args, 0)?)?;
            let rows = rows_of(arg(args, 1)?)?;
            let lines = lines_of(arg(args, 2)?)?;
            let watcher = match arg(args, 3)? {
                Value::Null => None,
                other => Some(other),
            };
            let progress: Vec<Option<Map>> = list(arg(args, 4)?)?
                .iter()
                .map(|each| match each {
                    Value::Null => Ok(None),
                    other => map(other).map(|each| Some(each.clone())),
                })
                .collect::<Result<_, _>>()?;
            evidence::body(version, &rows, &lines, watcher, &progress).map_err(Failure::new)
        }
        "evidence.ledger_reach" => {
            let units = number(arg(args, 0)?)?;
            let oldest = arg(args, 1)?;
            let given = arg(args, 2)?;
            let now = tagged_float(arg(args, 3)?)?;
            let max_age = tagged_float(arg(args, 4)?)?;
            let limit = number(arg(args, 5)?)?;
            let reach = evidence::ledger_reach(units, oldest, given, now, max_age, limit);
            Ok(match reach {
                Reach::All => Value::Null,
                Reach::From(bound) => untag(bound),
            })
        }
        "evidence.canonical_version" => {
            Ok(evidence::canonical_version(arg(args, 0)?).map_or(Value::Null, Value::from))
        }
        _ => Err(Failure::new("UnknownOp")),
    }
}
