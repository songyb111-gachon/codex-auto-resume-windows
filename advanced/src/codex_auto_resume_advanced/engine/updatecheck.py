# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""A weekly update check while idle (v0.6.18): the Dashboard's Check for updates, run by the watcher once a week.

The standard edition asks GitHub whether a newer release exists only when a person presses Check for updates (C4, C5),
and refreshes the Codex compatibility data only on request, never from the watcher (C7) - the check refreshes it as it
goes. With this capability on, the watcher runs that very check on its own, at most once in WEEK, and only while no
recovery is waiting, being sent or being watched (core's records, domain/states.py) - at P8, as an errand, which starts
it and returns: the check itself runs on a thread of its own, so a slow network never holds a tick.

The check is the Dashboard's, switch for switch (gui/DashboardMaintenance.cs, CheckForUpdates and StartBootstrap): this
installation's own scripts/bootstrap.ps1, run by Windows PowerShell from System32 by full path, `-NoProfile
-NonInteractive -ExecutionPolicy Bypass -File <script> -CheckOnly`, with CODEX_AUTO_RESUME_PLUGIN_HOME naming this
installation and no console (CREATE_NO_WINDOW), waited for at most CHECK_SECONDS - the window's CheckMilliseconds -
and never killed: one that has not finished by then is left to finish on its own, and says nothing. Its answer is read
as the window reads it (`offer`): the `update:` line and the exit code must agree, and a newer release is offered
where it says `available`; where it says `current` or `newer-local`, a pre-release on a `prerelease:` line is offered
- exactly what a pressed check would offer, nothing else. An administrator's DisableUpdateCheck, which greys the
window's button, means no check here either.

What it offers it shows once in a watcher's life - kept, so a watcher that starts again shows it again until it
is installed or put away (IdleUpdateCheck) - as a notice of its own kind (`update_offered`, registered with core in plug.py), whose
one button opens the Dashboard's Diagnostics page, where an update is installed (surfaces.update_view, core's
runtime/app.py). It never downloads or installs anything. The time of the last check is kept in this edition's own
state (state/choices.py, `stamp`, under OptionKey.LAST_CHECK), written before the check starts, so a check that fails,
is refused by GitHub or never finishes waits for the next week like one that answered.

Each check that ends says what it did in the watcher's log (logs\\auto-resume.log), one English line (v0.6.18
acceptance; `said`): checked and nothing newer, a newer version offered and which, or could not check and why - in the
words the Dashboard's Check for updates says the same with (its English catalog: diag.update_could_not_ask and the
rest). The line names versions only, never a path, a name or what the check printed.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
import re
import subprocess
import threading

from codex_auto_resume.domain.plug import DEFER

from ..vocabulary import OptionKey

CAPABILITY = "idle_update_check"
WEEK = 7 * 86400
# The Dashboard's CheckMilliseconds (gui/DashboardMaintenance.cs), in seconds.
CHECK_SECONDS = 120
# How often the errand looks whether a check is due, in seconds.
LOOK_EVERY = 60
# The answers of scripts/bootstrap.ps1's -CheckOnly: the `update:` line's first word, with the exit code it comes with.
ANSWERS = {"current": 0, "available": 10, "newer-local": 11, "unavailable": 12}
# A release's version, as the bootstrap rebuilds it from three integers; and a pre-release's, as the window holds the
# `prerelease:` line to before it offers it (DashboardMaintenance.PrereleaseRule).
RELEASE = re.compile(r"(0|[1-9][0-9]{0,5})\.(0|[1-9][0-9]{0,5})\.(0|[1-9][0-9]{0,5})\Z")
PRERELEASE = re.compile(r"(0|[1-9][0-9]{0,5})\.(0|[1-9][0-9]{0,5})\.(0|[1-9][0-9]{0,5})-(alpha|beta)"
                        r"(\.([2-9]|[1-9][0-9]{1,2}))?\Z")
# The variables the window sets, or takes away, for the check: this installation, and nothing of an install.
HOME_VARIABLE = "CODEX_AUTO_RESUME_PLUGIN_HOME"
INSTALL_VARIABLES = ("CODEX_AUTO_RESUME_UPDATING_DASHBOARD", "CODEX_AUTO_RESUME_PROGRESS_LINES")
# Why a check could not answer, as run_check puts it on its `said` list: the script or Windows PowerShell not there,
# the check not started, or not finished within CHECK_SECONDS.
MISSING, NOT_STARTED, RUNNING = "missing", "not_started", "running"
# The Dashboard's words for a check that did not answer (gui/DashboardMaintenance.cs UpdateWords): their keys in the
# English catalog, with the English beside each for a catalog that cannot be read. `running` is said up to the
# Dashboard's advice to look at its page again, which a log line has no page for.
COULD_NOT = {
    "unavailable": ("diag.update_could_not_ask",
                    "GitHub could not be asked just now. This says nothing about whether an update exists."),
    MISSING: ("diag.update_incomplete",
              "Files this installation is made of are missing, so it could not be checked. Install it again from the "
              "release archive."),
    RUNNING: ("diag.update_running",
              "It is taking longer than usual and is still working. It carries on in the background; look at this page "
              "again in a few minutes."),
    "failed": ("diag.update_failed", "The update check did not finish."),
}
LOG_PREFIX = "weekly update check: "
# Core's states of a recovery that is waiting, being sent or being watched: none may be, for a check to start.
BUSY = ("WAITING", "CLAIMED", "IN_FLIGHT", "OBSERVING")


def _last(printed, name):
    """The rest of the last line of `printed` that starts with `name`, or None."""
    found = None
    for line in str(printed or "").replace("\r", "").split("\n"):
        line = line.strip()
        if line.startswith(name):
            found = line[len(name):]
    return found


def offer(code, printed):
    """What a check that exited with `code` and printed `printed` offers, as the Dashboard reads it: (version, False)
    for a newer release, (version, True) for a newer pre-release, or None for nothing - up to date, ahead, GitHub not
    asked, or an answer the code and the line do not agree on. Pure."""
    line = _last(printed, "update: ")
    words = line.split(" ") if line is not None else []
    said = words[0] if words else ""
    if said not in ANSWERS or ANSWERS[said] != code:
        return None
    if said == "available":
        latest = words[2] if len(words) > 2 else ""
        return (latest, False) if RELEASE.match(latest) else None
    if said in ("current", "newer-local"):
        pre = _last(printed, "prerelease: ")
        if pre is not None and pre.startswith("v") and PRERELEASE.match(pre[1:]):
            return pre[1:], True
    return None


def english(why) -> str:
    """The Dashboard's English words for a check that did not answer, for `why` (COULD_NOT; anything else: "failed")."""
    key, fallback = COULD_NOT.get(why, COULD_NOT["failed"])
    try:
        from codex_auto_resume import l10n
        text = l10n.text(key, "en")
    except Exception:
        text = fallback
    if why == RUNNING:
        text = text.split(";")[0].rstrip(".") + "."
    return text


def said(answered, why=None) -> str:
    """The watcher's log line for a check that ended: `answered` as run_check returns it - (code, printed), or None and
    `why` it did not answer. One line that names versions only. Pure, but for the English catalog it reads."""
    if answered is None:
        return LOG_PREFIX + "could not check: " + english(why if why in (MISSING, RUNNING) else "failed")
    code, printed = answered
    found = offer(code, printed)
    if found is not None:
        version, prerelease = found
        return LOG_PREFIX + ("pre-release v%s offered" if prerelease else "v%s offered") % version
    line = _last(printed, "update: ")
    words = line.split(" ") if line is not None else []
    answer = words[0] if words and words[0] in ANSWERS and ANSWERS[words[0]] == code else None
    shown = [word if RELEASE.match(word) else "?" for word in words[1:3]] + ["?", "?"]
    if answer == "current":
        return LOG_PREFIX + "checked, nothing newer: v%s is the newest published release" % shown[0]
    if answer == "newer-local":
        return LOG_PREFIX + "checked, nothing newer: this build is ahead of the newest published release, v%s" % shown[1]
    if answer == "unavailable":
        return LOG_PREFIX + "could not check: " + english("unavailable")
    return LOG_PREFIX + "could not check: " + english("failed")


def script_of(paths) -> Path:
    """This installation's bootstrap, as the window finds it beside itself: <home>\\app\\scripts\\bootstrap.ps1."""
    return Path(paths.home) / "app" / "scripts" / "bootstrap.ps1"


def run_check(script, home, seconds=CHECK_SECONDS, said=None):
    """Run `script` -CheckOnly as the Dashboard does and wait for it at most `seconds`: (exit code, what it printed), or
    None where Windows PowerShell or the script is not there, it could not be started, or it has not finished - then it
    is left to finish on its own, never killed. Where it returns None it puts why on the list `said`, when one is given:
    MISSING, NOT_STARTED or RUNNING."""
    from codex_auto_resume import pwsh
    why = said if isinstance(said, list) else []
    powershell = pwsh.executable()
    if not Path(script).is_file():
        why.append(MISSING)
        return None
    if powershell is None:
        why.append(NOT_STARTED)
        return None
    environment = dict(os.environ)
    environment[HOME_VARIABLE] = str(home)
    for name in INSTALL_VARIABLES:
        environment.pop(name, None)
    try:
        process = subprocess.Popen(
            [powershell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(script),
             "-CheckOnly"],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=environment,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except OSError:
        why.append(NOT_STARTED)
        return None
    try:
        printed, _errors = process.communicate(timeout=seconds)
    except subprocess.TimeoutExpired:
        # Left to finish, as the window leaves a check it calls "running": what it prints is read and dropped.
        threading.Thread(target=process.communicate, daemon=True).start()
        why.append(RUNNING)
        return None
    return process.returncode, printed.decode("utf-8", "replace")


def _update_check_managed() -> bool:
    """Whether an administrator's DisableUpdateCheck is set (core's managed.py), asked afresh."""
    from codex_auto_resume.control.policy import managed_policy
    return managed_policy().disable_update_check is True


class _Errand:
    __slots__ = ("code", "now")

    def __init__(self, code, now):
        self.code, self.now = code, now

    def run(self, guard):
        return self.code.start(self.now)


class IdleUpdateCheck:
    """idle_update_check's code: its P8 errand, and what it offers for the icon's surface. `run`, `managed`, `start` and
    `installed` are seams a test fills: the check (run_check's shape), the administrator's switch, how the check's
    thread is started (`start(target)`), and the version installed here (config.version).

    What a check offers is kept (v0.6.18), as stamps beside LAST_CHECK - the version (`encode`) and when it was found -
    so a watcher that starts again still shows it, once in its life, until that version or a newer one is installed, a
    later check answers that nothing is newer, or a person turns the capability off: an offer found before it last stood
    on is one they put away."""
    __slots__ = ("paths", "_scoped", "_run", "_managed", "_start", "_installed", "_lock", "_offered", "_offered_at",
                 "_found", "_said", "_line", "_running", "_looked", "_loaded", "_log")

    def __init__(self, paths, *, run=None, managed=None, start=None, installed=None, log=None):
        self.paths = paths
        self._scoped = None
        self._run = run or run_check
        self._managed = managed or _update_check_managed
        self._start = start or (lambda target: threading.Thread(target=target, daemon=True).start())
        self._installed = installed or _installed_version
        self._lock = threading.Lock()
        self._offered = None                   # (version, prerelease) offered and not put away
        self._offered_at = None                # when it was found, whole seconds
        self._found = None                     # (version, prerelease) a check found, not yet kept
        self._said = None                      # the journal word of a check that ended, not yet counted
        self._line = None                      # its line for the watcher's log (`said`), not yet written
        self._log = log or _log_line
        self._running = False
        self._looked = None
        self._loaded = False

    def bind(self, scoped):
        self._scoped = scoped

    def tick(self, view):
        scoped = self._scoped
        if scoped is None:
            return DEFER
        try:
            self._settle()
        except Exception:
            pass
        try:
            now = scoped.now()
            if self._looked is not None and 0 <= now - self._looked < LOOK_EVERY:
                return DEFER
            self._looked = now
            return _Errand(self, now) if self._due(view, now) else DEFER
        except Exception:
            return DEFER

    def _due(self, view, now) -> bool:
        """Whether a check may start now: none running, none in the last WEEK, nothing waiting, being sent or watched,
        not turned off by an administrator, and this installation's bootstrap there to run."""
        with self._lock:
            if self._running:
                return False
        last = self._scoped.stamped(OptionKey.LAST_CHECK)
        if type(last) is int and 0 <= now - last < WEEK:
            return False
        if self._busy(view):
            return False
        if self._managed() is not False:
            return False
        return script_of(self.paths).is_file()

    @staticmethod
    def _busy(view) -> bool:
        """Whether core holds a recovery that is waiting, being sent or watched - or its records cannot be read."""
        from codex_auto_resume.domain import states
        wanted = frozenset().union(*(getattr(states, name) for name in BUSY))
        try:
            return bool(view.records_in(wanted))
        except Exception:
            return True

    def start(self, now):
        """The errand: the time of this check kept first, then the check started on a thread of its own. Nothing starts
        where the time cannot be kept - a check that could not be counted would run again at the next look."""
        if self._scoped.stamp(OptionKey.LAST_CHECK, int(now)) is not True:
            return None
        with self._lock:
            if self._running:
                return None
            self._running = True
        try:
            self._start(self._check)
        except Exception:
            with self._lock:
                self._running = False
        return None

    def _check(self):
        """The check, on its own thread: what it offers, shown at once, and its word, for the next tick to keep and
        count - the thread writes nothing."""
        try:
            why = []
            if self._run is run_check:
                answered = run_check(script_of(self.paths), self.paths.home, said=why)
            else:
                answered = self._run(script_of(self.paths), self.paths.home)
            found = offer(*answered) if answered is not None else None
            word = "unanswered" if answered is None else "offered" if found is not None else "checked"
            line = said(answered, why[0] if why else None)
        except Exception:
            found, word = None, "unanswered"
            line = LOG_PREFIX + "could not check: " + english("failed")
        with self._lock:
            if found is not None:
                self._offered = found
            self._found = found
            self._said = word
            self._line = line
            self._running = False

    def _settle(self) -> None:
        """On the tick: a check that ended counted and what it found kept (or, answering nothing newer, the kept offer
        dropped); the kept offer read once; and dropped where the version installed reached it or it was found before
        the capability last stood on."""
        scoped = self._scoped
        with self._lock:
            said, found, self._said, self._found = self._said, self._found, None, None
            line, self._line = self._line, None
        if line is not None:
            try:
                self._log(line)
            except Exception:
                pass
        if said is not None:
            try:
                scoped.count(said)
            except Exception:
                pass
        if said == "offered" and found is not None:
            self._keep(found, int(scoped.now()))
        elif said == "checked":
            self._drop()
        if not self._loaded:
            self._loaded = True
            kept = decode(scoped.stamped(OptionKey.OFFERED_VERSION))
            at = scoped.stamped(OptionKey.OFFERED_AT)
            if kept is not None and type(at) is int:
                with self._lock:
                    self._offered, self._offered_at = kept, at
        with self._lock:
            offered, at = self._offered, self._offered_at
        if offered is None:
            return
        installed = encode(self._installed())
        reached = installed is not None and installed >= (encode(offered[0]) or 0)
        since = scoped.since()
        put_away = isinstance(since, (int, float)) and type(at) is int and at < since
        if reached or put_away:
            self._drop()

    def _keep(self, found, now) -> None:
        code = encode(found[0])
        with self._lock:
            self._offered, self._offered_at = found, now
        if code is not None:
            self._scoped.stamp(OptionKey.OFFERED_VERSION, code)
            self._scoped.stamp(OptionKey.OFFERED_AT, now)

    def _drop(self) -> None:
        with self._lock:
            self._offered = self._offered_at = None
        for key in (OptionKey.OFFERED_VERSION, OptionKey.OFFERED_AT):
            self._scoped.unstamp(key)

    def offered(self):
        """(version, prerelease) offered and not put away, or None."""
        with self._lock:
            return self._offered


def _log_line(line) -> None:
    """One line in the watcher's log (core's logbook: logs\\auto-resume.log), written as its other lines are."""
    from codex_auto_resume.logbook import LOGGER_NAME
    logging.getLogger(LOGGER_NAME).info("%s", line)


def _installed_version():
    """The version installed here (core's config.version), or None."""
    try:
        from codex_auto_resume.config import version
        return version()
    except Exception:
        return None


def _parts(version):
    """(major, minor, patch, stage) of a release's or a pre-release's version - the stage 9999 for a release, 1000 and
    the stage's number for an alpha, 2000 and it for a beta - each number below 1000, or None."""
    if not isinstance(version, str):
        return None
    release = RELEASE.match(version)
    found = release or PRERELEASE.match(version)
    if found is None:
        return None
    numbers = [int(found.group(index)) for index in (1, 2, 3)]
    if release is not None:
        stage = 9999
    else:
        stage = (1000 if found.group(4) == "alpha" else 2000) + (int(found.group(6)) if found.group(6) else 1)
    return (*numbers, stage) if all(number < 1000 for number in numbers) else None


def encode(version):
    """`version` as one whole number from 1 that keeps its order - a release after its pre-releases, a later stage after
    an earlier - for a stamp of `options` (whole numbers from 1), or None for one it cannot hold. Pure."""
    parts = _parts(version)
    if parts is None:
        return None
    major, minor, patch, stage = parts
    return ((major * 1000 + minor) * 1000 + patch) * 10000 + stage


def decode(value):
    """(version, prerelease) of a number `encode` made, or None. Pure."""
    if type(value) is not int or value < 1:
        return None
    stage, rest = value % 10000, value // 10000
    patch, rest = rest % 1000, rest // 1000
    minor, major = rest % 1000, rest // 1000
    if major >= 1000:
        return None
    base = "%d.%d.%d" % (major, minor, patch)
    if stage == 9999:
        version, prerelease = base, False
    elif 1001 <= stage <= 1999 or 2001 <= stage <= 2999:
        number = stage % 1000
        version = base + ("-alpha" if stage < 2000 else "-beta") + ("" if number == 1 else ".%d" % number)
        prerelease = True
    else:
        return None
    return (version, prerelease) if encode(version) == value else None


def make(paths) -> IdleUpdateCheck:
    return IdleUpdateCheck(paths)
