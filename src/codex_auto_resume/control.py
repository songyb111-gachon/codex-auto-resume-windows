"""The shared control surface used by every front end.

The command line, the Codex skill, the MCP server and the standalone settings window
all call these functions. None of them talks to SQLite, the registry or the settings
file directly, so an action means the same thing however it was requested.

Two properties matter more than the API shape:

* **This is not a second recovery engine.** Nothing here scans Codex for failures,
  schedules an attempt, reserves an interruption or submits a continuation. It reads
  state and expresses intent; the watcher remains the only thing that recovers.
* **Configuration never requires Codex.** Everything except the few genuinely
  Codex-dependent operations works with the app closed, the plugin unloaded and the
  watcher stopped, because a user must be able to change policy exactly when the thing
  the policy governs is unavailable.
"""
from __future__ import annotations

import os
from pathlib import Path
import time
import uuid

from . import config, machine, settings, startup
from .store import (MAX_BUDGET_RESETS, TERMINAL, LegacyStore, StateFromNewerVersion, Store,
                    StoreError, UpgradePending)
from .windows import AdapterError, Mutex, WakeEvent


# How long to wait for a launched watcher to become visible, and how often to look.
#
# The watcher takes the single-instance mutex early in `App.run` - but early is still
# after a Python interpreter has started and imported the engine. Measured over five
# launches on a warm machine: 0.156 s to 0.297 s. The window is generous against a cold
# disk; the interval is short so the ordinary case returns almost at once.
WATCHER_START_TIMEOUT = 6.0
WATCHER_START_INTERVAL = 0.1
# A cancel must not fail because the watcher happens to be writing. The store already
# waits ten seconds for a lock; the cancel tries again for this long in total.
CANCEL_RETRY_SECONDS = 30.0
# A heartbeat older than this, from a watcher that holds the mutex, is not ticking.
TICK_STALE_SECONDS = 180.0

UPGRADE_PENDING = ("Upgrade pending: an older watcher still owns the state. Use Stop watcher, "
                   "then Start watcher, or sign out and back in.")
NEWER_STATE = ("The recovery state was written by a newer version of Codex Auto Resume. "
               "Update this installation; do not delete the state.")


class ControlError(RuntimeError):
    """A rejected request. The message is safe to show a user."""


def _identifier(value, name="interruption id") -> str:
    """Interruption ids are opaque lowercase hex. Nothing else addresses a record."""
    text = str(value or "").strip().lower()
    if len(text) != 64 or any(character not in "0123456789abcdef" for character in text):
        raise ControlError("invalid %s" % name)
    return text


def _thread_id(value) -> str:
    try:
        parsed = uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        raise ControlError("thread id must be a canonical UUID") from None
    if str(parsed) != str(value):
        raise ControlError("thread id must be lowercase canonical UUID text")
    return str(value)


# The journal entries that change a schedule or a flag and never the record's stored
# reason. Every other same-state event really did change the reason - `Store.update`
# writes one whenever `last_error` changed - and so really did change the public code.
_REASON_UNCHANGED = frozenset({"retry_now", "cancel_requested"})


def describe_record(row, *, enabled=True, thread_enabled=True, watcher=None) -> dict:
    """One record as every interface shows it: stable machine values only."""
    described = machine.describe(row, enabled=enabled, thread_enabled=thread_enabled, watcher=watcher)
    gates = machine.decode_gates(row.get("gate_eval")) if row.get("gate_eval") else None
    return {
        "interruption_id": row["interruption_id"],
        "thread_id": row["thread_id"],
        "state": row["state"],
        "code": described["code"],
        "reason": described["reason"],
        "overlays": described["overlays"],
        "eligible_at": described["eligible_at"],
        "terminal": described["terminal"],
        "category": row["category"],
        "detected_at": row["detected_at"],
        "reset_at": row["reset_at"],
        "next_retry_at": row["next_retry_at"],
        "recovery_attempts": row["recovery_attempts"],
        "no_progress_count": row["no_progress_count"],
        "chain_continuations": row["chain_continuations"],
        "chain_origin_id": row["chain_origin_id"],
        "parent_interruption_id": row["parent_interruption_id"],
        "budget_resets": row["budget_resets"],
        # So a front end can disable "Give attempts back" when the store would certainly
        # refuse it, instead of offering a button whose only answer is an error.
        "budget_resets_left": max(0, MAX_BUDGET_RESETS - row["budget_resets"]),
        "cancel_requested": bool(row["cancel_requested"]),
        "recovery_turn_status": row["recovery_turn_status"],
        "user_joined": bool(row["user_joined"]),
        "after_user_work": bool(row["after_user_work"]),
        "outcome_at": row["outcome_at"],
        "first_queued_at": row["first_queued_at"],
        "gates": {name: list(result) for name, result in gates.items()} if gates else None,
        "gates_at": row["gate_eval_at"],
    }


class Control:
    """Bound to one runtime home. Cheap to construct; opens the store per call."""

    def __init__(self, home=None):
        self.paths = home if isinstance(home, config.Paths) else config.Paths(home)

    # ------------------------------------------------------------------ settings
    def settings_path(self) -> Path:
        return self.paths.settings_file

    def get_settings(self) -> dict:
        return settings.load(self.settings_path())

    def update_settings(self, changes: dict) -> dict:
        try:
            return settings.update(self.settings_path(), changes)
        except settings.SettingsError as exc:
            raise ControlError(str(exc)) from None

    def restore_defaults(self) -> dict:
        try:
            return settings.save(self.settings_path(), settings.defaults())
        except settings.SettingsError as exc:
            raise ControlError(str(exc)) from None

    def describe_settings(self) -> list:
        return settings.describe()

    # ------------------------------------------------------------------- state
    def _open(self, *, legacy_ok: bool = False):
        """The state, opened the way every per-call opener must open it.

        An older schema is upgraded only while holding the watcher's single-instance
        mutex, which proves no watcher is using it. If a watcher holds the mutex it is
        an older one, and until it stops only the actions that reduce automation are
        offered (`legacy_ok`); everything else says the upgrade is pending.
        """
        try:
            return Store(self.paths.state_dir, check=False)
        except UpgradePending:
            pass
        except StateFromNewerVersion:
            raise ControlError(NEWER_STATE) from None
        except StoreError as exc:
            raise ControlError("local state is unavailable: %s" % exc) from None
        try:
            with Mutex(str(self.paths.state_dir), timeout=0.0):
                return Store(self.paths.state_dir, migrate=True, check=True)
        except AdapterError:
            pass
        except StoreError as exc:
            raise ControlError("local state is unavailable: %s" % exc) from None
        if legacy_ok:
            try:
                return LegacyStore(self.paths.state_dir)
            except StoreError:
                pass
        raise ControlError(UPGRADE_PENDING)

    def watcher_running(self):
        """True / False / None, where None means the probe itself was unavailable."""
        from .app import App
        return App(self.paths, console=False, enable_logging=False).watcher_running()

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
                "code_version": (status or {}).get("code_version")}

    def startup_enabled(self) -> bool:
        try:
            value = startup.current_value()
        except startup.StartupError:
            return False
        return bool(value and startup.belongs_to(value, self.paths.home))

    def set_startup_enabled(self, enabled: bool) -> bool:
        if not isinstance(enabled, bool):
            raise ControlError("enabled must be true or false")
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
            raise ControlError(str(exc)) from None
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
        import subprocess

        running = self.watcher_running()
        if running is True:
            return {"started": False, "confirmed": True,
                    "state": "already-running", "reason": "already running"}
        launcher = self.paths.home / "watcher-launcher.py"
        entry = launcher if launcher.is_file() else self.paths.entry_script
        if not Path(entry).is_file():
            raise ControlError("the watcher is not installed here")
        flags = 0
        if os.name == "nt":
            flags = (getattr(subprocess, "DETACHED_PROCESS", 0)
                     | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
        arguments = [str(startup.python_launcher()), str(entry)]
        if entry != launcher:
            # The stable launcher already knows its home; the raw entry point does not.
            arguments += ["--home", str(self.paths.home), "--quiet"]
        arguments.append("run")
        try:
            process = subprocess.Popen(arguments, cwd=str(self.paths.home), close_fds=True,
                                       creationflags=flags, stdin=subprocess.DEVNULL,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as exc:
            raise ControlError("could not start the watcher: %s" % exc) from None
        result = self._confirm_watcher(process)
        result["started"] = True
        return result

    def _confirm_watcher(self, process) -> dict:
        return await_watcher(self.watcher_running, process)

    def get_status(self) -> dict:
        values = self.get_settings()
        with self._open(legacy_ok=True) as store:
            stored = store.settings()
            counts = store.status_counts()
            legacy = isinstance(store, LegacyStore)
            watcher = self._watcher(store)
            codes: dict[str, int] = {}
            pending = 0
            if not legacy:
                for row in store.pending():
                    pending += 1
                    code = machine.public_code(row)
                    codes[code] = codes.get(code, 0) + 1
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
            "settings": values,
        }

    # ------------------------------------------------------------------- pending
    def _described(self, store, rows, source=None) -> list:
        settings_row = store.settings()
        disabled = store.disabled_threads()
        watcher = self._watcher(store)
        listed = []
        for row in rows:
            identity = {}
            if source is not None:
                try:
                    identity = source.identity(row["thread_id"]) or {}
                except Exception:
                    identity = {}
            item = describe_record(row, enabled=settings_row["enabled"],
                                   thread_enabled=row["thread_id"] not in disabled,
                                   watcher=watcher)
            item.update({"thread_enabled": row["thread_id"] not in disabled,
                         "name": identity.get("name"), "project": identity.get("project"),
                         "cwd_basename": identity.get("cwd_basename")})
            listed.append(item)
        return listed

    def list_pending(self, include_terminal: bool = False, source=None) -> list:
        """Pending recoveries, with display labels attached where available.

        Labels are decoration: every action below addresses a record by its exact
        interruption id, never by anything shown here.
        """
        with self._open() as store:
            rows = store.all_records() if include_terminal else store.pending()
            return self._described(store, rows, source)

    def history(self, limit: int = 200, include_hidden: bool = False, source=None) -> list:
        """Recent recoveries, newest first, for the History view. Clear history hides
        rows here and nowhere else."""
        with self._open() as store:
            return self._described(store, store.history(include_hidden=include_hidden, limit=limit), source)

    def timeline(self, interruption_id: str) -> dict:
        """The content-free journal of one recovery's whole chain, oldest first."""
        key = _identifier(interruption_id)
        with self._open() as store:
            record = store.get(key)
            if record is None:
                raise ControlError("no such interruption")
            events = store.events(chain_origin_id=record["chain_origin_id"])
        # Each state an event moved to, also as the public code every interface already
        # has words for - the stored state names are the engine's, not a person's.
        #
        # The code is derived the way the lists derive it, from the state and the reason
        # that was stored with it, so a release after a queue process that never started
        # reads "failed_retryable" here exactly as it does in Pending. The two entries
        # that move only a schedule or a flag keep whatever code that interruption
        # already had: their reason describes the action, not the record.
        previous = {}
        for event in events:
            to_state = event.get("to_state")
            owner = event.get("interruption_id")
            if (to_state and event.get("from_state") == to_state
                    and event.get("code") in _REASON_UNCHANGED and owner in previous):
                code = previous[owner]
            elif to_state:
                code = machine.public_code({"state": to_state, "last_error": event.get("reason")})
            else:
                code = None
            event["to_code"] = code
            if code is not None:
                previous[owner] = code
        return {"interruption_id": key, "chain_origin_id": record["chain_origin_id"], "events": events}

    def statistics(self, days: float | None = None) -> dict:
        since = 0.0 if not days else max(0.0, time.time() - float(days) * 86400)
        with self._open() as store:
            result = store.statistics(since)
        result["period_days"] = days
        return result

    # ------------------------------------------------------------------ mutations
    def set_enabled(self, enabled: bool) -> dict:
        """Global pause/resume. Reuses the existing kill switch rather than adding a
        second concept, so there is only ever one answer to "is recovery running".
        Pending records are preserved either way."""
        if not isinstance(enabled, bool):
            raise ControlError("enabled must be true or false")
        with self._open(legacy_ok=True) as store:
            store.set_enabled(enabled, time.time())
            return {"enabled": bool(store.settings()["enabled"])}

    def set_thread_enabled(self, thread_id: str, enabled: bool, *, actor: str = "gui") -> dict:
        """Switch automatic recovery on or off for one conversation."""
        thread = _thread_id(thread_id)
        if not isinstance(enabled, bool):
            raise ControlError("enabled must be true or false")
        with self._open(legacy_ok=True) as store:
            store.set_thread_enabled(thread, enabled, actor=actor)
            return {"thread_id": thread, "enabled": store.thread_enabled(thread)}

    def cancel_interruption(self, interruption_id: str, *, actor: str = "gui") -> dict:
        """Stop recovering one exact interruption, and anything that continues it.

        Always available: cancelling only ever reduces automation, so it never needs
        Codex to be running, and it is retried rather than lost when the watcher is
        busy writing. A continuation that may already be in Codex is only marked; the
        watcher takes it back if it is still queued.
        """
        key = _identifier(interruption_id)
        deadline = time.monotonic() + CANCEL_RETRY_SECONDS
        while True:
            try:
                with self._open() as store:
                    result = store.cancel_interruption(key, time.time(), actor=actor)
                    if result is None:
                        raise ControlError("no such interruption")
                    record = store.get(key)
                break
            except ControlError:
                raise
            except StoreError:
                if time.monotonic() >= deadline:
                    raise ControlError("the state is busy; the cancel was not recorded") from None
                time.sleep(0.5)
        effects = result["effects"]
        if not result["changed"]:
            message = "already finished; nothing to stop"
        elif any(effect == "cancel_requested" for effect in effects.values()):
            message = ("cancelled; a continuation already handed to Codex is withdrawn if it is "
                       "still queued, and one already running is not stopped")
        else:
            message = "cancelled"
        return {"interruption_id": key, "thread_id": record["thread_id"], "state": record["state"],
                "changed": result["changed"], "effects": effects, "message": message}

    def cancel_thread(self, thread_id: str, *, actor: str = "gui") -> dict:
        """Turn automatic recovery off for one conversation and stop what it has."""
        thread = _thread_id(thread_id)
        with self._open(legacy_ok=True) as store:
            store.cancel_thread(thread, time.time(), actor=actor)
        return {"thread_id": thread}

    def reset_recovery_budget(self, interruption_id: str, *, actor: str = "gui") -> dict:
        """Give an exhausted interruption its attempts back.

        Deliberately explicit, and deliberately not a send: the record re-enters the
        wait its kind of failure needs and every gate runs again from the top. It does
        not switch a conversation back on, and it can be done a few times per task, not
        without limit.
        """
        key = _identifier(interruption_id)
        with self._open() as store:
            record = store.get(key)
            if record is None:
                raise ControlError("no such interruption")
            restored, detail = store.restore_budget_detailed(key, time.time(), actor=actor)
            if not restored:
                raise ControlError({
                    "not_exhausted": "that recovery has not been exhausted",
                    "cancel_requested": "that recovery was cancelled",
                    "possibly_sent": "that recovery may already have been sent",
                    "reset_limit": ("its budget was already reset %d times; continue this task "
                                    "in Codex yourself" % MAX_BUDGET_RESETS),
                }.get(detail, "that recovery cannot be continued"))
            thread_on = store.thread_enabled(record["thread_id"])
            note = None if thread_on else ("automatic recovery is off for this conversation; "
                                           "switch it on for this recovery to run")
            return {"interruption_id": key, "state": store.get(key)["state"], "note": note}

    def request_retry_now(self, interruption_id: str, *, actor: str = "gui") -> dict:
        """Make a waiting interruption eligible immediately.

        This brings the *schedule* forward and nothing else. It does not send, does not
        bypass the loaded-thread requirement, does not bypass a usage window and does
        not skip revalidation: the watcher still runs the entire pipeline, and if usage
        is still exhausted the record simply goes back to waiting.
        """
        key = _identifier(interruption_id)
        with self._open() as store:
            record = store.get(key)
            if record is None:
                raise ControlError("no such interruption")
            accepted, detail = store.request_retry_now(key, time.time(), actor=actor)
        if not accepted:
            raise ControlError({
                "finished": "that recovery has already finished",
                "cancel_requested": "that recovery was cancelled",
                "claimed": "that recovery is being sent now",
                "in_flight": "that recovery is already in Codex",
                "observing": "that recovery is already running in Codex",
            }.get(detail, "that recovery cannot be checked now"))
        woke = False
        try:
            woke = WakeEvent(str(self.paths.state_dir)).signal()
        except Exception:
            woke = False
        now = time.time()
        if detail > now + 1:
            note = ("the usage reset is at a later time; the watcher checks then, and every "
                    "safety check still applies")
        elif woke:
            note = "checking now; every safety check still applies"
        else:
            note = "the watcher checks at its next poll; every safety check still applies"
        return {"interruption_id": key, "state": record["state"], "eligible_at": detail,
                "woke": woke, "note": note}

    def clear_history(self, *, actor: str = "gui") -> dict:
        """Hide finished recoveries from the History view. Deletes nothing, cancels
        nothing, and never hides a recovery that may still change."""
        with self._open() as store:
            return store.hide_history(time.time(), actor=actor)


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


def _version() -> str:
    return config.version()
