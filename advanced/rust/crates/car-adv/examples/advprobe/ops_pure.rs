//! `arming.pure.*`: the pure functions arming decides with, one case each.

use std::collections::BTreeMap;

use car_adv::arming::{self, Standing};
use car_adv::jsonx::{int, maybe_text, text, texts};
use car_adv::measured::Table;
use car_adv::policy::Policy;
use car_adv::seam::ArmRow;
use car_adv::autocheck::{self, Results, Settled};
use car_adv::vocabulary::{
    Actor, ArmingState, ArmingWarning, AutoResult, ClosedWord, Measurement, OffReason, Verdict,
    parse,
};
use car_machine::json::Value;
use car_policy::plug::Point;

use crate::defs;
use crate::ops_registry::table_of;
use crate::util::{Failure, Out, arg, bad, flag, list, map, number, text as as_text};

fn word_opt<W: ClosedWord>(value: &Value) -> Result<Option<W>, Failure> {
    match value {
        Value::Null => Ok(None),
        other => parse::<W>(as_text(other)?).map(Some).ok_or_else(bad),
    }
}

pub fn row_of(value: &Value) -> Result<Option<ArmRow>, Failure> {
    if matches!(value, Value::Null) {
        return Ok(None);
    }
    let found = map(value)?;
    let get = |name: &str| found.get(name).ok_or_else(bad);
    Ok(Some(ArmRow {
        state: parse::<ArmingState>(as_text(get("state")?)?).ok_or_else(bad)?,
        since: match get("since")? {
            Value::Null => None,
            other => Some(crate::util::float(other)?),
        },
        actor: word_opt::<Actor>(get("actor")?)?,
        reason: word_opt::<OffReason>(get("reason")?)?,
        statement_revision: match get("statement_revision")? {
            Value::Null => None,
            other => Some(number(other)?),
        },
        engine_version: match get("engine_version")? {
            Value::Null => None,
            other => Some(as_text(other)?.to_owned()),
        },
        warnings: list(get("warnings")?)?
            .iter()
            .map(|each| parse::<ArmingWarning>(as_text(each)?).ok_or_else(bad))
            .collect::<Result<_, _>>()?,
        keep_on: flag(get("keep_on")?)?,
        send_again: flag(get("send_again")?)?,
    }))
}

fn results_of(value: &Value) -> Result<Results, Failure> {
    let mut found = Results::new();
    for row in list(value)? {
        let row = list(row)?;
        let measurement: Measurement = parse(as_text(arg(row, 0)?)?).ok_or_else(bad)?;
        let result: AutoResult = parse(as_text(arg(row, 1)?)?).ok_or_else(bad)?;
        found.insert(measurement, result);
    }
    Ok(found)
}

fn policy_of(value: &Value) -> Result<Policy, Failure> {
    crate::ops_words::policy_of(value)
}

fn standing_json(found: Standing) -> Value {
    Value::Array(vec![
        text(found.state.as_str()),
        maybe_text(found.change.map(|each| each.as_str())),
        maybe_text(found.held.map(|each| each.as_str())),
        maybe_text(found.notice.map(|each| each.as_str())),
    ])
}

fn warnings_json(found: &[ArmingWarning]) -> Value {
    texts(&found.iter().map(|each| each.as_str()).collect::<Vec<_>>())
}

pub fn run(op: &str, args: &[Value]) -> Out {
    match op {
        "arming.pure.engine_version" => {
            Ok(maybe_text(arming::engine_version(arg(args, 0)?).as_deref()))
        }
        "arming.pure.compat_warning" => {
            let definition = defs::from_json(arg(args, 1)?)?;
            Ok(maybe_text(
                arming::compat_warning(arg(args, 0)?, &definition).map(|each| each.as_str()),
            ))
        }
        "arming.pure.warnings_for" => {
            let definition = defs::from_json(arg(args, 0)?)?;
            let table: Table = table_of(arg(args, 2)?)?;
            Ok(warnings_json(&arming::warnings_for(
                &definition,
                arg(args, 1)?,
                &table,
                flag(arg(args, 3)?)?,
                &results_of(arg(args, 4)?)?,
            )))
        }
        "arming.pure.standing" => {
            let definition = defs::from_json(arg(args, 0)?)?;
            let row = row_of(arg(args, 1)?)?;
            Ok(standing_json(arming::standing(
                &definition,
                row.as_ref(),
                &policy_of(arg(args, 2)?)?,
                arg(args, 3)?,
                &table_of(arg(args, 4)?)?,
                &results_of(arg(args, 5)?)?,
            )))
        }
        "arming.pure.departs" => {
            let definition = defs::from_json(arg(args, 0)?)?;
            Ok(texts(&arming::departs(
                &definition,
                row_of(arg(args, 1)?)?.as_ref(),
            )))
        }
        "arming.pure.offers_send_again" => {
            let definition = defs::from_json(arg(args, 0)?)?;
            let sending: Vec<Point> = list(arg(args, 1)?)?
                .iter()
                .map(|each| Point::parse(as_text(each)?).ok_or_else(bad))
                .collect::<Result<_, _>>()?;
            Ok(Value::Bool(arming::offers_send_again(
                &definition,
                &sending,
            )))
        }
        "arming.pure.kept_words" => Ok(texts(&arming::kept_words(
            flag(arg(args, 0)?)?,
            flag(arg(args, 1)?)?,
        ))),
        "arming.pure.held_word" => {
            let definition = defs::from_json(arg(args, 0)?)?;
            let row = row_of(arg(args, 1)?)?;
            let state: ArmingState = parse(as_text(arg(args, 2)?)?).ok_or_else(bad)?;
            Ok(maybe_text(
                arming::held_word(
                    &definition,
                    row.as_ref(),
                    state,
                    word_opt::<OffReason>(arg(args, 3)?)?,
                    word_opt::<ArmingWarning>(arg(args, 4)?)?,
                    &policy_of(arg(args, 5)?)?,
                )
                .as_deref(),
            ))
        }
        "arming.pure.rises" => {
            let notice: OffReason = parse(as_text(arg(args, 1)?)?).ok_or_else(bad)?;
            Ok(Value::Bool(arming::rises(
                word_opt::<OffReason>(arg(args, 0)?)?,
                notice,
            )))
        }
        "arming.pure.confirmed" => Ok(match arming::confirmed_of(arg(args, 0)?) {
            None => Value::Null,
            Some(found) => {
                let mut words: Vec<&str> = found.iter().map(|each| each.as_str()).collect();
                words.sort_unstable();
                texts(&words)
            }
        }),
        "arming.pure.claimed_at" => {
            Ok(arming::claimed_at(arg(args, 0)?).map_or(Value::Null, Value::from))
        }
        "arming.pure.carried" => {
            let mut spent: Vec<(String, Vec<f64>)> = Vec::new();
            for (key, times) in map(arg(args, 0)?)? {
                let times = list(times)?
                    .iter()
                    .map(crate::util::float)
                    .collect::<Result<_, _>>()?;
                spent.push((key.as_str().ok_or_else(bad)?.to_owned(), times));
            }
            let claimed = match arg(args, 2)? {
                Value::Null => None,
                other => Some(crate::util::float(other)?),
            };
            Ok(Value::Bool(arming::carried(
                &spent,
                as_text(arg(args, 1)?)?,
                claimed,
            )))
        }
        "arming.pure.settled" => {
            let measurement: Measurement = parse(as_text(arg(args, 0)?)?).ok_or_else(bad)?;
            let version = match arg(args, 1)? {
                Value::Null => None,
                other => Some(as_text(other)?),
            };
            let found = autocheck::settled(
                measurement,
                version,
                &table_of(arg(args, 2)?)?,
                &results_of(arg(args, 3)?)?,
            );
            Ok(text(match found {
                Settled::Here => "here",
                Settled::Failed => "failed",
                Settled::Gone => "gone",
                Settled::StandsIn => "stands_in",
                Settled::Unsettled => "unsettled",
            }))
        }
        "arming.pure.grade" => {
            let measurements: Vec<Measurement> = list(arg(args, 0)?)?
                .iter()
                .map(|each| parse(as_text(each)?).ok_or_else(bad))
                .collect::<Result<_, _>>()?;
            let version = match arg(args, 1)? {
                Value::Null => None,
                other => Some(as_text(other)?),
            };
            let (word, earlier) = autocheck::grade(
                &measurements,
                version,
                &table_of(arg(args, 2)?)?,
                &results_of(arg(args, 3)?)?,
            );
            Ok(Value::Array(vec![
                text(word.as_str()),
                maybe_text(earlier.as_deref()),
            ]))
        }
        "arming.pure.constants" => Ok(Value::Array(vec![
            int(arming::SURFACES.len() as i64),
            Value::from(arming::SAME_CLAIM),
        ])),
        _ => Err(Failure::new("UnknownOp")),
    }
}

#[allow(dead_code)]
fn unused(_: BTreeMap<String, String>, _: Verdict) {}
