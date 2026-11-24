//! `domain/states.py`: the recovery state machine, the states a record may be stored in and the moves allowed.
//!
//! The groups of states (`WAITING`, `CLAIMED`, ...) and `PLAIN_MOVES` are generated into
//! [`crate::vocab_gen::domain_states`] from the tag; the functions here read them.

use crate::json::Value;
use crate::pyval::{self, Num, Py, compare, get, in_set, is, minus, truthy};
use crate::vocab_gen::domain_states as table;
use crate::vocab_gen::domain_vocabulary::FailureCategory;

/// A Windows start this many seconds after a turn was seen starting ended it.
pub const BOOT_MARGIN: f64 = 5.0;

/// Each caller's window of a plausible time, in seconds since 1970 (low, high). They do not agree, and that is
/// kept as it is.
pub const EPOCH_STORE: (i64, i64) = (0, 253_402_300_799);
pub const EPOCH_CODEX: (i64, i64) = (946_684_800, 4_102_444_800);
pub const EPOCH_USAGE: (i64, i64) = (1, 4_102_444_800);

fn union(groups: &[&[&str]], state: &Value) -> Py<bool> {
    pyval::hashable(state)?;
    Ok(groups
        .iter()
        .any(|group| in_set(state, group).unwrap_or(false)))
}

/// `may_be_queued(state, queue_id)`: claimed, queued, taken back without proof, or an uncertain submission that
/// still owns a queue row.
pub fn may_be_queued(state: &Value, queue_id: &Value) -> Py<bool> {
    Ok(union(&[table::CLAIMED, table::IN_FLIGHT], state)?
        || (is(state, "submission_unknown") && !matches!(queue_id, Value::Null)))
}

/// `still_followed(row, now, window)`: whether an uncertain submission is still followed at `now`.
pub fn still_followed(row: &Value, now: &Value, window: &Value) -> Py<bool> {
    if !is(get(row, "state")?, "submission_unknown") {
        return Ok(false);
    }
    if !matches!(get(row, "queue_id")?, Value::Null) {
        return Ok(true);
    }
    let submitted = get(row, "submitted_at")?;
    let detected = get(row, "detected_at")?;
    let sent = if truthy(submitted) {
        submitted
    } else if truthy(detected) {
        detected
    } else {
        now
    };
    let elapsed = minus(now, sent)?;
    let limit = Num::of(window).ok_or("TypeError")?.as_f64();
    Ok(elapsed <= limit)
}

/// `plain_move_allowed(old, new)`: whether `Store.update` may move a record from `old` to `new`.
pub fn plain_move_allowed(old: &Value, new: &Value) -> Py<bool> {
    if pyval::eq(old, new) {
        return Ok(true);
    }
    pyval::hashable(old)?;
    pyval::hashable(new)?;
    let Some(from) = pyval::text(old) else {
        return Ok(false);
    };
    let Some(to) = pyval::text(new) else {
        return Ok(false);
    };
    Ok(table::PLAIN_MOVES
        .get(from)
        .is_some_and(|moves| moves.items().iter().any(|each| each.as_str() == Some(to))))
}

/// `epoch(value, low, high, integer=, exact=, finite=)`: whether `value` is a plausible time. A boolean is never a
/// time; `finite` asks `math.isfinite` first, which raises OverflowError for an int too large to be a float.
pub fn epoch(value: &Value, low: i64, high: i64, integer: bool, finite: bool) -> Py<bool> {
    if !matches!(value, Value::Int(_) | Value::Float(_)) {
        return Ok(false);
    }
    if integer && !matches!(value, Value::Int(_)) {
        return Ok(false);
    }
    if finite && !pyval::is_finite(value)? {
        return Ok(false);
    }
    let number = Num::of(value).ok_or("TypeError")?;
    let inside = compare(Num::Whole(low as i128), number).is_some_and(|order| order.is_le())
        && compare(number, Num::Whole(high as i128)).is_some_and(|order| order.is_le());
    Ok(inside)
}

/// `waiting_state(record, now)`: the wait a record goes back to when it returns to waiting at `now`.
pub fn waiting_state(record: &Value, now: &Value) -> Py<&'static str> {
    if is(
        get(record, "category")?,
        FailureCategory::UsageLimit.as_str(),
    ) {
        let reset = get(record, "reset_at")?;
        let ahead = !matches!(reset, Value::Null) && pyval::greater(reset, now)?;
        return Ok(if ahead {
            "waiting_reset"
        } else {
            "waiting_poll"
        });
    }
    Ok("waiting_backoff")
}

/// `ended_by_boot(started, booted)`: whether Windows started after a turn began, by more than `BOOT_MARGIN`.
pub fn ended_by_boot(started: &Value, booted: &Value) -> Py<bool> {
    let (low, high) = EPOCH_STORE;
    if !epoch(started, low, high, false, true)? || !epoch(booted, low, high, false, true)? {
        return Ok(false);
    }
    let started = Num::of(started).ok_or("TypeError")?.as_f64();
    let booted = Num::of(booted).ok_or("TypeError")?.as_f64();
    Ok(booted > started + BOOT_MARGIN)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::json::from_str;

    fn v(text: &str) -> Value {
        from_str(text).unwrap()
    }

    #[test]
    fn moves_and_queues() {
        assert!(plain_move_allowed(&v("\"queued\""), &v("\"turn_started\"")).unwrap());
        assert!(!plain_move_allowed(&v("\"failed\""), &v("\"queued\"")).unwrap());
        assert!(may_be_queued(&v("\"submitting\""), &Value::Null).unwrap());
        assert!(!may_be_queued(&v("\"submission_unknown\""), &Value::Null).unwrap());
        assert!(may_be_queued(&v("[]"), &Value::Null).is_err());
    }

    #[test]
    fn epochs() {
        let (low, high) = EPOCH_CODEX;
        assert!(epoch(&v("1700000000"), low, high, false, true).unwrap());
        assert!(!epoch(&v("true"), low, high, false, true).unwrap());
        assert!(epoch(&v("1e999"), low, high, false, true).is_ok());
        let huge = "9".repeat(400);
        assert_eq!(
            epoch(&v(&huge), low, high, false, true),
            Err("OverflowError")
        );
        assert_eq!(epoch(&v(&huge), low, high, false, false), Ok(false));
    }
}
