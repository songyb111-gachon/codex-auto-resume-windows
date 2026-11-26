//! Turning what Codex recorded into records this product owns (`engine/detect.py`).
//!
//! Detection registers a failure once, under an id derived from the failure itself, so the same interruption seen
//! twice is the same record - and a record whose turn is no longer the thread's latest is superseded rather than
//! recovered. v0.6.14: the edition's plug is asked at P17 about a failure core never recovers alone (engine/relaxed.rs).

use std::collections::BTreeSet;

use car_codex::payload::{admissible as admissible_failure, detect};
use car_machine::domain::{ids, skips, states};
use car_machine::json::{Map, Str, Value};
use car_machine::pytext::py_str;
use car_machine::pyval::{self, Py};
use car_machine::vocab_gen::domain_skips::{CATEGORY_OFF, CONVERSATION_OFF, NOT_RECOVERED};
use car_machine::vocab_gen::domain_states::TERMINAL;
use car_policy::classify::failures::{ADMISSIBLE, USAGE_LIMIT};
use car_policy::classify::{guards, ladder, needsyou};
use car_policy::plug::{Alternative, Answer, Point, paced_as};

use crate::compaction::COMPACTED;
use crate::options::limits_of;
use crate::py::{self, get, row, s, text, text_of, truthy};
use crate::relaxed::UNADMITTED_SECONDS;
use crate::seam::Register;
use crate::{Engine, Row};

/// v0.6.16-beta.3 (issue #27): how far before the look-back window failed turns are still read, to say once that each
/// came before it (A16) - the longest look-back Settings allow.
pub const PASSED_OVER_SECONDS: f64 = 7.0 * 86400.0;
/// The most (turn, reason) pairs and explained turns kept, the oldest let go first; and the most skip lines one check
/// writes - the rest are counted in one line.
pub const SKIPS_KEPT: usize = 20000;
pub const SKIPS_AT_ONCE: usize = 20;

/// `(reason, kind word)` of domain/skips.py.
pub type Why = (String, Value);

/// A turn id as a key of what was said.
fn turn_key(value: &Value) -> String {
    text(value).map_or_else(|| py_str(value), str::to_owned)
}

impl Engine {
    /// `waiting_state(row)`: the wait a record returns to when it goes back to waiting now.
    pub fn waiting_state(&self, row: &Row) -> Py<String> {
        states::waiting_state(&Value::Object(row.clone()), &Value::Float(self.now()))
            .map(str::to_owned)
    }

    /// `_keyed(found)`: a failure as this engine's home knows it (v0.6.15-beta).
    pub fn keyed(&self, found: Option<Map>) -> Py<Option<Map>> {
        let Some(mut found) = found else {
            return Ok(None);
        };
        if !self.home_key.is_empty() {
            let key = ids::interruption_id(
                get(&found, "thread_id"),
                get(&found, "turn_id"),
                get(&found, "completed_at"),
                get(&found, "ordinal"),
                &Value::from(self.home_key.as_str()),
            )?;
            found.insert(Str::from("interruption_id"), Value::from(key));
        }
        Ok(Some(found))
    }

    /// `valid_interruption(row)`: whether the record is still its conversation's latest failure.
    pub fn valid_interruption(&mut self, row: &Row) -> Py<bool> {
        let Some(latest) = self.source.latest(&s(row, "thread_id"))? else {
            return Ok(false);
        };
        if latest.is_empty() {
            return Ok(false);
        }
        if self.compacted_since(row, &latest)? {
            // v0.6.16-beta.4: still the one (engine/compaction.rs).
            return Ok(true);
        }
        let whole = Value::Object(latest);
        let found = if text_of(row, "category").is_some_and(|c| ADMISSIBLE.contains(&c)) {
            admissible_failure(&whole)?
        } else {
            detect(&whole)?
        };
        let found = self.keyed(found)?;
        Ok(found.is_some_and(|found| {
            py::eq(get(&found, "interruption_id"), get(row, "interruption_id"))
        }))
    }

    /// `supersede_reason(row)`: why this interruption is no longer the one to recover.
    pub fn supersede_reason(&mut self, row: &Row) -> (String, String) {
        let progress = self
            .source
            .progress(&s(row, "thread_id"), get(row, "ordinal"))
            .unwrap_or_default();
        if truthy(get(&progress, "later_turn")) && !self.only_wrap_ups_after(row) {
            return ("superseded_by_user".into(), "later_turn_exists".into());
        }
        ("superseded".into(), "latest_turn_changed".into())
    }

    /// `_only_wrap_ups_after(row)`: whether every turn after this record's is one a wrap-up of this product's started.
    fn only_wrap_ups_after(&mut self, row: &Row) -> bool {
        let thread = s(row, "thread_id");
        if self
            .wrap_up_markers()
            .get(&thread)
            .is_none_or(BTreeSet::is_empty)
        {
            return false;
        }
        let proof = self.proof(row);
        let Ok(later) = self
            .source
            .later_turns(&thread, get(row, "ordinal"), &proof)
        else {
            return false;
        };
        !later.is_empty() && self.persons_turns(&thread, later).is_empty()
    }

    /// `detection_since(settings)`: where the look-back window opens (A16).
    pub fn detection_since(&self, settings: &Row) -> Py<f64> {
        let armed = py::num(get(settings, "armed_at"))?;
        Ok(0.0_f64.max(armed - self.options.detection_lookback_seconds))
    }

    /// `not_taken_up(record)`: why a failure the history brought is still not taken up, or None.
    pub fn not_taken_up(&self, record: &Map) -> Py<Option<Why>> {
        if !self.store.thread_enabled(&s(record, "thread_id"))? {
            return Ok(Some((CONVERSATION_OFF.into(), Value::Null)));
        }
        let category = get(record, "category");
        if !self.recovers(text(category).unwrap_or_default()) {
            return Ok(Some((
                CATEGORY_OFF.into(),
                Value::from(skips::kind(category)),
            )));
        }
        Ok(None)
    }

    /// `_skip(thread_id, turn_id, reason, kind)`: one line for a failed turn not taken up, once per turn and reason.
    pub(crate) fn skip(&mut self, thread_id: &str, turn_id: &Value, reason: &str, kind: &Value) {
        if self
            .skips_told
            .keep((turn_key(turn_id), reason.to_owned()), SKIPS_KEPT)
        {
            let detail = Value::Array(vec![turn_id.clone(), Value::from(reason), kind.clone()]);
            self.log(Some(thread_id), "not_taken_up", detail);
        }
    }

    /// `_say_passed_over(since, asking)`: why each failed turn the history did not bring was passed over, once per
    /// turn; and how many failed turns the check saw, when that number changes. Never costs the tick.
    fn say_passed_over(&mut self, since: f64, asking: bool) {
        let before = if self.passed_since != Some(since) {
            0.0_f64.max(since - PASSED_OVER_SECONDS)
        } else {
            since
        };
        self.passed_since = Some(since);
        let known: BTreeSet<String> = self.passed_known.keys().cloned().collect();
        let Ok(read) = self.source.passed_over(since, before, &known) else {
            return;
        };
        let mut said: Vec<Map> = Vec::new();
        if let Value::Array(passed) = get(&read, "passed") {
            for entry in passed {
                let Value::Object(entry) = entry else {
                    continue;
                };
                let reason = get(entry, "reason");
                if pyval::is(reason, NOT_RECOVERED)
                    && asking
                    && text_of(entry, "category")
                        .is_some_and(|c| ADMISSIBLE.contains(&c) && c != COMPACTED)
                {
                    continue;
                }
                if self
                    .passed_known
                    .keep(turn_key(get(entry, "turn_id")), SKIPS_KEPT)
                    && !matches!(reason, Value::Null)
                {
                    said.push(entry.clone());
                }
            }
        }
        // The newest first, SKIPS_AT_ONCE of them, and how many more in one line.
        let at = |entry: &Map| py::or_number(get(entry, "completed_at"), 0.0).unwrap_or(0.0);
        said.sort_by(|a, b| {
            at(b)
                .partial_cmp(&at(a))
                .unwrap_or(std::cmp::Ordering::Equal)
        });
        for entry in said.iter().take(SKIPS_AT_ONCE) {
            let reason = py_str(get(entry, "reason"));
            self.skip(
                &s(entry, "thread_id"),
                get(entry, "turn_id"),
                &reason,
                get(entry, "kind"),
            );
        }
        for entry in said.iter().skip(SKIPS_AT_ONCE) {
            let reason = py_str(get(entry, "reason"));
            self.skips_told
                .keep((turn_key(get(entry, "turn_id")), reason), SKIPS_KEPT);
        }
        if said.len() > SKIPS_AT_ONCE {
            let more = (said.len() - SKIPS_AT_ONCE).to_string();
            self.log(None, "not_taken_up_more", Value::from(more));
        }
        let seen = get(&read, "seen").clone();
        if self
            .seen_failed
            .as_ref()
            .is_none_or(|old| !py::eq(old, &seen))
        {
            self.seen_failed = Some(seen.clone());
            self.log(None, "failed_turns_seen", Value::from(py_str(&seen)));
        }
    }

    // --------------------------------------------------------------- collect
    /// `_owner(thread_id, turn_id)`: which of our records put its continuation into this turn, if any.
    fn owner(&mut self, thread_id: &str, turn_id: &str) -> Py<Option<String>> {
        let candidates: Vec<Row> = self
            .claimed(thread_id)?
            .into_iter()
            .filter(|row| matches!(get(row, "recovery_turn_id"), Value::Null))
            .collect();
        if candidates.is_empty() {
            return Ok(None);
        }
        let proofs: Vec<String> = candidates.iter().map(|row| self.proof(row)).collect();
        let Ok(present) = self.source.turn_markers(thread_id, turn_id, &proofs) else {
            return Ok(None);
        };
        let present: BTreeSet<String> = present.into_iter().collect();
        Ok(candidates
            .iter()
            .find(|row| present.contains(&self.proof(row)))
            .map(|row| s(row, "interruption_id")))
    }

    /// `_legacy_carry(detection)`: the v0.5 no-progress carry, for a predecessor recorded before chains existed.
    fn legacy_carry(&mut self, detection: &Map) -> Py<Value> {
        let thread = s(detection, "thread_id");
        let previous: Vec<Row> = self
            .claimed(&thread)?
            .into_iter()
            .filter(|row| {
                text_of(row, "state") == Some("resumed")
                    && !py::eq(
                        get(row, "interruption_id"),
                        get(detection, "interruption_id"),
                    )
            })
            .collect();
        let Some(mut last) = previous.first() else {
            return Ok(Value::Null);
        };
        for row in &previous[1..] {
            if pyval::greater(get(row, "ordinal"), get(last, "ordinal"))? {
                last = row;
            }
        }
        let Ok(progress) = self.source.progress(&thread, get(last, "ordinal")) else {
            return Ok(Value::Null); // unreadable progress is not evidence of failure
        };
        if truthy(get(&progress, "assistant_reply")) || truthy(get(&progress, "later_completed")) {
            return Ok(Value::Null); // something happened; the chain starts over
        }
        py::plus_one(get(last, "no_progress_count"))
    }

    /// `collect()`: register every failure Codex's history brings that this product recovers.
    pub fn collect(&mut self) -> Py<()> {
        let settings = self.store.settings()?;
        if !truthy(get(&settings, "enabled")) {
            return Ok(());
        }
        let since = self.detection_since(&settings)?;
        let values = self.values();
        // v0.6.11: the same read also brings the failures a needs-you notice is raised for, only while one is on.
        let kinds = needsyou::kinds(&values);
        // v0.6.14: and, while the edition's plug wants P17, the failures it may take up and every error's shape.
        let asking = self.plug.wants(Point::Admission)
            && !self.observing(&settings)
            && !self.managed.disable_auto_resume;
        let mut found = match self.source.latest_failures(since, &kinds, asking, asking) {
            Ok(found) => found,
            // v0.6.26 final: a fresh home - its state holds no conversation, and Codex makes its history with the first
            // one it saves - has nothing to detect yet: a detection that read nothing, not one that could not read.
            Err("HistoryNotYet") => return Ok(()),
            Err(error) => return Err(error),
        };
        for raw in found.iter_mut() {
            let shape = raw.shift_remove("shape").unwrap_or(Value::Null);
            let admissible = raw.shift_remove("admissible").unwrap_or(Value::Bool(false));
            let whole = Value::Object(raw.clone());
            let mut record = self.keyed(detect(&whole)?)?;
            let admissible = record.is_none() && truthy(&admissible);
            if admissible {
                record = self.keyed(admissible_failure(&whole)?)?;
            }
            let Some(record) = record else { continue };
            self.collect_one(&record, &shape, admissible, asking)?;
        }
        // v0.6.16-beta.3: and why every other failed turn of the read was passed over (issue #27).
        self.say_passed_over(since, asking);
        // A failure being recovered needs no "needs you" notice (engine/notices.rs).
        self.tell_needs_you(&found, since);
        Ok(())
    }

    fn collect_one(
        &mut self,
        record: &Map,
        shape: &Value,
        admissible: bool,
        asking: bool,
    ) -> Py<()> {
        let thread = s(record, "thread_id");
        let key = s(record, "interruption_id");
        let why = self.not_taken_up(record)?;
        if let Some((reason, kind)) = &why
            && reason == CONVERSATION_OFF
        {
            self.skip(&thread, get(record, "turn_id"), reason, kind);
            return Ok(());
        }
        if self.store.get(&key)?.is_some() {
            return Ok(());
        }
        let category = s(record, "category");
        if let Some((reason, kind)) = why {
            // Logged once per interruption: the user switched this off deliberately.
            if !self.declined.contains(&key) {
                if self.declined.len() > 512 {
                    self.declined.clear();
                }
                self.declined.insert(key.clone());
                self.log(
                    Some(&thread),
                    "category_recovery_disabled",
                    Value::from(category.as_str()),
                );
            }
            self.skip(&thread, get(record, "turn_id"), &reason, &kind);
            return Ok(());
        }
        let now = self.now();
        if admissible {
            let completed = py::num(get(record, "completed_at"))?;
            let asked = self.unadmitted.get(&key).copied().unwrap_or(-1e18);
            if completed < now - ladder::ADMISSION_MAX_AGE as f64
                || now - asked < UNADMITTED_SECONDS
            {
                return Ok(()); // too old to take up, or put to the plug a moment ago
            }
        }
        let usage = category == USAGE_LIMIT;
        let turn = s(record, "turn_id");
        let hint = if usage {
            self.source.reset_hint(&thread, &turn)?
        } else {
            row(vec![
                ("reset_at", Value::Null),
                ("limit_type", Value::from(category.as_str())),
                ("uncertain", Value::Bool(false)),
            ])
        };
        // store.register accepts only these exact detection fields.
        let detection = row(vec![
            ("thread_id", get(record, "thread_id").clone()),
            ("turn_id", get(record, "turn_id").clone()),
            ("completed_at", get(record, "completed_at").clone()),
            ("started_at", get(record, "started_at").clone()),
            ("ordinal", get(record, "ordinal").clone()),
            ("interruption_id", get(record, "interruption_id").clone()),
            ("reset_at", get(&hint, "reset_at").clone()),
            ("limit_type", get(&hint, "limit_type").clone()),
            ("uncertain", Value::Bool(truthy(get(&hint, "uncertain")))),
            ("category", Value::from(category.as_str())),
        ]);
        let reset = get(&detection, "reset_at").clone();
        let owner = self.owner(&thread, &turn)?;
        let progress = self.source.turn_progress(&thread, &turn)?;
        let carry = if owner.is_some() {
            Value::Null
        } else {
            self.legacy_carry(&detection)?
        };
        let (mut answer, mut parent) = (Answer::Defer, None);
        if asking {
            let Some(decided) = self.taken_up(
                record,
                shape,
                owner.as_deref(),
                progress,
                &carry,
                admissible,
                now,
            )?
            else {
                return Ok(());
            };
            (answer, parent) = decided;
        }
        let poll = self.options.conservative_poll_seconds;
        let (state, when) = if usage {
            if truthy(&reset) {
                let reset_at = py::num(&reset)?;
                (
                    "waiting_reset",
                    (now + 30.0).max(reset_at + self.options.reset_grace_seconds),
                )
            } else {
                ("waiting_poll", now + poll)
            }
        } else if answer == Answer::Is(Alternative::Capacity) {
            (
                "waiting_backoff",
                now + self.capacity_wait(parent.as_ref())?,
            )
        } else if let Some(paced) = match &answer {
            Answer::Is(word) => paced_as(*word),
            Answer::Defer => None,
        } {
            // Taken up as a temporary kind (P17): waited, counted and switched off as that kind.
            let wait =
                self.detection_wait(paced, &thread, &turn, owner.as_deref(), &Value::Null)?;
            ("waiting_backoff", now + wait)
        } else if admissible {
            let wait = self.admitted_wait(parent.as_ref(), &detection, owner.as_deref())?;
            ("waiting_backoff", now + wait)
        } else {
            // The preset's first wait, as in v0.6.10; from v0.6.11 the Custom ladder's step for this attempt at the
            // task, a Retry-After Codex named, and jitter, each only if set.
            let wait = self.detection_wait(
                &category,
                &thread,
                &turn,
                owner.as_deref(),
                get(record, "retry_after"),
            )?;
            ("waiting_backoff", now + wait)
        };
        // v0.6.11: a conversation that asks first, or only notifies, has what it detects held for a person.
        let mut hold = self.admission(&thread, now)?;
        // And what the two guards keep of it, each only while it is on (engine/guard.rs).
        let facts = self.detected_facts(&thread);
        if matches!(hold, Value::Null)
            && guards::over(&self.values(), get(&facts, "context_tokens"))
        {
            hold = Value::from(guards::CONTEXT_HOLD);
        }
        // One transaction: the record can never exist without its real schedule and the counters of its task.
        let limits = if answer == Answer::Is(Alternative::Capacity) {
            self.capacity_limits()
        } else {
            self.limits()
        };
        let options = Register {
            state: state.into(),
            next_retry_at: when,
            owner_id: owner.clone(),
            failed_turn_progress: progress.map_or(Value::Null, Value::Bool),
            legacy_carry: carry,
            limits: limits_of(&limits),
            hold,
            home_key: self.home_key.clone(),
            task_print: get(&facts, "task_print").clone(),
            context_tokens: get(&facts, "context_tokens").clone(),
        };
        if !self.store.register(&detection, now, &options)? {
            return Ok(());
        }
        let registered = self.store.get(&key)?.ok_or("TypeError")?;
        if admissible {
            self.log(Some(&thread), "failure_taken_up", Value::from(key.as_str()));
            self.passed_known.keep(turn.clone(), SKIPS_KEPT);
        } else if usage {
            self.log(
                Some(&thread),
                "usageLimitExceeded_detected",
                Value::from(key.as_str()),
            );
        } else {
            self.log(
                Some(&thread),
                "transient_failure_detected",
                Value::from(category.as_str()),
            );
        }
        let registered_state = s(&registered, "state");
        if TERMINAL.contains(&registered_state.as_str()) {
            // Created already stopped: said once, and never as "will resume".
            let last = get(&registered, "last_error").clone();
            self.log(Some(&thread), &registered_state, last.clone());
            let detail = row(vec![
                ("state", Value::from(registered_state.as_str())),
                ("reason", last),
            ]);
            self.announce("stopped", &registered, detail);
            return Ok(());
        }
        if usage && truthy(&reset) {
            let at = py::int_of(&reset)?;
            self.log(Some(&thread), "reset_expected", Value::from(at.to_string()));
        } else if usage {
            let poll = (self.options.conservative_poll_seconds as i64).to_string();
            self.log(
                Some(&thread),
                "reset_unknown_conservative_poll",
                Value::from(poll),
            );
        }
        if truthy(get(&detection, "uncertain")) {
            self.log(Some(&thread), "blocking_limit_uncertain", Value::Null);
        }
        // A held one says it waits for a person, never that it will resume.
        let held = match get(&registered, "hold") {
            Value::Null => Map::new(),
            hold => row(vec![("hold", hold.clone())]),
        };
        self.announce("interruption", &registered, held);
        Ok(())
    }
}
