# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""The Dashboard's account card (account_switch, v0.6.20): which Codex account is signed in.

`advanced-account` is the long-lived bridge's, the Dashboard's alone (surfaces.py, K3) - no MCP tool, the icon, a
card or anything remote reaches it. Only while account_switch stands on or is watched: off, nothing is read. It reads
the account with account/read in the Dashboard's own process (codex/account.read) and answers the plan word, the kind
and the address masked (codex/account.mask) - the address itself never leaves this function, and nothing of it is
written anywhere - and whether the card offers Codex's own sign-out and sign-in: only while the capability is on and
MAL passed on the Codex in force; until then the card says how to switch in Codex instead (the narrower route).

`advanced-account-switch` is that button, after the window asked first: Codex's own `codex logout` then `codex login`
(codex/account.switch), on a thread of this process's own - the one caller of `switch` - so the bridge answers at once
and the card reads `switch` (waiting, then the outcome word) with `advanced-account`; while it waits, the account is not
read. One at a time per installation. Refused off or watched (NOT_ON), before MAL passed (SWITCH_UNMEASURED) and while
one waits (SWITCH_RUNNING). Each is counted in the journal: asked, then signed in, not signed in, or failed.
"""
from __future__ import annotations

import threading
from pathlib import Path

from ..codex import account
from ..vocabulary import ArmingState, Measurement, Refusal
from .resets import _refused, _standing

CAPABILITY = account.CAPABILITY
WAITING = "waiting"
# The journal's word for each outcome (registry.ACCOUNT_SWITCH.codes).
COUNTED = {account.SIGNED_IN: "signed_in", account.CANCELLED: "not_signed_in", account.TIMED_OUT: "switch_failed",
           account.FAILED: "switch_failed"}
# {an installation's home: WAITING or the last switch's outcome}, for the life of the Dashboard's process.
_SWITCHES = {}
_LOCK = threading.Lock()


def _home(runtime):
    return Path(runtime.paths.home)


def switching(runtime):
    """WAITING while a switch of this installation's waits, else the last one's outcome word, or None."""
    with _LOCK:
        return _SWITCHES.get(_home(runtime))


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
    state = switching(runtime)
    found = account.parse(None) if state == WAITING else (reader or account.read)(runtime.paths)
    present = found.get("present")
    return {"done": True, "refusal": None, "present": present,
            "plan": found.get("plan_word") if present else None, "kind": found.get("kind") if present else None,
            "mask": account.mask(found.get("email")) if present else None, "button": offered(runtime),
            "switch": state}


def _count(runtime, code) -> None:
    try:
        runtime.state.counted(CAPABILITY, code)
    except Exception:
        pass


def switch(runtime, *, start=None, run=None) -> dict:
    """advanced-account-switch: Codex's own sign-out and sign-in started on a thread of its own; `start` (how the thread
    is started, `start(target)`) and `run` (codex/account.switch's shape, given the paths) are a test's."""
    if not offered(runtime):
        if runtime.states(fresh=True).get(CAPABILITY, ArmingState.OFF) != ArmingState.ARMED:
            return _refused(Refusal.NOT_ON)
        return _refused(Refusal.SWITCH_UNMEASURED)
    home = _home(runtime)
    with _LOCK:
        if _SWITCHES.get(home) == WAITING:
            return _refused(Refusal.SWITCH_RUNNING)
        _SWITCHES[home] = WAITING
    _count(runtime, "switch_asked")
    paths = runtime.paths
    work = run or account.switch

    def target():
        try:
            outcome = work(paths)
        except Exception:
            outcome = account.FAILED
        outcome = outcome if outcome in account.OUTCOMES else account.FAILED
        with _LOCK:
            _SWITCHES[home] = outcome
        _count(runtime, COUNTED[outcome])
    try:
        (start or (lambda job: threading.Thread(target=job, name="account-switch", daemon=True).start()))(target)
    except Exception:
        with _LOCK:
            _SWITCHES[home] = account.FAILED
        return _refused(Refusal.STATE_UNAVAILABLE)
    return {"done": True, "refusal": None, "switch": WAITING}
