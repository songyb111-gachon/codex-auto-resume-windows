"""Composition root and the watcher loop (single instance, stoppable, crash-tolerant)."""
from __future__ import annotations

import logging
import os
from pathlib import Path
import sys
import time
import traceback

from . import config, notify, settings as policy
from .engine import Engine
from .logbook import LOGGER_NAME, EngineLog, setup_logging
from .source import LocalSource
from .store import Store
from .windows import AdapterError, Backend, Mutex, StopEvent

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_BUSY = 3
# Long enough that a status probe, which holds the single-instance mutex for
# microseconds, has certainly let go; short enough to be invisible at startup.
MUTEX_RETRY_SECONDS = 0.25
MIN_POLL = 5
MAX_POLL = 3600
DEFAULT_POLL = 30


class App:
    def __init__(self, paths: config.Paths, *, codex_exe=None, codex_home=None, console=False, enable_logging=True):
        self.paths = paths
        if enable_logging:
            self.paths.ensure()
            self.logger = setup_logging(paths.log_file, console=console)
        else:
            # Management commands (uninstall) must never create or reopen a log file.
            self.logger = logging.getLogger(LOGGER_NAME + ".silent")
            self.logger.handlers = [logging.NullHandler()]
            self.logger.propagate = False
        self.settings = config.load_settings(paths)
        self._codex_exe_override = codex_exe or self.settings.get("codex_exe")
        self.codex_home = Path(codex_home).resolve() if codex_home else config.codex_home()
        self._backend = None
        self._settings_stamp_seen = self._settings_stamp()

    # ------------------------------------------------------------ components
    def open_store(self) -> Store:
        return Store(self.paths.state_dir)

    def backend(self) -> Backend:
        if self._backend is None:
            def compatible(path):
                Backend(self.codex_home, path)._compatible()
            exe = config.discover_codex_exe(self._codex_exe_override, compatible)
            backend = Backend(self.codex_home, exe)
            # Discovery probed a throwaway instance; run the check on the one we keep so
            # engine_version/engine_verified are populated for status, doctor and logs.
            backend._compatible()
            if not backend.engine_verified:
                self.logger.info(
                    "engine %s is not a version this tool was verified against; accepted "
                    "because `codex queue` still offers --thread/--message. Delivery is "
                    "still proven per interruption before anything is marked resumed.",
                    backend.engine_version)
            self._backend = backend
        return self._backend

    def source(self) -> LocalSource:
        return LocalSource(self.codex_home)

    def engine(self, store: Store, *, dispatch_lock=None) -> Engine:
        kwargs = {"log": EngineLog(self.logger), "notify": self._notifier(self.source())}
        if dispatch_lock is not None:
            kwargs["dispatch_lock"] = dispatch_lock
        engine = Engine(store, self.source(), self.backend(), **kwargs)
        engine.apply_policy(self.settings)
        return engine

    def _settings_stamp(self):
        """A cheap identity for the settings file, used to notice edits while running."""
        try:
            status = self.paths.settings_file.stat()
        except OSError:
            return None
        return (status.st_mtime_ns, status.st_size)

    def refresh_settings(self, engine: Engine) -> bool:
        """Adopt settings edited while the watcher is running.

        Someone changing a preference expects it to take effect, not to have to restart
        a background process they never started by hand. Only policy is re-read, and it
        goes through the same validator as every other path, so an edit made with a text
        editor cannot do anything an edit made in the window could not.
        """
        stamp = self._settings_stamp()
        if stamp == self._settings_stamp_seen:
            return False
        self._settings_stamp_seen = stamp
        values = config.load_settings(self.paths)
        if values == self.settings:
            return False
        self.settings = values
        engine.apply_policy(values)
        self.logger.info("settings reloaded")
        return True

    def _notifier(self, source):
        """Turn an engine lifecycle event into a Windows notification.

        Two things are deliberately decided here rather than in the engine. The labels
        - a task's title, its project - are looked up at notification time, so the
        engine never acquires a display dependency and keeps working purely from the
        exact thread UUID. And whether an event is shown at all is read from the
        settings on every event, so turning notifications off takes effect at once
        instead of at the next restart.
        """
        def announce(event, detail):
            if not policy.notification_enabled(self.settings, event):
                return False
            thread_id = detail.get("thread_id")
            try:
                identity = source.identity(thread_id)
            except Exception:
                identity = None     # an unnamed task is still worth announcing
            state = detail.get("state")
            if event == "interruption":
                return notify.scheduled(thread_id, detail.get("interruption_id"),
                                        detail.get("reset_at"),
                                        detail.get("category") or "usage_limit", identity)
            if event == "starting":
                return notify.starting(thread_id, identity)
            if event == "result":
                if state == "resumed":
                    return notify.resumed(thread_id, identity)
                # An uncertain submission is never resent, so it must not be reported
                # as a failure that will be retried.
                return notify.attempt_failed(thread_id, identity,
                                             certain=state != "submission_unknown")
            if event == "stopped":
                reason = ("no_progress" if state == "no_progress_exhausted"
                          else "attempts" if state == "retry_budget_exhausted" else None)
                return notify.stopped(thread_id, identity, reason=reason)
            return False
        return announce

    def mutex(self, timeout: float = 0.0) -> Mutex:
        return Mutex(str(self.paths.state_dir), timeout=timeout)

    def stop_event(self) -> StopEvent:
        return StopEvent(str(self.paths.state_dir))

    def watcher_running(self) -> bool | None:
        """True/False, or None when the probe itself is unavailable."""
        try:
            with self.mutex(timeout=0.0):
                return False
        except AdapterError as exc:
            if str(exc) == "mutex_busy":
                return True
            return None

    # ------------------------------------------------------------------- run
    def _record_failure(self, label: str) -> None:
        # Class names only in the main log; the traceback goes to the rotating error log.
        exc_type = sys.exc_info()[0]
        self.logger.info("%s failed (%s); no submission was made", label, exc_type.__name__ if exc_type else "error")
        try:
            with self.paths.error_log.open("a", encoding="utf-8") as stream:
                stream.write(time.strftime("[%Y-%m-%d %H:%M:%S] ") + label + "\n")
                stream.write(traceback.format_exc())
            if self.paths.error_log.stat().st_size > 2_000_000:
                rotated = self.paths.error_log.with_suffix(".log.1")
                self.paths.error_log.replace(rotated)
        except OSError:
            pass

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
            with self.stop_event() as stop:
                return self._loop(mutex, stop, once=once, poll=poll)
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

    def _loop(self, mutex: Mutex, stop: StopEvent, *, once: bool, poll: int | None) -> int:
        self.logger.info("watcher started (pid %d, state %s)", os.getpid(), self.paths.state_dir)
        if mutex.abandoned:
            self.logger.info("previous watcher exited without releasing the mutex; reconciling before any send")
        try:
            store = self.open_store()
        except Exception:
            self._record_failure("opening state")
            return EXIT_ERROR
        engine = None
        last_enabled = None
        exit_code = EXIT_OK
        try:
            while True:
                try:
                    # Built lazily and retried: a transient codex.exe probe failure (an
                    # antivirus scan or an in-progress Codex update at logon) must defer
                    # this tick, never end the watcher for the whole session.
                    if engine is None:
                        engine = self.engine(store)
                    else:
                        self.refresh_settings(engine)
                    enabled = store.settings()["enabled"]
                    if enabled != last_enabled:
                        self.logger.info("auto-resume is %s", "enabled" if enabled else "disabled (kill switch active; no submissions)")
                        last_enabled = enabled
                    engine.tick()
                except Exception:
                    self._record_failure("initialising Codex adapter" if engine is None else "tick")
                if once:
                    if engine is None:
                        exit_code = EXIT_ERROR
                    break
                interval = self._poll_interval(store, poll)
                if stop.wait(interval):
                    self.logger.info("stop requested; watcher exiting")
                    break
        except KeyboardInterrupt:
            self.logger.info("interrupted; watcher exiting")
        finally:
            store.close()
            self.logger.info("watcher stopped")
        return exit_code
