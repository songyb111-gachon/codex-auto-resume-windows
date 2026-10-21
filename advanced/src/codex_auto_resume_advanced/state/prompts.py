# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""A person's queued prompts (version 4, v0.6.15-beta): their own words for one conversation, to go after the turn
now running, at a time, or on a schedule - in order, each once.

    prompts   one row a prompt: its conversation, its words while one is still to go, when it goes (after_turn,
              at_time at `at`, recurring every day or week from `at`, at most 30 occurrences and never past
              `until`, 30 days from when it was written at most), whether it waits for the one before it to be
              delivered (`depends`), its place in its conversation's queue, where it stands, and the record of its
              current occurrence - a row of `records` (state/records.py) with an id of its own, which the one
              claim counts with core's rows (ledger.py) - and (v0.6.19, #50) what it does while a turn of its
              conversation runs (`while_running`): goes into Codex's queue, as every prompt did before, or waits

The file refuses words on a prompt that is done or cancelled, a series past 30 occurrences or 30 days, and a
recurring prompt without its every; this module refuses the rest: twenty waiting in all, five to a conversation.
"""
from __future__ import annotations

from ..vocabulary import PromptEvery, PromptReason, PromptState, PromptTrigger, RecordState, Refusal, WhileRunning

PROMPT_QUEUE = "prompt_queue"
from .choices import Refused
from .schema import PROMPT_SPAN
from .session import StateError, _key, _thread, _timestamp, _word

# A prompt still to go: waiting for its time, due and being tried, or held for a person.
PENDING = (PromptState.WAITING, PromptState.READY, PromptState.HELD)
PROMPTS_LIMIT = 20
PER_CONVERSATION = 5
OCCURRENCES = range(1, 31)
# A prompt's words at most, as a reset message's: what core's one send carries less the marker.
WORDS_LIMIT = 8192
# What a prompt's row may be changed in by the engine (engine/promptqueue.py), and nothing else of it.
CHANGES = frozenset({"state", "reason", "record_id", "gate", "gate_reason", "due_at", "launching_at", "sent_at",
                     "finished_at", "sent_count"})
# v0.6.19 (#50, Delete completed): a finished prompt that is completed work - delivered, or handed over to the person,
# who joined the turn it started - and so one a person may take off the list. Never one cancelled, held, still to go,
# uncertain (unknown), expired, missed or superseded: those stay until `prune`.
COMPLETED = (PromptReason.DELIVERED, PromptReason.HANDED_OVER)
# How many prompts one Delete completed names at most: as many rows as the journal's pass lets the table keep.
CLEAR_MOST = 5000


def _prompt(row) -> dict:
    found = dict(row)
    found["depends"] = bool(found["depends"])
    if "withdraw" in found:
        found["withdraw"] = bool(found["withdraw"])
    return found


class PromptsMixin:
    def add_prompt(self, thread_id, words, trigger, *, at=None, every=None, occurrences=1, until=None,
                   depends=False, while_running=WhileRunning.QUEUE, now=None) -> int:
        """A person's prompt, waiting, last in its conversation's queue; its id. Refused (Refused) for words that
        are empty or too long (prompt_refused), a time or schedule that is not one on offer (occasion_invalid),
        twenty waiting in all or five in that conversation (queue_full), and a prompt that waits for the one
        before it where there is none (dependency_unknown). `while_running` (v0.6.19, #50): what it does while a turn
        of its conversation runs - after_turn goes into Codex's queue by its nature, so it waits for nothing."""
        _thread(thread_id)
        current = self._now(now)
        if not isinstance(words, str) or not words.strip() or len(words) > WORDS_LIMIT:
            raise Refused(Refusal.PROMPT_REFUSED)
        try:
            trigger = _word(trigger, PromptTrigger, "trigger")
            every = None if every is None else _word(every, PromptEvery, "every")
            while_running = _word(while_running, WhileRunning, "while_running")
        except StateError:
            raise Refused(Refusal.OCCASION_INVALID) from None
        if trigger == PromptTrigger.AFTER_TURN and while_running != WhileRunning.QUEUE:
            raise Refused(Refusal.OCCASION_INVALID)
        if trigger == PromptTrigger.AFTER_TURN:
            shaped = at is None and every is None and occurrences == 1 and until is None
            due = current
        else:
            shaped = (at is not None and (every is not None) == (trigger == PromptTrigger.RECURRING)
                      and type(occurrences) is int and occurrences in OCCURRENCES
                      and (occurrences == 1 or trigger == PromptTrigger.RECURRING))
            due = at
        if trigger == PromptTrigger.RECURRING and until is None:
            until = current + PROMPT_SPAN
        try:
            due = _timestamp(due, "time")
            until = None if until is None else _timestamp(until, "until")
        except StateError:
            raise Refused(Refusal.OCCASION_INVALID) from None
        if (not shaped or (trigger != PromptTrigger.AFTER_TURN and due < current - 60)
                or (until is not None and not current < until <= current + PROMPT_SPAN)):
            raise Refused(Refusal.OCCASION_INVALID)
        with self._transaction() as connection:
            waiting = connection.execute("SELECT thread_id FROM prompts WHERE state IN (?,?,?)", PENDING).fetchall()
            if len(waiting) >= PROMPTS_LIMIT or sum(row[0] == thread_id for row in waiting) >= PER_CONVERSATION:
                raise Refused(Refusal.QUEUE_FULL)
            last = connection.execute("SELECT max(position) FROM prompts WHERE thread_id=?", (thread_id,)).fetchone()[0]
            if depends and last is None:
                raise Refused(Refusal.DEPENDENCY_UNKNOWN)
            cursor = connection.execute(
                "INSERT INTO prompts (thread_id, words, trigger, at, every, occurrences, sent_count, until, depends, "
                "position, state, created_at, due_at, while_running) VALUES (?,?,?,?,?,?,0,?,?,?,?,?,?,?)",
                (thread_id, words, trigger, None if trigger == PromptTrigger.AFTER_TURN else due, every, occurrences,
                 until, int(bool(depends)), 0 if last is None else last + 1, PromptState.WAITING, current, due,
                 while_running))
            return cursor.lastrowid

    def prompts(self, *, thread_id=None, pending=True) -> list:
        """The prompts in queue order - by conversation, then place - each with its current occurrence's record
        state, queue item and whether a Cancel asked for it back: those still to go (`pending`), all (None), or
        the finished."""
        clauses, values = [], []
        if thread_id is not None:
            clauses.append("p.thread_id=?")
            values.append(_thread(thread_id))
        if pending is not None:
            clauses.append("p.state %s (?,?,?)" % ("IN" if pending else "NOT IN"))
            values.extend(PENDING)
        with self._read() as connection:
            if connection is None:
                return []
            rows = connection.execute(
                "SELECT p.*, c.state AS record_state, c.queue_id AS queue_id, c.withdraw AS withdraw FROM prompts p "
                "LEFT JOIN records c ON c.record_id = p.record_id%s ORDER BY p.thread_id, p.position"
                % (" WHERE " + " AND ".join(clauses) if clauses else ""), values).fetchall()
        return [_prompt(row) for row in rows]

    def prompt(self, prompt_id) -> dict | None:
        if type(prompt_id) is not int:
            raise StateError("invalid prompt id")
        with self._read() as connection:
            row = None if connection is None else connection.execute(
                "SELECT p.*, c.state AS record_state, c.queue_id AS queue_id, c.withdraw AS withdraw FROM prompts p "
                "LEFT JOIN records c ON c.record_id = p.record_id WHERE p.prompt_id=?", (prompt_id,)).fetchone()
        return None if row is None else _prompt(row)

    def change_prompt(self, prompt_id, **changes) -> None:
        """Some of a prompt's fields written (CHANGES), and nothing else of it - its words never."""
        if type(prompt_id) is not int or not changes or not set(changes) <= CHANGES:
            raise StateError("invalid prompt change")
        if "state" in changes:
            changes["state"] = _word(changes["state"], PromptState, "state")
        if changes.get("reason") is not None:
            changes["reason"] = _word(changes["reason"], PromptReason, "reason")
        if changes.get("record_id") is not None:
            _key(changes["record_id"], "record id")
        names = sorted(changes)
        # A prompt that ends lets its words go in the same statement: the file refuses them on a finished one.
        ending = ", words=NULL" if changes.get("state") in (PromptState.DONE, PromptState.CANCELLED) else ""
        with self._transaction(create=False) as connection:
            if connection is None:
                return
            connection.execute("UPDATE prompts SET %s%s WHERE prompt_id=?"
                               % (", ".join("%s=?" % name for name in names), ending),
                               tuple(changes[name] for name in names) + (prompt_id,))

    def cancel_prompt(self, prompt_id, at=None) -> str:
        """A person's Cancel of one prompt, its words gone - "cancelled"; or, for an occurrence Codex already holds
        in its queue, "withdrawing": core takes it back (the owner's answer of 2026-10-09), and the move it tells
        ends it. Refused (being_sent) while its occurrence is being sent, and for a prompt not still to go."""
        if type(prompt_id) is not int:
            raise StateError("invalid prompt id")
        now = self._now(at)
        with self._transaction(create=False) as connection:
            row = None if connection is None else connection.execute(
                "SELECT p.state, p.record_id, p.launching_at, p.sent_at, c.state AS record_state FROM prompts p "
                "LEFT JOIN records c ON c.record_id = p.record_id WHERE p.prompt_id=?", (prompt_id,)).fetchone()
            if row is None or row["state"] not in [str(state) for state in PENDING]:
                raise Refused(Refusal.INVALID_REQUEST)
            if row["record_state"] == RecordState.IN_FLIGHT and row["sent_at"] is not None:
                connection.execute("UPDATE records SET withdraw=1 WHERE record_id=? AND state=?",
                                   (row["record_id"], RecordState.IN_FLIGHT))
                return "withdrawing"
            if row["launching_at"] is not None or row["record_state"] == RecordState.IN_FLIGHT:
                raise Refused(Refusal.BEING_SENT)
            connection.execute("UPDATE prompts SET state=?, reason=?, words=NULL, finished_at=? WHERE prompt_id=?",
                               (PromptState.CANCELLED, PromptReason.BY_PERSON, now, prompt_id))
            if row["record_id"] is not None:
                connection.execute("UPDATE records SET state=?, finished_at=? WHERE record_id=? AND state=?",
                                   (RecordState.CANCELLED, now, row["record_id"], RecordState.WAITING))
            return "cancelled"

    def go_on_prompt(self, prompt_id) -> bool:
        """A person's Go on for a prompt held because the one before it did not arrive: it waits again. False if it
        is not held."""
        if type(prompt_id) is not int:
            raise StateError("invalid prompt id")
        with self._transaction(create=False) as connection:
            if connection is None:
                return False
            # The person's word: it no longer waits for the one before it (`depends`), which did not arrive.
            return connection.execute("UPDATE prompts SET state=?, reason=NULL, depends=0 WHERE prompt_id=? AND state=?",
                                      (PromptState.WAITING, prompt_id, PromptState.HELD)).rowcount == 1

    def clear_done(self, prompt_ids, generation) -> dict:
        """A person's Delete completed (v0.6.19, #50): of the prompts `prompt_ids` the Dashboard showed as completed,
        each still finished as completed work (COMPLETED) deleted - its row alone, never its occurrence's row of
        `records`, which the ledger's caps count - and every other one left as it is and counted: one that moved on,
        is gone, or was never completed. {"deleted": n, "skipped": n}. Refused (Refused) for ids that are not a list of
        distinct prompt ids (invalid_request), and as a whole, deleting nothing, where anything moved since the list was
        read at `generation` (stale_generation) - checked in the deleting transaction."""
        if (not isinstance(prompt_ids, (list, tuple)) or not 0 < len(prompt_ids) <= CLEAR_MOST
                or any(type(prompt) is not int for prompt in prompt_ids) or len(set(prompt_ids)) != len(prompt_ids)):
            raise Refused(Refusal.INVALID_REQUEST)
        if type(generation) is not int:
            raise Refused(Refusal.STALE_GENERATION)
        deleted = 0
        with self._transaction(create=False) as connection:
            if connection is None:
                raise Refused(Refusal.STALE_GENERATION)
            if connection.execute("SELECT generation FROM meta").fetchone()[0] != generation:
                raise Refused(Refusal.STALE_GENERATION)
            for prompt in prompt_ids:
                deleted += connection.execute(
                    "DELETE FROM prompts WHERE prompt_id=? AND state=? AND reason IN (%s) AND words IS NULL"
                    % ",".join("?" for _ in COMPLETED), (prompt, PromptState.DONE, *COMPLETED)).rowcount
        return {"deleted": deleted, "skipped": len(prompt_ids) - deleted}

    def end_prompts(self, reason, *, thread_id=None, at=None) -> int:
        """Every prompt still to go whose occurrence is not in flight - of `thread_id`, or all - ended with `reason`
        (turned off, the conversation switched off), its words gone. One in flight is left to core's watch,
        which settles it, and to the move that ends it. How many."""
        reason = _word(reason, PromptReason, "reason")
        now = self._now(at)
        clauses, values = ["p.state IN (?,?,?)", "(c.state IS NULL OR c.state=?)"], [*PENDING, RecordState.WAITING]
        if thread_id is not None:
            clauses.append("p.thread_id=?")
            values.append(_thread(thread_id))
        with self._transaction(create=False) as connection:
            if connection is None:
                return 0
            rows = connection.execute("SELECT p.prompt_id, p.record_id FROM prompts p LEFT JOIN records c ON "
                                      "c.record_id = p.record_id WHERE " + " AND ".join(clauses), values).fetchall()
            for prompt_id, record_id in rows:
                connection.execute("UPDATE prompts SET state=?, reason=?, words=NULL, finished_at=? WHERE "
                                   "prompt_id=?", (PromptState.CANCELLED, reason, now, prompt_id))
                if record_id is not None:
                    connection.execute("UPDATE records SET state=?, finished_at=? WHERE record_id=?",
                                       (RecordState.CANCELLED, now, record_id))
            return len(rows)


def prune(connection, now, max_age, limit) -> None:
    """Prompts finished `max_age` ago, then the oldest finished beyond `limit` - never one still to go."""
    finished = "state IN ('%s', '%s')" % (PromptState.DONE, PromptState.CANCELLED)
    connection.execute("DELETE FROM prompts WHERE %s AND coalesce(finished_at, created_at) < ?" % finished,
                       (now - max_age,))
    excess = connection.execute("SELECT count(*) FROM prompts").fetchone()[0] - limit
    if excess > 0:
        connection.execute("DELETE FROM prompts WHERE prompt_id IN (SELECT prompt_id FROM prompts WHERE %s "
                           "ORDER BY coalesce(finished_at, created_at) LIMIT ?)" % finished, (excess,))


# How a move of an occurrence's record ends that occurrence: its reason, and the record's state then.
_ENDS = {"delivered": (PromptReason.DELIVERED, RecordState.FINISHED),
         "unproven": (PromptReason.UNKNOWN, RecordState.FINISHED),
         "superseded": (PromptReason.SUPERSEDED, RecordState.FINISHED),
         "handed_over": (PromptReason.HANDED_OVER, RecordState.FINISHED)}
DAY = 86400
PERIODS = {PromptEvery.DAY: DAY, PromptEvery.WEEK: 7 * DAY}


def next_slot(row):
    """When a recurring prompt's next occurrence falls after the one at `due_at`, or None where its series ends there:
    its occurrences used, or past `until`."""
    if row["trigger"] != PromptTrigger.RECURRING or row["sent_count"] >= row["occurrences"]:
        return None
    following = row["due_at"] + PERIODS[PromptEvery(row["every"])]
    return following if row["until"] is None or following <= row["until"] else None


class PromptMovesMixin:
    def prompt_moved(self, record_id, move, *, at=None, queue_id=None) -> dict | None:
        """What core told of a prompt's occurrence (P14), in one transaction across the prompt and its record: sent,
        the queue item is kept, and so are its words while Codex holds it (they go when it ends); handed back or
        never started, it waits again; delivered, unproven, superseded or handed over, the occurrence is used - a
        series waits for its next, anything else is done; withdrawn on a person's Cancel, it is cancelled, and on a
        Pause held for them to say go on or cancel (no guess, E1); refused by Codex, said, and left. The capability and
        whether it turns it off (UNPROVEN), or None where it is no prompt's."""
        _key(record_id, "record id")
        now = self._now(at)
        move = str(move)
        with self._transaction(create=False) as connection:
            if connection is None:
                return None
            row = connection.execute("SELECT p.*, c.state AS record_state, c.withdraw AS withdraw FROM prompts p "
                                     "JOIN records c ON c.record_id = p.record_id WHERE p.record_id=?",
                                     (record_id,)).fetchone()
            if row is None or row["state"] not in [str(state) for state in PENDING]:
                return None
            prompt = row["prompt_id"]
            if move == "sent":
                # Its words stay while Codex holds it: a Pause takes it back and holds it for the person to go on
                # (decision 6), and Go on sends these words again. They go when the occurrence ends.
                connection.execute("UPDATE prompts SET sent_at=coalesce(launching_at, ?), launching_at=coalesce("
                                   "launching_at, ?) WHERE prompt_id=?", (now, now, prompt))
                if isinstance(queue_id, str) and len(queue_id) == 36:
                    connection.execute("UPDATE records SET queue_id=? WHERE record_id=?", (queue_id, record_id))
            elif move in ("released", "not_started"):
                connection.execute("UPDATE records SET state=?, finished_at=NULL WHERE record_id=? AND state=?",
                                   (RecordState.WAITING, record_id, RecordState.IN_FLIGHT))
                connection.execute("UPDATE prompts SET launching_at=NULL WHERE prompt_id=?", (prompt,))
            elif move in _ENDS:
                reason, record_state = _ENDS[move]
                connection.execute("UPDATE records SET state=?, finished_at=?, withdraw=0 WHERE record_id=?",
                                   (record_state, now, record_id))
                used = dict(row, sent_count=row["sent_count"] + 1)
                following = None if move == "unproven" else next_slot(used)
                if following is None:
                    connection.execute("UPDATE prompts SET state=?, reason=?, words=NULL, sent_count=?, finished_at=? "
                                       "WHERE prompt_id=?", (PromptState.DONE, reason, used["sent_count"], now, prompt))
                else:
                    connection.execute("UPDATE prompts SET state=?, reason=?, sent_count=?, record_id=NULL, due_at=?, "
                                       "launching_at=NULL, sent_at=NULL WHERE prompt_id=?",
                                       (PromptState.WAITING, reason, used["sent_count"], following, prompt))
            elif move == "withdrawn":
                connection.execute("UPDATE records SET state=?, finished_at=?, withdraw=0 WHERE record_id=?",
                                   (RecordState.CANCELLED, now, record_id))
                if row["withdraw"]:
                    connection.execute("UPDATE prompts SET state=?, reason=?, words=NULL, finished_at=? WHERE "
                                       "prompt_id=?", (PromptState.CANCELLED, PromptReason.WITHDRAWN, now, prompt))
                else:
                    connection.execute("UPDATE prompts SET state=?, reason=?, record_id=NULL, launching_at=NULL, "
                                       "sent_at=NULL WHERE prompt_id=?", (PromptState.HELD, PromptReason.WITHDRAWN,
                                                                          prompt))
            elif move == "withdraw_refused":
                connection.execute("UPDATE prompts SET reason=? WHERE prompt_id=?", (PromptReason.WITHDRAW_REFUSED,
                                                                                     prompt))
                connection.execute("UPDATE records SET withdraw=0 WHERE record_id=?", (record_id,))
            elif move != "waiting":
                return None
            return {"capability": PROMPT_QUEUE, "trip": move == "unproven"}

    def prompts_in_flight(self) -> list:
        """Every prompt whose occurrence is in flight, whatever its capability stands at: core watches each to its end."""
        return [row for row in self.prompts(pending=True) if row["record_state"] == RecordState.IN_FLIGHT]

    def release_unlaunched_prompts(self, after, at=None) -> int:
        """Every occurrence claimed `after` seconds ago whose launch never began, handed back (as state/resets)."""
        now = self._now(at)
        with self._transaction(create=False) as connection:
            if connection is None:
                return 0
            keys = [row[0] for row in connection.execute(
                "SELECT c.record_id FROM prompts p JOIN records c ON c.record_id = p.record_id WHERE p.state=? "
                "AND p.launching_at IS NULL AND p.sent_at IS NULL AND c.state=? AND c.claimed_at IS NOT NULL "
                "AND c.claimed_at <= ?", (PromptState.READY, RecordState.IN_FLIGHT, now - after)).fetchall()]
            for key in keys:
                connection.execute("UPDATE records SET state=? WHERE record_id=? AND state=?",
                                   (RecordState.WAITING, key, RecordState.IN_FLIGHT))
            return len(keys)


class PromptsHandle:
    """What prompt_queue's code is given of the state (state.Scoped's `prompts`): the prompts, read always; their
    occurrences made and their moves of its own written only while the runtime has it on."""
    __slots__ = ("capability", "_calls")

    def __init__(self, state, capability, on):
        self.capability = capability

        def is_on():
            return on is not None and on() is True

        def writing(call):
            def written(*arguments, **keywords):
                if not is_on():
                    raise StateError("the capability is not on")
                return call(*arguments, **keywords)
            return written

        def occur(prompt_id, key, thread_id, due_at):
            """A due prompt's occurrence: its record waiting, and the prompt ready with it."""
            if state.add_record(key, capability, thread_id):
                state.change_prompt(prompt_id, state=PromptState.READY, record_id=key, due_at=due_at)
                return True
            return False

        self._calls = {
            "on": is_on,
            "now": lambda: state.clock(),
            "prompts": state.prompts,
            "prompt": state.prompt,
            "occur": writing(occur),
            "change": writing(state.change_prompt),
            "drop": writing(lambda key: state.move_record(key, RecordState.CANCELLED)),
            "end": writing(lambda reason, *, thread_id=None: state.end_prompts(reason, thread_id=thread_id)),
        }

    def __getattr__(self, name):
        calls = object.__getattribute__(self, "_calls")
        if name in calls:
            return calls[name]
        raise AttributeError(name)


def end_pending(connection, capabilities, now) -> None:
    """Every prompt still to go whose occurrence is not in flight, ended (turned_off) with its words, in the caller's
    transaction, when prompt_queue moves off on (state/arming.py): turning it on again revives none."""
    if PROMPT_QUEUE not in capabilities:
        return
    rows = connection.execute("SELECT p.prompt_id, p.record_id FROM prompts p LEFT JOIN records c ON c.record_id = "
                              "p.record_id WHERE p.state IN (?,?,?) AND (c.state IS NULL OR c.state <> ?)",
                              (*PENDING, RecordState.IN_FLIGHT)).fetchall()
    for prompt, record in rows:
        connection.execute("UPDATE prompts SET state=?, reason=?, words=NULL, finished_at=? WHERE prompt_id=?",
                           (PromptState.CANCELLED, PromptReason.TURNED_OFF, now, prompt))
        if record is not None:
            connection.execute("UPDATE records SET state=?, finished_at=? WHERE record_id=? AND state<>?",
                               (RecordState.CANCELLED, now, record, RecordState.FINISHED))
