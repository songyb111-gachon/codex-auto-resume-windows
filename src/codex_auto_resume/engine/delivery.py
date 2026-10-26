"""How a continuation is carried, the last look before it goes, and what proves it arrived.

Core has always ended a continuation's words with the record's marker, and proven delivery by
finding that marker in Codex's history (A4). The edition's plug may ask for a continuation with no
marker instead (domain/plug.py, P15): the words go as they are, through the channel it named at
P5, under a client id core derives from the interruption (ids.continuation_client_id), and Codex
keeps that id on the message. `_delivery` takes that answer before the claim and writes the id
into the record; `proof` is what every look at a sent record is made for from then on - that id,
or the marker; and `presend_problem` is the last look, after the claim, made for it.

A conversation the app does not hold is the other way a continuation can be carried (P16): engine/routes.py.

The standard edition's plug always defers, so every record it sends carries its marker and is
looked for by it, and one the app does not hold waits for it, exactly as before.
"""
from __future__ import annotations

from .. import continuation as _message, failures
from ..domain import ids
from ..domain.plug import DEFER, Alternative, Point
from ..machine import CLAIMED, WAITING
from .options import backoff_delay


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

    def _delivery(self, row, sender, resend=False):
        """P15: the client id a continuation of `row` is sent under with no marker, or None for
        the marker, as core has always sent it - or, for a `resend` (engine/resend.py), False where
        it would not carry the proof its first send did: the derived id through a channel for one
        sent with no marker, the marker for one sent with it. A resend writes nothing here.

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
        if resend:
            return client if (client is not None) == (self.proof(row) != row["marker"]) else False
        if client is not None and row.get("recovery_client_id") != client:
            self.store.update(row["interruption_id"], at=self.clock(), recovery_client_id=client)
        elif client is None and row.get("recovery_client_id") == derived:
            self.store.update(row["interruption_id"], at=self.clock(), recovery_client_id=None)
        return client

    def presend_problem(self, claim, forced=False):
        """The last look before the queue process starts. Returns (target, reason,
        delay) to give the claim back, or None to send. A person's Send now (`forced`) is not
        stopped by a postponement, which it passed; by everything else, as any send is.

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
        postponed = not forced and (claim.get("not_before") or 0) > now      # schema 4's, and
        if not self.allowed(claim) or postponed or self.quiet_until(now) is not None:   # quiet hours
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

    # --------------------------------------------------------------- words for this time (v0.6.16-beta.3)
    def _once_words(self, row, message, limits):
        """(the continuation with this interruption's words for this time after it, the words), or (`message`,
        None): no words, words that fail the Custom message's check as they are read again (A27), or a record not
        waiting. Built before the claim, as every word of a continuation is (A26); they change no gate."""
        self._once_seen.pop(row.get("interruption_id"), None)
        if self.once_words is None or row.get("state") not in WAITING:
            return message, None
        try:
            words = self.once_words.words(row["interruption_id"])
            self._once_seen[row["interruption_id"]] = words     # what the file held as this one was built
            joined = _message.with_once_words(message, words, row["category"], self.policy_values, row=row,
                                              limits=limits)
        except Exception:
            return message, None
        return (joined, words) if joined != message else (message, None)

    def _once_words_moved(self, claim) -> bool:
        """Whether a person changed this interruption's words for this time - added, edited or took them away -
        between the read that built its continuation and the claim: True, and the claim is given back so the next
        continuation carries what the person wrote; spending the old words would delete the new ones unsent, and a
        continuation sent without words just added would let them be deleted with the record. Asked under the
        file's lock after the claim, where the Dashboard can no longer add any (control/actions.py set_once_words
        checks under the same lock); a file that cannot be had just now changes nothing."""
        key = claim["interruption_id"]
        if key not in self._once_seen:
            return False
        seen = self._once_seen.pop(key)
        try:
            moved = self.once_words.unchanged(key, seen) is False
        except Exception:
            moved = False
        if moved:                       # given back as a pre-send look gives one back: nothing was sent
            self._release(key, claim, "waiting_retry", "released_before_send", self.options["state_poll_seconds"])
            self.log(claim["thread_id"], "waiting_retry", "released_before_send")
        return moved

    def _spend_once_words(self, claim, words) -> bool:
        """The words taken off the file as the continuation carrying them is handed to Codex, so they are never sent
        twice: True, and they go; False - the file could not be written - and this continuation goes without them."""
        try:
            spent = self.once_words.remove(claim["interruption_id"])
        except Exception:
            spent = False
        if spent:
            self._once_sent[claim["interruption_id"]] = words
        self.log(claim["thread_id"], "once_words_sent" if spent else "once_words_kept", None)
        return spent

    def _prune_once_words(self):
        """Words of an interruption that is no longer waiting - recovered otherwise, cancelled, expired, superseded,
        gone - deleted (the default home's engine only; every home's records are in its one store)."""
        if self.once_words is None or self.home_key:
            return
        try:
            self.once_words.prune(lambda key: (self.store.get(key) or {}).get("state") in WAITING | CLAIMED)
        except Exception:
            self.log(None, "once_words_unavailable", None)

    def _after_send(self, row, response, resend=False):
        """What came of a send: queued, given back or tried again for one that never started, and
        an uncertain submission for anything else - and, for a resend, never a wait (engine/resend.py)."""
        reserved = self.store.get(row["interruption_id"])
        outcome = response.get("outcome")
        words = self._once_sent.pop(row["interruption_id"], None)
        if words is not None and outcome == "not_started":     # never handed over: they wait for the next one
            try:
                self.once_words.restore(row["interruption_id"], words)
            except Exception:
                pass
        if resend and outcome != "accepted":
            self._after_resend(reserved, outcome)
        elif outcome == "accepted":
            now = self.clock()
            self.transition(reserved, "queued", None, delay=1, event="submitted",
                            queue_id=response.get("queue_id"),
                            first_queued_at=reserved["first_queued_at"] or now)
            self.log(row["thread_id"], "continuation_submitted", None)
            self.announce("starting", reserved, **self._told_of(row))   # a Tell's line (engine/guard.py)
        elif outcome == "not_started":
            if response.get("error_code") == "queue_consent_refused":
                target = "cancelled" if reserved["cancel_requested"] else self.waiting_state(reserved)
                reason = "user_cancelled" if reserved["cancel_requested"] else "released_before_send"
                self._release(row["interruption_id"], reserved, target, reason,
                              self.options["state_poll_seconds"])
                self.log(row["thread_id"], target, reason)
                return
            retry = reserved["retry_count"] + 1
            if retry >= self.options["max_queue_retries"]:
                self.transition(reserved, "failed", "queue_launch_retry_limit", retry_count=retry,
                                submitted_at=None)
            else:
                delay = (self.delay_for(reserved["recovery_attempts"])
                         if reserved["category"] != failures.USAGE_LIMIT else backoff_delay(retry))
                self.transition(reserved, "waiting_retry", "queue_process_not_started",
                                retry_count=retry, submitted_at=None, delay=delay)
        else:
            # Persist the no-resend state first. Diagnostic logging is not allowed to
            # be a prerequisite for the safety-critical state transition.
            self.transition(reserved, "submission_unknown", "queue_result_unknown_do_not_resend", delay=1)
            # CLI receipt diagnostics are fixed vocabulary only: never log CLI output,
            # which could echo a prompt or carry credentials. Do not infer non-delivery
            # from a missing receipt, and do not turn an unknown send into a retry.
            try:
                if response.get("error_code") == "queue_response_unconfirmed":
                    detail = response.get("receipt_detail")
                    if detail == "nonzero_exit":
                        code = response.get("exit_code")
                        self.log(row["thread_id"], "queue_receipt_exit_nonzero",
                                 str(code) if type(code) is int and 0 <= code <= 255 else None)
                    elif detail == "empty_stdout":
                        self.log(row["thread_id"], "queue_receipt_empty_stdout", None)
                    elif detail == "unrecognized_stdout":
                        self.log(row["thread_id"], "queue_receipt_unrecognized_stdout", None)
            except Exception:
                # A diagnostics sink must not affect an already-persisted delivery state.
                pass

    # --------------------------------------------------------------- receipts on workers (P12, v0.6.15-beta)
    def _workers(self, due) -> int:
        """How many sends of this tick may wait for their receipts at once: P12's answer (domain/plughands.py), and 1
        - every send inline, as always - for another Codex home than the default, a retiring one, or an engine that
        has no store for a worker to open."""
        workers = self.plug.partition(due)
        return 1 if self.home_key or self.retiring or self.open_store is None else workers

    def _take_slot(self, resend, route):
        """A worker for the send being dispatched, taken before its claim - waiting, outside any transaction, while
        every worker is busy - while a pool is open; never for a resend or a route."""
        if (self._pool is not None and not resend and route in (None, Alternative.QUEUE_FOR_OPEN,
                                                                Alternative.TO_SESSION)
                and self._held_slot is None):
            self._held_slot = self._pool.take()

    def _pooled(self, sender, client) -> frozenset:
        """Whether this send goes to the worker taken for it - core's own backend, carrying its marker, or (v0.6.17)
        a channel the plug said may wait beside others (plughands.Channel's `concurrent`) - as the claim is told:
        CONCURRENCY among what it carries, so the plug's ledger pays for it (and its tripwire on a send whose fate is
        unknown covers it, K7). Any other channel is sent inline, one at a time, as before."""
        self._pooling = self._held_slot is not None and (
            (sender is self.backend and client is None)
            or (sender is not self.backend and getattr(sender, "concurrent", False) is True))
        return frozenset({Point.CONCURRENCY}) if self._pooling else frozenset()

    def _launched(self, current, call, thread, words, key, carrying) -> bool:
        """The send handed to its worker - after the claim, the pre-send look and the proof check - if it goes to
        one: True, and the pool settles it (`_settle_launch`). False, and dispatch makes the one send inline."""
        if not self._pooling:
            return False
        slot, self._held_slot, self._pooling = self._held_slot, None, False
        slot.launch(call, thread, words, key, carrying, settle=current)
        return True

    def _free_slot(self):
        if self._held_slot is not None:
            self._held_slot.free()
        self._held_slot, self._pooling = None, False

    def _settle_launch(self, current, response):
        """What came of a send a worker waited for, on the tick thread and under the dispatch lock, as dispatch
        settles its own."""
        with self.dispatch_lock():
            try:
                self._after_send(current, response, False)
            except Exception:
                self.log(current["thread_id"], "post_send_bookkeeping_failed", None)
