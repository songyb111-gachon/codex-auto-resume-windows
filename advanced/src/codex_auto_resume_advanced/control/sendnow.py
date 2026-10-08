# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""Send now: one waiting recovery a person chose, sent at the watcher's next look (v0.6.14).

The standard edition sends a continuation only when its schedule says, at least fifteen minutes after
the last one in the same conversation, and never past the attempt budget (A8, A20, A21, H2); Retry now
only brings the next check forward. With this capability on, the Dashboard can ask, for one waiting
recovery, that it go at the next look instead: core then passes, for that one look, the wait before
its next try, a postponement, the minutes before a first send, the fifteen minutes between two
continuations and an attempt budget the person set that is used up - never one an administrator set -
and every other check runs (core's engine/relaxed.py, SEND_NOW).

The request (`request`, the bridge's advanced-send-now) names one record by its interruption id, as
the Dashboard's other per-record actions do, and is taken only while this capability stands on - not
watched, not read down by a policy: a click that could only be journalled would be a request left
lying for a later arm. It is a FORCE_ONCE override of that record, renewed by a second click, that
lapses after fifteen minutes; the watcher is woken as Retry now wakes it. The hook at P7 answers
SEND_NOW only for a record core holds as waiting with such a request, made since this capability last
stood where it stands - so turning it off, or watching it, voids every request made before, and so
does a policy that reads it down (arming.py, sweep). The claim checks the same again and uses the
request (ledger.py): one click, one claim. Anything that cannot be read is no request, and the
record waits for its schedule as the standard edition's would.
"""
from __future__ import annotations

from codex_auto_resume import machine
from codex_auto_resume.domain import ids
from codex_auto_resume.domain.plug import DEFER, Alternative

from ..vocabulary import ArmingState, OverrideKind, Refusal

CAPABILITY = "send_now"
# How long a request stands, in seconds.
LIFETIME = 900
REQUESTED = "requested"


def fresh(override, since, now) -> bool:
    """Whether a FORCE_ONCE `override` is one a send may still use at `now`: unused, younger than
    LIFETIME and made at or after `since`, when the capability last stood where it stands. Pure."""
    if not isinstance(override, dict) or override.get("used_at") is not None:
        return False
    if override.get("kind") != OverrideKind.FORCE_ONCE:
        return False
    made = override.get("created_at")
    numbers = all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in (made, since))
    return numbers and made >= since and 0 <= now - made < LIFETIME


def wake(paths) -> bool:
    """Wake the watcher, as Retry now does (core's control/actions.py): its next look comes now."""
    from codex_auto_resume.windows import WakeEvent
    return bool(WakeEvent(str(paths.state_dir)).signal())


def request(runtime, interruption_id) -> dict:
    """advanced-send-now: a person's request, in the Dashboard, that the waiting recovery
    `interruption_id` go at the watcher's next look. Refused for an id of the wrong shape
    (INVALID_REQUEST), for a registry that has no Send now (UNKNOWN_CAPABILITY), and unless it stands
    on now (NOT_ON) - watched, or read down to watched or off by a policy, included. It cannot see
    core's record and need not: the hook answers only for one core holds as waiting."""
    if not ids.is_interruption_id(interruption_id):
        return {"done": False, "refusal": Refusal.INVALID_REQUEST}
    if runtime.registry.get(CAPABILITY) is None:
        return {"done": False, "refusal": Refusal.UNKNOWN_CAPABILITY}
    if runtime.states(fresh=True).get(CAPABILITY, ArmingState.OFF) != ArmingState.ARMED:
        return {"done": False, "refusal": Refusal.NOT_ON}
    now = runtime.clock()
    from ..state import StateError
    try:
        runtime.state.renew_override(interruption_id, CAPABILITY, OverrideKind.FORCE_ONCE, at=now)
        runtime.state.counted(CAPABILITY, REQUESTED, at=now)
    except StateError:
        return {"done": False, "refusal": Refusal.STATE_UNAVAILABLE}
    try:
        wake(runtime.paths)
    except Exception:
        pass                                         # the request stands; the next look finds it
    return {"done": True, "refusal": None, "expires_at": now + LIFETIME}


class SendNow:
    """The capability's code: its hook at P7. `bind` gives it the runtime's clock, its own request of a
    record and since when it has stood where it stands (state.Scoped)."""
    __slots__ = ("paths", "_scoped")

    def __init__(self, paths):
        self.paths = paths
        self._scoped = None

    def bind(self, scoped):
        self._scoped = scoped

    def schedule(self, record, due):
        """P7: SEND_NOW for a record core holds as waiting that a person asked to send now, with a
        request still fresh (`fresh`); DEFER for everything else - an uncertain one among them."""
        scoped = self._scoped
        if (scoped is None or not isinstance(record, dict) or record.get("state") not in machine.WAITING
                or not ids.is_interruption_id(record.get("interruption_id"))):
            return DEFER
        try:
            asked = scoped.request(record["interruption_id"])
            since = scoped.since()
            now = scoped.now()
        except Exception:                            # what cannot be read is no request
            return DEFER
        return Alternative.SEND_NOW if fresh(asked, since, now) else DEFER


def make(paths) -> SendNow:
    """The capability's factory (registry.CapabilityDef.make): its code for one installation."""
    return SendNow(paths)
