# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""The Dashboard's account card (account_switch, v0.6.19): which Codex account is signed in.

`advanced-account` is the long-lived bridge's, the Dashboard's alone (surfaces.py, K3) - no MCP tool, the icon, a
card or anything remote reaches it. Only while account_switch stands on or is watched: off, nothing is read. It reads
the account with account/read in the Dashboard's own process (codex/account.read) and answers the plan word, the kind
and the address masked (codex/account.mask) - the address itself never leaves this function, and nothing of it is
written anywhere - and whether the card offers Codex's own sign-out and sign-in: only while the capability is on and
MAL passed on the Codex in force; until then the card says how to switch in Codex instead (the narrower route).
"""
from __future__ import annotations

from ..codex import account
from ..vocabulary import ArmingState, Measurement, Refusal
from .resets import _refused, _standing

CAPABILITY = account.CAPABILITY


def offered(runtime) -> bool:
    """Whether the card offers the button: the capability on - not watched - and MAL passed on the Codex in force."""
    try:
        return (runtime.states(fresh=True).get(CAPABILITY, ArmingState.OFF) == ArmingState.ARMED
                and runtime.arming.verdict(Measurement.MAL) == "pass")
    except Exception:
        return False


def view(runtime, *, reader=None) -> dict:
    """advanced-account: {present, plan, kind, mask, button} of the account signed in - `present` None where Codex could
    not be asked - or NOT_ON while the capability is off, with nothing read. `reader` is a test's (account.read's
    shape)."""
    if not _standing(runtime, CAPABILITY):
        return _refused(Refusal.NOT_ON)
    found = (reader or account.read)(runtime.paths)
    present = found.get("present")
    return {"done": True, "refusal": None, "present": present,
            "plan": found.get("plan_word") if present else None, "kind": found.get("kind") if present else None,
            "mask": account.mask(found.get("email")) if present else None, "button": offered(runtime)}
