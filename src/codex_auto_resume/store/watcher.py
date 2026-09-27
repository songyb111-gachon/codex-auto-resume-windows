"""The watcher's heartbeat, and what it says about itself."""
from __future__ import annotations

import re

from .. import machine
from ..domain import usage as readings
from ..domain.vocabulary import WatcherEnd
from ..machine import STATES
from .validate import ENGINE_STATES, WATCHER_ENDS, _finite, _short_text, _timestamp

# The number Windows gives a sign-in (win/ownprocess.py), as the heartbeat keeps it.
_SIGN_IN = re.compile(r"^[0-9a-f]{16}$")
# What a watcher that stops on purpose writes; RUNNING is the heartbeat's, UNEXPECTED a reader's.
_ENDS_WRITTEN = (WatcherEnd.CLEAN, WatcherEnd.MEMORY_GUARD)


def _bytes(value):
    return value if type(value) is int and 0 <= value < 2 ** 53 else None


def _sign_in(value):
    return value if isinstance(value, str) and _SIGN_IN.match(value) else None


class WatcherMixin:
    # ------------------------------------------------------------ the watcher
    def heartbeat(self, now: float, *, pid: int, session_id: str, started_at: float, ok: bool,
                  engine_state: str, code_version: str, usage=None, awake_since=None,
                  memory_peak=None, sign_in=None, booted_at=None) -> None:
        """The watcher's proof of life, written every tick.

        `usage` (v0.6.11) is the last usage reading the engine made, as (time, windows) - None when it
        has made none since it started, which leaves the reading already here as it was: the last one
        is the last one, whichever watcher read it. Only a reading `domain/usage.py` keeps is written.
        `awake_since` (v0.6.11) is since when the watcher keeps this PC awake, or None - written every
        tick, so a watcher that stopped keeping it awake says so at once. `memory_peak` (v0.6.11) is the
        most private memory the watcher has committed, in bytes, and `sign_in` and `booted_at` the sign-in
        it runs in and when Windows started (win/ownprocess.py). Every beat says the watcher is running
        (WatcherEnd.RUNNING) until one that stops on purpose says otherwise (`watcher_ended`)."""
        _timestamp(now, "now")
        state = engine_state if engine_state in ENGINE_STATES else "unknown"
        reading = self._reading(usage)
        awake = float(awake_since) if machine.epoch(awake_since, *machine.EPOCH_STORE) else None
        booted = float(booted_at) if machine.epoch(booted_at, *machine.EPOCH_STORE) else None
        with self._transaction() as connection:
            connection.execute(
                "INSERT INTO watcher_status (singleton, pid, session_id, started_at, last_tick_at, "
                "last_tick_ok, engine_state, code_version, awake_since, memory_peak, end_mark, ended_at, "
                "sign_in, booted_at) VALUES (1,?,?,?,?,?,?,?,?,?,?,NULL,?,?) "
                "ON CONFLICT(singleton) DO UPDATE SET "
                "pid=excluded.pid, session_id=excluded.session_id, started_at=excluded.started_at, "
                "last_tick_at=excluded.last_tick_at, last_tick_ok=excluded.last_tick_ok, "
                "engine_state=excluded.engine_state, code_version=excluded.code_version, "
                "awake_since=excluded.awake_since, memory_peak=excluded.memory_peak, "
                "end_mark=excluded.end_mark, ended_at=NULL, sign_in=excluded.sign_in, "
                "booted_at=excluded.booted_at",
                (int(pid), _short_text(str(session_id)[:64], "session_id", 64), _finite(started_at),
                 now, int(bool(ok)), state, _short_text(str(code_version)[:32], "code_version", 32), awake,
                 _bytes(memory_peak), WatcherEnd.RUNNING.value, _sign_in(sign_in), booted))
            if reading is not None:
                connection.execute("UPDATE watcher_status SET usage_at=?, usage=? WHERE singleton=1", reading)

    def watcher_ended(self, now: float, end: str) -> bool:
        """A watcher that stops on purpose says how (v0.6.11): CLEAN, or MEMORY_GUARD. Written over the
        heartbeat it left; a watcher that never beat has nothing to say it of. Returns whether it was
        written."""
        _timestamp(now, "now")
        if end not in _ENDS_WRITTEN:
            raise ValueError("not how a watcher ends on purpose")
        with self._transaction() as connection:
            changed = connection.execute("UPDATE watcher_status SET end_mark=?, ended_at=? WHERE singleton=1",
                                         (str(end), now)).rowcount
        return changed == 1

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
        end = row.get("end_mark")
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
            # v0.6.11: the most private memory it committed, in bytes (memguard.py); how it last ended, and
            # when, as it wrote it - RUNNING until a watcher stops on purpose - and the sign-in and the start
            # of Windows it ran in (control/watcher.py reads the four together). None where not one.
            "memory_peak": _bytes(row.get("memory_peak")),
            "end_mark": end if end in WATCHER_ENDS and end != WatcherEnd.UNEXPECTED else None,
            "ended_at": _finite(row.get("ended_at")),
            "sign_in": _sign_in(row.get("sign_in")),
            "booted_at": _finite(row.get("booted_at")),
        }
