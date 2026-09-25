"""What the watcher does every few seconds, and how long it waits before doing it again.

One tick reads what Codex recorded, registers what is new, sends what is due and reconciles
what was sent. The interval moves between `MIN_POLL` and `MAX_POLL` with how much there is to
do, and the wake event cuts the wait short when somebody presses Retry now.

A mixin rather than a module of functions, because a tick is the `App` it runs inside: the
store it opened, the backend it resolved, the settings it last read. `runtime/app.py` is what
this is mixed into, and is everything the loop is given rather than everything it does.
"""
from __future__ import annotations

import logging
import os
import sys
import threading
import time
import traceback
import uuid

from .. import compatio, config, l10n
from ..logbook import EngineLog
from ..openstate import open_state
from ..store import (SCHEMA_VERSION, RecordSchemaMismatch, StateFromNewerVersion, Store,
                     StoreError)
from ..windows import AdapterError, Mutex, StopEvent, wait_any


EXIT_OK = 0
EXIT_ERROR = 1
EXIT_BUSY = 3
# The state was written by a newer version of this tool. The launcher re-reads the
# installation once and starts whatever is installed now.
EXIT_SCHEMA_NEWER = 4
# Long enough that a status probe, which holds the single-instance mutex for
# microseconds, has certainly let go; short enough to be invisible at startup.


# Long enough that a status probe, which holds the single-instance mutex for
# microseconds, has certainly let go; short enough to be invisible at startup.
MUTEX_RETRY_SECONDS = 0.25
MIN_POLL = 5
MAX_POLL = 3600
DEFAULT_POLL = 30
# While anything of ours may be sitting in Codex's queue, look this often.
WATCH_SECONDS = 1.0
# However often Retry Now is pressed, at most one extra tick per this many seconds.
WAKE_COALESCE_SECONDS = 5.0
# A store that cannot be opened is retried with a growing wait, up to this.
OPEN_RETRY_MAX_SECONDS = 60.0
# What the log says about the engine it just accepted, in the word the gate reads for it -
# from the registry data in force (compatio.engine_word), the bundled baseline and an
# imported cache alike, so it never contradicts the compatibility line that follows it.


class WatchLoop:
    """One tick, and the wait before the next. Mixed into `App`."""

    def run(self, *, once: bool = False, poll: int | None = None) -> int:
        # Busy is checked twice, a moment apart, before it is believed.
        #
        # `watcher_running()` answers by taking this same mutex and letting it go again,
        # so every status read - the settings window, the MCP panel, `doctor`, and the
        # confirmation loop that now watches a start - holds it for a few microseconds.
        # A single instantaneous test can therefore lose to a status probe and conclude
        # that another watcher owns the machine, which is how a perfectly good watcher
        # could exit at the exact moment someone asked whether it was up.
        #
        # Single-instance safety is unchanged: a real second watcher holds this for its
        # whole life, so it fails both attempts. Only a microsecond-long probe passes.
        mutex = None
        for attempt in (0, 1):
            try:
                mutex = self.mutex(timeout=0.0).__enter__()
                break
            except AdapterError as exc:
                if str(exc) != "mutex_busy":
                    self.logger.info("single-instance mutex unavailable (%s); refusing to run", exc)
                    return EXIT_ERROR
                if attempt == 0:
                    time.sleep(MUTEX_RETRY_SECONDS)
                    continue
                self.logger.info("another watcher already holds the single-instance mutex; exiting")
                return EXIT_BUSY
        try:
            try:
                stop = self.stop_event().__enter__()
            except AdapterError as exc:
                # A stop event planted by a lower-integrity process would let that process
                # stop the watcher at will; refuse to run on it rather than obey it.
                self.logger.info("stop event unavailable (%s); refusing to run", exc)
                return EXIT_ERROR
            try:
                wake = None
                try:
                    wake = self.wake_event().__enter__()
                except AdapterError as exc:
                    # Only Retry Now loses its immediacy: the stored schedule still runs.
                    self.logger.info("wake event unavailable (%s); Retry Now waits for the next poll", exc)
                try:
                    try:
                        self._home_lock = self.home_lock().__enter__()
                    except AdapterError as exc:
                        self.logger.info("another engine or process holds this Codex home (%s); "
                                         "refusing to run", exc)
                        return EXIT_BUSY
                    try:
                        return self._loop(mutex, stop, wake, once=once, poll=poll)
                    finally:
                        self._home_lock.__exit__(None, None, None)
                        self._home_lock = None
                finally:
                    if wake is not None:
                        wake.__exit__(None, None, None)
            finally:
                stop.__exit__(None, None, None)
        finally:
            mutex.__exit__(None, None, None)

    def _poll_interval(self, store: Store, poll: int | None) -> int:
        # A transient store read here must NOT end the watcher; fall back to a safe poll.
        try:
            interval = poll if poll else store.settings()["poll_seconds"]
        except Exception:
            self._record_failure("poll interval read")
            interval = poll or DEFAULT_POLL
        return max(MIN_POLL, min(int(interval), MAX_POLL))

    def _wait_for(self, stop, wake, seconds: float):
        """'stop', 'wake', or None when the time ran out."""
        if wake is None:
            return "stop" if stop.wait(seconds) else None
        fired = wait_any([stop.handle, wake.handle], seconds)
        return "stop" if fired == 0 else "wake" if fired == 1 else None

    def _open_for_watcher(self, stop):
        """The watcher's store: upgraded under the mutex it holds, retried with backoff.

        Returns a Store, or an exit code. A state from a newer version is never retried
        and never treated as damage; the launcher starts the installed code instead.
        """
        delay = 1.0
        while True:
            try:
                store = Store(self.paths.state_dir, migrate=True, check=True)
                if store.migrated_from is not None:
                    self.logger.info("state upgraded from schema %d to %d", store.migrated_from, SCHEMA_VERSION)
                return store
            except StateFromNewerVersion:
                self.logger.info("schema_newer_than_watcher; exiting so the installed version can start")
                return EXIT_SCHEMA_NEWER
            except Exception:
                self._record_failure("opening state")
            if self._wait_for(stop, None, delay) == "stop":
                return EXIT_OK
            delay = min(delay * 2, OPEN_RETRY_MAX_SECONDS)

    def _heartbeat(self, store, session, started, ok):
        try:
            store.heartbeat(time.time(), pid=os.getpid(), session_id=session, started_at=started,
                            ok=ok, engine_state=self.engine_state(), code_version=config.version())
        except Exception:
            pass    # the heartbeat reports health; it must never be the thing that fails

    def _between_ticks(self, stop, wake, engine, interval, last_tick):
        """Wait for the next tick. Every second while anything of ours may be queued in
        Codex, the watch runs on its own; a wake is honoured at most once per few
        seconds. Returns 'stop', 'wake' or None."""
        deadline = time.monotonic() + interval
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            watching = False
            try:
                watching = bool(getattr(engine, "watch_needed", lambda: False)())
            except Exception:
                watching = False
            fired = self._wait_for(stop, wake, min(remaining, WATCH_SECONDS) if watching else remaining)
            if fired == "stop":
                return "stop"
            if fired == "wake":
                gap = WAKE_COALESCE_SECONDS - (time.monotonic() - last_tick)
                if gap > 0 and self._wait_for(stop, None, gap) == "stop":
                    return "stop"
                return "wake"
            if not watching:
                return None             # the whole interval was waited in one go
            try:
                engine.watch()
            except Exception:
                self._record_failure("watch")

    def _loop(self, mutex: Mutex, stop: StopEvent, wake=None, *, once: bool, poll: int | None) -> int:
        self.logger.info("watcher started (pid %d, state %s)", os.getpid(), self.paths.state_dir)
        # The edition, once, at the start - only where it says something. The standard edition's
        # plug is NULL and writes no line, so a standard watcher's log is what it always was
        # (decision C12).
        plug = getattr(self, "plug", None)
        if plug is not None and not plug.null:
            self.logger.info("edition %s", plug.badge)
        if mutex.abandoned:
            self.logger.info("previous watcher exited without releasing the mutex; reconciling before any send")
        store = self._open_for_watcher(stop)
        if isinstance(store, int):
            return store
        session, started = uuid.uuid4().hex[:12], time.time()
        engine = None
        last_enabled = None
        exit_code = EXIT_OK
        if not once:
            self._failure_baseline()
        # Not `tray`: `from . import tray` names the module in this file too, and a local
        # that shadows a module name reads as that module to anything scanning the source.
        icon = None if once else self._start_tray(stop)
        try:
            while True:
                ok = False
                try:
                    if store.schema_version() > SCHEMA_VERSION:
                        raise StateFromNewerVersion("newer schema")
                    # Built lazily and retried: a transient codex.exe probe failure (an
                    # antivirus scan or an in-progress Codex update at logon) must defer
                    # this tick, never end the watcher for the whole session.
                    if engine is None:
                        try:
                            engine = self.engine(store)
                        finally:
                            # With or without an engine: a refused engine is reported as
                            # what it is, and the gate's word is settled before any tick.
                            self._compatibility_tick()
                    else:
                        self.refresh_settings(engine)
                        self._compatibility_tick()
                    enabled = store.settings()["enabled"]
                    if enabled != last_enabled:
                        self.logger.info("auto-resume is %s", "enabled" if enabled else "disabled (kill switch active; no submissions)")
                        last_enabled = enabled
                    engine.tick()
                    ok = True
                except (StateFromNewerVersion, RecordSchemaMismatch):
                    # A newer version's state, or its rows met mid-tick: never a corruption,
                    # and never something this version should keep trying to read.
                    self.logger.info("schema_newer_than_watcher; exiting so the installed version can start")
                    exit_code = EXIT_SCHEMA_NEWER
                    break
                except StoreError:
                    self._record_failure("tick")
                except Exception:
                    self._record_failure("initialising Codex adapter" if engine is None else "tick")
                self._heartbeat(store, session, started, ok)
                if not once:
                    self._failure_baseline()            # made good at the next tick if a write was refused
                if icon is not None:
                    self._update_tray(icon, store)
                last_tick = time.monotonic()
                if once:
                    if engine is None:
                        exit_code = EXIT_ERROR
                    break
                interval = self._poll_interval(store, poll)
                if self._between_ticks(stop, wake, engine, interval, last_tick) == "stop":
                    self.logger.info("stop requested; watcher exiting")
                    break
        except KeyboardInterrupt:
            self.logger.info("interrupted; watcher exiting")
        finally:
            if icon is not None:
                icon.stop()
            store.close()
            self.logger.info("watcher stopped")
        return exit_code

    # ------------------------------------------------------------------ tray
    def _failure_baseline(self):
        """Where no time a failure was last seen can be believed, now: a failure from before this watcher - or before
        the upgrade that brought the red icon - is never shown as new (control.acknowledge_failure). At the start and
        at every tick, which costs a look at one file, so a write Windows refused once is made good."""
        from ..control import Control
        try:
            Control(self.paths).acknowledge_failure(baseline=True)
        except Exception as exc:
            self.logger.info("failure baseline not written (%s)", type(exc).__name__)
