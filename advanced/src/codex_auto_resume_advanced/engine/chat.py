# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""Chat with a conversation from the Dashboard (v0.6.19, P2, P5 and P15; the owner's of 2026-10-02).

A person picks a conversation the Codex app has open on the Dashboard's Chat page, reads its last turns - their
messages and Codex's replies, read only while the page asks (codex/conversation.py) - and sends a message of up to
2,000 characters (control/chat.py). The message waits in the state (state/chat.py) until core takes it:

* P2 - each conversation's oldest waiting message is handed core as a person's MESSAGE record; core carries it out
  as it carries out every record of the edition's own - its gates (the app holds the conversation, nothing of core's
  in flight, consent, usage), the one claim, the last look, the one send - and follows it (engine/plugrecords.py).
* P5 and P15 - for that record this is the channel and the answer is CLIENT_ID: the words go into the conversation
  exactly as typed, with no marker, through `thread/queue/add` under the client id core derives from the record's id
  (MC1: it shows at once as the person's own message and runs), and core proves it by that id
  (engine/recordchannel.py).
* Its pace is its own (A20): one in flight in a conversation across both stores, thirty a conversation and sixty a
  day, never core's five a day or fifteen minutes (state/records.claim_record).
* Its words leave the disk the moment its send begins (state/chat.py); a message Codex did not take within three
  minutes is taken back and never sent again by itself; turned off, every message still waiting is cancelled.

Approvals are still answered in Codex: what MC2 measured shows a turn in progress and finished, never a wait for one.
"""
from __future__ import annotations

from codex_auto_resume.domain import ids
from codex_auto_resume.domain.plug import DEFER, Alternative

from ..vocabulary import ChatState
from .markerfree import MarkerFreeContinuation

CAPABILITY = "codex_chat"
WORDS = 2000


def handed(row) -> dict | None:
    """What core is handed of one message (P2: plughands.records_of), or None for one not to hand."""
    key = row.get("record_id")
    if not (isinstance(key, str) and len(key) == 64):
        return None
    own = {"record_id": key, "thread_id": row["thread_id"], "marker": ids.short_marker(key), "purpose": "message",
           "ordinal": None}
    if row["state"] == ChatState.IN_FLIGHT:
        return dict(own, state="in_flight", words=None, sent_at=row.get("sent_at"), queue_id=None, withdraw=False)
    if row["state"] == ChatState.WAITING and row.get("words"):
        return dict(own, state="waiting", words=row["words"], sent_at=None, queue_id=None, withdraw=False)
    return None


# How long Codex has to take a message it holds in its queue before it is taken back (A6: never sent again by itself).
TAKEN_WITHIN = 180


def watched(row, now) -> dict | None:
    """A message in flight as core watches it: asked back out of Codex's queue once TAKEN_WITHIN has passed."""
    record = handed(row)
    if record is not None and record["sent_at"] is not None and now - record["sent_at"] >= TAKEN_WITHIN:
        record["withdraw"] = True
    return record


def _ours(record) -> bool:
    """Whether `record` is a record of this edition's own (P2) - a record id and no interruption id - which is the only
    kind a chat message is; a recovery of core's never is."""
    return isinstance(record, dict) and "record_id" in record and "interruption_id" not in record


class Channel(MarkerFreeContinuation):
    """The one call a chat message goes by: thread/queue/add with its client id, over a session restricted to this
    capability's methods (codex/protocol.CAPABILITY_METHODS)."""
    __slots__ = ()

    def _session(self):
        if self._open is not None:
            return self._open()
        from ..codex import inuse
        from ..codex.protocol import Session
        return Session(inuse.backend(self.paths), capability=CAPABILITY)


class CodexChat:
    """The capability's code: its hooks at P2, P5 and P15. `bind` gives it its view of the state (state.Scoped)."""
    __slots__ = ("paths", "_scoped", "channel")

    def __init__(self, paths, *, session=None):
        self.paths, self._scoped = paths, None
        self.channel = Channel(paths, session=session)

    def bind(self, scoped):
        self._scoped = scoped

    def records(self, view):
        """P2: each conversation's oldest waiting message, and those in flight - for core to try or to watch."""
        scoped = self._scoped
        if scoped is None:
            return DEFER
        try:
            rows = scoped.chat.pending()
        except Exception:
            return DEFER
        found, seen = [], set()
        for row in rows:
            if row["state"] == ChatState.WAITING and view.thread_enabled(row["thread_id"]) is False:
                try:
                    scoped.chat.conversation_off(row["record_id"])
                except Exception:
                    pass
                continue
            if row["state"] == ChatState.WAITING and row["thread_id"] in seen:
                continue
            seen.add(row["thread_id"])
            record = handed(row)
            if record is not None:
                found.append(record)
        return found or DEFER

    def sender(self, record, backend):
        """P5: the channel, for a message of its own - and nothing for anything else: a recovery of core's, or any
        record of another capability's, goes as it would with chat off (the runtime asks this only for a chat
        message, runtime._own_record_answer; this holds it even where it is asked otherwise)."""
        return self.channel if _ours(record) else DEFER

    def delivery(self, record):
        """P15: no marker for a message of its own; core proves it by the client id it derives from the record's id."""
        return Alternative.CLIENT_ID if _ours(record) else DEFER


def make(paths) -> CodexChat:
    """The capability's factory (registry.CapabilityDef.make): its code for one installation."""
    return CodexChat(paths)
