# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""Where each capability stands, as stored: the arming rows, the generation and the ceiling.

A row that is not off also holds what the person confirmed when they moved it there: the
statement revision, for "on" the Codex version, and the statement's warnings (ArmingWarning),
which arming.standing reads so that a warning they confirmed never trips what they turned on.

This is only the writing. Who may move a capability, and when, is `arming.py`'s to decide; here
each move is one transaction that checks its words, bumps the generation and journals itself.

Keep on (v0.6.14, K8) is a row in `options` (KeepOn), set and let go for a capability that is on or
watched, a move like any other but for `since`, which it never touches; every move to off takes it
away. Send again (v0.6.14) is a second row beside it, only ever with it. A kept-on capability's notice - what would have turned it off - is its row's `reason`, which a
row that is not off held nowhere before: written only as it rises (KEPT_NOTICES), with no generation,
and taken away by the next arm, the person confirming again.

The generation is one number for the whole table, raised by every move of every capability. A
request to turn something on names the generation it was made against, and is refused if any
move came in between - so a person who turned a capability off, anywhere, cannot have that
undone by a Dashboard that had not yet seen it. A move to off names none: nothing ever stands
in the way of turning something off.
"""
from __future__ import annotations

from ..registry import GLOBAL_HOURLY
from ..vocabulary import (KEPT_NOTICES, Actor, ArmingState, ArmingWarning, JournalCode, KeepOn,
                          OffReason, Refusal)
from .choices import Refused
from .resets import end_pending
from .schema import RESET_CAPABILITIES
from .session import StaleGeneration, StateError, _word

# The journal line each move writes.
_CODES = {ArmingState.ARMED: JournalCode.ARMED, ArmingState.SHADOW: JournalCode.WATCHED}
# Keep on's rows in `options`, as SQL: what every move to off deletes.
_KEPT = "choice IN (%s)" % ", ".join("'%s'" % word for word in KeepOn)


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
            "warnings": _confirmed(row["warnings"]), "keep_on": False}


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
            kept = {}
            for capability, choice in connection.execute("SELECT capability, choice FROM options WHERE "
                                                         + _KEPT):
                kept.setdefault(capability, set()).add(choice)
        found = {}
        for row in rows:
            if self.registry.get(row["capability"]) is None:
                continue
            words = kept.get(row["capability"], set()) if row["state"] != ArmingState.OFF else set()
            keep_on = str(KeepOn.KEEP_ON) in words
            found[row["capability"]] = dict(_row(row), keep_on=keep_on,
                                            send_again=keep_on and str(KeepOn.SEND_AGAIN) in words)
        return found

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
                connection.execute("DELETE FROM options WHERE capability=? AND " + _KEPT, (capability,))
                if before is None or _row(before)["state"] == ArmingState.OFF:
                    return False, current
            elif before is not None and _row(before)["state"] == state and (
                    before["statement_revision"], before["engine_version"], before["warnings"],
                    before["reason"]) == (revision, engine_version, warnings, None):
                return False, current
            connection.execute(
                "INSERT OR REPLACE INTO arming (capability, state, since, actor, reason, "
                "statement_revision, engine_version, warnings) VALUES (?,?,?,?,?,?,?,?)",
                (capability, state, now, actor, reason, revision, engine_version, warnings))
            if state != ArmingState.ARMED:
                end_pending(connection, (capability,), now)      # a reset action's rules end with it
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
            connection.execute("DELETE FROM options WHERE " + _KEPT)
            if not on:
                return 0, current
            connection.execute(
                "UPDATE arming SET state='off', since=?, actor=?, reason=?, statement_revision=NULL, "
                "engine_version=NULL, warnings=NULL WHERE state <> 'off'", (now, actor, reason))
            end_pending(connection, RESET_CAPABILITIES, now)     # every reset action's rules end with them
            connection.execute("UPDATE meta SET generation = generation + 1")
            self._note(connection, now, JournalCode.RESET if actor == Actor.EDITION_ENTRY
                       else JournalCode.ALL_OFF, reason=reason, actor=actor)
            return on, current + 1

    def set_keep_on(self, capability, on, *, send_again=False, actor, generation=None, at=None) -> int:
        """Keep `capability` on - with Send again or without (v0.6.14) - or let it turn itself off again
        (K8): its KeepOn rows set to what is asked, against `generation` - which turning anything on needs,
        and which the write moves on - and only for one that is on or watched (NOT_ON). Send again is only
        ever with Keep on. `since` is never touched: a Send now request is dated by it. The generation
        after; StaleGeneration where anything moved since."""
        actor = _word(actor, Actor, "actor")
        if (self.registry.get(capability) is None or type(on) is not bool or type(send_again) is not bool
                or (send_again and not on)):
            raise StateError("invalid keep on")
        wanted = {str(KeepOn.KEEP_ON)} if on else set()
        if send_again:
            wanted.add(str(KeepOn.SEND_AGAIN))
        now = self._now(at)
        with self._transaction(create=False) as connection:
            if connection is None:
                if on:
                    raise Refused(Refusal.NOT_ON)
                return 0
            current = connection.execute("SELECT generation FROM meta").fetchone()[0]
            if generation is not None and generation != current:
                raise StaleGeneration("stale generation")
            held = {row[0] for row in connection.execute(
                "SELECT choice FROM options WHERE capability=? AND " + _KEPT, (capability,))}
            if held == wanted:
                return current
            adding = not wanted <= held
            if adding and type(generation) is not int:
                raise StateError("invalid generation")
            row = connection.execute("SELECT state FROM arming WHERE capability=?", (capability,)).fetchone()
            if on and (row is None or row["state"] == ArmingState.OFF):
                raise Refused(Refusal.NOT_ON)
            connection.execute("DELETE FROM options WHERE capability=? AND " + _KEPT, (capability,))
            for word in sorted(wanted):
                connection.execute("INSERT INTO options (capability, choice, value) VALUES (?,?,1)",
                                   (capability, word))
            connection.execute("UPDATE meta SET generation = generation + 1")
            code = (JournalCode.KEEP_ON_OFF if not on else JournalCode.KEEP_ON if adding
                    else JournalCode.SEND_AGAIN_OFF)
            self._note(connection, now, code, capability=capability, actor=actor)
            return current + 1

    def send_again_off(self, capability, *, reason, at=None) -> bool:
        """A kept-on capability's Send again taken away by a tripwire (v0.6.14): a continuation it sent
        once more was found twice. Keep on stays, the notice rises to `reason` where it is higher
        (KEPT_NOTICES), and the generation moves on, as for every turn off - a page that had not seen it
        cannot set Send again back without asking. Whether anything was taken away."""
        reason = _word(reason, OffReason, "reason")
        now = self._now(at)
        with self._transaction(create=False) as connection:
            if connection is None:
                return False
            if connection.execute("DELETE FROM options WHERE capability=? AND choice=?",
                                  (capability, str(KeepOn.SEND_AGAIN))).rowcount != 1:
                return False
            connection.execute("UPDATE meta SET generation = generation + 1")
            self._note(connection, now, JournalCode.SEND_AGAIN_OFF, capability=capability, reason=reason,
                       actor=Actor.TRIPWIRE)
            held = connection.execute("SELECT state, reason FROM arming WHERE capability=?",
                                      (capability,)).fetchone()
            if (held is not None and held["state"] != ArmingState.OFF and reason in KEPT_NOTICES
                    and not (held["reason"] in KEPT_NOTICES
                             and KEPT_NOTICES.index(held["reason"]) <= KEPT_NOTICES.index(reason))):
                connection.execute("UPDATE arming SET reason=? WHERE capability=?", (reason, capability))
                self._note(connection, now, JournalCode.KEPT, capability=capability, reason=reason,
                           actor=Actor.TRIPWIRE)
            return True

    def note_kept(self, capability, reason, *, at=None) -> bool:
        """What would have turned a kept-on capability off, noted on its row instead (K8): written only
        where its notice is none or less serious (KEPT_NOTICES), in one transaction, with no generation
        and `since` untouched, and journalled once for each rise. Whether it was written."""
        reason = _word(reason, OffReason, "reason")
        if reason not in KEPT_NOTICES:
            raise StateError("not a notice")
        now = self._now(at)
        with self._transaction(create=False) as connection:
            if connection is None:
                return False
            row = connection.execute("SELECT state, reason FROM arming WHERE capability=?",
                                     (capability,)).fetchone()
            if row is None or row["state"] == ArmingState.OFF:
                return False
            held = row["reason"]
            if held in KEPT_NOTICES and KEPT_NOTICES.index(held) <= KEPT_NOTICES.index(reason):
                return False
            connection.execute("UPDATE arming SET reason=? WHERE capability=? AND state <> 'off'",
                               (reason, capability))
            self._note(connection, now, JournalCode.KEPT, capability=capability, reason=reason,
                       actor=Actor.TRIPWIRE)
            return True

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
