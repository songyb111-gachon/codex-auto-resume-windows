# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""Subagent recovery through the parent (v0.6.15-beta, the plan's item 5): a parent hears, in fixed words, which of
its subagents stopped and why - and nothing is ever written to a subagent. At P4, P8 and P2.

The standard edition recovers a person's own conversations alone: a subagent's conversation is never detected and
never sent to (A15). With this on:

* 5a, P4 - the parent failed too (the usual usage-limit case): core's own words for the parent's continuation, and
  one line per subagent whose latest turn failed or was interrupted, at most MAX_LINES:
  "Subagent <its id> stopped: <kind>. Resume or respawn it only if it is still needed." - the catalog's words, with
  only the subagent's canonical id and a closed kind word varying (the failure's category, dropped at once to one of
  KINDS: the raw error is never kept). Core takes them as a Custom message (at most 2,000 characters - over that, its
  own words go). One mention per child failure: a decision kept in state/continuations.py under its key.
* 5b, P8 then P2 - the parent completed normally after a subagent failed: one P2 CONTINUATION to the parent with the
  same lines, its ordinal the parent's latest turn, sent only while that turn is the latest. Off until MS passes on
  the Codex in force (the narrowed route): 5a adds words to a send core makes anyway; 5b makes new sends on lineage
  nobody has watched on this Codex.

Never the child: every record is the parent's (`thread_id`), core's P2 gate refuses a conversation that is not a
person's own, and P4 changes only the words of a send to the parent. Children are read only for a parent asked about
(codex/lineage.py); Codex's way of writing items into a conversation is named in no source file of either edition
(tests/test_structural_invariants.py).
"""
from __future__ import annotations

from codex_auto_resume import failures
from codex_auto_resume.domain import ids
from codex_auto_resume.domain.plug import DEFER

from .. import statement
from ..codex import inuse
from ..codex.lineage import Lineage
from ..codex.turns import Turns
from ..vocabulary import ContinuationKind, ContinuationReason, Measurement, RecordState
from .continued import answer_key, handed, words_pass

CAPABILITY = "subagent_parent"
MAX_LINES = 5
LINE_KEY = "continue.subagent.line"
KIND_PREFIX = "continue.subagent.kind."
# The closed kind a subagent's stop is told as: a usage limit, a temporary failure, an interruption, or an error.
KINDS = ("usage_limit", "temporary", "interrupted", "error")
LOOK_EVERY = 60
RECENT = 3600
SEEN_LIMIT = 256


def kind_of(child) -> str | None:
    """The closed kind word a subagent's latest turn is told as, or None for one that did not stop on a failure."""
    if child.status == "interrupted":
        return "interrupted"
    if child.status != "failed":
        return None
    if child.category == failures.USAGE_LIMIT:
        return "usage_limit"
    return "temporary" if child.category in failures.TRANSIENT else "error"


def line(child, kind, locale=None) -> str | None:
    """One subagent's line, in the catalog's words: its canonical id and its kind word, nothing else."""
    if not ids.is_uuid(child.thread_id) or kind not in KINDS:
        return None
    word = statement.CATALOGS.text(KIND_PREFIX + kind, locale)
    return statement.CATALOGS.text(LINE_KEY, locale, child=str(child.thread_id).lower(), kind=word)


class _Errand:
    __slots__ = ("code", "view")

    def __init__(self, code, view):
        self.code, self.view = code, view

    def run(self, guard):
        return self.code.look(self.view)


class SubagentParent:
    """The capability's code: its hooks at P4, P8 and P2. `bind` gives it its view of the state (state.Scoped)."""
    __slots__ = ("paths", "_scoped", "_home", "_looked", "_pending")

    def __init__(self, paths, *, home=None):
        self.paths = paths
        self._scoped = None
        self._home = home
        self._looked = None
        # v0.6.18: the lines P4 put in a parent's words, by its interruption, told once the claim carrying them commits.
        self._pending = {}

    def bind(self, scoped):
        self._scoped = scoped

    def _codex_home(self):
        return self._home if self._home is not None else inuse.home(self.paths)

    def _stopped(self, parent):
        """[(key, line)] for each of `parent`'s subagents whose latest turn stopped on a failure and was not told
        yet, at most MAX_LINES. Empty where nothing can be read."""
        try:
            children = Lineage(self._codex_home()).children(parent)
        except Exception:
            return []
        found = []
        handle = self._scoped.continuations
        for child in children:
            kind = kind_of(child)
            if kind is None or child.turn_id is None:
                continue
            key = answer_key(CAPABILITY, parent, child.thread_id, child.turn_id)
            if handle.get(key) is not None:
                continue                                 # told once
            text = line(child, kind)
            if text is not None:
                found.append((key, text))
            if len(found) >= MAX_LINES:
                break
        return found

    # ------------------------------------------------------------------ P4 (5a)
    def text(self, record, text):
        """P4: core's own words for a parent's continuation, and a line for each subagent that stopped - or DEFER
        where none did, the lines would pass 2,000 characters, or nothing can be read."""
        scoped = self._scoped
        thread = record.get("thread_id") if isinstance(record, dict) else None
        if scoped is None or not isinstance(text, str) or not ids.is_uuid(thread):
            return DEFER
        stopped = self._stopped(thread)
        if not stopped:
            return DEFER
        words = text + "\n\n" + "\n".join(line_ for _key, line_ in stopped)
        if len(words) > 2000:
            return DEFER
        key = record.get("interruption_id")
        if not ids.is_interruption_id(key) or not scoped.continuations.on():
            return DEFER                                 # watched: only core's words
        # v0.6.18: told only once the claim carrying these words commits (`words_sent`): a claim held after P4, or
        # core's own words sent instead (a conversation's Custom message, the validator), tells nothing - and the
        # lines come again at the next send.
        if len(self._pending) >= SEEN_LIMIT:
            self._pending.clear()
        self._pending[key] = (thread, tuple(child for child, _line in stopped))
        return words

    def words_sent(self, record):
        """The claim that carried P4's lines for `record` committed (runtime.Runtime._words_sent): each child told."""
        key = record.get("interruption_id") if isinstance(record, dict) else None
        pending = self._pending.pop(key, None)
        if pending is None:
            return
        thread, children = pending
        for child in children:
            self._scoped.continuations.note(child, ContinuationKind.SUBAGENT, thread, ContinuationReason.MENTIONED)
        self._count("told")

    # ------------------------------------------------------------------ P8 (5b)
    def tick(self, view):
        scoped = self._scoped
        if scoped is None or not scoped.passed(Measurement.MS):
            return DEFER                                 # 5b waits for MS: 5a alone runs
        now = scoped.now()
        if self._looked is not None and 0 <= now - self._looked < LOOK_EVERY:
            return DEFER
        return _Errand(self, view)

    def look(self, view):
        """The errand (5b): each conversation that finished a turn lately, with no error, whose subagent stopped -
        one continuation to it, with the lines."""
        scoped = self._scoped
        handle = scoped.continuations
        if not handle.on():
            return None
        now = scoped.now()
        self._looked = now
        try:
            turns = Turns(self._codex_home())
            candidates = turns.recent(now - RECENT)
        except Exception:
            return None
        for parent in candidates:
            try:
                if view.thread_enabled(parent) is not True:
                    continue
                turn = turns.latest(parent)
            except Exception:
                continue
            if turn is None or turn.status != "completed" or turn.errored:
                continue
            stopped = self._stopped(parent)
            if not stopped:
                continue
            words = "\n".join(line_ for _key, line_ in stopped)
            key = answer_key(CAPABILITY, "followed_up", parent, turn.turn_id)
            if handle.get(key) is not None or not words_pass(words):
                continue
            if handle.add(key, ContinuationKind.SUBAGENT, parent, words, ordinal=turn.ordinal):
                for child_key, _line in stopped:
                    handle.note(child_key, ContinuationKind.SUBAGENT, parent, ContinuationReason.MENTIONED,
                                ordinal=turn.ordinal)
                self._count("followed_up")
        return None

    # ------------------------------------------------------------------ P2 (5b)
    def records(self, view):
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


def make(paths) -> SubagentParent:
    """The capability's factory (registry.CapabilityDef.make): its code for one installation."""
    return SubagentParent(paths)
