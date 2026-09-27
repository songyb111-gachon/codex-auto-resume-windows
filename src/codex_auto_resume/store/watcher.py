"""The watcher's heartbeat, and what it says about itself."""
from __future__ import annotations

from .. import machine
from ..domain import usage as readings
from ..machine import STATES
from .validate import ENGINE_STATES, _finite, _short_text, _timestamp


class WatcherMixin:
    # ------------------------------------------------------------ the watcher
    def heartbeat(self, now: float, *, pid: int, session_id: str, started_at: float, ok: bool,
                  engine_state: str, code_version: str, usage=None, awake_since=None) -> None:
        """The watcher's proof of life, written every tick.

        `usage` (v0.6.11) is the last usage reading the engine made, as (time, windows) - None when it
        has made none since it started, which leaves the reading already here as it was: the last one
        is the last one, whichever watcher read it. Only a reading `domain/usage.py` keeps is written.
        `awake_since` (v0.6.11) is since when the watcher keeps this PC awake, or None - written every
        tick, so a watcher that stopped keeping it awake says so at once."""
        _timestamp(now, "now")
        state = engine_state if engine_state in ENGINE_STATES else "unknown"
        reading = self._reading(usage)
        awake = float(awake_since) if machine.epoch(awake_since, *machine.EPOCH_STORE) else None
        with self._transaction() as connection:
            connection.execute(
                "INSERT INTO watcher_status (singleton, pid, session_id, started_at, last_tick_at, "
                "last_tick_ok, engine_state, code_version, awake_since) VALUES (1,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(singleton) DO UPDATE SET "
                "pid=excluded.pid, session_id=excluded.session_id, started_at=excluded.started_at, "
                "last_tick_at=excluded.last_tick_at, last_tick_ok=excluded.last_tick_ok, "
                "engine_state=excluded.engine_state, code_version=excluded.code_version, "
                "awake_since=excluded.awake_since",
                (int(pid), _short_text(str(session_id)[:64], "session_id", 64), _finite(started_at),
                 now, int(bool(ok)), state, _short_text(str(code_version)[:32], "code_version", 32), awake))
            if reading is not None:
                connection.execute("UPDATE watcher_status SET usage_at=?, usage=? WHERE singleton=1", reading)

    @staticmethod
    def _reading(usage):
        """(time, stored text) for a reading worth keeping, or None."""
        if not isinstance(usage, tuple) or len(usage) != 2:
            return None
        at, windows = usage
        text = readings.encode(windows)
        if text is None or not machine.epoch(at, *machine.EPOCH_STORE):
            return None
        return float(at), text

    def watcher_status(self) -> dict | None:
        with self._read() as connection:
            row = connection.execute("SELECT * FROM watcher_status WHERE singleton=1").fetchone()
        if row is None:
            return None
        row = dict(row)
        windows = readings.decode(row.get("usage"))
        at = _finite(row.get("usage_at"))
        return {
            "pid": row["pid"] if isinstance(row["pid"], int) else None,
            "started_at": _finite(row["started_at"]),
            "last_tick_at": _finite(row["last_tick_at"]),
            "last_tick_ok": bool(row["last_tick_ok"]),
            "engine_state": row["engine_state"] if row["engine_state"] in ENGINE_STATES else "unknown",
            "code_version": row["code_version"] if isinstance(row["code_version"], str) else None,
            # v0.6.11: the last usage reading, with when it was made - or None. A stored reading that is
            # not exactly one is none (domain/usage.py).
            "usage": {"read_at": at, "windows": windows} if windows is not None and at is not None else None,
            # v0.6.11: since when it keeps this PC awake while a task waits, or None (power.py).
            "awake_since": _finite(row.get("awake_since")),
        }
