//! car-codex's readers (S3.2), two ways in:
//!
//! * `leaves.batch` cases named `codex.*`, `eligibility.*`, `rollout.*`, `workspace.*` and `paths.*` ([`case`]): the
//!   pure readers and the file readers, one function at a time, as `tests/rustdiff/diffs_codex_*.py` writes them;
//! * `codex.script` ([`script`]): a list of cases, each a Codex home (the databases and rollout files a test wrote,
//!   read where they are: the readers never write) and a list of `LocalSource` calls named as the Python's methods,
//!   answered with the same shape the reference's runner writes.
//!
//! Nothing here decides anything: every answer is car-codex's own function's.

use std::collections::BTreeSet;
use std::path::Path;
use std::sync::{Arc, Mutex};

use car_codex::chains::{self, ChainMemory};
use car_codex::errors::Error;
use car_codex::source::{LocalSource, Why};
use car_codex::{eligibility, labels, paths, payload, rollout, usage, values, workspace};
use car_machine::json::{Map, Str, Value};
use car_machine::pyval::Py;
use car_policy::settings::os::Os;

use crate::leaves::Args;
use crate::policy::PlatformOs;

fn object(pairs: Vec<(&str, Value)>) -> Value {
    let mut map = Map::new();
    for (key, value) in pairs {
        map.insert(Str::from(key), value);
    }
    Value::Object(map)
}

fn set_of(value: &Value) -> BTreeSet<String> {
    match value {
        Value::Array(items) => items
            .iter()
            .filter_map(|each| match each {
                Value::Str(text) => text.as_str().map(str::to_owned),
                _ => None,
            })
            .collect(),
        _ => BTreeSet::new(),
    }
}

fn optional_set(value: &Value) -> Option<BTreeSet<String>> {
    match value {
        Value::Null => None,
        other => Some(set_of(other)),
    }
}

fn text_of(value: &Value) -> Option<&str> {
    match value {
        Value::Str(text) => text.as_str(),
        _ => None,
    }
}

fn texts(value: &Value) -> Vec<String> {
    match value {
        Value::Array(items) => items
            .iter()
            .filter_map(|each| text_of(each).map(str::to_owned))
            .collect(),
        _ => Vec::new(),
    }
}

fn map_of(value: Option<Map>) -> Value {
    value.map_or(Value::Null, Value::Object)
}

fn text_or_null(value: Option<String>) -> Value {
    value.map_or(Value::Null, |each| Value::from(each.as_str()))
}

fn failed(error: &Error) -> &'static str {
    error.class()
}

/// A `(reason, kind)` pair as the reference writes its tuple.
fn why(found: &Option<Why>) -> Value {
    match found {
        None => Value::Null,
        Some(each) => Value::Array(vec![
            Value::from(each.reason),
            each.kind.as_deref().map_or(Value::Null, Value::from),
        ]),
    }
}

fn cell_of(value: &Value) -> car_codex::sql::Cell {
    use car_codex::sql::Cell;
    match value {
        Value::Int(number) => number.as_i64().map_or(Cell::Null, Cell::Int),
        Value::Float(number) => Cell::Real(*number),
        Value::Str(text) => text
            .as_str()
            .map_or(Cell::Null, |word| Cell::Text(word.to_owned())),
        _ => Cell::Null,
    }
}

/// One case of `leaves.batch`: `Some(answer)` where the name is one of this seat's.
pub fn case(name: &str, args: &Args) -> Option<Py<Value>> {
    let os = PlatformOs;
    let kinds_of = |at: usize| set_of(args.get(at));
    Some(match name {
        "codex.detect" => payload::detect(args.get(0)).map(map_of),
        "codex.normalize" => values::normalize(args.get(0)).map(map_of),
        "codex.admissible" => payload::admissible(args.get(0)).map(map_of),
        "codex.error_shape" => match args.get(0) {
            Value::Object(row) => Ok(values::error_shape(row)),
            _ => Err("AttributeError"),
        },
        "codex.judge" => match args.get(0) {
            Value::Object(row) => {
                payload::judge(row, &kinds_of(1), args.flag(2), args.flag(3)).map(map_of)
            }
            _ => Err("TypeError"),
        },
        "codex.later_turn" => match args.get(0) {
            Value::Object(row) => payload::later_turn(row).map(Value::Object),
            _ => Err("TypeError"),
        },
        "codex.marker_row" => match (args.get(0), args.text(1)) {
            (Value::Object(row), Ok(marker)) => payload::marker_row(row, marker).map(map_of),
            _ => Err("TypeError"),
        },
        "codex.item_is_ours" => args
            .text(1)
            .map(|proof| Value::Bool(payload::item_is_ours(args.get(0), proof))),
        "codex.queue_has_marker" => args
            .text(1)
            .map(|marker| Value::Bool(payload::queue_has_marker(args.get(0), marker))),
        "codex.choose_reset" => payload::choose_reset(args.get(0), args.get(1)).map(Value::Object),
        "codex.parse_usage" => usage::parse_usage(args.get(0)).map(Value::Object),
        "codex.label" => {
            Ok(labels::label(args.get(0)).map_or(Value::Null, |each| Value::from(each.as_str())))
        }
        "codex.taken_thread_source" => {
            values::taken_thread_source(args.get(0), &kinds_of(1), args.flag(2)).map(Value::Bool)
        }
        "codex.turn_status" => {
            values::turn_status(args.get(0)).map(|each| each.map_or(Value::Null, Value::from))
        }
        "codex.epoch" => values::epoch(args.get(0)).map(Value::Bool),
        "codex.json" => Ok(values::json_of(args.get(0)).unwrap_or(Value::Null)),
        "codex.printable" => match (args.int(0), args.int(1)) {
            (Ok(start), Ok(stop)) => Ok(Value::from(
                (start..stop)
                    .map(|point| {
                        if labels::is_printable(u32::try_from(point).unwrap_or(u32::MAX)) {
                            '1'
                        } else {
                            '0'
                        }
                    })
                    .collect::<String>()
                    .as_str(),
            )),
            _ => Err("TypeError"),
        },
        "eligibility.row_problem" => {
            let row = |name: &str| match args.get(0) {
                Value::Object(map) => cell_of(map.get(name).unwrap_or(&Value::Null)),
                _ => car_codex::sql::Cell::Null,
            };
            let (source, archived, thread_source, history_mode) = (
                row("source"),
                row("archived"),
                row("thread_source"),
                row("history_mode"),
            );
            eligibility::row_problem(
                &eligibility::ThreadRow {
                    source: &source,
                    archived: &archived,
                    thread_source: &thread_source,
                    history_mode: &history_mode,
                },
                &kinds_of(1),
                &set_of(args.get(2)),
                args.flag(3),
            )
            .map(|each| each.map_or(Value::Null, |word| Value::from(word.as_str())))
        }
        "eligibility.originator_taken" => eligibility::originator_taken(
            args.get(0),
            args.get(1),
            &kinds_of(2),
            &set_of(args.get(3)),
        )
        .map(Value::Bool),
        "eligibility.kind_of" => {
            eligibility::kind_of(args.get(0), args.get(1), &kinds_of(2), &set_of(args.get(3)))
                .map(|each| each.map_or(Value::Null, Value::from))
        }
        "eligibility.forked" => Ok(Value::Bool(eligibility::forked(args.get(0)))),
        "eligibility.source_taken" => Ok(Value::Bool(eligibility::source_taken(
            args.get(0),
            &kinds_of(1),
        ))),
        "eligibility.widened_originator" => Ok(Value::Bool(eligibility::widened_originator(
            args.get(0),
            &kinds_of(1),
        ))),
        "eligibility.newer_than_engine" => Ok(Value::Bool(eligibility::newer_than_engine(
            args.get(0),
            args.get(1),
        ))),
        // A folder that is no text is no folder: `_local_folder` answers None before it looks.
        "workspace.head_digest" => Ok(Value::from(
            workspace::head_digest(text_of(args.get(0)).unwrap_or("")).as_str(),
        )),
        "rollout.continued_id" => match (args.get(0), args.get(1)) {
            (Value::Str(thread), Value::Str(file)) => Ok(text_or_null(rollout::continued_id(
                thread.as_str().unwrap_or(""),
                file.as_str().unwrap_or(""),
            ))),
            _ => Ok(Value::Null),
        },
        "rollout.placed" => match args.get(0) {
            Value::Object(row) => Ok(Value::Object(rollout::placed(
                row,
                args.get(1),
                args.int(2).unwrap_or(0) as usize,
            ))),
            _ => Err("TypeError"),
        },
        "rollout.taken" => {
            let rows: Vec<(Option<String>, Option<String>)> = match args.get(1) {
                Value::Array(items) => items
                    .iter()
                    .map(|each| match each {
                        Value::Array(pair) => (
                            pair.first().and_then(text_of).map(str::to_owned),
                            pair.get(1).and_then(text_of).map(str::to_owned),
                        ),
                        _ => (None, None),
                    })
                    .collect(),
                _ => Vec::new(),
            };
            let mut found: Vec<String> = rollout::taken(&texts(args.get(0)), &rows)
                .into_iter()
                .collect();
            found.sort();
            Ok(Value::Array(
                found
                    .iter()
                    .map(|each| Value::from(each.as_str()))
                    .collect(),
            ))
        }
        "rollout.confined" => match args.text(0) {
            // A thread id that is no text is no id: `confined` answers None before it looks at the path.
            Ok(home) => {
                rollout::confined(&os, home, text_of(args.get(1)).unwrap_or(""), args.get(2))
                    .map(text_or_null)
                    .map_err(|error| failed(&error))
            }
            _ => Err("TypeError"),
        },
        "rollout.session_meta" => args.text(0).and_then(|path| {
            rollout::session_meta(path)
                .map(map_of)
                .map_err(|error| failed(&error))
        }),
        "rollout.reset_scan" => args.text(0).and_then(|path| {
            rollout::reset_scan(path, args.get(1), args.text(2).unwrap_or(""), args.get(3))
                .map(Value::Object)
        }),
        "rollout.superseded_in" => args.text(0).map(|path| {
            let limit = match args.get(2) {
                Value::Int(number) => number.as_u64(),
                _ => None,
            };
            Value::from(rollout::superseded_in(
                path,
                args.text(1).unwrap_or(""),
                limit,
            ))
        }),
        "rollout.turn_trigger" => args.text(0).and_then(|path| {
            rollout::turn_trigger(path, text_of(args.get(1)))
                .map(text_or_null)
                .map_err(|error| failed(&error))
        }),
        "paths.newest_generation" => match (args.text(0), args.text(1)) {
            (Ok(home), Ok(kind)) => paths::newest_generation(&os, home, kind)
                .map(text_or_null)
                .map_err(|error| failed(&error)),
            _ => Err("TypeError"),
        },
        "paths.safe_path" => args.text(0).and_then(|path| {
            paths::safe_path(&os, path)
                .map(|each| Value::from(each.as_str()))
                .map_err(|error| failed(&error))
        }),
        _ => return None,
    })
}

// --------------------------------------------------------------------------------------------- the script
fn raised(error: &Error) -> Value {
    object(vec![
        ("raised", Value::from(error.class())),
        (
            "message",
            match error {
                Error::Source(refused) => Value::from(refused.0.as_str()),
                _ => Value::from(""),
            },
        ),
    ])
}

fn arg(args: &[Value], at: usize) -> &Value {
    static NULL: Value = Value::Null;
    args.get(at).unwrap_or(&NULL)
}

fn keyword<'a>(keywords: &'a Map, name: &str) -> Option<&'a Value> {
    keywords.get(name)
}

fn flag(keywords: &Map, name: &str) -> bool {
    matches!(keyword(keywords, name), Some(Value::Bool(true)))
}

fn id_text(value: &Value) -> &str {
    text_of(value).unwrap_or("")
}

/// One call of a `LocalSource` (or of its chain memory), named as the Python's method.
fn run(
    source: &mut LocalSource,
    method: &str,
    args: &[Value],
    keywords: &Map,
) -> Result<Value, Error> {
    let thread = id_text(arg(args, 0));
    let list = |value: &Value| {
        Value::Array(
            texts(value)
                .iter()
                .map(|each| Value::from(each.as_str()))
                .collect(),
        )
    };
    Ok(match method {
        "@plug" => {
            source.session_kinds = set_of(keyword(keywords, "kinds").unwrap_or(&Value::Null));
            source.widened = set_of(keyword(keywords, "widened").unwrap_or(&Value::Null));
            Value::Null
        }
        "resolve" => Value::from(source.resolve(thread)?.as_str()),
        "written" => {
            let found = source.written()?;
            object(vec![
                (
                    "state_written",
                    found.state_written.map_or(Value::Null, Value::from),
                ),
                (
                    "history_written",
                    found.history_written.map_or(Value::Null, Value::from),
                ),
            ])
        }
        "cloud_tasks" => source.cloud_tasks().map_or(Value::Null, Value::from),
        "newer_than_engine" => {
            Value::Bool(source.newer_than_engine(thread, &set_of(arg(args, 1)), arg(args, 2))?)
        }
        "written_by" => text_or_null(source.written_by(thread, &set_of(arg(args, 1)))?),
        "rescan_evidence" => Value::from(source.rescan_evidence(thread, id_text(arg(args, 1)))),
        "_eligibility" => {
            let kinds = keyword(keywords, "kinds").and_then(optional_set);
            let widened = keyword(keywords, "widened").and_then(optional_set);
            let turn = keyword(keywords, "turn_id").and_then(text_of);
            let (path, found) = source.eligibility(
                thread,
                flag(keywords, "strict"),
                kinds.as_ref(),
                turn,
                widened.as_ref(),
            )?;
            Value::Array(vec![text_or_null(path), why(&found)])
        }
        "taken" => {
            let widened = keyword(keywords, "widened").and_then(optional_set);
            Value::Bool(source.taken(thread, &set_of(arg(args, 1)), widened.as_ref())?)
        }
        "_chain" => {
            let turn = keyword(keywords, "turn_id").and_then(text_of);
            let (path, chain, found) = source.chain(thread, flag(keywords, "strict"), turn)?;
            Value::Array(vec![
                text_or_null(path),
                Value::Array(
                    chain
                        .iter()
                        .map(|each| Value::from(each.as_str()))
                        .collect(),
                ),
                why(&found),
            ])
        }
        "_ids" | "turn_chain" => Value::Array(
            source
                .turn_chain(thread)?
                .iter()
                .map(|each| Value::from(each.as_str()))
                .collect(),
        ),
        "_owner" => {
            let turn = keyword(keywords, "turn_id").and_then(text_of);
            let (owner, found, index) = source.owner(text_of(arg(args, 0)), turn)?;
            Value::Array(vec![
                text_or_null(owner),
                why(&found),
                Value::from(index as i64),
            ])
        }
        "owner_of" => text_or_null(source.owner_of(thread)?),
        "_rollout_path" => text_or_null(source.rollout_path(thread)?),
        "latest" => map_of(source.latest(thread)?),
        "latest_failures" => {
            let needs = set_of(keyword(keywords, "needs_you").unwrap_or(&Value::Null));
            let found = source.latest_failures(
                arg(args, 0),
                &needs,
                flag(keywords, "admissible"),
                flag(keywords, "shapes"),
            )?;
            Value::Array(found.into_iter().map(Value::Object).collect())
        }
        "passed_over" => {
            let known = set_of(keyword(keywords, "known").unwrap_or(&Value::Null));
            let newest = match keyword(keywords, "newest") {
                Some(Value::Int(number)) => number.as_i64().map(|each| each.max(0) as usize),
                _ => None,
            };
            let deadline = match keyword(keywords, "deadline_in") {
                Some(Value::Int(number)) => number
                    .as_i64()
                    .map(|each| rollout::monotonic() + each as f64),
                Some(Value::Float(number)) => Some(rollout::monotonic() + number),
                _ => None,
            };
            Value::Object(source.passed_over(
                arg(args, 0),
                arg(args, 1),
                flag(keywords, "every_status"),
                &known,
                newest,
                deadline,
            )?)
        }
        "stalled_turns" => Value::Array(
            source
                .stalled_turns(arg(args, 0), arg(args, 1), arg(args, 2))?
                .into_iter()
                .map(Value::Object)
                .collect(),
        ),
        "identity" => Value::Object(source.identity(thread)?),
        "project_key" => text_or_null(source.project_key(thread)?),
        "task_facts" => Value::Object(source.task_facts(
            thread,
            flag(keywords, "fingerprint"),
            flag(keywords, "tokens"),
        )?),
        "progress" => Value::Object(source.progress(thread, arg(args, 1))?),
        "reset_hint" => Value::Object(source.reset_hint(thread, id_text(arg(args, 1)))?),
        "marker_rows" => Value::Array(
            source
                .marker_rows(thread, id_text(arg(args, 1)))?
                .into_iter()
                .map(Value::Object)
                .collect(),
        ),
        "queued_rows" => Value::Array(
            source
                .queued_rows(thread, id_text(arg(args, 1)))?
                .into_iter()
                .map(Value::Object)
                .collect(),
        ),
        "queue_row" => {
            Value::Object(source.queue_row(thread, id_text(arg(args, 1)), id_text(arg(args, 2)))?)
        }
        "foreign_queued" => Value::from(source.foreign_queued(thread, id_text(arg(args, 1)))?),
        "later_turns" => Value::Array(
            source
                .later_turns(thread, arg(args, 1), id_text(arg(args, 2)))?
                .into_iter()
                .map(Value::Object)
                .collect(),
        ),
        "turn_observation" => Value::Object(source.turn_observation(
            thread,
            id_text(arg(args, 1)),
            id_text(arg(args, 2)),
        )?),
        "turn_progress" => source
            .turn_progress(thread, id_text(arg(args, 1)))?
            .map_or(Value::Null, Value::Bool),
        "turn_item_counts" => map_of(source.turn_item_counts(thread, id_text(arg(args, 1)))?),
        "turn_markers" => list(&Value::Array(
            source
                .turn_markers(thread, id_text(arg(args, 1)), &texts(arg(args, 2)))?
                .iter()
                .map(|each| Value::from(each.as_str()))
                .collect(),
        )),
        "marker_presence" => Value::Object(source.marker_presence(thread, id_text(arg(args, 1)))?),
        "projection" => Value::Object(source.projection(thread)?),
        "activity" => {
            let default_recent = Value::Float(3600.0);
            Value::Object(source.activity(
                &texts(arg(args, 0)),
                keyword(keywords, "now").unwrap_or(&Value::Null),
                keyword(keywords, "recent").unwrap_or(&default_recent),
                keyword(keywords, "booted").unwrap_or(&Value::Null),
            )?)
        }
        _ => return Err(Error::Python("NotPorted")),
    })
}

/// One of the memory's calls (`chains.get`, `chains.extend`), on the memory a case made.
fn run_chains(
    memory: &Arc<Mutex<ChainMemory>>,
    os: &dyn Os,
    home: &str,
    method: &str,
    args: &[Value],
) -> Result<Value, Error> {
    let mut held = memory
        .lock()
        .unwrap_or_else(|poisoned| poisoned.into_inner());
    let thread = id_text(arg(args, 0));
    let found = match method {
        "chains.get" => held.get(os, home, thread)?,
        "chains.extend" => held.extend(os, home, thread, &texts(arg(args, 1)))?,
        _ => return Err(Error::Python("NotPorted")),
    };
    Ok(Value::Array(
        found
            .iter()
            .map(|each| Value::from(each.as_str()))
            .collect(),
    ))
}

/// `codex.script`: every case of `cases`, each answered as `{"open": null | {"raised": ...}, "results": [...]}`.
pub fn script(cases: &Value) -> Value {
    let Value::Array(cases) = cases else {
        return Value::Null;
    };
    let os: Arc<dyn Os + Send + Sync> = Arc::new(PlatformOs);
    let mut answers = Vec::with_capacity(cases.len());
    for each in cases {
        let Value::Object(case) = each else {
            answers.push(Value::Null);
            continue;
        };
        // A fresh process of the reference starts with no listing, no first line and no trigger remembered.
        rollout::forget();
        let home = case.get("home").and_then(text_of).unwrap_or("");
        let memory = match case.get("chains").and_then(text_of) {
            Some(file) => chains::memory(Some(Path::new(file)), true),
            None => Arc::new(Mutex::new(ChainMemory::new(None, true))),
        };
        let opened = LocalSource::new(Arc::clone(&os), home, Some(Arc::clone(&memory)));
        let mut source = match opened {
            Ok(source) => source,
            Err(error) => {
                answers.push(object(vec![
                    ("open", raised(&error)),
                    ("results", Value::Array(Vec::new())),
                ]));
                continue;
            }
        };
        source.session_kinds = set_of(case.get("kinds").unwrap_or(&Value::Null));
        source.widened = set_of(case.get("widened").unwrap_or(&Value::Null));
        let mut results = Vec::new();
        if let Some(Value::Array(operations)) = case.get("ops") {
            for operation in operations {
                let Value::Object(operation) = operation else {
                    results.push(Value::Null);
                    continue;
                };
                let method = operation.get("method").and_then(text_of).unwrap_or("");
                let no_args: Vec<Value> = Vec::new();
                let args = match operation.get("args") {
                    Some(Value::Array(items)) => items,
                    _ => &no_args,
                };
                let no_keywords = Map::new();
                let keywords = match operation.get("kwargs") {
                    Some(Value::Object(map)) => map,
                    _ => &no_keywords,
                };
                let answer = if method.starts_with("chains.") {
                    run_chains(&memory, os.as_ref(), &source.home, method, args)
                } else {
                    run(&mut source, method, args, keywords)
                };
                results.push(match answer {
                    Ok(value) => value,
                    Err(error) => raised(&error),
                });
            }
        }
        answers.push(object(vec![
            ("open", Value::Null),
            ("results", Value::Array(results)),
        ]));
    }
    Value::Array(answers)
}
