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
from .windows import AdapterError, Mutex, StopEvent, WakeEvent


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
# A cancel must not fail because the watcher happens to be writing. The store already
# waits ten seconds for a lock; the cancel tries again for this long in total.
CANCEL_RETRY_SECONDS = 30.0
# A heartbeat older than this, from a watcher that holds the mutex, is not ticking.
TICK_STALE_SECONDS = 180.0

UPGRADE_PENDING = ("Upgrade pending: an older watcher still owns the state. Use Stop watcher, "
                   "then Start watcher, or sign out and back in.")
NEWER_STATE = ("The recovery state was written by a newer version of Codex Auto Resume. "
               "Update this installation; do not delete the state.")


# Every way this layer can refuse a request, as a stable machine value. The English
# sentence beside each one is what the command line prints and what a support log keeps;
# the code is what a front end looks up in the language the rest of the product is already
# speaking, because a window whose own lead sentence is Korean and whose explanation is
# English has told half the story in the wrong language.
#
# The vocabulary is closed on purpose. `interface.py` carries an `error.<code>` string for
# every member in every language, and the tests refuse both a raise whose code is not here
# and a code that reaches the catalogs without a sentence to say it, so a new refusal
# cannot quietly arrive untranslated.
ERROR_CODES = frozenset({
    "invalid_id", "invalid_thread_id", "invalid_enabled", "no_such_interruption",
    "not_installed", "start_failed", "store_unavailable", "newer_state", "upgrade_pending",
    "state_busy", "not_exhausted", "cancel_requested", "possibly_sent", "reset_limit",
    "already_finished", "being_sent", "in_flight", "observing", "cannot_continue",
    "cannot_check_now", "file_exists", "request_failed",
})
# The code for a refusal with nothing more specific to say, and the one every caller may
# assume is present. A rejection carrying no code at all would leave a front end holding
# the English sentence with no way to say it, which is the gap the codes exist to close,
# so the default is a real member of the set and never None.
FALLBACK_CODE = "request_failed"


class ControlError(RuntimeError):
    """A rejected request. The message is safe to show a user.

    `str(exc)` is exactly the English sentence it has always been, because the command
    line prints it and the logs keep it. `code` is that same refusal as one of
    `ERROR_CODES`, so a front end can say it in the person's own language instead of
    parsing prose that was never meant to be parsed.
    """

    def __init__(self, message, *, code: str = FALLBACK_CODE):
        super().__init__(message)
        self.code = code or FALLBACK_CODE


# What the store says when it refuses to restore a budget or to bring a check forward, as
# the sentence a person reads and the code a front end translates. Each detail keeps its
# own code rather than sharing one "cannot" for the group: "it was cancelled", "it may
# already have been sent" and "you have given it its attempts back as often as you may"
# have three different next steps, and one code for the three would hand every front end a
# single unhelpful sentence to show for all of them.
#
# The entry under None is each table's own last resort, so a detail this layer has never
# heard of - a store a version ahead, a record that vanished between two statements - still
# arrives as a coded rejection rather than as an uncoded one.
_REFUSALS_RESTORE = {
    "not_exhausted": ("that recovery has not been exhausted", "not_exhausted"),
    "finished": ("that recovery has already finished", "already_finished"),
    "cancel_requested": ("that recovery was cancelled", "cancel_requested"),
    "possibly_sent": ("that recovery may already have been sent", "possibly_sent"),
    # Left as a template: the count belongs to this layer's own constant, and a sentence
    # frozen at import stops following it the moment that constant moves.
    "reset_limit": ("its budget was already reset %d times; continue this task in Codex "
                    "yourself", "reset_limit"),
    # The record went between the read and the write - the watcher can finish one and the
    # row can be hidden. That is not a refusal of policy, and saying so would send a person
    # looking for a rule that does not exist.
    "unknown_record": ("no such interruption", "no_such_interruption"),
    None: ("that recovery cannot be continued", "cannot_continue"),
}
_REFUSALS_RETRY = {
    "finished": ("that recovery has already finished", "already_finished"),
    "cancel_requested": ("that recovery was cancelled", "cancel_requested"),
    "claimed": ("that recovery is being sent now", "being_sent"),
    "in_flight": ("that recovery is already in Codex", "in_flight"),
    "observing": ("that recovery is already running in Codex", "observing"),
    "unknown_record": ("no such interruption", "no_such_interruption"),
    None: ("that recovery cannot be checked now", "cannot_check_now"),
}


def _refusal(table: dict, detail) -> tuple:
    """The sentence and the code for what the store refused, or the table's last resort."""
    message, code = table.get(detail) or table[None]
    return (message % MAX_BUDGET_RESETS if "%d" in message else message), code


def _identifier(value, name="interruption id") -> str:
    """Interruption ids are opaque lowercase hex. Nothing else addresses a record."""
    text = str(value or "").strip().lower()
    if len(text) != 64 or any(character not in "0123456789abcdef" for character in text):
        raise ControlError("invalid %s" % name, code="invalid_id")
    return text


def _thread_id(value) -> str:
    try:
        parsed = uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        raise ControlError("thread id must be a canonical UUID",
                           code="invalid_thread_id") from None
    if str(parsed) != str(value):
        raise ControlError("thread id must be lowercase canonical UUID text",
                           code="invalid_thread_id")
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
            # The sentence is the validator's own and names the setting it refused. The
            # closed set has no code for "this value is out of range", because a code is
            # there for a refusal a front end must word itself and both settings surfaces
            # already frame this one in their own language - "Not saved: {reason}" - around
            # the English detail. So this carries the generic code deliberately.
            raise ControlError(str(exc), code="request_failed") from None

    def restore_defaults(self) -> dict:
        try:
            return settings.save(self.settings_path(), settings.defaults())
        except settings.SettingsError as exc:
            # Generic for the same reason as `update_settings` above.
            raise ControlError(str(exc), code="request_failed") from None

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
            raise ControlError(NEWER_STATE, code="newer_state") from None
        except StoreError as exc:
            raise ControlError("local state is unavailable: %s" % exc,
                               code="store_unavailable") from None
        try:
            with Mutex(str(self.paths.state_dir), timeout=0.0):
                return Store(self.paths.state_dir, migrate=True, check=True)
        except AdapterError:
            pass
        except StoreError as exc:
            raise ControlError("local state is unavailable: %s" % exc,
                               code="store_unavailable") from None
        if legacy_ok:
            try:
                return LegacyStore(self.paths.state_dir)
            except StoreError:
                pass
        raise ControlError(UPGRADE_PENDING, code="upgrade_pending")

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
        import subprocess

        running = self.watcher_running()
        if running is True:
            return {"started": False, "confirmed": True,
                    "state": "already-running", "reason": "already running"}
        launcher = self.paths.home / "watcher-launcher.py"
        entry = launcher if launcher.is_file() else self.paths.entry_script
        if not Path(entry).is_file():
            raise ControlError("the watcher is not installed here", code="not_installed")
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
            raise ControlError("could not start the watcher: %s" % exc,
                               code="start_failed") from None
        result = self._confirm_watcher(process)
        result["started"] = True
        return result

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
                raise ControlError("no such interruption", code="no_such_interruption")
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
            raise ControlError("enabled must be true or false", code="invalid_enabled")
        with self._open(legacy_ok=True) as store:
            store.set_enabled(enabled, time.time())
            return {"enabled": bool(store.settings()["enabled"])}

    def set_thread_enabled(self, thread_id: str, enabled: bool, *, actor: str = "gui") -> dict:
        """Switch automatic recovery on or off for one conversation."""
        thread = _thread_id(thread_id)
        if not isinstance(enabled, bool):
            raise ControlError("enabled must be true or false", code="invalid_enabled")
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
                        raise ControlError("no such interruption", code="no_such_interruption")
                    record = store.get(key)
                break
            except ControlError:
                raise
            except StoreError:
                if time.monotonic() >= deadline:
                    raise ControlError("the state is busy; the cancel was not recorded",
                                       code="state_busy") from None
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
                raise ControlError("no such interruption", code="no_such_interruption")
            restored, detail = store.restore_budget_detailed(key, time.time(), actor=actor)
            if not restored:
                # The store checks "is it one of the two exhausted states" before it checks
                # anything else, so it calls a cancelled or recovered record "not_exhausted"
                # - which would tell a person their cancelled recovery still has attempts
                # left. This layer has the record in hand and can say which it really is.
                if detail == "not_exhausted" and record["state"] in TERMINAL:
                    detail = "cancel_requested" if record["cancel_requested"] else "finished"
                message, code = _refusal(_REFUSALS_RESTORE, detail)
                raise ControlError(message, code=code)
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
                raise ControlError("no such interruption", code="no_such_interruption")
            accepted, detail = store.request_retry_now(key, time.time(), actor=actor)
        if not accepted:
            message, code = _refusal(_REFUSALS_RETRY, detail)
            raise ControlError(message, code=code)
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
