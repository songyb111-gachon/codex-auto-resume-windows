//! A continuation queued for when its conversation is opened (v0.6.15-beta, P16's QUEUE_FOR_OPEN)
//! (`engine/foropen.py`).
//!
//! Core keeps it in Codex's queue only while the plug still says so, and 30 days and an hour at most; opened, it has
//! the delivery window like any queued item, and then is taken back as not delivered on open.

use car_machine::domain::states::may_be_queued;
use car_machine::json::Value;
use car_machine::pyval::{self, Py};
use car_policy::classify::gates::{PASS, PLUGGED, Vector, WAIT, decode_gates, gate};
use car_policy::plug::{Alternative, UnloadedAnswer};

use crate::dispatch::Route;
use crate::py::{self, get, s, text_of, truthy, with};
use crate::{Engine, Row};

/// The longest a continuation is kept in Codex's queue for when its conversation is opened: 30 days and an hour.
pub const DEFERRED_LONGEST: f64 = 30.0 * 86400.0 + 3600.0;

impl Engine {
    /// `_not_for_open(current, route, sender, client, vector)`: True if a QUEUE_FOR_OPEN or TO_SESSION send waits for
    /// its conversation to be opened, as A11 says.
    pub(crate) fn not_for_open(
        &mut self,
        current: &Row,
        route: Option<&Route>,
        channel: bool,
        client: Option<&str>,
        vector: &mut Vector,
    ) -> Py<bool> {
        let open = route.is_some_and(|route| route.is(Alternative::QueueForOpen));
        let session = route.is_some_and(|route| route.is(Alternative::ToSession));
        if !(open || session) || (!channel && client.is_none()) {
            return Ok(false);
        }
        if open && channel && client.is_some() {
            return Ok(false);
        }
        let reason = if open {
            "notLoaded"
        } else {
            "held_by_other_session"
        };
        vector.set("thread_available", gate(WAIT, reason));
        let poll = self.options.state_poll_seconds;
        self.wait(
            current,
            "waiting_for_loaded_thread",
            Some(reason),
            poll,
            vector,
        )?;
        Ok(true)
    }

    /// `for_open(row)`: whether `row` was sent for its conversation to be opened.
    pub fn for_open(row: &Row) -> Py<bool> {
        let queued = may_be_queued(get(row, "state"), get(row, "queue_id"))?
            || text_of(row, "state") == Some("submitting");
        Ok(queued
            && decode_gates(get(row, "gate_eval")).get("thread_available")
                == Some(&(PASS.to_string(), PLUGGED.to_string())))
    }

    /// `_open_reason(row, loaded, now)`: why a continuation queued for opening is taken back now, or None.
    pub fn open_reason(&mut self, row: &Row, loaded: &Value, now: f64) -> Py<Option<String>> {
        let key = s(row, "interruption_id");
        if pyval::is(loaded, "loaded") {
            let first = *self.loaded_since.entry(key).or_insert(now);
            return Ok((now - first >= self.options.delivery_timeout_seconds)
                .then(|| "not_delivered_on_open".to_owned()));
        }
        self.loaded_since.remove(&key);
        let since = py::or(
            get(row, "first_queued_at"),
            py::or(get(row, "submitted_at"), Value::Float(now)),
        );
        if now - py::num(&since)? >= DEFERRED_LONGEST {
            return Ok(Some("window_ended".into()));
        }
        let told = with(
            row,
            vec![("loaded", loaded.clone()), ("queued_since", since)],
        );
        let answer = self.plug.unloaded(&Value::Object(told));
        if !matches!(answer, UnloadedAnswer::Queued(Alternative::QueueForOpen)) {
            return Ok(Some("window_ended".into()));
        }
        // Kept: the one-second watch looks again only once a poll has passed on the engine's clock.
        self.for_open_seen.insert(key, now);
        Ok(None)
    }

    /// `_for_open_rests(row)`: whether the one-second watch leaves a continuation queued for opening alone this pass.
    pub fn for_open_rests(&mut self, row: &Row) -> Py<bool> {
        let Some(seen) = self.for_open_seen.get(&s(row, "interruption_id")).copied() else {
            return Ok(false);
        };
        let age = self.now() - seen;
        if !(0.0..self.options.state_poll_seconds).contains(&age) || !Engine::for_open(row)? {
            return Ok(false);
        }
        let settings = self.store.settings()?;
        Ok(truthy(get(&settings, "enabled"))
            && !self.observing(&settings)
            && !truthy(get(row, "cancel_requested"))
            && self.store.thread_enabled(&s(row, "thread_id"))?)
    }
}
