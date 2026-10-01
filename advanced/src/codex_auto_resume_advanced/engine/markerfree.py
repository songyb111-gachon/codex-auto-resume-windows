# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""Marker-free continuation: the advanced edition's answer at P5 and P15.

The standard edition sends every continuation with `codex queue` and ends its words with a short
marker, `[codex-auto-resume:<16 hex>]`, which is how it proves the message arrived and finds the
turn it started (A2, A4). This capability sends the words with no marker. Asked at P15 it answers
CLIENT_ID, and asked at P5 it names itself as the channel; core then derives a client id from the
interruption (ids.continuation_client_id - the same interruption, the same id), writes it into the
record before the claim, and hands this channel the words and that id for the one send. The
channel adds one item to the conversation's queue through Codex's own app server -
`thread/queue/add` with `clientUserMessageId`, the call measurement M7 made - and Codex keeps the
id on the message as `clientId`. That call changes Codex's state through its app server, which the
standard edition never asks it to (B3, B4), so the statement names those two standards as well
as A2 and A4. Core proves delivery by that id and by nothing else
(engine/delivery.py in core), and follows, takes back and settles the record by it exactly as it
does one with a marker.

What this code does not do is decide anything: every gate, the claim, the pre-send look and the
launch guard are core's, and so is what follows the send. Where the send cannot be proven - the
app server refuses the call, does not answer, or the item never shows - the answer here is
"unknown", and core holds the record as an uncertain submission, never sent again, exactly as it
holds one of `codex queue`'s; the tripwire for a paid send that went unknown turns this capability
off (arming.py). Only a failure before anything was asked of Codex - no app server could be
started, or the words are not ones core would send - is "not started", which core may retry.

No test opens a real Codex: the tests give the channel a session over a fake app server, and the
live session is opened only by a watcher that has this capability armed.
"""
from __future__ import annotations

from contextlib import nullcontext

from codex_auto_resume.domain import ids
from codex_auto_resume.domain.plug import Alternative

from ..codex import inuse
from ..codex.protocol import Session, SessionRefused

CAPABILITY = "marker_free_continuation"
METHOD = "thread/queue/add"
# What core's own send takes as one message (codex/transport.py), and so all this one takes.
MAX_PROMPT = 8192


def _queue_id(result):
    """The queued item's id in what thread/queue/add answered, where it says one in a shape this
    knows; None otherwise, and the watch finds the item by its client id instead."""
    if not isinstance(result, dict):
        return None
    found = [result.get("queuedSubmissionId"), result.get("id")]
    for name in ("queuedSubmission", "item"):
        nested = result.get(name)
        if isinstance(nested, dict):
            found.append(nested.get("id"))
    return next((value for value in found if ids.is_uuid(value)), None)


def _close(session):
    try:
        session.__exit__(None, None, None)
    except Exception:
        pass


class MarkerFreeContinuation:
    """The capability's code: its hooks at P5 and P15, and the channel core sends through.

    `session` is a factory for the app-server session the one call is made in; None opens a live
    one against the Codex the watcher drives (codex/inuse.py), restricted to this capability's one
    method (codex/protocol.CAPABILITY_METHODS)."""
    __slots__ = ("paths", "_open")

    def __init__(self, paths, *, session=None):
        self.paths = paths
        self._open = session

    def sender(self, record, backend):
        """P5: this object is the channel. `backend` is core's stand-in, never core's backend."""
        return self

    def delivery(self, record):
        """P15: no marker; core derives the client id and proves delivery by it."""
        return Alternative.CLIENT_ID

    def send(self, thread_id, prompt, *, launch_guard=None, client_id=None):
        """Add `prompt` to `thread_id`'s queue under `client_id`, and say what came of it the way
        core's backend does: accepted (with the queued item's id when Codex gave one), unknown, or
        not started. Never raises.

        Without a client id - core sends the marker through a channel only when P15 was not
        taken for this send - the item is added with no id, and the marker in the words is what
        proves it, as it always was."""
        if (not ids.is_uuid(thread_id) or not isinstance(prompt, str) or not prompt
                or len(prompt) > MAX_PROMPT or "\0" in prompt
                or not (client_id is None or ids.is_uuid(client_id))):
            return {"outcome": "not_started", "error_code": "queue_preflight_failed"}
        params = {"threadId": thread_id, "input": [{"type": "text", "text": prompt}]}
        if client_id is not None:
            params["clientUserMessageId"] = client_id
        session, opened = None, False
        try:
            with launch_guard if launch_guard is not None else nullcontext(True) as permitted:
                if permitted is not True:
                    return {"outcome": "not_started", "error_code": "queue_consent_refused"}
                session = self._session()
                session.__enter__()
                opened = True
        except Exception:
            # No app server, none that would talk, or a guard that failed: the call was never
            # made, so nothing can be in Codex.
            if opened:
                _close(session)
            return {"outcome": "not_started", "error_code": "queue_spawn_failed"}
        try:
            result = session.call(METHOD, params)
        except SessionRefused:
            return {"outcome": "not_started", "error_code": "queue_preflight_failed"}
        except Exception as exc:
            # Refused, or no answer in time: asked, and nothing proves what came of it.
            timed_out = str(exc) == "protocol_timeout"
            return {"outcome": "unknown",
                    "error_code": "queue_timeout" if timed_out else "queue_result_unknown"}
        finally:
            _close(session)
        return {"outcome": "accepted", "queue_id": _queue_id(result)}

    def _session(self):
        if self._open is not None:
            return self._open()
        return Session(inuse.backend(self.paths), capability=CAPABILITY)


def make(paths) -> MarkerFreeContinuation:
    """The capability's factory (registry.CapabilityDef.make): its code for one installation."""
    return MarkerFreeContinuation(paths)
