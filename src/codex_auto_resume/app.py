"""Composition root and the watcher loop (single instance, stoppable, crash-tolerant)."""
from __future__ import annotations

import logging
import os
from pathlib import Path
import sys
import time
import traceback

from . import config
from .engine import Engine
from .logbook import LOGGER_NAME, EngineLog, setup_logging
from .source import LocalSource
from .store import Store
from .windows import AdapterError, Backend, Mutex, StopEvent

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_BUSY = 3
MIN_POLL = 5
MAX_POLL = 3600


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

    # ------------------------------------------------------------ components
    def open_store(self) -> Store:
        return Store(self.paths.state_dir)

    def backend(self) -> Backend:
        if self._backend is None:
            def compatible(path):
                Backend(self.codex_home, path)._compatible()
            exe = config.discover_codex_exe(self._codex_exe_override, compatible)
            self._backend = Backend(self.codex_home, exe)
        return self._backend

    def source(self) -> LocalSource:
        return LocalSource(self.codex_home)

    def engine(self, store: Store, *, dispatch_lock=None) -> Engine:
        options = {"detection_lookback_seconds": float(self.settings["detection_lookback_hours"]) * 3600.0}
        kwargs = {"log": EngineLog(self.logger), "options": options}
        if dispatch_lock is not None:
            kwargs["dispatch_lock"] = dispatch_lock
        return Engine(store, self.source(), self.backend(), **kwargs)

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
        try:
            mutex = self.mutex(timeout=0.0).__enter__()
        except AdapterError as exc:
            if str(exc) == "mutex_busy":
                self.logger.info("another watcher already holds the single-instance mutex; exiting")
                return EXIT_BUSY
            self.logger.info("single-instance mutex unavailable (%s); refusing to run", exc)
            return EXIT_ERROR
        try:
            with self.stop_event() as stop:
                return self._loop(mutex, stop, once=once, poll=poll)
        finally:
            mutex.__exit__(None, None, None)

    def _loop(self, mutex: Mutex, stop: StopEvent, *, once: bool, poll: int | None) -> int:
        self.logger.info("watcher started (pid %d, state %s)", os.getpid(), self.paths.state_dir)
        if mutex.abandoned:
            self.logger.info("previous watcher exited without releasing the mutex; reconciling before any send")
        try:
            store = self.open_store()
        except Exception:
            self._record_failure("opening state")
            return EXIT_ERROR
        try:
            engine = self.engine(store)
        except Exception:
            self._record_failure("initialising Codex adapter")
            store.close()
            return EXIT_ERROR
        last_enabled = None
        exit_code = EXIT_OK
        try:
            while True:
                try:
                    enabled = store.settings()["enabled"]
                    if enabled != last_enabled:
                        self.logger.info("auto-resume is %s", "enabled" if enabled else "disabled (kill switch active; no submissions)")
                        last_enabled = enabled
                    engine.tick()
                except Exception:
                    self._record_failure("tick")
                if once:
                    break
                interval = poll if poll else store.settings()["poll_seconds"]
                interval = max(MIN_POLL, min(int(interval), MAX_POLL))
                if stop.wait(interval):
                    self.logger.info("stop requested; watcher exiting")
                    break
        except KeyboardInterrupt:
            self.logger.info("interrupted; watcher exiting")
        finally:
            store.close()
            self.logger.info("watcher stopped")
        return exit_code
