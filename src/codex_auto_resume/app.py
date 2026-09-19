"""Composition root and the watcher loop (single instance, stoppable, crash-tolerant)."""
from __future__ import annotations

import logging
import os
from pathlib import Path
import queue
import sys
import threading
import time
import traceback
import uuid

from . import compatio, config, l10n, notifier, settings as policy
from .engine import Engine
from .logbook import LOGGER_NAME, EngineLog, setup_logging
from .source import LocalSource
from .store import (SCHEMA_VERSION, RecordSchemaMismatch, StateFromNewerVersion, Store, StoreError,
                    UpgradePending)
from .windows import AdapterError, Backend, HomeLock, Mutex, StopEvent, WakeEvent, wait_any

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_BUSY = 3
# The state was written by a newer version of this tool. The launcher re-reads the
# installation once and starts whatever is installed now.
EXIT_SCHEMA_NEWER = 4
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
UPGRADE_PENDING = ("Upgrade pending: an older watcher still owns the state. Use Stop watcher, "
                   "then Start watcher, or sign out and back in.")
# What the log says about the engine it just accepted, in the word the gate reads for it -
# from the registry data in force (compatio.engine_word), the bundled baseline and an
# imported cache alike, so it never contradicts the compatibility line that follows it.
ENGINE_LOG_WORDS = {
    "verified": "is verified: its local checks pass, and the registry data in force verifies "
                "this build",
    "structurally_compatible": "is compatible: its local checks pass (`codex queue` still "
                               "offers --thread/--message), and the registry data in force "
                               "does not verify this build",
    "incompatible": "passes its local checks, but the registry data in force marks it "
                    "incompatible; nothing is sent while that data is in force",
}
ENGINE_LOG_CHECKS_ONLY = "passes its local checks (`codex queue` still offers --thread/--message)"


class Toasts:
    """Notifications off the tick path.

    Showing one runs PowerShell and can take many seconds. The engine only ever puts an
    event on this queue; a daemon thread shows them one at a time. A full queue drops
    the event and says so: a notification must never delay or decide a recovery.
    """

    def __init__(self, show, logger):
        self._show, self._logger = show, logger
        self._queue = queue.Queue(maxsize=64)
        self._thread = None
        self._lock = threading.Lock()

    def __call__(self, event, detail):
        try:
            self._queue.put_nowait((event, dict(detail)))
        except queue.Full:
            self._logger.info("notification queue full; %s dropped", event)
            return False
        with self._lock:
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._run, name="toasts", daemon=True)
                self._thread.start()
        return True

    def _run(self):
        while True:
            try:
                event, detail = self._queue.get(timeout=30)
            except queue.Empty:
                return
            try:
                self._show(event, detail)
            except Exception:
                self._logger.info("notification failed (%s)", event)


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
        # Everything this process says - the icon, its menu, every notification - is in the
        # Interface language the user stored, which is `system` until they choose.
        from . import tray_popup
        l10n.set_preference(self.settings.get("interface_language"))
        # Reduce motion and, since v0.6.5, the Theme: the notification card is drawn in it before
        # anybody has opened the popup, which is where the icon used to take it up first.
        tray_popup.adopt_settings(self.settings)
        self._tray = None
        # v0.6.5: notices on their way to the notification card on the icon's thread. Nothing is
        # attached until the icon's thread hosts the card; until then, and whenever it cannot,
        # every notification is today's toast (notifier.deliver).
        self._inbox = notifier.Inbox()
        self._codex_exe_override = codex_exe or self.settings.get("codex_exe")
        self.codex_home = Path(codex_home).resolve() if codex_home else config.codex_home()
        # Fixed at construction, so what the lock protects cannot move under a running
        # process when its environment is edited.
        self.lock_dir = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "codex-auto-resume" / "homes"
        self._backend = None
        # What discovery found for each candidate on its last attempt, and the Compatibility
        # Registry's evaluator with the word the engine's gate reads (None until it first runs).
        self._discovery = {}
        self._compat = None
        self._engine_state = None
        self._settings_stamp_seen = self._settings_stamp()
        self._home_lock = None

    # ------------------------------------------------------------ components
    def open_store(self, *, check: bool = False) -> Store:
        """Open the state for one command, as any per-call opener must.

        An older schema is upgraded only while holding the watcher's mutex, which proves
        no watcher is running - an older watcher would otherwise be writing rows the
        upgrade is changing. If a watcher does hold it, it can only be an older one (a
        current watcher upgrades at start), and the command is refused until it stops.
        """
        try:
            return Store(self.paths.state_dir, check=check)
        except UpgradePending:
            pass
        try:
            with self.mutex(timeout=0.0):
                return Store(self.paths.state_dir, migrate=True, check=True)
        except AdapterError:
            raise UpgradePending(UPGRADE_PENDING) from None

    def backend(self) -> Backend:
        if self._backend is None:
            discovery = {}

            def compatible(path):
                probe = Backend(self.codex_home, path)
                try:
                    probe._compatible()
                finally:
                    # Kept for the Compatibility Registry, so a refusal by a failed check can
                    # be reported as what it is. The decision itself is unchanged.
                    discovery[str(path)] = probe.last_checks()
            try:
                exe = config.discover_codex_exe(self._codex_exe_override, compatible)
            finally:
                self._discovery = discovery
            backend = Backend(self.codex_home, exe)
            # Discovery probed a throwaway instance; run the check on the one we keep so
            # engine_version/engine_verified are populated for status, doctor and logs.
            backend._compatible()
            try:
                word = compatio.engine_word(self.paths, backend.engine_version)
            except Exception:
                word = None
            self.logger.info("engine %s %s. Delivery is still proven per interruption before "
                             "anything is marked resumed.", backend.engine_version,
                             ENGINE_LOG_WORDS.get(word, ENGINE_LOG_CHECKS_ONLY))
            self._backend = backend
        return self._backend

    def engine_state(self) -> str:
        """The word the engine's `engine_compatible` gate reads, and the heartbeat stores.

        From the Compatibility Registry once the watcher has evaluated it: the backend it
        drives, the checks that backend passed, and the registry data in force. Before
        that - a per-call process, or the moment before the first evaluation - the answer
        the product always gave, which is the same word for every case that exists today.
        """
        if self._engine_state is not None:
            return self._engine_state
        backend = self._backend
        if backend is None:
            return "unknown"
        return "verified" if getattr(backend, "engine_verified", False) else "structurally_compatible"

    def _compatibility_tick(self) -> None:
        """Evaluate compatibility for this tick and write the report. Never ends the watcher.

        A failure here fails closed: the gate reads `unknown`, so nothing is sent on the
        strength of a check that did not run, and nothing already sent is touched.
        """
        try:
            if self._compat is None:
                explicit = self._codex_exe_override or os.environ.get(config.ENV_CODEX_EXE) or None
                self._compat = compatio.Evaluator(self.paths, self.codex_home, log=self.logger.info,
                                                  explicit=explicit)
            self._engine_state = self._compat.tick(self._backend, self._discovery)
        except Exception:
            self._engine_state = "unknown"
            self._record_failure("compatibility check")

    def source(self) -> LocalSource:
        return LocalSource(self.codex_home)

    def engine(self, store: Store, *, dispatch_lock=None) -> Engine:
        source = self.source()
        kwargs = {"log": EngineLog(self.logger), "notify": Toasts(self._notifier(source), self.logger),
                  "language": l10n.current(), "engine_state": self.engine_state,
                  "home_lock": lambda: self._home_lock is not None and self._home_lock.held}
        if dispatch_lock is not None:
            kwargs["dispatch_lock"] = dispatch_lock
        engine = Engine(store, source, self.backend(), **kwargs)
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
        previous = self.settings.get("interface_language")
        self.settings = values
        engine.apply_policy(values)
        from . import tray_popup
        tray_popup.adopt_settings(values)
        if values.get("interface_language") != previous:
            from . import interface
            l10n.set_preference(values.get("interface_language"))
            if self._tray is not None:
                # The icon's words change with the language. Nothing else about the icon
                # does, and nothing about recovery does at all.
                self._tray.set_strings(interface.catalog())
        self.logger.info("settings reloaded")
        return True

    def _notifier(self, source):
        """Turn an engine lifecycle event into a notification: the card, or a Windows toast.

        Two things are deliberately decided here rather than in the engine. The labels
        - a task's title, its project - are looked up at notification time, so the
        engine never acquires a display dependency and keeps working purely from the
        exact thread UUID. And whether an event is shown at all is read from the
        settings on every event, so turning notifications off takes effect at once
        instead of at the next restart.

        Since v0.6.5 the event is built into one Notice (notifier.build: the same mapping,
        event for event, that was written out here until then) and shown by exactly one
        route (notifier.deliver): the product's card beside the notification area when the
        icon's thread hosts it and Windows says a notification may pop, else today's toast,
        byte for byte. This runs on the Toasts thread, never on the tick path.
        """
        def announce(event, detail):
            if not policy.notification_enabled(self.settings, event):
                return False
            thread_id = detail.get("thread_id")
            try:
                identity = source.identity(thread_id)
            except Exception:
                identity = None     # an unnamed task is still worth announcing
            notice = notifier.build(event, detail, identity)
            if notice is None:
                return False
            return notifier.deliver(notice, inbox=self._inbox,
                                    setting=self.settings.get(notifier.CARD_SETTING, True) is True)[1]
        return announce

    def _notice_action(self, uri):
        """A card's button, on a worker thread: what its toast button would do, done in process.

        Only an open URI for one of the window's pages, or a cancel of one exact interruption
        through the control layer with the toast's actor; everything else is ignored
        (notifier.activate). What a cancel says afterwards goes out the way any notice does, and
        what the press did - or why it did nothing - is one line in this log, as the toast's is.
        """
        from . import tray
        from .control import Control
        return notifier.activate(uri, control=Control(self.paths),
                                 open_dashboard=lambda page: tray.open_dashboard(self.paths.home, page),
                                 announce=lambda notice: notifier.deliver(
                                     notice, inbox=self._inbox,
                                     setting=self.settings.get(notifier.CARD_SETTING, True) is True),
                                 log=self.logger.info)

    def mutex(self, timeout: float = 0.0) -> Mutex:
        return Mutex(str(self.paths.state_dir), timeout=timeout)

    def stop_event(self) -> StopEvent:
        return StopEvent(str(self.paths.state_dir))

    def wake_event(self) -> WakeEvent:
        return WakeEvent(str(self.paths.state_dir))

    def home_lock(self) -> HomeLock:
        return HomeLock(self.codex_home, self.lock_dir)

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
        if mutex.abandoned:
            self.logger.info("previous watcher exited without releasing the mutex; reconciling before any send")
        store = self._open_for_watcher(stop)
        if isinstance(store, int):
            return store
        session, started = uuid.uuid4().hex[:12], time.time()
        engine = None
        last_enabled = None
        exit_code = EXIT_OK
        tray = None if once else self._start_tray(stop)
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
                if tray is not None:
                    self._update_tray(tray, store)
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
            if tray is not None:
                tray.stop()
            store.close()
            self.logger.info("watcher stopped")
        return exit_code

    # ------------------------------------------------------------------ tray
    def _start_tray(self, stop):
        """The icon, if the user wants one. A tray that cannot start costs the icon only."""
        if os.name != "nt" or not self.settings.get("show_tray", True):
            return None
        from . import interface, tray
        from .control import Control
        home = self.paths.home

        def toggle(paused):
            Control(self.paths).set_enabled(bool(paused))

        icon = home / "codex-auto-resume.ico"
        if not icon.is_file():
            icon = config.PROJECT_ROOT / "assets" / "codex-auto-resume.ico"
        # The popup's names come through `list_pending`, which asks the same read-only
        # source the notifications use for a conversation's display name and nothing else.
        try:
            names = self.source()
        except Exception:
            names = None
        # The notification card lives on the icon's thread too (notice_window.CardStack): the
        # icon attaches the inbox once it hosts the card, a button on a card comes back to
        # `_notice_action` on a worker thread, and every notice the card took is ended once by
        # notifier.complete - its silent history copy, or today's toast if it was never seen.
        icon_tray = tray.Tray(icon_path=icon, strings=interface.catalog(),
                              on_open=lambda: tray.open_dashboard(home), on_toggle=toggle,
                              on_pending=lambda: tray.open_dashboard(home, "pending"),
                              on_stop=lambda: StopEvent(str(self.paths.state_dir)).signal(),
                              control=Control(self.paths), pending_source=names,
                              on_dashboard=lambda: tray.open_dashboard(home, "pending"),
                              log=self.logger.info, inbox=self._inbox,
                              on_notice_action=self._notice_action,
                              on_notice_complete=notifier.complete)
        if not icon_tray.start():
            return None
        self._tray = icon_tray
        return icon_tray

    def _update_tray(self, icon_tray, store):
        from . import tray
        try:
            icon_tray.update(tray.snapshot_from(store, time.time()))
        except Exception:
            pass
