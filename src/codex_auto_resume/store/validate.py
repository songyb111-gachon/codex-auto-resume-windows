"""Every value checked before it is written, and the record as a whole.

Nothing reaches a table without passing through here: a row this release cannot write is a row
the next one cannot read.
"""
from __future__ import annotations

import math
from typing import Any

from .. import failures, needsyou
from ..domain import ids, vocabulary
from .. import machine
from ..machine import CLAIMED, IN_FLIGHT, OBSERVING, STATES
from .columns import _MUTABLE, _NEEDS_RECOVERY_TURN, _NOTICE_COLUMNS, _RECORD_COLUMNS
from .errors import RecordSchemaMismatch, StoreError


ENGINE_STATES = frozenset(vocabulary.EngineState)
# v0.6.11: how the watcher last ended, as the heartbeat keeps it (store/watcher.py).
WATCHER_ENDS = tuple(vocabulary.WatcherEnd)


# ------------------------------------------------------------------------- validators
def _uuid(value: Any, name: str) -> str:
    problem = ids.uuid_problem(value)
    if problem == ids.NOT_CANONICAL:
        raise StoreError(f"Invalid {name}: canonical UUID required")
    if problem is not None:
        raise StoreError(f"Invalid {name}")
    return value


def _timestamp(value: Any, name: str, *, nullable: bool = False) -> Any:
    if value is None and nullable:
        return None
    if not machine.epoch(value, *machine.EPOCH_STORE):
        raise StoreError(f"Invalid {name}")
    return value


def _integer(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0 or value > 2**63 - 1:
        raise StoreError(f"Invalid {name}")
    return value


def _flag(value: Any, name: str) -> bool:
    if not isinstance(value, (int, bool)) or value not in (0, 1):
        raise StoreError(f"Invalid {name}")
    return bool(value)


def _short_text(value: Any, name: str, maximum: int, *, nullable: bool = False) -> Any:
    if value is None and nullable:
        return None
    if (not isinstance(value, str) or len(value) > maximum
            or any(ord(character) < 32 or ord(character) == 127 for character in value)):
        raise StoreError(f"Invalid {name}")
    return value


def _choice(value: Any, name: str, allowed) -> Any:
    if value is not None and value not in allowed:
        raise StoreError(f"Invalid {name}")
    return value


def _validated_record(row: dict[str, Any]) -> dict[str, Any]:
    if set(row) != set(_RECORD_COLUMNS):
        raise RecordSchemaMismatch("Invalid record schema")
    key = row["interruption_id"]
    if not ids.is_interruption_id(key, as_stored=True):
        raise StoreError("Invalid interruption_id")
    _uuid(row["thread_id"], "thread_id")
    _uuid(row["turn_id"], "turn_id")
    for field in ("completed_at", "detected_at", "next_retry_at", "chain_first_detected_at",
                  "usage_unavailable_seconds"):
        _timestamp(row[field], field)
    for field in ("started_at", "reset_at", "resumed_at", "submitted_at", "withdrawn_at",
                  "turn_started_at", "outcome_at", "first_queued_at", "last_claim_at",
                  "usage_probe_at", "gate_eval_at", "history_hidden_at", "not_before",
                  "objection_at"):
        _timestamp(row[field], field, nullable=True)
    for field in ("ordinal", "retry_count", "attempt_count", "recovery_attempts",
                  "no_progress_count", "withdraw_failures", "chain_continuations",
                  "budget_resets", "retry_now_count"):
        _integer(row[field], field)
    if row["category"] not in failures.CATEGORIES:
        raise StoreError("Invalid failure category")
    for field in ("uncertain", "cancel_requested", "user_joined", "after_user_work", "legacy",
                  "withdraw_deleted"):
        row[field] = _flag(row[field], field)
    _short_text(row["limit_type"], "limit_type", 160, nullable=True)
    _short_text(row["last_error"], "last_error", 240, nullable=True)
    _short_text(row["gate_eval"], "gate_eval", 4000, nullable=True)
    if not isinstance(row["state"], str) or row["state"] not in STATES:
        raise StoreError("Unknown record state")
    # Its short marker, or - for a record made before v0.6.11 - the marker of its whole id.
    if row["marker"] not in ids.record_markers(key):
        raise StoreError("Invalid record marker")
    _choice(row["hold"], "hold", machine.HOLDS)
    # v0.6.11: the guards' digest and count (guards.py), each empty while its guard is off: 64 hex
    # digits, and a whole number no larger than guards.MAX_TOKENS.
    if row["task_print"] is not None and not ids.is_digest(row["task_print"]):
        raise StoreError("Invalid task_print")
    if row["context_tokens"] is not None and _integer(row["context_tokens"], "context_tokens") > 2 ** 53:
        raise StoreError("Invalid context_tokens")
    for field in ("queue_id", "recovery_turn_id"):
        if row[field] is not None:
            _uuid(row[field], field)
    if row["recovery_client_id"] is not None and not ids.is_client_id(row["recovery_client_id"]):
        raise StoreError("Invalid recovery_client_id")
    _choice(row["recovery_turn_status"], "recovery_turn_status", machine.TURN_STATUSES)
    _choice(row["withdraw_reason"], "withdraw_reason", machine.WITHDRAW_REASONS)
    parent = row["parent_interruption_id"]
    if parent is not None and not ids.is_interruption_id(parent, as_stored=True):
        raise StoreError("Invalid parent_interruption_id")
    if not ids.is_interruption_id(row["chain_origin_id"], as_stored=True):
        raise StoreError("Invalid chain_origin_id")
    state = row["state"]
    if state in CLAIMED | IN_FLIGHT | OBSERVING and row["submitted_at"] is None:
        raise StoreError("Missing submission timestamp")
    if state in _NEEDS_RECOVERY_TURN and row["recovery_turn_id"] is None:
        raise StoreError("Missing recovery turn")
    if state == "withdrawn_unconfirmed" and (row["withdraw_reason"] is None or row["withdrawn_at"] is None):
        raise StoreError("Missing withdrawal details")
    return row


def _validated_tier(value):
    """A conversation's tier (schema 4): one of the closed list, or None - no tier of its own."""
    return _choice(value, "tier", machine.IMPORTANCE_TIERS)


def _validated_notice(row: dict[str, Any]) -> dict[str, Any]:
    """One needs-you notice (schema 4): ids, its kind - a failure that needs a person, or a turn that
    stopped moving (needsyou.NOTICE_KINDS) - and times; nothing else."""
    if set(row) != set(_NOTICE_COLUMNS):
        raise RecordSchemaMismatch("Invalid notice schema")
    if not ids.is_interruption_id(row["interruption_id"], as_stored=True):
        raise StoreError("Invalid notice interruption_id")
    _uuid(row["thread_id"], "notice thread_id")
    if row["category"] not in needsyou.NOTICE_KINDS:
        raise StoreError("Invalid notice category")
    _timestamp(row["raised_at"], "raised_at")
    _timestamp(row["seen_at"], "seen_at", nullable=True)
    return row


def _finite(value, default=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return default
    return float(value)


def _sql(value):
    return int(value) if isinstance(value, bool) else value


def is_usage(row: dict) -> bool:
    return row.get("category") == failures.USAGE_LIMIT


def _claim_cost(row, refund: bool = False) -> str:
    """What one claim costs a record's budgets - an attempt, which a usage limit never spends,
    and a link of its chain - as the SET clause that charges it or gives it back, never below 0."""
    cost = (("recovery_attempts", 0 if is_usage(row) else 1), ("chain_continuations", 1))
    template = "%s=max(0, %s-%d)" if refund else "%s=%s+%d"
    return ", ".join(template % (column, column, amount) for column, amount in cost)
