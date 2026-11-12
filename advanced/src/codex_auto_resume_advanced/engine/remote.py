# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""The resident courier's capabilities (v0.6.22, plans/v0619-design/D-remote.md): the loopback API and web view
(local_api, with local_api_actions and local_api_lan beside it) and remote control over Telegram (telegram_remote, with
telegram_continue beside it).

While local_api or telegram_remote stands on, the watcher keeps one resident courier running beside it - a process of its own,
`pythonw.exe -c <launch.BOOTSTRAP> <import roots> --home <home> --serve` (courier/__main__.py), in the watcher's job
object, so it ends with the watcher however the watcher ends. At P8 the errand starts one where none answers the
resident's mutex (courier/resident.py, `running`), at most RESTARTS more times in an hour after the first: past that it
is not started again until the hour has passed, the journal says `gave_up` and the card says it stopped - never a loop
of restarts. Each start is a journal line, so the count outlives a watcher that restarted and the Dashboard's process
can read it (`stopped`). The resident itself reads the capabilities' states every few seconds and closes what was
turned off, so turning one off ends its role within seconds and turning all off ends the process.

Watched, the errand is only journalled and never run (runtime.tick): nothing is started. Off, nothing is asked. So
while it is off there is no process, no socket and no thread.

Paused, core asks P8 nothing - but it asks P22, and both answer there (v0.6.22, the owner's word of 2026-11-06): they
declare they send nothing to Codex, so the resident is started while paused too, after a watcher restart included, and
Telegram's /recovery-on can still arrive. The same errand, under the same cap.

The others are actions - core never asks them; they only widen what the resident does while the capability they require
stands on: local_api_actions lets the API pause and cancel, local_api_lan lets it bind beyond 127.0.0.1, and
telegram_continue adds /continue and /recovery-on. Paused, what the resident does still only reads and reduces - or, under
telegram_continue, is the person's own release of a hold or lift of the pause.

No network here: the errand only starts a process (courier/launch.py).
"""
from __future__ import annotations

from pathlib import Path

from codex_auto_resume.domain.plug import DEFER

API = "local_api"
API_ACTIONS = "local_api_actions"
API_LAN = "local_api_lan"
TELEGRAM = "telegram_remote"
TELEGRAM_CONTINUE = "telegram_continue"
RESIDENT = (API, TELEGRAM)
DEFAULT_PORT = 47615
# The port a person may type: anything a user's program may listen on, the default among them.
PORT_RANGE = (1024, 65535)
RESTARTS = 3                       # starts after the first in one hour, at most
HOUR = 3600
STARTING = 30                      # seconds a start is given to take its mutex before another is tried
START_WORD = "resident_started"
GAVE_UP_WORD = "gave_up"
# What each capability counts, as its journal says it: the resident started, and given up on for the hour; the API's
# server started or stopped, its port taken, and closed for five minutes after ten wrong tokens in a minute. The actions
# it carried out.
API_CODES = (START_WORD, GAVE_UP_WORD, "started", "stopped", "port_taken", "locked")
API_ACTION_CODES = ("paused", "cancelled", "list_again")
# Telegram's: the resident's two, its long poll started or stopped, and each command it carried out or what it ignored.
TELEGRAM_CODES = (START_WORD, GAVE_UP_WORD, "started", "stopped", "status", "listed", "cancelled", "paused", "list_again",
                  "ignored")
TELEGRAM_CONTINUE_CODES = ("continued", "pause_lifted")


def setup_time(paths):
    """When setup last ran for this installation - an install, an update or a Repair writes its runtime.json - as a
    whole second, or None (a source checkout, or a file that cannot be read). The hour's count of starts begins there
    too (v0.6.22 final, the live acceptance's re-check): an earlier version's courier that could not start - every one
    before v0.6.22's fix, from an installed copy - used the hour's starts, and the new one stayed stopped for up to an
    hour after the update. A setup run is a new installation's start; a crash loop still gets at most RESTARTS more."""
    try:
        return int((Path(paths.home) / "runtime.json").stat().st_mtime)
    except (OSError, AttributeError, TypeError, ValueError):
        return None


def starts(journal_times, now, since=None) -> list:
    """When a resident was started in the last hour, and since `since` (setup_time) where it is given, oldest first, by
    any capability's errand: `journal_times` is the state's (capability, word, since)."""
    floor = now - HOUR if since is None else max(now - HOUR, since)
    return sorted(at for capability in RESIDENT for at in journal_times(capability, START_WORD, floor)
                  if 0 <= now - at < HOUR and at >= floor)


def stopped(journal_times, now, since=None) -> bool:
    """Whether the resident has been started as often as an hour allows (since the last setup run): the card's
    `stopped`."""
    return len(starts(journal_times, now, since)) > RESTARTS


class _Errand:
    """One start of the resident. Both capabilities answer P8 in the same tick, before either errand runs, so each looks
    again just before it launches (v0.6.23): a resident that answers now, or one started within STARTING - by the other's
    errand a moment ago - or the hour's starts used, and it starts nothing. One launch a tick, one start counted."""
    __slots__ = ("code",)

    def __init__(self, code):
        self.code = code

    def run(self, guard):
        code = self.code
        try:
            scoped = code._scoped
            now = scoped.now()
            started = starts(scoped.journal_times, now, setup_time(code.paths))
            if (code._running(code.paths) or (started and now - started[-1] < STARTING)
                    or len(started) > RESTARTS):
                return None
        except Exception:
            return None
        if code._launch(code.paths):
            scoped.count(START_WORD)
        return None


class Resident:
    """local_api's and telegram_remote's code: the P8 errand that keeps the resident courier running. Both answer, and the first in the
    registry's order starts it - the second's errand finds it running, or just started (`_Errand.run`). `running` and `launch` are seams a test
    fills: whether a resident answers its mutex, and how one is started."""
    __slots__ = ("paths", "capability", "_scoped", "_running", "_launch", "_told")

    def __init__(self, paths, capability, *, running=None, launch=None):
        self.paths = paths
        self.capability = capability
        self._scoped = None
        self._running = running or _running
        self._launch = launch or _start
        self._told = False

    def bind(self, scoped):
        self._scoped = scoped

    def resident(self, view):
        """P22, asked only while recovery is paused: the same errand, so the courier stays reachable."""
        return self.tick(view)

    def tick(self, view):
        scoped = self._scoped
        if scoped is None:
            return DEFER
        try:
            if self._running(self.paths):
                self._told = False
                return DEFER
            now = scoped.now()
            started = starts(scoped.journal_times, now, setup_time(self.paths))
            if started and now - started[-1] < STARTING:
                return DEFER                  # one was just started: it is given time to take its mutex
            if len(started) > RESTARTS:
                if not self._told:
                    self._told = bool(scoped.count(GAVE_UP_WORD))
                return DEFER
            return _Errand(self)
        except Exception:
            return DEFER


class Widening:
    """An action that widens what the resident does while what it requires stands on (local_api_actions,
    local_api_lan, telegram_continue): nothing of it runs at a plug point; the resident reads whether it stands on."""
    __slots__ = ("paths",)

    def __init__(self, paths):
        self.paths = paths


def _running(paths) -> bool:
    from ..courier.resident import running
    return running(paths)


def _start(paths):
    from ..courier import launch
    return launch.start(paths, "--serve")


def make_local_api(paths) -> Resident:
    return Resident(paths, API)


def make_telegram_remote(paths) -> Resident:
    return Resident(paths, TELEGRAM)


def make_widening(paths) -> Widening:
    return Widening(paths)
