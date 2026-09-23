"""The switches the state holds: recovery on or off, and per conversation."""
from __future__ import annotations

import sqlite3
from typing import Any
from .errors import StoreError
from .validate import _flag, _integer, _timestamp, _uuid


class PolicyMixin:
    # ---------------------------------------------------------------- settings
    @staticmethod
    def _read_settings(connection: sqlite3.Connection) -> dict[str, Any]:
        rows = connection.execute("SELECT * FROM settings").fetchall()
        if len(rows) != 1 or rows[0]["singleton"] != 1:
            raise StoreError("Invalid settings")
        row = dict(rows[0])
        enabled = _flag(row["enabled"], "enabled")
        armed_at = _timestamp(row["armed_at"], "armed_at")
        poll = _integer(row["poll_seconds"], "poll_seconds")
        if not 5 <= poll <= 3600 or (enabled and armed_at == 0):
            raise StoreError("Invalid settings")
        return {"enabled": enabled, "armed_at": armed_at, "poll_seconds": poll}

    def settings(self) -> dict[str, Any]:
        with self._read() as connection:
            return self._read_settings(connection)

    def set_enabled(self, enabled: bool, now: float) -> None:
        if not isinstance(enabled, bool):
            raise StoreError("enabled must be boolean")
        _timestamp(now, "now")
        if enabled and now == 0:
            raise StoreError("Cannot arm with zero timestamp")
        with self._transaction() as connection:
            settings = self._read_settings(connection)
            # A new enable period excludes failures that happened while disabled.
            # Existing pending records remain eligible; collection applies this cutoff.
            armed_at = now if enabled and not settings["enabled"] else settings["armed_at"]
            connection.execute(
                "UPDATE settings SET enabled=?, armed_at=? WHERE singleton=1", (int(enabled), armed_at)
            )

    @staticmethod
    def _thread_enabled(connection: sqlite3.Connection, thread_id: str) -> bool:
        row = connection.execute("SELECT enabled FROM threads WHERE thread_id=?", (thread_id,)).fetchone()
        return True if row is None else _flag(row[0], "thread enabled")

    def thread_enabled(self, thread_id: str) -> bool:
        _uuid(thread_id, "thread_id")
        with self._read() as connection:
            return self._thread_enabled(connection, thread_id)

    def disabled_threads(self) -> set:
        with self._read() as connection:
            return {row[0] for row in connection.execute("SELECT thread_id FROM threads WHERE enabled=0")}

    def set_thread_enabled(self, thread_id: str, enabled: bool, *, actor: str = "engine",
                           at: float | None = None) -> None:
        _uuid(thread_id, "thread_id")
        if not isinstance(enabled, bool):
            raise StoreError("enabled must be boolean")
        with self._transaction() as connection:
            before = self._thread_enabled(connection, thread_id)
            connection.execute(
                "INSERT INTO threads VALUES (?,?) ON CONFLICT(thread_id) DO UPDATE SET enabled=excluded.enabled",
                (thread_id, int(enabled)),
            )
            if enabled and not before:
                self._event(connection, self._now(at), "thread_enabled", actor=actor)
