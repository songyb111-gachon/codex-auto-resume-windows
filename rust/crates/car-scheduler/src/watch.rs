//! The watch, as `engine/reconcile.py` writes it: [`watch`], [`watch_record`], [`guard_queued`], [`withdraw_reason`],
//! [`withdraw`], [`settle`] and [`correlate`], each over the engine's [`Host`].
//!
//! What a record is looked for by is its proof (`Host::proof`): its marker, as it always was - or, for a continuation
//! the edition's plug had sent with no marker (P15), the client id it was queued under. Every look below is made for
//! that one proof, so a marker-free continuation is followed, taken back and settled exactly as one with a marker is,
//! and never sent twice.

use std::time::{Duration, Instant};

use car_machine::domain::states::{may_be_queued, still_followed};
use car_machine::json::{Map, Str, Value};
use car_machine::pyval::{self, Py, truthy};
use car_machine::vocab_gen::domain_public::{
    RELEASABLE_WITHDRAWALS, SESSION_WITHDRAWALS, SUPERSEDE_WITHDRAWALS, UNDETERMINED_WAITS,
};
use car_machine::vocab_gen::domain_states::WATCHED;
use car_policy::classify::gates::was_resent;
use car_policy::classify::value::{get, number, or_zero, text, text_of};

use crate::{Correlate, Host, Row, Withdrawn};

/// `FLAG_WITHDRAW_DELETED` (domain/public.py).
const FLAG_WITHDRAW_DELETED: i64 = 4;

/// What an owned queue item becomes when it was taken back and nothing ran (`SETTLED`).
pub const SETTLED: &[(&str, &str)] = &[
    ("cancel", "cancelled"),
    ("thread_disabled", "cancelled"),
    ("superseded_by_user", "superseded_by_user"),
    ("user_queued_input", "superseded_by_user"),
    ("superseded", "superseded"),
    ("duplicate_owner", "superseded"),
    ("not_loaded", "failed"),
    ("expired", "failed"),
    // Withdrawn by a Pause, but it was already an uncertain submission: final, never released back to waiting. The
    // same for Observe only (v0.6.11).
    ("paused_unknown", "failed"),
    ("observe_only_unknown", "failed"),
];

/// `SETTLED.get(reason, "submission_unknown")`.
pub fn settled(reason: &Value) -> &'static str {
    text(reason)
        .and_then(|reason| SETTLED.iter().find(|(key, _)| *key == reason))
        .map_or("submission_unknown", |(_, state)| state)
}

/// `_UNDETERMINED`: a running turn that has not yet recorded who started it holds back the decision.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Undetermined;

/// What `withdraw_reason` answers: `Ok(None)` leave it queued, `Ok(Some(reason))` take it back, `Err(Undetermined)`.
pub type Reason = Result<Option<String>, Undetermined>;

fn has(group: &[&str], word: &str) -> bool {
    group.contains(&word)
}

fn has_value(group: &[&str], value: &Value) -> bool {
    text(value).is_some_and(|word| has(group, word))
}

fn row_of(pairs: Vec<(&str, Value)>) -> Row {
    let mut row = Row::new();
    for (key, value) in pairs {
        row.insert(Str::from(key), value);
    }
    row
}

fn key_of(row: &Row) -> String {
    text_of(row, "interruption_id")
        .unwrap_or_default()
        .to_owned()
}

fn thread_of(row: &Row) -> String {
    text_of(row, "thread_id").unwrap_or_default().to_owned()
}

/// `int + 1` of a stored count.
fn plus_one(value: &Value) -> Py<Value> {
    match value {
        Value::Int(number) => number
            .as_i64()
            .and_then(|n| n.checked_add(1))
            .map(Value::from)
            .ok_or("OverflowError"),
        Value::Bool(on) => Ok(Value::from(i64::from(*on) + 1)),
        Value::Float(number) => Ok(Value::Float(number + 1.0)),
        _ => Err("TypeError"),
    }
}

/// `watch_needed()`: whether anything may be sitting in Codex's queue right now.
///
/// While that is true the watcher looks every second instead of every poll: the window in which a person can start
/// work ahead of our queued item is seconds long.
pub fn watch_needed<H: Host>(host: &H) -> Py<bool> {
    for row in host.records(WATCHED)? {
        if may_be_queued(get(&row, "state"), get(&row, "queue_id"))? {
            return Ok(true);
        }
    }
    Ok(false)
}

/// `watch()`: one pass over everything that may be in Codex's queue. Runs paused or not.
///
/// A record that owns a row in Codex's queue is looked at on every pass, whatever its schedule says. Everything else
/// that is unresolved is looked at when due. The pass has a time budget, and starts one record further on each time, so
/// one slow delete cannot keep the others waiting pass after pass.
pub fn watch<H: Host>(host: &mut H) -> Py<()> {
    let now = host.clock();
    let mut rows = host.records(WATCHED)?;
    if !rows.is_empty() {
        let offset = host.watch_offset();
        let start = (*offset % rows.len() as u64) as usize;
        rows.rotate_left(start);
        *offset += 1;
    }
    let budget = host.option("watch_budget_seconds");
    let deadline = Instant::now().checked_add(Duration::from_secs_f64(budget.max(0.0)));
    for row in rows {
        if deadline.is_some_and(|deadline| Instant::now() > deadline) {
            break;
        }
        if text_of(&row, "state") == Some("submission_unknown")
            && matches!(get(&row, "queue_id"), Value::Null)
        {
            if or_zero(get(&row, "next_retry_at")) > now {
                continue;
            }
            let window = Value::Float(host.option("unknown_reconcile_window_seconds"));
            if !still_followed(&Value::Object(row.clone()), &Value::Float(now), &window)? {
                continue;
            }
        }
        if host.for_open_rests(&row)? {
            continue;
        }
        let looked = (|| -> Py<()> {
            let lock = host.dispatch_lock();
            let _held = lock.as_ref().map(|lock| lock.lock());
            let current = host.watch_store().get(&key_of(&row))?;
            if let Some(current) = current
                && text_of(&current, "state").is_some_and(|state| has(WATCHED, state))
            {
                watch_record(host, &current)?;
            }
            Ok(())
        })();
        if looked.is_err() {
            host.log(
                Some(&thread_of(&row)),
                "reconciliation_unavailable",
                Value::Null,
            );
        }
    }
    Ok(())
}

/// `watch_record(row)`: follow one continuation that may be in Codex. Never sends anything. Where a plug may ask for a
/// resend, what each look finds is remembered for it (engine/resend.py).
pub fn watch_record<H: Host>(host: &mut H, row: &Row) -> Py<()> {
    let now = host.clock();
    let (thread, marker) = (thread_of(row), host.proof(row));
    let key = key_of(row);
    host.untraced(&key);
    let found = host.watch_source().marker_rows(&thread, &marker)?;
    if found.len() > 1 {
        // Our unique marker in two places cannot be explained by one send, so no turn is picked. Anything still queued
        // is still taken back.
        if text_of(row, "state") != Some("submission_unknown")
            || text_of(row, "last_error") != Some("duplicate_marker")
        {
            host.transition(
                row,
                "submission_unknown",
                Some("duplicate_marker"),
                Some(60.0),
                None,
                Row::new(),
            )?;
        }
        for item in host.watch_source().queued_rows(&thread, &marker)? {
            delete(host, &thread, get(&item, "id"));
        }
        return Ok(());
    }
    if let Some(first) = found.first() {
        return correlate(host, row, first);
    }
    if text_of(row, "state") == Some("withdrawn_unconfirmed") {
        return settle(host, row);
    }
    if truthy(get(row, "queue_id")) {
        let queue_id = text_of(row, "queue_id").ok_or("TypeError")?.to_owned();
        let known = host.watch_source().queue_row(&thread, &queue_id, &marker)?;
        if truthy(get(&known, "exists")) {
            host.sighted(&key);
        }
        if truthy(get(&known, "exists")) && !truthy(get(&known, "has_marker")) {
            // Somebody edited our queued message in Codex. It is theirs now: nothing is deleted and nothing more is
            // sent.
            return host.transition(
                row,
                "handed_over",
                Some("queued_item_edited"),
                None,
                None,
                Row::new(),
            );
        }
    }
    let queued = host.watch_source().queued_rows(&thread, &marker)?;
    if !queued.is_empty() {
        host.sighted(&key);
        return guard_queued(host, row, &queued);
    }
    if text_of(row, "state") == Some("submission_unknown") {
        let extra = if truthy(get(row, "queue_id")) {
            row_of(vec![("queue_id", Value::Null)])
        } else {
            Row::new()
        };
        let last = get(row, "last_error");
        let reason = if truthy(last) {
            text(last).ok_or("TypeError")?.to_owned()
        } else {
            "no_receipt_do_not_resend".to_owned()
        };
        let poll = host.option("conservative_poll_seconds");
        host.transition(
            row,
            "submission_unknown",
            Some(&reason),
            Some(poll),
            None,
            extra,
        )?;
        host.traceless(row, now);
        return Ok(());
    }
    let age = now - submitted_or(row, now)?;
    let state = text_of(row, "state").unwrap_or_default().to_owned();
    if age < host.option("delivery_timeout_seconds") {
        // Between leaving the queue and appearing in history. Waiting is safe.
        host.transition(
            row,
            &state,
            Some("awaiting_delivery_receipt"),
            Some(1.0),
            None,
            Row::new(),
        )
    } else {
        let poll = host.option("conservative_poll_seconds");
        host.transition(
            row,
            "submission_unknown",
            Some("no_receipt_do_not_resend"),
            Some(poll),
            None,
            Row::new(),
        )
    }
}

/// `row.get("submitted_at") or now`.
fn submitted_or(row: &Row, now: f64) -> Py<f64> {
    let submitted = get(row, "submitted_at");
    if truthy(submitted) {
        car_policy::classify::value::arithmetic(submitted).ok_or("TypeError")
    } else {
        Ok(now)
    }
}

/// `guard_queued(row, queued)`: our item is in Codex's queue. Leave it there only while it is still right.
pub fn guard_queued<H: Host>(host: &mut H, row: &Row, queued: &[Map]) -> Py<()> {
    let reason = if queued.len() > 1 {
        Ok(Some("duplicate_owner".to_owned()))
    } else {
        withdraw_reason(host, row)?
    };
    let reason = match reason {
        Err(Undetermined) => return Ok(()),
        Ok(reason) => reason,
    };
    let Some(reason) = reason else {
        let item = &queued[0];
        let mut changes = Row::new();
        if !pyval::eq(get(row, "queue_id"), get(item, "id")) {
            changes.insert(Str::from("queue_id"), get(item, "id").clone());
        }
        if matches!(get(row, "recovery_client_id"), Value::Null) && truthy(get(item, "client_id")) {
            changes.insert(
                Str::from("recovery_client_id"),
                get(item, "client_id").clone(),
            );
        }
        if text_of(row, "state") == Some("submitting") {
            let first = get(row, "first_queued_at");
            let first = if truthy(first) {
                first.clone()
            } else {
                Value::Float(host.clock())
            };
            changes.insert(Str::from("first_queued_at"), first);
            return host.transition(row, "queued", None, Some(1.0), Some("submitted"), changes);
        }
        if !changes.is_empty() {
            let at = host.clock();
            host.watch_store()
                .update(&key_of(row), &changes, Some(at), None, 0)?;
        }
        return Ok(());
    };
    if truthy(get(row, "withdraw_failures")) && or_zero(get(row, "next_retry_at")) > host.clock() {
        return Ok(()); // the last delete failed; the next one is paced
    }
    let ids: Vec<Value> = queued.iter().map(|item| get(item, "id").clone()).collect();
    withdraw(host, row, &ids, &reason)
}

/// `withdraw_reason(row)`: why our queued item must be taken back now, or None to leave it queued.
///
/// Cancel and a disabled thread withdraw it at once; so does any sign that the failure it answers is no longer the
/// thread's latest state, and then Pause. A turn that is running but has not yet recorded who started it holds back
/// only the decisions that depend on that - the supersede and expiry withdrawals - never a cancel or a Pause. A
/// submission already known to be uncertain is still withdrawn by a Pause, under its own reason; Observe only takes it
/// back as a Pause does, under reasons of its own.
pub fn withdraw_reason<H: Host>(host: &mut H, row: &Row) -> Py<Reason> {
    let now = host.clock();
    let (thread, marker) = (thread_of(row), host.proof(row));
    let take = |reason: &str| Ok(Ok(Some(reason.to_owned())));
    if truthy(get(row, "cancel_requested")) {
        return take("cancel");
    }
    if !host.watch_store().thread_enabled(&thread)? {
        return take("thread_disabled");
    }
    // v0.6.16-beta.3: a turn a wrap-up of this product's started is not someone else's (persons_turns).
    let later = host
        .watch_source()
        .later_turns(&thread, get(row, "ordinal"), &marker)?;
    let turns = host.persons_turns(&thread, later);
    let undetermined = turns
        .iter()
        .any(|turn| text_of(turn, "kind") == Some("undetermined"));
    if turns.iter().any(|turn| host.foreign(row, turn)) {
        return take("superseded_by_user");
    }
    if host.watch_source().foreign_queued(&thread, &marker)? != 0 {
        return take("user_queued_input");
    }
    if turns.is_empty() && !host.valid_interruption(row)? {
        return take("superseded");
    }
    let settings = host.watch_store().settings()?;
    let enabled = truthy(get(&settings, "enabled"));
    if !enabled || host.observing(&settings) {
        let reason = if !enabled { "paused" } else { "observe_only" };
        // v0.6.14: or one resent.
        let uncertain = text_of(row, "state") == Some("submission_unknown") || was_resent(row);
        return if uncertain {
            take(&format!("{reason}_unknown"))
        } else {
            take(reason)
        };
    }
    let loaded = host.loaded(&thread)?;
    // v0.6.16-beta.4: or sent to another session.
    if host.for_open(row)? || host.to_session(row) {
        let reason = if host.for_open(row)? {
            host.open_reason(row, &loaded, now)?
        } else {
            host.session_reason(row, &loaded, now)
        };
        if let Some(reason) = reason {
            return Ok(if undetermined && has(UNDETERMINED_WAITS, &reason) {
                Err(Undetermined)
            } else {
                Ok(Some(reason))
            });
        }
    } else if pyval::is(&loaded, "notLoaded") {
        return take("not_loaded");
    } else if now - submitted_or(row, now)? >= host.option("delivery_timeout_seconds") {
        return Ok(if undetermined {
            Err(Undetermined)
        } else {
            Ok(Some("expired".to_owned()))
        });
    }
    if host.projection_fresh(&thread) == Some(false) {
        return take("projection_stale");
    }
    Ok(if undetermined {
        Err(Undetermined)
    } else {
        Ok(None)
    })
}

/// `_delete(thread, queue_id)`: whether the backend said the delete happened (`is True`); a failure is no.
fn delete<H: Host>(host: &mut H, thread: &str, queue_id: &Value) -> bool {
    let Some(queue_id) = text(queue_id) else {
        // Codex's queue ids are text; any other value could not name a row to delete.
        return false;
    };
    matches!(host.delete_queue(thread, queue_id), Ok(Value::Bool(true)))
}

/// `SESSION_WITHDRAWALS.get(reason, reason)`.
fn stored_reason(reason: &str) -> String {
    SESSION_WITHDRAWALS
        .get(reason)
        .and_then(|node| node.as_str())
        .unwrap_or(reason)
        .to_owned()
}

/// `withdraw(row, queue_ids, reason)`: delete our queued item. A successful delete is not proof that it never ran:
/// Codex can report the delete after the turn has already started. The settle that follows decides.
pub fn withdraw<H: Host>(host: &mut H, row: &Row, queue_ids: &[Value], reason: &str) -> Py<()> {
    let (shown, reason) = (reason.to_owned(), stored_reason(reason)); // v0.6.16-beta.4 (tosession.py)
    let now = host.clock();
    let (thread, marker) = (thread_of(row), host.proof(row));
    let key = key_of(row);
    let results: Vec<bool> = queue_ids
        .iter()
        .map(|queue_id| delete(host, &thread, queue_id))
        .collect();
    let told = |reason: &str| {
        let mut told = row.clone();
        told.insert(Str::from("withdraw_reason"), Value::from(reason));
        told
    };
    if !results.is_empty() && results.iter().all(|done| *done) {
        let changes = row_of(vec![
            ("state", Value::from("withdrawn_unconfirmed")),
            ("withdraw_reason", Value::from(reason.as_str())),
            ("withdrawn_at", Value::Float(now)),
            ("withdraw_deleted", Value::Bool(true)),
            ("queue_id", queue_ids[0].clone()),
            ("last_error", Value::from(shown.as_str())),
            ("next_retry_at", Value::Float(now + 1.0)),
        ]);
        host.watch_store().update(
            &key,
            &changes,
            Some(now),
            Some("withdraw"),
            FLAG_WITHDRAW_DELETED,
        )?;
        // P14 is told why (v0.6.15-beta): a tripwire reads not_delivered_on_open there.
        host.moved(&told(&reason), "withdrawn_unconfirmed");
        host.log(
            Some(&thread),
            "withdrawn_unconfirmed",
            Value::from(shown.as_str()),
        );
        return Ok(());
    }
    let remaining = host.watch_source().queued_rows(&thread, &marker)?;
    if !remaining.is_empty() {
        host.sighted(&key);
        let attempts = plus_one(get(row, "withdraw_failures"))?;
        let pace = host.option("delete_retry_seconds");
        let over = number(&attempts).is_some_and(|n| n >= host.option("max_withdraw_attempts"));
        if over && text_of(row, "state") != Some("submission_unknown") {
            // Still watched on every pass while the row exists; only the deletes are paced.
            let extra = row_of(vec![
                ("withdraw_failures", attempts),
                ("queue_id", get(&remaining[0], "id").clone()),
            ]);
            host.transition(
                row,
                "submission_unknown",
                Some("queue_cleanup_unconfirmed"),
                Some(pace),
                None,
                extra,
            )?;
        } else {
            let changes = row_of(vec![
                ("withdraw_failures", attempts),
                ("next_retry_at", Value::Float(now + pace)),
            ]);
            host.watch_store()
                .update(&key, &changes, Some(now), None, 0)?;
        }
        return Ok(());
    }
    // Gone, but not by our hand: dispatched, or removed in Codex.
    let changes = row_of(vec![
        ("state", Value::from("withdrawn_unconfirmed")),
        ("withdraw_reason", Value::from(reason.as_str())),
        ("withdrawn_at", Value::Float(now)),
        ("withdraw_deleted", Value::Bool(false)),
        ("last_error", Value::from(shown.as_str())),
        ("next_retry_at", Value::Float(now + 1.0)),
    ]);
    host.watch_store()
        .update(&key, &changes, Some(now), Some("withdraw"), 0)?;
    host.moved(&told(&reason), "withdrawn_unconfirmed");
    host.log(
        Some(&thread),
        "withdrawn_unconfirmed",
        Value::from(shown.as_str()),
    );
    Ok(())
}

/// `settle(row)`: decide what a withdrawn item became, once it can be decided.
///
/// For the delivery window after the withdrawal the watch keeps looking for our marker. If it appears, the
/// continuation ran after all and is followed like any other. If it never appears and Codex's history is known to be
/// current, nothing ran. If the history cannot be trusted, the record stays unknown - never resent.
pub fn settle<H: Host>(host: &mut H, row: &Row) -> Py<()> {
    let now = host.clock();
    let (thread, marker) = (thread_of(row), host.proof(row));
    let key = key_of(row);
    let queued = host.watch_source().queued_rows(&thread, &marker)?;
    if !queued.is_empty() {
        host.sighted(&key);
        // Back in the queue, or never really gone: take it back again.
        for item in &queued {
            delete(host, &thread, get(item, "id"));
        }
        return Ok(());
    }
    // Looked at on every pass of the window, so a lag anywhere in it is known.
    host.projection_now(&thread);
    let withdrawn_at = number(get(row, "withdrawn_at")).ok_or("TypeError")?;
    if now - withdrawn_at < host.option("delivery_timeout_seconds") {
        return Ok(());
    }
    let fresh = host.fresh_throughout(&thread, withdrawn_at);
    let reason = get(row, "withdraw_reason").clone();
    let poll = host.option("conservative_poll_seconds");
    if !fresh || pyval::is(&reason, "projection_stale") {
        return host.transition(
            row,
            "submission_unknown",
            Some("withdraw_unconfirmed"),
            Some(poll),
            None,
            Row::new(),
        );
    }
    if has_value(RELEASABLE_WITHDRAWALS, &reason) {
        let later = !host
            .watch_source()
            .later_turns(&thread, get(row, "ordinal"), &marker)?
            .is_empty();
        let target = host.waiting_state(row)?;
        let proofs = Withdrawn {
            window: host.option("delivery_timeout_seconds"),
            later_turn: later,
            marker_rows: 0,
            row_present: false,
            fresh,
            target: target.clone(),
            next_retry_at: Some(now),
        };
        if host.watch_store().release_withdrawn(&key, now, &proofs)? {
            host.moved(row, &target);
            host.log(Some(&thread), "released_after_withdrawal", reason);
            return Ok(());
        }
        return host.transition(
            row,
            "submission_unknown",
            Some("withdraw_unconfirmed"),
            Some(poll),
            None,
            Row::new(),
        );
    }
    let target = settled(&reason);
    let why = if pyval::is(&reason, "duplicate_owner") {
        "duplicate_owner"
    } else {
        "owned_queue_removed"
    };
    host.transition(row, target, Some(why), None, None, Row::new())
}

/// `correlate(row, found)`: our marker is in history; record the exact turn it started.
///
/// That turn is the turn of the row holding the marker - never the thread's latest turn, which may already be
/// somebody else's.
pub fn correlate<H: Host>(host: &mut H, row: &Row, found: &Map) -> Py<()> {
    let now = host.clock();
    let thread = thread_of(row);
    let key = key_of(row);
    let ambiguous = |host: &mut H| {
        host.transition(
            row,
            "submission_unknown",
            Some("ambiguous_receipt"),
            Some(900.0),
            None,
            Row::new(),
        )
    };
    let ordinal = get(found, "ordinal");
    if !matches!(ordinal, Value::Null) && pyval::less_or_equal(ordinal, get(row, "ordinal"))? {
        return ambiguous(host);
    }
    let (own, theirs) = (get(row, "recovery_client_id"), get(found, "client_id"));
    if truthy(own) && truthy(theirs) && !pyval::eq(own, theirs) {
        return ambiguous(host);
    }
    if truthy(get(found, "first_unset")) || matches!(get(found, "turn_id"), Value::Null) {
        // Codex has not yet recorded who started that turn. Wait - bounded.
        let submitted = submitted_or(row, now)?;
        if now - submitted > host.option("unknown_reconcile_window_seconds") {
            ambiguous(host)?;
        }
        return Ok(());
    }
    let client = if truthy(theirs) {
        theirs.clone()
    } else {
        own.clone()
    };
    let turn_id = text_of(found, "turn_id").ok_or("TypeError")?.to_owned();
    let status = get(found, "status").clone();
    if !truthy(get(found, "starts_turn")) {
        // Our text landed inside a turn somebody else started. That turn is theirs.
        let options = Correlate {
            client_id: client,
            status,
            state: "handed_over".into(),
            reason: Value::from("marker_not_turn_initiator"),
            user_joined: true,
            ..Correlate::default()
        };
        if host
            .watch_store()
            .correlate(&key, &turn_id, now, &options)?
        {
            host.moved(row, "handed_over");
            host.log(
                Some(&thread),
                "handed_over",
                Value::from("marker_not_turn_initiator"),
            );
            return Ok(());
        }
        return ambiguous(host);
    }
    let proof = host.proof(row);
    let turns = host
        .watch_source()
        .later_turns(&thread, get(row, "ordinal"), &proof)?;
    let mut before_ours = false;
    for turn in &turns {
        if host.foreign(row, turn) && pyval::less(get(turn, "ordinal"), ordinal)? {
            before_ours = true;
            break;
        }
    }
    let withdrawn = text_of(row, "state") == Some("withdrawn_unconfirmed");
    let reason = get(row, "withdraw_reason");
    let after_user = before_ours || has_value(SUPERSEDE_WITHDRAWALS, reason);
    let extra = if withdrawn && has_value(RELEASABLE_WITHDRAWALS, reason) && !host.to_session(row) {
        Some(if pyval::is(reason, "paused") {
            "dispatched_while_paused"
        } else {
            "dispatched_while_observing"
        })
    } else if withdrawn && truthy(get(row, "withdraw_deleted")) {
        Some("dispatched_despite_delete")
    } else if before_ours {
        Some("continuation_after_user_turn")
    } else {
        None
    };
    let options = Correlate {
        client_id: client,
        status,
        after_user_work: after_user,
        extra_event: extra.map(str::to_owned),
        ..Correlate::default()
    };
    if !host
        .watch_store()
        .correlate(&key, &turn_id, now, &options)?
    {
        return ambiguous(host);
    }
    host.moved(row, "turn_started");
    host.log(
        Some(&thread),
        "turn_started",
        extra.map_or(Value::Null, Value::from),
    );
    let detail = row_of(vec![
        ("state", Value::from("turn_started")),
        ("reason", Value::Null),
    ]);
    host.announce("result", row, detail);
    Ok(())
}
