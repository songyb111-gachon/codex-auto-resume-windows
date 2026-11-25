//! The codex readers' ops: `rd.turns.*`, `rd.lineage.children`, `rd.threads.own`, `rd.conversation.view`,
//! `rd.sessions.*`, `rd.goals.read`, `rd.credits.*`, `rd.alpha`.

use std::collections::BTreeSet;
use std::sync::Arc;

use car_adv::codex::conversation::Conversation;
use car_adv::codex::goals::Goals;
use car_adv::codex::lineage::Lineage;
use car_adv::codex::sessions::Origins;
use car_adv::codex::threads::Threads;
use car_adv::codex::turns::{Failure as ReadFailure, SharedOs, Turns, is_alpha};
use car_adv::codex::credits;
use car_codex::system::PolicyOs;
use car_machine::json::{Int, Map, Value};

use crate::{Context, Failure, Out, arg, text};

fn os() -> SharedOs {
    Arc::new(PolicyOs)
}

fn failed(class: &'static str) -> impl Fn(ReadFailure) -> Failure {
    move |failure| match failure {
        ReadFailure::Unavailable(reason) => Failure::coded(class, &reason),
        ReadFailure::Raised(raised) => Failure::new(raised),
    }
}

fn opt(value: Option<String>) -> Value {
    value.map_or(Value::Null, Value::from)
}

fn int(value: &Value) -> Result<i64, Failure> {
    match value {
        Value::Int(n) => n.as_i64().ok_or_else(crate::bad),
        Value::Float(f) => Ok(f.trunc() as i64),
        _ => Err(crate::bad()),
    }
}

pub fn run(_context: &Context, op: &str, args: &[Value]) -> Out {
    let turns_failed = failed("TurnsUnavailable");
    let home = || text(arg(args, 0));
    match op {
        "rd.alpha" => Ok(Value::Bool(is_alpha(&text(arg(args, 0))?))),
        "rd.turns.latest" => {
            let found = Turns::new(&home()?, os()).latest(arg(args, 1)).map_err(&turns_failed)?;
            Ok(match found {
                None => Value::Null,
                Some(turn) => Value::Array(vec![
                    Value::from(turn.turn_id),
                    Value::from(turn.status),
                    Value::Bool(turn.errored),
                    turn.completed_at.map_or(Value::Null, Value::from),
                    Value::Bool(turn.final_agent),
                    Value::Int(Int::parse(&turn.ordinal.to_string()).ok_or_else(crate::bad)?),
                    Value::Object(turn.kinds.into_iter().map(|(kind, count)| (kind.into(), Value::from(count))).collect()),
                    turn.started_at.unwrap_or(Value::Null),
                ]),
            })
        }
        "rd.turns.turn_code" => Turns::new(&home()?, os()).turn_code(arg(args, 1), arg(args, 2)).map_err(&turns_failed),
        "rd.turns.status" => Ok(opt(Turns::new(&home()?, os()).status(arg(args, 1), arg(args, 2)).map_err(&turns_failed)?)),
        "rd.turns.recent" => Ok(Value::Array(
            Turns::new(&home()?, os())
                .recent(int(arg(args, 1))?)
                .map_err(&turns_failed)?
                .into_iter()
                .map(Value::from)
                .collect(),
        )),
        "rd.turns.running" => Ok(Value::Array(
            Turns::new(&home()?, os())
                .running(arg(args, 1))
                .map_err(&turns_failed)?
                .into_iter()
                .map(Value::from)
                .collect(),
        )),
        "rd.turns.between" => Ok(Value::from(
            Turns::new(&home()?, os())
                .between(arg(args, 1), arg(args, 2), arg(args, 3))
                .map_err(&turns_failed)?,
        )),
        "rd.turns.plan_statuses" => Ok(
            match Turns::new(&home()?, os()).plan_statuses(arg(args, 1)).map_err(&turns_failed)? {
                None => Value::Null,
                Some(found) => Value::Array(found.into_iter().map(Value::from).collect()),
            },
        ),
        "rd.lineage.children" => {
            let reader = Lineage { home: home()?, os: os() };
            Ok(Value::Array(
                reader
                    .children(arg(args, 1))
                    .map_err(&turns_failed)?
                    .into_iter()
                    .map(|child| Value::Array(vec![Value::from(child.thread_id), child.turn_id, child.status, child.category]))
                    .collect(),
            ))
        }
        "rd.threads.own" => {
            let reader = Threads { home: home()?, os: os() };
            let skip: BTreeSet<String> = match arg(args, 2) {
                Value::Array(items) => items.iter().filter_map(|item| text(item).ok()).collect(),
                _ => BTreeSet::new(),
            };
            Ok(Value::Array(
                reader
                    .own(int(arg(args, 1))?, &skip)
                    .map_err(&turns_failed)?
                    .into_iter()
                    .map(|(thread, name)| Value::Array(vec![Value::from(thread), Value::from(name)]))
                    .collect(),
            ))
        }
        "rd.conversation.view" => {
            let reader = Conversation { home: home()?, os: os() };
            Ok(Value::Array(reader.view(arg(args, 1)).map_err(&turns_failed)?))
        }
        "rd.sessions.rollout" => {
            let reader = Origins { home: home()?, os: os() };
            Ok(opt(reader.rollout(arg(args, 1)).map_err(&turns_failed)?))
        }
        "rd.sessions.find" => {
            let reader = Origins { home: home()?, os: os() };
            let (path, how) = reader.find(arg(args, 1), None).map_err(&turns_failed)?;
            Ok(Value::Array(vec![opt(path), Value::from(how)]))
        }
        "rd.sessions.names" => {
            let reader = Origins { home: home()?, os: os() };
            let found = reader.names().map_err(&turns_failed)?;
            Ok(Value::Object(found.into_iter().map(|(id, path)| (id.into(), Value::from(path))).collect::<Map>()))
        }
        "rd.sessions.origin" => {
            let reader = Origins { home: home()?, os: os() };
            let (row, first) = reader.origin(arg(args, 1)).map_err(&turns_failed)?;
            Ok(Value::Array(vec![row.map_or(Value::Null, Value::Object), first.map_or(Value::Null, Value::Object)]))
        }
        "rd.sessions.events_since" => {
            let reader = Origins { home: home()?, os: os() };
            let offset = match arg(args, 2) {
                Value::Null => None,
                other => Some(int(other)?),
            };
            let (kinds, next) = reader.events_since(arg(args, 1), offset).map_err(&turns_failed)?;
            Ok(Value::Array(vec![
                Value::Array(kinds.into_iter().map(Value::from).collect()),
                next.map_or(Value::Null, Value::from),
            ]))
        }
        "rd.sessions.newest_event" => {
            let reader = Origins { home: home()?, os: os() };
            Ok(match reader.newest_event(arg(args, 1)).map_err(&turns_failed)? {
                None => Value::Null,
                Some((kind, payload)) => Value::Array(vec![Value::from(kind), Value::from(payload)]),
            })
        }
        "rd.goals.read" => {
            let goals_failed = failed("GoalsUnavailable");
            let reader = Goals::new(&home()?, os()).map_err(&goals_failed)?;
            Ok(match reader.read(arg(args, 1)).map_err(&goals_failed)? {
                None => Value::Null,
                Some(goal) => Value::Array(vec![
                    Value::from(goal.goal_id),
                    Value::from(goal.status.as_str()),
                    Value::from(goal.updated_at_ms),
                ]),
            })
        }
        "rd.credits.parse" => credits::parse(arg(args, 0)).map_err(Failure::new),
        "rd.credits.details_listed" => Ok(Value::Bool(credits::details_listed(arg(args, 0)))),
        "rd.credits.outcome" => Ok(Value::from(credits::outcome(arg(args, 0)).as_str())),
        "rd.credits.full" => {
            let windows = match arg(args, 0) {
                Value::Array(items) => items.clone(),
                Value::Null => Vec::new(),
                _ => return Err(Failure::new("TypeError")),
            };
            Ok(Value::Array(credits::full(&windows).map_err(Failure::new)?))
        }
        "rd.credits.params" => Ok(Value::Array(vec![credits::detailed(), credits::light()])),
        _ => Err(Failure::new("UnknownOp")),
    }
}
