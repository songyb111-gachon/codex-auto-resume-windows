# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""Empty-response recovery (v0.6.15-beta, the plan's item 3): a turn that ended with no reply is continued once, and a
chain of them twice, judged only by the kinds of item it left - at P8 and P2.

The standard edition recovers failed turns alone: a turn Codex completed is never one it continues (0.5, A13). With
this on, a conversation of a person's own, switched on, whose latest turn Codex completed with no error and no final
agent item, and whose items are only of the kinds in EMPTY_KINDS - the person's message and Codex's reasoning, and
nothing it did or said - is sent the edition's own words once, in the interface language: "The last turn ended
without a reply. Please continue from where you stopped." (A26). Judged by kinds alone, never by words
(codex/turns.py): any other kind, or one Codex adds tomorrow, is not empty (fail closed).

* P8, the errand, at most once a minute: the conversations with a turn completed in the last hour (codex/turns.recent),
  each one's latest turn looked at twice, SECOND_LOOK apart, at least SETTLE_AFTER after it completed and the same
  both times; then a goal Codex keeps going (active) or that Codex's own loop guard stopped (blocked) is left alone -
  noted, never written (the owner's answer of 2026-10-09) - and goals that cannot be read leave it to the standard
  edition. Once a turn: the key is the turn's (state/continuations.py). Twice a chain: a chain is the run of empty
  turns each the very next turn after a continuation of this edition's that was delivered; its third is not made,
  noted `chain_spent`.
* P2: every continuation waiting, handed core with its words and its turn's ordinal (P2's CONTINUATION): core sends it
  only while that turn is still the conversation's latest (SUPERSEDED otherwise), through its gates, the one claim
  and the ledger's caps across both stores, and the pre-send look (projection fresh, nothing queued by anyone).

Until ME passes for the Codex in force, the same route, with the UNMEASURED warning the person confirms.
"""
from __future__ import annotations

from codex_auto_resume.domain.plug import DEFER
from codex_auto_resume.domain.plughands import Widening

from .. import statement
from ..codex import inuse
from ..codex.goals import Goals, GoalsUnavailable
from ..codex.turns import Turns, TurnsUnavailable
from ..vocabulary import ContinuationKind, ContinuationReason, GoalStatus, RecordState
from .continued import answer_key, handed, words_pass
from .usage import EVERY_CONVERSATION

CAPABILITY = "empty_response"
# The kinds an empty turn's items may be, and nothing else: the person's message and Codex's reasoning.
EMPTY_KINDS = frozenset({"userMessage", "reasoning"})
SETTLE_AFTER = 10
SECOND_LOOK = 30
LOOK_EVERY = 60
RECENT = 3600
CHAIN_LIMIT = 2
WORDS_KEY = "continue.empty_response"
# How many conversations' first looks are remembered at most, before all are forgotten at once.
SEEN_LIMIT = 256


def empty(turn) -> bool:
    """Whether `turn` (codex/turns.Turn) ended with no reply: completed, no error, no final agent item, a message of
    the person's and nothing but EMPTY_KINDS."""
    return (turn is not None and turn.status == "completed" and not turn.errored and not turn.final_agent
            and turn.completed_at is not None and turn.kinds.get("userMessage", 0) > 0
            and set(turn.kinds) <= EMPTY_KINDS)


class _Errand:
    __slots__ = ("code", "view")

    def __init__(self, code, view):
        self.code, self.view = code, view

    def run(self, guard):
        return self.code.look(self.view)


class EmptyResponse:
    """The capability's code: its hooks at P8 and P2. `bind` gives it its view of the state (state.Scoped)."""
    __slots__ = ("paths", "_scoped", "_home", "_seen", "_looked")

    def __init__(self, paths, *, home=None):
        self.paths = paths
        self._scoped = None
        self._home = home
        self._seen = {}
        self._looked = None

    def bind(self, scoped):
        self._scoped = scoped

    def _codex_home(self):
        return self._home if self._home is not None else inuse.home(self.paths)

    def _source(self):
        """Core's reader, judging a conversation as core does (v0.6.18) - a person's own, or P19's widening while
        Recover every conversation is on - never a subagent's, a review's or another kind Codex makes for itself, which
        core never recovers and whose record would wait for good (as the wrap-up and the forced stop judge one)."""
        from codex_auto_resume.codex import LocalSource
        source = LocalSource(self._codex_home())
        try:
            widened = self._scoped.armed(EVERY_CONVERSATION) is True
        except Exception:
            widened = False
        source.widened = frozenset({Widening.EVERY_DESKTOP}) if widened else frozenset()
        return source

    # ------------------------------------------------------------------ P8
    def tick(self, view):
        scoped = self._scoped
        if scoped is None:
            return DEFER
        now = scoped.now()
        if self._looked is not None and 0 <= now - self._looked < LOOK_EVERY:
            return DEFER
        return _Errand(self, view)

    def look(self, view):
        """The errand: the conversations that finished a turn lately, each one's latest turn looked at."""
        scoped = self._scoped
        handle = scoped.continuations
        if not handle.on():
            return None
        now = scoped.now()
        self._looked = now
        try:
            home = self._codex_home()
            turns = Turns(home)
            candidates = turns.recent(now - RECENT)
            source = self._source()
        except Exception:
            return None
        self._not_own(handle, source)
        if len(self._seen) > SEEN_LIMIT:
            self._seen.clear()
        for thread in candidates:
            try:
                if view.thread_enabled(thread) is not True or source.latest(thread) is None:
                    continue                             # switched off, or not a conversation of a person's own
                turn = turns.latest(thread)
            except (TurnsUnavailable, Exception):
                continue
            if not empty(turn) or now - turn.completed_at < SETTLE_AFTER:
                self._seen.pop(thread, None)
                continue
            shape = (turn.turn_id, tuple(sorted(turn.kinds.items())))
            first = self._seen.get(thread)
            if first is None or first[0] != shape:
                self._seen[thread] = (shape, now)
                continue
            if now - first[1] < SECOND_LOOK:
                continue
            self._seen.pop(thread, None)
            self._answer(handle, home, turns, thread, turn)
        return None

    @staticmethod
    def _not_own(handle, source) -> None:
        """v0.6.18: a continuation waiting for a conversation core does not take for a person's own - made before this
        look judged them so, or one Recover every conversation widened to and no longer does - ended: core holds it
        WAITING for good (not_user_conversation), ahead of this capability's others at P2."""
        try:
            waiting = {row["thread_id"] for row in handle.mine() if row["record_state"] == RecordState.WAITING}
        except Exception:
            return
        for thread in waiting:
            try:
                if source.latest(thread) is None:
                    handle.end(ContinuationReason.WITHDRAWN, thread_id=thread)
            except Exception:
                continue

    def _answer(self, handle, home, turns, thread, turn) -> None:
        key = answer_key(CAPABILITY, thread, turn.turn_id)
        if handle.get(key) is not None:
            return                                       # answered, or decided, once
        try:
            goal = Goals(home).read(thread)
        except GoalsUnavailable:
            return                                       # what the standard edition does: nothing
        except Exception:
            return
        if goal is not None and goal.status in (GoalStatus.ACTIVE, GoalStatus.BLOCKED):
            if handle.note(key, ContinuationKind.EMPTY_RESPONSE, thread, ContinuationReason.GOAL_LEFT,
                           ordinal=turn.ordinal):
                self._count("goal_left")
            return
        chain = self._chain(handle, turns, thread, turn)
        if chain is None:
            return
        if chain > CHAIN_LIMIT:
            if handle.note(key, ContinuationKind.EMPTY_RESPONSE, thread, ContinuationReason.CHAIN_SPENT,
                           ordinal=turn.ordinal, chain=chain):
                self._count("chain_spent")
            return
        words = statement.CATALOGS.text(WORDS_KEY)
        if not words_pass(words):
            return
        if handle.add(key, ContinuationKind.EMPTY_RESPONSE, thread, words, ordinal=turn.ordinal, chain=chain):
            self._count("found")

    @staticmethod
    def _chain(handle, turns, thread, turn):
        """Where `turn` stands in its chain: 1, or one more than the continuation it is the very next turn after - one
        of this edition's that was delivered. None where that cannot be read."""
        last = handle.last(thread)
        if (last is None or last.get("record_id") is None or last.get("reason") != ContinuationReason.DELIVERED
                or type(last.get("ordinal")) is not int or last["ordinal"] >= turn.ordinal):
            return 1
        try:
            between = turns.between(thread, last["ordinal"], turn.ordinal)
        except Exception:
            return None
        return last["chain"] + 1 if between == 0 else 1

    # ------------------------------------------------------------------ P2
    def records(self, view):
        """P2: every continuation of this capability waiting, with its words. One in flight is the runtime's to hand
        (runtime.records), whatever this stands at now."""
        scoped = self._scoped
        if scoped is None:
            return DEFER
        try:
            rows = scoped.continuations.mine()
        except Exception:
            return DEFER
        found = [handed(row) for row in rows if row["record_state"] == RecordState.WAITING]
        return [record for record in found if record is not None] or DEFER

    def _count(self, code) -> None:
        try:
            self._scoped.count(code)
        except Exception:
            pass


def make(paths) -> EmptyResponse:
    """The capability's factory (registry.CapabilityDef.make): its code for one installation."""
    return EmptyResponse(paths)
