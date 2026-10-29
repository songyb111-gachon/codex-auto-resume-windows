# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""What the advanced edition says happened, and the counts its sampler keeps - both bounded.

The journal is content-free and closed like core's (store/journal.py): a capability id, a code,
and the reason, actor, point and answer as words from closed lists. A word outside them is
written as "other", or not at all, and never fails the move it describes. And like core's, it is
never read to decide anything: the spend ledger is the only record a decision counts.

Everything here is bounded the way core's journal is - 5,000 entries or 90 days, whichever comes
first, pruned every 256 entries - and so are the spend ledger, the records, the overrides, the
admissions and the samples, which are pruned in the same pass - and from v0.6.19 the stage's tables (advanced state
version 8), each as the groundwork bounded it. A spend is never pruned inside the day its ceilings count,
and a record or an override that may still be acted on never at all. What a watched capability would have
done (`would_have` lines) is bounded tighter, inside those: at most WATCH_LIMIT lines a capability, its
newest, cut in the same pass before the journal's own bound, so one noisy watched capability never
pushes another's out (between passes one can hold up to WATCH_LIMIT + 255); the journal's own bound
then cuts every other line before any of them.
"""
from __future__ import annotations

import time

from codex_auto_resume.domain.plug import Alternative, Point

from ..vocabulary import Actor, ArmingWarning, JournalCode, OffReason, RecordState

EVENT_LIMIT = 5000
WATCH_LIMIT = 120                 # would_have lines kept a capability, its newest (250; 200; 180; 150 until v0.6.19: 34 fit; 140 until v0.6.20: 35; 130 at v0.6.20's 38; 120 from its 39th, the window anchor: 41 fit)
EVENT_MAX_AGE = 90 * 86400
_PRUNE_EVERY = 256
_DAY = 86400
# The v0.6.19 stage's bounds (advanced state version 8, plans/v0619-design/D-groundwork.md): the usage readings 90 days
# and 20,000 rows, the token days and the rollouts read 90 days (the owner may make it 400), the pushed notices 7 days and
# 500, the conversations opened 7 days and 1,000, the restarts 7 days, the Stop hook's answers 90 days.
SAMPLES_MAX_AGE, SAMPLES_LIMIT = 90 * _DAY, 20000
TOKENS_MAX_AGE = 90 * _DAY
OUTBOX_MAX_AGE, OUTBOX_LIMIT = 7 * _DAY, 500
OPENS_MAX_AGE, OPENS_LIMIT = 7 * _DAY, 1000
RESTARTS_MAX_AGE = 7 * _DAY
HOOK_CLAIMS_MAX_AGE = 90 * _DAY
# v0.6.20 (advanced state version 9): the steers, 30 days and 1,000 rows - never one still waiting.
STEERS_MAX_AGE, STEERS_LIMIT = 30 * _DAY, 1000


def prune_every(row_id) -> bool:
    return isinstance(row_id, int) and row_id % _PRUNE_EVERY == 0


def _closed(value, words):
    return value if value in tuple(words) else None


def _reason(value):
    """A reason as the journal keeps it: why a capability is off, or (v0.6.17) one of the statement's warning words -
    why a capability stood aside for another (runtime.CONFLICTS)."""
    return _closed(value, OffReason) or _closed(value, ArmingWarning)


def _answer(value):
    """What a capability answered, as a word: an alternative at a decision point, or the name of
    the point it gave a value at. Never the value itself - words a capability would have sent,
    or a channel, are not the journal's to keep."""
    return _closed(value, Alternative) or _closed(value, Point)


class JournalMixin:
    def _answer(self, value):
        """`_answer`'s word, or (v0.6.17) the id of a capability the registry holds - the other capability an
        `overruled` line names. Still never a value a capability gave."""
        if isinstance(value, str) and self.registry.get(value) is not None:
            return value
        return _answer(value)

    def _code(self, code, capability) -> str:
        """`code` if it is one of the journal's own or one of `capability`'s, else "other"."""
        if code in tuple(JournalCode):
            return code
        definition = self.registry.get(capability)
        if definition is not None and isinstance(code, str) and "." in code:
            prefix, _, word = code.partition(".")
            if prefix == definition.journal_prefix and word in definition.codes:
                return code
        return JournalCode.OTHER

    def _note(self, connection, at, code, *, capability=None, reason=None, actor=None,
              point=None, answer=None) -> None:
        """One journal line, inside the caller's transaction on this file's own connection."""
        capability = capability if self.registry.get(capability) is not None else None
        connection.execute(
            "INSERT INTO journal (at, capability, code, reason, actor, point, answer) "
            "VALUES (?,?,?,?,?,?,?)",
            (at, capability, self._code(code, capability), _reason(reason),
             _closed(actor, Actor), _closed(point, Point),
             self._answer(answer)))
        if prune_every(connection.execute("SELECT last_insert_rowid()").fetchone()[0]):
            self._prune(connection, at)

    def note(self, code, *, capability=None, reason=None, actor=None, point=None, answer=None,
             at=None) -> None:
        """One journal line in a transaction of its own. Written only where the file is already
        there: a line about something that was never turned on has nothing to describe."""
        now = self._now(at)
        with self._transaction(create=False) as connection:
            if connection is not None:
                self._note(connection, now, code, capability=capability, reason=reason,
                           actor=actor, point=point, answer=answer)

    def journal(self, *, capability=None, limit=500) -> list:
        """Journal lines, oldest first, coerced as they are read: a line that no longer fits the
        vocabulary reads as "other" and never fails the read."""
        limit = max(1, min(int(limit), EVENT_LIMIT))
        where, arguments = ("WHERE capability=?", (capability,)) if capability else ("", ())
        with self._read() as connection:
            if connection is None:
                return []
            rows = connection.execute(
                "SELECT * FROM (SELECT * FROM journal %s ORDER BY event_id DESC LIMIT ?) "
                "ORDER BY event_id" % where, (*arguments, limit)).fetchall()
        return [{"at": row["at"],
                 "capability": row["capability"] if self.registry.get(row["capability"]) else None,
                 "code": self._code(row["code"], row["capability"]),
                 "reason": _reason(row["reason"]), "actor": _closed(row["actor"], Actor),
                 "point": _closed(row["point"], Point),
                 "answer": self._answer(row["answer"])}
                for row in rows]

    # ------------------------------------------------------------------ sampler
    def sample(self, capability, code, at=None) -> bool:
        """Count one occurrence of one of `capability`'s own codes, today. False, and nothing
        counted, for a code that is not its own. The file must already be there."""
        definition = self.registry.get(capability)
        if definition is None or code not in definition.codes:
            return False
        now = self._now(at)
        with self._transaction(create=False) as connection:
            if connection is None:
                return False
            connection.execute(
                "INSERT INTO sampler (capability, code, day, count) VALUES (?,?,?,1) "
                "ON CONFLICT (capability, code, day) DO UPDATE SET count = count + 1",
                (capability, code, int(now // _DAY)))
        return True

    def counted(self, capability, code, at=None) -> bool:
        """One of `capability`'s own codes counted today, with its journal line, in one transaction.
        False, and nothing written, for a code that is not its own or where there is no file."""
        definition = self.registry.get(capability)
        if definition is None or code not in definition.codes:
            return False
        now = self._now(at)
        with self._transaction(create=False) as connection:
            if connection is None:
                return False
            connection.execute(
                "INSERT INTO sampler (capability, code, day, count) VALUES (?,?,?,1) "
                "ON CONFLICT (capability, code, day) DO UPDATE SET count = count + 1",
                (capability, code, int(now // _DAY)))
            self._note(connection, now, definition.code(code), capability=capability)
        return True

    def samples(self, capability) -> dict:
        """{code: count} over the days the sampler keeps."""
        with self._read() as connection:
            if connection is None:
                return {}
            rows = connection.execute("SELECT code, sum(count) FROM sampler WHERE capability=? "
                                      "GROUP BY code", (capability,)).fetchall()
        definition = self.registry.get(capability)
        return {row[0]: int(row[1]) for row in rows if definition and row[0] in definition.codes}

    # ------------------------------------------------------------------- bounds
    @staticmethod
    def _prune(connection, now) -> None:
        """Every bounded table, in one pass."""
        old = now - EVENT_MAX_AGE
        connection.execute("DELETE FROM journal WHERE at < ?", (old,))
        # What each watched capability would have done: its newest WATCH_LIMIT lines. The journal's
        # own bound then cuts every other line first, oldest first, so it never cuts a watched
        # capability's answers for other lines: all of them together (at most WATCH_LIMIT a
        # capability, test_advanced_state) fit inside it.
        watched = str(JournalCode.WOULD_HAVE)
        for (capability,) in connection.execute("SELECT DISTINCT capability FROM journal WHERE code=?",
                                                (watched,)).fetchall():
            connection.execute("DELETE FROM journal WHERE event_id IN (SELECT event_id FROM journal "
                               "WHERE code=? AND capability IS ? ORDER BY event_id DESC "
                               "LIMIT -1 OFFSET ?)", (watched, capability, WATCH_LIMIT))
        excess = connection.execute("SELECT count(*) FROM journal").fetchone()[0] - EVENT_LIMIT
        if excess > 0:
            connection.execute("DELETE FROM journal WHERE event_id IN (SELECT event_id FROM journal "
                               "ORDER BY code IS ?, event_id LIMIT ?)", (watched, excess))
        connection.execute("DELETE FROM sampler WHERE day < ?", (int(old // _DAY),))
        excess = connection.execute("SELECT count(*) FROM sampler").fetchone()[0] - EVENT_LIMIT
        if excess > 0:
            connection.execute("DELETE FROM sampler WHERE rowid IN (SELECT rowid FROM sampler "
                               "ORDER BY day LIMIT ?)", (excess,))
        # A record still waiting or in flight is never pruned, however old: the claim ledger
        # counts it. An override is pruned once it is old, used or not.
        settled = "state IN ('%s', '%s')" % (RecordState.FINISHED, RecordState.CANCELLED)
        connection.execute("DELETE FROM records WHERE %s AND coalesce(finished_at, created_at) < ?"
                           % settled, (old,))
        excess = connection.execute("SELECT count(*) FROM records").fetchone()[0] - EVENT_LIMIT
        if excess > 0:
            connection.execute("DELETE FROM records WHERE record_id IN (SELECT record_id FROM records "
                               "WHERE %s ORDER BY created_at LIMIT ?)" % settled, (excess,))
        connection.execute("DELETE FROM overrides WHERE created_at < ?", (old,))
        excess = connection.execute("SELECT count(*) FROM overrides").fetchone()[0] - EVENT_LIMIT
        if excess > 0:
            connection.execute("DELETE FROM overrides WHERE rowid IN (SELECT rowid FROM overrides "
                               "ORDER BY created_at LIMIT ?)", (excess,))
        # Which capability took up which interruption, and the samples of what nothing classified
        # (state/choices.py): the same bounds. An interruption taken up ends within a day on the clock
        # (core's ladder.ADMITTED_MAX_SECONDS), long before its row is old. Rules and choices are a
        # person's own, never pruned.
        connection.execute("DELETE FROM admissions WHERE created_at < ?", (old,))
        excess = connection.execute("SELECT count(*) FROM admissions").fetchone()[0] - EVENT_LIMIT
        if excess > 0:
            connection.execute("DELETE FROM admissions WHERE interruption_id IN (SELECT interruption_id "
                               "FROM admissions ORDER BY created_at LIMIT ?)", (excess,))
        connection.execute("DELETE FROM samples WHERE at < ?", (old,))
        excess = connection.execute("SELECT count(*) FROM samples").fetchone()[0] - EVENT_LIMIT
        if excess > 0:
            connection.execute("DELETE FROM samples WHERE sample_id IN (SELECT sample_id FROM samples "
                               "ORDER BY sample_id LIMIT ?)", (excess,))
        JournalMixin._prune_spend(connection, "main", now)
        # The reset actions' rules and spends (v0.6.14): the same bounds, and never one still to act.
        from .resets import prune
        prune(connection, now, EVENT_MAX_AGE, EVENT_LIMIT)
        # And the continuations, the conversations kept going and the prompts (v0.6.15-beta): the same.
        from . import continuations, prompts
        continuations.prune(connection, now, EVENT_MAX_AGE, EVENT_LIMIT)
        prompts.prune(connection, now, EVENT_MAX_AGE, EVENT_LIMIT)
        # And the v0.6.19 stage's (advanced state version 8): each bound the groundwork fixed, one call a table. The
        # feed, a remote channel's pairing and the account seen are one row each, and need none.
        bound = JournalMixin._bound
        bound(connection, "usage_samples", "at", now - SAMPLES_MAX_AGE, SAMPLES_LIMIT)
        connection.execute("DELETE FROM token_days WHERE day < ?",
                           (time.strftime("%Y-%m-%d", time.gmtime(now - TOKENS_MAX_AGE)),))
        bound(connection, "token_files", "read_at", now - TOKENS_MAX_AGE)
        bound(connection, "outbox", "at", now - OUTBOX_MAX_AGE, OUTBOX_LIMIT, first="state = 'waiting', ")
        bound(connection, "opens", "at", now - OPENS_MAX_AGE, OPENS_LIMIT)
        bound(connection, "restarts", "at", now - RESTARTS_MAX_AGE)
        bound(connection, "hook_claims", "at", now - HOOK_CLAIMS_MAX_AGE)
        # And v0.6.20's steers (version 9).
        from . import steers
        steers.prune(connection, now, STEERS_MAX_AGE, STEERS_LIMIT)

    @staticmethod
    def _bound(connection, table, column, before, limit=None, first="") -> None:
        """`table`'s rows older than `before` by `column`, then - where it has a `limit` - its oldest beyond it (those
        `first` puts last, kept longest)."""
        connection.execute("DELETE FROM %s WHERE %s < ?" % (table, column), (before,))
        excess = connection.execute("SELECT count(*) FROM %s" % table).fetchone()[0] - (limit or 0)
        if limit and excess > 0:
            connection.execute("DELETE FROM %s WHERE rowid IN (SELECT rowid FROM %s ORDER BY %s%s LIMIT ?)"
                               % (table, table, first, column), (excess,))

    @staticmethod
    def _prune_spend(connection, schema, now) -> None:
        """Spends older than 90 days, then the oldest beyond 5,000 - but never one from the last
        day, which every ceiling counts. (At most GLOBAL_HOURLY an hour can be spent, so a day
        never holds more than 288 of them.)"""
        connection.execute("DELETE FROM %s.spend WHERE at < ?" % schema, (now - EVENT_MAX_AGE,))
        excess = connection.execute("SELECT count(*) FROM %s.spend" % schema).fetchone()[0] - EVENT_LIMIT
        if excess > 0:
            connection.execute("DELETE FROM %s.spend WHERE spend_id IN (SELECT spend_id FROM %s.spend "
                               "WHERE at < ? ORDER BY spend_id LIMIT ?)" % (schema, schema),
                               (now - _DAY, excess))
