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

It answers for every send (v0.6.17, issue #42). A continuation queued for when its conversation is opened (P16's
QUEUE_FOR_OPEN) it carries too - with no marker, under its client id, left in the queue for the person to open - only
where MQO passed for the Codex in force: that such an item, taken when the conversation is opened, is found in
Codex's history by its client id, which is how core proves this delivery (`carries`). Unmeasured or failed, and for
a continuation sent to another Codex session (TO_SESSION), which MQO does not cover, it stands aside for that send:
core's backend carries it with its marker, and the runtime journals it as overruled, naming queue_for_open or
other_sessions and why (runtime.CONFLICTS). Every other send - a conversation the app holds - it serves as before.

Beside Continue with no words (v0.6.17, #47 P-6) it serves the sends that carry words, and that capability the routes:
core asks a route's P15 with the record saying `route`, where only SILENT is taken (runtime._takes), so this answer is
passed over there - a turn with no words carries no marker either.

Beside Several conversations at once (v0.6.17, #47 P-7) its sends may wait for their receipts on workers, each add in a
session of its own under its own client id (`pools`), where MQP passed on the Codex in force: that several such adds at
once are each accepted and each lands only in its own conversation. Unmeasured or failed, its sends go one at a time,
as before, and the runtime journals parallel_dispatch as overruled for them and why.

No test opens a real Codex: the tests give the channel a session over a fake app server, and the
live session is opened only by a watcher that has this capability armed.
"""
from __future__ import annotations

from contextlib import nullcontext
import uuid

from codex_auto_resume.domain import ids
from codex_auto_resume.domain.plug import Alternative

from ..codex import inuse
from ..codex.protocol import Session, SessionRefused, submitted
from ..vocabulary import ArmingWarning, Measurement

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
    __slots__ = ("paths", "_open", "_scoped")

    def __init__(self, paths, *, session=None):
        self.paths = paths
        self._open = session
        self._scoped = None

    def bind(self, scoped):
        """Its view of the state (state.Scoped): here, only whether a measurement passed or failed on the Codex in
        force."""
        self._scoped = scoped

    def carries(self, word):
        """Whether it can carry its send together with the P16 answer `word` taken for the same record (v0.6.17,
        runtime.CONFLICTS): True for QUEUE_FOR_OPEN where MQO passed on the Codex in force; otherwise why not, as the
        statement's warning words say it - MQO failed, or not measured (TO_SESSION: no measurement covers it)."""
        scoped = self._scoped
        if word == Alternative.QUEUE_FOR_OPEN and scoped is not None:
            try:
                if scoped.passed(Measurement.MQO):
                    return True
                if scoped.failed(Measurement.MQO):
                    return ArmingWarning.MEASUREMENT_FAILED
            except Exception:
                pass
        return ArmingWarning.UNMEASURED

    def sender(self, record, backend):
        """P5: this object is the channel. `backend` is core's stand-in, never core's backend."""
        return self

    def pools(self):
        """Whether its send may wait for its receipt on a worker beside others (core's plughands.Channel, P12;
        v0.6.17): True where MQP passed on the Codex in force - each send opens a session of its own (`_session`),
        as MQP's adds did; otherwise why not, as the statement's warning words say it - MQP failed, or not
        measured."""
        scoped = self._scoped
        if scoped is not None:
            try:
                if scoped.passed(Measurement.MQP):
                    return True
                if scoped.failed(Measurement.MQP):
                    return ArmingWarning.MEASUREMENT_FAILED
            except Exception:
                pass
        return ArmingWarning.UNMEASURED

    def delivery(self, record):
        """P15: no marker; core derives the client id and proves delivery by it."""
        return Alternative.CLIENT_ID

    def send(self, thread_id, prompt, *, launch_guard=None, client_id=None):
        """Add `prompt` to `thread_id`'s queue under `client_id`, and say what came of it the way
        core's backend does: accepted (with the queued item's id when Codex gave one), unknown, or
        not started. Never raises.

        Without a client id - core sends the marker through a channel only when P15 was not
        taken for this send - the item is added under a fresh id of its own, and the marker in the
        words is what proves it, as it always was: codex-cli 0.163.0-alpha.10.2's schema makes
        `clientUserMessageId` required on thread/queue/add, and an add without it is refused (#49)."""
        if (not ids.is_uuid(thread_id) or not isinstance(prompt, str) or not prompt
                or len(prompt) > MAX_PROMPT or "\0" in prompt
                or not (client_id is None or ids.is_uuid(client_id))):
            return {"outcome": "not_started", "error_code": "queue_preflight_failed"}
        params = {"threadId": thread_id, "input": self._input(prompt),
                  "clientUserMessageId": client_id or str(uuid.uuid4())}
        session, opened, pending = None, False, None
        try:
            with launch_guard if launch_guard is not None else nullcontext(True) as permitted:
                if permitted is not True:
                    return {"outcome": "not_started", "error_code": "queue_consent_refused"}
                session = self._session()
                session.__enter__()
                opened = True
                # v0.6.18: the add written inside core's launch guard, with the session's start - a Pause or Cancel
                # that commits after the guard stops it; its answer awaited outside.
                pending = submitted(session, METHOD, params)
        except Exception:
            # No app server, none that would talk, or a guard that failed before the add: the call was never made, so
            # nothing can be in Codex. A guard that failed as it closed, after the add was written, is read as core's
            # queue launch is: its answer below, never an unsent attempt.
            if pending is None:
                if opened:
                    _close(session)
                return {"outcome": "not_started", "error_code": "queue_spawn_failed"}
        try:
            result = pending()
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

    def _input(self, prompt):
        """The add's `input`: the words alone (v0.6.20: the prompt queue's picture channel adds its pictures after them,
        engine/promptqueue.ImageChannel)."""
        return [{"type": "text", "text": prompt}]

    def _session(self):
        if self._open is not None:
            return self._open()
        return Session(inuse.backend(self.paths), capability=CAPABILITY)


def make(paths) -> MarkerFreeContinuation:
    """The capability's factory (registry.CapabilityDef.make): its code for one installation."""
    return MarkerFreeContinuation(paths)
