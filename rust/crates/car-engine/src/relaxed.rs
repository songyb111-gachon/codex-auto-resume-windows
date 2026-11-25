//! What the edition's plug may relax (v0.6.14 stage 3b), and the bounds core holds every answer to
//! (`engine/relaxed.py`).
//!
//! Two gates core keeps, each asked of the plug: P17, whether a failure core never recovers alone is taken up when it
//! is detected; and known_failure, whether such a record goes on when it falls due. An answer is taken only if core
//! offered it, and is carried out within core's own bounds (ladder). And P7 (EARLY, SEND_NOW). The standard edition's
//! plug is asked nothing here: a record taken up under another edition ends unsent at its next look, and that is all.

use std::collections::BTreeSet;

use car_machine::domain::public::eligible_at;
use car_machine::json::{Map, Str, Value};
use car_machine::pyval::Py;
use car_policy::classify::failures::{self, ADMISSIBLE, UNKNOWN as UNKNOWN_KIND, USAGE_LIMIT};
use car_policy::classify::gates::{
    BLOCK, FORCEABLE, HELD, OBSERVE_ONLY, PASS, PLUGGED, SEND_NOW, UNKNOWN, Vector, WAIT,
    birth_stop, gate, gate_schedule, own_budget_only,
};
use car_policy::classify::ladder::{self, EARLY_STATES};
use car_policy::plug::{Alternative, Answer, Point, paced_as};

use crate::dispatch::{Known, vector_value};
use crate::options::{LimitsMap, limits_of};
use crate::py::{self, get, row, s, text, text_of, with};
use crate::{Engine, Row};

/// How often a failure P17 did not take up is put to it again, at most.
pub const UNADMITTED_SECONDS: f64 = 60.0;
/// How many records of a task are read back, at most, for the kinds of failure it has had (v0.6.14).
pub const CHAIN_WALK: usize = 64;

impl Engine {
    /// `chain_started_at(row)`: when a record's task first failed, on the clock (v0.6.14).
    pub fn chain_started_at(&self, row: &Row) -> Py<Value> {
        if py::eq(get(row, "chain_origin_id"), get(row, "interruption_id")) {
            return Ok(get(row, "detected_at").clone());
        }
        let origin = self.store.get(&s(row, "chain_origin_id"))?;
        Ok(origin.map_or(Value::Null, |origin| get(&origin, "detected_at").clone()))
    }

    /// `chain_categories(row)`: every kind of failure a record's task has had, sorted, or None where one is gone.
    pub fn chain_categories(&self, row: &Row) -> Py<Option<Vec<String>>> {
        let mut found: BTreeSet<String> = BTreeSet::new();
        let mut seen: BTreeSet<String> = BTreeSet::new();
        let mut current = Some(row.clone());
        while let Some(row) = current {
            let key = s(&row, "interruption_id");
            if seen.contains(&key) || seen.len() >= CHAIN_WALK {
                break;
            }
            found.insert(s(&row, "category"));
            if py::eq(get(&row, "interruption_id"), get(&row, "chain_origin_id")) {
                return Ok(Some(found.into_iter().collect()));
            }
            seen.insert(key);
            current = match text(get(&row, "parent_interruption_id")) {
                Some(parent) => self.store.get(parent)?,
                None => None,
            };
        }
        Ok(None)
    }

    /// `_unadmit(key, now)`: a failure P17 did not take up is asked again a minute from now at the soonest.
    fn unadmit(&mut self, key: &str, now: f64) {
        if self.unadmitted.len() > 512 {
            self.unadmitted.clear();
        }
        self.unadmitted.insert(key.to_owned(), now);
    }

    /// `_taken_up(record, shape, owner, progress, carry, admissible, now)`: P17 for one failure - (the answer core
    /// carries out, the record of its task it continues), or None for a failure left alone.
    #[allow(clippy::too_many_arguments)]
    pub(crate) fn taken_up(
        &mut self,
        record: &Map,
        shape: &Value,
        owner: Option<&str>,
        progress: Option<bool>,
        carry: &Value,
        admissible: bool,
        now: f64,
    ) -> Py<Option<(Answer<Alternative>, Option<Row>)>> {
        let mut facts = match shape {
            Value::Object(shape) => shape.clone(),
            _ => Map::new(),
        };
        facts.insert(Str::from("category"), get(record, "category").clone());
        let facts = Value::Object(facts);
        let mut offered: Vec<&'static str> = if matches!(shape, Value::Null) {
            Vec::new()
        } else {
            failures::takes(&facts, &|category| self.recovers(category))?
        };
        if offered.is_empty() {
            return Ok(if admissible {
                None
            } else {
                Some((Answer::Defer, None))
            });
        }
        let parent =
            self.store
                .chain_parent(&s(record, "thread_id"), &s(record, "turn_id"), owner)?;
        let progress = progress.map_or(Value::Null, Value::Bool);
        if admissible
            && birth_stop(
                parent.as_ref(),
                &progress,
                Some(&limits_of(&self.limits())),
                false,
                now,
                carry,
            )
            .is_some()
        {
            self.unadmit(&s(record, "interruption_id"), now);
            return Ok(None);
        }
        let chain = match &parent {
            None => Value::Null,
            Some(parent) => {
                let mut chain = Map::new();
                for name in [
                    "interruption_id",
                    "category",
                    "recovery_attempts",
                    "chain_continuations",
                    "detected_at",
                ] {
                    chain.insert(Str::from(name), get(parent, name).clone());
                }
                let started = self.chain_started_at(parent)?;
                chain.insert(Str::from("chain_started_at"), started);
                let categories = self.chain_categories(parent)?;
                chain.insert(
                    Str::from("categories"),
                    categories.map_or(Value::Null, |found| {
                        Value::Array(
                            found
                                .iter()
                                .map(|each| Value::from(each.as_str()))
                                .collect(),
                        )
                    }),
                );
                Value::Object(chain)
            }
        };
        if let Value::Object(found) = &chain
            && !Engine::capacity_open(get(found, "chain_started_at"), now)
        {
            offered.retain(|word| *word != Alternative::Capacity.as_str()); // 24 hours on the clock
        }
        if offered.is_empty() {
            return Ok(if admissible {
                None
            } else {
                Some((Answer::Defer, parent))
            });
        }
        let mut failure = Map::new();
        for name in [
            "interruption_id",
            "thread_id",
            "turn_id",
            "category",
            "started_at",
            "completed_at",
            "ordinal",
        ] {
            failure.insert(Str::from(name), get(record, name).clone());
        }
        if let Value::Object(facts) = &facts {
            for (key, value) in facts {
                failure.insert(key.clone(), value.clone());
            }
        }
        failure.insert(
            Str::from("takes"),
            Value::Array(offered.iter().map(|word| Value::from(*word)).collect()),
        );
        failure.insert(Str::from("chain"), chain);
        let mut answer = self.plug.admission(&Value::Object(failure));
        if let Answer::Is(word) = answer
            && !offered.contains(&word.as_str())
        {
            answer = Answer::Defer;
        }
        if admissible && answer == Answer::Defer {
            self.unadmit(&s(record, "interruption_id"), now);
            return Ok(None);
        }
        Ok(Some((answer, parent)))
    }

    /// `capacity_open(started_at, now)`: whether a task's capacity retries may go on (24 hours on the clock).
    pub fn capacity_open(started_at: &Value, now: f64) -> bool {
        py::arithmetic(started_at)
            .is_some_and(|started| now - started < ladder::CAPACITY_MAX_SECONDS as f64)
    }

    /// `_capacity_wait(parent)`: core's own step for the attempt at its task, lengthened by up to a fifth.
    pub(crate) fn capacity_wait(&mut self, parent: Option<&Row>) -> Py<f64> {
        let steps = ladder::CAPACITY_WAITS;
        let index = match parent {
            Some(parent) => py_index(py::int_of(get(parent, "recovery_attempts"))?, steps.len())?,
            None => 0,
        };
        let wait = Value::from(steps[index as usize]);
        let draw = self.draw();
        let values = Value::Object(row(vec![("retry_jitter", Value::Bool(true))]));
        py::num(&ladder::jittered(&wait, &values, &Value::Float(draw))?)
    }

    /// `_admitted_wait(parent, detection, owner)`: core's own wait for the attempt at its task, never less than an
    /// unknown failure's first wait, jitter as set.
    pub(crate) fn admitted_wait(
        &mut self,
        parent: Option<&Row>,
        detection: &Map,
        owner: Option<&str>,
    ) -> Py<f64> {
        let steps = ladder::ADMITTED_WAITS;
        let index = match parent {
            Some(parent) => py_index(py::int_of(get(parent, "recovery_attempts"))?, steps.len())?,
            None => 0,
        };
        let mut wait = Value::from(steps[index as usize]);
        if matches!(get(&self.policy_values, "retry_jitter"), Value::Bool(true)) {
            let draw = self.draw();
            wait = ladder::jittered(&wait, &self.values(), &Value::Float(draw))?;
        }
        let first = self.detection_wait(
            UNKNOWN_KIND,
            &s(detection, "thread_id"),
            &s(detection, "turn_id"),
            owner,
            &Value::Null,
        )?;
        Ok(py::num(&wait)?.max(first))
    }

    /// `_known_failure(row, vector, now)`: the known_failure gate - go on as core, relaxed, or stopped here.
    pub(crate) fn known_failure(&mut self, row: &Row, vector: &mut Vector, now: f64) -> Py<Known> {
        let category = s(row, "category");
        let poll = self.options.conservative_poll_seconds;
        let consent = vector.or_unknown("consent").0 == PASS;
        if failures::is_recoverable(&category) {
            if !self.recovers(&category) {
                vector.set("known_failure", gate(BLOCK, "category_disabled"));
                let state = s(row, "state");
                self.wait(row, &state, Some("category_disabled"), poll, vector)?;
                return Ok(Known::Stopped);
            }
            vector.set("known_failure", gate(PASS, "ok"));
            if !consent {
                return Ok(Known::Go(None));
            }
            let chained = self.chained(row)?;
            let answer = self.plug.gate(
                "known_failure",
                &Value::Object(chained),
                &vector_value(vector),
            );
            if self.held("known_failure", row, vector, &answer)? {
                return Ok(Known::Stopped);
            }
            if answer == Answer::Is(Alternative::Capacity)
                && failures::readmits(&Value::from(category.as_str()), &Value::from("capacity"))?
                && Engine::capacity_open(&self.chain_started_at(row)?, now)
            {
                vector.set("known_failure", gate(PASS, PLUGGED));
                return Ok(Known::Go(Some("capacity")));
            }
            if answer == Answer::Is(Alternative::VerifiedReset)
                && failures::reset_verified(row, now)
            {
                // v0.6.22 (issue #59): a reset core saw pass, claimed within RESET_PER_DAY, its spacing kept.
                vector.set("known_failure", gate(PASS, PLUGGED));
                return Ok(Known::Go(Some("reset")));
            }
            return Ok(Known::Go(None));
        }
        if !consent {
            vector.set("known_failure", gate(UNKNOWN, OBSERVE_ONLY));
            let (state, last) = (s(row, "state"), py::opt(row, "last_error"));
            self.wait(row, &state, last.as_deref(), poll, vector)?;
            return Ok(Known::Stopped);
        }
        if self.plug.is_null() || !ADMISSIBLE.contains(&category.as_str()) {
            return self.not_recovered(row, vector, "not_recoverable");
        }
        if now - py::num(get(row, "detected_at"))? >= ladder::ADMITTED_MAX_SECONDS as f64 {
            return self.not_recovered(row, vector, "admission_expired");
        }
        let chained = self.chained(row)?;
        let answer = self.plug.gate(
            "known_failure",
            &Value::Object(chained),
            &vector_value(vector),
        );
        if self.held("known_failure", row, vector, &answer)? {
            return Ok(Known::Stopped);
        }
        let word = match answer {
            Answer::Is(word) => Value::from(word.as_str()),
            Answer::Defer => Value::Null,
        };
        if !failures::readmits(&Value::from(category.as_str()), &word)? {
            return self.not_recovered(row, vector, "not_recoverable");
        }
        if let Answer::Is(word) = answer
            && let Some(paced) = paced_as(word)
            && !self.recovers(paced)
        {
            vector.set("known_failure", gate(BLOCK, "category_disabled"));
            let state = s(row, "state");
            self.wait(row, &state, Some("category_disabled"), poll, vector)?;
            return Ok(Known::Stopped);
        }
        vector.set("known_failure", gate(PASS, PLUGGED));
        Ok(Known::Go(Some("admitted")))
    }

    /// `relaxed_points(relaxed)`: the points a relaxation's send carries, for the ledger to pay.
    pub fn relaxed_points(relaxed: Option<&str>) -> BTreeSet<Point> {
        match relaxed {
            Some("admitted" | "capacity" | "reset") => BTreeSet::from([Point::Gates]),
            Some("early" | "resend" | "forced") => BTreeSet::from([Point::Schedule]),
            _ => BTreeSet::new(),
        }
    }

    /// `_early(row, vector, now, quiet_until)`: P7 asked early (EARLY).
    pub(crate) fn early(
        &mut self,
        row: &Row,
        vector: &mut Vector,
        now: f64,
        quiet_until: Option<f64>,
    ) -> Py<bool> {
        let schedule = vector.or_unknown("schedule");
        if self.plug.is_null()
            || vector.or_unknown("consent").0 != PASS
            || text_of(row, "category") != Some(USAGE_LIMIT)
            || !text_of(row, "state").is_some_and(|state| EARLY_STATES.contains(&state))
            || !matches!(schedule.1.as_str(), "not_due" | "waiting_reset")
            || gate_schedule(row, now, quiet_until, true, false).0 != PASS
        {
            return Ok(false);
        }
        let opened = self.early_at;
        let inside = opened
            .is_some_and(|opened| (0.0..ladder::EARLY_WINDOW as f64).contains(&(now - opened)));
        // v0.6.19 (issue #50): a person's reading opens the window before its five minutes are up.
        let asked = !inside && self.store.early_check_asked(now)?;
        if !inside
            && opened
                .is_some_and(|opened| (0.0..ladder::EARLY_SPACING as f64).contains(&(now - opened)))
            && !asked
        {
            return Ok(false);
        }
        if !self.plug.wants(Point::Schedule) {
            return Ok(false);
        }
        let whole = Value::Object(row.clone());
        let said = self.plug.schedule(&whole, &eligible_at(&whole)?);
        self.schedule_said = Some(said.clone());
        if said != Answer::Is(Alternative::Early) {
            return Ok(false);
        }
        if !inside {
            self.early_at = Some(now);
            if asked {
                self.store.early_check_taken()?;
            }
        }
        self.early_look = Some(s(row, "interruption_id"));
        vector.set("schedule", gate(PASS, PLUGGED));
        Ok(true)
    }

    /// `_send_now(row, vector, now, quiet_until)`: P7 at a schedule core refused (SEND_NOW).
    pub(crate) fn send_now(
        &mut self,
        row: &Row,
        vector: &mut Vector,
        now: f64,
        quiet_until: Option<f64>,
    ) -> bool {
        if self.plug.is_null()
            || vector.or_unknown("consent").0 != PASS
            || !FORCEABLE.contains(&vector.or_unknown("schedule").1.as_str())
            || gate_schedule(row, now, quiet_until, false, true).0 != PASS
            || !self.plug.wants(Point::Schedule)
        {
            return false;
        }
        let said = match &self.schedule_said {
            Some(said) => said.clone(),
            None => {
                let whole = Value::Object(row.clone());
                let Ok(due) = eligible_at(&whole) else {
                    return false;
                };
                let said = self.plug.schedule(&whole, &due);
                self.schedule_said = Some(said.clone());
                said
            }
        };
        if said != Answer::Is(Alternative::SendNow) {
            return false;
        }
        vector.set("schedule", gate(PASS, SEND_NOW));
        true
    }

    /// `_own_budget(row, vector)`: a person's Send now passes an attempt budget spent under their own setting alone.
    pub(crate) fn own_budget(&self, row: &Row, vector: &mut Vector) {
        let administrators = self.managed.max_recovery_attempts.map(|limit| limit as f64);
        if vector.or_unknown("attempt_budget") == gate(BLOCK, "recovery_budget")
            && own_budget_only(row, administrators)
        {
            vector.set("attempt_budget", gate(PASS, SEND_NOW));
        }
    }

    /// `forced_limits(limits)`: `limits` as a Send now's claim is told them, with the administrator's ceiling.
    pub fn forced_limits(&self, limits: &LimitsMap) -> LimitsMap {
        with(
            limits,
            vec![(
                "managed_max_recovery_attempts",
                self.managed
                    .max_recovery_attempts
                    .map_or(Value::Null, Value::from),
            )],
        )
    }

    /// `_held(name, row, vector, answer)`: whether the plug's answer at gate `name` holds this record. HOLD only
    /// restricts: the gate is recorded as waiting, and the record keeps its state and reason for one more poll.
    pub(crate) fn held(
        &mut self,
        name: &str,
        row: &Row,
        vector: &mut Vector,
        answer: &Answer<Alternative>,
    ) -> Py<bool> {
        if *answer != Answer::Is(Alternative::Hold) {
            return Ok(false);
        }
        vector.set(name, gate(WAIT, HELD));
        let (state, last) = (s(row, "state"), py::opt(row, "last_error"));
        let poll = self.options.state_poll_seconds;
        self.wait(row, &state, last.as_deref(), poll, vector)?;
        Ok(true)
    }

    /// `_parked(row, vector)`: while `row` is looked at early, a wait is its gate vector alone.
    pub(crate) fn parked(&mut self, row: &Row, vector: &Vector) -> Py<bool> {
        let key = s(row, "interruption_id");
        if self.early_look.as_deref() != Some(key.as_str()) {
            return Ok(false);
        }
        let now = self.now();
        self.store.record_gates(&key, vector, now)?;
        Ok(true)
    }

    /// `_chained(row)`: a record as known_failure is put to the plug, read only while the plug wants the gates.
    fn chained(&self, row: &Row) -> Py<Row> {
        if !self.plug.wants(Point::Gates) {
            return Ok(row.clone());
        }
        Ok(with(
            row,
            vec![("chain_started_at", self.chain_started_at(row)?)],
        ))
    }

    /// `_not_recovered(row, vector, reason)`: end a record P17 took up that nothing takes up any more.
    fn not_recovered(&mut self, row: &Row, vector: &mut Vector, reason: &str) -> Py<Known> {
        vector.set("known_failure", gate(BLOCK, reason));
        let now = self.now();
        self.store
            .record_gates(&s(row, "interruption_id"), vector, now)?;
        self.transition(
            row,
            "terminal_failure",
            Some(reason),
            None,
            None,
            Row::new(),
        )?;
        Ok(Known::Stopped)
    }
}

/// `steps[min(n, len(steps) - 1)]`'s index, as Python takes it: a negative count counts from the end.
fn py_index(n: i64, len: usize) -> Py<i64> {
    let index = n.min(len as i64 - 1);
    let index = if index < 0 { index + len as i64 } else { index };
    if index < 0 {
        Err("IndexError")
    } else {
        Ok(index)
    }
}
