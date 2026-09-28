"""How a continuation is carried, the last look before it goes, and what proves it arrived.

Core has always ended a continuation's words with the record's marker, and proven delivery by
finding that marker in Codex's history (A4). The edition's plug may ask for a continuation with no
marker instead (domain/plug.py, P15): the words go as they are, through the channel it named at
P5, under a client id core derives from the interruption (ids.continuation_client_id), and Codex
keeps that id on the message. `_delivery` takes that answer before the claim and writes the id
into the record; `proof` is what every look at a sent record is made for from then on - that id,
or the marker; and `presend_problem` is the last look, after the claim, made for it.

The standard edition's plug always defers, so every record it sends carries its marker and is
looked for by it, exactly as before.
"""
from __future__ import annotations

from ..domain import ids
from ..domain.plug import Alternative


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
