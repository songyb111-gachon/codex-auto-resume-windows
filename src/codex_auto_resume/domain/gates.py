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
# edition's plug holds nothing, so no standard record is ever stored with it.
HELD = "held"
GATE_REASONS = REASONS | frozenset({
    NOT_CHECKED, "paused", "thread_disabled", "cancel_requested", "not_due", "possibly_sent",
    "engine_incompatible", "engine_unknown", "projection_table_missing",
    "home_lock_unavailable", "identity_unreadable", "not_recoverable", "usage_available",
    "ok", HELD,
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
