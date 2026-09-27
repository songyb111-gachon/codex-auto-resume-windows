"""The watcher's side of its own health (v0.6.11): its memory, how it ended, and the status file.

Asked by the loop on the thread that ticks, after a tick has ended - never inside one:

* its memory (memguard.py): the peak, which the heartbeat keeps at every setting, and - only while the
  memory guard is on - whether it is over the limit: warned of once, or the watcher stops before the
  next tick, with its own exit code, and a notice says why;
* how it ended: `ended` is asked once as the watcher leaves on purpose, and writes that it did, so a
  reader can tell a watcher that stopped from one that stopped unexpectedly (control/watcher.py) - with
  the sign-in and the start of Windows it ran in, read once here (win/ownprocess.py);
* the status file for other tools (statusfile.py): written after every tick while its setting is on,
  once more as the watcher stops, and removed - once - when the setting is off.

At the defaults the guard is off and the status file is not written: all that happens is that the
watcher asks Windows about its own memory and writes the peak into its heartbeat, beside the rest.
"""
from __future__ import annotations

import time

from .. import config, memguard, statusfile
from ..domain.vocabulary import NoticeKind
from ..win import ownprocess


class Health:
    """One watcher's memory readings, warning and status file. `port` is win/ownprocess.py, or a test's
    stand-in with the same three names; `notice(event, detail, final=...)` raises a notice."""

    def __init__(self, *, paths, log, notice, port=None, clock=time.time):
        port = ownprocess if port is None else port
        self._paths, self._log, self._notice, self._port, self._clock = paths, log, notice, port, clock
        # Private memory committed at the last look, and the most so far, in bytes; None until known.
        self.private = None
        self.peak = None
        self.warned = False
        # Which sign-in this watcher runs in, and when Windows started: asked once, as it starts.
        self.sign_in = port.sign_in()
        self.booted_at = port.booted_at()
        # Whether the status file was being written at the last look: None before the first.
        self._writing = None

    # ------------------------------------------------------------------ memory
    def look(self) -> None:
        """Ask Windows how much memory this process has committed now, and the most it has."""
        reading = self._port.memory()
        if reading is None:
            self.private = None
            return
        private, peak = reading
        self.private = private
        self.peak = max(peak, private, self.peak or 0)

    def over(self, values) -> bool:
        """Whether the watcher is to stop now, for the memory guard. With warn, over the limit is said
        once and the watcher goes on; with stop, it is said, and this answers True."""
        answer = memguard.verdict(values, self.private, self.warned)
        if answer == memguard.OK:
            return False
        detail = {"used": memguard.mib(self.private), "limit": memguard.limit_mib(values)}
        self.warned = True
        if answer == memguard.WARN:
            self._log("the watcher uses %d MiB of memory, more than the %d MiB the memory guard allows; "
                      "it goes on" % (detail["used"], detail["limit"]))
            self._notice(NoticeKind.MEMORY_WARNING.value, detail, final=False)
            return False
        self._log("the watcher uses %d MiB of memory, more than the %d MiB the memory guard allows; "
                  "stopping before the next tick" % (detail["used"], detail["limit"]))
        self._notice(NoticeKind.MEMORY_STOPPED.value, detail, final=True)
        return True

    # ------------------------------------------------------------------ how it ended
    def ended(self, store, end) -> None:
        """Write that the watcher stops on purpose, and how (WatcherEnd: clean or memory_guard)."""
        store.watcher_ended(self._clock(), end)

    # ------------------------------------------------------------------ the status file
    def status(self, store, values, *, running: bool, engine: str) -> None:
        """Write the status file while its setting is on; remove it, once, when the setting is off."""
        target = self._paths.status_file
        if not statusfile.wanted(values):
            if self._writing is not False:
                self._writing = False
                if statusfile.remove(target):
                    self._log("status file removed: its setting is off")
            return
        if self._writing is not True:
            self._log("writing the status file for other tools after every tick")
        self._writing = True
        stored = store.settings()
        heartbeat = store.watcher_status() or {}
        statusfile.write(target, statusfile.content(
            now=self._clock(), version=config.version(), running=running, enabled=bool(stored["enabled"]),
            observe_only=bool(stored.get("observe_only") or values.get("observe_only")), engine=engine,
            rows=store.pending(), reading=heartbeat.get("usage")))
