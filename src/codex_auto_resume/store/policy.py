"""The switches the state holds: recovery on or off, and per conversation."""
from __future__ import annotations

import sqlite3
from typing import Any
from .. import machine
from ..machine import WAITING
from .errors import StoreError
from .validate import _flag, _integer, _timestamp, _uuid, _validated_record, _validated_tier


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
        # Schema 4's switch. An older watcher's state (store/legacy.py) has no such column, and
        # nothing there is only observed.
        observe_only = _flag(row.get("observe_only", 0), "observe_only")
        return {"enabled": enabled, "armed_at": armed_at, "poll_seconds": poll,
                "observe_only": observe_only}

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

    def set_observe_only(self, observe_only: bool) -> bool:
        """Observe only (schema 4), written from the setting of that name: while it is on, every
        claim is refused here whatever the engine asked. Returns whether it changed."""
        if not isinstance(observe_only, bool):
            raise StoreError("observe_only must be boolean")
        with self._transaction() as connection:
            before = self._read_settings(connection)["observe_only"]
            if before != observe_only:
                connection.execute("UPDATE settings SET observe_only=? WHERE singleton=1",
                                   (int(observe_only),))
            return before != observe_only

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
                "INSERT INTO threads (thread_id, enabled) VALUES (?,?) "
                "ON CONFLICT(thread_id) DO UPDATE SET enabled=excluded.enabled",
                (thread_id, int(enabled)),
            )
            if enabled and not before:
                self._event(connection, self._now(at), "thread_enabled", actor=actor)

    # ------------------------------------------------------------ tiers (schema 4)
    @staticmethod
    def _thread_tier(connection: sqlite3.Connection, thread_id: str):
        row = connection.execute("SELECT tier FROM threads WHERE thread_id=?", (thread_id,)).fetchone()
        return None if row is None else _validated_tier(row[0])

    def thread_tier(self, thread_id: str):
        """The tier this conversation has of its own, or None: it has the default's."""
        _uuid(thread_id, "thread_id")
        with self._read() as connection:
            return self._thread_tier(connection, thread_id)

    def thread_tiers(self) -> dict:
        """Every conversation that has a tier of its own, and that tier."""
        with self._read() as connection:
            return {row[0]: _validated_tier(row[1]) for row in
                    connection.execute("SELECT thread_id, tier FROM threads WHERE tier IS NOT NULL")}

    def set_thread_tier(self, thread_id: str, tier, now: float, *, actor: str = "gui") -> dict:
        """Give one conversation a tier of its own, or take it away (None: the default's again).

        A tier that asks a person first - Ask me first, Only notify me - also holds what this
        conversation has waiting and not yet sent, in the same transaction, so choosing it can
        only ever hold more back. Choosing a tier that asks less lets nothing go: a record already
        held stays held until a person lets it continue (`release_hold`). Returns the tier now
        stored and how many records it held."""
        _uuid(thread_id, "thread_id")
        _timestamp(now, "now")
        _validated_tier(tier)
        hold = machine.hold_for_tier(tier)
        held = 0
        with self._transaction() as connection:
            before = self._thread_tier(connection, thread_id)
            connection.execute(
                "INSERT INTO threads (thread_id, enabled, tier) VALUES (?,1,?) "
                "ON CONFLICT(thread_id) DO UPDATE SET tier=excluded.tier", (thread_id, tier))
            if tier != before:
                self._event(connection, now, "tier_set", actor=actor)
            if hold is not None:
                waiting = sorted(WAITING)
                for value in connection.execute(
                        "SELECT * FROM interruptions WHERE thread_id=? AND hold IS NULL "
                        "AND submitted_at IS NULL AND cancel_requested=0 AND state IN (%s)"
                        % ",".join("?" for _ in waiting), (thread_id, *waiting)).fetchall():
                    row = _validated_record(dict(value))
                    connection.execute("UPDATE interruptions SET hold=? WHERE interruption_id=?",
                                       (hold, row["interruption_id"]))
                    self._event(connection, now, "held", record=row, from_state=row["state"],
                                to_state=row["state"], actor=actor)
                    held += 1
        return {"tier": tier, "held": held}

    def enrol_conversation(self, thread_id: str, tier: str, now: float) -> bool:
        """Give a conversation this state has never seen - no switch or tier of its own, no record -
        `tier` as its own (settings' new_conversation_policy), in one transaction, so a person's own
        choice made a moment earlier is never written over. Returns whether it was new."""
        _uuid(thread_id, "thread_id")
        _timestamp(now, "now")
        if _validated_tier(tier) is None:
            raise StoreError("A new conversation needs a tier")
        with self._transaction() as connection:
            seen = connection.execute(
                "SELECT 1 FROM threads WHERE thread_id=? UNION ALL "
                "SELECT 1 FROM interruptions WHERE thread_id=? LIMIT 1", (thread_id, thread_id)).fetchone()
            if seen is not None:
                return False
            connection.execute("INSERT INTO threads (thread_id, enabled, tier) VALUES (?,1,?)",
                               (thread_id, tier))
            self._event(connection, now, "tier_set")
            return True

    def hold_changed(self, interruption_id: str, task_print: str, now: float, *,
                     actor: str = "engine") -> bool:
        """The task-changed guard's hold (v0.6.11, guards.py): hold one record for a person
        (`workspace_changed`) and make `task_print`, what the guard found, its digest - in one
        transaction, so a person's Let it continue lets it go and only a further change holds it
        again. Only while it still waits unsent and nothing holds it; False when it was not held."""
        _timestamp(now, "now")
        if not (isinstance(task_print, str) and len(task_print) == 64
                and all(character in "0123456789abcdef" for character in task_print)):
            raise StoreError("Invalid task_print")
        waiting = sorted(WAITING)
        with self._transaction() as connection:
            value = connection.execute(
                "SELECT * FROM interruptions WHERE interruption_id=? AND hold IS NULL "
                "AND submitted_at IS NULL AND cancel_requested=0 AND task_print IS NOT NULL "
                "AND state IN (%s)" % ",".join("?" for _ in waiting), (interruption_id, *waiting)).fetchone()
            if value is None:
                return False
            row = _validated_record(dict(value))
            connection.execute("UPDATE interruptions SET hold=?, task_print=? WHERE interruption_id=?",
                               ("workspace_changed", task_print, interruption_id))
            self._event(connection, now, "held", record=row, from_state=row["state"],
                        to_state=row["state"], actor=actor)
            return True

    def hold_waiting(self, interruption_ids, hold: str, now: float, *, actor: str = "gui") -> int:
        """Hold these records for a person (`hold`), each only while it still waits unsent and
        nothing holds it yet - so this can only ever hold more back. Returns how many it held."""
        _timestamp(now, "now")
        if hold not in machine.HOLDS:
            raise StoreError("Invalid hold")
        held = 0
        waiting = sorted(WAITING)
        with self._transaction() as connection:
            for key in sorted(set(interruption_ids)):
                value = connection.execute(
                    "SELECT * FROM interruptions WHERE interruption_id=? AND hold IS NULL "
                    "AND submitted_at IS NULL AND cancel_requested=0 AND state IN (%s)"
                    % ",".join("?" for _ in waiting), (key, *waiting)).fetchone()
                if value is None:
                    continue
                row = _validated_record(dict(value))
                connection.execute("UPDATE interruptions SET hold=? WHERE interruption_id=?",
                                   (hold, key))
                self._event(connection, now, "held", record=row, from_state=row["state"],
                            to_state=row["state"], actor=actor)
                held += 1
        return held
