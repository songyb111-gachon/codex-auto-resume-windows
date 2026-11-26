//! `rescan.py`: Rescan and reconcile (v0.6.16, issue #39) - every waiting recovery looked at again, on a person's
//! word, by the watcher's own rules and nothing copied from them.
//!
//! * RETIRED, only on proof that a person's newer work came after its failure;
//! * RECHECKED, where the history is exactly current and the record is still its conversation's latest failure;
//! * UNRESOLVED, for everything else, with why.
//!
//! `proofs`, `persons` and `judge` are here, over [`RescanEngine`]: the engine's own calls the reference makes of
//! `engine` and `engine.source` (car-engine's and car-codex's, each diffed on its own). `judge_for` - an engine of each
//! record's own Codex home, with no backend and no store - is joined by the integration through car-control's
//! `Host::rescan_judge`.

use car_machine::domain::ids;
use car_machine::json::{Map, Value};

use crate::fail::{Failed, Res};

pub const SECONDS: f64 = 20.0;
pub const STALE: &str = "projection_stale";
pub const CHANGED_LATEST: &str = "latest_turn_changed";
pub const UNREADABLE: &str = "unreadable";
pub const TOO_LARGE: &str = "too_large";
pub const MARKER_FREE: &str = "marker_free";
pub const HOME_UNKNOWN: &str = "home_unknown";
pub const OUT_OF_TIME: &str = "out_of_time";
pub const ROLLED_BACK: &str = "rolled_back";
pub const UNPROJECTED: &str = "message_not_projected";
pub const LATER_TURN: &str = "later_turn_exists";
pub const RETIRED: &str = car_store::actions::RETIRED;
pub const RECHECKED: &str = car_store::actions::RECHECKED;
pub const UNRESOLVED: &str = "unresolved";

/// What `judge` asks of the engine of the record's home (`engine` and `engine.source`).
pub trait RescanEngine {
    /// `engine.proof(row)`.
    fn proof(&mut self, row: &Map) -> Res<Value>;
    /// `source.turn_observation(thread, turn_id, proof)`.
    fn turn_observation(&mut self, thread: &Value, turn_id: &Value, proof: &Value) -> Res<Value>;
    /// `source.later_turns(thread, ordinal, proof)`.
    fn later_turns(&mut self, thread: &Value, ordinal: &Value, proof: &Value) -> Res<Value>;
    /// `engine.persons_turns(thread, turns)`.
    fn persons_turns(&mut self, thread: &Value, turns: &Value) -> Res<Vec<Value>>;
    /// `engine.foreign(row, turn)`.
    fn foreign(&mut self, row: &Map, turn: &Value) -> Res<bool>;
    /// `source.turn_markers(thread, turn_id, ours)`.
    fn turn_markers(&mut self, thread: &Value, turn_id: &Value, ours: &[String]) -> Res<bool>;
    /// `engine.clock()`.
    fn clock(&mut self) -> f64;
    /// `engine.fresh_throughout(thread, now)`.
    fn fresh_throughout(&mut self, thread: &Value, now: f64) -> Res<bool>;
    /// `engine.valid_interruption(row)`.
    fn valid_interruption(&mut self, row: &Map) -> Res<bool>;
    /// `engine.source.rescan_evidence(thread, turn_id)`: one of rollout's words.
    fn rescan_evidence(&mut self, thread: &Value, turn_id: &Value) -> Res<Value>;
}

fn get<'a>(map: &'a Map, key: &str) -> &'a Value {
    static NULL: Value = Value::Null;
    map.get(key).unwrap_or(&NULL)
}

/// `proofs(kin)`: (every proof a continuation of this product's may carry in the conversation, sorted; whether one
/// went with no marker).
pub fn proofs(kin: &[Map]) -> (Vec<String>, bool) {
    let mut found: Vec<String> = Vec::new();
    let mut free = false;
    for row in kin {
        let key = car_machine::pytext::py_str(get(row, "interruption_id"));
        found.extend(ids::record_markers(&key));
        let marker = get(row, "marker");
        if car_machine::pyval::truthy(marker) {
            found.push(car_machine::pytext::py_str(marker));
        }
        let client = get(row, "recovery_client_id");
        if let Value::Str(client) = client
            && client.as_str() == Some(ids::continuation_client_id(&key).as_str())
        {
            found.push(crate::fail::lossy(client));
            free = true;
        }
    }
    let mut kept: Vec<String> = found
        .into_iter()
        .filter(|proof| ids::is_delivery_proof(&Value::from(proof.as_str())))
        .collect();
    kept.sort();
    kept.dedup();
    (kept, free)
}

/// `persons(engine, row, ours)`: the turns after the record's exact failed turn that a person started, and whether
/// one such turn's user message is not in the history yet.
pub fn persons(engine: &mut dyn RescanEngine, row: &Map, ours: &[String]) -> Res<(Vec<Value>, bool)> {
    let key = |name: &str| row.get(name).cloned().ok_or_else(|| Failed::new("KeyError", name));
    let thread = key("thread_id")?;
    let proof = engine.proof(row)?;
    let seen = engine.turn_observation(&thread, &key("turn_id")?, &proof)?;
    let Value::Object(seen) = seen else {
        return Err(Failed::new("AttributeError", "get"));
    };
    let ordinal = key("ordinal")?;
    if !car_machine::pyval::truthy(get(&seen, "found")) || !car_machine::pyval::eq(get(&seen, "ordinal"), &ordinal) {
        return Ok((Vec::new(), false));
    }
    let later = engine.later_turns(&thread, &ordinal, &proof)?;
    let (mut found, mut unprojected) = (Vec::new(), false);
    for turn in engine.persons_turns(&thread, &later)? {
        let Value::Object(fields) = &turn else {
            return Err(Failed::new("TypeError", "turn"));
        };
        let turn_id = fields
            .get("turn_id")
            .cloned()
            .ok_or_else(|| Failed::new("KeyError", "turn_id"))?;
        if matches!(turn_id, Value::Null)
            || !car_machine::pyval::is(get(fields, "reason"), LATER_TURN)
            || !engine.foreign(row, &turn)?
        {
            continue;
        }
        if engine.turn_markers(&thread, &turn_id, ours)? {
            continue;
        }
        let observed = engine.turn_observation(&thread, &turn_id, &proof)?;
        let Value::Object(observed) = observed else {
            return Err(Failed::new("AttributeError", "get"));
        };
        // `observed.get("branded_user_messages", 1)`.
        let branded = observed
            .get("branded_user_messages")
            .cloned()
            .unwrap_or(Value::from(1));
        if car_machine::pyval::truthy(&branded) {
            continue;
        }
        if !car_machine::pyval::truthy(get(&observed, "foreign_user_messages")) {
            unprojected = true;
            continue;
        }
        found.push(turn);
    }
    Ok((found, unprojected))
}

/// `judge(engine, row, kin, deadline)`: (outcome, reason) for one waiting record. What it raises is what the
/// reference lets out of it: the record's own `thread_id` missing, and rollout's word unhashable (a dict lookup).
pub fn judge(
    engine: &mut dyn RescanEngine,
    row: &Map,
    kin: &[Map],
    deadline: Option<f64>,
    monotonic: f64,
) -> Res<(&'static str, Option<String>)> {
    judged(engine, row, kin, deadline, monotonic)
}

fn judged(
    engine: &mut dyn RescanEngine,
    row: &Map,
    kin: &[Map],
    deadline: Option<f64>,
    monotonic: f64,
) -> Res<(&'static str, Option<String>)> {
    if deadline.is_some_and(|deadline| monotonic > deadline) {
        return Ok((UNRESOLVED, Some(OUT_OF_TIME.into())));
    }
    let thread = row
        .get("thread_id")
        .cloned()
        .ok_or_else(|| Failed::new("KeyError", "thread_id"))?;
    let (ours, free) = proofs(kin);
    let (found, unprojected) = match crate::fail::guarded(|| persons(engine, row, &ours)) {
        Ok(found) => found,
        Err(_) => return Ok((UNRESOLVED, Some(UNREADABLE.into()))),
    };
    if !found.is_empty() {
        return Ok((RETIRED, Some(LATER_TURN.into())));
    }
    if unprojected {
        return Ok((UNRESOLVED, Some(UNPROJECTED.into())));
    }
    let now = engine.clock();
    let current = crate::fail::guarded(|| engine.fresh_throughout(&thread, now)).unwrap_or(false);
    if current {
        return Ok(match crate::fail::guarded(|| engine.valid_interruption(row)) {
            Ok(true) => (RECHECKED, None),
            Ok(false) => (UNRESOLVED, Some(CHANGED_LATEST.into())),
            Err(_) => (UNRESOLVED, Some(UNREADABLE.into())),
        });
    }
    if free {
        return Ok((UNRESOLVED, Some(MARKER_FREE.into())));
    }
    let found = crate::fail::guarded(|| engine.rescan_evidence(&thread, get(row, "turn_id")))
        .unwrap_or_else(|_| Value::from(car_codex::rollout::UNREADABLE));
    if car_machine::pyval::is(&found, car_codex::rollout::LATER_MESSAGE) {
        return Ok((RETIRED, Some(LATER_TURN.into())));
    }
    if matches!(found, Value::Array(_) | Value::Object(_)) {
        return Err(Failed::new("TypeError", "unhashable type"));
    }
    let word = car_machine::pyval::text(&found).unwrap_or_default();
    let reason = match word {
        w if w == car_codex::rollout::TOO_LARGE => TOO_LARGE,
        w if w == car_codex::rollout::UNREADABLE => UNREADABLE,
        w if w == car_codex::rollout::ROLLED_BACK => ROLLED_BACK,
        _ => STALE,
    };
    Ok((UNRESOLVED, Some(reason.into())))
}
