"""The recovery state machine: the stored states, the legal moves between them, and
what each one means to a person.

Everything here is a pure function of values that are already in our own store. No
Codex database is read, no settings file is opened and no clock is consulted, so the
answer a user interface shows for a record is the answer every other interface shows
for the same row.

Three layers, kept apart on purpose:

* **Stored states** are the engine's working vocabulary. They are precise about what
  the engine knows - "a send may be in progress", "the turn is running" - and they are
  the only thing the store validates.
* **Public codes** are what a person is told. They are stable, they never depend on a
  setting, and several stored states can share one.
* **Overlays** are facts about the surroundings - recovery is paused, the watcher is
  not running - that change what a waiting record will do next without changing what
  it is. They never apply to a record that may already have been sent.
"""
from __future__ import annotations

import json

# ----------------------------------------------------------------------- stored states
WAITING = frozenset({
    "waiting_reset", "waiting_poll", "waiting_for_app", "waiting_for_loaded_thread",
    "waiting_for_usage", "waiting_retry", "waiting_backoff",
})
# Claimed: the store has reserved the record and a send may already be under way.
CLAIMED = frozenset({"submitting"})
# Sent into Codex's queue, or taken back out of it without proof that it never ran.
IN_FLIGHT = frozenset({"queued", "withdrawn_unconfirmed"})
# Our continuation started a turn; the engine is watching that exact turn.
OBSERVING = frozenset({"turn_started", "turn_completed"})
# How an observed recovery turn ended.
OUTCOMES = frozenset({
    "recovered", "completed_no_progress", "handed_over", "recovery_turn_failed",
    "stopped_by_user", "outcome_unverified",
})
EXHAUSTED = frozenset({"retry_budget_exhausted", "no_progress_exhausted"})
TERMINAL = frozenset({
    # "resumed" is what v0.5 wrote once the message was delivered. It is kept so old
    # rows stay valid; this version never writes it.
    "resumed",
    "cancelled", "superseded", "superseded_by_user", "failed", "submission_unknown",
    "terminal_failure",
}) | EXHAUSTED | OUTCOMES
STATES = WAITING | CLAIMED | IN_FLIGHT | OBSERVING | TERMINAL

# The 18 states schema 2 knew, for the downgrade path.
V2_STATES = frozenset({
    "resumed", "cancelled", "superseded", "failed", "submission_unknown",
    "superseded_by_user", "retry_budget_exhausted", "no_progress_exhausted", "terminal_failure",
    "submitting", "queued",
}) | WAITING

# Anything from a claim onwards may have reached Codex. Every gate treats it so.
POSSIBLY_SENT = CLAIMED | IN_FLIGHT | OBSERVING | TERMINAL

# Moves a plain `Store.update` may make. Everything else is either a dedicated store
# operation (reserve, release_claim, release_withdrawn, restore_budget and
# cancel_interruption, each of which proves its own precondition) or not allowed.
_TO_STOP = frozenset({
    "superseded", "superseded_by_user", "retry_budget_exhausted", "no_progress_exhausted",
    "terminal_failure",
})
PLAIN_MOVES = {
    **{state: WAITING | _TO_STOP for state in WAITING},
    "submitting": frozenset({
        "submitting", "queued", "withdrawn_unconfirmed", "turn_started", "handed_over",
        "submission_unknown",
        # Only for a send proven never to have started; the store checks the proof.
        "waiting_retry", "failed",
    }),
    "queued": frozenset({
        "queued", "withdrawn_unconfirmed", "turn_started", "handed_over", "submission_unknown",
    }),
    # A hand-over found during the settle goes through Store.correlate, which checks
    # its own preconditions; a plain update cannot make that move.
    "withdrawn_unconfirmed": frozenset({
        "withdrawn_unconfirmed", "turn_started", "cancelled", "superseded",
        "superseded_by_user", "failed", "submission_unknown",
    }),
    "submission_unknown": frozenset({
        "submission_unknown", "queued", "withdrawn_unconfirmed", "turn_started", "handed_over",
    }),
    "turn_started": frozenset({
        "turn_started", "turn_completed", "handed_over", "stopped_by_user", "outcome_unverified",
    }),
    "turn_completed": frozenset({
        "turn_completed", "recovered", "completed_no_progress", "recovery_turn_failed",
        "handed_over", "stopped_by_user", "outcome_unverified",
    }),
}


def plain_move_allowed(old: str, new: str) -> bool:
    """Whether `Store.update` may move a record from `old` to `new`.

    A terminal record may be rewritten in place (its schedule, its reason) but never
    moved; `submission_unknown` is the one stop that can still resolve, because a late
    receipt is information, not a retry.
    """
    if old == new:
        return True
    return new in PLAIN_MOVES.get(old, frozenset())


# ---------------------------------------------------------------------------- reasons
WITHDRAW_REASONS = frozenset({
    "cancel", "paused", "paused_unknown", "thread_disabled", "superseded", "superseded_by_user",
    "user_queued_input", "not_loaded", "expired", "projection_stale", "duplicate_owner",
})
SUPERSEDE_WITHDRAWALS = frozenset({"superseded", "superseded_by_user", "user_queued_input"})
TURN_STATUSES = frozenset({"inProgress", "completed", "failed", "interrupted", "other"})
ACTORS = frozenset({"engine", "gui", "cli", "toast", "mcp"})

# Every reason the engine or the store writes. The journal stores only these; anything
# else is recorded as "other" rather than refused, because a journal entry must never
# be the thing that stops a state change from committing.
REASONS = frozenset({
    # waiting
    "desktop_app_unavailable", "notLoaded", "loaded_state_unknown", "loaded_recheck_failed",
    "usage_unavailable", "usage_unknown", "usage_recheck_failed", "daily_submission_cap",
    "thread_submission_cooldown", "queue_process_not_started", "projection_stale",
    "user_input_queued", "waiting_reset", "other_recovery_in_flight", "released_before_send",
    "released_after_withdrawal", "budget_restored", "retry_now",
    # stops
    "recovery_budget", "no_progress_budget", "chain_cap", "queue_launch_retry_limit",
    "later_turn_exists", "latest_turn_changed", "parent_cancelled", "parent_handed_over",
    "user_cancelled", "usage_never_available", "usage_not_restored_after_reset",
    "duplicate_owner", "category_disabled",
    # sending and receipts
    "awaiting_delivery_receipt", "queue_result_unknown_do_not_resend",
    "no_receipt_do_not_resend", "multiple_matching_queue_items", "queue_cleanup_unconfirmed",
    "withdraw_unconfirmed", "duplicate_marker", "ambiguous_receipt", "queued_item_edited",
    "owned_queue_removed", "turn_without_user_item", "post_send_bookkeeping_failed",
    # outcomes
    "marker_not_turn_initiator", "user_joined", "stale_turn_row", "unknown_turn_status",
    "outcome_deadline", "correlation_conflict", "progress_observed", "no_progress_observed",
    "turn_failed", "turn_interrupted",
}) | WITHDRAW_REASONS

EVENT_CODES = frozenset({
    "detected", "state", "claim", "submitted", "release_claim", "withdraw",
    "release_withdrawn", "correlated", "continuation_after_user_turn",
    "dispatched_despite_delete", "dispatched_while_paused", "cancel", "cancel_requested",
    "reset_budget", "retry_now", "identity_drift", "hidden", "migrated",
    "disabled_threads_with_pending", "thread_enabled", "other",
})
# Bits for `events.flags`. Integers only: nothing a person wrote can be stored here.
FLAG_AFTER_USER_WORK = 1
FLAG_USER_JOINED = 2
FLAG_WITHDRAW_DELETED = 4
FLAG_LEGACY = 8


def event_code(value) -> str:
    return value if isinstance(value, str) and value in EVENT_CODES else "other"


def reason_code(value):
    if value is None:
        return None
    return value if isinstance(value, str) and value in REASONS else "other"


def actor_code(value) -> str:
    return value if isinstance(value, str) and value in ACTORS else "engine"


def turn_status(value) -> str | None:
    if value is None:
        return None
    return value if isinstance(value, str) and value in TURN_STATUSES else "other"


# ------------------------------------------------------------------------ public codes
WAITING_CODES = frozenset({
    "waiting_reset", "waiting_usage", "waiting_thread", "scheduled", "failed_retryable",
})
PUBLIC_CODES = WAITING_CODES | frozenset({
    "submission_claimed", "submitted", "withdrawing", "turn_running", "turn_finishing",
    "recovered", "no_progress", "handed_over", "recovery_failed", "stopped_by_user",
    "outcome_unverified", "delivered_legacy", "cancelled", "superseded", "exhausted",
    "failed_terminal", "submission_unknown",
})
_DIRECT = {
    "waiting_reset": "waiting_reset", "waiting_poll": "waiting_reset",
    "waiting_for_usage": "waiting_usage",
    "waiting_for_app": "waiting_thread", "waiting_for_loaded_thread": "waiting_thread",
    "waiting_backoff": "scheduled",
    "queued": "submitted", "withdrawn_unconfirmed": "withdrawing",
    "turn_started": "turn_running", "turn_completed": "turn_finishing",
    "recovered": "recovered", "completed_no_progress": "no_progress",
    "handed_over": "handed_over", "recovery_turn_failed": "recovery_failed",
    "stopped_by_user": "stopped_by_user", "outcome_unverified": "outcome_unverified",
    "resumed": "delivered_legacy", "cancelled": "cancelled",
    "superseded": "superseded", "superseded_by_user": "superseded",
    "retry_budget_exhausted": "exhausted", "no_progress_exhausted": "exhausted",
    # `failed` is always final. Whether attempts "remain" is a setting, and a setting
    # must never change what an already-stopped record claims to be.
    "failed": "failed_terminal", "terminal_failure": "failed_terminal",
    "submission_unknown": "submission_unknown",
}


def public_code(record: dict) -> str:
    """The one public code for a stored record. Never reads settings."""
    state = record.get("state")
    if state == "waiting_retry":
        return ("failed_retryable" if record.get("last_error") == "queue_process_not_started"
                else "scheduled")
    if state == "submitting":
        if record.get("last_error") == "awaiting_delivery_receipt" or record.get("queue_id"):
            return "submitted"
        return "submission_claimed"
    return _DIRECT.get(state, "outcome_unverified")


def eligible_at(record: dict):
    """When a waiting record is next looked at: its schedule, or a later usage reset."""
    if record.get("state") not in WAITING:
        return None
    return max(record.get("next_retry_at") or 0, record.get("reset_at") or 0) or None


def public_reason(record: dict):
    """The reason shown next to the code. A closed vocabulary; never free text."""
    if record.get("state") == "no_progress_exhausted":
        return "no_progress_budget"
    return reason_code(record.get("last_error"))


# ----------------------------------------------------------------------------- overlays
OVERLAYS = ("cancel_pending", "paused", "thread_disabled", "compatibility_blocked",
            "engine_unavailable", "watcher_not_ticking")


def overlays(record: dict, *, enabled=True, thread_enabled=True, watcher=None) -> list:
    """Circumstances that change what a record will do next, without changing it.

    `cancel_pending` applies to anything still running. The rest apply only to a
    record that has not been sent: telling someone a sent message is "paused" would be
    a promise nothing can keep.
    """
    found = []
    state = record.get("state")
    if record.get("cancel_requested") and state not in TERMINAL:
        found.append("cancel_pending")
    if state not in WAITING:
        return found
    if not enabled:
        found.append("paused")
    if not thread_enabled:
        found.append("thread_disabled")
    watcher = watcher or {}
    if watcher.get("engine_state") == "incompatible":
        found.append("compatibility_blocked")
    if watcher.get("running") is False:
        found.append("engine_unavailable")
    elif watcher.get("running") is True and watcher.get("ticking") is False:
        found.append("watcher_not_ticking")
    return found


def describe(record: dict, **surroundings) -> dict:
    """Everything an interface needs to show one record, as stable machine values."""
    return {
        "code": public_code(record),
        "reason": public_reason(record),
        "eligible_at": eligible_at(record),
        "overlays": overlays(record, **surroundings),
        "terminal": record.get("state") in TERMINAL,
    }


# -------------------------------------------------------------------------------- gates
PASS, WAIT, BLOCK, UNKNOWN = "PASS", "WAIT", "BLOCK", "UNKNOWN"
GATE_RESULTS = frozenset({PASS, WAIT, BLOCK, UNKNOWN})
GATES = (
    "consent", "engine_compatible", "single_owner", "submission_safe", "identity",
    "known_failure", "schedule", "chain_budget", "attempt_budget", "no_progress_budget",
    "thread_available", "no_newer_user_work", "usage",
)
NOT_CHECKED = "not_checked"
GATE_REASONS = REASONS | frozenset({
    NOT_CHECKED, "paused", "thread_disabled", "cancel_requested", "not_due", "possibly_sent",
    "engine_incompatible", "engine_unknown", "projection_table_missing",
    "home_lock_unavailable", "identity_unreadable", "not_recoverable", "usage_available",
    "ok",
})


def gate(result: str, reason: str = "ok") -> tuple:
    return (result, reason if reason in GATE_REASONS else "other")


def gate_consent(enabled, thread_enabled, cancel_requested) -> tuple:
    if not enabled:
        return gate(BLOCK, "paused")
    if not thread_enabled:
        return gate(BLOCK, "thread_disabled")
    if cancel_requested:
        return gate(BLOCK, "cancel_requested")
    return gate(PASS)


def gate_schedule(record, now) -> tuple:
    if (record.get("next_retry_at") or 0) > now:
        return gate(WAIT, "not_due")
    if record.get("reset_at") is not None and record["reset_at"] > now:
        return gate(WAIT, "waiting_reset")
    return gate(PASS)


def gate_submission_safe(record, others_in_flight: int) -> tuple:
    if record.get("submitted_at") is not None or record.get("state") not in WAITING:
        return gate(BLOCK, "possibly_sent")
    if others_in_flight:
        return gate(WAIT, "other_recovery_in_flight")
    return gate(PASS)


def gate_budgets(record, limits: dict, usage_category: bool) -> dict:
    result = {}
    if record.get("chain_continuations", 0) >= limits["max_chain_continuations"]:
        result["chain_budget"] = gate(BLOCK, "chain_cap")
    else:
        result["chain_budget"] = gate(PASS)
    if not usage_category and record.get("recovery_attempts", 0) >= limits["max_recovery_attempts"]:
        result["attempt_budget"] = gate(BLOCK, "recovery_budget")
    else:
        result["attempt_budget"] = gate(PASS)
    if record.get("no_progress_count", 0) >= limits["max_no_progress"]:
        result["no_progress_budget"] = gate(BLOCK, "no_progress_budget")
    else:
        result["no_progress_budget"] = gate(PASS)
    return result


def first_refusal(vector: dict):
    """The first gate, in evaluation order, that does not pass - or None.

    A gate that was never evaluated counts as a refusal: UNKNOWN never passes.
    """
    for name in GATES:
        result = vector.get(name, (UNKNOWN, NOT_CHECKED))
        if result[0] != PASS:
            return name, result
    return None


def encode_gates(vector: dict) -> str:
    """The persisted form. Allowlisted names and codes only, so it is display-safe."""
    clean = {}
    for name in GATES:
        result, reason = vector.get(name, (UNKNOWN, NOT_CHECKED))
        if result not in GATE_RESULTS:
            result = UNKNOWN
        clean[name] = [result, reason if reason in GATE_REASONS else "other"]
    return json.dumps(clean, separators=(",", ":"), sort_keys=True)


def decode_gates(text) -> dict:
    """Read a stored vector back. Anything unexpected becomes UNKNOWN, never an error."""
    try:
        raw = json.loads(text) if isinstance(text, str) and len(text) <= 4000 else {}
    except ValueError:
        raw = {}
    result = {}
    for name in GATES:
        value = raw.get(name) if isinstance(raw, dict) else None
        if (isinstance(value, list) and len(value) == 2 and value[0] in GATE_RESULTS
                and isinstance(value[1], str)):
            result[name] = (value[0], value[1] if value[1] in GATE_REASONS else "other")
        else:
            result[name] = (UNKNOWN, NOT_CHECKED)
    return result
