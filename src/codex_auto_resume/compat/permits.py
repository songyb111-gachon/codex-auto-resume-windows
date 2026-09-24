"""What may be done at a tier, and with whose word (v0.6.11's opt-in gate).

Never raises, and UNKNOWN is never permission. The one part of the registry that is
policy rather than data, which is why tests/test_stack.py places it apart.
"""
from __future__ import annotations

from ..domain.vocabulary import (PermitReason)
from .model import (FAILED_HERE, INCOMPATIBLE, STATES, TIERS, UNKNOWN, VERIFIED)

# ------------------------------------------------------------------------------ v0.6.11
PERMIT_REASONS = frozenset(PermitReason)


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
        if state in (INCOMPATIBLE, FAILED_HERE):  # failed here fails a check, as incompatible does
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
