//! How a continuation is carried, the last look before it goes, and what proves it arrived (`engine/delivery.py`).
//!
//! Core has always ended a continuation's words with the record's marker, and proven delivery by finding that marker
//! in Codex's history (A4). The edition's plug may ask for a continuation with no marker instead (P15): `delivery`
//! takes that answer before the claim and writes the id into the record; `proof` is what every look at a sent record
//! is made for from then on; `presend_problem` is the last look, after the claim. The standard edition's plug always
//! defers, so every record it sends carries its marker.

use car_machine::domain::ids;
use car_machine::json::{Map, Value};
use car_machine::pyval::Py;
use car_machine::vocab_gen::domain_states::{CLAIMED, WAITING};
use car_policy::classify::continuation::{self, Settings};
use car_policy::classify::failures::USAGE_LIMIT;
use car_policy::plug::{Alternative, Answer};

use crate::options::{LimitsMap, backoff_delay};
use crate::py::{self, get, row, s, text, text_of, truthy, with};
use crate::{Engine, Row};

/// (target, reason, delay) to give a claim back.
pub type Problem = (String, String, f64);

impl Engine {
    /// `proof(row)`: the client id a marker-free continuation was queued under, or its marker.
    pub fn proof_of(row: &Row) -> String {
        let client = get(row, "recovery_client_id");
        if let Some(client) = text(client)
            && client
                == ids::continuation_client_id(text_of(row, "interruption_id").unwrap_or_default())
        {
            return client.to_owned();
        }
        s(row, "marker")
    }

    /// `proof(row)`.
    pub fn proof(&self, row: &Row) -> String {
        Engine::proof_of(row)
    }

    /// `_delivery(row, sender, resend)`: P15 - the client id a continuation of `row` is sent under with no marker,
    /// `Some(None)` for the marker, or (a resend) `None` where it would not carry the proof its first send did.
    pub(crate) fn delivery(
        &mut self,
        row: &Row,
        channel: bool,
        resend: bool,
    ) -> Py<Option<Option<String>>> {
        let answer = self.plug.delivery(&Value::Object(row.clone()));
        let key = s(row, "interruption_id");
        let derived = ids::continuation_client_id(&key);
        let client =
            (answer == Answer::Is(Alternative::ClientId) && channel).then(|| derived.clone());
        if resend {
            let marker_free = self.proof(row) != s(row, "marker");
            return Ok(if client.is_some() == marker_free {
                Some(client)
            } else {
                None
            });
        }
        let held = get(row, "recovery_client_id");
        if let Some(client) = &client
            && text(held) != Some(client.as_str())
        {
            let at = self.now();
            self.store.update(
                &key,
                &row_of("recovery_client_id", Value::from(client.as_str())),
                Some(at),
                None,
                0,
            )?;
        } else if client.is_none() && text(held) == Some(derived.as_str()) {
            let at = self.now();
            self.store.update(
                &key,
                &row_of("recovery_client_id", Value::Null),
                Some(at),
                None,
                0,
            )?;
        }
        Ok(Some(client))
    }

    /// `presend_problem(claim, forced)`: the last look before the queue process starts. (target, reason, delay) to
    /// give the claim back, or None to send. A person's Send now is not stopped by a postponement, which it passed.
    pub fn presend_problem(&mut self, claim: Option<&Row>, forced: bool) -> Py<Option<Problem>> {
        let poll = self.options.state_poll_seconds;
        let back = |target: &str, reason: &str, delay: f64| {
            Ok(Some((target.to_owned(), reason.to_owned(), delay)))
        };
        let Some(claim) = claim else {
            return back("waiting_retry", "released_before_send", poll);
        };
        if text_of(claim, "state") != Some("submitting")
            || !matches!(get(claim, "queue_id"), Value::Null)
        {
            return back("waiting_retry", "released_before_send", poll);
        }
        if truthy(get(claim, "cancel_requested")) {
            return back("cancelled", "user_cancelled", 0.0);
        }
        let now = self.now();
        let postponed = !forced && py::or_zero(get(claim, "not_before")) > now; // schema 4's, and
        if !self.allowed(claim)? || postponed || self.quiet_until(now)?.is_some() {
            // quiet hours
            let state = self.waiting_state(claim)?;
            return back(&state, "released_before_send", poll);
        }
        if !self.valid_interruption(claim)? {
            let (state, reason) = self.supersede_reason(claim);
            return back(&state, &reason, 0.0);
        }
        let thread = s(claim, "thread_id");
        if self.projection_now(&thread) != Some(true) {
            return back("waiting_for_loaded_thread", "projection_stale", poll);
        }
        let proof = self.proof(claim);
        if self.source.foreign_queued(&thread, &proof)? != 0 {
            return back("waiting_retry", "user_input_queued", poll);
        }
        let marker = s(claim, "marker");
        let mut tokens = vec![proof];
        if tokens[0] != marker {
            tokens.push(marker);
        }
        for token in tokens {
            let presence = self.source.marker_presence(&thread, &token)?;
            if truthy(get(&presence, "history")) || truthy(get(&presence, "queue")) {
                return back("superseded", "duplicate_owner", 0.0);
            }
        }
        if !(self.home_lock)()? {
            return back("waiting_for_app", "home_lock_unavailable", poll);
        }
        Ok(None)
    }

    /// `_plugged_text(row, message, limits)`: P4 - (the plug's words, True), or (core's own `message`, False).
    pub(crate) fn plugged_text(
        &self,
        row: &Row,
        message: String,
        limits: &LimitsMap,
    ) -> (String, bool) {
        let said = self
            .plug
            .text(&Value::Object(row.clone()), &message.as_str().into());
        let Answer::Is(words) = said else {
            return (message, false);
        };
        let words = Value::Str(words);
        let taken = (|| -> Py<Option<String>> {
            continuation::validate_custom(&words).map_err(|_| "PromptError")?;
            let values = Value::Object(with(
                &self.policy_values,
                vec![
                    ("continuation_style", Value::from("custom")),
                    ("custom_message_by_thread", Value::Null),
                    ("custom_message_mode", Value::from("global")),
                    ("custom_message", words.clone()),
                ],
            ));
            let environ = continuation::Environ {
                variable: &|name: &str| (self.environ)(name),
                windows: &|| (self.windows_languages)(),
            };
            let at = Settings {
                values: &values,
                row: &Value::Object(row.clone()),
                limits: &Value::Object(limits.clone()),
                environ: &environ,
                clock: self.local.as_ref(),
            };
            if continuation::source_for(get(row, "category"), &at)? != Some("global") {
                return Ok(None);
            }
            Ok(Some(continuation::for_settings(get(row, "category"), &at)?))
        })();
        match taken {
            Ok(Some(words)) => (words, true),
            _ => (message, false),
        }
    }

    // --------------------------------------------------------------- words for this time (v0.6.16-beta.3)
    /// `_once_words(row, message, limits)`: (the continuation with this interruption's words for this time after it,
    /// the words), or (`message`, None).
    pub(crate) fn once_words_for(
        &mut self,
        row: &Row,
        message: String,
        limits: &LimitsMap,
    ) -> (String, Option<Value>) {
        let key = s(row, "interruption_id");
        self.once_seen.remove(&key);
        let waiting = text_of(row, "state").is_some_and(|state| WAITING.contains(&state));
        if !waiting {
            return (message, None);
        }
        let Some(once) = self.once_words.as_ref() else {
            return (message, None);
        };
        let Ok(words) = once.words(&key) else {
            return (message, None);
        };
        self.once_seen.insert(key, words.clone()); // what the file held as this one was built
        let environ = continuation::Environ {
            variable: &|name: &str| (self.environ)(name),
            windows: &|| (self.windows_languages)(),
        };
        let values = self.values();
        let at = Settings {
            values: &values,
            row: &Value::Object(row.clone()),
            limits: &Value::Object(limits.clone()),
            environ: &environ,
            clock: self.local.as_ref(),
        };
        let joined = continuation::with_once_words(
            &Value::from(message.as_str()),
            &words,
            get(row, "category"),
            &at,
        );
        match joined {
            Ok(Value::Str(joined)) => {
                let joined = String::from_utf8_lossy(joined.as_bytes()).into_owned();
                if joined != message {
                    (joined, Some(words))
                } else {
                    (message, None)
                }
            }
            _ => (message, None),
        }
    }

    /// `_once_words_moved(claim)`: whether a person changed this interruption's words for this time between the read
    /// that built its continuation and the claim - True, and the claim is given back. v0.6.23 (audit C3): a file that
    /// cannot be had just now gives the claim back once too.
    pub(crate) fn once_words_moved(&mut self, claim: &Row) -> Py<bool> {
        let key = s(claim, "interruption_id");
        let Some(seen) = self.once_seen.remove(&key) else {
            return Ok(false);
        };
        let unchanged = match self.once_words.as_ref() {
            Some(once) => once.unchanged(&key, &seen).unwrap_or(Value::Null),
            None => Value::Null,
        };
        let moved = matches!(unchanged, Value::Bool(false))
            || (matches!(unchanged, Value::Null) && !self.once_doubted.contains(&key));
        if matches!(unchanged, Value::Null) && moved {
            self.once_doubted.insert(key.clone());
        } else {
            self.once_doubted.remove(&key);
        }
        if moved {
            // given back as a pre-send look gives one back: nothing was sent
            let poll = self.options.state_poll_seconds;
            self.release(
                &key,
                Some(claim),
                "waiting_retry",
                "released_before_send",
                poll,
            )?;
            self.log(
                Some(&s(claim, "thread_id")),
                "waiting_retry",
                Value::from("released_before_send"),
            );
        }
        Ok(moved)
    }

    /// `_spend_once_words(claim, words)`: the words taken off the file as the continuation carrying them is handed to
    /// Codex, so they are never sent twice.
    pub(crate) fn spend_once_words(&mut self, claim: &Row, words: &Value) -> bool {
        let key = s(claim, "interruption_id");
        let spent = match self.once_words.as_ref() {
            Some(once) => once
                .remove(&key)
                .map(|spent| truthy(&spent))
                .unwrap_or(false),
            None => false,
        };
        if spent {
            self.once_sent.insert(key, words.clone());
        }
        let event = if spent {
            "once_words_sent"
        } else {
            "once_words_kept"
        };
        self.log(Some(&s(claim, "thread_id")), event, Value::Null);
        spent
    }

    /// `_prune_once_words()`: words of an interruption no longer waiting, deleted (the default home's engine only).
    pub(crate) fn prune_once_words(&mut self) {
        if self.once_words.is_none() || !self.home_key.is_empty() {
            return;
        }
        let store = self.store.as_ref();
        let mut keep = |key: &str| -> Py<bool> {
            let state = store
                .get(key)?
                .map(|row| get(&row, "state").clone())
                .unwrap_or(Value::Null);
            Ok(text(&state)
                .is_some_and(|state| WAITING.contains(&state) || CLAIMED.contains(&state)))
        };
        let pruned = self
            .once_words
            .as_ref()
            .map_or(Ok(()), |once| once.prune(&mut keep));
        if pruned.is_err() {
            self.log(None, "once_words_unavailable", Value::Null);
        }
    }

    /// `_after_send(row, response, resend)`: what came of a send.
    pub(crate) fn after_send(&mut self, row: &Row, response: &Map, resend: bool) -> Py<()> {
        let key = s(row, "interruption_id");
        let thread = s(row, "thread_id");
        let reserved = self.store.get(&key)?.ok_or("TypeError")?;
        let outcome = get(response, "outcome").clone();
        let outcome_is = |word: &str| text(&outcome) == Some(word);
        let words = self.once_sent.remove(&key);
        if let Some(words) = &words
            && outcome_is("not_started")
            && let Some(once) = self.once_words.as_ref()
        {
            let _ = once.restore(&key, words); // never handed over: they wait for the next one
        }
        if resend && !outcome_is("accepted") {
            return self.after_resend(&reserved, &outcome);
        }
        if outcome_is("accepted") {
            let now = self.now();
            let first = py::or(get(&reserved, "first_queued_at"), Value::Float(now));
            self.transition(
                &reserved,
                "queued",
                None,
                Some(1.0),
                Some("submitted"),
                row_pairs(vec![
                    ("queue_id", get(response, "queue_id").clone()),
                    ("first_queued_at", first),
                ]),
            )?;
            self.log(Some(&thread), "continuation_submitted", Value::Null);
            let told = self.told_of(row);
            self.announce("starting", &reserved, told); // a Tell's line (engine/guard.rs)
            return Ok(());
        }
        if outcome_is("not_started") {
            let poll = self.options.state_poll_seconds;
            if text(get(response, "error_code")) == Some("queue_consent_refused") {
                let cancel = truthy(get(&reserved, "cancel_requested"));
                let target = if cancel {
                    "cancelled".to_owned()
                } else {
                    self.waiting_state(&reserved)?
                };
                let reason = if cancel {
                    "user_cancelled"
                } else {
                    "released_before_send"
                };
                self.release(&key, Some(&reserved), &target, reason, poll)?;
                self.log(Some(&thread), &target, Value::from(reason));
                return Ok(());
            }
            let retry = py::plus_one(get(&reserved, "retry_count"))?;
            let count = py::int_of(&retry)?;
            if (count as f64) >= self.options.max_queue_retries {
                return self.transition(
                    &reserved,
                    "failed",
                    Some("queue_launch_retry_limit"),
                    None,
                    None,
                    row_pairs(vec![("retry_count", retry), ("submitted_at", Value::Null)]),
                );
            }
            let delay = if text_of(&reserved, "category") != Some(USAGE_LIMIT) {
                py::num(&self.delay_for(py::int_of(get(&reserved, "recovery_attempts"))?))?
            } else {
                backoff_delay(count) as f64
            };
            return self.transition(
                &reserved,
                "waiting_retry",
                Some("queue_process_not_started"),
                Some(delay),
                None,
                row_pairs(vec![("retry_count", retry), ("submitted_at", Value::Null)]),
            );
        }
        // Persist the no-resend state first. Diagnostic logging is not a prerequisite for it.
        self.transition(
            &reserved,
            "submission_unknown",
            Some("queue_result_unknown_do_not_resend"),
            Some(1.0),
            None,
            Row::new(),
        )?;
        // CLI receipt diagnostics are fixed vocabulary only: never CLI output.
        if text(get(response, "error_code")) == Some("queue_response_unconfirmed") {
            match text(get(response, "receipt_detail")) {
                Some("nonzero_exit") => {
                    let code = match get(response, "exit_code") {
                        Value::Int(code) => code
                            .as_i64()
                            .filter(|code| (0..=255).contains(code))
                            .map_or(Value::Null, |code| Value::from(code.to_string())),
                        _ => Value::Null,
                    };
                    self.log(Some(&thread), "queue_receipt_exit_nonzero", code);
                }
                Some("empty_stdout") => {
                    self.log(Some(&thread), "queue_receipt_empty_stdout", Value::Null)
                }
                Some("unrecognized_stdout") => self.log(
                    Some(&thread),
                    "queue_receipt_unrecognized_stdout",
                    Value::Null,
                ),
                _ => {}
            }
        }
        Ok(())
    }

    // --------------------------------------------------------------- receipts on workers (P12, v0.6.15-beta)
    /// `_workers(due)`: P12's answer, and 1 for another Codex home, a retiring one, or no store for a worker.
    pub(crate) fn workers(&self, due: &[Row]) -> i64 {
        let records: Vec<Value> = due.iter().map(|row| Value::Object(row.clone())).collect();
        let workers = self.plug.partition(&records);
        if !self.home_key.is_empty() || self.retiring || !self.open_store || self.opener.is_none() {
            1
        } else {
            workers
        }
    }
}

fn row_of(name: &str, value: Value) -> Row {
    row(vec![(name, value)])
}

fn row_pairs(pairs: Vec<(&str, Value)>) -> Row {
    row(pairs)
}

impl Engine {
    /// Hand the engine what opens a store for a worker (P12's `open_store`).
    pub fn set_opener(&mut self, opener: crate::launches::Opener) {
        self.opener = Some(opener);
    }

    /// `_take_slot(resend, route)`: a worker for the send being dispatched, taken before its claim - waiting, outside
    /// any transaction, while every worker is busy - while a pool is open; never for a resend or a route.
    pub(crate) fn take_slot(&mut self, resend: bool, queued_or_none: bool) {
        if self.held_slot.is_some() || resend || !queued_or_none {
            return;
        }
        let Some(mut pool) = self.pool.take() else {
            return;
        };
        let slot =
            pool.take(&mut |current, response| self.settle_launch(&current, &response, false));
        self.pool = Some(pool);
        self.held_slot = Some(slot);
    }

    /// `_pooled(sender, client)`: whether this send goes to the worker taken for it - core's own backend carrying its
    /// marker (one whose send can leave this thread), or a channel that said it may wait beside others.
    pub(crate) fn pooled(&mut self, backend: bool, concurrent: bool, client: Option<&str>) -> bool {
        self.pooling = self.held_slot.is_some()
            && ((backend && client.is_none() && self.backend.worker_send().is_some())
                || (!backend && concurrent));
        self.pooling
    }

    /// `_free_slot()`.
    pub(crate) fn free_slot(&mut self) {
        self.held_slot = None;
        self.pooling = false;
    }

    /// `_settle_launch(current, response)`: what came of a send a worker waited for, on the tick thread and under the
    /// dispatch lock (taken here unless the dispatch taking a slot holds it already), as dispatch settles its own.
    pub(crate) fn settle_launch(
        &mut self,
        current: &Row,
        response: &car_machine::json::Map,
        lock: bool,
    ) {
        let held = self.dispatch_lock.clone();
        let _held = if lock {
            held.as_ref().map(|lock| lock.lock())
        } else {
            None
        };
        if self.after_send(current, response, false).is_err() {
            let thread = crate::py::s(current, "thread_id");
            self.log(Some(&thread), "post_send_bookkeeping_failed", Value::Null);
        }
    }
}
