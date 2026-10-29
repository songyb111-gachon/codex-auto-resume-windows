"""A conversation the app does not hold, continued by a route the edition's plug names (P16).

Core has always waited for the app to open such a conversation (A11); the plug may name a route instead, and
`_unloaded` takes it where core would wait, once every gate before that one has passed - and, from v0.6.16-beta.4,
`_unheld` where the app is not running and nothing holds the conversation's writer lock (Backend.holder), asked only
while the plug wants P16. The gates after it are the ones a send passes, and `_resume_unloaded` carries the route out
as `dispatch` carries out a send: the one claim - which the plug's ledger pays for - the pre-send look, and the route
called once inside the launch guard, handed core's own look at whether the conversation is still not held, for it to
ask at the last moment before it changes anything in Codex - and, for a route that takes words, the words core decided
before the claim, its marker at their end. A route that did what it was asked without a turn of its own leaves the
record waiting again with its claim counted (the cooldown, the day's five and the chain); one that ran the turn itself
("ran") leaves it queued, proven by its marker as any delivered send; one that never started gives the claim back,
and anything else is an uncertain submission, never tried again, exactly as a send's is.

Out of engine/delivery.py, at its size, in v0.6.16-beta.4. The standard edition's plug names no route, so none of this
runs for it.
"""
from __future__ import annotations

from .. import machine
from ..domain import ids
from ..domain.plug import QUEUED, DEFER, Alternative, Point

# Where P16 is asked (v0.6.16-beta.4): a conversation the running app does not hold, and one nothing holds while the
# app is not running (Backend.holder's word for it). OURS is Backend.holder's word for an app server this process
# started and holds: no other holder at a route's last look, and never a reason to ask P16.
APP_FREE, NOBODY, OURS = "app_free", "none", "ours"


class RoutesMixin:
    def _route(self, row, app, vector):
        """(the route the plug names for `row`, or None; what the app said of the conversation): P16 where the app
        does not hold it (`_unloaded`), and - with no app at all (v0.6.16-beta.4) - where nothing holds it
        (`_unheld`), which the app's word is notLoaded for."""
        if not app:
            return self._unheld(row, vector), "notLoaded"
        loaded = self.backend.loaded(row["thread_id"], app)
        # v0.6.16-beta.4: or held by another Codex session (engine/tosession.py).
        return self._unloaded(row, loaded, vector) or self._session(row, loaded, vector), loaded

    def _still_where(self, thread_id, app, route) -> bool:
        """The re-check under the dispatch lock: the same app, holding the conversation for a send or not holding it
        for a route - or, with no app (v0.6.16-beta.4), still none, and nothing holding it; for TO_SESSION, the SAME
        session still holding it, by the pid and creation time kept when P16 answered (engine/tosession.py)."""
        if app is None:
            return self._unheld_now(thread_id)
        if self.backend.app_identity() != app:
            return False
        loaded = self.backend.loaded(thread_id, app)
        if route is Alternative.TO_SESSION:
            kept = self._session_holders.pop(thread_id, None)
            return (loaded == "elsewhere" and kept is not None
                    and getattr(self.backend, "session_holder", None) == kept)
        return loaded == ("loaded" if route is None else "notLoaded")

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
        # v0.6.16-beta.4: told where it is asked - the app runs, and does not hold it.
        route = self.plug.unloaded(dict(row, holder=APP_FREE, app=True))
        if route is DEFER or route is Alternative.TO_SESSION:
            return None
        vector["thread_available"] = machine.gate(machine.PASS, machine.PLUGGED)
        return route

    def _unheld(self, row, vector):
        """P16 with the Codex app closed (v0.6.16-beta.4): the route the plug names for `row`, whose conversation
        nothing holds, or None - core's own wait for the app (A11).

        Asked only where the plug wants P16 at all - so the standard edition never asks who holds anything and
        makes exactly the calls it always made - for the default Codex home, once consent has passed, and only
        where nothing holds the conversation's writer lock and no process of the app runs (Backend.holder). Only a
        route is taken: QUEUE_FOR_OPEN needs an app to open the conversation in."""
        if self.home_key or vector["consent"][0] != machine.PASS or not self.plug.wants(Point.UNLOADED):
            return None
        if self._holder(row["thread_id"]) != NOBODY:
            return None
        route = self.plug.unloaded(dict(row, holder=NOBODY, app=False))
        if route is DEFER or route in QUEUED:
            return None
        vector["thread_available"] = machine.gate(machine.PASS, machine.PLUGGED)
        return route

    def _unheld_now(self, thread_id, ours=False) -> bool:
        """Whether, now, the Codex app is still not running and nothing holds `thread_id` - a look that fails, no.
        With `ours` - the route's own last look - an app server this process started and holds counts as no other
        holder: the route's server holds the writer lock from its thread/resume until it lets go, so without it no
        turn could ever start; any other holder still says no."""
        try:
            return (self.backend.app_identity() is None
                    and self._holder(thread_id) in ((NOBODY, OURS) if ours else (NOBODY,)))
        except Exception:
            return False

    def _holder(self, thread_id) -> str:
        """Backend.holder's word for `thread_id`; "unknown" from a backend that cannot say (one of no such call)."""
        holder = getattr(self.backend, "holder", None)
        return holder(thread_id) if callable(holder) else "unknown"

    def _resume_unloaded(self, current, vector, limits, route, app, relaxed=None, forced=False, words=None):
        """Carry out the route the plug named at P16, as `dispatch` carries out a send: the one
        claim, paid for by the plug's ledger (P11, told the route is what it carries); the pre-send
        look; and the route called once, inside the launch guard. Called under the dispatch lock,
        with the conversation still not held by the app `app` and usage still there (`dispatch`).

        The route is handed `still_unloaded`, core's look at the conversation made again when it
        is asked - never the cached one: consent still given (the launch guard's own check, read
        again), and the app `app` still there and saying notLoaded; anything else, a look that
        fails included, is no. A route opens a session with Codex
        before it changes anything, which takes seconds, and the app may open the conversation in
        them; asked at the last moment, the look keeps the route from changing a conversation the
        app has just taken, and the route answers not started."""
        key = current["interruption_id"]
        at = self.clock()
        message, worded, once, plain = words if words is not None else (None, False, None, None)
        # v0.6.17: SILENT is a turn with no words at all, so it yields to any words the continuation carries that
        # are not core's own template - another capability's at P4, or the person's words for this time. A silent
        # turn would throw them away, and the person's would be spent as they went (`_spend_once_words` below),
        # lost for good: not sent, not kept. Where it yields the continuation goes by its marker, as one whose
        # P15 was never asked, and P4's words are carried and paid for as any send's are.
        carries_words = worded or once is not None
        silent = message is not None and self._silent(current, yields=carries_words)
        claimed, gate, reason = self.store.reserve_detailed(
            key, at, limits=self.forced_limits(limits) if forced else limits, gates=vector, ledger=self.plug,
            carried=frozenset({Point.UNLOADED}) | ({Point.TEXT} if worded and not silent else frozenset())
            | ({Point.DELIVERY} if silent else frozenset())
            | self.relaxed_points(relaxed) | self.relaxed_points("forced" if forced else None),
            quiet_until=self.quiet_until(at), relaxed=relaxed, forced=forced, caps=self.caps(relaxed))
        if not claimed:
            self._refused(current, gate, reason)
            return
        self.moved(current, "submitting")
        claim = self.store.get(key)
        problem = self.presend_problem(claim, forced=True) if forced else self.presend_problem(claim)
        if problem is not None:
            target, why, delay = problem
            self._release(key, claim, target, why, delay)
            self.log(current["thread_id"], target, why)
            return
        if words is not None and self._once_words_moved(claim):     # given back (engine/delivery.py)
            return
        thread_id = claim["thread_id"]
        if once is not None and not self._spend_once_words(claim, once):
            message = plain                 # never sent twice (the words for this time, as a send's)

        refused = []

        def still_unloaded() -> bool:
            # Consent again, as the launch guard asks it (store.submission_guard): a Cancel, Pause or observe-only set
            # while the route's session started, resumed and listed - seconds each - stops it here, before anything
            # changes in Codex, as the guard stops a send or a channel's add.
            try:
                with self.store.submission_guard(key) as permitted:
                    if permitted is not True:
                        refused.append(True)
                        return False
            except Exception:
                return False
            if app is None:
                return self._unheld_now(thread_id, ours=True)
            try:
                return (self.backend.app_identity() == app
                        and self.backend.loaded(thread_id, app) == "notLoaded")
            except Exception:
                return False
        # A route that takes words (v0.6.16-beta.4) is handed them as a send would carry them, the marker read back
        # from the claimed row at their end, and the client id core derives from the interruption.
        handed = ({} if message is None else
                  {"words": "" if silent else message + "\n\n" + claim["marker"],
                   "client_id": ids.continuation_client_id(key)})
        try:
            response = route.resume(thread_id, launch_guard=self.store.submission_guard(key),
                                    still_unloaded=still_unloaded, **handed)
        except Exception:
            response = {"outcome": "unknown"}
        if not isinstance(response, dict):
            response = {"outcome": "unknown"}
        if refused and response.get("outcome") == "not_started":
            response = dict(response, error_code="queue_consent_refused")     # a Cancel is settled as one
        try:
            self._after_resume(current, response)
        except Exception:
            self.log(current["thread_id"], "post_send_bookkeeping_failed", None)

    def _silent(self, row, yields=False) -> bool:
        """P15 for a route that takes words (v0.6.16-beta.4): SILENT is no words at all, the turn proven by the client
        id core derives - written into the record before the claim (its `recovery_client_id`, engine/delivery.proof),
        and taken away again where it is not SILENT this time, so the record goes by its marker.

        With `yields` (v0.6.17) P15 is not asked at all and this continuation is not silent: it carries words a
        turn with none would throw away (`_resume_unloaded`), so it goes by its marker, and an id an earlier
        silent look wrote into the record is taken away again, exactly as a look that was answered otherwise.

        Asked with `route` (v0.6.17, #47): the plug is told this P15 is a route's, which takes SILENT alone - so an
        answer only a channel's send can carry (CLIENT_ID) is not the one it takes here, and a capability that
        serves channel sends does not stand in the way of one that serves routes."""
        derived = ids.continuation_client_id(row["interruption_id"])
        silent = not yields and self.plug.delivery(dict(row, route=True)) is Alternative.SILENT
        if silent and row.get("recovery_client_id") != derived:
            self.store.update(row["interruption_id"], at=self.clock(), recovery_client_id=derived)
        elif not silent and row.get("recovery_client_id") == derived:
            self.store.update(row["interruption_id"], at=self.clock(), recovery_client_id=None)
        return silent

    def _silent_proven(self, row, turn_id) -> bool:
        """A turn started with no words (P15's SILENT) keeps no client id on any item (M3B, 2026-10-16): the turn id
        the route's turn/start returned is its proof, correlated at once - as the watch correlates a marker it finds.
        Any other record is left to the watch. Whether it was."""
        if row.get("recovery_client_id") != ids.continuation_client_id(row["interruption_id"]):
            return False
        current = self.store.get(row["interruption_id"])
        if current is None:
            return False
        if not self.store.correlate(row["interruption_id"], turn_id, self.clock(), client_id=row["recovery_client_id"],
                                    status="inProgress"):
            return False
        self.moved(current, "turn_started")
        self.log(row["thread_id"], "turn_started", None)
        return True

    def _after_resume(self, row, response):
        """What came of a route (P16). Accepted: nothing was queued, and the conversation goes on
        when the app opens it, so the record waits again - the claim still counted against the
        cooldown, the day's claims and the chain, never given back. Not started: the claim is given
        back, as for a send that never started, its time kept for the caps. Anything else may have
        changed Codex and nothing proves how: an uncertain submission, never tried again (A6).

        The person's words for this time, taken off the file as the route was handed them, are put back for the
        next continuation where it never started (v0.6.17), exactly as `_after_send` puts back a send's: the
        route takes and hands them inside one call, so core cannot wait for it to start before taking them."""
        key = row["interruption_id"]
        outcome = response.get("outcome")
        words = self._once_sent.pop(key, None)
        if words is not None and outcome == "not_started":     # never handed to Codex: they wait for the next one
            try:
                self.once_words.restore(key, words)
            except Exception:
                pass
        reserved = self.store.get(key)
        poll = self.options["state_poll_seconds"]
        if outcome == "accepted":
            self.transition(reserved, "waiting_retry", "notLoaded", delay=poll, submitted_at=None)
        elif outcome == "ran" and ids.is_uuid(response.get("turn_id")):
            # v0.6.16-beta.4: a route that started the one turn itself, carrying core's words: the record is sent,
            # and the watch proves it by its marker in Codex's history as it proves any (A4) - never sent again.
            self.transition(reserved, "queued", None, delay=1, event="submitted", queue_id=None)
            self.log(row["thread_id"], "continuation_submitted", None)
            self.announce("starting", reserved, **self._told_of(row))
            self._silent_proven(reserved, response["turn_id"])
        elif outcome == "not_started":
            refused = response.get("error_code") == "queue_consent_refused"
            target = ("cancelled" if refused and reserved["cancel_requested"]
                      else self.waiting_state(reserved))
            reason = "user_cancelled" if target == "cancelled" else "released_before_send"
            self._release(key, reserved, target, reason, poll)
            self.log(row["thread_id"], target, reason)
        else:
            self.transition(reserved, "submission_unknown", "queue_result_unknown_do_not_resend", delay=1)
