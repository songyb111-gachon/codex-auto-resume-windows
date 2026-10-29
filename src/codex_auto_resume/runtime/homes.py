"""The Codex homes a watcher holds beside the default one (v0.6.15-beta), each recovered by an engine of its own.

The default home is the watcher's as it always was: locked at the start (runtime/loop.py), its engine built
by `App.engine` with the edition's plug. Up to three more are named in Settings (homes.py), and each one this
watcher can lock gets a `HomeRun` of its own: a reader of that home (LocalSource), a backend whose CODEX_HOME is
that home (one codex.exe for all - the one the default home's discovery found), a HomeLock on it - its path and
its folder's identity, held for the run's life - and an Engine with:

* the NULL plug: the advanced edition acts on the default home only, so no capability is asked about,
  pays for or sends to another home's record (R18);
* the watcher's one dispatch lock: no two sends at once, in any home;
* the home's key: its records carry it, its ids are derived with it (domain/ids.py), and it sees, claims and
  watches its own home's records alone (Store.records_in(..., home_key)).

A home whose lock is busy, whose folder cannot be read, or that is the same folder as one already watched is not
watched at all - no reader, no detection, no record - and is tried again every RETRY_SECONDS. A home taken out of
Settings has every record waiting in it cancelled, final (home_removed), and its run kept - reader, backend, lock
and watch, detecting and sending nothing (`Engine.retiring`) - until none of its records may still be in Codex's
queue; only then is its lock let go (R10, R11). A record of a home no Settings name, met at the start, is
cancelled the same way.

Whatever goes wrong with another home costs that home alone: the default home's tick has already run.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

from .. import homes as configured, machine
from ..domain.vocabulary import HomeState
from ..windows import AdapterError, HomeLock

# How often a home that could not be watched is tried again, and how often a watched one is asked whether the
# ChatGPT app runs on it.
RETRY_SECONDS = 600
REMOVED = "home_removed"


def _spelling(path) -> str:
    """A home's path as Settings spell it, case-folded: the same whether or not its folder can be reached now."""
    return os.path.normcase(os.path.abspath(str(path)))


class HomeRun:
    """One extra Codex home this watcher holds: what reads it, what sends to it, its lock and its engine."""

    def __init__(self, key, path, alias, lock, source, backend, engine):
        self.key, self.path, self.alias = key, path, alias
        self.lock, self.source, self.backend, self.engine = lock, source, backend, engine
        self.retiring = False
        self.other_home = False
        self.asked_at = float("-inf")

    def close(self):
        try:
            self.lock.__exit__(None, None, None)
        except Exception:
            pass


class Homes:
    """Every extra Codex home of one watcher. Ticked after the default home's engine, on the same thread."""

    def __init__(self, app, *, clock=time.monotonic):
        self.app, self.clock = app, clock
        self.runs = {}            # key -> HomeRun
        self.states = {}          # key -> HomeState of a configured home not watched now
        self._tried = {}          # key -> when it was last tried
        self._swept = False
        self._exe = None

    # ------------------------------------------------------------------ what Settings name
    def configured(self) -> dict:
        """key -> (path, alias) for each home Settings name beside the default, as the settings coerced them."""
        entries = configured.coerce((self.app.settings or {}).get(configured.FIELD, []), [])
        found = {}
        for entry in entries:
            try:
                found[configured.key(entry["path"])] = (Path(entry["path"]), entry["alias"])
            except (OSError, ValueError, RuntimeError):
                continue
        return found

    # ------------------------------------------------------------------ once a tick
    def sync(self, store) -> None:
        """Bring the runs in line with Settings: retire what was removed, let go of what has settled, start what
        can be started (each at most every RETRY_SECONDS), and rebuild every engine on a new codex.exe."""
        wanted = self.configured()
        now = self.clock()
        # v0.6.18: a home's key hashes its resolved path, which can change with the folder's reach - a mapped network
        # drive resolves to its UNC form online and to its letter offline. A key that no longer matches is never a
        # removal alone: a run whose path Settings still name is kept, and while a named folder is out of reach the
        # start's sweep waits, since that home may be known by another key once it is back.
        named = {_spelling(path) for path, _alias in wanted.values()}
        if not self._swept:
            orphans = [key for key in store.home_keys() if key not in wanted]
            if not orphans or not any(configured.problem(path) == configured.MISSING for path, _ in wanted.values()):
                self._swept = True
                for key in orphans:
                    store.cancel_home(key, time.time(), REMOVED)
        for key, run in list(self.runs.items()):
            if key not in wanted and not run.retiring and _spelling(run.path) in named:
                continue
            if key not in wanted and not run.retiring:
                run.retiring = run.engine.retiring = True
                cancelled = store.cancel_home(key, time.time(), REMOVED)
                self.app.logger.info("a Codex home was removed from Settings; %d waiting recover%s cancelled, "
                                     "and it is watched until what was sent there settles",
                                     cancelled, "y" if cancelled == 1 else "ies")
            elif key in wanted and run.retiring:
                run.retiring = run.engine.retiring = False          # added back: nothing cancelled comes back
            if run.retiring and not any(machine.may_be_queued(row["state"], row["queue_id"])
                                        for row in store.records_in(machine.WATCHED, home_key=key)):
                run.close()
                del self.runs[key]
                self.app.logger.info("a removed Codex home has nothing in flight any more; its lock is let go")
        exe = self._codex_exe()
        if exe is not None and exe != self._exe:
            self._exe = exe
            for run in self.runs.values():
                run.backend = self.app.home_backend(run.path, exe)
                run.engine = self._engine(store, run)
        for key, (path, alias) in wanted.items():
            run = self.runs.get(key)
            if run is not None:
                run.alias = alias
                if now - run.asked_at >= RETRY_SECONDS:
                    run.asked_at = now
                    run.other_home = self._other_home(run)
                continue
            if key in self._tried and now - self._tried[key] < RETRY_SECONDS:
                continue
            self._tried[key] = now
            self.states[key] = self._start(store, key, path, alias, exe)
        for key in list(self.states):
            if key not in wanted:
                del self.states[key]

    def _codex_exe(self):
        try:
            return self.app.backend().codex_exe
        except Exception:
            return None

    def _start(self, store, key, path, alias, exe) -> HomeState:
        """Watch one home, or say why it is not watched."""
        if exe is None or configured.problem(path) is not None:
            return HomeState.UNAVAILABLE
        default_lock = getattr(self.app, "_home_lock", None)
        taken = {getattr(default_lock, "identity", None)} | {run.lock.identity for run in self.runs.values()}
        if key == configured.key(self.app.codex_home):
            return HomeState.DUPLICATE
        lock = self.app.extra_home_lock(path)
        try:
            lock.__enter__()
        except AdapterError as exc:
            return HomeState.LOCK_BUSY if str(exc) == "home_lock_busy" else HomeState.UNAVAILABLE
        if lock.identity in taken:
            lock.__exit__(None, None, None)
            return HomeState.DUPLICATE
        try:
            backend = self.app.home_backend(path, exe)
            run = HomeRun(key, path, alias, lock, self.app.home_source(path), backend, None)
            run.engine = self._engine(store, run)
        except Exception:
            lock.__exit__(None, None, None)
            raise
        self.runs[key] = run
        self.states.pop(key, None)
        self.app.logger.info("another Codex home is watched beside the default one")
        return HomeState.WATCHED

    def _engine(self, store, run):
        engine = self.app.home_engine(store, run.source, run.backend, run.key, lambda: run.lock.held)
        engine.retiring = run.retiring
        return engine

    def _other_home(self, run) -> bool:
        """Whether the ChatGPT app runs, but not on this home: its server holds this home's state open, or it
        is on another one (codex/pairing.py `require_holder`). Asked every RETRY_SECONDS, for Settings' words."""
        try:
            return bool(self.app.backend().app_identity()) and not run.backend.app_identity()
        except Exception:
            return False

    def tick(self) -> None:
        for run in list(self.runs.values()):
            try:
                run.engine.tick()
            except Exception:
                self.app._record_failure("tick of another Codex home")

    def watch_needed(self) -> bool:
        return any(run.engine.watch_needed() for run in self.runs.values())

    def watch(self) -> None:
        for run in list(self.runs.values()):
            try:
                run.engine.watch()
            except Exception:
                self.app._record_failure("watch of another Codex home")

    def apply_policy(self, values, managed) -> None:
        for run in self.runs.values():
            run.engine.apply_policy(values, managed)

    def heartbeat(self):
        """What the heartbeat keeps of each home (store/watcher.py homes_text): None with the default alone."""
        listed = [{"key": "", "state": HomeState.WATCHED.value}]
        for key in self.configured():
            run = self.runs.get(key)
            state = (self.states.get(key, HomeState.UNAVAILABLE) if run is None
                     else HomeState.RETIRING if run.retiring
                     else HomeState.OTHER_HOME if run.other_home else HomeState.WATCHED)
            listed.append({"key": key, "state": str(state)})
        for key, run in self.runs.items():
            if run.retiring and all(entry["key"] != key for entry in listed):
                listed.append({"key": key, "state": HomeState.RETIRING.value})
        return listed[:4] if len(listed) > 1 else None

    def close(self) -> None:
        for run in self.runs.values():
            run.close()
        self.runs.clear()
