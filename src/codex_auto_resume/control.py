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

from . import config, settings, startup
from .store import TERMINAL, Store, StoreError


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

    # -------------------------------------------------------------------- status
    def _open(self) -> Store:
        try:
            return Store(self.paths.state_dir)
        except StoreError as exc:
            raise ControlError("local state is unavailable: %s" % exc) from None

    def watcher_running(self):
        """True / False / None, where None means the probe itself was unavailable."""
        from .app import App
        return App(self.paths, console=False, enable_logging=False).watcher_running()

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
            return {"started": False, "reason": "already running"}
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
            subprocess.Popen(arguments, cwd=str(self.paths.home), close_fds=True,
                             creationflags=flags, stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as exc:
            raise ControlError("could not start the watcher: %s" % exc) from None
        return {"started": True, "reason": None}

    def get_status(self) -> dict:
        values = self.get_settings()
        with self._open() as store:
            stored = store.settings()
            counts = store.status_counts()
            pending = len(store.pending())
        return {
            "version": _version(),
            "enabled": bool(stored["enabled"]),
            "watcher_running": self.watcher_running(),
            "startup_enabled": self.startup_enabled(),
            "pending": pending,
            "states": counts,
            "home": str(self.paths.home),
            "settings": values,
        }

    # ------------------------------------------------------------------- pending
    def list_pending(self, include_terminal: bool = False, source=None) -> list:
        """Pending recoveries, with display labels attached where available.

        Labels are decoration: every action below addresses a record by its exact
        interruption id, never by anything shown here.
        """
        with self._open() as store:
            rows = store.all_records() if include_terminal else store.pending()
            enabled = {row["thread_id"]: store.thread_enabled(row["thread_id"]) for row in rows}
        listed = []
        for row in rows:
            identity = {}
            if source is not None:
                try:
                    identity = source.identity(row["thread_id"]) or {}
                except Exception:
                    identity = {}
            listed.append({
                "interruption_id": row["interruption_id"],
                "thread_id": row["thread_id"],
                "state": row["state"],
                "category": row["category"],
                "detected_at": row["detected_at"],
                "reset_at": row["reset_at"],
                "next_retry_at": row["next_retry_at"],
                "recovery_attempts": row["recovery_attempts"],
                "no_progress_count": row["no_progress_count"],
                "thread_enabled": enabled[row["thread_id"]],
                "terminal": row["state"] in TERMINAL,
                "name": identity.get("name"),
                "project": identity.get("project"),
                "cwd_basename": identity.get("cwd_basename"),
            })
        return listed

    # ------------------------------------------------------------------ mutations
    def set_enabled(self, enabled: bool) -> dict:
        """Global pause/resume. Reuses the existing kill switch rather than adding a
        second concept, so there is only ever one answer to "is recovery running".
        Pending records are preserved either way."""
        if not isinstance(enabled, bool):
            raise ControlError("enabled must be true or false")
        with self._open() as store:
            store.set_enabled(enabled, time.time())
            return {"enabled": bool(store.settings()["enabled"])}

    def cancel_interruption(self, interruption_id: str) -> dict:
        """Stop recovering one exact interruption. Always available: cancelling only
        ever reduces automation, so it never needs Codex to be running."""
        key = _identifier(interruption_id)
        with self._open() as store:
            record = store.get(key)
            if record is None:
                raise ControlError("no such interruption")
            store.cancel(record["thread_id"], time.time())
            return {"interruption_id": key, "thread_id": record["thread_id"],
                    "state": store.get(key)["state"]}

    def cancel_thread(self, thread_id: str) -> dict:
        thread = _thread_id(thread_id)
        with self._open() as store:
            store.cancel(thread, time.time())
        return {"thread_id": thread}

    def reset_recovery_budget(self, interruption_id: str) -> dict:
        """Give an exhausted interruption its attempts back.

        Deliberately explicit, and deliberately not a send: the record re-enters the
        normal waiting state and every gate runs again from the top. The store decides
        whether the record is eligible, so this cannot restore a budget the state
        machine considers finished for some other reason.
        """
        key = _identifier(interruption_id)
        with self._open() as store:
            record = store.get(key)
            if record is None:
                raise ControlError("no such interruption")
            if record["state"] not in ("retry_budget_exhausted", "no_progress_exhausted"):
                raise ControlError("that recovery has not been exhausted")
            if not store.restore_budget(key, time.time()):
                raise ControlError("that recovery cannot be resumed")
            # Exhausting a budget also parks the thread; without this the record would
            # be eligible and the thread still switched off.
            store.set_thread_enabled(record["thread_id"], True)
            return {"interruption_id": key, "state": store.get(key)["state"]}

    def request_retry_now(self, interruption_id: str) -> dict:
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
            if record["state"] in TERMINAL:
                raise ControlError("that recovery has already finished")
            if record["cancel_requested"]:
                raise ControlError("that recovery was cancelled")
            store.update(key, next_retry_at=time.time())
            return {"interruption_id": key, "state": record["state"],
                    "note": "eligible now; every safety check still applies"}


def _version() -> str:
    import json
    manifest = config.PROJECT_ROOT / ".codex-plugin" / "plugin.json"
    try:
        return str(json.loads(manifest.read_text(encoding="utf-8")).get("version") or "unknown")
    except (OSError, ValueError):
        return "unknown"
