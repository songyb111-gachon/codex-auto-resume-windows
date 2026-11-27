//! `control/follow.py` (seat S7.3a): a delivered message followed to the end of its work (v0.6.20, issue #50) - the
//! turn it started, tied by its proof in Codex's history or else by time, and each cut-off of that work and where its
//! recovery stands, from core's state. Read-only, ids, closed words and times only.

use std::cmp::Ordering;
use std::path::Path;
use std::sync::Arc;

use car_machine::domain::{ids, public::public_code};
use car_machine::json::{Map, Str, Value};
use car_machine::pyval;
use car_machine::vocab_gen::domain_states::{TERMINAL, WAITING as WAITING_STATES};

use super::resets::{
    Result, among, codex_home, codex_os, get, is, is_int, refused_here, shown, standing, text, with,
};
use crate::engine::promptqueue::CAPABILITY;
use crate::runtime::Runtime;
use crate::vocabulary::{PromptReason, PromptState, Refusal};

pub const STEPS: usize = 12;
pub const EXACT: &str = "exact";
pub const TIME: &str = "time";
pub const NONE: &str = "none";
pub const NOT_FOUND: &str = "not_found";
pub const AMBIGUOUS: &str = "ambiguous";
pub const NO_RECORD: &str = "no_record";
pub const WAITING: &str = "waiting";
pub const RECOVERING: &str = "recovering";
pub const RECOVERED: &str = "recovered";
pub const ENDED: &str = "ended";
pub const STILL_RUNNING: &str = "still_running";
pub const FINISHED: &str = "finished";
pub const UNKNOWN: &str = "unknown";
pub const STEP_FIELDS: &[&str] = &[
    "interruption_id",
    "turn_id",
    "category",
    "limit_type",
    "detected_at",
    "reset_at",
    "outcome_at",
    "recovery_turn_id",
    "recovery_turn_status",
];
/// `machine.TURN_STATUSES`.
const TURN_STATUSES: &[&str] = &["completed", "failed", "inProgress", "interrupted", "other"];

/// What reads the marker rows of an occurrence's turn: None where the history cannot be read.
pub type Reader<'a> = &'a dyn Fn(&Value, &Value) -> Option<Vec<Value>>;

/// `proofs(record_id)`: its marker, then the client id it went under with none.
pub fn proofs(record_id: &str) -> [String; 2] {
    [
        ids::short_marker(record_id),
        ids::continuation_client_id(record_id),
    ]
}

/// `read_turns(home)`'s reader: the marker rows of the occurrence's turn, for each proof until one is found.
pub fn read_turns(home: &str, thread_id: &Value, record_id: &Value) -> Option<Vec<Value>> {
    let source = car_codex::source::LocalSource::new(codex_os(), home, None).ok()?;
    let thread = match thread_id {
        Value::Str(text) => text.as_str()?.to_owned(),
        _ => return None,
    };
    let record = match record_id {
        Value::Str(text) => text.as_str()?.to_owned(),
        _ => return None,
    };
    for proof in proofs(&record) {
        let found = source.marker_rows(&thread, &proof).ok()?;
        if !found.is_empty() {
            return Some(found.into_iter().map(Value::Object).collect());
        }
    }
    Some(Vec::new())
}

fn stage(state: &Value) -> &'static str {
    if among(state, WAITING_STATES) {
        WAITING
    } else if is(state, "recovered") {
        RECOVERED
    } else if among(state, TERMINAL) {
        ENDED
    } else {
        RECOVERING
    }
}

/// `_turn_of(found)`: (link, turn id, its status, why).
fn turn_of(found: Option<&[Value]>) -> (&'static str, Value, Value, Value) {
    let mut turns: Vec<(Value, Value)> = Vec::new();
    for row in found.unwrap_or_default() {
        let Value::Object(row) = row else { continue };
        let turn = get(row, "turn_id");
        if ids::is_uuid(&turn) && !turns.iter().any(|(seen, _)| pyval::eq(seen, &turn)) {
            turns.push((turn, get(row, "status")));
        }
    }
    match turns.len() {
        1 => {
            let (turn, status) = turns.remove(0);
            (EXACT, turn, status, Value::Null)
        }
        0 => (NONE, Value::Null, Value::Null, text(NOT_FOUND)),
        _ => (NONE, Value::Null, Value::Null, text(AMBIGUOUS)),
    }
}

fn number(value: &Value) -> Option<f64> {
    match value {
        Value::Int(_) | Value::Float(_) | Value::Bool(_) => super::resets::number_of(value),
        _ => None,
    }
}

/// `_by_time(prompt, records)`: (link, turn id, why) by time.
fn by_time(prompt: &Map, records: &[Map]) -> (&'static str, Value, Value) {
    let sent = get(prompt, "sent_at");
    let low = if pyval::truthy(&sent) {
        sent
    } else {
        get(prompt, "due_at")
    };
    let high = get(prompt, "finished_at");
    let (Some(low), Some(high)) = (number(&low), number(&high)) else {
        return (NONE, Value::Null, text(NOT_FOUND));
    };
    let recovery_turns: Vec<Value> = records
        .iter()
        .map(|record| get(record, "recovery_turn_id"))
        .filter(|turn| !matches!(turn, Value::Null))
        .collect();
    let low = low.trunc();
    let found: Vec<&Map> = records
        .iter()
        .filter(|record| {
            matches!(get(record, "parent_interruption_id"), Value::Null)
                && !recovery_turns
                    .iter()
                    .any(|turn| pyval::eq(turn, &get(record, "turn_id")))
                && number(&get(record, "started_at")).is_some_and(|at| low <= at && at <= high)
        })
        .collect();
    match found.len() {
        1 => (TIME, get(found[0], "turn_id"), Value::Null),
        0 => (NONE, Value::Null, text(NOT_FOUND)),
        _ => (NONE, Value::Null, text(AMBIGUOUS)),
    }
}

/// `_cut_off(records, turn_id, parent)`: the earliest detected interruption of `turn_id`, or of `parent`'s.
fn cut_off<'a>(records: &'a [Map], turn_id: &Value, parent: &Value) -> Option<&'a Map> {
    let mut found: Vec<&Map> = records
        .iter()
        .filter(|record| pyval::eq(&get(record, "turn_id"), turn_id))
        .collect();
    if found.is_empty() && !matches!(parent, Value::Null) {
        found = records
            .iter()
            .filter(|record| pyval::eq(&get(record, "parent_interruption_id"), parent))
            .collect();
    }
    found.sort_by(|a, b| {
        let key = |record: &Map| {
            let at = get(record, "detected_at");
            let id = get(record, "interruption_id");
            (
                if pyval::truthy(&at) {
                    at
                } else {
                    super::resets::int(0)
                },
                if pyval::truthy(&id) { id } else { text("") },
            )
        };
        let (a, b) = (key(a), key(b));
        pyval::order(&a.0, &b.0)
            .ok()
            .flatten()
            .unwrap_or(Ordering::Equal)
            .then_with(|| {
                pyval::order(&a.1, &b.1)
                    .ok()
                    .flatten()
                    .unwrap_or(Ordering::Equal)
            })
    });
    found.first().copied()
}

/// `follow(prompt, found, records)`: the follow-through of the delivered message `prompt`. Pure.
pub fn follow(prompt: &Map, found: Option<&[Value]>, records: &[Map]) -> Map {
    let thread = get(prompt, "thread_id");
    let records: Vec<Map> = records
        .iter()
        .filter(|record| pyval::eq(&get(record, "thread_id"), &thread))
        .cloned()
        .collect();
    let mut answer = Map::new();
    for (key, value) in [
        ("link", text(NONE)),
        ("why", Value::Null),
        ("turn_id", Value::Null),
        ("turn_status", Value::Null),
        ("steps", Value::Array(Vec::new())),
        ("end", text(UNKNOWN)),
    ] {
        answer.insert(Str::new(key), value);
    }
    if matches!(get(prompt, "record_id"), Value::Null) {
        answer.insert(Str::new("why"), text(NO_RECORD));
        return answer;
    }
    let (mut link, mut turn, mut status, mut why) = turn_of(found);
    if link == NONE && is(&why, NOT_FOUND) {
        let (by_link, by_turn, by_why) = by_time(prompt, &records);
        (link, turn, why) = (by_link, by_turn, by_why);
        status = Value::Null;
    }
    let shown_status = if among(&status, TURN_STATUSES) {
        status
    } else {
        Value::Null
    };
    answer.insert(Str::new("link"), text(link));
    answer.insert(Str::new("why"), why);
    answer.insert(Str::new("turn_id"), turn.clone());
    answer.insert(Str::new("turn_status"), shown_status.clone());
    if link == NONE {
        return answer;
    }
    let (mut steps, mut current, mut parent, mut seen): (Vec<Value>, Value, Value, Vec<Value>) =
        (Vec::new(), turn, Value::Null, Vec::new());
    while !matches!(current, Value::Null) && steps.len() < STEPS {
        let Some(record) = cut_off(&records, &current, &parent) else {
            break;
        };
        let key = get(record, "interruption_id");
        if seen.iter().any(|each| pyval::eq(each, &key)) {
            break;
        }
        seen.push(key.clone());
        let mut step = shown(record, STEP_FIELDS);
        let code = public_code(&Value::Object(record.clone())).map_or(Value::Null, text);
        step.insert(Str::new("code"), code);
        step.insert(Str::new("stage"), text(stage(&get(record, "state"))));
        steps.push(Value::Object(step));
        current = get(record, "recovery_turn_id");
        parent = key;
        if matches!(current, Value::Null) {
            break;
        }
    }
    let end = match steps.last() {
        Some(Value::Object(last)) => get(last, "stage"),
        _ if link == EXACT && is(&shown_status, "inProgress") => text(STILL_RUNNING),
        _ if link == EXACT && among(&shown_status, &["completed", "failed", "interrupted"]) => {
            text(FINISHED)
        }
        _ => text(UNKNOWN),
    };
    answer.insert(Str::new("steps"), Value::Array(steps));
    answer.insert(Str::new("end"), end);
    answer
}

/// `_records(runtime, thread_id)`: core's interruptions of `thread_id`, every one; none where core's state is not there.
fn records_of(runtime: &Runtime, thread: &Value) -> Result<Vec<Map>> {
    if !Path::new(&runtime.paths.state_dir)
        .join("state.sqlite")
        .is_file()
    {
        return Ok(Vec::new());
    }
    let store = car_store::Store::open(
        Path::new(&runtime.paths.state_dir),
        Arc::new(car_control::host::Probe),
    )
    .map_err(|_| crate::state::Error::state("cannot open core's state"))?;
    let all = store
        .all_records()
        .map_err(|_| crate::state::Error::state("cannot read core's state"))?;
    Ok(all
        .into_iter()
        .filter(|record| pyval::eq(&get(record, "thread_id"), thread))
        .collect())
}

/// `view(runtime, prompt, reader=None)`: advanced-prompt-follow.
pub fn view(runtime: &Runtime, prompt: &Value, reader: Option<Reader<'_>>) -> Result<Value> {
    if !is_int(prompt) {
        return Ok(refused_here(Refusal::InvalidRequest, runtime));
    }
    if !standing(runtime, CAPABILITY) {
        return Ok(refused_here(Refusal::NotOn, runtime));
    }
    let row = match super::resets::call(runtime, "prompt", &[prompt.clone()], &[]) {
        Ok(row) => row,
        Err(_) => return Ok(refused_here(Refusal::StateUnavailable, runtime)),
    };
    let Value::Object(row) = row else {
        return Ok(refused_here(Refusal::InvalidRequest, runtime));
    };
    if !is(&get(&row, "state"), PromptState::Done.as_str())
        || !is(&get(&row, "reason"), PromptReason::Delivered.as_str())
    {
        return Ok(refused_here(Refusal::InvalidRequest, runtime));
    }
    let thread = get(&row, "thread_id");
    let Ok(records) = records_of(runtime, &thread) else {
        return Ok(refused_here(Refusal::StateUnavailable, runtime));
    };
    let home = match reader {
        Some(_) => None,
        None => Some(codex_home(runtime)?),
    };
    let record = get(&row, "record_id");
    let found = if matches!(record, Value::Null) {
        None
    } else {
        match (reader, &home) {
            (Some(reader), _) => reader(&thread, &record),
            (None, Some(home)) => read_turns(home, &thread, &record),
            (None, None) => None,
        }
    };
    let answer = follow(&row, found.as_deref(), &records);
    Ok(with(
        Value::Object(answer),
        vec![
            ("done", Value::Bool(true)),
            ("refusal", Value::Null),
            ("prompt", prompt.clone()),
            ("thread_id", thread),
            ("sent_at", get(&row, "sent_at")),
            ("delivered_at", get(&row, "finished_at")),
            ("due_at", get(&row, "due_at")),
            ("occurrence", get(&row, "sent_count")),
            ("occurrences", get(&row, "occurrences")),
            ("trigger", get(&row, "trigger")),
        ],
    ))
}
