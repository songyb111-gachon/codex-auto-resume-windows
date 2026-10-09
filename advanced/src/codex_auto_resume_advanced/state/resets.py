# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""What the reset actions keep (v0.6.14): the usage windows they count, the last reading, their rules and
their spends.

    windows        one row for each usage window a pending rule names - a bucket and a length in minutes,
                   never a slot - with the reset it is open until, whether it filled, when it last closed,
                   how many times it reset and filled (both only ever grow), when it was last seen and how
                   many readings in a row did not show it (engine/resetwatch.py)
    readings       one row: when this edition last read usage itself and asked to, the last reading counted,
                   the last usage-limit record of core's it noticed - and, only while reset_credit is on,
                   how many reset credits there are and when the soonest expires (B10)
    reset_rules    a person's rules: use a reset credit when the chosen limit is reached (reset_credit), or
                   send their own message to one conversation when the chosen window resets
                   (reset_message), each with the occasion it waits for, what it has counted and where it
                   stands - and, for a message still to be sent, its words. Words are held by a message
                   that is counting, due or held, and by nothing else: the file refuses them on a rule that
                   is done or cancelled, and on a credit's rule
    credit_spends  each credit this edition asked Codex to spend, under the key it was asked with, one for
                   each filling of a window at most, and what came of it

A message's own record is a row of `records` (state/records.py), which the one claim counts with core's
rows (ledger.py); its words are here, never there.
"""
from __future__ import annotations

from ..vocabulary import Refusal, RecordState, RuleReason, RuleState, SpendOutcome
from .choices import Refused
from .schema import BUCKETS, RESET_CAPABILITIES
from .session import StateError, _key, _thread, _timestamp, _word

CREDIT, MESSAGE = RESET_CAPABILITIES
# A rule still to act: counting, due, or held for a person.
PENDING = (RuleState.COUNTING, RuleState.READY, RuleState.HELD)
FINISHED = (RuleState.DONE, RuleState.CANCELLED)
# How many rules may wait at once: ten messages, one to a conversation, and four credit rules.
MESSAGES_LIMIT = 10
CREDIT_RULES_LIMIT = 4
# A message's words, at most: what core's one send carries less the blank line and the marker
# (continuation.PROMPT_LIMIT), which the file holds them under too.
WORDS_LIMIT = 8192
ORDINALS = range(0, 10)
# What a rule's row may be changed in, and nothing else of it.
CHANGES = frozenset({"state", "reason", "adopted_at", "base", "ordinal", "due_at", "launching_at", "sent_at",
                     "gate", "gate_reason", "finished_at"})
TIMES = frozenset({"adopted_at", "due_at", "launching_at", "sent_at", "finished_at"})
GATE_WORD_LIMIT = 48
READING = frozenset({"read_at", "asked_at", "applied_at", "signal_at", "credits", "expiry_known",
                     "nearest_expiry"})


def _family(bucket, minutes):
    if bucket not in BUCKETS or type(minutes) is not int or not 0 < minutes <= 10 * 10080:
        raise StateError("invalid window")
    return bucket, minutes


def _gate_word(value):
    """A gate's or a reason's name as core says it: lowercase letters, digits and underscores, or None."""
    if value is None:
        return None
    if (not isinstance(value, str) or not 0 < len(value) <= GATE_WORD_LIMIT
            or not all(character.isascii() and (character.isalnum() or character == "_") for character in value)):
        raise StateError("invalid gate word")
    return value


def _rule(row) -> dict:
    found = dict(row)
    found["repeat"], found["ask_first"] = bool(found["repeat"]), bool(found["ask_first"])
    return found


class ResetsMixin:
    # ------------------------------------------------------------------ windows
    def windows(self) -> dict:
        """{(bucket, minutes): the window's row} for every window counted. Empty with no file."""
        with self._read() as connection:
            if connection is None:
                return {}
            rows = connection.execute("SELECT * FROM windows").fetchall()
        return {(row["bucket"], row["minutes"]): dict(row) for row in rows}

    def save_windows(self, rows) -> None:
        """The windows counted, exactly these: each row of `rows` written, and every other row gone - a
        window no rule names any more is not counted (engine/resetwatch.py)."""
        with self._transaction(create=False) as connection:
            if connection is None:
                return
            kept = []
            for row in rows:
                family = _family(row["bucket"], row["minutes"])
                kept.append(family)
                connection.execute(
                    "INSERT OR REPLACE INTO windows (bucket, minutes, open_reset_at, open_full, last_closed_at, "
                    "resets, hits, seen_at, misses) VALUES (?,?,?,?,?,?,?,?,?)",
                    (*family, row["open_reset_at"], int(bool(row["open_full"])), row["last_closed_at"],
                     row["resets"], row["hits"], row["seen_at"], row["misses"]))
            for family in [(row["bucket"], row["minutes"]) for row in connection.execute("SELECT bucket, minutes "
                                                                                           "FROM windows")]:
                if family not in kept:
                    connection.execute("DELETE FROM windows WHERE bucket=? AND minutes=?", family)

    # ------------------------------------------------------------------ the last reading
    def reading(self) -> dict:
        """The one row of `readings`, or its empty form with no file."""
        with self._read() as connection:
            row = None if connection is None else connection.execute("SELECT * FROM readings").fetchone()
        if row is None:
            return {name: None for name in READING}
        found = dict(row)
        found.pop("singleton", None)
        return found

    def set_reading(self, **values) -> None:
        """Some fields of the last reading written (READING), and nothing else of it."""
        if not values or not set(values) <= READING:
            raise StateError("invalid reading")
        with self._transaction(create=False) as connection:
            if connection is None:
                return
            connection.execute("UPDATE readings SET %s WHERE singleton=1"
                               % ", ".join("%s=?" % name for name in sorted(values)),
                               tuple(values[name] for name in sorted(values)))

    # ------------------------------------------------------------------ rules
    def reset_rules(self, *, capability=None, pending=True) -> list:
        """The rules, oldest first: those still to act (`pending`), all of them (None) or the finished."""
        where, arguments = [], []
        if capability is not None:
            where.append("capability=?")
            arguments.append(capability)
        if pending is not None:
            states = PENDING if pending else FINISHED
            where.append("state IN (%s)" % ", ".join("?" for _ in states))
            arguments += [str(state) for state in states]
        with self._read() as connection:
            if connection is None:
                return []
            rows = connection.execute("SELECT r.*, c.thread_id AS thread_id, c.state AS record_state "
                                      "FROM reset_rules r LEFT JOIN records c ON c.record_id = r.record_id%s "
                                      "ORDER BY r.rule_id" % ((" WHERE " + " AND ".join("r." + w for w in where))
                                                              if where else ""), arguments).fetchall()
        return [_rule(row) for row in rows]

    def reset_rule(self, rule_id):
        if type(rule_id) is not int:
            return None
        with self._read() as connection:
            if connection is None:
                return None
            row = connection.execute("SELECT r.*, c.thread_id AS thread_id, c.state AS record_state FROM reset_rules r "
                                     "LEFT JOIN records c ON c.record_id = r.record_id WHERE r.rule_id=?",
                                     (rule_id,)).fetchone()
        return _rule(row) if row is not None else None

    def add_reset_rule(self, capability, bucket, minutes, ordinal, *, repeat=False, ask_first=False,
                       thread_id=None, words=None, record_id=None, at=None) -> int:
        """A new rule, counting from its adoption (engine/resetwatch.py): the rule's id. A message makes its
        record in the same transaction - waiting, of reset_message, in the conversation it is for - and
        is refused (Refused) where that conversation has one waiting already, or ten wait in all; four
        credit rules at most may wait."""
        if capability not in RESET_CAPABILITIES:
            raise StateError("unknown reset capability")
        bucket, minutes = _family(bucket, minutes)
        if type(ordinal) is not int or ordinal not in ORDINALS or (ordinal == 0 and capability != CREDIT):
            raise Refused(Refusal.OCCASION_INVALID)
        if type(repeat) is not bool or type(ask_first) is not bool:
            raise StateError("invalid rule")
        message = capability == MESSAGE
        if message:
            _thread(thread_id)
            _key(record_id, "record id")
            if type(words) is not str or not 0 < len(words) <= WORDS_LIMIT or repeat:
                raise Refused(Refusal.MESSAGE_REFUSED)
        elif thread_id is not None or words is not None or record_id is not None:
            raise StateError("a credit's rule holds no conversation and no words")
        now = self._now(at)
        with self._transaction() as connection:
            pending = connection.execute(
                "SELECT count(*) FROM reset_rules WHERE capability=? AND state IN (?,?,?)",
                (capability, *[str(state) for state in PENDING])).fetchone()[0]
            if pending >= (MESSAGES_LIMIT if message else CREDIT_RULES_LIMIT):
                raise Refused(Refusal.RESETS_FULL)
            if message:
                if connection.execute(
                        "SELECT 1 FROM reset_rules r JOIN records c ON c.record_id = r.record_id WHERE c.thread_id=? "
                        "AND r.state IN (?,?,?)", (thread_id, *[str(state) for state in PENDING])).fetchone():
                    raise Refused(Refusal.ALREADY_SCHEDULED)
                if connection.execute("SELECT 1 FROM records WHERE record_id=?", (record_id,)).fetchone():
                    raise StateError("record id taken")
                connection.execute("INSERT INTO records (record_id, capability, thread_id, state, created_at, claims) "
                                   "VALUES (?,?,?,?,?,0)", (record_id, MESSAGE, thread_id, RecordState.WAITING, now))
            cursor = connection.execute(
                "INSERT INTO reset_rules (capability, bucket, minutes, ordinal, repeat, ask_first, record_id, words, "
                "created_at, state) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (capability, bucket, minutes, ordinal, int(repeat), int(ask_first), record_id, words, now,
                 RuleState.COUNTING))
            return cursor.lastrowid

    def change_rule(self, rule_id, *, expect=None, **changes) -> bool:
        """Some fields of one rule written (CHANGES), only while it is still `expect` - a state, or a tuple
        of them - where given, and never one that has finished. Whether it was."""
        if type(rule_id) is not int or not changes or not set(changes) <= CHANGES:
            raise StateError("invalid rule change")
        values = dict(changes)
        if "state" in values:
            values["state"] = _word(values["state"], RuleState, "rule state")
        if values.get("reason") is not None:
            values["reason"] = _word(values["reason"], RuleReason, "rule reason")
        for name in ("gate", "gate_reason"):
            if name in values:
                values[name] = _gate_word(values[name])
        for name in TIMES & set(values):
            if values[name] is not None:
                values[name] = _timestamp(values[name], name)
        if "base" in values and values["base"] is not None and (type(values["base"]) is not int or values["base"] < 0):
            raise StateError("invalid base")
        if "ordinal" in values and (type(values["ordinal"]) is not int or values["ordinal"] not in ORDINALS):
            raise StateError("invalid ordinal")
        if values.get("state") in FINISHED:
            values["words"] = None
        expected = (expect,) if isinstance(expect, str) else tuple(expect or PENDING)
        with self._transaction(create=False) as connection:
            if connection is None:
                return False
            return connection.execute(
                "UPDATE reset_rules SET %s WHERE rule_id=? AND state IN (%s)"
                % (", ".join("%s=?" % name for name in sorted(values)), ", ".join("?" for _ in expected)),
                (*[values[name] for name in sorted(values)], rule_id, *[str(state) for state in expected])).rowcount == 1

    def end_rule(self, rule_id, state, reason, at=None) -> bool:
        """A rule finished - done or cancelled, with why - and its words gone; a message's record finished
        or cancelled with it, in the same transaction. Never one in flight but by the move that ends it
        (`in_flight` True). Whether it was."""
        state = _word(state, RuleState, "rule state")
        if state not in FINISHED:
            raise StateError("not an end")
        reason = _word(reason, RuleReason, "rule reason")
        now = self._now(at)
        with self._transaction(create=False) as connection:
            if connection is None:
                return False
            row = connection.execute("SELECT record_id FROM reset_rules WHERE rule_id=? AND state IN (?,?,?)",
                                     (rule_id, *[str(word) for word in PENDING])).fetchone()
            if row is None:
                return False
            connection.execute("UPDATE reset_rules SET state=?, reason=?, words=NULL, finished_at=? WHERE rule_id=?",
                               (state, reason, now, rule_id))
            if row["record_id"] is not None:
                connection.execute("UPDATE records SET state=?, finished_at=? WHERE record_id=? AND state<>?",
                                   (RecordState.FINISHED if state == RuleState.DONE else RecordState.CANCELLED, now,
                                    row["record_id"], RecordState.FINISHED))
            return True

    def cancel_reset_rule(self, rule_id, at=None) -> None:
        """A person's Cancel of one rule (by_person), its words gone - refused (Refused) for a rule that is
        not there or has finished, and for a message being sent: claimed, or its launch begun. A cancel and
        a claim serialise on this file's write lock, so one of them is first."""
        now = self._now(at)
        with self._transaction(create=False) as connection:
            row = None if connection is None else connection.execute(
                "SELECT r.state, r.record_id, r.launching_at, c.state AS record_state FROM reset_rules r "
                "LEFT JOIN records c ON c.record_id = r.record_id WHERE r.rule_id=?",
                (rule_id if type(rule_id) is int else -1,)).fetchone()
            if row is None or row["state"] not in [str(state) for state in PENDING]:
                raise Refused(Refusal.UNKNOWN_RULE)
            if row["launching_at"] is not None or row["record_state"] == RecordState.IN_FLIGHT:
                raise Refused(Refusal.BEING_SENT)
            connection.execute("UPDATE reset_rules SET state=?, reason=?, words=NULL, finished_at=? WHERE rule_id=?",
                               (RuleState.CANCELLED, RuleReason.BY_PERSON, now, rule_id))
            if row["record_id"] is not None:
                connection.execute("UPDATE records SET state=?, finished_at=? WHERE record_id=?",
                                   (RecordState.CANCELLED, now, row["record_id"]))

    # ------------------------------------------------------------------ spends
    def add_credit_spend(self, rule_id, bucket, minutes, occasion, key, at=None):
        """A spend written before Codex is asked (A5's analogue): its id - or None where this filling of the
        window has one already, which is never asked for twice."""
        bucket, minutes = _family(bucket, minutes)
        if type(rule_id) is not int or type(occasion) is not int or occasion < 0:
            raise StateError("invalid spend")
        if not isinstance(key, str) or len(key) != 36:
            raise StateError("invalid key")
        now = self._now(at)
        with self._transaction() as connection:
            if connection.execute("SELECT 1 FROM credit_spends WHERE bucket=? AND minutes=? AND occasion=?",
                                  (bucket, minutes, occasion)).fetchone():
                return None
            return connection.execute(
                "INSERT INTO credit_spends (rule_id, bucket, minutes, occasion, attempt_id, created_at, tries) "
                "VALUES (?,?,?,?,?,?,1)", (rule_id, bucket, minutes, occasion, key, now)).lastrowid

    def finish_credit_spend(self, spend_id, outcome, at=None) -> bool:
        outcome = _word(outcome, SpendOutcome, "spend outcome")
        now = self._now(at)
        with self._transaction(create=False) as connection:
            if connection is None:
                return False
            return connection.execute("UPDATE credit_spends SET outcome=?, finished_at=? WHERE spend_id=? AND "
                                      "outcome IS NULL", (outcome, now, spend_id)).rowcount == 1

    def retry_credit_spend(self, spend_id) -> bool:
        """The one retry of a spend whose outcome is not known, under the same key. Whether it may."""
        with self._transaction(create=False) as connection:
            if connection is None:
                return False
            return connection.execute("UPDATE credit_spends SET tries=2 WHERE spend_id=? AND tries=1 AND "
                                      "outcome IS NULL", (spend_id,)).rowcount == 1

    def drop_credit_spend(self, spend_id) -> bool:
        """A spend Codex was never asked for - its guard refused the write, or Codex refused the method -
        taken away: only one with no outcome, never tried again. Whether it was."""
        with self._transaction(create=False) as connection:
            if connection is None:
                return False
            return connection.execute("DELETE FROM credit_spends WHERE spend_id=? AND outcome IS NULL AND tries=1",
                                      (spend_id,)).rowcount == 1

    def credit_spends(self, since=None) -> list:
        """The spends, newest first: every one, or those made at `since` or after."""
        with self._read() as connection:
            if connection is None:
                return []
            rows = connection.execute("SELECT * FROM credit_spends WHERE created_at >= ? ORDER BY spend_id DESC",
                                      (float("-inf") if since is None else since,)).fetchall()
        return [dict(row) for row in rows]


def prune(connection, now, max_age, limit) -> None:
    """The reset actions' bounds, in the journal's one pass (state/journal.py): finished rules and spends
    older than `max_age`, then the oldest beyond `limit`. A rule still to act is never pruned, nor a spend
    of the last week, which the bounds count (engine/credits.py). Windows are the tracker's to drop."""
    finished = "state IN ('%s', '%s')" % (RuleState.DONE, RuleState.CANCELLED)
    connection.execute("DELETE FROM reset_rules WHERE %s AND coalesce(finished_at, created_at) < ?" % finished,
                       (now - max_age,))
    excess = connection.execute("SELECT count(*) FROM reset_rules").fetchone()[0] - limit
    if excess > 0:
        connection.execute("DELETE FROM reset_rules WHERE rule_id IN (SELECT rule_id FROM reset_rules WHERE %s "
                           "ORDER BY rule_id LIMIT ?)" % finished, (excess,))
    week = now - 7 * 86400
    connection.execute("DELETE FROM credit_spends WHERE created_at < ? AND created_at < ?", (now - max_age, week))
    excess = connection.execute("SELECT count(*) FROM credit_spends").fetchone()[0] - limit
    if excess > 0:
        connection.execute("DELETE FROM credit_spends WHERE spend_id IN (SELECT spend_id FROM credit_spends "
                           "WHERE created_at < ? ORDER BY spend_id LIMIT ?)", (week, excess))


class ResetsHandle:
    """What one reset action's code is given of the state (state.Scoped's `resets`): the windows and the
    last reading, which both reset actions count together, the rules and the spends - writes only while
    the runtime has the capability on, and its own rules alone where it changes or ends one. Held in a
    closure, as the Scoped view is: against a capability's mistakes, not its intent."""
    __slots__ = ("capability", "_calls")

    def __init__(self, state, capability, on):
        self.capability = capability

        def writing(call):
            def written(*arguments, **keywords):
                if on is None or on() is not True:
                    raise StateError("the capability is not on")
                return call(*arguments, **keywords)
            return written

        def own(call):
            def owned(rule_id, *arguments, **keywords):
                rule = state.reset_rule(rule_id)
                if rule is None or rule["capability"] != capability:
                    raise StateError("not this capability's rule")
                return call(rule_id, *arguments, **keywords)
            return writing(owned)
        self._calls = {
            "on": lambda: on is not None and on() is True,
            "now": lambda: state.clock(),
            "windows": state.windows, "reading": state.reading, "reset_rules": state.reset_rules,
            "reset_rule": state.reset_rule, "credit_spends": state.credit_spends,
            "save_windows": writing(state.save_windows), "set_reading": writing(state.set_reading),
            # The tracker adopts and holds every pending rule, of both reset actions (engine/resetwatch.py).
            "change_rule": writing(state.change_rule),
            "end_rule": own(state.end_rule),
            "add_credit_spend": writing(state.add_credit_spend),
            "finish_credit_spend": writing(state.finish_credit_spend),
            "retry_credit_spend": writing(state.retry_credit_spend),
            "drop_credit_spend": writing(state.drop_credit_spend),
        }

    def __getattr__(self, name):
        calls = object.__getattribute__(self, "_calls")
        if name in calls:
            return calls[name]
        raise AttributeError(name)
