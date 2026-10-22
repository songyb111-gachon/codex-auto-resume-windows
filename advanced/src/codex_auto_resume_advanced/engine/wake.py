# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""Wake this PC for a reset (wake_for_reset, v0.6.19): a waitable timer for the earliest reset something waits for.

The standard edition can keep the PC awake while a task waits (core's power.py, runtime/waking.py), and looks again at
once when the PC wakes; it never wakes a sleeping PC on a schedule of its own (C4), and asks Windows only the listed
questions (B16). With this capability on, at P8 - once a tick, as an errand - the watcher finds the earliest time
something it waits for falls due:

* core's waiting usage-limit records: next_check_at of each record in category usage_limit (core's view, `records_in`);
* the reset actions' pending rules - a reset credit, a message of a person's own - that know when they act (`due_at`);
* the forced stop's held window (usage_pause): the reset its pause holds for (the meter's `paused_reset_at`).

The earliest of them all, less the lead a person chose (1, 2 or 5 minutes; 2 by default), is when a waitable timer of
the watcher's own wakes the PC (win/waketimer.py) - set, moved when that time changes, and cancelled when nothing waits
any more, when that time has come (the watcher is awake to act then), or when Windows does not allow wake timers for the
power source in use: the product never changes that setting (F1); the statement says where it is. Waking only lets the
watcher run its ordinary tick sooner: every gate a recovery passes is unchanged.

Cancelled too when recovery is paused or the capability is turned off. Neither asks P8 again - a pause asks the plug
nothing, a capability off is asked nothing - so a small watch on a thread of its own looks every WATCH_EVERY seconds
and takes the timer back once the capability no longer stands on, or no tick has come for STALE seconds. And when the
watcher stops, Windows drops the timer with the handle: a PC is never woken for a watcher that is not there.

Measurement MWAKE (whether such a timer wakes this PC - Modern Standby, the lid, the battery) is the measurement
session's; until it passes the statement carries the warning that it was not measured.
"""
from __future__ import annotations

import threading

from codex_auto_resume.domain.plug import DEFER

from ..vocabulary import OptionKey

CAPABILITY = "wake_for_reset"
LEADS = (1, 2, 5)
DEFAULT_LEAD = 2
# How often the watch looks whether the timer is still wanted, and how long with no tick it waits before it lets go.
WATCH_EVERY = 15
STALE = 180
# How long Windows' answer about wake timers is taken as read.
ASK_EVERY = 60
# Core's waiting states, and the category a usage-limit record is in.
WAITING = "WAITING"
USAGE_LIMIT = "usage_limit"


def _number(value):
    return float(value) if type(value) in (int, float) and value > 0 else None


class _Errand:
    """Run last in the tick, after the other capabilities' errands - the reset actions' and the forced stop's among
    them - so the due times it reads are the ones they just kept."""
    __slots__ = ("code", "view")

    def __init__(self, code, view):
        self.code, self.view = code, view

    def run(self, guard):
        try:
            due = self.code.earliest(self.view)
        except Exception:                              # noqa: BLE001 - what cannot be read wakes nothing
            due = None
        self.code.apply(due)
        return None


class WakeForReset:
    """wake_for_reset's code: its P8 errand and the watch beside it. `timer` (win/waketimer.WakeTimer's shape) and
    `start` (how the watch's thread is started, `start(target)`) are the seams a test fills; no real timer is set and no
    thread is started in a test."""
    __slots__ = ("paths", "_scoped", "_timer", "_start", "_lock", "_ticked", "_watching", "_allowed", "_asked")

    def __init__(self, paths, *, timer=None, start=None):
        self.paths = paths
        self._scoped = None
        self._timer = timer
        self._start = start or (lambda target: threading.Thread(target=target, name="wake-timer", daemon=True).start())
        self._lock = threading.Lock()
        self._ticked = None
        self._watching = False
        self._allowed, self._asked = None, None

    def bind(self, scoped):
        self._scoped = scoped

    def timer(self):
        if self._timer is None:
            from ..win.waketimer import WakeTimer
            self._timer = WakeTimer()
        return self._timer

    # ------------------------------------------------------------------ P8
    def tick(self, view):
        if self._scoped is None:
            return DEFER
        return _Errand(self, view)

    def earliest(self, view):
        """The earliest time something waits for that is still to come, in Unix seconds, or None."""
        from codex_auto_resume.domain import states
        now = self._scoped.now()
        found = []
        for row in view.records_in(getattr(states, WAITING)):
            if row.get("category") == USAGE_LIMIT:
                found.append(_number(row.get("next_check_at")))
        for rule in self._scoped.resets.reset_rules():
            found.append(_number(rule.get("due_at")))
        for row in self._scoped.meter.rows().values():
            held = row.get("paused_reset_at")
            if held is not None and held == row.get("reset_at"):
                found.append(_number(held))
        later = [when for when in found if when is not None and when > now]
        return min(later) if later else None

    def lead(self) -> int:
        value = (self._scoped.options() or {}).get(OptionKey.WAKE_LEAD_MINUTES, DEFAULT_LEAD)
        return value if value in LEADS else DEFAULT_LEAD

    def apply(self, due):
        """The errand: the timer set for `due` less the lead, moved, or cancelled - and the watch started."""
        scoped = self._scoped
        now = scoped.now()
        with self._lock:
            self._ticked = now
        timer = self.timer()
        wake_at = None if due is None else due - 60 * self.lead()
        if wake_at is None or wake_at <= now:
            if timer.cancel():
                scoped.count("cancelled")
            return
        if not self._windows_allows(now):
            if timer.cancel():
                scoped.count("cancelled")
            return
        if timer.due == wake_at:
            self._watch()
            return
        first = timer.due is None
        if timer.set(wake_at):
            if first:
                scoped.count("set")          # a move is not counted: core's next look moves it often
            self._watch()

    def _windows_allows(self, now) -> bool:
        """Windows' Allow wake timers for the power source in use, asked at most once in ASK_EVERY seconds; a change to
        not allowed is counted once."""
        if self._asked is None or not 0 <= now - self._asked < ASK_EVERY:
            allowed = self.timer().allowed() is True
            if not allowed and self._allowed is not False:
                self._scoped.count("not_allowed")
            self._allowed, self._asked = allowed, now
        return self._allowed is True

    # ------------------------------------------------------------------ the watch
    def _watch(self):
        with self._lock:
            if self._watching:
                return
            self._watching = True
        try:
            self._start(self._loop)
        except Exception:                              # noqa: BLE001
            with self._lock:
                self._watching = False

    def _loop(self):
        import time
        while self.look():
            time.sleep(WATCH_EVERY)

    def look(self) -> bool:
        """One look of the watch: the timer cancelled where the capability no longer stands on or no tick came for
        STALE seconds (a pause, a capability off). Whether to go on looking - not once nothing is set."""
        scoped, timer = self._scoped, self.timer()
        if timer.due is None:
            with self._lock:
                self._watching = False
            return False
        with self._lock:
            ticked = self._ticked
        try:
            standing = scoped.armed(CAPABILITY) is True
            fresh = ticked is not None and 0 <= scoped.now() - ticked < STALE
        except Exception:                              # noqa: BLE001
            standing = fresh = False
        if standing and fresh:
            return True
        timer.cancel()
        try:
            scoped.count("cancelled")
        except Exception:                              # noqa: BLE001 - counted only while on
            pass
        with self._lock:
            self._watching = False
        return False


def make(paths) -> WakeForReset:
    return WakeForReset(paths)
