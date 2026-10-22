# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""Compact a full conversation, then continue (v0.6.16-beta.4, P17, P3 and P16).

A turn that fails because the conversation is longer than its model's context window is one the standard edition
never retries (A14): it ends the record and its needs-you card says to compact or start again. Codex's own automatic
compaction comes first; this is for when it did not, and M7 settled that a queued `/compact` is plain text - so the
queue never compacts here, and no source of either edition sends a text beginning with `/`.

* P17 - ADMIT for Codex's own `contextWindowExceeded` alone (core offers it for that one code, failures.admits): the
  failure is a core record of its kind, terminal_invalid, which core follows as its own.
* P3 known_failure - ADMIT again while it is worth going on: not a day since it was taken up, and the compaction
  turn after it, if there is one, did not fail. DEFER ends it as the failure it is, and its card stands.
* P3 thread_available - the Codex app holds the conversation: HOLD while the failed turn is still its latest - Pending
  asks the person to run /compact in Codex (MXA) - and DEFER once a compaction turn is the latest: core's ordinary
  continuation follows, once (a compaction turn supersedes nothing of this record's, core's engine/detect.py).
* P16 - nothing holds it and Codex is closed: compact mode of the headless route (codex/headless.py) -
  thread/resume, the same settings refusals, thread/compact/start - which core settles as "accepted": the record
  waits again, its claim counted. Once the compaction turn is the latest, the same route continues it with core's
  words ("ran"). A compaction that takes ten minutes is let go (codex/headless.COMPACT_SECONDS).

Its ceilings are two a conversation - the compaction's claim and its continuation's - and six a day. Until MX (the
headless half) and MXA (the app half) pass for the Codex in force, its statement carries the UNMEASURED warning.
"""
from __future__ import annotations

from codex_auto_resume.domain import ids
from codex_auto_resume.domain.plug import DEFER, Alternative

from ..codex import headless, inuse
from ..codex.turns import Turns
from .headless import HOUR, _app_running, follow_up, unheld

CAPABILITY = "compact_continue"
KIND = "terminal_invalid"
CODE = "contextWindowExceeded"
# How long after it was taken up a full conversation is still continued, at most.
GIVE_UP_SECONDS = 24 * HOUR
# The kinds a compaction turn leaves (core's codex/history.later_turns: no content, kinds alone).
COMPACTION_KINDS = frozenset({"contextCompaction", "reasoning"})


class CompactContinue:
    """The capability's code: its hooks at P17, P3 and P16, and P8 for its runs. `bind` gives it its view of the
    state (state.Scoped). Its seams are the tests': `turns` reads the latest turn (None: the Codex home's,
    codex/inuse.py), `session`, `follower` and `app_running` are the headless route's."""
    __slots__ = ("paths", "_scoped", "_turns", "_open", "follower", "_app", "_routes")

    def __init__(self, paths, *, turns=None, session=None, follower=None, app_running=None):
        self.paths, self._scoped = paths, None
        self._turns = turns
        self._open = session if session is not None else headless.live_session(paths)
        self.follower = follower or headless.FOLLOWER
        self._app = app_running if app_running is not None else _app_running(paths)
        self._routes = {}

    def bind(self, scoped):
        self._scoped = scoped

    def _latest(self, thread_id):
        """The conversation's latest turn (codex/turns.Turn), or None where it cannot be read."""
        try:
            turns = self._turns if self._turns is not None else Turns(inuse.home(self.paths))
            return turns.latest(thread_id)
        except Exception:
            return None

    def _compacted(self, record):
        """Whether the latest turn after `record`'s failure is a compaction alone that completed: True, False (none, or
        one interrupted: nothing was compacted) - or "failed" for one that ended failed - and None where it cannot be
        read or is still running (v0.6.18: never a continuation onto a context a running compaction has not made)."""
        latest = self._latest(record.get("thread_id"))
        if latest is None:
            return None
        if latest.ordinal <= (record.get("ordinal") or 0):
            return False
        kinds = {kind for kind, count in latest.kinds.items() if count}
        if not kinds or not kinds <= COMPACTION_KINDS or "contextCompaction" not in kinds:
            return False
        if latest.status == "failed":
            return "failed"
        if latest.status == "completed":
            return True
        return False if latest.status == "interrupted" else None

    def admission(self, failure):
        """P17: ADMIT for a full context window - Codex's contextWindowExceeded - and nothing else."""
        if failure.get("category") != KIND or failure.get("code") != CODE:
            return DEFER
        return Alternative.ADMIT

    def gate(self, name, record, facts):
        """P3: ADMIT again at known_failure while it is worth going on; at thread_available, HOLD until the person's
        /compact is the latest turn."""
        if not isinstance(record, dict) or record.get("category") != KIND:
            return DEFER
        if name == "known_failure":
            taken = self._taken_at(record)
            now = self._scoped.now() if self._scoped is not None else None
            if taken is None or now is None or now - taken >= GIVE_UP_SECONDS:
                return DEFER
            return DEFER if self._compacted(record) == "failed" else Alternative.ADMIT
        if name == "thread_available":
            return DEFER if self._compacted(record) is True else Alternative.HOLD
        return DEFER

    def _taken_at(self, record):
        try:
            row = self._scoped.admission(record.get("interruption_id"))
        except Exception:
            return None
        return row.get("created_at") if isinstance(row, dict) else None

    def unloaded(self, record):
        """P16, nothing holding it while Codex is closed: compact it here, or - once compacted - continue it here."""
        key = record.get("interruption_id") if isinstance(record, dict) else None
        if (not unheld(record) or record.get("category") != KIND or not ids.is_interruption_id(key)
                or self.follower.live() is not None):
            return DEFER
        compacted = self._compacted(record)
        if compacted is None or compacted == "failed":
            return DEFER
        route = headless.HeadlessRun(CAPABILITY, key=key, session=self._open, follower=self.follower,
                                     seconds=HOUR, mode=headless.TURN if compacted else headless.COMPACT,
                                     app_running=self._app)
        self._routes = {key: route}
        return route

    def tick(self, view):
        """P8: the run kinds' one path (engine/headless.follow_up): how each run ended journalled, the live one's row
        written, a Stop handed on, a row no thread follows ended LOST."""
        return follow_up(self._scoped, self.follower, CAPABILITY, self._routes.values())

    # v0.6.18: turned off or watched, the same bookkeeping (runtime.Runtime.tick): a Stop still reaches a live run.
    tend = tick


def make(paths) -> CompactContinue:
    """The capability's factory (registry.CapabilityDef.make): its code for one installation."""
    return CompactContinue(paths)
