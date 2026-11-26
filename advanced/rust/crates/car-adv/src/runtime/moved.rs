//! `Runtime.moved` (P14) and its tripwires (`runtime.py`).

use car_machine::json::Value;
use car_policy::classify::gates::{PASS, decode_gates};
use car_policy::plug::Point;

use super::ask::{StrValue, own_record};
use super::{
    KEEP_GOING, NOT_DELIVERED_ON_OPEN, Py, Runtime, SUBMITTING, WITHDRAWN_UNCONFIRMED, caught,
    field, key_of, object,
};
use crate::seam_p7::{OTHER_SESSIONS, QUEUE_FOR_OPEN, SILENT};
use crate::vocabulary::{JournalCode, OffReason, OverrideKind};

/// `RECORD_MOVES`.
const RECORD_MOVES: &[&str] = car_policy::plug::vocab_gen::domain_plug::RECORD_MOVES;

/// `MOVE_CODES`: what each move of a record of the edition's own is counted as, in its capability's own words.
fn move_code(movement: &str) -> Option<&'static str> {
    match movement {
        "sent" => Some("sent"),
        "delivered" => Some("delivered"),
        "unproven" => Some("unknown"),
        "not_started" => Some("not_started"),
        _ => None,
    }
}

impl Runtime {
    /// `moved(record, state)`: P14 - core has moved `record` to `state`.
    pub fn moved(&self, record: &Value, state: &str) -> Py<()> {
        if self.registry.is_empty() {
            return Ok(());
        }
        if own_record(record) && RECORD_MOVES.contains(&state) {
            return self.record_moved(record, state);
        }
        if state == SUBMITTING && object(record).is_some() {
            self.pooled_acted(record)?;
            self.words_sent(record);
        }
        if self.not_delivered_on_open(record, state)?
            || self.not_dispatched_by_session(record, state)
            || self.refused_by_codex()
        {
            self.states(true, &[]);
        }
        if self.arming.moved(record, state) {
            self.states(true, &[]);
        }
        Ok(())
    }

    /// `_words_sent(record)` (v0.6.18): a claim that carried a capability's words committed - it is told so.
    fn words_sent(&self, record: &Value) {
        let texted = self
            .texted
            .borrow_mut()
            .remove(&key_of(record))
            .unwrap_or_default();
        for capability in texted {
            let Some(definition) = self.registry.get(&capability) else {
                continue;
            };
            // Nothing kept on a raise: the lines are told again at the next send.
            let _ = self.call_own(definition, |code| code.words_sent(record));
        }
    }

    /// `_pooled_acted(record)` (v0.6.17): a claim that pooled `record` committed - the capability at P12 acted.
    fn pooled_acted(&self, record: &Value) -> Py<()> {
        let pooled = self
            .pooled
            .borrow_mut()
            .remove(&key_of(record))
            .unwrap_or_default();
        for capability in pooled {
            if let Some(definition) = self.registry.get(&capability) {
                self.once(
                    JournalCode::Acted,
                    definition,
                    Point::Concurrency,
                    Point::Concurrency.as_str(),
                    Some(record),
                )?;
            }
        }
        Ok(())
    }

    /// `_not_delivered_on_open(record, state)`: core took back a continuation queued for opening because Codex did not
    /// run it when the conversation was opened - the capability whose override queued it turns off (or, kept on, notes).
    fn not_delivered_on_open(&self, record: &Value, state: &str) -> Py<bool> {
        if state != WITHDRAWN_UNCONFIRMED
            || object(record).is_none()
            || field(record, "withdraw_reason").as_str_value() != Some(NOT_DELIVERED_ON_OPEN)
        {
            return Ok(false);
        }
        let Some(found) = caught(self.state.override_of(
            field(record, "interruption_id"),
            &Value::Str(QUEUE_FOR_OPEN.into()),
        ))?
        else {
            return Ok(false);
        };
        let Some(found) = found else {
            return Ok(false);
        };
        if found.get("kind").and_then(|kind| kind.as_str_value())
            != Some(OverrideKind::QueueForOpen.as_str())
        {
            return Ok(false);
        }
        Ok(self
            .arming
            .trip(QUEUE_FOR_OPEN, OffReason::NotDeliveredOnOpen)
            .unwrap_or(false))
    }

    /// `_not_dispatched_by_session(record, state)`: a continuation another Codex session held did not take it within
    /// the delivery window - other_sessions turns off (or, kept on, notes).
    fn not_dispatched_by_session(&self, record: &Value, state: &str) -> bool {
        if state != WITHDRAWN_UNCONFIRMED
            || object(record).is_none()
            || field(record, "withdraw_reason").as_str_value() != Some(NOT_DELIVERED_ON_OPEN)
        {
            return false;
        }
        let gates = decode_gates(field(record, "gate_eval"));
        let Some(gate) = gates.get("thread_available") else {
            return false;
        };
        if gate.0 != PASS || gate.1 != car_policy::classify::vocab_gen::domain_gates::SESSION {
            return false;
        }
        self.arming
            .trip(OTHER_SESSIONS, OffReason::NotDispatchedBySession)
            .unwrap_or(false)
    }

    /// `_refused_by_codex()`: a route met Codex refusing a turn with no input - silent_continuation turns off, once.
    fn refused_by_codex(&self) -> bool {
        if !crate::codex::headless::EMPTY_REFUSED.load(std::sync::atomic::Ordering::SeqCst)
            || self.refused_tripped.get().is_some()
            || self.registry.get(SILENT).is_none()
        {
            return false;
        }
        self.refused_tripped.set(Some(self.now()));
        self.arming
            .trip(SILENT, OffReason::RefusedByCodex)
            .unwrap_or(false)
    }

    /// `_record_moved(record, move)`: P14 for a record of the edition's own - its rule and record as core says they
    /// are now, counted in its capability's words, and (unproven a day after it was sent) its capability turned off.
    fn record_moved(&self, record: &Value, movement: &str) -> Py<()> {
        let at = || Value::Float(self.now());
        let word = Value::Str(movement.into());
        let id = field(record, "record_id");
        let moved = (|| -> Result<Option<crate::state::sql::Row>, crate::state::Error> {
            let mut moved = self.state.record_moved(
                id,
                &word,
                field(record, "gate"),
                field(record, "reason"),
                &at(),
                field(record, "queue_id"),
            )?;
            if moved.is_none() {
                moved =
                    self.state
                        .continuation_moved(id, &word, &at(), field(record, "queue_id"))?;
            }
            if moved.is_none() {
                moved = self.state.prompt_moved(
                    id,
                    &word,
                    &at(),
                    field(record, "queue_id"),
                    field(record, "gate"),
                    field(record, "reason"),
                )?;
            }
            if moved.is_none() {
                moved = self
                    .state
                    .chat_moved(id, &word, field(record, "reason"), &at())?;
            }
            Ok(moved)
        })();
        // Repaired from the next P2 where the state refuses.
        let Some(Some(moved)) = caught(moved)? else {
            return Ok(());
        };
        let capability = moved.get("capability").cloned().unwrap_or(Value::Null);
        if movement == "sent" && capability.as_str_value() == Some(KEEP_GOING) {
            // Keep going counts a continuation as used at its send's start (engine/keepgoing.py).
            caught(
                self.state
                    .keep_going_used(field(record, "thread_id"), &at()),
            )?;
        }
        if let Some(code) = move_code(movement) {
            caught(
                self.state
                    .counted(&capability, &Value::Str(code.into()), &at()),
            )?;
        }
        if car_machine::pyval::truthy(moved.get("trip").unwrap_or(&Value::Null))
            && let Some(capability) = capability.as_str_value()
        {
            let _ = self.arming.trip(capability, OffReason::SubmissionUnknown);
            self.states(true, &[]);
        }
        Ok(())
    }
}
