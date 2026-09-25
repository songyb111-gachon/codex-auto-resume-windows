"""Whether the watcher runs, whether it starts at sign-in, starting it and asking it to stop.

A stop is a request and never a kill: the watcher finishes the tick it is in, because a tick
that is submitting a continuation must not be cut short - a watcher stopped mid-submission
cannot prove whether it sent.
"""
from __future__ import annotations

import os
from pathlib import Path
import time

from .. import config, machine, startup
from ..store import TERMINAL, LegacyStore, Store, StoreError
from ..windows import AdapterError, Mutex, StopEvent
from .errors import ControlError



# How long to wait for a launched watcher to become visible, and how often to look.
#
# The watcher takes the single-instance mutex early in `App.run` - but early is still
# after a Python interpreter has started and imported the engine. Measured over five
# launches on a warm machine: 0.156 s to 0.297 s. The window is generous against a cold
# disk; the interval is short so the ordinary case returns almost at once.
WATCHER_START_TIMEOUT = 6.0
WATCHER_START_INTERVAL = 0.1
# How long to wait for a signalled watcher to let the single-instance mutex go, and how
# often to look. A stop is a request and never a kill: the watcher finishes the tick it is
# in first, and a tick that is submitting a continuation must not be cut short, because a
# watcher stopped mid-submission cannot prove whether it sent. Ten seconds is what
# `codex-auto-resume stop` has always waited, and "still finishing" is an ordinary answer
# here rather than a failure.
WATCHER_STOP_TIMEOUT = 10.0
WATCHER_STOP_INTERVAL = 0.25


# A heartbeat older than this, from a watcher that holds the mutex, is not ticking.
TICK_STALE_SECONDS = 180.0


def await_watcher(probe, process, *, timeout=None, interval=None) -> dict:
    """Wait, briefly and by the clock, for a launched watcher to become real.

    `Popen` returning proves one thing: Windows created a process. It does not prove the
    watcher survived its imports, took the single-instance mutex, opened its state, or
    stayed alive - and `watcher_running()` is the only thing that can say so, because the
    mutex is what the rest of the product asks about too.

    Reporting the launch as a running watcher produced exactly the contradiction you
    would expect: "The watcher is running." followed immediately by a status saying it
    was not. So this waits for the authoritative answer instead of assuming it.

    Bounded, on `time.monotonic`, so that a clock change cannot cut the window short or
    extend it forever, and in several short probes rather than one long sleep: measured
    over five launches on a warm machine the watcher becomes visible in 0.16-0.30 s, so
    the common case returns almost at once, while a first start behind an antivirus scan
    of a cold interpreter is still reported correctly rather than as a failure.

    The probe takes the mutex for microseconds to test it. `App.run` retries a busy mutex
    once for that reason: a status check must never be able to convince a starting
    watcher that it lost a race to itself.

    `probe` is the authoritative `watcher_running`; `process` is the `Popen` handle, or
    None where the caller has no handle to watch.
    """
    timeout = WATCHER_START_TIMEOUT if timeout is None else timeout
    interval = WATCHER_START_INTERVAL if interval is None else interval
    deadline = time.monotonic() + timeout
    while True:
        if probe() is True:
            return {"confirmed": True, "state": "running", "reason": None}
        if process is not None and process.poll() is not None:
            # It ran and stopped. Nearly always a second watcher already holding the
            # mutex, or an installation the launcher could not resolve; either way the
            # logs say which, and claiming success would not. The wording surfaces name
            # the directory rather than `launcher.log`, because the entry-script path
            # this function also supports never writes that file.
            return {"confirmed": False, "state": "exited", "reason": "exited"}
        if time.monotonic() >= deadline:
            return {"confirmed": False, "state": "unconfirmed", "reason": "unconfirmed"}
        time.sleep(interval)


def await_stopped(probe, *, timeout=None, interval=None) -> dict:
    """Wait, briefly and by the clock, for a signalled watcher to let the mutex go.

    The stop event only delivers a request. The single-instance mutex is what says whether
    the watcher is still there, and it is the authoritative answer the rest of the product
    asks for too, so a stop reported here means the same thing a status read means.

    Bounded on `time.monotonic`, like `await_watcher` above, so that a clock change can
    neither cut the wait short nor extend it for ever.

    A probe that cannot tell keeps the wait running and, if it is still the answer when the
    time is up, is reported as `unknown` rather than as a watcher that is still finishing:
    the two have different fixes, and only one of them is safe to upgrade over.
    """
    timeout = WATCHER_STOP_TIMEOUT if timeout is None else timeout
    interval = WATCHER_STOP_INTERVAL if interval is None else interval
    deadline = time.monotonic() + timeout
    while True:
        answer = probe()
        if answer is False:
            return {"stopped": True, "state": "stopped", "reason": None}
        if time.monotonic() >= deadline:
            state = "still-finishing" if answer is True else "unknown"
            return {"stopped": False, "state": state, "reason": state}
        time.sleep(interval)


def _version() -> str:
    return config.version()


class WatcherMixin:
    """The watcher's life, as this layer asks about it."""

    def watcher_running(self):
        """True / False / None, where None means the probe itself was unavailable.

        The same probe as `App.watcher_running`, made here rather than borrowed. Building an
        `App` only to ask imported the whole watcher - the engine, the icon's window code and
        the notifications - so the first `status` of every bridge process waited 0.1 to 0.3 s
        on imports, measured, holding the bridge lock the whole time. The tests hold the two
        probes to the same answers.
        """
        try:
            with Mutex(str(self.paths.state_dir), timeout=0.0):
                return False
        except AdapterError as exc:
            if str(exc) == "mutex_busy":
                return True
            return None

    def _watcher(self, store) -> dict:
        """What is known about the watcher: the mutex probe plus its own heartbeat."""
        running = self.watcher_running()
        status = None
        try:
            status = store.watcher_status() if isinstance(store, Store) else None
        except StoreError:
            status = None
        ticking = None
        if running is True and status and status.get("last_tick_at"):
            ticking = time.time() - status["last_tick_at"] < TICK_STALE_SECONDS
        return {"running": running, "ticking": ticking,
                "engine_state": (status or {}).get("engine_state", "unknown"),
                "last_tick_at": (status or {}).get("last_tick_at"),
                "last_tick_ok": (status or {}).get("last_tick_ok"),
                "code_version": (status or {}).get("code_version"),
                # The identity of the process making the claim, which is the only thing here
                # that can prove a handover. `app.py` writes `config.version()` into the
                # heartbeat on every tick, so the moment an upgrade replaces the files a
                # still-running *old* watcher starts reporting the *new* version: a changed
                # `code_version` therefore proves nothing about a restart, while a
                # `started_at` that moved, from a watcher that holds the mutex, does.
                "pid": (status or {}).get("pid"),
                "started_at": (status or {}).get("started_at")}

    def startup_enabled(self) -> bool:
        try:
            value = startup.current_value()
        except startup.StartupError:
            return False
        return bool(value and startup.belongs_to(value, self.paths.home))

    def set_startup_enabled(self, enabled: bool) -> bool:
        if not isinstance(enabled, bool):
            raise ControlError("enabled must be true or false", code="invalid_enabled")
        try:
            if enabled:
                launcher = self.paths.home / "watcher-launcher.py"
                entry = launcher if launcher.is_file() else self.paths.entry_script
                startup.install(startup.command_line(entry, None if launcher.is_file() else self.paths.home))
            else:
                value = startup.current_value()
                # Only ever unregister our own; a foreign value is left alone.
                if value and startup.belongs_to(value, self.paths.home):
                    startup.uninstall()
        except startup.StartupError as exc:
            # The registry layer's own sentence, and the generic code for the reason given
            # at `update_settings`: the set has no word for a registration that failed.
            raise ControlError(str(exc), code="request_failed") from None
        return self.startup_enabled()

    def start_watcher(self) -> dict:
        """Start the watcher if it is not already running.

        Still not a recovery engine: this launches the same process the installer
        launches, with the same arguments, and then has nothing more to do with it. It
        decides nothing about any interruption.

        It exists because the alternative was a dead end. A settings window that
        reports "watcher not running" and offers no way to start one leaves the user
        with a product that has quietly stopped working and no route back except
        re-running the installer - and the whole point of the watcher is that it is the
        part nobody should have to think about.
        """
        running = self.watcher_running()
        if running is True:
            return {"started": False, "confirmed": True,
                    "state": "already-running", "reason": "already running"}
        try:
            process = self._launch_watcher()
        except OSError as exc:
            raise ControlError("could not start the watcher: %s" % exc,
                               code="start_failed") from None
        result = self._confirm_watcher(process)
        result["started"] = True
        return result

    def _launch_watcher(self, extra_flags: int = 0, *, launcher_only: bool = False):
        """Start the watcher the way the installer and sign-in do, and return its Popen.

        Raises ControlError `not_installed` when there is nothing to start - with `launcher_only`,
        when the installation's stable launcher is missing, whatever else is there, and when
        there is no pythonw.exe to run it under - and OSError when Windows refuses the process.
        """
        import subprocess

        launcher = self.paths.home / "watcher-launcher.py"
        if launcher_only and not launcher.is_file():
            raise ControlError("the watcher is not installed here", code="not_installed")
        entry = launcher if launcher.is_file() else self.paths.entry_script
        if not Path(entry).is_file():
            raise ControlError("the watcher is not installed here", code="not_installed")
        # DETACHED_PROCESS below is safe only because this is pythonw.exe, a GUI program: a
        # detached python.exe would have no console to hand down, and anything it started
        # plainly would open a window. python_launcher refuses rather than return python.exe.
        try:
            interpreter = startup.python_launcher()
        except startup.StartupError as exc:
            raise ControlError(str(exc), code="not_installed") from None
        flags = 0
        if os.name == "nt":
            flags = (getattr(subprocess, "DETACHED_PROCESS", 0)
                     | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | extra_flags)
        arguments = [str(interpreter), str(entry)]
        if entry != launcher:
            # The stable launcher already knows its home; the raw entry point does not.
            arguments += ["--home", str(self.paths.home), "--quiet"]
        arguments.append("run")
        return subprocess.Popen(arguments, cwd=str(self.paths.home), close_fds=True,
                                creationflags=flags, stdin=subprocess.DEVNULL,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


    def _confirm_watcher(self, process) -> dict:
        return await_watcher(self.watcher_running, process)

    def stop_watcher(self) -> dict:
        """Ask a running watcher to stop, and report only what the probe can prove.

        The product's own upgrade-pending message tells people to use Stop watcher and then
        Start watcher. Start existed and stop did not, so that instruction could not be
        followed from any front end - the only stop lived in the command line, which is
        exactly the place a user of the window or the panel never goes.

        This is that same stop and not a second mechanism: the named event the watcher
        already waits on, signalled once. Nothing here kills a process, and nothing here may,
        because a watcher stopped mid-submission cannot prove whether it sent the
        continuation, and a continuation that may have been sent is never sent again. The
        only safe stop is the one the watcher performs itself at the end of the tick it is in.

        The four answers are the four things the single-instance mutex - the same probe
        `watcher_running` uses, so every part of the product means one thing by "running" -
        can say. `stopped` is the one that may never be guessed: "the probe could not tell"
        and "it let go" are different sentences, and rounding the first into the second is how
        a front end ends up inviting an upgrade that the old watcher is still holding.
        """
        def probe():
            try:
                return self.watcher_running()
            except Exception:
                # A probe that failed has not said the mutex is free. It says nothing at all,
                # and nothing is not evidence of a stop.
                return None

        if probe() is False:
            # Nothing holds the mutex, so there is nothing to ask and nothing to wait for.
            return {"stopped": False, "signalled": False, "state": "not-running",
                    "reason": "not-running"}
        # Signalled exactly once, and only where something may be listening. `signal` opens
        # the watcher's own event and creates nothing, so a stop can never be left lying
        # around for a later watcher to find and obey.
        try:
            signalled = StopEvent(str(self.paths.state_dir)).signal()
        except Exception:
            # Not Windows, or the event could not be opened. The wait below still runs: what
            # the mutex says is a question for the probe, not for how the asking went.
            signalled = False
        result = await_stopped(probe)
        result["signalled"] = signalled
        return result

    def get_status(self) -> dict:
        values = self.get_settings()
        with self._open(legacy_ok=True) as store:
            stored = store.settings()
            counts = store.status_counts()
            legacy = isinstance(store, LegacyStore)
            watcher = self._watcher(store)
            codes: dict[str, int] = {}
            pending = 0
            marks = None
            if not legacy:
                for row in store.pending():
                    pending += 1
                    code = machine.public_code(row)
                    codes[code] = codes.get(code, 0) + 1
                marks = store.failure_marks()
            else:
                pending = sum(count for state, count in counts.items() if state not in TERMINAL)
        return {
            "version": _version(),
            "enabled": bool(stored["enabled"]),
            "watcher_running": watcher["running"],
            "watcher": watcher,
            "upgrade_pending": legacy,
            "startup_enabled": self.startup_enabled(),
            "pending": pending,
            "states": counts,
            "codes": codes,
            # A certain failure nobody has seen yet (unseen_failure): the taskbar button's red, as the icon's.
            "failure_unseen": self.failure_unseen(marks),
            "settings": values,
        }
