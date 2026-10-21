# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""Send notices to your phone or inbox (push_notices, v0.6.19, plans/v0619-design/D-courier.md).

At P20 core tells the plug of each notice it hands to the card or the toast - its kind, its category word, its record's
place in Pending and when, closed words and numbers only (core's notifier.told). Here that kind is mapped to a closed
event (KINDS; a kind not in it is not pushed), held to the events the person picked (OptionKey.PUSH_EVENTS, a bit set
in EVENTS' order) and to the channels they switched on, and written to the outbox, one row a channel - only while it
stands on and recovery is not paused (K5), and only as far as the outbox's 30 an hour leaves room. Watched, nothing is
written: the answer says it would have been pushed, and the journal keeps that.

The told call never waits for anything and never starts the courier: it writes and returns, so no notice is delayed
(E11). At P8 the errand starts the courier where a row waits (courier/launch.start_due: at most once a minute). This
edition's own notices - the update check's offer, the meter's warning, the forced stop's - reach P20 the same way,
because they go through core's notifier.
"""
from __future__ import annotations

from codex_auto_resume.domain.plug import DEFER, Point

from ..vocabulary import CourierChannel, CourierEvent, OptionKey

CAPABILITY = "push_notices"
# The events a person may pick, in the bit set's order (the test notice is the card's, never picked).
EVENTS = tuple(event for event in CourierEvent if event != CourierEvent.TEST)
# The notifier's kinds (core's notifier.build) as the events they are; an interruption is one for a usage limit alone.
KINDS = {"resumed": CourierEvent.RECOVERED, "failed": CourierEvent.FAILED, "stopped": CourierEvent.FAILED,
         "needs_you": CourierEvent.NEEDS_YOU, "memory_stopped": CourierEvent.STOPPED_UNEXPECTEDLY,
         "restarted": CourierEvent.RESTARTED, "update_offered": CourierEvent.UPDATE_OFFERED}
USAGE_LIMIT = "usage_limit"
SWITCH = (1, 2)                           # a channel's switch: 1 on, 2 off (registry SWITCH)
ON, OFF = SWITCH


def bit(event) -> int:
    return 1 << EVENTS.index(CourierEvent(event))


DEFAULT_EVENTS = sum(bit(event) for event in (CourierEvent.USAGE_LIMIT_DETECTED, CourierEvent.RECOVERED,
                                               CourierEvent.FAILED, CourierEvent.NEEDS_YOU))
EVENT_CHOICES = tuple(range(1, 1 << len(EVENTS)))


def event_of(facts):
    """The closed event of a notice core told of, or None: one not pushed."""
    if not isinstance(facts, dict):
        return None
    kind = facts.get("kind")
    if kind == "interruption":
        return CourierEvent.USAGE_LIMIT_DETECTED if facts.get("category") == USAGE_LIMIT else None
    return KINDS.get(kind) if isinstance(kind, str) else None


def picked(bits, event) -> bool:
    return type(bits) is int and bool(bits & bit(event))


class _Errand:
    __slots__ = ("code", "now")

    def __init__(self, code, now):
        self.code, self.now = code, now

    def run(self, guard):
        self.code._launch(self.code.paths, self.now)
        return None


class PushNotices:
    """push_notices' code: its P20 hook and its P8 errand. `paused` and `launch` are seams a test fills: whether
    recovery is paused (the compatibility report's read of core's switch) and how the courier is started."""
    __slots__ = ("paths", "_scoped", "_paused", "_launch")

    def __init__(self, paths, *, paused=None, launch=None):
        self.paths = paths
        self._scoped = None
        self._paused = paused or _paused
        self._launch = launch or _start

    def bind(self, scoped):
        self._scoped = scoped

    def notice(self, facts):
        """P20: the notice written to the outbox for each channel switched on, while on; Point.NOTICE - what it did
        or would have done - or DEFER where it is not one to push."""
        scoped = self._scoped
        event = event_of(facts)
        if scoped is None or event is None:
            return DEFER
        options = scoped.options()
        if not picked(options.get(OptionKey.PUSH_EVENTS), event):
            return DEFER
        channels = [channel for channel in CourierChannel if options.get(OptionKey(str(channel))) == ON]
        if not channels:
            return DEFER
        if not scoped.armed(CAPABILITY):
            return Point.NOTICE                     # watched: journalled as what it would have pushed
        if self._paused(self.paths) is not False:
            return DEFER                            # paused, or that cannot be told: nothing is written (K5)
        from ..courier.outbox import alias
        category = facts.get("category") if isinstance(facts.get("category"), str) else None
        at = facts.get("at") if isinstance(facts.get("at"), (int, float)) else scoped.now()
        written = scoped.outbox.enqueue(channels, event, category, alias(facts.get("alias_index")), float(at))
        return Point.NOTICE if written else DEFER

    def tick(self, view):
        """P8: the courier started where a row of the outbox waits (at most once a minute)."""
        scoped = self._scoped
        if scoped is None:
            return DEFER
        try:
            now = scoped.now()
            return _Errand(self, now) if scoped.outbox.waiting(now) else DEFER
        except Exception:
            return DEFER


def _paused(paths):
    from ..report.records import paused
    return paused(paths)


def _start(paths, now):
    from ..courier import launch
    return launch.start_due(paths, now)


def make(paths) -> PushNotices:
    return PushNotices(paths)
