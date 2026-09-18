"""Codex Compatibility Registry: the model and the data format. Pure - no file, process or
network access happens in this module.

What it answers is narrow: for the Codex engine on this machine, which of the things this
product does can be relied on, and why. Every answer is one of four states:

* ``VERIFIED``     - the maintainer tested this exact engine version, with cited evidence;
* ``COMPATIBLE``   - the local structural checks pass; nobody has verified this build;
* ``INCOMPATIBLE`` - a local check failed, or registry data says this build is unsafe;
* ``UNKNOWN``      - it cannot be established, because a check could not run.

Two rules decide every answer, and they are the whole reason the registry can be fed data
from outside the release without that data being able to make anything less careful:

1. **A failed local check always wins.** Nothing a registry document says can turn a local
   FAIL into anything but INCOMPATIBLE.
2. **Registry data can never raise a capability above what the local checks allow.** It can
   restrict anything (INCOMPATIBLE, for an exact version or a range of them); it can elevate
   only a local PASS, only to VERIFIED, and only for an exact version string. An unrunnable
   check stays UNKNOWN whatever the data claims.

`resolve()` is those two rules as five lines, in that order.

The data format carries one integer major (`codex-auto-resume-compat/1`). An unknown major,
a malformed document, a duplicate key, a non-finite number, a range that tries to grant
trust, or a document that says it requires a signature (nothing verifies one yet) is
rejected *whole* - never partly read. Unknown keys, unknown capability ids and unknown state
names are ignored, and an unknown state is never treated as VERIFIED. Every reason that
reaches a person or a model is a code from a closed vocabulary; no free text from a registry
document goes anywhere.

The signature slot (`signature`, `key_id`, `requires_signature`) is reserved in format 1 so
that signing can arrive as a data change rather than a format major: a document that sets
`requires_signature` is rejected entirely until a verifier exists, and a cached document may
not lower it relative to the bundled baseline.
"""
from __future__ import annotations

import calendar
import json
import math
import re
import time

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

EPOCH_MIN = 946684800          # 2000-01-01, as source.epoch
EPOCH_MAX = 4102444800         # 2100-01-01

# ------------------------------------------------------------------------------ states
VERIFIED, COMPATIBLE, INCOMPATIBLE, UNKNOWN = "VERIFIED", "COMPATIBLE", "INCOMPATIBLE", "UNKNOWN"
STATES = (VERIFIED, COMPATIBLE, INCOMPATIBLE, UNKNOWN)
# Worst first. The coarse state is the worst of the capabilities it summarises.
_ORDER = {INCOMPATIBLE: 0, UNKNOWN: 1, COMPATIBLE: 2, VERIFIED: 3}

# What one local check found.
PASS, FAIL, UNAVAILABLE, NOT_APPLICABLE = "PASS", "FAIL", "UNAVAILABLE", "NOT_APPLICABLE"
RESULTS = (PASS, FAIL, UNAVAILABLE, NOT_APPLICABLE)

# The product dimension, which is not a registry state: how a capability is offered.
TIERS = ("conservative", "advanced", "experimental", "unsupported")

# The coarse vocabulary the watcher's heartbeat already stores (store.ENGINE_STATES). The
# stored token for COMPATIBLE stays `structurally_compatible`: it is a wire value.
COARSE = {VERIFIED: "verified", COMPATIBLE: "structurally_compatible",
          INCOMPATIBLE: "incompatible", UNKNOWN: "unknown"}
ENGINE_STATES = tuple(COARSE.values())

# ------------------------------------------------------------------------------ checks
# Every local structural check, each grounded in the code path that relies on it. None of
# them sends anything, starts `codex app-server`, or writes anywhere.
CHECKS = (
    # E1 windows.Backend.engine_checks: the binary sits at the official, content-addressed
    #    %LOCALAPPDATA%\OpenAI\Codex\bin\<hex>\codex.exe.
    "official_location",
    # E2 `codex --version` runs and exits 0.
    "version_runs",
    # E5 config.discover_codex_exe: exactly one candidate passes (or one was named).
    "single_candidate",
    # E4 `codex queue --help` exits 0 and still offers --thread and --message - the one
    #    interface windows.Backend.send drives.
    "queue_flags",
    # E6 source.DB_KINDS: the newest generation of each database has every column the
    #    read-only adapter reads. A missing column is a FAIL; no database is UNAVAILABLE.
    "state_schema", "history_schema", "queue_schema",
    # E7 source.LocalSource.projection: thread_history_projection_state with
    #    next_rollout_byte_offset, which the freshness gate compares with the rollout file.
    "projection_table",
    # The rollout directory the reset hint and eligibility read (source._rollout_path).
    "sessions_directory",
    # windows.Backend.loaded: the writer-lock directory, and the Restart Manager API that
    # inventories it without ever taking a lock.
    "lock_directory", "restart_manager",
    # windows.Protocol.call: the two App Server methods usage and withdrawal use are the
    #    ones the adapter allowlists (a code-level check; nothing is started).
    "protocol_usage_method", "protocol_delete_method",
)

# capability -> (the local checks that prove it, tier). The four without checks are not
# implemented; they are listed so v0.6.6 can offer them, and they stay `unsupported`.
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
# `permits()` reads them for anything v0.6.6 offers beyond the conservative default.
SEND_GATE = ("engine_present", "exact_thread_recovery")

# Why a capability has the state it has.
RESOLUTION_REASONS = frozenset({
    "local_check_failed", "registry_incompatible", "local_check_unavailable",
    "not_implemented", "registry_verified", "local_checks_passed",
})
# Why a reader could not use the report at all (every capability is then UNKNOWN).
VIEW_REASONS = frozenset({"report_absent", "report_invalid", "report_stale", "engine_changed"})
REASONS = RESOLUTION_REASONS | VIEW_REASONS

# The reasons a registry document may give. Closed: anything else becomes `unspecified`,
# so a document can never put words in front of a person or a model.
REGISTRY_REASONS = frozenset({
    "queued_message_not_delivered_while_unloaded", "queue_receipt_format_changed",
    "queue_interface_changed", "schema_changed", "protocol_changed", "delivery_unverified",
    "maintainer_advisory", "unspecified",
})

SOURCES = ("local", "bundled", "cache")
BUNDLED_STATES = ("ok", "missing", "rejected")
# absent: none imported. ok: in force. expired: past expires_at - its INCOMPATIBLE data
# still applies, its VERIFIED data does not. rejected: failed validation (kept on disk, not
# deleted, so a person can look at it). superseded: older than the bundled baseline.
# from_newer_product: needs a newer version of this product to be read. from_the_future:
# published more than FUTURE_SKEW_SECONDS after this computer's clock says it is now - the
# clock is behind, or the data is misdated - and treated as expired until the clock catches
# up: its restrictions apply, its trust does not.
CACHE_STATES = ("absent", "ok", "expired", "rejected", "superseded", "from_newer_product",
                "from_the_future")
# Time may only ever withhold trust. A cache in any of these standings still restricts -
# its INCOMPATIBLE data is in force - and only the first may also grant VERIFIED. No clock,
# however wrong, can lift a restriction.
RESTRICTING_STATES = ("ok", "expired", "from_the_future")
TRUSTING_STATES = ("ok",)
DATA_SOURCES = ("cache", "bundled", "none")
VIEW_STATUSES = ("ok", "absent", "invalid", "stale", "engine_changed")
CACHE_ORIGINS = ("main", "file")

# Why an import was refused. Closed, like everything else that leaves this module.
IMPORT_REASONS = frozenset({
    "too_large", "not_json", "duplicate_key", "not_finite", "too_deep", "not_an_object",
    "unknown_format", "invalid_field", "signature_required", "range_cannot_grant",
    "unevidenced_verified", "too_many", "from_the_future", "from_newer_product", "rollback",
    "unreadable", "not_a_json_file", "write_failed",
})

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
    if not EPOCH_MIN <= value <= EPOCH_MAX:
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
            if name not in CAPABILITIES or state not in (VERIFIED, INCOMPATIBLE):
                # Unknown capability ids and states that carry no weight here (COMPATIBLE,
                # UNKNOWN, or a name from a later format) are ignored - and an unknown state
                # can never be read as VERIFIED, because only the literal is.
                continue
            if state == VERIFIED and not evidence:
                # VERIFIED is a claim about a tested build; without a citation it is just
                # an assertion, and the evidence rule refuses those.
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


def document_standing(document, *, product, bundled=None, now=None, role="cache"):
    """Whether a validated document may be used, as one of CACHE_STATES.

    The bundled baseline is judged by the product version alone - not by the clock. The
    release authenticates it, it describes exact builds that were tested for this release,
    and it never expires; a clock that is wrong must not set its restrictions aside.

    For a cache, time only ever withholds trust (RESTRICTING_STATES, TRUSTING_STATES): past
    its `expires_at`, or dated after this computer's clock by more than a day, its VERIFIED
    data stops applying while its INCOMPATIBLE data still does. The answer depends on `now`,
    so a reader that keeps a document has to ask again as time passes.
    """
    now = time.time() if now is None else now
    ours = product_key(product)
    if ours is not None and document["min_product"] > ours:
        return "from_newer_product"
    if role == "bundled":
        return "ok"
    if bundled is not None:
        if document["sequence"] < bundled["sequence"]:
            return "superseded"
        if bundled.get("requires_signature") and not document.get("requires_signature"):
            return "rejected"
    if document["published_at"] > now + FUTURE_SKEW_SECONDS:
        # The clock is behind, or the document is misdated. Either way nothing it verifies
        # is believed - but what it restricts still is, exactly as for an expired one.
        return "from_the_future"
    if document["expires_at"] is None or document["expires_at"] <= now:
        # Restrictive data never expires; the VERIFIED part of an expired cache does, and a
        # remote document that gives no expiry is treated as expired for that purpose.
        return "expired"
    return "ok"


# ------------------------------------------------------------------------------ resolution
def combine(results) -> str:
    """Several check results to one: any FAIL fails, then any that could not run, then any
    that did not apply. No checks at all is NOT_APPLICABLE."""
    results = [result if result in RESULTS else UNAVAILABLE for result in results]
    if not results:
        return NOT_APPLICABLE
    for result in (FAIL, UNAVAILABLE, NOT_APPLICABLE):
        if result in results:
            return result
    return PASS


def resolve(local, evidence):
    """(state, reason) for one capability. `local` is one of RESULTS; `evidence` is
    VERIFIED, INCOMPATIBLE or None. Local always wins; remote data only ever restricts,
    or elevates a local PASS."""
    if local not in RESULTS:
        local = UNAVAILABLE
    if evidence not in (VERIFIED, INCOMPATIBLE):
        evidence = None
    if local == FAIL:
        return INCOMPATIBLE, "local_check_failed"
    if evidence == INCOMPATIBLE:
        return INCOMPATIBLE, "registry_incompatible"
    if local in (UNAVAILABLE, NOT_APPLICABLE):
        return UNKNOWN, "local_check_unavailable"
    if evidence == VERIFIED:
        return VERIFIED, "registry_verified"
    return COMPATIBLE, "local_checks_passed"


def _in_range(key, advisory) -> bool:
    if key is None:
        return False
    if advisory["low"] is not None and key < advisory["low"]:
        return False
    if advisory["high"] is not None and key >= advisory["high"]:
        return False
    return True


def evidence_for(capability, version, sources):
    """(state, source, registry_reason) for one capability, from the documents in force.

    `sources` is a list of ``(name, document, verified_allowed)``. INCOMPATIBLE is the union
    over every source (an expired cache's restrictions included), so remote data can never
    lift a bundled INCOMPATIBLE; VERIFIED needs an exact version match in a source whose
    VERIFIED data is in force.
    """
    key = parse_version(version)
    for name, document, _ in sources:
        if document is None:
            continue
        claim = document["engines"].get(version, {}).get(capability) if isinstance(version, str) else None
        if claim and claim["state"] == INCOMPATIBLE:
            return INCOMPATIBLE, name, claim["reason"]
        for advisory in document["advisories"]:
            if capability in advisory["capabilities"] and _in_range(key, advisory):
                return INCOMPATIBLE, name, advisory["reason"]
    if key is None:
        return None, None, None
    for name, document, verified_allowed in sources:
        if document is None or not verified_allowed:
            continue
        claim = document["engines"].get(version, {}).get(capability)
        if claim and claim["state"] == VERIFIED:
            return VERIFIED, name, None
    return None, None, None


def evaluate(checks, *, version, sources) -> dict:
    """Every capability's state from the local check results and the documents in force."""
    capabilities = {}
    for name, (needed, tier) in CAPABILITIES.items():
        local = combine(checks.get(check, UNAVAILABLE) for check in needed)
        evidence, origin, why = evidence_for(name, version, sources)
        state, reason = resolve(local, evidence)
        if not needed and reason == "local_check_unavailable":
            reason = "not_implemented"
        entry = {"state": state, "reason": reason,
                 "source": origin if reason in ("registry_incompatible", "registry_verified") else "local",
                 "tier": tier}
        if reason == "registry_incompatible":
            entry["registry_reason"] = why
        capabilities[name] = entry
    return capabilities


def aggregate(capabilities, names=SEND_GATE) -> str:
    """The worst state over `names`, in the heartbeat's stored vocabulary."""
    worst = VERIFIED
    for name in names:
        entry = capabilities.get(name) if isinstance(capabilities, dict) else None
        state = entry.get("state") if isinstance(entry, dict) else UNKNOWN
        state = state if state in _ORDER else UNKNOWN
        if _ORDER[state] < _ORDER[worst]:
            worst = state
    return COARSE[worst]


# The engine-level checks of a backend the watcher accepted: `windows.Backend._compatible()`
# accepts a binary only when all of them pass, and discovery accepts exactly one.
ACCEPTED_CHECKS = {"official_location": PASS, "version_runs": PASS, "queue_flags": PASS,
                   "single_candidate": PASS}


def accepted_word(version, sources) -> str:
    """The gate's word for an engine that passed its local checks, from the registry data
    in force: `verified`, `structurally_compatible` or `incompatible`. The watcher's gate,
    `status`, `doctor` and the start-up log all say this, so they cannot disagree."""
    capabilities = evaluate(ACCEPTED_CHECKS, version=version if isinstance(version, str) else None,
                            sources=sources)
    return aggregate(capabilities)


def verified_versions(document) -> tuple:
    """Exact versions a document marks VERIFIED for sending (exact_thread_recovery)."""
    if not document:
        return ()
    return tuple(sorted(version for version, claims in document["engines"].items()
                        if claims.get("exact_thread_recovery", {}).get("state") == VERIFIED))


# ------------------------------------------------------------------------------ the report
def _finite_number(value):
    return (not isinstance(value, bool) and isinstance(value, (int, float))
            and math.isfinite(value))


def _epoch_or_none(value):
    if value is None:
        return None
    if not _finite_number(value) or not EPOCH_MIN <= value <= EPOCH_MAX:
        raise ValueError("epoch")
    return float(value)


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
        if item["state"] == VERIFIED and item["reason"] != "registry_verified":
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
        if not _finite_number(checked) or not EPOCH_MIN <= checked <= EPOCH_MAX:
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
    """The compatibility summary a model may read: codes and one timestamp, nothing else -
    no version string, no path, no free text."""
    view = view if isinstance(view, dict) else unusable_view("invalid")
    data = view.get("data") or {}
    return {"status": view.get("status") if view.get("status") in VIEW_STATUSES else "invalid",
            "overall": view.get("overall") if view.get("overall") in ENGINE_STATES else "unknown",
            "source": data.get("source") if data.get("source") in DATA_SOURCES else "none",
            "checked_at": view.get("checked_at") if _finite_number(view.get("checked_at")) else None,
            "capabilities": {name: {"state": entry["state"], "reason": entry["reason"]}
                             for name, entry in (view.get("capabilities") or {}).items()
                             if name in CAPABILITIES and entry.get("state") in STATES
                             and entry.get("reason") in REASONS}}


# ------------------------------------------------------------------------------ v0.6.6
PERMIT_REASONS = frozenset({
    "allowed", "incompatible", "unknown", "not_opted_in", "not_verified",
    "not_acknowledged_for_this_engine", "unsupported_tier",
})


def permits(view, capability, *, tier, opt_in=False, engine_version=None,
            acknowledged_version=None):
    """(allowed, reason) for doing `capability` at `tier`. Never raises; UNKNOWN is never
    allowed and INCOMPATIBLE is never overridable by an opt-in.

    * conservative - VERIFIED or COMPATIBLE (today's behaviour: requiring VERIFIED would
      switch off every machine on an unverified Codex build);
    * advanced     - an opt-in and VERIFIED;
    * experimental - an opt-in, VERIFIED or COMPATIBLE, and an acknowledgement given for
      this exact engine version, so an opt-in does not carry silently into a build nobody
      has looked at;
    * unsupported  - never.
    """
    try:
        entry = (view.get("capabilities") or {}).get(capability) if isinstance(view, dict) else None
        state = entry.get("state") if isinstance(entry, dict) else UNKNOWN
        if state not in STATES:
            state = UNKNOWN
        if tier not in TIERS or tier == "unsupported":
            return False, "unsupported_tier"
        if state == INCOMPATIBLE:
            return False, "incompatible"
        if state == UNKNOWN:
            return False, "unknown"
        if tier == "conservative":
            return True, "allowed"
        if opt_in is not True:
            return False, "not_opted_in"
        if tier == "advanced":
            return (True, "allowed") if state == VERIFIED else (False, "not_verified")
        reported = (view.get("engine") or {}).get("version")
        if (not isinstance(engine_version, str) or engine_version != reported
                or acknowledged_version != engine_version):
            return False, "not_acknowledged_for_this_engine"
        return True, "allowed"
    except Exception:
        return False, "unknown"
