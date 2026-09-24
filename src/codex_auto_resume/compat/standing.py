"""What a document says about a version: whether it may be used, which claim wins, and
on what evidence.
"""
from __future__ import annotations

import time

from .model import (CAPABILITIES, CHECKED, COARSE, COMPATIBLE, FAIL, FAILED_HERE,
                    FUTURE_SKEW_SECONDS, INCOMPATIBLE, NOT_APPLICABLE, PASS, RESULTS, SEND_GATE,
                    UNAVAILABLE, UNKNOWN, VERIFIED, _ORDER, parse_version, product_key)

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
    """(state, reason) for one capability. `local` is one of RESULTS; `evidence` is VERIFIED,
    CHECKED, INCOMPATIBLE or None. Local always wins; remote data only restricts or elevates a PASS."""
    if local not in RESULTS:
        local = UNAVAILABLE
    if evidence not in (VERIFIED, CHECKED, INCOMPATIBLE):
        evidence = None
    if local == FAIL:  # on a build the data vouches for, the cause is most likely this machine
        return (FAILED_HERE, "local_check_failed_here") if evidence in (VERIFIED, CHECKED) \
            else (INCOMPATIBLE, "local_check_failed")
    if evidence == INCOMPATIBLE:
        return INCOMPATIBLE, "registry_incompatible"
    if local in (UNAVAILABLE, NOT_APPLICABLE):
        return UNKNOWN, "local_check_unavailable"
    if evidence in (VERIFIED, CHECKED):
        return evidence, "registry_verified" if evidence == VERIFIED else "registry_checked"
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
    lift a bundled INCOMPATIBLE; VERIFIED or CHECKED needs an exact version match in a source
    whose trust is in force, and the best of them wins.
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
    best = (None, None, None)
    for name, document, verified_allowed in sources:
        claims = document["engines"].get(version, {}) if document and verified_allowed else {}
        claim = claims.get(capability)
        if claim and claim["state"] == VERIFIED:
            return VERIFIED, name, None
        best = (CHECKED, name, None) if claim and claim["state"] == CHECKED and best[0] is None else best
    return best


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
                 "source": origin if reason.startswith("registry_") else "local",
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
