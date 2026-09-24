"""Codex's words and numbers, read the same way everywhere.

A status Codex gives, a time it writes, the JSON in a row: each is read through one function
here, so two readers cannot disagree about what a value means.
"""
from __future__ import annotations

import json
import math

from .. import failures, machine
from ..domain import ids


MAX_SCAN_BYTES = 8 * 1024 * 1024

MAX_META_BYTES = 256 * 1024

MAX_ITEM_BYTES = 1024 * 1024

KNOWN_STATUSES = machine.TURN_STATUSES - {"other"}      # Codex's own four; "other" is ours

# Item types that count as a turn having produced something. Anything Codex adds later
# does not count until it is added here on purpose.
PROGRESS_ITEM_TYPES = frozenset({"agentMessage", "commandExecution", "fileChange", "mcpToolCall"})


def _turn_status(value):
    if value is None:
        return None
    return value if value in KNOWN_STATUSES else "other"


def epoch(value) -> bool:
    return machine.epoch(value, *machine.EPOCH_CODEX, exact=True)


def _json(value):
    if not isinstance(value, str) or len(value) > MAX_ITEM_BYTES:
        return None
    try:
        return json.loads(value)
    except (ValueError, RecursionError):
        return None


def normalize(row) -> dict | None:
    """Normalize just the required scalar fields, discarding raw error text."""
    if not isinstance(row, dict):
        return None
    tid, turn = row.get("thread_id"), row.get("turn_id")
    status = row.get("status")
    ordinal = row.get("ordinal", row.get("rollout_ordinal"))
    if (not ids.is_uuid(tid) or not ids.is_uuid(turn)
            or not isinstance(status, str) or status not in KNOWN_STATUSES
            or type(ordinal) is not int or ordinal < 0):
        return None
    started, completed = row.get("started_at"), row.get("completed_at")
    if not epoch(started) or (completed is not None and not epoch(completed)):
        return None
    if completed is not None and completed < started:
        return None
    if "category" in row:
        # Already normalized once: keep the decision rather than reclassifying from
        # fields that no longer exist, so normalize() stays idempotent.
        category = row["category"] if row["category"] in failures.CATEGORIES else None
    else:
        if "error_json" in row:
            err = _json(row["error_json"])
            info = err.get("codexErrorInfo") if isinstance(err, dict) else None
            text = err.get("message") if isinstance(err, dict) else None
        else:
            info = row.get("error_info", row.get("codexErrorInfo"))
            text = row.get("message")
        # The raw error is classified here and then dropped: only the category name
        # continues past this point, so no error text can reach state, logs or a toast.
        category = failures.classify(info, text) if status == "failed" else None
    return {"thread_id": tid, "turn_id": turn, "status": status,
            "started_at": started, "completed_at": completed,
            "ordinal": ordinal, "category": category}
