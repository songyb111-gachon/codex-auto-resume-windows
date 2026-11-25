//! A continuation sent to a conversation another Codex session holds (v0.6.16-beta.4, P16's TO_SESSION)
//! (`engine/tosession.py`).
//!
//! Where `loaded()` says "elsewhere" and the plug answers TO_SESSION at P16, core sends its own words with its marker
//! through its own backend, under the one claim, the thread_available gate passed with the word `session` - and only
//! while the same session, by pid and creation time, still holds it at the re-check under the dispatch lock.

use car_machine::json::Value;
use car_machine::pyval;
use car_policy::classify::gates::{PASS, SESSION, Vector, decode_gates, gate};
use car_policy::plug::{Alternative, UnloadedAnswer};

use crate::dispatch::Route;
use crate::py::{self, get, s, with};
use crate::{Engine, Row};

impl Engine {
    /// `to_session(row)`: whether `row` was sent to a conversation another Codex session held.
    pub fn to_session(row: &Row) -> bool {
        decode_gates(get(row, "gate_eval")).get("thread_available")
            == Some(&(PASS.to_string(), SESSION.to_string()))
    }

    /// `_session(row, loaded, vector)`: P16 for a conversation another Codex session holds - TO_SESSION, with the
    /// holder's identity kept for the re-check under the lock; or None, core's own wait.
    pub(crate) fn session(
        &mut self,
        row: &Row,
        loaded: &Value,
        vector: &mut Vector,
    ) -> Option<Route> {
        let held = self.backend.session_holder();
        if !pyval::is(loaded, "elsewhere")
            || vector.or_unknown("consent").0 != PASS
            || matches!(held, Value::Null)
        {
            return None;
        }
        let told = with(
            row,
            vec![
                ("holder", Value::from("session")),
                ("app", Value::Bool(true)),
            ],
        );
        let answer = self.plug.unloaded(&Value::Object(told));
        if !matches!(answer, UnloadedAnswer::Queued(Alternative::ToSession)) {
            return None;
        }
        self.session_holders.insert(s(row, "thread_id"), held);
        vector.set("thread_available", gate(PASS, SESSION));
        Some(Route::Queued(Alternative::ToSession))
    }

    /// `_session_reason(row, loaded, now)`: why a continuation sent to another session is taken back now, or None.
    pub fn session_reason(&self, row: &Row, loaded: &Value, now: f64) -> Option<String> {
        if pyval::is(loaded, "notLoaded") {
            return Some("session_ended".into());
        }
        let submitted = py::or_number(get(row, "submitted_at"), now).unwrap_or(now);
        if now - submitted < self.options.delivery_timeout_seconds {
            return None;
        }
        Some(if pyval::is(loaded, "loaded") {
            "expired".into()
        } else {
            "session_expired".into()
        })
    }
}
