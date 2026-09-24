"""The Compatibility Registry's format: every closed word, the limits, parsing and validation.

Pure: no file, no process, no clock that is not handed in. What a document may contain
is decided here and nowhere else.
"""
from __future__ import annotations

import calendar
import json
import math
import re
import time

from .. import machine
from ..domain.vocabulary import (BundledState, CacheOrigin, CacheState, CompatCheck, CompatSource,
                                 CompatState, DataSource, EngineState, ImportReason, LocalResult,
                                 RegistryReason, ResolutionReason, Tier, ViewReason, ViewStatus)


# ------------------------------------------------------------------------------ formats
FORMAT_PREFIX = "codex-auto-resume-compat/"
FORMAT_MAJOR = "1"
FORMAT = FORMAT_PREFIX + FORMAT_MAJOR
CACHE_FORMAT = "codex-auto-resume-compat-cache/1"
REPORT_FORMAT = "codex-auto-resume-compat-report/1"

# The settings file's cap, and for the same reason: a byte cap is checked before anything
# is parsed, so a hostile or broken file costs a stat and nothing else.
MAX_DOCUMENT_BYTES = 256 * 1024
MAX_CACHE_BYTES = MAX_DOCUMENT_BYTES + 4 * 1024
MAX_REPORT_BYTES = 64 * 1024
MAX_ENGINES = 500
MAX_ADVISORIES = 200
MAX_EVIDENCE = 8
# A published_at this far ahead of the local clock is not believed.
FUTURE_SKEW_SECONDS = 24 * 3600
# A report newer than the clock by more than this is not believed either.
REPORT_FUTURE_SECONDS = 300
# How old a report may be before a reader stops believing it: the watcher recomputes at
# least every RECOMPUTE_SECONDS, and ticks at most MAX_POLL (3600 s) apart, so a watcher
# that is ticking never trips this. Five minutes of slack for a slow tick.
RECOMPUTE_SECONDS = 600
REPORT_MAX_AGE = RECOMPUTE_SECONDS + 3600 + 300

EPOCH_MIN, EPOCH_MAX = machine.EPOCH_CODEX      # 2000-01-01 to 2100-01-01, as Codex's history

# ------------------------------------------------------------------------------ states
VERIFIED, CHECKED, COMPATIBLE = "VERIFIED", "CHECKED", "COMPATIBLE"
FAILED_HERE, INCOMPATIBLE, UNKNOWN = "FAILED_HERE", "INCOMPATIBLE", "UNKNOWN"
STATES = tuple(CompatState)
# Worst first. The coarse state is the worst of the capabilities it summarises.
_ORDER = {INCOMPATIBLE: 0, FAILED_HERE: 1, UNKNOWN: 2, COMPATIBLE: 3, CHECKED: 4, VERIFIED: 5}
_OWN_REASON = dict(VERIFIED="registry_verified", CHECKED="registry_checked", FAILED_HERE="local_check_failed_here")

# What one local check found.
PASS, FAIL, UNAVAILABLE, NOT_APPLICABLE = (LocalResult.PASS, LocalResult.FAIL,
                                          LocalResult.UNAVAILABLE, LocalResult.NOT_APPLICABLE)
RESULTS = tuple(LocalResult)

# The product dimension, which is not a registry state: how a capability is offered.
TIERS = tuple(Tier)

# The coarse vocabulary the watcher's heartbeat already stores (store.ENGINE_STATES). The
# stored token for COMPATIBLE stays `structurally_compatible`: it is a wire value.
COARSE = {VERIFIED: EngineState.VERIFIED, CHECKED: EngineState.CHECKED,
          COMPATIBLE: EngineState.STRUCTURALLY_COMPATIBLE, FAILED_HERE: EngineState.FAILED_HERE,
          INCOMPATIBLE: EngineState.INCOMPATIBLE, UNKNOWN: EngineState.UNKNOWN}
ENGINE_STATES = tuple(EngineState)

# ------------------------------------------------------------------------------ checks
# Every local structural check, each grounded in the code path that relies on it (the
# vocabulary says which). None of them sends anything, starts `codex app-server`, or writes
# anywhere.
CHECKS = tuple(CompatCheck)

# capability -> (the local checks that prove it, tier). The four without checks are not
# implemented; they are listed so v0.6.11 can offer them, and they stay `unsupported`.
CAPABILITIES = {
    "engine_present": (("official_location", "version_runs", "single_candidate"), "conservative"),
    "exact_thread_recovery": (("official_location", "version_runs", "queue_flags"), "conservative"),
    "usage_limit_detection": (("history_schema", "state_schema"), "conservative"),
    "usage_reset_hint": (("history_schema", "sessions_directory"), "conservative"),
    "usage_probe": (("version_runs", "protocol_usage_method"), "conservative"),
    "thread_eligibility": (("state_schema", "sessions_directory"), "conservative"),
    "loaded_state_detection": (("lock_directory", "restart_manager"), "conservative"),
    "recovery_turn_tracking": (("history_schema", "queue_schema", "projection_table"), "conservative"),
    "queue_withdraw": (("version_runs", "protocol_delete_method", "queue_schema"), "conservative"),
    "outcome_observation": (("history_schema",), "conservative"),
    "transient_classification": (("history_schema",), "conservative"),
    "projection_freshness": (("projection_table", "sessions_directory"), "conservative"),
    "empty_response_recovery": ((), "unsupported"),
    "not_loaded_recovery": ((), "unsupported"),
    "goal_continuation": ((), "unsupported"),
    "subagent_recovery": ((), "unsupported"),
}

# The capabilities whose state the engine's `engine_compatible` gate reads, through the
# coarse word. Exactly the engine-level checks the gate has always stood on (discovery's
# E1, E2, E4, E5), so no existing decision moves. The other send-required capabilities -
# turn tracking, withdrawal, loaded state, projection freshness - keep the dynamic gates
# they already have at the moment of an attempt; their static states are reported, and
# `permits()` reads them for anything v0.6.11 offers beyond the conservative default.
SEND_GATE = ("engine_present", "exact_thread_recovery")

# Why a capability has the state it has.
RESOLUTION_REASONS = frozenset(ResolutionReason)
# Why a reader could not use the report at all (every capability is then UNKNOWN).
VIEW_REASONS = frozenset(ViewReason)
REASONS = RESOLUTION_REASONS | VIEW_REASONS

# The reasons a registry document may give. Closed: anything else becomes `unspecified`,
# so a document can never put words in front of a person or a model.
REGISTRY_REASONS = frozenset(RegistryReason)

SOURCES = tuple(CompatSource)
BUNDLED_STATES = tuple(BundledState)
# absent: none imported. ok: in force. expired: past expires_at - its INCOMPATIBLE data
# still applies, its VERIFIED data does not. rejected: failed validation (kept on disk, not
# deleted, so a person can look at it). superseded: older than the bundled baseline.
# from_newer_product: needs a newer version of this product to be read. from_the_future:
# published more than FUTURE_SKEW_SECONDS after this computer's clock says it is now - the
# clock is behind, or the data is misdated - and treated as expired until the clock catches
# up: its restrictions apply, its trust does not.
CACHE_STATES = tuple(CacheState)
# Time may only ever withhold trust. A cache in any of these standings still restricts -
# its INCOMPATIBLE data is in force - and only the first may also grant VERIFIED. No clock,
# however wrong, can lift a restriction.
RESTRICTING_STATES = ("ok", "expired", "from_the_future")
TRUSTING_STATES = ("ok",)
DATA_SOURCES = tuple(DataSource)
VIEW_STATUSES = tuple(ViewStatus)
CACHE_ORIGINS = tuple(CacheOrigin)

# Why an import was refused. Closed, like everything else that leaves this module.
IMPORT_REASONS = frozenset(ImportReason)

VERSION_RE = re.compile(
    r"codex-cli (\d{1,6})\.(\d{1,6})\.(\d{1,6})(?:-alpha\.(\d{1,9})(?:\.(\d{1,9}))?)?")
BOUND_RE = re.compile(r"(\d{1,6})\.(\d{1,6})\.(\d{1,6})(?:-alpha\.(\d{1,9})(?:\.(\d{1,9}))?)?")
PRODUCT_RE = re.compile(r"(\d{1,6})\.(\d{1,6})\.(\d{1,6})")
# What a version string may look like to be stored or shown at all. `codex --version` is the
# official binary's output, but it still never reaches a report unchecked.
SAFE_VERSION_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9 ._+()-]{0,79}")
TIMESTAMP_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})Z")
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
ADVISORY_ID_RE = re.compile(r"CAR-\d{4}-\d{4}")
EVIDENCE_RE = re.compile(r"docs/evidence/[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)*\.json")
HEX64_RE = re.compile(r"[0-9a-f]{64}")


class DocumentError(ValueError):
    """A document or file that is refused. `code` is one of IMPORT_REASONS; no other text."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code if code in IMPORT_REASONS else "invalid_field"


# ------------------------------------------------------------------------------ decoding
def _reject_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise DocumentError("duplicate_key")
        result[key] = value
    return result


def _reject_constant(_name):
    raise DocumentError("not_finite")


def _finite_float(text):
    value = float(text)
    if not math.isfinite(value):
        raise DocumentError("not_finite")
    return value


def decode(raw, limit: int = MAX_DOCUMENT_BYTES):
    """Bytes (or text) to a JSON value, hardened: a byte cap before anything is parsed,
    duplicate keys refused, NaN/Infinity and overflowing numbers refused, deep nesting
    refused. Raises DocumentError; never returns a partial value."""
    if isinstance(raw, str):
        raw = raw.encode("utf-8")
    if not isinstance(raw, (bytes, bytearray)):
        raise DocumentError("not_json")
    if len(raw) > limit:
        raise DocumentError("too_large")
    try:
        text = bytes(raw).decode("utf-8-sig")
    except UnicodeDecodeError:
        raise DocumentError("not_json") from None
    try:
        return json.loads(text, object_pairs_hook=_reject_duplicates,
                          parse_constant=_reject_constant, parse_float=_finite_float)
    except DocumentError:
        raise
    except RecursionError:
        raise DocumentError("too_deep") from None
    except ValueError:
        raise DocumentError("not_json") from None


# ------------------------------------------------------------------------------ versions
def parse_version(text):
    """`codex-cli MAJOR.MINOR.PATCH[-alpha.N[.M]]` to an ordering key, or None.

    A pre-release sorts before its release. An unparseable string matches no range and no
    engine entry, so it can be COMPATIBLE at best - never VERIFIED, and never caught by a
    range advisory either, which is why ranges may only restrict and VERIFIED is exact.
    """
    if not isinstance(text, str):
        return None
    match = VERSION_RE.fullmatch(text.strip())
    return _key(match) if match else None


def _bound(text):
    if not isinstance(text, str):
        raise DocumentError("invalid_field")
    match = BOUND_RE.fullmatch(text)
    if not match:
        raise DocumentError("invalid_field")
    return _key(match)


def _key(match):
    major, minor, patch, alpha, sub = match.groups()
    if alpha is None:
        return (int(major), int(minor), int(patch), 1, 0, 0)
    return (int(major), int(minor), int(patch), 0, int(alpha), int(sub or 0))


def product_key(text):
    if not isinstance(text, str):
        return None
    match = PRODUCT_RE.fullmatch(text.strip())
    return tuple(int(part) for part in match.groups()) if match else None


def safe_version(text):
    """The version string if it is one a report may carry, else None."""
    if isinstance(text, str) and SAFE_VERSION_RE.fullmatch(text):
        return text
    return None


def _timestamp(text, *, optional=False):
    if text is None and optional:
        return None
    if not isinstance(text, str):
        raise DocumentError("invalid_field")
    match = TIMESTAMP_RE.fullmatch(text)
    if not match:
        raise DocumentError("invalid_field")
    try:
        value = calendar.timegm(time.strptime(text, "%Y-%m-%dT%H:%M:%SZ"))
    except (ValueError, OverflowError):
        raise DocumentError("invalid_field") from None
    if not machine.epoch(value, EPOCH_MIN, EPOCH_MAX, finite=False):
        raise DocumentError("invalid_field")
    return float(value)


def _integer(value, low=0, high=2 ** 31 - 1):
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise DocumentError("invalid_field")
    return value


def _registry_reason(value):
    return value if isinstance(value, str) and value in REGISTRY_REASONS else "unspecified"


# ------------------------------------------------------------------------------ documents
def validate_document(value) -> dict:
    """A registry document, validated whole and normalised, or DocumentError.

    Returns ``{"sequence", "published_at", "expires_at", "min_product", "requires_signature",
    "engines": {version: {capability: {"state", "reason"}}}, "advisories": [...]}``.
    """
    if not isinstance(value, dict):
        raise DocumentError("not_an_object")
    declared = value.get("format")
    if not isinstance(declared, str) or not declared.startswith(FORMAT_PREFIX) \
            or declared[len(FORMAT_PREFIX):] != FORMAT_MAJOR:
        raise DocumentError("unknown_format")
    requires = value.get("requires_signature", False)
    if not isinstance(requires, bool):
        raise DocumentError("invalid_field")
    if requires:
        # Nothing verifies a signature yet, so a document that demands one cannot be read
        # honestly. It is refused whole - never read with the signature ignored.
        raise DocumentError("signature_required")
    for reserved in ("signature", "key_id"):
        slot = value.get(reserved)
        if slot is not None and (not isinstance(slot, str) or len(slot) > 8192):
            raise DocumentError("invalid_field")
    sequence = _integer(value.get("sequence"))
    published = _timestamp(value.get("published_at"))
    expires = _timestamp(value.get("expires_at"), optional=True)
    if expires is not None and expires <= published:
        raise DocumentError("invalid_field")
    minimum = product_key(value.get("min_product"))
    if minimum is None:
        raise DocumentError("invalid_field")

    engines_in = value.get("engines", [])
    if not isinstance(engines_in, list):
        raise DocumentError("invalid_field")
    if len(engines_in) > MAX_ENGINES:
        raise DocumentError("too_many")
    engines = {}
    for entry in engines_in:
        if not isinstance(entry, dict):
            raise DocumentError("invalid_field")
        version = entry.get("version")
        if safe_version(version) is None or parse_version(version) is None:
            raise DocumentError("invalid_field")
        if version in engines:
            raise DocumentError("invalid_field")
        listed = entry.get("capabilities", {})
        if not isinstance(listed, dict):
            raise DocumentError("invalid_field")
        capabilities = {}
        for name, claim in listed.items():
            if not isinstance(claim, dict):
                raise DocumentError("invalid_field")
            evidence = claim.get("evidence", [])
            if not isinstance(evidence, list) or len(evidence) > MAX_EVIDENCE:
                raise DocumentError("invalid_field")
            for path in evidence:
                if not isinstance(path, str) or not EVIDENCE_RE.fullmatch(path) or ".." in path:
                    raise DocumentError("invalid_field")
            verified_at = claim.get("verified_at")
            if verified_at is not None and (not isinstance(verified_at, str)
                                            or not DATE_RE.fullmatch(verified_at)):
                raise DocumentError("invalid_field")
            state = claim.get("state")
            if name not in CAPABILITIES or state not in (VERIFIED, CHECKED, INCOMPATIBLE):
                # Unknown capability ids and states that carry no weight here (COMPATIBLE,
                # UNKNOWN, or a name from a later format) are ignored - and an unknown state
                # is never read as trust: only the literals are. v0.6.5 and v0.6.6 skip CHECKED.
                continue
            if state in (VERIFIED, CHECKED) and not evidence:
                # Either is a claim about a tested build; without a citation it is just an
                # assertion, and the evidence rule refuses those.
                raise DocumentError("unevidenced_verified")
            capabilities[name] = {"state": state, "reason": _registry_reason(claim.get("reason")),
                                  "evidence": list(evidence)}
        engines[version] = capabilities

    advisories_in = value.get("advisories", [])
    if not isinstance(advisories_in, list):
        raise DocumentError("invalid_field")
    if len(advisories_in) > MAX_ADVISORIES:
        raise DocumentError("too_many")
    advisories = []
    seen = set()
    for advisory in advisories_in:
        if not isinstance(advisory, dict):
            raise DocumentError("invalid_field")
        identifier = advisory.get("id")
        if not isinstance(identifier, str) or not ADVISORY_ID_RE.fullmatch(identifier) \
                or identifier in seen:
            raise DocumentError("invalid_field")
        seen.add(identifier)
        if advisory.get("state") != INCOMPATIBLE:
            # A range is a fuzzy match, and a fuzzy match must never grant trust.
            raise DocumentError("range_cannot_grant")
        match = advisory.get("match")
        if not isinstance(match, dict) or not ({"version_gte", "version_lt"} & set(match)):
            raise DocumentError("invalid_field")
        low = _bound(match["version_gte"]) if "version_gte" in match else None
        high = _bound(match["version_lt"]) if "version_lt" in match else None
        if low is not None and high is not None and not low < high:
            raise DocumentError("invalid_field")
        names = advisory.get("capabilities")
        if not isinstance(names, list) or not names or not all(isinstance(n, str) for n in names):
            raise DocumentError("invalid_field")
        advisories.append({"id": identifier, "low": low, "high": high,
                           "capabilities": frozenset(n for n in names if n in CAPABILITIES),
                           "reason": _registry_reason(advisory.get("reason"))})
    return {"sequence": sequence, "published_at": published, "expires_at": expires,
            "min_product": minimum, "requires_signature": False,
            "engines": engines, "advisories": advisories}


def parse_document(raw, limit: int = MAX_DOCUMENT_BYTES) -> dict:
    return validate_document(decode(raw, limit))
