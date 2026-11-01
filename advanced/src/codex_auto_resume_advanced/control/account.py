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

v0.6.20 final (the owner, 2026-11-01: ask, then restart): the running Codex app does not follow a sign-in made with
`codex login` until it is restarted (MAL failed partial; plans/measure-20261101b-result.md). So a switch that signed in
leaves the card asking "Restart Codex now so it uses the new account?" (`restart` ASK). `advanced-account-restart` is the
answer: {"now": false} is Not now (NOT_NOW: the card says Codex needs a restart, and still offers it); {"now": true}
restarts Codex (codex/restart.restart) on a thread of its own - only while nothing runs or waits (codex/restart.busy:
refused RESTART_BUSY otherwise, and the card offers it again once it is clear), only after a sign-in this Dashboard made
(NOTHING_TO_RESTART), one at a time (RESTART_RUNNING). While it is asked or runs, the card shows the account read when
the sign-in ended, and Codex is not asked again; once it has ended, the account is read afresh. The button - and so all
of this - stands on MALR, the measurement of exactly this route, in place of MAL (`offered`); MAL stays the record of
the plain route (measured.py).
"""
from __future__ import annotations

import threading
from pathlib import Path

from ..codex import account, restart as restarts
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
# v0.6.20 final: the restart after a sign-in - asked, put off, running, or what it came to (codex/restart.OUTCOMES) - and
# the card's account as read when the sign-in ended ({present, plan, kind, mask}: the address only masked), per home.
ASK, NOT_NOW, RESTARTING = "ask", "not_now", "restarting"
# The states Restart may be pressed in: asked, put off, or a restart that did not get Codex going again.
RESTARTABLE = frozenset({ASK, NOT_NOW, restarts.NOT_ENDED, restarts.NOT_STARTED, restarts.FAILED})
_RESTARTS = {}
_SHOWN = {}
# The journal's word for each restart outcome (registry.ACCOUNT_SWITCH.codes), and for how Codex ended.
RESTART_COUNTED = {restarts.RESTARTED: "restarted", restarts.SIGNED_OUT: "restarted",
                   restarts.NOT_RUNNING: "restart_not_needed", restarts.NOT_ENDED: "restart_failed",
                   restarts.NOT_STARTED: "restart_failed", restarts.FAILED: "restart_failed"}
ENDED_COUNTED = {restarts.CLOSED: "codex_closed", restarts.ENDED: "codex_ended"}


def _home(runtime):
    return Path(runtime.paths.home)


def switching(runtime):
    """WAITING while a switch of this installation's waits, else the last one's outcome word, or None."""
    with _LOCK:
        return _SWITCHES.get(_home(runtime))


def restarting(runtime):
    """The restart after this installation's last sign-in: ASK, NOT_NOW, RESTARTING, what it came to, or None."""
    with _LOCK:
        return _RESTARTS.get(_home(runtime))


def offered(runtime) -> bool:
    """Whether the card offers the button: the capability on - not watched - and MALR passed on the Codex in force (the
    sign-in, then the restart; v0.6.20 final, in place of MAL)."""
    try:
        return (runtime.states(fresh=True).get(CAPABILITY, ArmingState.OFF) == ArmingState.ARMED
                and runtime.arming.verdict(Measurement.MALR) == "pass")
    except Exception:
        return False


def failed(runtime) -> bool:
    """Whether MALR failed - on whichever Codex, as a statement's warnings read a fail (arming.verdict): the card then says
    its button is hidden because the measurement failed, not that it has not been made (v0.6.20)."""
    try:
        return runtime.arming.verdict(Measurement.MALR) == "fail"
    except Exception:
        return False


def _shown(found) -> dict:
    """The card's account of an account read: {present, plan, kind, mask} - never the address."""
    present = found.get("present") if isinstance(found, dict) else None
    return {"present": present, "plan": found.get("plan_word") if present else None,
            "kind": found.get("kind") if present else None,
            "mask": account.mask(found.get("email")) if present else None}


def view(runtime, *, reader=None) -> dict:
    """advanced-account: {present, plan, kind, mask, button, measurement_failed} of the account signed in - `present` None
    where Codex could not be asked - or NOT_ON while the capability is off, with nothing read. `reader` is a test's
    (account.read's shape)."""
    if not _standing(runtime, CAPABILITY):
        return _refused(Refusal.NOT_ON)
    state = switching(runtime)
    asked = restarting(runtime)
    if state == WAITING:
        shown = _shown(account.parse(None))
    elif asked in RESTARTABLE or asked == RESTARTING:
        with _LOCK:
            shown = dict(_SHOWN.get(_home(runtime)) or _shown(account.parse(None)))
    else:
        shown = _shown((reader or account.read)(runtime.paths))
    button = offered(runtime)
    found = dict({"done": True, "refusal": None}, **shown)
    found.update({"button": button, "measurement_failed": failed(runtime), "switch": state,
                  "restart": asked if button else None, "busy": []})
    if button and asked in RESTARTABLE:
        found["busy"] = list(restarts.busy(runtime.paths))
    return found


def _count(runtime, code) -> None:
    try:
        runtime.state.counted(CAPABILITY, code)
    except Exception:
        pass


def switch(runtime, *, start=None, run=None, reader=None) -> dict:
    """advanced-account-switch: Codex's own sign-out and sign-in started on a thread of its own; `start` (how the thread
    is started, `start(target)`), `run` (codex/account.switch's shape, given the paths) and `reader` (account.read's,
    the card's account once it signed in) are a test's. One that signed in leaves the restart asked (ASK)."""
    if not offered(runtime):
        if runtime.states(fresh=True).get(CAPABILITY, ArmingState.OFF) != ArmingState.ARMED:
            return _refused(Refusal.NOT_ON)
        return _refused(Refusal.SWITCH_UNMEASURED)
    home = _home(runtime)
    with _LOCK:
        if _SWITCHES.get(home) == WAITING:
            return _refused(Refusal.SWITCH_RUNNING)
        _SWITCHES[home] = WAITING
        _RESTARTS.pop(home, None)
        _SHOWN.pop(home, None)
    _count(runtime, "switch_asked")
    paths = runtime.paths
    work = run or account.switch

    def target():
        try:
            outcome = work(paths)
        except Exception:
            outcome = account.FAILED
        outcome = outcome if outcome in account.OUTCOMES else account.FAILED
        shown = None
        if outcome == account.SIGNED_IN:
            try:
                shown = _shown((reader or account.read)(paths))
            except Exception:
                shown = _shown(account.parse(None))
        with _LOCK:
            _SWITCHES[home] = outcome
            if shown is not None:
                _SHOWN[home] = shown
                _RESTARTS[home] = ASK
        _count(runtime, COUNTED[outcome])
    try:
        (start or (lambda job: threading.Thread(target=job, name="account-switch", daemon=True).start()))(target)
    except Exception:
        with _LOCK:
            _SWITCHES[home] = account.FAILED
        return _refused(Refusal.STATE_UNAVAILABLE)
    return {"done": True, "refusal": None, "switch": WAITING}


def restart(runtime, argument, *, start=None, run=None) -> dict:
    """advanced-account-restart: {"now": false} puts the restart off (NOT_NOW); {"now": true} restarts Codex on a thread
    of its own, while nothing runs or waits. `start` (as `switch`'s) and `run` (codex/restart.restart's shape, given the
    paths) are a test's."""
    now = argument.get("now") if isinstance(argument, dict) else None
    if type(now) is not bool:
        return _refused(Refusal.INVALID_REQUEST)
    if not offered(runtime):
        if runtime.states(fresh=True).get(CAPABILITY, ArmingState.OFF) != ArmingState.ARMED:
            return _refused(Refusal.NOT_ON)
        return _refused(Refusal.SWITCH_UNMEASURED)
    home = _home(runtime)
    with _LOCK:
        asked = _RESTARTS.get(home)
        if asked == RESTARTING:
            return _refused(Refusal.RESTART_RUNNING)
        if asked not in RESTARTABLE:
            return _refused(Refusal.NOTHING_TO_RESTART)
        if not now:
            _RESTARTS[home] = NOT_NOW
            return {"done": True, "refusal": None, "restart": NOT_NOW}
    if restarts.busy(runtime.paths):
        return _refused(Refusal.RESTART_BUSY)
    with _LOCK:
        if _RESTARTS.get(home) not in RESTARTABLE:
            return _refused(Refusal.RESTART_RUNNING)
        _RESTARTS[home] = RESTARTING
    _count(runtime, "restart_asked")
    paths = runtime.paths
    work = run or restarts.restart

    def target():
        try:
            outcome, how = work(paths)
        except Exception:
            outcome, how = restarts.FAILED, None
        outcome = outcome if outcome in restarts.OUTCOMES else restarts.FAILED
        with _LOCK:
            _RESTARTS[home] = outcome
        if how in ENDED_COUNTED:
            _count(runtime, ENDED_COUNTED[how])
        _count(runtime, RESTART_COUNTED[outcome])
    try:
        (start or (lambda job: threading.Thread(target=job, name="account-restart", daemon=True).start()))(target)
    except Exception:
        with _LOCK:
            _RESTARTS[home] = restarts.FAILED
        return _refused(Refusal.STATE_UNAVAILABLE)
    return {"done": True, "refusal": None, "restart": RESTARTING}
