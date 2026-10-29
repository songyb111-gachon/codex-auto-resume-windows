# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""Restart the watcher if it stops unexpectedly (crash_restart, v0.6.19): P13's answers.

The standard edition's launcher runs the watcher in its own process and returns when it ends; a watcher that crashed
stays stopped, and the Dashboard says it "stopped unexpectedly" (core's control/watcher.py, WatcherEnd.UNEXPECTED). No
helper stays resident to start it again (F8). With this capability on, the launcher asks P13 before it runs the watcher
and this answers SUPERVISE: the launcher runs the watcher as a child of its own - the same launcher, under pythonw.exe,
with no window (scripts/watcher_launcher.py) - and waits for it. Once the child ended the launcher asks again, with its
exit code and whether its heartbeat says it stopped on purpose, and this answers RESTART only when every one holds:

* the end was not clean - no clean stop, and no memory guard's, in the heartbeat (`clean` is not True);
* the exit code is not 0, nor EXIT_BUSY (3: another watcher holds this home), nor EXIT_SCHEMA_NEWER (4: the state is
  newer than the code, which the launcher answers by starting the installed copy once, as ever), nor
  EXIT_MEMORY_GUARD (5: stopped on purpose by the guard);
* the stop event was not signalled - uninstall, an upgrade, a person's Stop (win/stopflag.py, held from the start);
* fewer than CAP restarts in the HOUR before - each one a row in `restarts` (state/restarts.py), written before the
  restart is made, so a restart that could not be counted is not made.

Before it answers RESTART it waits RESTART_DELAY seconds on the stop event itself, so a stop asked in those seconds is
seen too. The third restart in an hour is the last: at the next abnormal end it answers nothing (DEFER), the launcher
returns, the Dashboard says "stopped unexpectedly" as in the standard edition, and one notice of its own kind says it
was left stopped (`restart_gave_up`, registered in plug.py; raised by core's notifier as Windows' toast, since no
watcher is running to show a card).

It never kills anything: it only starts again what ended (E8). A restarted watcher reconciles before it sends, as every
watcher does at every start (E2, A5-A7). It answers RESTART only in a launcher it answered SUPERVISE in, so a watcher
run in the launcher's own process is never counted. Every answer is a closed word; nothing of it reaches the child's
arguments.
"""
from __future__ import annotations

from codex_auto_resume.domain.plug import DEFER, Alternative

CAPABILITY = "crash_restart"
# How many restarts an hour, and the hour.
CAP = 3
HOUR = 3600
# Seconds between a watcher's end and its restart.
RESTART_DELAY = 5
# The exit codes a watcher is never started again after: done, another watcher holds the home, the state is newer than
# the code (the launcher starts the installed copy once itself), the memory guard stopped it.
EXIT_OK, EXIT_BUSY, EXIT_SCHEMA_NEWER, EXIT_MEMORY_GUARD = 0, 3, 4, 5
NEVER_RESTARTED = frozenset({EXIT_OK, EXIT_BUSY, EXIT_SCHEMA_NEWER, EXIT_MEMORY_GUARD})
PHASE_START, PHASE_ENDED = "start", "ended"
# The notice of its own kind, and core's notifier event that raises it.
GAVE_UP = "restart_gave_up"


def gave_up_notice(paths) -> bool:
    """The notice that the watcher was left stopped, raised by core's notifier as Windows' toast under the
    notifications switch, kept on screen where a person chose its kind (notice_kinds). Whether it was shown."""
    from codex_auto_resume import config, l10n, notice_kinds, notifier, settings
    values = config.load_settings(paths)
    if not settings.notification_enabled(values, GAVE_UP):
        return False
    l10n.set_preference(values.get("interface_language"))
    notice = notifier.build(GAVE_UP, {}, destination=notifier.click_destination(values),
                            stay=notice_kinds.chosen(values))
    if notice is None:
        return False
    return bool(notifier.deliver(notice, inbox=None, setting=False)[1])


class CrashRestart:
    """crash_restart's code: P13's two answers. `stop` (win/stopflag.StopFlag's shape) and `notify` (gave_up_notice's)
    are the seams a test fills; nothing real is opened, waited on or shown in a test."""
    __slots__ = ("paths", "_scoped", "_stop", "_notify", "_supervising")

    def __init__(self, paths, *, stop=None, notify=None):
        self.paths = paths
        self._scoped = None
        self._stop = stop
        self._notify = notify or gave_up_notice
        self._supervising = False

    def bind(self, scoped):
        self._scoped = scoped

    def _flag(self):
        if self._stop is None:
            from ..win.stopflag import StopFlag
            self._stop = StopFlag(self.paths)
        return self._stop

    def supervise(self, facts):
        if not isinstance(facts, dict) or self._scoped is None:
            return DEFER
        phase = facts.get("phase")
        if phase == PHASE_START:
            # The stop event is held from now on, so a stop asked while the child runs is still seen once it ended.
            self._flag().hold()
            self._supervising = True
            return Alternative.SUPERVISE
        if phase == PHASE_ENDED and self._supervising:
            return self._ended(facts.get("exit_code"), facts.get("clean"))
        return DEFER

    def _ended(self, code, clean):
        if type(code) is not int or code in NEVER_RESTARTED or clean is True:
            return DEFER
        stop = self._flag()
        if stop.signalled():
            return DEFER
        scoped = self._scoped
        try:
            now = scoped.now()
            recent = [row for row in scoped.restarts.since(now - HOUR) if row.get("restarted")]
        except Exception:                              # noqa: BLE001 - restarts that cannot be counted are not made
            return DEFER
        if len(recent) >= CAP:
            try:
                scoped.restarts.noted(code, False)
                scoped.count("gave_up")
            except Exception:                          # noqa: BLE001
                pass
            try:
                self._notify(self.paths)
            except Exception:                          # noqa: BLE001 - a notice not shown leaves it stopped all the same
                pass
            return DEFER
        if stop.wait(RESTART_DELAY):
            return DEFER
        try:
            if scoped.restarts.noted(code, True) is not True:
                return DEFER
        except Exception:                              # noqa: BLE001 - a restart that cannot be counted is not made
            return DEFER
        scoped.count("restarted")
        return Alternative.RESTART


def make(paths) -> CrashRestart:
    return CrashRestart(paths)
