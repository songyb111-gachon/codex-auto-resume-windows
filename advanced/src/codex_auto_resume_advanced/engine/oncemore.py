# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""Once more when unsure: the advanced edition's answer at P7 for an uncertain submission (v0.6.14).

The standard edition never sends a continuation again once its delivery is uncertain (standards 0.2,
A6, E2, H2): it follows it for a day in case it arrives, and otherwise leaves it as uncertain. Core
asks P7 about one such record right after a look of its watch found no trace of it - its marker, or
the client id it went under, neither in Codex's history nor in its queue (core's engine/resend.py) -
and this answers RESEND for it, once:

* only for one core holds as `submission_unknown` and could resend (machine.resend_candidate): its
  send's answer was unknown or no receipt came, between 15 minutes and 6 hours ago, Codex never seen
  holding it, never resent, not cancelled, held or carried by a route;
* never one this edition has a resend of already, by this capability or Keep on's Send again
  (state.resent, the RESEND_ONCE overrides the claim writes);
* never one whose send was paid for by a capability that is a channel or a route (SENDER, UNLOADED):
  what such a channel did besides queueing - a goal set active, say - is not core's to repeat, and a
  channel's own Send again is the only way such a send goes once more.

Everything else is core's to prove, and core proves it before it sends, at every gate a send passes,
with this edition's other capabilities asked at each (engine/resend.py); the claim pays one unit and
writes RESEND_ONCE, or holds (ledger.py). A resend found twice afterwards turns this capability off,
whether or not it is kept on (arming.py).

It holds no memory of its own: what it asks is the state's, through its view (state.Scoped).
"""
from __future__ import annotations

import math
import time

from codex_auto_resume import machine
from codex_auto_resume.domain.plug import DEFER, Alternative

CAPABILITY = "once_more_when_unsure"
UNKNOWN = "submission_unknown"
# How long after its send an uncertain submission may be sent once more, in seconds: core's own
# window (engine/options.py, resend_after_seconds and resend_until_seconds), held here again as this
# capability's own restriction.
WINDOW = (900, 6 * 3600)


def claimed_at(record):
    """When the send of `record` core holds now was claimed, or None where that cannot be read."""
    at = record.get("last_claim_at") if isinstance(record, dict) else None
    if isinstance(at, bool) or not isinstance(at, (int, float)) or not math.isfinite(at):
        return None
    return at


def resendable(record, now) -> bool:
    """Whether core could send `record` once more now, from its own columns (machine.resend_candidate)."""
    if not isinstance(record, dict) or record.get("state") != UNKNOWN:
        return False
    try:
        return machine.resend_candidate(record, now, WINDOW)
    except Exception:                                # a record core would not hold: never resent
        return False


class OnceMore:
    """The capability's code: its hook at P7. `bind` gives it the runtime's clock and the state's two
    reads it asks (state.Scoped): whether a record was resent, and whether a channel paid for its send."""
    __slots__ = ("paths", "_scoped")

    def __init__(self, paths):
        self.paths = paths
        self._scoped = None

    def bind(self, scoped):
        self._scoped = scoped

    def schedule(self, record, due):
        """P7: RESEND for an uncertain submission core could send once more, that this edition never
        resent and no channel paid for; DEFER for everything else."""
        scoped = self._scoped
        now = scoped.now() if scoped is not None else time.time()
        if scoped is None or not resendable(record, now):
            return DEFER
        key = record.get("interruption_id")
        try:
            if scoped.resent(key) or scoped.channel_paid(key, claimed_at(record)):
                return DEFER
        except Exception:                            # a state that cannot be read resends nothing
            return DEFER
        return Alternative.RESEND


def make(paths) -> OnceMore:
    """The capability's factory (registry.CapabilityDef.make): its code for one installation."""
    return OnceMore(paths)
