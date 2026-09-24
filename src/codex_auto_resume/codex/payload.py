"""Reading one interruption out of what Codex recorded.

`detect` turns a failed turn into the record the engine keeps, and the two marker checks answer
whether a continuation of ours is already sitting in Codex's queue.
"""
from __future__ import annotations

import json
import math
import re

from .. import failures
from ..domain import ids
from .values import _json, epoch, normalize


def detect(row) -> dict | None:
    """A failed turn this tool is willing to recover, or None.

    `unknown` and every terminal category stop here: they are never registered, so
    they can never be retried by a later change somewhere else in the pipeline.
    """
    normalized = normalize(row)
    if (normalized is None or normalized["status"] != "failed"
            or not failures.is_recoverable(normalized["category"] or "")
            or normalized["completed_at"] is None):
        return None
    normalized["interruption_id"] = ids.interruption_id(
        *(normalized[k] for k in ("thread_id", "turn_id", "completed_at", "ordinal")))
    return normalized


def _content_has_marker(content, marker):
    return isinstance(content, list) and any(
        isinstance(item, dict) and item.get("type") == "text"
        and isinstance(item.get("text"), str) and marker in item["text"]
        for item in content)


def _queue_has_marker(payload, marker):
    if not isinstance(payload, dict):
        return False
    # TurnInput's serde shape is version-pinned; unknown shapes fail closed.
    # protocol/src/turn_input.rs derives serde without tag/rename attributes:
    # {"UserInput": {"content": [...], "client_id": ...}}.
    content = payload.get("UserInput")
    return (set(payload) == {"UserInput"} and isinstance(content, dict)
            and _content_has_marker(content.get("content"), marker))


def _choose_reset(buckets, completed_at):
    blocked = []
    ambiguity = False
    for bucket, limits in buckets.items():
        has_window = False
        for name in ("primary", "secondary"):
            window = limits.get(name)
            if not isinstance(window, dict):
                continue
            used, reset = window.get("used_percent"), window.get("resets_at")
            if type(used) not in (int, float) or not math.isfinite(used) or used < 0:
                continue
            has_window = True
            if used >= 100:
                if epoch(reset) and reset >= completed_at:
                    blocked.append((reset, bucket + ":" + name))
                else:
                    ambiguity = True
        if not has_window:
            ambiguity = True
    if blocked:
        reset, limit = max(blocked)
        return {"reset_at": reset, "limit_type": limit, "uncertain": ambiguity or len(blocked) > 1}
    # Actual sample is codex primary=98%, immediately followed by premium=null.
    # Preserve its corroborating reset ONLY when its own usage is high enough to
    # plausibly be the block; a low-usage window's far-future reset must not delay
    # the first eligibility check. A fresh live availability check is still required.
    primary = buckets.get("codex", {}).get("primary")
    if isinstance(primary, dict):
        used = primary.get("used_percent")
        reset = primary.get("resets_at")
        if (type(used) in (int, float) and math.isfinite(used) and used >= 90
                and epoch(reset) and reset >= completed_at):
            return {"reset_at": reset, "limit_type": "codex:primary_hint", "uncertain": True}
    return {"reset_at": None, "limit_type": "unknown", "uncertain": True}
