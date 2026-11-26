//! Claiming the right to send, and letting it go again (store/claims.py, and the claim's own checks of
//! store/ledger.py).
//!
//! A claim is the only way into `submitting`, and it re-checks every store-side gate inside the
//! `BEGIN IMMEDIATE` transaction that grants it, so two processes claiming one record at once give one
//! claim: the second waits on the write lock (busy timeout 10 s), then reads the record already
//! `submitting` and is refused `submission_safe`/`possibly_sent`.
//!
//! The edition's plug is one thing the claim knows (`Claim::plugged`, `ledger.null` False) and one it does not: its
//! claim ledger (P11) is NOT PORTED here - no authorizer, no savepoint, no `claim_ledger` asked. A plugged claim is
//! one whose ledger always answers DEFER and never raises: every branch `ledger.null` decides is ported (an early
//! look, a Send now past a gate, a relaxation paid for, a resend granted, each only for what the send `carried`), which
//! is what a scripted plug in the engine's traces can hold. A ledger that holds or fails comes with the advanced plug
//! (S7.2). With `plugged` False the claim is the NULL plug's, the standard edition's.

use std::collections::BTreeSet;

use car_machine::json::Value;
use car_policy::classify::failures::{ADMISSIBLE, reset_verified};
use car_policy::classify::gates::{FORCEABLE, SEND_NOW, own_budget_only};
use car_policy::classify::ladder::{CAPACITY_MAX_SECONDS, EARLY_STATES};
use car_policy::plug::{Guarded, Point};
use rusqlite::Connection;

use crate::errors::{Error, Result};
use crate::journal::{Event, event, finite_value};
use crate::machine::policy::gates::{
    BLOCK, HELD, Limits, PASS, RESEND, Vector, WAIT, counted_from, encode_gates, first_refusal,
    gate, gate_budgets, gate_consent, gate_schedule, gate_submission_safe, resend_candidate,
    was_resent,
};
use crate::machine::policy::{USAGE_LIMIT, is_recoverable};
use crate::machine::vocab::{RELEASABLE_WITHDRAWALS, WAITING, WATCHED};
use crate::machine::{has, ids, may_be_queued, turn_status};
use crate::policy::thread_enabled;
use crate::session::{Store, read_settings};
use crate::validate::{claim_cost, is_usage, now as check_now, uuid, uuid_text, validated_record};
use crate::value::{
    Row, execute, get, int, integer, or, scalar, set, string, text_of, truthy, tuples,
};

/// `reserve_detailed`'s keywords. `plugged` is `not ledger.null` (the plug is not NULL's) and `carried` the points
/// whose answers the send carries, which its ledger pays for; the ledger itself (P11) is not asked here.
#[derive(Clone, Debug, Default)]
pub struct Claim {
    pub plugged: bool,
    pub carried: BTreeSet<Point>,
    pub limits: Option<Limits>,
    pub gates: Option<Vector>,
    pub quiet_until: Option<f64>,
    pub relaxed: Option<String>,
    /// (after, until) seconds from its send: an uncertain submission claimed once more.
    pub resend: Option<(f64, f64)>,
    pub forced: bool,
    /// (claims a day, spacing in seconds).
    pub caps: Option<(f64, f64)>,
}

/// (claimed, refusing gate, reason).
pub type Claimed = (bool, Option<String>, Option<String>);

fn refused(name: &str, reason: &str) -> Claimed {
    (false, Some(name.to_string()), Some(reason.to_string()))
}

/// `correlate`'s keywords.
#[derive(Clone, Debug)]
pub struct Correlate {
    pub client_id: Value,
    pub status: Value,
    pub state: String,
    pub reason: Value,
    pub after_user_work: bool,
    pub user_joined: bool,
    pub extra_event: Option<String>,
}

impl Default for Correlate {
    fn default() -> Self {
        Correlate {
            client_id: Value::Null,
            status: Value::Null,
            state: "turn_started".into(),
            reason: Value::Null,
            after_user_work: false,
            user_joined: false,
            extra_event: None,
        }
    }
}

/// `release_withdrawn`'s proofs.
#[derive(Clone, Debug)]
pub struct Withdrawn {
    pub window: f64,
    pub later_turn: bool,
    pub marker_rows: i64,
    pub row_present: bool,
    pub fresh: bool,
    pub target: String,
    pub next_retry_at: Option<f64>,
}

pub const FLAG_AFTER_USER_WORK: i64 = 1;
pub const FLAG_USER_JOINED: i64 = 2;
pub const FLAG_WITHDRAW_DELETED: i64 = 4;

pub(crate) fn others_in_flight(
    connection: &Connection,
    thread_id: &Value,
    exclude: &str,
) -> Result<i64> {
    let mut count = 0;
    for row in tuples(
        connection,
        "SELECT state, queue_id FROM interruptions WHERE thread_id=? AND interruption_id<>?",
        &[thread_id.clone(), string(exclude)],
    )? {
        if may_be_queued(&row[0], &row[1])? {
            count += 1;
        }
    }
    Ok(count)
}

fn consent(connection: &Connection, settings: &Row, row: &Row) -> Result<(String, String)> {
    let on = |name: &str| matches!(get(settings, name), Value::Bool(true));
    Ok(gate_consent(
        on("enabled"),
        thread_enabled(connection, text_of(row, "thread_id").unwrap_or_default())?,
        truthy(get(row, "cancel_requested")),
        on("observe_only"),
        get(row, "hold"),
    ))
}

/// `_caps_refusal`: the conversation's day and spacing, read inside the claim.
fn caps_refusal(
    connection: &Connection,
    row: &Row,
    now: f64,
    vector: &mut Vector,
    caps: (f64, f64),
    forced: bool,
) -> Result<Option<(String, String)>> {
    let (per_day, cooldown) = caps;
    let thread = get(row, "thread_id").clone();
    let since = Value::Float(now - 86400.0);
    let count = integer(
        connection,
        "SELECT coalesce(sum(max(attempt_count, 1)), 0) FROM interruptions WHERE thread_id=? AND coalesce(submitted_at, last_claim_at)>?",
        &[thread.clone(), since.clone()],
    )?;
    let reason = if count as f64 >= per_day {
        "daily_submission_cap"
    } else {
        let latest = scalar(
            connection,
            "SELECT max(coalesce(submitted_at, last_claim_at)) FROM interruptions WHERE thread_id=? AND coalesce(submitted_at, last_claim_at)>?",
            &[thread, since],
        )?;
        // `forced or latest is None or now - latest >= cooldown` passes: a NaN spacing is never reached, so it refuses.
        let spaced = |latest: f64| {
            matches!(
                (now - latest).partial_cmp(&cooldown),
                Some(std::cmp::Ordering::Greater | std::cmp::Ordering::Equal)
            )
        };
        match finite_value(&latest, None) {
            Some(latest) if !forced && !spaced(latest) => "thread_submission_cooldown",
            _ => return Ok(None),
        }
    };
    vector.set("attempt_budget", gate(WAIT, reason));
    Ok(Some(("attempt_budget".into(), reason.into())))
}

/// `_early_claim`: whether the claim skips a record's next look and its reset time (EARLY): only for one that waits
/// for a usage limit to reset, or for usage, and only as a relaxation the plug's ledger pays for.
fn early_claim(row: &Row, options: &Claim) -> bool {
    options.relaxed.as_deref() == Some("early")
        && text_of(row, "category") == Some(USAGE_LIMIT)
        && has(EARLY_STATES, text_of(row, "state").unwrap_or_default())
        && options.plugged
        && options.carried.contains(&Point::Schedule)
}

/// `_forced_claim`: a person's Send now (SEND_NOW) as the claim takes it, written into `vector`.
fn forced_claim(row: &Row, now: f64, vector: &mut Vector, options: &Claim) {
    let Some(limits) = &options.limits else {
        return;
    };
    if !has(WAITING, text_of(row, "state").unwrap_or_default())
        || !options.plugged
        || !options.carried.contains(&Point::Schedule)
    {
        return;
    }
    if vector
        .get("schedule")
        .is_some_and(|found| has(FORCEABLE, &found.1))
    {
        let again = gate_schedule(row, now, options.quiet_until, false, true);
        vector.set(
            "schedule",
            if again.0 == PASS {
                gate(PASS, SEND_NOW)
            } else {
                again
            },
        );
    }
    if vector
        .get("attempt_budget")
        .is_some_and(|found| found.0 == BLOCK && found.1 == "recovery_budget")
        && own_budget_only(row, limits.managed_max_recovery_attempts)
    {
        vector.set("attempt_budget", gate(PASS, SEND_NOW));
    }
}

/// `reset_refused` (v0.6.22, issue #59): a verified reset's day, claimed only while the recorded reset is behind `now`,
/// the usage gate passed, and the plug's own channel or route carries it.
fn reset_refused(
    row: &Row,
    now: f64,
    vector: &mut Vector,
    options: &Claim,
) -> Option<(String, String)> {
    if options.relaxed.as_deref() != Some("reset") {
        return None;
    }
    let usage_passed = vector.get("usage").is_some_and(|found| found.0 == PASS);
    if reset_verified(row, now)
        && options.plugged
        && options.carried.contains(&Point::Gates)
        && (options.carried.contains(&Point::Sender) || options.carried.contains(&Point::Unloaded))
        && usage_passed
    {
        return None;
    }
    vector.set("submission_safe", gate(WAIT, HELD));
    Some(("submission_safe".into(), HELD.into()))
}

/// `_relaxation_refused`: a kind core recovers passes unless a relaxation was asked for that the plug's ledger does
/// not pay for; a kind it never recovers alone is claimed only as "admitted", with the gates among what is paid for.
fn relaxation_refused(
    connection: &Connection,
    row: &Row,
    now: f64,
    vector: &mut Vector,
    relaxed: Option<&str>,
    options: &Claim,
) -> Result<Option<(String, String)>> {
    let category = text_of(row, "category").unwrap_or_default();
    if is_recoverable(category) {
        if relaxed != Some("capacity") {
            return Ok(reset_refused(row, now, vector, options));
        }
        let origin = scalar(
            connection,
            "SELECT detected_at FROM interruptions WHERE interruption_id=?",
            &[get(row, "chain_origin_id").clone()],
        )?;
        let within = finite_value(&origin, None)
            .is_some_and(|started| now - started < CAPACITY_MAX_SECONDS as f64);
        if category != "server_5xx"
            || !options.plugged
            || !options.carried.contains(&Point::Gates)
            || matches!(origin, Value::Null)
            || !within
        {
            vector.set("chain_budget", gate(BLOCK, "capacity_window"));
            return Ok(Some(("chain_budget".into(), "capacity_window".into())));
        }
        return Ok(None);
    }
    if relaxed != Some("admitted")
        || !has(ADMISSIBLE, category)
        || !options.plugged
        || !options.carried.contains(&Point::Gates)
    {
        vector.set("known_failure", gate(BLOCK, "not_recoverable"));
        return Ok(Some(("known_failure".into(), "not_recoverable".into())));
    }
    Ok(None)
}

impl Store {
    /// `recent_claims(thread_id, since)`: the latest claim of each record, newest first.
    pub fn recent_claims(&self, thread_id: &str, since: f64) -> Result<Vec<Value>> {
        uuid_text(thread_id, "thread_id")?;
        let found = self.read(|connection| {
            Ok(tuples(
                connection,
                "SELECT coalesce(submitted_at, last_claim_at) AS at FROM interruptions WHERE thread_id=? AND coalesce(submitted_at, last_claim_at) > ? ORDER BY at DESC",
                &[string(thread_id), Value::Float(since)],
            )?)
        })?;
        Ok(found
            .into_iter()
            .map(|mut row| row.remove(0))
            .filter(|at| finite_value(at, None).is_some())
            .collect())
    }

    /// `recent_claim_count(thread_id, since)`: a conservative attempt count.
    pub fn recent_claim_count(&self, thread_id: &str, since: f64) -> Result<i64> {
        uuid_text(thread_id, "thread_id")?;
        self.read(|connection| {
            Ok(integer(
                connection,
                "SELECT coalesce(sum(max(attempt_count, 1)), 0) FROM interruptions WHERE thread_id=? AND coalesce(submitted_at, last_claim_at)>?",
                &[string(thread_id), Value::Float(since)],
            )?)
        })
    }

    /// `others_in_flight(thread_id, exclude)`.
    pub fn others_in_flight(&self, thread_id: &str, exclude: &str) -> Result<i64> {
        self.read(|connection| others_in_flight(connection, &string(thread_id), exclude))
    }

    /// `submission_guard(interruption_id)`: final consent, serialized with the queue launch under the write
    /// lock; `launch` runs inside it with whether the launch is permitted.
    pub fn submission_guard<T>(
        &self,
        interruption_id: &str,
        launch: impl FnOnce(bool) -> T,
    ) -> Result<T> {
        self.transaction(|connection| {
            let row = self.row(connection, interruption_id)?;
            let settings = read_settings(connection)?;
            let on = |name: &str| matches!(get(&settings, name), Value::Bool(true));
            let permitted = match &row {
                Some(row) => {
                    text_of(row, "state") == Some("submitting")
                        && !matches!(get(row, "submitted_at"), Value::Null)
                        && matches!(get(row, "queue_id"), Value::Null)
                        && !truthy(get(row, "cancel_requested"))
                        && matches!(get(row, "hold"), Value::Null)
                        && on("enabled")
                        && !on("observe_only")
                        && thread_enabled(
                            connection,
                            text_of(row, "thread_id").unwrap_or_default(),
                        )?
                }
                None => false,
            };
            Ok(launch(permitted))
        })
    }

    /// `reserve(interruption_id, now, ...)`.
    pub fn reserve(&self, interruption_id: &str, now: f64, options: &Claim) -> Result<bool> {
        Ok(self.reserve_detailed(interruption_id, now, options)?.0)
    }

    /// `reserve_detailed(interruption_id, now, ...)`: (claimed, refusing gate, reason). The gate vector is
    /// persisted whether the claim is granted or refused.
    pub fn reserve_detailed(
        &self,
        interruption_id: &str,
        now: f64,
        options: &Claim,
    ) -> Result<Claimed> {
        self.reserve_ledgered(interruption_id, now, options, None)
    }

    /// `reserve_detailed(..., ledger=plug)`: the claim with the plug's ledger asked last (P11, `_ledger_holds`) where
    /// the claim is plugged and every check of core's granted it. With no `ledger` a plugged claim's ledger defers.
    pub fn reserve_ledgered(
        &self,
        interruption_id: &str,
        now: f64,
        options: &Claim,
        ledger: Option<&Guarded>,
    ) -> Result<Claimed> {
        check_now(now)?;
        if options.gates.is_some() && options.limits.is_none() {
            return Err(Error::store(
                "A gate vector needs the budget limits it was evaluated with",
            ));
        }
        self.transaction(|connection| {
            let settings = read_settings(connection)?;
            let Some(row) = self.row(connection, interruption_id)? else {
                return Ok(refused("identity", "unknown_record"));
            };
            if let Some(window) = options.resend {
                return self.resend_claim(connection, &settings, &row, now, options, window, ledger);
            }
            let mut vector = options.gates.clone().unwrap_or_default();
            vector.set("consent", consent(connection, &settings, &row)?);
            let others = others_in_flight(connection, get(&row, "thread_id"), interruption_id)?;
            vector.set("submission_safe", gate_submission_safe(&row, others));
            vector.set(
                "schedule",
                gate_schedule(&row, now, options.quiet_until, early_claim(&row, options), false),
            );
            if let Some(limits) = &options.limits {
                for (name, found) in gate_budgets(&row, limits, is_usage(&row)) {
                    vector.set(name, found);
                }
            }
            if options.forced {
                forced_claim(&row, now, &mut vector, options);
            }
            let mut refusal = ["consent", "submission_safe", "schedule", "chain_budget", "attempt_budget", "no_progress_budget"]
                .iter()
                .find_map(|name| {
                    vector.get(name).filter(|found| found.0 != PASS).map(|found| (name.to_string(), found.1.clone()))
                });
            if let (None, Some(caps)) = (&refusal, options.caps) {
                refusal = caps_refusal(connection, &row, now, &mut vector, caps, options.forced)?;
            }
            if refusal.is_none() {
                refusal = relaxation_refused(
                    connection,
                    &row,
                    now,
                    &mut vector,
                    options.relaxed.as_deref(),
                    options,
                )?;
            }
            if options.gates.is_some() && refusal.is_none() {
                refusal = first_refusal(&vector).map(|(name, found)| (name.to_string(), found.1));
            }
            if refusal.is_none()
                && options.plugged
                && let Some(ledger) = ledger
                && self.ledger_asked(connection, ledger, &row, now, options)?
            {
                // The edition counts a claim of its own on this conversation, and the record waits as behind one of
                // core's.
                vector.set("submission_safe", gate(WAIT, HELD));
                refusal = Some(("submission_safe".into(), HELD.into()));
            }
            let encoded = options.gates.as_ref().map(|_| encode_gates(&vector));
            if let Some((name, reason)) = refusal {
                if let Some(encoded) = &encoded
                    && has(WAITING, text_of(&row, "state").unwrap_or_default())
                {
                    execute(
                        connection,
                        "UPDATE interruptions SET gate_eval=?, gate_eval_at=?, chain_first_detected_at=? WHERE interruption_id=?",
                        &[string(encoded), Value::Float(now), counted_from(&row, now), string(interruption_id)],
                    )?;
                }
                return Ok(refused(&name, &reason));
            }
            execute(
                connection,
                &format!(
                    "UPDATE interruptions SET state='submitting', attempt_count=attempt_count+1, {}, submitted_at=?, last_claim_at=?, last_error=NULL, gate_eval=coalesce(?, gate_eval), gate_eval_at=coalesce(?, gate_eval_at), chain_first_detected_at=? WHERE interruption_id=?",
                    claim_cost(&row, false)
                ),
                &[
                    Value::Float(now),
                    Value::Float(now),
                    crate::value::optional(encoded.as_deref()),
                    if encoded.is_some() { Value::Float(now) } else { Value::Null },
                    counted_from(&row, now),
                    string(interruption_id),
                ],
            )?;
            event(connection, now, "claim", Event {
                record: Some(&row),
                from_state: text_of(&row, "state"),
                to_state: Some("submitting"),
                ..Event::default()
            })?;
            Ok((true, None, None))
        })
    }

    /// `_resend_claim`: an uncertain submission claimed once more, only for a plugged claim that carries the schedule
    /// (the NULL plug's never grants one, and the answer says which check held it).
    fn resend_claim(
        &self,
        connection: &Connection,
        settings: &Row,
        row: &Row,
        now: f64,
        options: &Claim,
        window: (f64, f64),
        ledger: Option<&Guarded>,
    ) -> Result<Claimed> {
        let (Some(gates), Some(limits)) = (&options.gates, &options.limits) else {
            return Ok(refused("submission_safe", "possibly_sent"));
        };
        if !resend_candidate(row, now, window) {
            return Ok(refused("submission_safe", "possibly_sent"));
        }
        let mut vector = gates.clone();
        vector.set("consent", consent(connection, settings, row)?);
        let others = others_in_flight(
            connection,
            get(row, "thread_id"),
            text_of(row, "interruption_id").unwrap_or_default(),
        )?;
        vector.set(
            "submission_safe",
            if others != 0 {
                gate(WAIT, "other_recovery_in_flight")
            } else {
                gate(PASS, RESEND)
            },
        );
        let mut unscheduled = row.clone();
        set(&mut unscheduled, "next_retry_at", Value::Null);
        vector.set(
            "schedule",
            gate_schedule(&unscheduled, now, options.quiet_until, false, false),
        );
        for (name, found) in gate_budgets(row, limits, is_usage(row)) {
            vector.set(name, found);
        }
        let mut refusal = first_refusal(&vector).map(|(name, found)| (name.to_string(), found.1));
        if let (None, Some(caps)) = (&refusal, options.caps) {
            refusal = caps_refusal(connection, row, now, &mut vector, caps, false)?;
        }
        if refusal.is_none() {
            refusal = relaxation_refused(connection, row, now, &mut vector, None, options)?;
        }
        if refusal.is_none()
            && (!options.plugged
                || !options.carried.contains(&Point::Schedule)
                || match ledger {
                    Some(ledger) => self.ledger_asked(connection, ledger, row, now, options)?,
                    None => false,
                })
        {
            refusal = Some(("submission_safe".into(), HELD.into()));
        }
        if let Some((name, reason)) = refusal {
            return Ok(refused(&name, &reason));
        }
        execute(
            connection,
            "UPDATE interruptions SET state='submitting', attempt_count=attempt_count+1, submitted_at=?, last_claim_at=?, last_error=NULL, gate_eval=?, gate_eval_at=? WHERE interruption_id=?",
            &[
                Value::Float(now),
                Value::Float(now),
                string(&encode_gates(&vector)),
                Value::Float(now),
                get(row, "interruption_id").clone(),
            ],
        )?;
        event(
            connection,
            now,
            "claim",
            Event {
                record: Some(row),
                from_state: text_of(row, "state"),
                to_state: Some("submitting"),
                ..Event::default()
            },
        )?;
        Ok((true, None, None))
    }

    /// `_ledger_holds(connection, ledger, row, now, carried)` for a claim of core's own record.
    fn ledger_asked(
        &self,
        connection: &Connection,
        ledger: &Guarded,
        row: &Row,
        now: f64,
        options: &Claim,
    ) -> Result<bool> {
        let carried: Vec<Point> = options.carried.iter().copied().collect();
        crate::ledger::ledger_holds(
            connection,
            ledger,
            self.links.as_ref(),
            &Value::Object(row.clone()),
            now,
            &carried,
        )
    }

    /// `record_gates(interruption_id, gates, now)`: a due, unclaimable record's vector, its last wait ended.
    pub fn record_gates(&self, interruption_id: &str, gates: &Vector, now: f64) -> Result<()> {
        check_now(now)?;
        let encoded = encode_gates(gates);
        self.transaction(|connection| {
            let Some(row) = self.row(connection, interruption_id)? else { return Ok(()) };
            if !has(WAITING, text_of(&row, "state").unwrap_or_default()) {
                return Ok(());
            }
            execute(
                connection,
                "UPDATE interruptions SET gate_eval=?, gate_eval_at=?, chain_first_detected_at=? WHERE interruption_id=?",
                &[string(&encoded), Value::Float(now), counted_from(&row, now), string(interruption_id)],
            )?;
            Ok(())
        })
    }

    /// `record_would_send(interruption_id, gates, now, next_retry_at)`: Observe only's parked record; whether
    /// it was journaled.
    pub fn record_would_send(
        &self,
        interruption_id: &str,
        gates: &Vector,
        now: f64,
        next_retry_at: f64,
    ) -> Result<bool> {
        check_now(now)?;
        crate::validate::timestamp(&Value::Float(next_retry_at), "next_retry_at", false)?;
        let encoded = encode_gates(gates);
        self.transaction(|connection| {
            let Some(row) = self.row(connection, interruption_id)? else { return Ok(false) };
            if !has(WAITING, text_of(&row, "state").unwrap_or_default()) || !matches!(get(&row, "submitted_at"), Value::Null) {
                return Ok(false);
            }
            let fresh = crate::value::text(get(&row, "gate_eval")) != Some(encoded.as_str());
            execute(
                connection,
                "UPDATE interruptions SET gate_eval=?, gate_eval_at=?, next_retry_at=?, chain_first_detected_at=? WHERE interruption_id=?",
                &[string(&encoded), Value::Float(now), Value::Float(next_retry_at), counted_from(&row, now), string(interruption_id)],
            )?;
            if fresh {
                let state = text_of(&row, "state");
                event(connection, now, "would_send", Event {
                    record: Some(&row),
                    from_state: state,
                    to_state: state,
                    value: Some(now),
                    ..Event::default()
                })?;
            }
            Ok(fresh)
        })
    }

    /// `release_claim(interruption_id, target, reason, now, next_retry_at=None, actor="engine")`: undo a claim
    /// whose send never started.
    pub fn release_claim(
        &self,
        interruption_id: &str,
        target: &str,
        reason: &str,
        now: f64,
        next_retry_at: Option<f64>,
        actor: &str,
    ) -> Result<bool> {
        check_now(now)?;
        if !(has(WAITING, target)
            || matches!(target, "cancelled" | "superseded" | "superseded_by_user"))
        {
            return Err(Error::store("Invalid release target"));
        }
        self.transaction(|connection| {
            let Some(row) = self.row(connection, interruption_id)? else { return Ok(false) };
            if text_of(&row, "state") != Some("submitting")
                || !matches!(get(&row, "queue_id"), Value::Null)
                || matches!(get(&row, "submitted_at"), Value::Null)
                || was_resent(&row)
            {
                return Ok(false);
            }
            execute(
                connection,
                &format!(
                    "UPDATE interruptions SET state=?, submitted_at=NULL, last_error=?, next_retry_at=?, {}, cancel_requested=CASE WHEN ?='cancelled' THEN 1 ELSE cancel_requested END, outcome_at=coalesce(?, outcome_at) WHERE interruption_id=?",
                    claim_cost(&row, true)
                ),
                &[
                    string(target),
                    string(reason),
                    Value::Float(next_retry_at.unwrap_or(now)),
                    string(target),
                    if has(WAITING, target) { Value::Null } else { Value::Float(now) },
                    string(interruption_id),
                ],
            )?;
            event(connection, now, "release_claim", Event {
                record: Some(&row),
                from_state: Some("submitting"),
                to_state: Some(target),
                reason: string(reason),
                actor,
                ..Event::default()
            })?;
            Ok(true)
        })
    }

    /// `correlate(interruption_id, recovery_turn_id, now, ...)`: the exact Codex turn our continuation
    /// started, written once; a turn another record owns is refused (False).
    pub fn correlate(
        &self,
        interruption_id: &str,
        recovery_turn_id: &str,
        now: f64,
        options: &Correlate,
    ) -> Result<bool> {
        check_now(now)?;
        uuid(&string(recovery_turn_id), "recovery_turn_id")?;
        if !matches!(options.state.as_str(), "turn_started" | "handed_over") {
            return Err(Error::store("Invalid correlation state"));
        }
        let client = if ids::is_client_id(&options.client_id) {
            options.client_id.clone()
        } else {
            Value::Null
        };
        self.transaction(|connection| {
            let Some(row) = self.row(connection, interruption_id)? else { return Ok(false) };
            if !has(WATCHED, text_of(&row, "state").unwrap_or_default()) {
                return Ok(false);
            }
            let turn = get(&row, "recovery_turn_id");
            if !matches!(turn, Value::Null) && crate::value::text(turn) != Some(recovery_turn_id) {
                return Ok(false);
            }
            let mut updated = row.clone();
            let handed = options.state == "handed_over";
            set(&mut updated, "state", string(&options.state));
            set(&mut updated, "recovery_turn_id", string(recovery_turn_id));
            set(&mut updated, "recovery_client_id", client.clone());
            set(&mut updated, "recovery_turn_status", crate::value::optional(turn_status(&options.status).as_deref()));
            set(&mut updated, "resumed_at", Value::Float(now));
            set(&mut updated, "turn_started_at", Value::Float(now));
            set(&mut updated, "last_error", options.reason.clone());
            set(&mut updated, "first_queued_at", or(get(&row, "first_queued_at"), get(&row, "submitted_at")));
            set(&mut updated, "after_user_work", Value::Bool(truthy(get(&row, "after_user_work")) || options.after_user_work));
            set(&mut updated, "user_joined", Value::Bool(truthy(get(&row, "user_joined")) || options.user_joined));
            set(&mut updated, "outcome_at", if handed { Value::Float(now) } else { Value::Null });
            let updated = validated_record(updated)?;
            let after = truthy(get(&updated, "after_user_work"));
            let joined = truthy(get(&updated, "user_joined"));
            let written = execute(
                connection,
                "UPDATE interruptions SET state=?, recovery_turn_id=?, recovery_client_id=?, recovery_turn_status=?, resumed_at=?, turn_started_at=?, last_error=?, first_queued_at=?, after_user_work=?, user_joined=?, outcome_at=? WHERE interruption_id=?",
                &[
                    get(&updated, "state").clone(),
                    string(recovery_turn_id),
                    client.clone(),
                    get(&updated, "recovery_turn_status").clone(),
                    Value::Float(now),
                    Value::Float(now),
                    options.reason.clone(),
                    get(&updated, "first_queued_at").clone(),
                    int(i64::from(after)),
                    int(i64::from(joined)),
                    get(&updated, "outcome_at").clone(),
                    string(interruption_id),
                ],
            );
            if let Err(error) = written {
                let error = Error::from(error);
                if error.is_integrity() {
                    return Ok(false);
                }
                return Err(error);
            }
            let flags = (if after { FLAG_AFTER_USER_WORK } else { 0 }) | (if joined { FLAG_USER_JOINED } else { 0 });
            event(connection, now, "correlated", Event {
                record: Some(&updated),
                from_state: text_of(&row, "state"),
                to_state: Some(&options.state),
                reason: options.reason.clone(),
                turn_ref: Some("recovery"),
                flags,
                ..Event::default()
            })?;
            if let Some(extra) = options.extra_event.as_deref().filter(|extra| !extra.is_empty()) {
                event(connection, now, extra, Event {
                    record: Some(&updated),
                    turn_ref: Some("recovery"),
                    flags,
                    ..Event::default()
                })?;
            }
            Ok(true)
        })
    }

    /// `release_withdrawn(interruption_id, now, ...)`: a continuation withdrawn for a Pause or Observe only
    /// back to waiting, every proof re-checked here.
    pub fn release_withdrawn(
        &self,
        interruption_id: &str,
        now: f64,
        proofs: &Withdrawn,
    ) -> Result<bool> {
        check_now(now)?;
        if !has(WAITING, &proofs.target) {
            return Err(Error::store("Invalid release target"));
        }
        self.transaction(|connection| {
            let Some(row) = self.row(connection, interruption_id)? else { return Ok(false) };
            let withdrawn_at = crate::value::number(get(&row, "withdrawn_at")).unwrap_or(f64::INFINITY);
            if text_of(&row, "state") != Some("withdrawn_unconfirmed")
                || !text_of(&row, "withdraw_reason").is_some_and(|reason| has(RELEASABLE_WITHDRAWALS, reason))
                || !truthy(get(&row, "withdraw_deleted"))
                || now - withdrawn_at < proofs.window
                || proofs.later_turn
                || proofs.marker_rows != 0
                || proofs.row_present
                || !proofs.fresh
                || truthy(get(&row, "cancel_requested"))
                || was_resent(&row)
            {
                return Ok(false);
            }
            execute(
                connection,
                &format!(
                    "UPDATE interruptions SET state=?, submitted_at=NULL, queue_id=NULL, withdraw_reason=NULL, withdrawn_at=NULL, withdraw_deleted=0, withdraw_failures=0, last_error='released_after_withdrawal', next_retry_at=?, {} WHERE interruption_id=?",
                    claim_cost(&row, true)
                ),
                &[string(&proofs.target), Value::Float(proofs.next_retry_at.unwrap_or(now)), string(interruption_id)],
            )?;
            event(connection, now, "release_withdrawn", Event {
                record: Some(&row),
                from_state: Some("withdrawn_unconfirmed"),
                to_state: Some(&proofs.target),
                reason: get(&row, "withdraw_reason").clone(),
                flags: FLAG_WITHDRAW_DELETED,
                ..Event::default()
            })?;
            Ok(true)
        })
    }
}
