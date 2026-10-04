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
# v0.6.11 stage 3a: a gate core would have waited at, passed because the edition's plug named a
# route core carries out itself instead (domain/plug.py, P16) - thread_available, for a
# conversation the app does not hold. The standard edition's plug names no route, so no standard
# record is ever stored with it.
PLUGGED = "plugged"
# Schema 4 (v0.6.11): a record a person postponed (`interruptions.not_before`), a moment inside the
# quiet hours, and the watcher told to watch and never send (`settings.observe_only`). Each is a
# reason of a gate there already was - consent or schedule - so A8's thirteen gates, and their
# order, are what they were; and each is off at the defaults, where no record has a hold or a
# postponement, no hour is quiet and nothing is only observed.
POSTPONED, QUIET_HOURS, OBSERVE_ONLY = "postponed", "quiet_hours", "observe_only"
GATE_REASONS = REASONS | frozenset({
    NOT_CHECKED, "paused", "thread_disabled", "cancel_requested", "not_due", "possibly_sent",
    "engine_incompatible", "engine_unknown", "projection_table_missing",
    "home_lock_unavailable", "identity_unreadable", "usage_available",
    "ok", HELD, POSTPONED, QUIET_HOURS, OBSERVE_ONLY, PLUGGED,
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


def gate_schedule(record, now, *, quiet_until=None, early=False) -> tuple:
    """Whether it is time. A postponement (`not_before`) only ever makes a record later, and
    `quiet_until` - the end of the quiet hours `now` falls in, or None outside them - only holds
    a record that is otherwise due; neither is ever set at the defaults. `early` (v0.6.13, a
    usage-limited record the edition's plug looks at early) skips its next look and its reset
    time, and nothing else."""
    if not early and (record.get("next_retry_at") or 0) > now:
        return gate(WAIT, "not_due")
    if not early and record.get("reset_at") is not None and record["reset_at"] > now:
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


def chain_span(record) -> float:
    """How long a task has kept failing: from its first failure to this, its latest one, less the
    time it waited aside (`waited_aside`) - for a person, a postponement or an objection window,
    quiet hours, the app. The store moves the start of that time (`chain_first_detected_at`) later
    by each such wait as it ends, and a record of the chain begun after it inherits the moved start,
    so no wait aside is ever in it (v0.6.11, ladder.py). The retry waits themselves - the ladder's,
    and the engine's floor between two continuations - are what failing again and again is made
    of, and count."""
    span = (record.get("detected_at") or 0) - (record.get("chain_first_detected_at") or 0)
    return span if span > 0 else 0.0


# What a due record waits for that is its retries' own pacing rather than a wait aside: its schedule
# (a retry's wait, a usage reset) and the engine's floor for one conversation (A20).
_PACING = frozenset({("schedule", "not_due"), ("schedule", "waiting_reset"),
                     ("attempt_budget", "daily_submission_cap"),
                     ("attempt_budget", "thread_submission_cooldown")})


def waited_aside(vector) -> bool:
    """Whether a record the stored `vector` held back was waiting aside (v0.6.11): for anything but
    its retries' own pacing (_PACING) - a person (a Pause, a conversation off, a cancel, a hold,
    Observe only), a postponement or an objection window, quiet hours, the app or Codex, another
    recovery, a person's own queued input, usage, a plug's hold. A budget spent stops the record and
    is none. A time ceiling never counts a wait aside (chain_span). A gate never evaluated says
    nothing, and neither does an empty vector."""
    for name in GATES:
        result, reason = (vector or {}).get(name, (UNKNOWN, NOT_CHECKED))
        if result == PASS or reason == NOT_CHECKED or (name, reason) in _PACING:
            continue
        if result == BLOCK and name in ("chain_budget", "attempt_budget", "no_progress_budget"):
            continue
        return True
    return False


def counted_from(row, now) -> float:
    """Where a waiting record's chain's counted time starts once `now` ends what its stored vector
    said it waited for (v0.6.11): later by that wait, when it was one aside (waited_aside), which a
    time ceiling never counts - and the start the record already had otherwise. The store writes it
    with every new vector and with the claim, so each wait aside is taken off once, and a record of
    the chain begun after this one inherits the start (chain_span)."""
    start, at = row["chain_first_detected_at"], row["gate_eval_at"]
    if at is None or now <= at or not waited_aside(decode_gates(row["gate_eval"])):
        return start
    return start + (now - at)


def over_ceiling(record, limits: dict, usage_category: bool) -> bool:
    """Whether a temporary task has kept failing past its time ceiling (`max_chain_seconds`, absent
    at the defaults). A usage limit waits for its reset and has none."""
    ceiling = limits.get("max_chain_seconds")
    return not usage_category and ceiling is not None and chain_span(record) >= ceiling


# What a record of a task takes from the record whose own continuation started the turn that failed.
CHAIN_FIELDS = ("chain_origin_id", "chain_first_detected_at", "chain_continuations",
                "recovery_attempts", "usage_unavailable_seconds", "budget_resets")


def inherited(parent, failed_turn_progress, legacy_carry=None) -> dict:
    """The counters a new record of a task starts with: its parent's, and one more turn with no
    progress unless the turn that failed made some - or, with no parent, the v0.5 carry of a
    predecessor from before chains existed, if there is one."""
    if parent is None:
        carry = legacy_carry
        good = isinstance(carry, int) and not isinstance(carry, bool) and carry > 0
        return {"no_progress_count": carry} if good else {}
    found = {field: parent[field] for field in CHAIN_FIELDS}
    found["parent_interruption_id"] = parent["interruption_id"]
    found["no_progress_count"] = parent["no_progress_count"] + (0 if failed_turn_progress is True else 1)
    return found


def birth_stop(parent, failed_turn_progress, limits, usage_category: bool, *, now, legacy_carry=None):
    """(state, reason) a new record of a task is born stopped in, or None: its parent was cancelled
    or handed over, or a budget is spent (`limits`, None to check none). The store decides it in the
    transaction that registers the record (store/records.py); the engine asks it beforehand only to
    leave alone what it would not take up (v0.6.13, engine/detect.py)."""
    if parent is not None and parent["cancel_requested"]:
        return "cancelled", "parent_cancelled"
    if parent is not None and (parent["user_joined"] or parent["after_user_work"]
                               or parent["state"] in ("handed_over", "stopped_by_user")):
        return "superseded", "parent_handed_over"
    if limits is None:
        return None
    row = {"detected_at": now, "chain_first_detected_at": now, "chain_continuations": 0,
           "recovery_attempts": 0, "no_progress_count": 0,
           **inherited(parent, failed_turn_progress, legacy_carry)}
    if row["no_progress_count"] >= limits["max_no_progress"]:
        return "no_progress_exhausted", "no_progress_budget"
    if row["chain_continuations"] >= limits["max_chain_continuations"]:
        return "retry_budget_exhausted", "chain_cap"
    if over_ceiling(row, limits, usage_category):
        # v0.6.11: a temporary task that kept failing past its time ceiling (absent at the
        # defaults), measured from its first failure to this one.
        return "retry_budget_exhausted", "chain_time_cap"
    if not usage_category and row["recovery_attempts"] >= limits["max_recovery_attempts"]:
        return "retry_budget_exhausted", "recovery_budget"
    return None


def gate_budgets(record, limits: dict, usage_category: bool) -> dict:
    result = {}
    if record.get("chain_continuations", 0) >= limits["max_chain_continuations"]:
        result["chain_budget"] = gate(BLOCK, "chain_cap")
    elif over_ceiling(record, limits, usage_category):
        result["chain_budget"] = gate(BLOCK, "chain_time_cap")
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


def would_send_at(record: dict):
    """Observe only (v0.6.11): when a waiting record last passed every gate but consent, which only
    observe-only refused - the moment it would have been sent - or None. Read from the record's own
    stored vector, never the journal, and never a setting."""
    if record.get("state") not in WAITING or not record.get("gate_eval"):
        return None
    vector = decode_gates(record.get("gate_eval"))
    if vector["consent"] != (BLOCK, OBSERVE_ONLY):
        return None
    if any(vector[name][0] != PASS for name in GATES if name != "consent"):
        return None
    return record.get("gate_eval_at")


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
