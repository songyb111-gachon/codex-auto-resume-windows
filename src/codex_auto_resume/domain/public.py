"""One record, as every interface shows it: one code, one reason, and what is on top of it.

A closed vocabulary throughout. A surface never reads a stored state, a category or a gate
vector directly - it reads `describe`, and what it may then show is the list of values these
names are drawn from, which is why nothing here reads settings or the clock.
"""
from __future__ import annotations

from .vocabulary import (Actor, EventCode, GateName, GateResult, HoldKind, ImportanceTier,
                         Overlay, Page, PublicCode, ReasonCode, RecordState, TurnStatus,
                         WithdrawReason)
from .states import CLAIMED, IN_FLIGHT, OBSERVING, TERMINAL, WAITING, waiting_state


# ---------------------------------------------------------------------------- reasons
WITHDRAW_REASONS = frozenset(WithdrawReason)
SUPERSEDE_WITHDRAWALS = frozenset({"superseded", "superseded_by_user", "user_queued_input"})
TURN_STATUSES = frozenset(TurnStatus)
ACTORS = frozenset(Actor)
# Schema 4 (v0.6.11). Why a record waits for a person (`interruptions.hold`), and how much a
# conversation asks first (`threads.tier`). Neither is ever set at the defaults: a record with no
# hold and a conversation with no tier are what every record and conversation were until then.
HOLDS = frozenset(HoldKind)
IMPORTANCE_TIERS = tuple(ImportanceTier)
# The hold each tier puts on an interruption of its conversation: Ask me first waits for a person to
# let it continue, and Only notify me as well. Resume automatically and the objection window hold
# nothing - the window is a time (`not_before`), not a person.
_TIER_HOLDS = {ImportanceTier.ASK_FIRST: HoldKind.ASK, ImportanceTier.NOTIFY_ONLY: HoldKind.NOTIFY_ONLY}


def hold_for_tier(tier):
    """The hold `tier` puts on an interruption, or None: every tier but the two that ask a person."""
    return _TIER_HOLDS.get(tier) if isinstance(tier, str) else None

# Every reason the engine or the store writes. The journal stores only these; anything
# else is recorded as "other" rather than refused, because a journal entry must never
# be the thing that stops a state change from committing.
REASONS = frozenset(ReasonCode)

EVENT_CODES = frozenset(EventCode)
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
PUBLIC_CODES = frozenset(PublicCode)
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
    """When a waiting record is next looked at: its schedule, or a later usage reset, or a
    later time a person postponed it to (`not_before`, schema 4), whichever is last.

    None for a record held for a person (`hold`, schema 4) as for one that is not waiting: no
    time will send it, only a person letting it continue, so no surface may say its time has
    come or that it is being checked (J7)."""
    if record.get("state") not in WAITING or record.get("hold") is not None:
        return None
    return max(record.get("next_retry_at") or 0, record.get("reset_at") or 0,
               record.get("not_before") or 0) or None


def public_reason(record: dict):
    """The reason shown next to the code. A closed vocabulary; never free text."""
    if record.get("state") == "no_progress_exhausted":
        return "no_progress_budget"
    return reason_code(record.get("last_error"))


# The settings window's pages, in the order it shows them: the ones a notification's button
# or the icon may open it on. A closed list, because the page is spliced into a command line -
# nothing else may ever reach it, whatever a caller passes.
PAGES = tuple(Page)


# ----------------------------------------------------------------------------- overlays
OVERLAYS = tuple(Overlay)


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
    # v0.6.11: it waits for a person (schema 4's hold) - its conversation asks first or only
    # notifies - and nothing is sent for it until one lets it continue. Read from the record, as
    # the two above are read from the switches: never from a setting or the clock.
    if record.get("hold") is not None:
        found.append("held")
    watcher = watcher or {}
    if watcher.get("engine_state") == "incompatible":
        found.append("compatibility_blocked")
    elif watcher.get("engine_state") == "failed_here":
        # The data vouches for this Codex version and a check here failed: this computer, not the version.
        found.append("compatibility_failed_here")
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
