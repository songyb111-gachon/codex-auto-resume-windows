"""The recovery state machine: the states a record may be stored in, and the moves allowed.

A record is in exactly one of these states, and `Store.update` will only move it along an edge
`PLAIN_MOVES` names. Everything a surface shows of a record is derived from one of them
(`domain/public.py`); everything that decides whether one may move is a gate
(`domain/gates.py`).
"""
from __future__ import annotations

import math

from .vocabulary import (Actor, EventCode, GateName, GateResult, Overlay, Page,
                         PublicCode, ReasonCode, RecordState, TurnStatus,
                         WithdrawReason)
from .vocabulary import FailureCategory


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
# Every stored state, each in exactly one of the groups above (tests/test_vocabulary.py).
STATES = frozenset(RecordState)

# The 18 states schema 2 knew, for the downgrade path.
V2_STATES = frozenset({
    "resumed", "cancelled", "superseded", "failed", "submission_unknown",
    "superseded_by_user", "retry_budget_exhausted", "no_progress_exhausted", "terminal_failure",
    "submitting", "queued",
}) | WAITING

# Anything from a claim onwards may have reached Codex. Every gate treats it so.
POSSIBLY_SENT = CLAIMED | IN_FLIGHT | OBSERVING | TERMINAL
# Everything that may be sitting in Codex's queue, or may have just left it: what the watch
# follows. An uncertain submission is followed whether or not it still owns a queue row.
WATCHED = CLAIMED | IN_FLIGHT | frozenset({"submission_unknown"})


def may_be_queued(state, queue_id) -> bool:
    """Whether a record may be sitting in Codex's queue right now: claimed, queued, taken back
    without proof that it never ran, or an uncertain submission that still owns a queue row.

    The store counts these on a conversation before it lets another of its records be
    claimed, and the engine watches every second while any exists. One rule, so a state
    added here is added to both.
    """
    return state in CLAIMED | IN_FLIGHT or (state == "submission_unknown" and queue_id is not None)

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


# Each caller's window of a plausible time, in seconds since 1970. They do not agree, and
# that is kept as it is - known drift, for v0.6.8 to settle: see epoch().
EPOCH_STORE = (0, 253402300799)            # the store: the epoch to the last second of 9999
EPOCH_CODEX = (946684800, 4102444800)      # Codex's history and the registry: 2000 to 2100
EPOCH_USAGE = (1, 4102444800)              # the App Server's usage windows: to 2100


def epoch(value, low, high, *, integer: bool = False, exact: bool = False,
          finite: bool = True) -> bool:
    """Whether `value` is a plausible time: a number of seconds from `low` to `high`, both
    included, so never a NaN or an infinity. A boolean is never a time; `integer` takes
    whole seconds only, and `exact` takes `int` and `float` themselves and no subclass.
    `finite` asks math.isfinite first, as the store, Codex's history and the registry's
    report always have - which raises OverflowError for an int too large to be a float,
    where the window alone would only say no.

    The one reading of a time. Its callers bring their own window and their own strictness,
    because they disagree and unifying them would change what some caller accepts: the store
    takes anything up to the year 9999 and a subclass of int, Codex's history takes 2000 to
    2100 and no subclass, the App Server's usage windows take whole seconds only - so a reset
    Codex reports as 1.7e9 is dropped there and kept by the store. That disagreement is
    recorded as known drift for v0.6.8, not resolved here.
    """
    if type(value) is bool or not isinstance(value, (int, float)):
        return False
    if exact and type(value) not in ((int,) if integer else (int, float)):
        return False
    if integer and not isinstance(value, int):
        return False
    if finite and not math.isfinite(value):
        return False
    return low <= value <= high


def waiting_state(record: dict, now: float) -> str:
    """The wait a record goes back to when it returns to waiting at `now`.

    A usage limit waits for a stored reset that is still ahead, and polls once it has passed
    - from the very moment it is reached; every other failure backs off. The engine sends a
    record back here after a send that never started or a withdrawal, and a restored budget
    comes back here too: one rule, so a change to it cannot leave either on the old one.
    """
    if record.get("category") == FailureCategory.USAGE_LIMIT:
        reset = record.get("reset_at")
        return "waiting_reset" if reset is not None and reset > now else "waiting_poll"
    return "waiting_backoff"


# ---------------------------------------------------------------------------- reasons
