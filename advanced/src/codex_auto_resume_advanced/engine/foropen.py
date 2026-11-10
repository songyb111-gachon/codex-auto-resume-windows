# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""Queue for opening: a conversation the Codex app does not hold is sent core's ordinary continuation, left in Codex's
queue for when the person opens it, for the days they chose (v0.6.15-beta, P16's QUEUE_FOR_OPEN).

The standard edition waits for the app to hold a conversation before it sends anything there (A11: nothing is queued
on the off chance). With this on, P16 answers QUEUE_FOR_OPEN for a usage-limited conversation the app does not hold
(core asks only where it reads notLoaded, never unknown, after consent): core sends its own words, with its marker,
through its own backend, under the one claim - which writes this capability's QUEUE_FOR_OPEN override, one per
interruption (ledger.py) - and Codex delivers it when the conversation is opened (M1). In the watch core asks again
whether to keep it there: yes while the override is within the person's Days (3 to 30, 3 by default), no after - and
core takes it back at 30 days and an hour whatever is answered (core's engine/foropen.py). An interruption once
queued for opening is never queued for opening again: given back to waiting, it waits for the app as A11 says.

Opened and not delivered within core's delivery timeout (300 seconds), core takes it back (not_delivered_on_open), gives it back to
waiting and sends it the ordinary way to the now loaded conversation - and this capability turns off: the tripwire
NOT_DELIVERED_ON_OPEN (runtime.moved). Where the goal continuation's route applies it answers first, before this in
the registry, and its route is carried out.

Beside the goal continuation (v0.6.17, #47 P-4). Once that route has set a conversation's goal active, its P16 answers
nothing more, and core asks no P3 for a record queued for opening - so the goal continuation's hold, "the goal and the
standard continuation never both run", would never be asked, and opening the conversation could run two turns: the
goal carried on (M2) and the queued continuation (M1). Measurement MQG asks Codex exactly that. Where it passed on the
Codex in force - one turn: the queued message ran and the goal carried on after it - both apply and nothing is held.
Anywhere else - not measured on this Codex, or measured as two turns - this answers nothing for a conversation whose
goal is active while the goal continuation is on: the goal carries the conversation, one continuation, and the record
waits for the app as A11 says. Its journal says so once a record, `qfo.goal_unmeasured` or `qfo.goal_two_turns`. The
goal is read as the goal continuation reads it (codex/goals.py: its status, never its words); one that cannot be read
is no goal, as there. An active goal also stands for the goal continuation's claim: its route is accepted only once the
goal reads back active.

It holds no memory of its own: what it reads is the state's, through its view (state.Scoped).
"""
from __future__ import annotations

from codex_auto_resume import failures
from codex_auto_resume.domain.plug import DEFER, Alternative

from ..codex import inuse
from ..codex.goals import Goals
from ..vocabulary import GoalStatus, Measurement, OptionKey, OverrideKind

CAPABILITY = "queue_for_open"
GOAL = "goal_continuation"
# MQG (v0.6.17): a goal set active and a continuation queued for opening, opened - one turn (a pass) or two. Read by its
# id; on a build whose vocabulary does not have it yet, it is not measured.
MQG = getattr(Measurement, "MQG", None)
# Why it answered nothing beside an active goal, as its journal says it (registry.QUEUE_FOR_OPEN.codes).
GOAL_UNMEASURED, GOAL_TWO_TURNS = "goal_unmeasured", "goal_two_turns"
CODES = (GOAL_UNMEASURED, GOAL_TWO_TURNS)
# Records it said that for, forgotten all at once past this many: one journal line a record.
NOTED_LIMIT = 4096
DAYS = (3, 4, 5, 6, 7, 14, 30)
DEFAULT_DAYS = 3
DAY = 86400
# Where core asks P16 for a conversation the running app does not hold (core's engine/delivery.APP_FREE).
APP_FREE = "app_free"


def watching(record) -> bool:
    """Whether core asks about a continuation already queued for opening (its watch hands `queued_since`), rather
    than whether to queue one."""
    return isinstance(record, dict) and "queued_since" in record


class QueueForOpen:
    """The capability's code: its hook at P16. `bind` gives it its view of the state (state.Scoped). `home` is the
    Codex home whose goals are read (None: the watcher's, codex/inuse.py) - the tests' seam."""
    __slots__ = ("paths", "_scoped", "_home", "_noted")

    def __init__(self, paths, *, home=None):
        self.paths = paths
        self._scoped = None
        self._home = home
        self._noted = set()

    def bind(self, scoped):
        self._scoped = scoped

    def unloaded(self, record):
        """P16: QUEUE_FOR_OPEN to queue a record not queued for opening before, or - in the watch - to keep one
        queued while its override is within the Days chosen; DEFER otherwise, and where the state cannot be read."""
        scoped = self._scoped
        key = record.get("interruption_id") if isinstance(record, dict) else None
        if scoped is None or not isinstance(key, str):
            return DEFER
        # v0.6.16-beta.4: queued only for a conversation the running app does not hold - never one asked with the
        # app closed or held by another session; the watch, which hands neither, asks only whether to keep it.
        if not watching(record) and record.get("holder") != APP_FREE:
            return DEFER
        # v0.6.17 (#47, P-5): usage-limited records only, as its definition and statement say. Core never asks P3 for
        # a record queued for opening, so a full context window queued here would skip compact_continue's hold until
        # /compact and run on a full window on open; a network or server failure is not what it was turned on for.
        if not watching(record) and record.get("category") != failures.USAGE_LIMIT:
            return DEFER
        if not watching(record) and self._for_goal(scoped, record, key):
            return DEFER
        try:
            override = scoped.request(key)
            if not watching(record):
                return DEFER if override is not None else Alternative.QUEUE_FOR_OPEN
            days = scoped.options().get(OptionKey.DAYS, DEFAULT_DAYS)
            now = scoped.now()
        except Exception:
            return DEFER
        if override is None or override.get("kind") != OverrideKind.QUEUE_FOR_OPEN:
            return DEFER
        days = days if days in DAYS else DEFAULT_DAYS
        return Alternative.QUEUE_FOR_OPEN if now - override["created_at"] < days * DAY else DEFER


    def _for_goal(self, scoped, record, key) -> bool:
        """Whether the conversation's active goal carries it: the goal continuation on, MQG not passed on the Codex
        in force, and the goal active. Said once a record in its journal, with why."""
        try:
            if not scoped.armed(GOAL):
                return False
            if MQG is not None and scoped.passed(MQG):
                return False
        except Exception:
            pass                                  # no verdict read is no pass: the side with one continuation
        if not self._active(record.get("thread_id")):
            return False
        try:
            failed = MQG is not None and scoped.failed(MQG) is True
        except Exception:
            failed = False
        if key not in self._noted:
            if len(self._noted) >= NOTED_LIMIT:
                self._noted.clear()
            self._noted.add(key)
            try:
                scoped.count(GOAL_TWO_TURNS if failed else GOAL_UNMEASURED)
            except Exception:
                pass
        return True

    def _active(self, thread_id) -> bool:
        """Whether `thread_id`'s goal is active; a goal that cannot be read is none."""
        if not isinstance(thread_id, str):
            return False
        try:
            goal = Goals(self._home if self._home is not None else inuse.home(self.paths)).read(thread_id)
        except Exception:
            return False
        return goal is not None and goal.status == GoalStatus.ACTIVE


def make(paths) -> QueueForOpen:
    """The capability's factory (registry.CapabilityDef.make): its code for one installation."""
    return QueueForOpen(paths)
