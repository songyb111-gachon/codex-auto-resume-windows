//! The pure half of `autocheck.py` that `arming` reads: how one measurement stands for a Codex, and the grade a capability
//! is told (`settled`, `grade`), over the reach column of `autocheck.CHECKS` (`seam_autocheck_gen.rs`).
//!
//! The rest of `autocheck.py` - the schema reading, the child processes, the record on disk, the tick - is S7.2's; `Edges`
//! (seam.rs) is where `arming` asks for the record (`checked_for`). The integration seat replaces this module with the
//! autocheck port's own `settled` and `grade`; the diffs hold both to the tag.

use std::collections::BTreeMap;

use car_machine::compat::model::parse_version;
use car_machine::json::Value;

use crate::measured::Table;
use crate::seam_autocheck_gen::REACH;
use crate::vocabulary::{AutoResult, CheckGrade, CheckReach, Measurement, Verdict};

/// `HERE, FAILED, GONE, STANDS_IN, UNSETTLED`.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Settled {
    Here,
    Failed,
    Gone,
    StandsIn,
    Unsettled,
}

pub type Results = BTreeMap<Measurement, AutoResult>;

/// `CHECKS.get(measurement, Row()).reach`: what the check can answer of one measurement; none for a row it has not.
pub fn reach(measurement: Measurement) -> CheckReach {
    REACH
        .iter()
        .find(|(each, _)| *each == measurement)
        .map_or(CheckReach::None, |(_, reach)| *reach)
}

/// `settled(measurement, version, table, results)`: how one measurement stands for the Codex `version`, by the design's five
/// rules, the first that holds: failed by a person on any Codex; passed by a person on this one; gone by the automatic check;
/// carried by the automatic check; or unsettled.
pub fn settled(
    measurement: Measurement,
    version: Option<&str>,
    table: &Table,
    results: &Results,
) -> Settled {
    let (verdict, measured_on) = match table.get(&measurement) {
        Some((verdict, engine)) => (Some(*verdict), Some(engine.as_str())),
        None => (None, None),
    };
    if verdict == Some(Verdict::Fail) {
        return Settled::Failed;
    }
    if verdict == Some(Verdict::Pass) && version.is_some() && measured_on == version {
        return Settled::Here;
    }
    match results.get(&measurement) {
        Some(AutoResult::Fail) => return Settled::Gone,
        Some(AutoResult::Pass) => {
            let reach = reach(measurement);
            if reach == CheckReach::Whole
                || (reach == CheckReach::Part && verdict == Some(Verdict::Pass))
            {
                return Settled::StandsIn;
            }
        }
        _ => {}
    }
    Settled::Unsettled
}

/// `_order(version)`: `(tuple(parse_version(version) or ()), version)`.
fn order(version: &str) -> (Vec<i64>, String) {
    let key = parse_version(&Value::from(version))
        .map(|parts| parts.to_vec())
        .unwrap_or_default();
    (key, version.to_owned())
}

/// `grade(measurements, version, table, results)`: `(CheckGrade, the oldest earlier Codex a person measured it on, or None)`
/// for a capability that rests on `measurements`.
pub fn grade(
    measurements: &[Measurement],
    version: Option<&str>,
    table: &Table,
    results: &Results,
) -> (CheckGrade, Option<String>) {
    if measurements.is_empty() {
        return (CheckGrade::None, None);
    }
    // `{measurement: word}` keeps the first place of a measurement named twice.
    let mut each: Vec<(Measurement, Settled)> = Vec::new();
    for measurement in measurements {
        let word = settled(*measurement, version, table, results);
        match each.iter_mut().find(|(seen, _)| seen == measurement) {
            Some(held) => held.1 = word,
            None => each.push((*measurement, word)),
        }
    }
    let has = |wanted: Settled| each.iter().any(|(_, word)| *word == wanted);
    if has(Settled::Failed) {
        if measurements
            .iter()
            .any(|m| results.get(m) == Some(&AutoResult::Fail))
        {
            return (CheckGrade::Failed, None);
        }
        let offered = each
            .iter()
            .any(|(m, word)| *word == Settled::Failed && results.get(m) == Some(&AutoResult::Pass));
        let grade = if offered {
            CheckGrade::FailedStillOffered
        } else {
            CheckGrade::Failed
        };
        return (grade, None);
    }
    if has(Settled::Gone) {
        return (CheckGrade::CheckFailed, None);
    }
    if has(Settled::Unsettled) {
        let offered = each.iter().all(|(m, word)| {
            *word != Settled::Unsettled || results.get(m) == Some(&AutoResult::Pass)
        });
        let grade = if offered {
            CheckGrade::OfferedOnly
        } else {
            CheckGrade::Unmeasured
        };
        return (grade, None);
    }
    if !has(Settled::StandsIn) {
        return (CheckGrade::Measured, None);
    }
    let earlier: Vec<&str> = each
        .iter()
        .filter(|(_, word)| *word == Settled::StandsIn)
        .filter_map(|(m, _)| table.get(m).map(|(_, engine)| engine.as_str()))
        .collect();
    let oldest = earlier
        .into_iter()
        .min_by_key(|version| order(version))
        .map(str::to_owned);
    (CheckGrade::AutoChecked, oldest)
}
