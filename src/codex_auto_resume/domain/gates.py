"""The gates a record passes before anything is sent, and the vector they are stored as.

Evaluated in order, and the first that does not pass is the reason shown. The vector is written
down with the record so what was decided can be read back afterwards, and anything unexpected
in a stored one becomes UNKNOWN rather than a pass.
"""
from __future__ import annotations

import json

from .public import REASONS
from .states import WAITING
from .vocabulary import GateName, GateResult


# -------------------------------------------------------------------------------- gates
PASS, WAIT, BLOCK, UNKNOWN = "PASS", "WAIT", "BLOCK", "UNKNOWN"
GATE_RESULTS = frozenset(GateResult)
GATES = tuple(GateName)
NOT_CHECKED = "not_checked"
# v0.6.11: a gate core passed and the edition's plug held (domain/plug.py, HOLD). The standard
# edition's plug holds nothing, so no standard record is ever stored with it. From schema 4 it is
# also the consent gate's word for a record that waits for a person (`interruptions.hold`).
HELD = "held"
# Schema 4 (v0.6.11): a record a person postponed (`interruptions.not_before`), a moment inside the
# quiet hours, and the watcher told to watch and never send (`settings.observe_only`). Each is a
# reason of a gate there already was - consent or schedule - so A8's thirteen gates, and their
# order, are what they were; and each is off at the defaults, where no record has a hold or a
# postponement, no hour is quiet and nothing is only observed.
POSTPONED, QUIET_HOURS, OBSERVE_ONLY = "postponed", "quiet_hours", "observe_only"
GATE_REASONS = REASONS | frozenset({
    NOT_CHECKED, "paused", "thread_disabled", "cancel_requested", "not_due", "possibly_sent",
    "engine_incompatible", "engine_unknown", "projection_table_missing",
    "home_lock_unavailable", "identity_unreadable", "not_recoverable", "usage_available",
    "ok", HELD, POSTPONED, QUIET_HOURS, OBSERVE_ONLY,
})


def gate(result: str, reason: str = "ok") -> tuple:
    return (result, reason if reason in GATE_REASONS else "other")


def gate_consent(enabled, thread_enabled, cancel_requested, *, observe_only=False,
                 hold=None) -> tuple:
    """Whether sending is allowed at all. The schema-4 conditions come after the three there
    always were, so a record they do not touch - every record, at the defaults - gets the answer
    it got before: observe-only blocks like a Pause, and a hold, of any word, waits for a person."""
    if not enabled:
        return gate(BLOCK, "paused")
    if not thread_enabled:
        return gate(BLOCK, "thread_disabled")
    if cancel_requested:
        return gate(BLOCK, "cancel_requested")
    if observe_only:
        return gate(BLOCK, OBSERVE_ONLY)
    if hold is not None:
        return gate(WAIT, HELD)
    return gate(PASS)


def gate_schedule(record, now, *, quiet_until=None) -> tuple:
    """Whether it is time. A postponement (`not_before`) only ever makes a record later, and
    `quiet_until` - the end of the quiet hours `now` falls in, or None outside them - only holds
    a record that is otherwise due; neither is ever set at the defaults."""
    if (record.get("next_retry_at") or 0) > now:
        return gate(WAIT, "not_due")
    if record.get("reset_at") is not None and record["reset_at"] > now:
        return gate(WAIT, "waiting_reset")
    if (record.get("not_before") or 0) > now:
        return gate(WAIT, POSTPONED)
    if quiet_until is not None and quiet_until > now:
        return gate(WAIT, QUIET_HOURS)
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
    return json.dumps(clean, separators=(",", ":"), sort_keys=True, allow_nan=False)


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
