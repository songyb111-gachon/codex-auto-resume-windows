//! Whether Codex is in a state worth reading: the app, the usage, the projection (`engine/freshness.py`).
//!
//! A projection that has fallen behind its rollout is the one that matters most - reading a turn from a history that
//! has not caught up is reading a past that is already wrong. v0.6.11 adds a PC that has just woken and one Windows
//! reports without internet (both off by default); v0.6.19 (issue #50) a person's Retry now and Rescan, served at the
//! next look or said not checked.

use car_machine::domain::usage::windows_of;
use car_machine::json::{Map, Value};
use car_machine::pyval::{self, Py};
use car_machine::vocab_gen::domain_public::REASONS;
use car_machine::vocab_gen::domain_states::{WAITING, WATCHED};
use car_policy::classify::failures::USAGE_LIMIT;
use car_policy::classify::gates::{
    PASS, UNKNOWN, Vector, WAIT, gate, gate_schedule, usage_read_stopped,
};
use car_policy::classify::power;

use crate::py::{self, field, get, row, s, text, text_of, truthy};
use crate::{Engine, Row};

/// v0.6.19: a person's request to read usage is served at the watcher's next look, or not at all: one older than
/// this at that look is not read, and the row says so.
pub const USAGE_CHECK_LONGEST: f64 = 120.0;

impl Engine {
    /// `engine._usage_cache = None`: the next look reads usage again (what a scenario does between two readings).
    pub fn clear_usage_cache(&mut self) {
        self.usage_cache = None;
    }

    /// `engine._usage_cache`: the time and the reading this engine reuses, if any.
    pub fn usage_cached(&self) -> Option<(f64, Value)> {
        self.usage_cache.clone()
    }

    /// `_no_app_reason()`: why a record waits where the backend's last look paired no app (#58's follow-up).
    pub fn no_app_reason(&self) -> String {
        if !pyval::is(&self.backend.app_look(), "unmatched") {
            return "desktop_app_unavailable".into();
        }
        let named = self.backend.app_unmatched_reason();
        match text(&named) {
            Some(named)
                if REASONS.contains(&named) && named.starts_with("app_server_unmatched") =>
            {
                named.to_owned()
            }
            _ => "app_server_unmatched".into(),
        }
    }

    /// `usage()`: the backend's usage reading, reused for 30 seconds (C9). v0.6.18: a clock set back ends a reading.
    pub fn usage(&mut self) -> Py<Value> {
        let now = self.now();
        let fresh = self
            .usage_cache
            .as_ref()
            .is_some_and(|(at, _)| (0.0..=30.0).contains(&(now - at)));
        if !fresh {
            let read = self.backend.usage()?;
            self.usage_cache = Some((now, read));
        }
        Ok(self
            .usage_cache
            .as_ref()
            .map_or(Value::Null, |(_, read)| read.clone()))
    }

    /// `_schedule_gate(row, vector, now, quiet_until)`: the schedule gate for `row`, and the record it is for.
    pub(crate) fn schedule_gate(
        &mut self,
        row: Row,
        vector: &Vector,
        now: f64,
        quiet_until: Option<f64>,
    ) -> Py<((String, String), Row)> {
        let found = gate_schedule(&row, now, quiet_until, false, false);
        let ahead = py::or_number(get(&row, "reset_at"), 0.0).unwrap_or(0.0) > now;
        if !(found.1 == "waiting_reset" || (found.1 == "not_due" && ahead)) {
            return Ok((found, row));
        }
        match self.asked_usage(row.clone(), vector, now, quiet_until)? {
            None => Ok((gate(WAIT, "not_due"), row)),
            Some(found) => Ok((gate_schedule(&found, now, quiet_until, false, false), found)),
        }
    }

    /// `_asked_usage(row, vector, now, quiet_until)`: a person's Retry now asked for usage to be read for `row`.
    fn asked_usage(
        &mut self,
        row: Row,
        vector: &Vector,
        now: f64,
        quiet_until: Option<f64>,
    ) -> Py<Option<Row>> {
        let key = s(&row, "interruption_id");
        let asked = match self.store.usage_checks_asked(now) {
            Ok(asked) => get(&asked, &key).clone(),
            Err(_) => Value::Null,
        };
        if matches!(asked, Value::Null) {
            return Ok(Some(row));
        }
        if let Some(why) = self.not_served(&row, now, quiet_until, Some(vector), &asked)? {
            self.store.usage_not_checked(&key, now, &why)?;
            return Ok(Some(row));
        }
        let source = self.store.usage_check_taken(&key)?;
        // A reading of the last 30 seconds answers it (C9): a Rescan's requests, one per recovery, are one reading.
        let available = match self.usage() {
            Ok(read) => field(&read, "available").cloned().unwrap_or(Value::Null),
            Err(_) => Value::Null,
        };
        let read = match available {
            Value::Bool(true) => "usage_available",
            Value::Bool(false) => "usage_unavailable",
            _ => "usage_unknown",
        };
        self.store.usage_checked(&key, now, read, &source)
    }

    /// `_not_served(row, now, quiet_until, vector, asked)`: why a person's request to read usage cannot be served.
    pub(crate) fn not_served(
        &self,
        row: &Row,
        now: f64,
        quiet_until: Option<f64>,
        vector: Option<&Vector>,
        asked: &Value,
    ) -> Py<Option<String>> {
        let settings = self.store.settings()?;
        let stopped = usage_read_stopped(
            truthy(get(&settings, "enabled")) && !self.managed.disable_auto_resume,
            self.store.thread_enabled(&s(row, "thread_id"))?,
            self.observing(&settings),
            quiet_until.is_some(),
        );
        if let Some(stopped) = stopped {
            return Ok(Some(stopped.into()));
        }
        let consent = vector.map(|vector| vector.or_unknown("consent"));
        if consent.is_none_or(|consent| consent.0 != PASS)
            || text_of(row, "category") != Some(USAGE_LIMIT)
            || gate_schedule(row, now, None, true, false).0 != PASS
        {
            return Ok(Some("held".into()));
        }
        if self.offline() {
            return Ok(Some("offline".into()));
        }
        let fresh = py::arithmetic(asked)
            .is_some_and(|asked| (0.0..=USAGE_CHECK_LONGEST).contains(&(now - asked)));
        if !fresh {
            return Ok(Some("busy".into()));
        }
        Ok(None)
    }

    /// `_usage_checks_left(before)`: at the end of a tick, each request standing when it began that its looks did not
    /// serve, taken and said not checked, with why.
    pub(crate) fn usage_checks_left(&mut self, before: &Map) {
        if before.is_empty() {
            return;
        }
        let _ = (|| -> Py<()> {
            let now = self.now();
            let standing = self.store.usage_checks_asked(now)?;
            let keys: Vec<String> = before
                .keys()
                .filter(|key| standing.contains_key(*key))
                .filter_map(|key| key.as_str().map(str::to_owned))
                .collect();
            for key in keys {
                let Some(row) = self.store.get(&key)? else {
                    self.store.usage_check_taken(&key)?;
                    continue;
                };
                let quiet = self.quiet_until(now)?;
                let why = self
                    .not_served(&row, now, quiet, None, &Value::Null)?
                    .unwrap_or_else(|| "held".into());
                self.store.usage_not_checked(&key, now, &why)?;
            }
            Ok(())
        })();
    }

    /// `last_usage()`: the last usage reading this engine made that had windows, as (time, windows).
    pub fn last_usage(&self) -> Option<(f64, Vec<Value>)> {
        let (at, read) = self.usage_cache.as_ref()?;
        windows_of(read)
            .ok()
            .flatten()
            .map(|windows| (*at, windows))
    }

    /// `loaded(thread_id)`: the loaded state of one thread, re-read at most every few seconds.
    pub fn loaded(&mut self, thread_id: &str) -> Py<Value> {
        let now = self.now();
        if let Some((at, value)) = self.loaded_cache.get(thread_id)
            && (0.0..self.options.loaded_check_seconds).contains(&(now - at))
        {
            return Ok(value.clone());
        }
        let app = self.backend.app_identity()?;
        let value = if truthy(&app) {
            self.backend.loaded(thread_id, &app)?
        } else {
            Value::from("unknown")
        };
        if self.loaded_cache.len() > 512 {
            self.loaded_cache.clear();
        }
        self.loaded_cache
            .insert(thread_id.to_owned(), (now, value.clone()));
        Ok(value)
    }

    /// `_identity_waits(row, vector, fresh, poll)`: the identity gate, once the projection table is there.
    pub(crate) fn identity_waits(
        &mut self,
        row: &Row,
        vector: &mut Vector,
        fresh: bool,
        poll: f64,
    ) -> Py<bool> {
        vector.set(
            "identity",
            if fresh {
                gate(PASS, "ok")
            } else {
                gate(UNKNOWN, "projection_stale")
            },
        );
        if !fresh {
            self.wait(
                row,
                "waiting_for_loaded_thread",
                Some("projection_stale"),
                poll,
                vector,
            )?;
            return Ok(true);
        }
        if self.newer_than_engine(row) {
            vector.set("identity", gate(WAIT, "version_newer_than_engine"));
            self.wait(
                row,
                "waiting_for_loaded_thread",
                Some("version_newer_than_engine"),
                poll,
                vector,
            )?;
            return Ok(true);
        }
        Ok(false)
    }

    /// `_projection_now(thread_id)`: exactly current right now - True, False, or None when the projection table itself
    /// is missing - and what was seen recorded, so a lag is measured from when it began.
    pub fn projection_now(&mut self, thread_id: &str) -> Option<bool> {
        let found = self
            .source
            .projection(thread_id)
            .unwrap_or_else(|_| row(vec![("table", Value::Null), ("fresh", Value::Null)]));
        if matches!(get(&found, "table"), Value::Bool(false)) {
            return None;
        }
        let now = self.now();
        if matches!(get(&found, "fresh"), Value::Bool(true)) {
            self.stale_since.remove(thread_id);
            return Some(true);
        }
        if self.stale_since.len() > 512 {
            self.stale_since.clear();
            self.stale_seen.clear();
            self.stale_cleared_at = now; // a lag seen before is no longer known (engine/resend.rs)
        }
        self.stale_since.entry(thread_id.to_owned()).or_insert(now);
        self.stale_seen.insert(thread_id.to_owned(), now);
        Some(false)
    }

    /// `projection_fresh(thread_id)`: current enough to decide from; a short lag passes.
    pub fn projection_fresh(&mut self, thread_id: &str) -> Option<bool> {
        let current = self.projection_now(thread_id);
        if current != Some(false) {
            return current;
        }
        let since = self.stale_since.get(thread_id).copied().unwrap_or(0.0);
        Some(self.now() - since < self.options.projection_grace_seconds)
    }

    /// `fresh_throughout(thread_id, since)`: exactly current now, and not seen behind at any point since `since`.
    pub fn fresh_throughout(&mut self, thread_id: &str, since: f64) -> bool {
        if self.projection_now(thread_id) != Some(true) {
            return false;
        }
        self.stale_seen
            .get(thread_id)
            .copied()
            .unwrap_or(f64::NEG_INFINITY)
            < since
    }

    /// `activity(threads)`: what may still run in Codex, for the power action (v0.6.12).
    pub fn activity(&self, threads: &[String]) -> Map {
        let booted = match self.store.watcher_status() {
            Ok(Some(status)) => get(&status, "booted_at").clone(),
            _ => Value::Null,
        };
        match self.source.activity(threads, self.now(), &booted) {
            Ok(found) => row(vec![
                ("history", get(&found, "history").clone()),
                ("running", get(&found, "running").clone()),
                ("queued", get(&found, "queued").clone()),
            ]),
            Err(_) => row(vec![
                ("history", Value::Null),
                ("running", Value::Null),
                ("queued", Value::Null),
            ]),
        }
    }

    /// `observe_projections()`: look at the history of every thread with something pending.
    pub fn observe_projections(&mut self) -> Py<()> {
        let mut states: Vec<&str> = WAITING.to_vec();
        states.extend_from_slice(WATCHED);
        let threads: std::collections::BTreeSet<String> = self
            .records(&states)?
            .iter()
            .map(|row| s(row, "thread_id"))
            .collect();
        for thread in threads {
            self.projection_now(&thread);
        }
        Ok(())
    }

    // ------------------------------------------------------------ sleep and the network (v0.6.11)
    /// `offline()`: whether Windows reports no internet, asked only while Wait for an internet connection is on.
    pub fn offline(&self) -> bool {
        if !power::waits_for_network(&self.values()) {
            return false;
        }
        matches!((self.connectivity)(), Ok(Value::Bool(false)))
    }

    /// `_offline(row, vector, now)`: just before usage would be read for a due record, True if it waits offline.
    pub(crate) fn offline_wait(&mut self, row: &Row, vector: &mut Vector, now: f64) -> Py<bool> {
        if !self.offline() {
            return Ok(false);
        }
        vector.set("usage", gate(WAIT, power::OFFLINE));
        if !self.parked(row, vector)? {
            self.store
                .record_gates(&s(row, "interruption_id"), vector, now)?;
            let poll = self.options.state_poll_seconds;
            self.transition(
                row,
                "waiting_for_usage",
                Some(power::OFFLINE),
                Some(poll),
                None,
                py::row(vec![("usage_probe_at", Value::Null)]),
            )?;
        }
        Ok(true)
    }

    /// `after_sleep(since, slept)`: this PC has woken (v0.6.11). Returns how many were held.
    pub fn after_sleep(&mut self, since: f64, slept: f64) -> Py<i64> {
        self.usage_cache = None;
        self.loaded_cache.clear();
        let Some(threshold) = power::sleep_threshold(&self.values()) else {
            return Ok(0);
        };
        if slept == 0.0 || slept < threshold as f64 {
            return Ok(0);
        }
        let now = self.now();
        let mut due = Vec::new();
        for row in self.records(WAITING)? {
            let whole = Value::Object(row.clone());
            if power::fell_due(&whole, &Value::Float(since), &Value::Float(now))? {
                due.push(s(&row, "interruption_id"));
            }
        }
        let held = if due.is_empty() {
            0
        } else {
            self.store.hold_waiting(&due, power::HOLD, now)?
        };
        if held != 0 {
            self.log(None, "held_after_sleep", Value::from(held));
            let payload = row(vec![
                ("slept", Value::Float(slept)),
                ("count", Value::from(held)),
            ]);
            if (self.notify_sink)("after_sleep", &payload).is_err() {
                self.log(None, "notification_failed", Value::from("after_sleep"));
            }
        }
        Ok(held)
    }
}
