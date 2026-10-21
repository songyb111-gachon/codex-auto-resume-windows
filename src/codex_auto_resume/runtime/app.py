"""The composition root: everything the product is wired out of, built once and handed round.

The log, the settings, the state, the Codex reader, the Windows backend, the engine, the icon
and the notifications are all opened here and only here, so a caller is handed what it uses
instead of reaching for it. What the watcher then does with them is `runtime/loop.py`, mixed
into this class.

So is the edition's plug: looked for once, and handed to the engine, the icon's control layer
and a card's button alike, so everything one watcher does is asked of the same plug.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
import sys
import threading
import time
import traceback
import uuid

from .. import (compatio, config, edition, l10n, managed, needsyou, notice_kinds, notifier, notify, oncewords,
               settings as policy)
from ..codex import LocalSource
from ..codex.chains import memory as chain_memory
from ..codex.pairing import app_engines
from ..domain.plug import DEFER, EXTRA, Surface, guard
from ..engine import Engine
from ..logbook import LOGGER_NAME, EngineLog, setup_logging
from ..openstate import open_state
from ..store import SCHEMA_VERSION, Store, StoreError
from ..win import network
from ..windows import AdapterError, Backend, HomeLock, Mutex, StopEvent, WakeEvent
from .loop import EXIT_BUSY, EXIT_ERROR, EXIT_MEMORY_GUARD, EXIT_OK, EXIT_SCHEMA_NEWER, WatchLoop  # noqa: F401
from .toasts import Toasts


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
    "checked": "is checked: its local checks pass, and the registry data in force records the "
               "maintainer's checks passing on this build; no real recovery has verified it yet",
}
ENGINE_LOG_CHECKS_ONLY = "passes its local checks (`codex queue` still offers --thread/--message)"

# v0.6.13: while the app runs its Codex server from another official build and the watcher still
# holds the one it found - that build failed its checks when it looked, as `codex --version` can
# while an update is still writing it - it looks again after a minute, then twice as long each
# time, up to every 15 minutes (App.engine_moved). A change is looked for at once.
ELSEWHERE_FIRST_WAIT = 60
ELSEWHERE_LONGEST_WAIT = 15 * 60


def _file_stamp(path):
    """Which file stands at `path`: its size and write time, or None when there is none."""
    try:
        stat = os.stat(path)
    except OSError:
        return None
    return (stat.st_size, stat.st_mtime_ns)


class App(WatchLoop):
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
        # v0.6.11: what an administrator's policy keys hold (managed.py), and the settings as they
        # leave them - which is what every part of this process works from - kept apart from the
        # stored ones the engine is handed with them.
        self.managed = self._read_managed()
        self._stored = config.load_settings(paths)
        self.settings = managed.clamp(self._stored, self.managed)
        # Everything this process says - the icon, its menu, every notification - is in the
        # Interface language the user stored, which is `system` until they choose.
        from ..ui import popup
        l10n.set_preference(self.settings.get("interface_language"))
        # Reduce motion and, since v0.6.5, the Theme: the notification card is drawn in it before
        # anybody has opened the popup, which is where the icon used to take it up first.
        popup.adopt_settings(self.settings)
        self._tray = None
        # v0.6.5: notices on their way to the notification card on the icon's thread. Nothing is
        # attached until the icon's thread hosts the card; until then, and whenever it cannot,
        # every notification is today's toast (notifier.deliver).
        self._inbox = notifier.Inbox()
        # v0.6.11: notices about the watcher itself - the memory guard's - off the tick path.
        self._watcher_toasts = None
        self._codex_exe_override = codex_exe or self.settings.get("codex_exe")
        self.codex_home = Path(codex_home).resolve() if codex_home else config.codex_home()
        # Fixed at construction, so what the lock protects cannot move under a running
        # process when its environment is edited.
        self.lock_dir = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "codex-auto-resume" / "homes"
        self._backend = None
        self._backend_stamp = None
        # v0.6.13: the official engines the app main ran instead of the one found, each with its file's
        # stamp, the last time that made the watcher look again - so it looks at once per change - and
        # when, on the monotonic clock, it looks again while that change stands, and after how long.
        self._elsewhere_seen = frozenset()
        self._elsewhere_due = 0.0
        self._elsewhere_wait = ELSEWHERE_FIRST_WAIT
        # What discovery found for each candidate on its last attempt, and the Compatibility
        # Registry's evaluator with the word the engine's gate reads (None until it first runs).
        self._discovery = {}
        self._compat = None
        self._engine_state = None
        self._settings_stamp_seen = self._settings_stamp()
        self._home_lock = None
        self._plug = None
        # v0.6.15-beta: the one dispatch lock of this watcher, handed to every engine it builds (one per
        # Codex home it watches, runtime/homes.py): a send and the watch of a record are never made at once.
        self._dispatch_lock = threading.RLock()

    @property
    def plug(self):
        """This process's plug, as core holds one (domain/plug.py): the edition's, looked for the
        first time it is needed and the same object for the rest of the process's life."""
        if getattr(self, "_plug", None) is None:
            self._plug = guard(edition.plug(self.paths))
        return self._plug

    # ------------------------------------------------------------ components
    def open_store(self, *, check: bool = False) -> Store:
        """Open the state for one command, as any per-call opener must (openstate.open_state).

        An older schema is upgraded only under the watcher's mutex, and while an older watcher
        holds it the command is refused (UpgradePending) until that watcher stops - as it is
        while an installation holds its lock, when the state may have been converted for the
        version being installed.
        """
        return open_state(self.paths.state_dir, legacy="never", check=check, hold_while_installing=True)

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
            asked = []

            def running():
                # v0.6.13: asked only where several official builds pass (config.discover_codex_exe).
                asked.append(True)
                return app_engines()
            try:
                exe = config.discover_codex_exe(self._codex_exe_override, compatible, running=running)
            finally:
                self._discovery = discovery
            if asked:
                self.logger.info("more than one official Codex engine passes the engine checks; "
                                 "the one the ChatGPT app runs as its Codex server is the one driven")
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
            self._backend_stamp = _file_stamp(backend.codex_exe)
            # v0.6.11: the edition's plug is told the Codex found here, so that a capability's
            # own session is with this very Codex and home - the setting, the arguments and
            # discovery's choice included - and not one it found for itself. NULL is told nothing.
            self.plug.codex(backend.codex_exe, backend.codex_home)
        return self._backend

    def engine_moved(self) -> bool:
        """Whether the codex.exe the backend was built on is no longer that file; if so, drop it.

        Discovery runs once per backend, and Codex replaces its engine when it updates: on
        2026-10-07 the app (26.930) restarted into a new bin/<hex> folder and emptied the old
        one, and from then on the watcher paired the app with a server at a path no process
        ran - every recovery waited, "ChatGPT app or its Codex server not running", until the
        watcher was restarted. A file gone from its path, or another file at it, means the
        next build discovers again, every engine check included; the same file means nothing -
        unless the app's own pairing found the app main running its server from another
        official engine and none at this path (v0.6.13, `_served_elsewhere`): at once for each
        change, and again, less and less often, while that change stands.
        """
        if self._backend is None:
            return False
        if _file_stamp(self._backend.codex_exe) != self._backend_stamp:
            self.logger.info("the Codex engine found earlier is gone or was replaced; looking for it again")
        else:
            # v0.6.13: the same file, but the app runs its server from another official build - an
            # update that kept the old folder. At once for each change. A build that then failed its
            # checks - `codex --version` can fail while an update is still writing it - is looked for
            # again while the change stands, after ELSEWHERE_FIRST_WAIT and then twice as long each
            # time up to ELSEWHERE_LONGEST_WAIT: tried again, so that recovery never waits for the
            # watcher to restart, but never on every tick.
            elsewhere = self._served_elsewhere()
            if not elsewhere:
                return False
            now = time.monotonic()
            if elsewhere != self._elsewhere_seen:
                self._elsewhere_wait = ELSEWHERE_FIRST_WAIT
            elif now < self._elsewhere_due:
                return False
            else:
                self._elsewhere_wait = min(self._elsewhere_wait * 2, ELSEWHERE_LONGEST_WAIT)
            self._elsewhere_seen = elsewhere
            self._elsewhere_due = now + self._elsewhere_wait
            self.logger.info("the ChatGPT app runs its Codex server from another official Codex engine "
                             "than the one found earlier; looking for it again")
        self._backend = None
        self._discovery = {}
        return True

    def _served_elsewhere(self) -> frozenset:
        """The official engines (E1, config.candidate_codex_exes) the app main ran as its children
        the last time the pairing found none at the held path, each with its file's stamp; nothing
        where an engine was named (--codex-exe, the setting or the environment), which is never
        second-guessed, and nothing where the official location cannot be read."""
        served = getattr(self._backend, "served_elsewhere", None)
        if not served or self._codex_exe_override or os.environ.get(config.ENV_CODEX_EXE):
            return frozenset()
        try:
            official = {os.path.normcase(str(path)): path for path in config.candidate_codex_exes()}
            keys = {os.path.normcase(path) for path in served}
        except (config.ConfigError, OSError, TypeError):
            return frozenset()
        return frozenset((key, _file_stamp(official[key])) for key in keys if key in official)

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
        return LocalSource(self.codex_home, chains=chain_memory(self.paths.split_chains_file))

    def engine(self, store: Store, *, dispatch_lock=None) -> Engine:
        source = self.source()
        kwargs = {"log": EngineLog(self.logger), "notify": Toasts(self._notifier(source), self.logger),
                  "language": l10n.current(), "engine_state": self.engine_state,
                  "home_lock": lambda: self._home_lock is not None and self._home_lock.held,
                  # v0.6.11: asked only while Wait for an internet connection is on (power.py).
                  "connectivity": network.internet}
        kwargs["dispatch_lock"] = dispatch_lock if dispatch_lock is not None else self.dispatch_lock
        # v0.6.15-beta (P12): a store of its own for each worker that waits for a receipt (engine/launches.py).
        kwargs["open_store"] = self.worker_store
        # v0.6.16-beta.3: the words for this time a person added in the Dashboard, beside the state (oncewords.py).
        kwargs["once_words"] = oncewords.OnceWords.of(self.paths)
        engine = Engine(store, source, self.backend(), plug=self.plug, **kwargs)
        engine.apply_policy(self._stored, self.managed)
        self._observe_only(engine)
        self._managed_pause(engine)
        return engine

    def worker_store(self) -> Store:
        """A connection of its own to the watcher's state, for one worker's launch guard (engine/launches.py): the
        state the watcher has already opened and upgraded, so it is not checked again."""
        return Store(self.paths.state_dir, check=False)

    def dispatch_lock(self):
        """The watcher's one dispatch lock (v0.6.15-beta), as an engine asks for it: the same
        `threading.RLock` for every engine of this process, made once."""
        lock = getattr(self, "_dispatch_lock", None)
        if lock is None:
            lock = self._dispatch_lock = threading.RLock()
        return lock

    @staticmethod
    def _read_managed():
        """The policy keys in force (control/policy.py asks Windows, for an installed copy alone)."""
        from ..control import policy as settings_policy
        return settings_policy.managed_policy()

    def _managed_pause(self, engine: Engine) -> None:
        """An administrator's DisableAutoResume (v0.6.11), written into the state as a Pause before
        any tick - where the engine, the claim and every surface read it, and a queued continuation
        is taken back as a Pause takes it. The engine refuses on the key as well, so a write that
        fails sends nothing. Nothing here switches recovery back on when the key goes: that is a
        person's to do, as after an upgrade."""
        if not self.managed.disable_auto_resume:
            return
        try:
            if engine.store.settings()["enabled"]:
                engine.store.set_enabled(False, time.time())
                self.logger.info("auto-resume paused: an administrator's policy key says so (DisableAutoResume)")
        except Exception:
            self._record_failure("administrator's pause")

    def _observe_only(self, engine: Engine) -> None:
        """Write Observe only into the state as the settings say it (v0.6.11): the claim refuses on
        the state's switch, the engine on the setting, and this keeps the two saying one thing - a
        setting edited by hand, or saved while an older watcher held the state, included. A write
        that fails changes nothing that is sent: the engine still refuses on the setting alone."""
        try:
            engine.store.set_observe_only(bool(self.settings.get("observe_only")))
        except Exception:
            self._record_failure("observe-only switch")

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
        # v0.6.11: the policy keys are asked every tick, the way the file's stamp is, and a Pause one
        # holds is made good before the tick whatever else changed.
        held = self._read_managed()
        stamp = self._settings_stamp()
        if stamp == self._settings_stamp_seen and held == self.managed:
            self._managed_pause(engine)
            return False
        self._settings_stamp_seen = stamp
        keys_changed = held != self.managed
        if keys_changed:
            self.logger.info("administrator's policy keys: %s", ", ".join(held.codes()) or "none")
            self.managed = held
        self._stored = config.load_settings(self.paths)
        values = managed.clamp(self._stored, held)
        if values == self.settings and not keys_changed:
            return False
        previous = self.settings.get("interface_language")
        self.settings = values
        engine.apply_policy(self._stored, held)
        homes = getattr(self, "_homes", None)
        if homes is not None:
            homes.apply_policy(self._stored, held)
        self._observe_only(engine)
        self._managed_pause(engine)
        from ..ui import popup
        popup.adopt_settings(values)
        if values.get("interface_language") != previous:
            from .. import interface
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
            # v0.6.11: a needs-you notice carries the sound its person chose, if any (notify.py).
            sound = event == needsyou.EVENT and self.settings.get(needsyou.SOUND_FIELD) is True
            chat = getattr(self, "_chat", False)      # v0.6.19: the in-app chat on (_edition_notices)
            notice = notifier.build(event, detail, identity, sound=sound,
                                    destination=notifier.click_destination(self.settings, chat),
                                    stay=notice_kinds.chosen(self.settings))
            # v0.6.18: Open Codex beside its other buttons, where the edition's plug asked for it (_edition_notices).
            notice = notifier.with_open_codex(notice, getattr(self, "_open_codex", False))
            if notice is None:
                return False
            return notifier.deliver(notice, inbox=self._inbox,
                                    setting=self.settings.get(notifier.CARD_SETTING, True) is True)[1]
        return announce

    def _watcher_notice(self, event, detail, *, final=False):
        """A notice about the watcher itself (v0.6.11: the memory guard's, memguard.py; v0.6.12: the power
        action's, runtime/afterwork.py, which no switch silences), under the notifications switch alone. Queued off the tick path like any other; but a `final` one - the
        watcher is stopping - is Windows' own toast, raised before it goes: the card lives on the icon's
        thread, which ends with this watcher, and a toast outlives it in the notification center."""
        if final:
            return self._show_watcher_notice(event, detail, final=True)
        if getattr(self, "_watcher_toasts", None) is None:
            self._watcher_toasts = Toasts(self._show_watcher_notice, self.logger)
        return self._watcher_toasts(event, detail)

    def _show_watcher_notice(self, event, detail, final=False):
        # v0.6.12: the power action's notices are raised whatever the notification switches say - the
        # countdown's carries the promised way to stop it (Q8). Windows' Do not disturb may still hide one.
        if event not in notifier.POWER_EVENTS and not policy.notification_enabled(self.settings, event):
            return False
        notice = notifier.build(event, detail, destination=notifier.click_destination(self.settings,
                                                                                      getattr(self, "_chat", False)),
                                stay=notice_kinds.chosen(self.settings))
        if notice is None:
            return False
        card = not final and self.settings.get(notifier.CARD_SETTING, True) is True
        return notifier.deliver(notice, inbox=None if final else self._inbox, setting=card)[1]

    def _notice_action(self, uri):
        """A card's button, on a worker thread: what its toast button would do, done in process.

        Only an open URI for one of the window's pages, or a cancel of one exact interruption
        through the control layer with the toast's actor - or, since v0.6.16, where a click on the
        card itself goes, which may be the Codex app's link to its conversation; everything else is
        ignored (notifier.activate). What a cancel says afterwards goes out the way any notice does, and
        what the press did - or why it did nothing - is one line in this log, as the toast's is.
        """
        from ..ui import tray
        from ..control import Control
        return notifier.activate(uri, control=Control(self.paths, plug=self.plug),
                                 open_dashboard=lambda page: tray.open_dashboard(self.paths.home, page),
                                 announce=lambda notice: notifier.deliver(
                                     notifier.with_open_codex(notice, getattr(self, "_open_codex", False)),
                                     inbox=self._inbox,
                                     setting=self.settings.get(notifier.CARD_SETTING, True) is True),
                                 log=self.logger.info, open_link=notify.open_in_codex,
                                 stay=notice_kinds.chosen(self.settings),
                                 open_chat=lambda thread: tray.open_chat(self.paths.home, thread))

    def _demo(self):
        """Show me what happens (v0.6.11), asked from Diagnostics: one made-up card, on a worker thread
        (the presence checks are not the icon thread's to wait for), and only where a card may be shown
        now - never a toast (notifier.show_demo). The state, the engine and Codex are not touched."""
        def show():
            try:
                notifier.show_demo(notifier.build_demo(time.time()), inbox=self._inbox,
                                   setting=self.settings.get(notifier.CARD_SETTING, True) is True)
            except Exception as exc:
                self.logger.info("demo card not shown (%s)", type(exc).__name__)
        threading.Thread(target=show, name="demo", daemon=True).start()

    def mutex(self, timeout: float = 0.0) -> Mutex:
        return Mutex(str(self.paths.state_dir), timeout=timeout)

    def stop_event(self) -> StopEvent:
        return StopEvent(str(self.paths.state_dir))

    def wake_event(self) -> WakeEvent:
        return WakeEvent(str(self.paths.state_dir))

    def home_lock(self) -> HomeLock:
        return HomeLock(self.codex_home, self.lock_dir)

    # ------------------------------------------------------------ other Codex homes (v0.6.15-beta)
    def extra_home_lock(self, path) -> HomeLock:
        """The lock of a Codex home Settings add: by its path and its folder's identity, never by one alone."""
        return HomeLock(path, self.lock_dir, require_identity=True)

    def home_source(self, path) -> LocalSource:
        return LocalSource(path, chains=chain_memory(self.paths.split_chains_file))

    @staticmethod
    def home_backend(path, codex_exe) -> Backend:
        """A backend whose CODEX_HOME is that home, on the codex.exe the default home's discovery found - one
        engine binary for all, so the compatibility evaluation, made against the default home, stays one."""
        return Backend(path, codex_exe, require_holder=True)

    def home_engine(self, store: Store, source, backend, key, held) -> Engine:
        """The engine of a Codex home other than the default (runtime/homes.py): the NULL plug - the advanced
        edition acts on the default home only - the watcher's one dispatch lock, that home's key, reader,
        backend and lock, and the policy every engine has."""
        engine = Engine(store, source, backend, plug=None, dispatch_lock=self.dispatch_lock, home_key=key,
                        log=EngineLog(self.logger), notify=Toasts(self._notifier(source), self.logger),
                        language=l10n.current(), engine_state=self.engine_state, home_lock=held,
                        connectivity=network.internet, once_words=oncewords.OnceWords.of(self.paths))
        engine.apply_policy(self._stored, self.managed)
        return engine

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


    def _start_tray(self, stop):
        """The icon, if the user wants one. A tray that cannot start costs the icon only."""
        if os.name != "nt" or not self.settings.get("show_tray", True):
            return None
        from .. import interface
        from ..ui import tray
        from ..control import Control
        home = self.paths.home

        def toggle(paused):
            Control(self.paths, plug=self.plug).set_enabled(bool(paused))

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
                              control=Control(self.paths, plug=self.plug), pending_source=names,
                              on_dashboard=lambda: tray.open_dashboard(home, "pending"),
                              log=self.logger.info, inbox=self._inbox,
                              on_notice_action=self._notice_action,
                              on_notice_complete=notifier.complete,
                              demo_name=str(self.paths.state_dir), on_demo=self._demo,
                              edition=edition.shown(self.plug))
        if not icon_tray.start():
            return None
        self._tray = icon_tray
        return icon_tray

    def _update_tray(self, icon_tray, store):
        from ..ui import tray
        try:
            snapshot = tray.snapshot_from(store, time.time())
            # P10: what the edition's plug adds to what the icon draws from, under its one key.
            # The icon draws nothing from it yet; the standard edition adds nothing at all.
            added = self.plug.surface(Surface.TRAY, dict(snapshot))
            if added is not DEFER:
                snapshot[EXTRA] = added
            self._edition_notices(added)
            icon_tray.update(snapshot)
        except Exception:
            pass

    def _edition_surface(self, store):
        """What the edition's plug adds to the icon's snapshot, read where there is no icon (v0.6.18): the notices
        it asks for and the buttons it adds are a watcher's, not the icon's - Windows' toast shows them where no card
        can. The standard edition's plug adds nothing, and is not asked."""
        from ..ui import tray
        try:
            if self.plug.null:
                return
            self._edition_notices(self.plug.surface(Surface.TRAY, dict(tray.snapshot_from(store, time.time()))))
        except Exception:
            pass

    def _edition_notices(self, added):
        """What the edition's plug added to the icon's snapshot, taken up by the watcher: the usage meter's warnings
        (_near_limit), and from v0.6.18 the weekly update check's offers (_update_offered) and whether a notice about
        one conversation offers Open Codex
        (notifier.with_open_codex) - true only while the plug says so, so a plug that says nothing, or the standard
        edition's, leaves every notice as it was."""
        extra = added if isinstance(added, dict) else {}
        notice = extra.get("notice")
        self._open_codex = isinstance(notice, dict) and notice.get("open_codex") is True
        # v0.6.19: whether the in-app chat is on, so a click on a notice may go where `notice_click` says (notifier).
        self._chat = isinstance(notice, dict) and notice.get("chat") is True
        if added is not DEFER:
            self._near_limit(added)
            self._update_offered(added)

    def _update_offered(self, added):
        """The advanced edition's weekly update check offers a newer version (v0.6.18): each offer its plug adds to the
        icon's snapshot is shown once in this watcher's life, by its key, under the notifications switch, off the tick
        path like every watcher notice. The standard edition adds none."""
        update = added.get("update") if isinstance(added, dict) else None
        notices = update.get("notices") if isinstance(update, dict) else None
        shown = self.__dict__.setdefault("_update_shown", set())
        for notice in notices if isinstance(notices, list) else ():
            key = notice.get("key") if isinstance(notice, dict) else None
            if not isinstance(key, str) or key in shown or len(shown) > 64:
                continue
            shown.add(key)
            self._watcher_notice("update_offered", {"version": notice.get("version"),
                                                    "prerelease": notice.get("prerelease") is True})

    def _near_limit(self, added):
        """The advanced edition's usage meter at a warning (v0.6.16-beta.3, issue #29): each notice its plug adds to
        the icon's snapshot is shown once in this watcher's life, by its key - a window and its reset - under the
        notifications switch, off the tick path like every watcher notice. The standard edition adds none."""
        meter = added.get("meter") if isinstance(added, dict) else None
        notices = meter.get("notices") if isinstance(meter, dict) else None
        shown = self.__dict__.setdefault("_near_limit_shown", set())
        for notice in notices if isinstance(notices, list) else ():
            key = notice.get("key") if isinstance(notice, dict) else None
            if not isinstance(key, str) or key in shown or len(shown) > 64:
                continue
            shown.add(key)
            self._watcher_notice("near_limit", {"minutes": notice.get("window_minutes"),
                                                "percent": notice.get("used_percent"),
                                                "reset_at": notice.get("reset_at"),
                                                # v0.6.16-beta.4: what the forced stop says, a closed word, else a warning
                                                "kind": notice.get("kind")})
