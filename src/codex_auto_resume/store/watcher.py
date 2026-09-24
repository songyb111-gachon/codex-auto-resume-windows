"""The watcher's heartbeat, and what it says about itself."""
from __future__ import annotations

from ..machine import STATES
from .validate import ENGINE_STATES, _finite, _short_text, _timestamp


class WatcherMixin:
    # ------------------------------------------------------------ the watcher
    def heartbeat(self, now: float, *, pid: int, session_id: str, started_at: float, ok: bool,
                  engine_state: str, code_version: str) -> None:
        """The watcher's proof of life, written every tick."""
        _timestamp(now, "now")
        state = engine_state if engine_state in ENGINE_STATES else "unknown"
        with self._transaction() as connection:
            connection.execute(
                "INSERT INTO watcher_status VALUES (1,?,?,?,?,?,?,?) ON CONFLICT(singleton) DO UPDATE SET "
                "pid=excluded.pid, session_id=excluded.session_id, started_at=excluded.started_at, "
                "last_tick_at=excluded.last_tick_at, last_tick_ok=excluded.last_tick_ok, "
                "engine_state=excluded.engine_state, code_version=excluded.code_version",
                (int(pid), _short_text(str(session_id)[:64], "session_id", 64), _finite(started_at),
                 now, int(bool(ok)), state, _short_text(str(code_version)[:32], "code_version", 32)))

    def watcher_status(self) -> dict | None:
        with self._read() as connection:
            row = connection.execute("SELECT * FROM watcher_status WHERE singleton=1").fetchone()
        if row is None:
            return None
        row = dict(row)
        return {
            "pid": row["pid"] if isinstance(row["pid"], int) else None,
            "started_at": _finite(row["started_at"]),
            "last_tick_at": _finite(row["last_tick_at"]),
            "last_tick_ok": bool(row["last_tick_ok"]),
            "engine_state": row["engine_state"] if row["engine_state"] in ENGINE_STATES else "unknown",
            "code_version": row["code_version"] if isinstance(row["code_version"], str) else None,
        }
