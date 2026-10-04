"""How a continuation is carried, the last look before it goes, and what proves it arrived.

Core has always ended a continuation's words with the record's marker, and proven delivery by
finding that marker in Codex's history (A4). The edition's plug may ask for a continuation with no
marker instead (domain/plug.py, P15): the words go as they are, through the channel it named at
P5, under a client id core derives from the interruption (ids.continuation_client_id), and Codex
keeps that id on the message. `_delivery` takes that answer before the claim and writes the id
into the record; `proof` is what every look at a sent record is made for from then on - that id,
or the marker; and `presend_problem` is the last look, after the claim, made for it.

A conversation the app does not hold is the other way a continuation can be carried (P16). Core
has always waited for the app to open it (A11); the plug may name a route instead, and
`_unloaded` takes it where core would wait, once every gate before that one has passed. The gates
after it are the ones a send passes, and `_resume_unloaded` carries the route out as `dispatch`
carries out a send: the one claim - which the plug's ledger pays for - the pre-send look, and the
route called once inside the launch guard, handed core's own look at whether the app still does
not hold the conversation, for it to ask at the last moment before it changes anything in Codex.
Nothing is queued, so nothing is watched: a route that
did what it was asked leaves the record waiting again with its claim counted (the cooldown, the
day's five and the chain), one that never started gives the claim back, and anything else is an
uncertain submission, never tried again, exactly as a send's is.

The standard edition's plug always defers, so every record it sends carries its marker and is
looked for by it, and one the app does not hold waits for it, exactly as before.
"""
from __future__ import annotations

from .. import continuation as _message, machine
from ..domain import ids
from ..domain.plug import DEFER, Alternative, Point


class DeliveryMixin:
    @staticmethod
    def proof(row):
        """What proves a continuation of `row` is ours: the client id a marker-free one was queued
        under, or else its marker.

        Which it is is written in the record itself, before the claim, by the one dispatch that
        chose it (`_delivery`): a record queued with no marker keeps the client id it was derived
        (ids.continuation_client_id) as its `recovery_client_id`. No id Codex gives a message is
        ever that one, so a record the standard edition sent - whatever client id Codex gave it -
        is looked for by its marker, as it always was; and a record sent with no marker is still
        followed by that id once the plug that chose it is gone."""
        client = row.get("recovery_client_id")
        if client is not None and client == ids.continuation_client_id(row["interruption_id"]):
            return client
        return row["marker"]

    def _delivery(self, row, sender):
        """P15: the client id a continuation of `row` is sent under with no marker, or None for
        the marker, as core has always sent it.

        Taken only for a send handed to the plug's channel: core's own backend is `codex queue`,
        which takes no client id, so through it the marker always goes. What is taken is written
        into the record before the claim - its `recovery_client_id` (`proof`) -
        so every look that follows the send is made for that id, whatever becomes of the plug
        that chose it; and a record that goes by its marker again, after a marker-free send was
        given back unsent, has that id taken away first. The standard edition's plug always
        defers, and its records never hold that id, so it writes nothing here."""
        answer = self.plug.delivery(row)
        derived = ids.continuation_client_id(row["interruption_id"])
        client = derived if answer is Alternative.CLIENT_ID and sender is not self.backend else None
        if client is not None and row.get("recovery_client_id") != client:
            self.store.update(row["interruption_id"], at=self.clock(), recovery_client_id=client)
        elif client is None and row.get("recovery_client_id") == derived:
            self.store.update(row["interruption_id"], at=self.clock(), recovery_client_id=None)
        return client

    def presend_problem(self, claim):
        """The last look before the queue process starts. Returns (target, reason,
        delay) to give the claim back, or None to send.

        Anything that changed since the gates ran - a cancel, a Pause, a disabled
        thread, a newer turn, somebody else's queued message, another copy of our
        marker - is caught here, where giving the claim back is still proven safe.
        A marker-free continuation is looked for by its client id (`proof`), and by its
        marker as well: one with the marker already there is the same continuation.
        """
        poll = self.options["state_poll_seconds"]
        if claim is None or claim["state"] != "submitting" or claim["queue_id"] is not None:
            return "waiting_retry", "released_before_send", poll
        if claim["cancel_requested"]:
            return "cancelled", "user_cancelled", 0
        now = self.clock()
        if (not self.allowed(claim) or (claim.get("not_before") or 0) > now    # schema 4's, and
                or self.quiet_until(now) is not None):                         # quiet hours
            return self.waiting_state(claim), "released_before_send", poll
        if not self.valid_interruption(claim):
            state, reason = self.supersede_reason(claim)
            return state, reason, 0
        if self._projection_now(claim["thread_id"]) is not True:
            return "waiting_for_loaded_thread", "projection_stale", poll
        proof = self.proof(claim)
        if self.source.foreign_queued(claim["thread_id"], proof):
            return "waiting_retry", "user_input_queued", poll
        for token in dict.fromkeys((proof, claim["marker"])):
            presence = self.source.marker_presence(claim["thread_id"], token)
            if presence.get("history") or presence.get("queue"):
                return "superseded", "duplicate_owner", 0
        if not self.home_lock():
            return "waiting_for_app", "home_lock_unavailable", poll
        return None

    def _plugged_text(self, row, message, limits) -> tuple:
        """P4: (the plug's words for this continuation, True), or (core's own `message`, False).

        Taken only as a person's Custom message is: they pass the same validator and are filled
        in the same way, for the same record, so they can say nothing a person could not have
        written in the Dashboard - over a conversation's own message too (v0.6.11). Words that fail
        the validator, or fill in to nothing, are not sent, and core's are - the person's own
        style, not the Standard text a Custom message falls back to."""
        words = self.plug.text(row, message)
        if words is DEFER:
            return message, False
        try:
            _message.validate_custom(words)
            values = dict(self.policy_values, continuation_style="custom", custom_message_by_thread=None,
                          custom_message_mode="global", custom_message=words)
            if _message.source_for(row["category"], values, row=row, limits=limits) != "global":
                return message, False
            return _message.for_settings(row["category"], values, row=row, limits=limits), True
        except Exception:
            return message, False

    # --------------------------------------------------------------- a conversation not held (P16)
    def _unloaded(self, row, loaded, vector):
        """P16: the route the plug names for `row`, whose conversation the app does not hold, or
        None - core's own wait (A11).

        Asked only where core would wait for the app to open the conversation - it said notLoaded,
        not that it could not tell - and only once consent has passed, so observe only, a Pause, a
        conversation switched off and a cancel are never put to it. A route taken passes the
        thread_available gate with the word that says whose doing that is (machine.PLUGGED); the
        gates that follow are the ones any send passes."""
        if loaded != "notLoaded" or vector["consent"][0] != machine.PASS:
            return None
        route = self.plug.unloaded(row)
        if route is DEFER:
            return None
        vector["thread_available"] = machine.gate(machine.PASS, machine.PLUGGED)
        return route

    def _resume_unloaded(self, current, vector, limits, route, app, relaxed=None):
        """Carry out the route the plug named at P16, as `dispatch` carries out a send: the one
        claim, paid for by the plug's ledger (P11, told the route is what it carries); the pre-send
        look; and the route called once, inside the launch guard. Called under the dispatch lock,
        with the conversation still not held by the app `app` and usage still there (`dispatch`).

        The route is handed `still_unloaded`, core's look at the conversation made again when it
        is asked - never the cached one: the app `app` still there and saying notLoaded, and
        anything else, a look that fails included, is no. A route opens a session with Codex
        before it changes anything, which takes seconds, and the app may open the conversation in
        them; asked at the last moment, the look keeps the route from changing a conversation the
        app has just taken, and the route answers not started."""
        key = current["interruption_id"]
        at = self.clock()
        claimed, gate, reason = self.store.reserve_detailed(
            key, at, limits=limits, gates=vector, ledger=self.plug,
            carried=frozenset({Point.UNLOADED}) | self.relaxed_points(relaxed),
            quiet_until=self.quiet_until(at), relaxed=relaxed)
        if not claimed:
            self._refused(current, gate, reason)
            return
        self.moved(current, "submitting")
        claim = self.store.get(key)
        problem = self.presend_problem(claim)
        if problem is not None:
            target, why, delay = problem
            self._release(key, claim, target, why, delay)
            self.log(current["thread_id"], target, why)
            return
        thread_id = claim["thread_id"]

        def still_unloaded() -> bool:
            try:
                return (self.backend.app_identity() == app
                        and self.backend.loaded(thread_id, app) == "notLoaded")
            except Exception:
                return False
        try:
            response = route.resume(thread_id, launch_guard=self.store.submission_guard(key),
                                    still_unloaded=still_unloaded)
        except Exception:
            response = {"outcome": "unknown"}
        if not isinstance(response, dict):
            response = {"outcome": "unknown"}
        try:
            self._after_resume(current, response)
        except Exception:
            self.log(current["thread_id"], "post_send_bookkeeping_failed", None)

    def _after_resume(self, row, response):
        """What came of a route (P16). Accepted: nothing was queued, and the conversation goes on
        when the app opens it, so the record waits again - the claim still counted against the
        cooldown, the day's claims and the chain, never given back. Not started: the claim is given
        back, as for a send that never started, its time kept for the caps. Anything else may have
        changed Codex and nothing proves how: an uncertain submission, never tried again (A6)."""
        key = row["interruption_id"]
        reserved = self.store.get(key)
        outcome = response.get("outcome")
        poll = self.options["state_poll_seconds"]
        if outcome == "accepted":
            self.transition(reserved, "waiting_retry", "notLoaded", delay=poll, submitted_at=None)
        elif outcome == "not_started":
            refused = response.get("error_code") == "queue_consent_refused"
            target = ("cancelled" if refused and reserved["cancel_requested"]
                      else self.waiting_state(reserved))
            reason = "user_cancelled" if target == "cancelled" else "released_before_send"
            self._release(key, reserved, target, reason, poll)
            self.log(row["thread_id"], target, reason)
        else:
            self.transition(reserved, "submission_unknown", "queue_result_unknown_do_not_resend", delay=1)
