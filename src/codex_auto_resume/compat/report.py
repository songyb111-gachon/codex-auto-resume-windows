"""The report the watcher writes, and every surface's view of it.

A view is built from the report and the data in force, never from a guess; a report
that is damaged or about another binary is UNKNOWN rather than rendered.
"""
from __future__ import annotations

import math

from .. import machine
from .model import (BUNDLED_STATES, CACHE_ORIGINS, CACHE_STATES, CAPABILITIES, CHECKS,
                    DATA_SOURCES, ENGINE_STATES, EPOCH_MAX, EPOCH_MIN, HEX64_RE, REASONS,
                    REGISTRY_REASONS, REPORT_FORMAT, REPORT_FUTURE_SECONDS, RESOLUTION_REASONS,
                    RESULTS, SOURCES, STATES, TIERS, UNAVAILABLE, UNKNOWN, VIEW_STATUSES,
                    _OWN_REASON, product_key, safe_version)
from .standing import (aggregate)

# ------------------------------------------------------------------------------ the report
def _finite_number(value):
    return (not isinstance(value, bool) and isinstance(value, (int, float))
            and math.isfinite(value))


def _epoch_or_none(value):
    if value is not None and not machine.epoch(value, EPOCH_MIN, EPOCH_MAX):
        raise ValueError("epoch")
    return None if value is None else float(value)


def _small_int_or_none(value):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 2 ** 31 - 1:
        raise ValueError("integer")
    return value


def _clean_engine(value) -> dict:
    if not isinstance(value, dict) or not isinstance(value.get("found"), bool):
        raise ValueError("engine")
    version = value.get("version")
    if version is not None and safe_version(version) is None:
        raise ValueError("version")
    signature = value.get("signature")
    if signature is not None:
        if (not isinstance(signature, list) or len(signature) != 2
                or any(isinstance(part, bool) or not isinstance(part, int) or part < 0
                       for part in signature)):
            raise ValueError("signature")
        signature = list(signature)
    digest = value.get("path_digest")
    if digest is not None and (not isinstance(digest, str) or not HEX64_RE.fullmatch(digest)):
        raise ValueError("digest")
    candidates = value.get("candidates")
    if candidates is not None and (isinstance(candidates, bool) or not isinstance(candidates, int)
                                   or not 0 <= candidates <= 1000):
        raise ValueError("candidates")
    return {"found": value["found"], "version": version, "signature": signature,
            "path_digest": digest, "candidates": candidates}


def _clean_data(value) -> dict:
    if not isinstance(value, dict):
        raise ValueError("data")
    clean = {
        "bundled": value.get("bundled"),
        "bundled_sequence": _small_int_or_none(value.get("bundled_sequence")),
        "cache": value.get("cache"),
        "cache_sequence": _small_int_or_none(value.get("cache_sequence")),
        "cache_origin": value.get("cache_origin"),
        "fetched_at": _epoch_or_none(value.get("fetched_at")),
        "source": value.get("source"),
        "expired": value.get("expired"),
    }
    if (clean["bundled"] not in BUNDLED_STATES or clean["cache"] not in CACHE_STATES
            or clean["source"] not in DATA_SOURCES or not isinstance(clean["expired"], bool)
            or clean["cache_origin"] not in CACHE_ORIGINS + (None,)):
        raise ValueError("data")
    return clean


def _clean_capabilities(value) -> dict:
    if not isinstance(value, dict):
        raise ValueError("capabilities")
    clean = {}
    for name in CAPABILITIES:
        entry = value.get(name)
        if entry is None:
            clean[name] = {"state": UNKNOWN, "reason": "local_check_unavailable", "source": "local",
                           "tier": CAPABILITIES[name][1]}
            continue
        if not isinstance(entry, dict):
            raise ValueError("capability")
        item = {"state": entry.get("state"), "reason": entry.get("reason"),
                "source": entry.get("source"), "tier": entry.get("tier")}
        if (item["state"] not in STATES or item["reason"] not in RESOLUTION_REASONS
                or item["source"] not in SOURCES or item["tier"] not in TIERS):
            raise ValueError("capability")
        if _OWN_REASON.get(item["state"], item["reason"]) != item["reason"]:
            raise ValueError("capability")
        if "registry_reason" in entry:
            if entry["registry_reason"] not in REGISTRY_REASONS:
                raise ValueError("capability")
            item["registry_reason"] = entry["registry_reason"]
        clean[name] = item
    return clean


def validate_report(value, *, now=None):
    """The report as a reader may use it, or None. Checked on every read, exactly as on
    write: a key allowlist at every level, every value in its closed vocabulary, unknown
    keys dropped, the coarse state recomputed from the capabilities rather than believed.
    A report that was truncated, edited or written by something else is refused whole."""
    try:
        if not isinstance(value, dict) or value.get("format") != REPORT_FORMAT:
            return None
        checked = value.get("checked_at")
        if not machine.epoch(checked, EPOCH_MIN, EPOCH_MAX):
            return None
        if now is not None and checked > now + REPORT_FUTURE_SECONDS:
            return None
        product = value.get("product")
        if not isinstance(product, str) or (product != "unknown" and product_key(product) is None):
            return None
        checks_in = value.get("checks")
        if not isinstance(checks_in, dict):
            return None
        checks = {}
        for name in CHECKS:
            result = checks_in.get(name, UNAVAILABLE)
            if result not in RESULTS:
                return None
            checks[name] = result
        capabilities = _clean_capabilities(value.get("capabilities"))
        report = {"format": REPORT_FORMAT, "checked_at": float(checked), "product": product,
                  "engine": _clean_engine(value.get("engine")),
                  "data": _clean_data(value.get("data")),
                  "overall": aggregate(capabilities), "checks": checks,
                  "capabilities": capabilities}
        acting = value.get("acting")
        if acting is not None:
            if acting not in ENGINE_STATES:
                return None
            report["acting"] = acting
        return report
    except (ValueError, TypeError, AttributeError):
        return None


def build_report(*, checked_at, product, engine, data, checks, capabilities, acting=None) -> dict:
    """A report ready to write. Validated before it is returned, so the writer can never
    put on disk anything a reader would refuse."""
    report = {"format": REPORT_FORMAT, "checked_at": float(checked_at),
              "product": product if isinstance(product, str) and product_key(product) else "unknown",
              "engine": engine, "data": data, "overall": aggregate(capabilities),
              "checks": {name: checks.get(name, UNAVAILABLE) for name in CHECKS},
              "capabilities": capabilities}
    if acting is not None:
        report["acting"] = acting
    clean = validate_report(report)
    if clean is None:
        raise ValueError("the report failed its own validation")
    return clean


# ------------------------------------------------------------------------------ views
def _all_unknown(reason) -> dict:
    return {name: {"state": UNKNOWN, "reason": reason, "source": "local", "tier": tier}
            for name, (_, tier) in CAPABILITIES.items()}


def unusable_view(status, *, data=None, checked_at=None, engine=None) -> dict:
    """What every reader shows when the report cannot be used: UNKNOWN for everything."""
    reason = {"absent": "report_absent", "invalid": "report_invalid", "stale": "report_stale",
              "engine_changed": "engine_changed"}.get(status, "report_invalid")
    return {"status": status if status in VIEW_STATUSES else "invalid",
            "overall": "unknown", "acting": None, "checked_at": checked_at,
            "engine": {"found": bool(engine and engine.get("found")),
                       "version": engine.get("version") if engine else None},
            "data": data, "checks": {name: UNAVAILABLE for name in CHECKS},
            "capabilities": _all_unknown(reason)}


def view_of(report) -> dict:
    """A usable report as readers see it. Never carries the path digest or the signature."""
    return {"status": "ok", "overall": report["overall"], "acting": report.get("acting"),
            "checked_at": report["checked_at"],
            "engine": {"found": report["engine"]["found"], "version": report["engine"]["version"]},
            "data": dict(report["data"]), "checks": dict(report["checks"]),
            "capabilities": {name: dict(entry) for name, entry in report["capabilities"].items()}}


def mcp_view(view) -> dict:
    """The compatibility summary a model may read: codes, one small number and one timestamp,
    nothing else - no version string, no path, no free text. It carries what the window's
    Diagnostics card shows, so the settings panel can say the same: what the watcher acts on
    (`acting`, which after Codex changed in place can differ from `overall`), which data is in
    force by its sequence number, and the refreshed data's standing (`cache`: expired or dated
    ahead, its restrictions apply and its trust does not)."""
    view = view if isinstance(view, dict) else unusable_view("invalid")
    data = view.get("data") if isinstance(view.get("data"), dict) else {}
    source = data.get("source") if data.get("source") in DATA_SOURCES else "none"
    # The number of the data in force, as the window reads it: the refreshed data's while that is
    # in force, the bundled data's while that is, and none without data.
    sequence = data.get({"cache": "cache_sequence", "bundled": "bundled_sequence"}.get(source))
    return {"status": view.get("status") if view.get("status") in VIEW_STATUSES else "invalid",
            "overall": view.get("overall") if view.get("overall") in ENGINE_STATES else "unknown",
            "acting": view.get("acting") if view.get("acting") in ENGINE_STATES else None,
            "source": source,
            "sequence": sequence if (isinstance(sequence, int) and not isinstance(sequence, bool)
                                     and sequence >= 0) else None,
            "cache": data.get("cache") if data.get("cache") in CACHE_STATES else None,
            "checked_at": view.get("checked_at") if _finite_number(view.get("checked_at")) else None,
            "capabilities": {name: {"state": entry["state"], "reason": entry["reason"]}
                             for name, entry in (view.get("capabilities") or {}).items()
                             if name in CAPABILITIES and entry.get("state") in STATES
                             and entry.get("reason") in REASONS}}


# ------------------------------------------------------------------------------ v0.6.11
