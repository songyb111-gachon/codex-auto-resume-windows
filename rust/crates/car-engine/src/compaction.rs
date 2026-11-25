//! A full context window's record, and the compaction turns after it (v0.6.16-beta.4) (`engine/compaction.py`).
//!
//! A compaction turn is Codex's own work, not the person's, so for that record alone it supersedes nothing (A17): a
//! later turn whose items are a contextCompaction and only reasoning beside it leaves the failure the one to continue.

use car_machine::json::{Map, Value};
use car_machine::pyval::{self, Py};

use crate::py::{get, s, text_of};
use crate::{Engine, Row};

/// The kind of record a compaction turn supersedes nothing of: a full context window, taken up (P17).
pub const COMPACTED: &str = "terminal_invalid";

impl Engine {
    /// `compacted_since(row, latest)`: whether every turn after a full context window's failure is a compaction alone.
    pub fn compacted_since(&mut self, row: &Row, latest: &Map) -> Py<bool> {
        if text_of(row, "category") != Some(COMPACTED) {
            return Ok(false);
        }
        let latest_ordinal = match get(latest, "ordinal") {
            found if car_policy::classify::value::truthy(found) => found.clone(),
            _ => Value::from(0),
        };
        if pyval::less_or_equal(&latest_ordinal, get(row, "ordinal"))? {
            return Ok(false);
        }
        let proof = self.proof(row);
        let Ok(turns) = self
            .source
            .later_turns(&s(row, "thread_id"), get(row, "ordinal"), &proof)
        else {
            return Ok(false);
        };
        Ok(!turns.is_empty()
            && turns
                .iter()
                .all(|turn| text_of(turn, "kind") == Some("foreign") && self.compaction(row, turn)))
    }

    /// `compaction(row, turn)`: whether a later `turn` of a full context window's record is a compaction alone.
    pub fn compaction(&self, row: &Row, turn: &Map) -> bool {
        if text_of(row, "category") != Some(COMPACTED)
            || matches!(get(turn, "turn_id"), Value::Null)
        {
            return false;
        }
        let proof = self.proof(row);
        match self.source.turn_observation(
            &s(row, "thread_id"),
            text_of(turn, "turn_id").unwrap_or_default(),
            &proof,
        ) {
            Ok(seen) => matches!(get(&seen, "compaction_only"), Value::Bool(true)),
            Err(_) => false,
        }
    }

    /// `foreign(row, turn)`: whether a later `turn` is someone else's work over `row` (A17).
    pub fn foreign(&self, row: &Row, turn: &Map) -> bool {
        text_of(turn, "kind") == Some("foreign") && !self.compaction(row, turn)
    }
}
