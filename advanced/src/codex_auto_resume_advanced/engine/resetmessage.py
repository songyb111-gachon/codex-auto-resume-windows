# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""A message of a person's own, sent to the conversation they picked when the window they picked resets
(v0.6.14): reset_message, at P8, P2 and P3.

The standard edition sends one thing of its own: a continuation, from its own templates or the Custom
message, for a recovery that is due (A26, C4). With this on, a person writes a message in the Dashboard
for one conversation that is switched on, and picks an occasion - "when the next 5-hour limit resets",
"the 3rd reset from now", "when the weekly limit resets" (engine/resetwatch.py) - and when that window
resets, core sends it, once, as it sends its own continuations: through its gates, its one claim and its
one send, with the record's marker after a blank line (engine/plugrecords.py, P2). It goes exactly as
typed: nothing is filled in, and it is at most 2,000 characters unless Longer reset messages is on
(A27's bound, departed from only there).

* P8, the errand: the usage windows counted - core's own reading, and this edition's where one is due -
  and the rules adopted (engine/resetwatch.py).
* P2: first the windows closed by time, with no reading, so a message is due at the very tick its window
  closes; then every message due is handed core with its words, and every one in flight, to be watched.
  One whose conversation was switched off is cancelled (H5); one unsent eight days after it was written,
  or a day after it fell due, has expired. Either way its words go.
* P3 `usage`: a core record of the same conversation is held while one of its messages is due or in
  flight, and while one counts for the very reset that record waits for - so when a continuation and the
  person's message wait for the same reset, only the message is sent, in the continuation's place (the
  owner's answer); a newer user turn then supersedes core's record (A17).

The runtime keeps what core tells it at P14 (runtime.py): sent, the words are gone; delivered, done;
unproven a day after it was sent, done as unknown, and the capability turns itself off (K7). The words
leave the disk at the send's start, at a cancel, at expiry and when the capability stands anywhere but on
(arming.py, sweep); the file refuses words on a finished rule (state/schema.py). They never reach a log,
the journal, diagnostics, a notification, the status, MCP or a golden.
"""
from __future__ import annotations

from codex_auto_resume import failures
from codex_auto_resume.domain import ids
from codex_auto_resume.domain.plug import DEFER, Alternative

from ..codex import credits
from ..vocabulary import Measurement, RecordState, RuleReason, RuleState
from . import resetwatch
from .resetwatch import TOL, Watch

CAPABILITY = "reset_message"
LONG = "long_reset_message"
# A message's words, at most: A27's 2,000 characters, unless Longer reset messages is on.
SHORT_LIMIT = 2000
# How long one waits to be sent, at most: eight days from when it was written, a day from when it fell due.
KEEP_FOR = 8 * 86400
DUE_FOR = 86400
USAGE = "usage"


class _Errand:
    __slots__ = ("code", "view")

    def __init__(self, code, view):
        self.code, self.view = code, view

    def run(self, guard):
        return self.code.look(self.view)


def handed(rule) -> dict | None:
    """What core is handed of one message (P2: plughands.records_of), or None for one not to hand."""
    key = rule["record_id"]
    if rule["record_state"] == RecordState.IN_FLIGHT:
        return {"record_id": key, "thread_id": rule["thread_id"], "marker": ids.short_marker(key),
                "state": "in_flight", "words": None, "sent_at": rule["sent_at"]}
    if rule["state"] == RuleState.READY and rule["record_state"] == RecordState.WAITING and rule["words"]:
        return {"record_id": key, "thread_id": rule["thread_id"], "marker": ids.short_marker(key),
                "state": "waiting", "words": rule["words"], "sent_at": None}
    return None


class ResetMessage:
    """The capability's code: its hooks at P8, P2 and P3. `bind` gives it its view of the state."""
    __slots__ = ("paths", "_scoped", "_open")

    def __init__(self, paths, *, session=None):
        self.paths = paths
        self._scoped = None
        self._open = session

    def bind(self, scoped):
        self._scoped = scoped

    def _watch(self, reader=None):
        scoped = self._scoped
        return Watch(scoped.resets, scoped.now, reader=reader, early=not scoped.failed(Measurement.MU),
                     light=scoped.passed(Measurement.MU), keep_credits=False)

    # ------------------------------------------------------------------ P8
    def tick(self, view):
        scoped = self._scoped
        if scoped is None:
            return DEFER
        try:
            pending = scoped.resets.reset_rules(capability=CAPABILITY)
        except Exception:
            return DEFER
        return _Errand(self, view) if pending else DEFER

    def look(self, view):
        """The errand: one look of the tracker's, this edition's own reading made where it is due."""
        if not self._scoped.resets.on():
            return None
        opened = []

        def reader(params):
            session = self._session()
            session.__enter__()
            opened.append(session)
            return session.call(credits.READ, params)
        try:
            looked = self._watch(reader).step(view)
        finally:
            for session in opened:
                try:
                    session.__exit__(None, None, None)
                except Exception:
                    pass
        for events in looked["events"].values():
            for event in events:
                if event in ("gap", "gone"):
                    self._count(event)
        return None

    # ------------------------------------------------------------------ P2
    def records(self, view):
        """P2: the windows closed by time first, then every message due, with its words, and every one in
        flight. Those whose conversation is off, and those that waited too long, end here."""
        scoped = self._scoped
        if scoped is None:
            return DEFER
        handle = scoped.resets
        rows = self._watch().by_time()
        now = scoped.now()
        found = []
        for rule in handle.reset_rules(capability=CAPABILITY):
            if rule["record_state"] == RecordState.IN_FLIGHT:
                if rule["words"] is not None and rule["launching_at"] is not None:
                    # Sent, by its launch, though the move that said so was not written: its words go now.
                    handle.change_rule(rule["rule_id"], expect=RuleState.READY, sent_at=rule["launching_at"])
                    rule = dict(rule, sent_at=rule["launching_at"])
                handed_ = handed(rule)
                if handed_ is not None:
                    found.append(handed_)
                continue
            ended = self._ended(rule, view, now)
            if ended is not None:
                handle.end_rule(rule["rule_id"], *ended)
                if ended[1] == RuleReason.EXPIRED:
                    self._count("expired")
                continue
            row = rows.get((rule["bucket"], rule["minutes"]))
            if resetwatch.due(rule, row):
                handle.change_rule(rule["rule_id"], expect=RuleState.COUNTING, state=RuleState.READY, due_at=now)
                rule = dict(rule, state=RuleState.READY, due_at=now)
                self._count("due")
            handed_ = handed(rule)
            if handed_ is not None:
                found.append(handed_)
        return found or DEFER

    def _ended(self, rule, view, now):
        """(state, reason) a message not yet sent ends with now, or None."""
        try:
            on = view.thread_enabled(rule["thread_id"])
        except Exception:
            on = True                                    # what cannot be read cancels nothing
        if on is False:
            return RuleState.CANCELLED, RuleReason.CONVERSATION_OFF
        if now - rule["created_at"] >= KEEP_FOR or (rule["due_at"] is not None and now - rule["due_at"] >= DUE_FOR):
            return RuleState.DONE, RuleReason.EXPIRED
        if rule["words"] is not None and len(rule["words"]) > SHORT_LIMIT and not self._scoped.armed(LONG):
            return RuleState.CANCELLED, RuleReason.TURNED_OFF
        return None

    # ------------------------------------------------------------------ P3
    def gate(self, name, record, facts):
        """P3 `usage`: HOLD a core record of a conversation one of these messages is due or in flight in -
        or one that counts for the very reset this usage-limit record waits for. DEFER otherwise."""
        scoped = self._scoped
        if name != USAGE or scoped is None or not isinstance(record, dict):
            return DEFER
        thread = record.get("thread_id")
        try:
            rules = [rule for rule in scoped.resets.reset_rules(capability=CAPABILITY) if rule["thread_id"] == thread]
            rows = scoped.resets.windows() if rules else {}
        except Exception:
            return DEFER
        for rule in rules:
            if rule["state"] == RuleState.READY or rule["record_state"] == RecordState.IN_FLIGHT:
                return Alternative.HOLD
            if self._same_reset(rule, rows.get((rule["bucket"], rule["minutes"])), record):
                return Alternative.HOLD
        return DEFER

    @staticmethod
    def _same_reset(rule, row, record) -> bool:
        """Whether a counting message falls due at the reset a usage-limit record of core's waits for: its
        next reset is its occasion, and the window open now resets when the record's reset is."""
        reset_at = record.get("reset_at")
        if (rule["state"] != RuleState.COUNTING or rule["base"] is None or row is None
                or record.get("category") != failures.USAGE_LIMIT or not isinstance(reset_at, (int, float))
                or row["open_reset_at"] is None):
            return False
        return (row["resets"] + 1 >= rule["base"] + rule["ordinal"]
                and abs(reset_at - row["open_reset_at"]) <= TOL)

    # ------------------------------------------------------------------ helpers
    def _count(self, code) -> None:
        try:
            self._scoped.count(code)
        except Exception:
            pass

    def _session(self):
        if self._open is not None:
            return self._open()
        from ..codex import inuse
        from ..codex.protocol import Session
        return Session(inuse.backend(self.paths), capability=CAPABILITY)


def make(paths) -> ResetMessage:
    """The capability's factory (registry.CapabilityDef.make): its code for one installation."""
    return ResetMessage(paths)


class LongMessages:
    """Longer reset messages (registry.LONG_RESET_MESSAGE), an action: nothing of it runs. While it stands on,
    reset_message takes a message up to what one continuation carries (continuation.PROMPT_LIMIT) instead of
    2,000 characters, and when it is turned off every waiting message longer than that is cancelled (P2)."""
    __slots__ = ("paths",)

    def __init__(self, paths):
        self.paths = paths


def make_long(paths) -> LongMessages:
    return LongMessages(paths)
