# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""Where each capability stands, as stored: the arming rows, the generation and the ceiling.

A row that is not off also holds what the person confirmed when they moved it there: the
statement revision, for "on" the Codex version, and the statement's warnings (ArmingWarning),
which arming.standing reads so that a warning they confirmed never trips what they turned on.

This is only the writing. Who may move a capability, and when, is `arming.py`'s to decide; here
each move is one transaction that checks its words, bumps the generation and journals itself.

The generation is one number for the whole table, raised by every move of every capability. A
request to turn something on names the generation it was made against, and is refused if any
move came in between - so a person who turned a capability off, anywhere, cannot have that
undone by a Dashboard that had not yet seen it. A move to off names none: nothing ever stands
in the way of turning something off.
"""
from __future__ import annotations

from ..registry import GLOBAL_HOURLY
from ..vocabulary import Actor, ArmingState, ArmingWarning, JournalCode, OffReason
from .session import StaleGeneration, StateError, _word

# The journal line each move writes.
_CODES = {ArmingState.ARMED: JournalCode.ARMED, ArmingState.SHADOW: JournalCode.WATCHED}


def _joined(warnings) -> str | None:
    """The warnings a person confirmed, as the column holds them: the vocabulary's words in its
    own order, joined by commas, and NULL for none. StateError for a word it does not hold."""
    if warnings is None:
        return None
    if isinstance(warnings, str) or not isinstance(warnings, (tuple, list, set, frozenset)):
        raise StateError("invalid warnings")
    chosen = {_word(word, ArmingWarning, "warning") for word in warnings}
    return ",".join(str(word) for word in ArmingWarning if word in chosen) or None


def _confirmed(value) -> tuple:
    """The column read back: the words the vocabulary holds, in its order. A word it does not
    hold was never confirmed, so it is left out - a row can only ever confirm less."""
    words = set(value.split(",")) if isinstance(value, str) else set()
    return tuple(word for word in ArmingWarning if str(word) in words)


def _row(row) -> dict:
    """An arming row as the rest of the edition reads it. A state the vocabulary does not hold
    is off: the CHECK keeps such a row out, and if one got in it turns nothing on."""
    state = row["state"] if row["state"] in tuple(ArmingState) else ArmingState.OFF
    revision = row["statement_revision"]
    version = row["engine_version"]
    return {"state": ArmingState(state), "since": row["since"],
            "actor": row["actor"] if row["actor"] in tuple(Actor) else None,
            "reason": row["reason"] if row["reason"] in tuple(OffReason) else None,
            "statement_revision": revision if type(revision) is int else None,
            "engine_version": version if isinstance(version, str) and len(version) <= 64 else None,
            "warnings": _confirmed(row["warnings"])}


class ArmingMixin:
    def meta(self) -> dict:
        """The generation and the global ceiling. With no file, what a new one would start with."""
        with self._read() as connection:
            if connection is None:
                return {"generation": 0, "global_hourly": GLOBAL_HOURLY}
            row = connection.execute("SELECT generation, global_hourly FROM meta").fetchone()
        return {"generation": row["generation"], "global_hourly": row["global_hourly"]}

    def arming(self) -> dict:
        """Every capability of the registry that has a row, by id. A row for an id the registry
        does not hold - a capability of another version - is left out: it is never evaluated."""
        with self._read() as connection:
            if connection is None:
                return {}
            rows = connection.execute("SELECT * FROM arming").fetchall()
        return {row["capability"]: _row(row) for row in rows
                if self.registry.get(row["capability"]) is not None}

    def move(self, capability, state, *, actor, reason=None, revision=None, engine_version=None,
             warnings=None, generation=None, at=None) -> tuple:
        """Put one capability in `state`. (moved, generation after).

        `warnings` are the statement's warnings the person confirmed with the move. `generation`,
        when given, must be the current one, or StaleGeneration is raised and nothing is written.
        A move to off never needs one, and does not make the file: with no file there is nothing
        on to turn off. A move to where it already stands, as it stands, writes nothing."""
        state = _word(state, ArmingState, "state")
        actor = _word(actor, Actor, "actor")
        reason = None if reason is None else _word(reason, OffReason, "reason")
        warnings = _joined(warnings)
        if self.registry.get(capability) is None:
            raise StateError("unknown capability")
        now = self._now(at)
        with self._transaction(create=state != ArmingState.OFF) as connection:
            if connection is None:
                return False, 0
            current = connection.execute("SELECT generation FROM meta").fetchone()[0]
            if generation is not None and generation != current:
                raise StaleGeneration("stale generation")
            before = connection.execute("SELECT * FROM arming WHERE capability=?", (capability,)).fetchone()
            if state == ArmingState.OFF:
                revision = engine_version = warnings = None
                if before is None or _row(before)["state"] == ArmingState.OFF:
                    return False, current
            elif before is not None and _row(before)["state"] == state and (
                    before["statement_revision"], before["engine_version"], before["warnings"]) == (
                    revision, engine_version, warnings):
                return False, current
            connection.execute(
                "INSERT OR REPLACE INTO arming (capability, state, since, actor, reason, "
                "statement_revision, engine_version, warnings) VALUES (?,?,?,?,?,?,?,?)",
                (capability, state, now, actor, reason, revision, engine_version, warnings))
            connection.execute("UPDATE meta SET generation = generation + 1")
            code = _CODES.get(state) or (JournalCode.TRIPPED if actor == Actor.TRIPWIRE
                                         else JournalCode.RESET if actor in (Actor.EDITION_ENTRY, Actor.ENGINE_CHANGE)
                                         else JournalCode.DISARMED)
            self._note(connection, now, code, capability=capability, reason=reason, actor=actor)
            return True, current + 1

    def all_off(self, *, actor, reason, at=None) -> tuple:
        """Every capability off at once, in one transaction. (how many were on, generation).

        Every row, not only the registry's: a row this version cannot evaluate is still turned
        off, so no later version finds it on."""
        actor = _word(actor, Actor, "actor")
        reason = _word(reason, OffReason, "reason")
        now = self._now(at)
        with self._transaction(create=False) as connection:
            if connection is None:
                return 0, 0
            on = connection.execute("SELECT count(*) FROM arming WHERE state <> 'off'").fetchone()[0]
            current = connection.execute("SELECT generation FROM meta").fetchone()[0]
            if not on:
                return 0, current
            connection.execute(
                "UPDATE arming SET state='off', since=?, actor=?, reason=?, statement_revision=NULL, "
                "engine_version=NULL, warnings=NULL WHERE state <> 'off'", (now, actor, reason))
            connection.execute("UPDATE meta SET generation = generation + 1")
            self._note(connection, now, JournalCode.RESET if actor == Actor.EDITION_ENTRY
                       else JournalCode.ALL_OFF, reason=reason, actor=actor)
            return on, current + 1

    def set_global_hourly(self, value, *, generation, actor, at=None) -> int:
        """Lower (or restore, up to GLOBAL_HOURLY) the one ceiling over every capability together.
        Returns the generation after. It is a move like any other: it needs the current one."""
        if type(value) is not int or not 1 <= value <= GLOBAL_HOURLY:
            raise StateError("invalid ceiling")
        actor = _word(actor, Actor, "actor")
        now = self._now(at)
        with self._transaction() as connection:
            current = connection.execute("SELECT generation FROM meta").fetchone()[0]
            if generation != current:
                raise StaleGeneration("stale generation")
            connection.execute("UPDATE meta SET global_hourly=?, generation = generation + 1", (value,))
            self._note(connection, now, JournalCode.CEILING_CHANGED, actor=actor)
            return current + 1
