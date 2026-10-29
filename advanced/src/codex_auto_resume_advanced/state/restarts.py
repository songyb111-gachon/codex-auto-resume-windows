# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""What the edition keeps of the watcher's restarts after it stopped unexpectedly (crash_restart, v0.6.19).

    restarts   one row for each abnormal end the supervisor decided on: when, the watcher's exit code, and whether it
               was started again (1) or left stopped because three had been started in the hour before (0) - written
               by the launcher that supervises the watcher (engine/supervise.py), counted for the cap, kept 7 days
               (state/journal.py's pruning pass)

It holds no path, no word and no conversation: a time, a number and a flag.
"""
from __future__ import annotations

from .session import StateError, _timestamp

RESTARTER = "crash_restart"
_COLUMNS = ("at", "exit_code", "restarted")


class RestartsMixin:
    # ------------------------------------------------------------------ restarts
    def restart_noted(self, exit_code, restarted, *, at=None) -> bool:
        """One abnormal end decided on: its row written. Whether it was."""
        if exit_code is not None and type(exit_code) is not int:
            raise StateError("invalid exit code")
        if type(restarted) is not bool:
            raise StateError("invalid restarted")
        now = self._now(at)
        with self._transaction() as connection:
            connection.execute("INSERT OR REPLACE INTO restarts (at, exit_code, restarted) VALUES (?,?,?)",
                               (now, exit_code, int(restarted)))
        return True

    def restarts_since(self, since) -> list:
        """The rows since `since`, the oldest first; empty with no file."""
        _timestamp(since, "since")
        with self._read() as connection:
            if connection is None:
                return []
            rows = connection.execute("SELECT %s FROM restarts WHERE at >= ? ORDER BY at" % ", ".join(_COLUMNS),
                                      (float(since),)).fetchall()
        return [dict(zip(_COLUMNS, row)) for row in rows]


class RestartsHandle:
    """What crash_restart's code is given of the state (state.Scoped's `restarts`): the rows - read by any - and one
    write, only for crash_restart and only while the runtime has it on. Held in a closure, as the Scoped view is."""
    __slots__ = ("capability", "_calls")

    def __init__(self, state, capability, on):
        self.capability = capability

        def noted(exit_code, restarted):
            if capability != RESTARTER or on is None or on() is not True:
                raise StateError("the capability may not write the restarts now")
            return state.restart_noted(exit_code, restarted)
        self._calls = {
            "since": lambda since: state.restarts_since(since),
            "noted": noted,
        }

    def __getattr__(self, name):
        calls = object.__getattribute__(self, "_calls")
        if name in calls:
            return calls[name]
        raise AttributeError(name)
