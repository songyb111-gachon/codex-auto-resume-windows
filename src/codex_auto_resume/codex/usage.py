"""Codex's usage reply, read to an allowlist of numbers.

Never the account it belongs to, never a plan name, never a balance: the fields below and
nothing else, so a reply that grows cannot start carrying something this product then logs.
"""
from __future__ import annotations

import math

from .. import machine


def parse_usage(value):
    """Allowlist numeric usage fields. Never retain account IDs, banners or credits."""
    unknown = {"available": None, "reset_at": None, "limit_type": "unknown", "reason": "usage_snapshot_unknown"}
    if not isinstance(value, dict):
        return unknown
    buckets = value.get("rateLimitsByLimitId")
    if not isinstance(buckets, dict) or not buckets:
        legacy = value.get("rateLimits")
        buckets = {"legacy": legacy} if isinstance(legacy, dict) else {}
    windows, blocked, spending, explicit_limit = [], [], False, False
    for bucket_id, bucket in buckets.items():
        if not isinstance(bucket, dict):
            return unknown
        safe_id = bucket_id if bucket_id in ("codex", "premium", "legacy") else "other"
        spending |= bucket.get("spendControlReached") is True
        explicit_limit |= bucket.get("rateLimitReachedType") == "rate_limit_reached"
        if bucket.get("rateLimitReachedType") in (
                "workspace_owner_credits_depleted", "workspace_member_credits_depleted",
                "workspace_owner_usage_limit_reached", "workspace_member_usage_limit_reached"):
            spending = True
        for slot in ("primary", "secondary"):
            window = bucket.get(slot)
            if window is None:
                continue
            if not isinstance(window, dict):
                return unknown
            used = window.get("usedPercent")
            if type(used) not in (int, float) or not math.isfinite(used) or used < 0:
                return unknown
            duration = window.get("windowDurationMins")
            if duration is not None and (type(duration) is not int or duration <= 0):
                return unknown
            resets_at = window.get("resetsAt")
            if resets_at is not None and not machine.epoch(
                    resets_at, *machine.EPOCH_USAGE, integer=True, exact=True, finite=False):
                return unknown
            entry = {"bucket": safe_id, "window": slot, "used_percent": used,
                     "window_minutes": duration, "reset_at": resets_at}
            windows.append(entry)
            if used >= 100:
                blocked.append(entry)
    if spending:
        return {"available": False, "reset_at": None, "limit_type": "spend_or_credits",
                "reason": "account_spend_or_credit_block", "windows": windows}
    if blocked:
        resets = [window["reset_at"] for window in blocked]
        reset = max(resets) if all(x is not None for x in resets) else None
        return {"available": False, "reset_at": reset,
                "limit_type": ",".join(sorted(set(str(w["window_minutes"] or "unknown") + "m" for w in blocked))),
                "reason": "one_or_more_exposed_windows_exhausted_blocking_bucket_not_attributed", "windows": windows}
    if explicit_limit:
        return {"available": False, "reset_at": None, "limit_type": "unattributed",
                "reason": "server_reports_rate_limit_reached", "windows": windows}
    if windows:
        return {"available": True, "reset_at": None, "limit_type": "exposed_windows",
                "reason": "exposed_windows_available_specific_model_bucket_not_guaranteed", "windows": windows}
    return unknown
