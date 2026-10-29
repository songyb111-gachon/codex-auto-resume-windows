# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""The prompt queue (v0.6.15-beta, the plan's item 7, on reset_message's way): a person's queued messages go after the
current turn, at a time or on a schedule, in order, each once, and their words go once each has ended - at P2.

The standard edition sends one thing of its own, a continuation for a recovery that is due (A26, C4). With this on, a
person writes messages in the Dashboard for one conversation each (control/prompts.py): after the turn now running
(`after_turn`: due at once, it goes through Codex's own queue, which runs it when that turn ends - MT measures it), at a
time (`at_time`), or every day or week from a time (`recurring`, 30 occurrences and 30 days at most). Core sends each as
it sends a message at a reset (P2's MESSAGE: exactly as typed, its marker after a blank line), through its gates, the
one claim and the ledger's caps - one in flight in a conversation across both stores, fifteen minutes apart and five a
day in one conversation (A20 kept, the owner's answer of 2026-10-09).

At P2, each conversation's prompts in their order (`position`), the first still to go alone eligible:
* one whose conversation is off is cancelled; one over 2,000 characters while Longer messages is off, cancelled;
* `depends`: not due until the one before it in that conversation was delivered - ended any other way, it is held
  (dependency_failed) for the person to say go on or cancel;
* due, its occurrence is made - a record with an id of its own - and handed core with its words;
* a series' occurrences that fell while nothing ran are caught up once, the latest alone, the earlier counted as used
  (`missed`); an occurrence not sent a day after it fell due is used as expired, and the series goes on;
* (v0.6.19, #50) one that waits while a turn runs (`while_running` "wait") is not handed while its conversation's
  latest turn is in progress (read-only, codex/turns.py) - its reason turn_running - nor while that cannot be read, and
  is handed once the turn is final; one that goes into Codex's queue ("queue", what every prompt did before) is
  handed as always. Either way core's every gate still applies, and an uncertain send still blocks.

The words leave the disk when a one-time prompt's occurrence ends - delivered, or ended any other way - not at its
send: while Codex holds it they are kept, so a Pause that takes it back can send them again on Go on (state/prompts.py,
prompt_moved) - and at a series' end, at a cancel, at expiry, when the conversation is switched off and when this is
turned off (watched, they are kept - v0.6.16-beta.3). They never reach a log, the journal, diagnostics, a
notification, the status, MCP or a golden.

v0.6.20 (#50 item 1, MIMG): a message may carry pictures - the product's own copies (images.py), kept while it is
still to go and swept at each P2 once it is not. An occurrence of one goes by this capability's own channel, P5
(`sender`): `thread/queue/add` with its words first and then each picture as a `localImage` item naming the copy, in
the person's order, under the client id core derives - and P15 (`delivery`) answers CLIENT_ID, so core proves it by
that id and no marker, as a chat message (engine/chat.py). A message with no pictures goes exactly as before, through
core's backend with its marker. One whose copies are no longer sendable (one gone, or not a picture any more), or any
with pictures while MIMG failed on the Codex in force, is not handed: it waits, and a day after it fell due it is used
as expired, as any occurrence. Neither the copies' paths nor a picture reach a log, the journal or diagnostics.
"""
from __future__ import annotations

import secrets

from codex_auto_resume import continuation
from codex_auto_resume.domain import ids
from codex_auto_resume.domain.plug import DEFER, Alternative

from .. import images as copies
from ..vocabulary import Measurement, PromptEvery, PromptReason, PromptState, PromptTrigger, RecordState, WhileRunning
from .markerfree import MarkerFreeContinuation

CAPABILITY = "prompt_queue"
LONG = "long_reset_message"
SHORT_LIMIT = 2000
DUE_FOR = 86400
# How far apart a series' occurrences fall (state/prompts.PERIODS, which the state's moves read the same way).
PERIODS = {PromptEvery.DAY: 86400, PromptEvery.WEEK: 7 * 86400}


def handed(row) -> dict | None:
    """What core is handed of one prompt's occurrence (P2: plughands.records_of), or None for one not to hand."""
    key = row.get("record_id")
    if key is None or row["state"] not in (PromptState.READY,):
        return None
    own = {"record_id": key, "thread_id": row["thread_id"], "marker": ids.short_marker(key), "purpose": "message",
           "ordinal": None}
    if row["record_state"] == RecordState.IN_FLIGHT:
        return dict(own, state="in_flight", words=None, sent_at=row.get("sent_at") or row.get("launching_at"),
                    queue_id=row.get("queue_id"), withdraw=bool(row.get("withdraw")))
    if row["record_state"] == RecordState.WAITING and row["words"]:
        return dict(own, state="waiting", words=row["words"], sent_at=None, queue_id=None, withdraw=False)
    return None


def turn_in_progress(paths, thread_id):
    """Whether conversation `thread_id`'s latest turn is in progress now (v0.6.19, #50): True, False for one that is
    final or no turn at all, or None where that cannot be read - read-only, from Codex's turn history (codex/turns.py)
    of the home the watcher drives (codex/inuse.py)."""
    from ..codex import inuse
    from ..codex.turns import Turns
    try:
        latest = Turns(inuse.home(paths)).latest(thread_id)
    except Exception:
        return None
    return latest is not None and latest.status == "inProgress"


def holds_for_turn(paths, row):
    """Whether `row`, a prompt that waits while a turn runs, is held now (#50): its conversation's latest turn in
    progress (True), or that unreadable (None - unknown never sends); False for one that goes into Codex's queue, or
    whose conversation has no turn running."""
    if row.get("while_running") != WhileRunning.WAIT:
        return False
    running = turn_in_progress(paths, row["thread_id"])
    return True if running is None else running


def _ours(record) -> bool:
    """Whether `record` is a record of this edition's own (P2) - a record id and no interruption id."""
    return isinstance(record, dict) and isinstance(record.get("record_id"), str) and "interruption_id" not in record


class ImageChannel(MarkerFreeContinuation):
    """The one call a message with pictures goes by (v0.6.20, MIMG): thread/queue/add with its words, then a localImage
    item for each copy in order, under its client id - over a session restricted to this capability's one method
    (codex/protocol.CAPABILITY_METHODS)."""
    __slots__ = ("images",)

    def __init__(self, paths, images, *, session=None):
        super().__init__(paths, session=session)
        self.images = tuple(images)

    def _input(self, prompt):
        return [{"type": "text", "text": prompt}] + [{"type": "localImage", "path": path} for path in self.images]

    def _session(self):
        if self._open is not None:
            return self._open()
        from ..codex import inuse
        from ..codex.protocol import Session
        return Session(inuse.backend(self.paths), capability=CAPABILITY)


def words_problem(words, long_on) -> bool:
    """Whether `words` are no message of a person's that core sends: empty, product text, a marker, or longer than
    2,000 characters while Longer messages is off (what one continuation carries while it is on)."""
    try:
        continuation.validate_prompt(words)
    except Exception:
        return True
    return not long_on and len(words) > SHORT_LIMIT


class PromptQueue:
    """The capability's code: its hook at P2. `bind` gives it its view of the state (state.Scoped)."""
    __slots__ = ("paths", "_scoped", "_session")

    def __init__(self, paths, *, session=None):
        self.paths = paths
        self._scoped = None
        self._session = session

    def bind(self, scoped):
        self._scoped = scoped

    def records(self, view):
        """P2: each conversation's first prompt still to go, made due and handed with its words where it is due."""
        scoped = self._scoped
        if scoped is None:
            return DEFER
        handle = scoped.prompts
        if not handle.on():
            return DEFER
        try:
            rows = handle.prompts(pending=None)
        except Exception:
            return DEFER
        now = handle.now()
        self._sweep(rows)
        long_on = scoped.armed(LONG)
        found, by_thread = [], {}
        for row in rows:
            by_thread.setdefault(row["thread_id"], []).append(row)
        for thread, queue in by_thread.items():
            try:
                record = self._first(handle, view, thread, queue, now, long_on)
            except Exception:
                continue
            if record is not None:
                found.append(record)
        return found or DEFER

    def watched_due(self, view):
        """While watched (v0.6.16-beta.3, runtime.Runtime._watched_records): the prompt id of each conversation's first
        prompt still to go that `_first` would make due and hand now, decided from the stored rows alone - nothing is
        written, cancelled, held, caught up or made due."""
        scoped = self._scoped
        if scoped is None:
            return []
        handle = scoped.prompts
        rows = handle.prompts(pending=None)
        now = handle.now()
        long_on = scoped.armed(LONG)
        found, by_thread = [], {}
        for row in rows:
            by_thread.setdefault(row["thread_id"], []).append(row)
        for thread, queue in by_thread.items():
            pending = [row for row in queue if row["state"] in (PromptState.WAITING, PromptState.READY)]
            if not pending or pending[0]["record_state"] == RecordState.IN_FLIGHT:
                continue
            row = pending[0]
            if view.thread_enabled(thread) is False or row["words"] is None or words_problem(row["words"], long_on):
                continue
            if row["depends"]:
                before = [other for other in queue if other["position"] < row["position"]]
                last = before[-1] if before else None
                if last is not None and (last["state"] in (PromptState.WAITING, PromptState.READY, PromptState.HELD)
                                         or last["reason"] != PromptReason.DELIVERED):
                    continue
            due = row["due_at"] if row["due_at"] is not None else now
            if now >= due and not holds_for_turn(self.paths, row):
                found.append("%s:%d" % (row["prompt_id"], int(due)))
        return found

    def _first(self, handle, view, thread, queue, now, long_on):
        """The record to hand of `thread`'s first prompt still to go, or None."""
        pending = [row for row in queue if row["state"] in (PromptState.WAITING, PromptState.READY,
                                                            PromptState.HELD)]
        if not pending:
            return None
        row = pending[0]
        if row["state"] == PromptState.HELD or row["record_state"] == RecordState.IN_FLIGHT:
            return None                                  # held for the person, or core's to watch (runtime.records)
        if view.thread_enabled(thread) is False:
            handle.end(PromptReason.CONVERSATION_OFF, thread_id=thread)
            return None
        if row["words"] is None or words_problem(row["words"], long_on):
            handle.change(row["prompt_id"], state=PromptState.CANCELLED, reason=PromptReason.TOO_LONG,
                          finished_at=now)
            return None
        if row["state"] == PromptState.READY:
            if row["due_at"] is not None and now - row["due_at"] >= DUE_FOR:
                return self._expired(handle, row, now)
            if self._held_for_turn(handle, row) or self._images_held(row):
                return None
            return handed(row)
        if row["depends"]:
            before = [other for other in queue if other["position"] < row["position"]]
            last = before[-1] if before else None
            if last is not None and last["state"] in (PromptState.WAITING, PromptState.READY, PromptState.HELD):
                return None
            if last is not None and last["reason"] != PromptReason.DELIVERED:
                handle.change(row["prompt_id"], state=PromptState.HELD, reason=PromptReason.DEPENDENCY_FAILED)
                self._count("held")
                return None
        due = row["due_at"] if row["due_at"] is not None else now
        if now < due:
            return None
        if self._held_for_turn(handle, row) or self._images_held(row):
            if row["trigger"] != PromptTrigger.RECURRING and now - due >= DUE_FOR:
                return self._expired(handle, row, now)
            return None
        if row["trigger"] == PromptTrigger.RECURRING:
            due = self._catch_up(handle, row, due, now)
            if due is None:
                return None
        key = secrets.token_hex(32)
        if not handle.occur(row["prompt_id"], key, thread, due):
            return None
        self._count("due")
        fresh = handle.prompt(row["prompt_id"])
        return handed(fresh) if fresh is not None else None

    def _images_held(self, row) -> bool:
        """Whether `row`'s pictures keep it from being handed this tick (v0.6.20): a copy no longer sendable, or MIMG
        failed on the Codex in force. False for a message with none."""
        found = copies.of(self.paths, row["prompt_id"])
        if not found:
            return False
        try:
            failed = self._scoped.failed(Measurement.MIMG)
        except Exception:
            failed = False
        return failed is True or copies.problem(self.paths, row["prompt_id"])

    def _sweep(self, rows) -> None:
        """Every copy whose prompt is no longer still to go removed (images.sweep) - at start, and after each
        delivery, cancel and end."""
        pending = [row["prompt_id"] for row in rows if row["state"] in (PromptState.WAITING, PromptState.READY,
                                                                        PromptState.HELD)]
        try:
            copies.sweep(self.paths, pending)
        except Exception:
            pass

    def images_of(self, record) -> list:
        """The copies' paths of the message whose occurrence is `record`, in order - [] for a record that is no prompt's
        still to go, or one with no pictures."""
        if not _ours(record) or self._scoped is None:
            return []
        try:
            rows = self._scoped.prompts.prompts(pending=True)
        except Exception:
            return []
        for row in rows:
            if row.get("record_id") == record["record_id"]:
                return [image["path"] for image in copies.of(self.paths, row["prompt_id"])]
        return []

    def sender(self, record, backend):
        """P5 (v0.6.20): the picture channel for an occurrence of a message with pictures, and nothing for anything
        else - a message with none goes through core's backend with its marker, as before."""
        found = self.images_of(record)
        return ImageChannel(self.paths, found, session=self._session) if found else DEFER

    def delivery(self, record):
        """P15 (v0.6.20): no marker for a message with pictures; core proves it by the client id it derives."""
        return Alternative.CLIENT_ID if self.images_of(record) else DEFER

    def _held_for_turn(self, handle, row) -> bool:
        """Whether `row` waits for its conversation's running turn this tick (#50, holds_for_turn): its reason says so
        where the turn is known to run."""
        if row.get("while_running") != WhileRunning.WAIT:
            return False
        running = turn_in_progress(self.paths, row["thread_id"])
        if running is True and row["reason"] != PromptReason.TURN_RUNNING:
            handle.change(row["prompt_id"], reason=PromptReason.TURN_RUNNING)
        return running is not False

    def _catch_up(self, handle, row, due, now):
        """A series' latest occurrence that fell, the earlier ones that fell while nothing ran counted as used
        (`missed`): when that one is due, or None where the series ended."""
        period = PERIODS[row["every"]]
        late = int((now - due) // period)
        if late <= 0:
            return due
        used = min(row["sent_count"] + late, row["occurrences"])
        latest = due + late * period
        if used >= row["occurrences"] or (row["until"] is not None and latest > row["until"]):
            handle.change(row["prompt_id"], state=PromptState.DONE, reason=PromptReason.MISSED, sent_count=used,
                          finished_at=now)
            self._count("missed")
            return None
        handle.change(row["prompt_id"], sent_count=used, due_at=latest)
        self._count("missed")
        return latest

    def _expired(self, handle, row, now):
        """An occurrence not sent a day after it fell due: used, as expired - a series waits for its next."""
        period = PERIODS.get(row["every"]) if row["trigger"] == PromptTrigger.RECURRING else None
        used = row["sent_count"] + 1
        following = None if period is None else row["due_at"] + period
        if following is None or used >= row["occurrences"] or (row["until"] is not None and following > row["until"]):
            handle.change(row["prompt_id"], state=PromptState.DONE, reason=PromptReason.EXPIRED, sent_count=used,
                          finished_at=now)
        else:
            handle.change(row["prompt_id"], state=PromptState.WAITING, reason=PromptReason.EXPIRED, sent_count=used,
                          record_id=None, due_at=following)
        self._count("expired")
        return None

    def _count(self, code) -> None:
        try:
            self._scoped.count(code)
        except Exception:
            pass


def make(paths) -> PromptQueue:
    """The capability's factory (registry.CapabilityDef.make): its code for one installation."""
    return PromptQueue(paths)
