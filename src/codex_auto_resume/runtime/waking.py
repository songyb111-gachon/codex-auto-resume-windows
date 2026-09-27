"""The watcher's side of sleep and of keeping this PC awake (v0.6.11; power.py says what each does).

Asked by the loop on the thread that ticks: before a tick, whether this PC slept since the last one,
which the engine is then told (engine/freshness.py); after it, whether to keep the PC awake; and when
the watcher stops, to let go of everything. At the defaults it asks Windows nothing - Ask after a long
sleep and Keep this PC awake are both off, so no listener is registered, no clock is compared and no
request is made - and the watcher waits as v0.6.10 waited.

Keeping awake is a request the thread that ticks holds (SetThreadExecutionState): made when a task
waits and the power allows it, and taken back when nothing waits, when the hours chosen are up for
this stretch of waiting, when recovery is paused, when a tick fails and when the watcher stops. A
stretch begins when something starts to wait and ends when nothing does, so the hours count once per
stretch, not once per tick. The PC's own power settings are never changed (F1).
"""
from __future__ import annotations

import threading
import time

from .. import power
from ..domain.vocabulary import KeepAwake
from ..machine import WAITING
from ..win import power as windows


class Waking:
    """One watcher's listener, clock readings and keep-awake request. `port` is win/power.py, or a
    test's stand-in with the same four names."""

    def __init__(self, *, signal, log, port=windows, clock=time.time):
        self._port, self._signal, self._log, self._clock = port, signal, log, clock
        self._woke = threading.Event()
        self._listener = None
        # (wall clock, time awake) at the last look, while listening; None otherwise.
        self._reading = None
        # Since when this PC is asked to stay awake, while it is; when this stretch of waiting began;
        # and whether its hours are up.
        self.awake_since = None
        self._stretch = None
        self._spent = False

    # ---------------------------------------------------------------- before a tick
    def before(self, engine, values) -> float:
        """Listen while a setting wants it, and tell `engine` if this PC slept since the last look.
        Returns the seconds it slept (0.0 for none). The reading is kept only once the engine has
        been told, so a tick that could not tell it sees the same sleep again."""
        if not power.listens(values):
            self._deafen()
            return 0.0
        self._listen()
        if engine is None:
            return 0.0
        awake = self._port.awake_seconds()
        now = (self._clock(), awake) if awake is not None else None
        woke = self._woke.is_set()
        slept = power.asleep(self._reading, now) if self._reading is not None and now is not None else 0.0
        if slept or woke:
            if slept:
                self._log("this PC slept for about %d minutes; looking again at everything that waits"
                          % int(slept // 60))
            engine.after_sleep(self._reading[0] if self._reading is not None else self._clock(), slept)
        self._woke.clear()
        self._reading = now
        return slept

    def _listen(self) -> None:
        if self._listener is None:
            listener = self._port.WakeListener(self._heard)
            if listener.start():
                self._listener = listener

    def _heard(self) -> None:
        """This PC woke: on a thread of Windows' own, so a flag and the wake event, and nothing else."""
        self._woke.set()
        try:
            self._signal()
        except Exception:
            pass

    def _deafen(self) -> None:
        listener, self._listener = self._listener, None
        if listener is not None:
            listener.stop()
        self._reading = None
        self._woke.clear()

    # ----------------------------------------------------------------- after a tick
    def after(self, store, values, *, ok: bool, paused: bool):
        """Keep this PC awake, or let it go, after a tick. Returns since when it is kept awake, or None."""
        mode = power.keep_awake(values)
        if mode == KeepAwake.OFF or paused:
            self._stretch, self._spent = None, False
            return self.let_go()
        if not ok:
            return self.let_go()        # nothing is known of what waits; the stretch goes on
        count = power.waiting(store.records_in(WAITING))
        now = self._clock()
        if count == 0:
            self._stretch, self._spent = None, False
            return self.let_go()
        if self._stretch is None:
            self._stretch = now
        if not self._spent and now - self._stretch >= power.awake_cap(values):
            self._spent = True
            if self.awake_since is not None:
                self._log("kept this PC awake for the hours chosen; it may sleep again")
        mains = self._port.on_mains() if mode == KeepAwake.ON_AC else None
        if self._spent or not power.wants_awake(mode, count, mains):
            return self.let_go()
        if self.awake_since is None and self._port.keep_awake(True):
            self.awake_since = now
            self._log("keeping this PC awake while %d task(s) wait" % count)
        return self.awake_since

    def let_go(self):
        """Take back the request to keep this PC awake, if one is held. Returns None."""
        if self.awake_since is not None:
            self.awake_since = None
            self._port.keep_awake(False)
            self._log("no longer keeping this PC awake")
        return None

    def stop(self) -> None:
        """The watcher stops: let go, and stop listening."""
        try:
            self.let_go()
        finally:
            self._deafen()
