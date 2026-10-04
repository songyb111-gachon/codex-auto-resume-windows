"""Sending one continuation, and everything checked at the last moment.

`attempt` gathers the facts and evaluates the gates, and `dispatch` claims the right to send and
starts the queue process, after `presend_problem` (engine/delivery.py), the look taken after the
claim and before the process - the only moment where giving the claim back is still provably safe.

The edition's plug is asked here at seven points, every one of them after the consent gate: the
schedule (P7) and the gates (P3) once core's own evaluation has passed, where what it can answer is
HOLD - and at known_failure, which is also asked for a record P17 took up whose kind core does not
recover alone (v0.6.13), the words that take it up again, without which it ends unsent
(engine/relaxed.py); what continues a conversation the app does not hold (P16,
engine/delivery.py) where core would wait for it to be opened; the words (P4), what the send is
handed to (P5) and how it is carried and proven (P15, engine/delivery.py) before the claim; and
its ledger (P11) inside the claim. Whatever it answers, the send is still this module's one call,
made after the one claim, the pre-send look (engine/delivery.py) and inside the launch guard, and
a route named at P16 is carried out the same way in its place - and so is an uncertain submission
sent once more, which P7 asked for and engine/resend.py proved may go (v0.6.13).
"""
from __future__ import annotations

from .. import continuation as _message, failures, l10n, ladder, machine
from ..domain.plug import Alternative, Point
from ..machine import OBSERVING, TERMINAL, WAITING, WATCHED
from .reconcile import UNSENT


class DispatchMixin:
    def attempt(self, row):
        """Look at one record: every gate, and the send if all pass. A record looked at early (EARLY)
        is that only for this look, and every wait it meets leaves it as it was (engine/relaxed.py)."""
        self._early_look = self._schedule_said = None
        try:
            self._attempt(row)
        finally:
            self._early_look = self._schedule_said = None

    def _attempt(self, row):
        now = self.clock()
        poll = self.options["state_poll_seconds"]
        settings = self.store.settings()
        vector = {"consent": machine.gate_consent(settings["enabled"], self.store.thread_enabled(row["thread_id"]),
                  row.get("cancel_requested"), observe_only=self.observing(settings), hold=row.get("hold"))}
        # Observe only goes on through every other gate, asking no plug, to where a send would begin.
        if vector["consent"][0] != machine.PASS and not self.observes(row, vector):
            # No transition - the overlays already say why it waits - but a due record
            # still records the refusing gate, once, so every interface can show it.
            recorded = machine.decode_gates(row.get("gate_eval")).get("consent")
            if (row.get("next_retry_at") or 0) <= now and recorded != vector["consent"]:
                self.store.record_gates(row["interruption_id"], vector, now)
            return
        quiet_until = self.quiet_until(now)     # v0.6.11; None with no quiet hours, the default
        vector["schedule"] = machine.gate_schedule(row, now, quiet_until=quiet_until)
        early = vector["schedule"][0] != machine.PASS and self._early(row, vector, now, quiet_until)
        # SEND_NOW (v0.6.13): a person's request passes the retry's wait and a postponement only.
        forced = vector["schedule"][0] != machine.PASS and self._send_now(row, vector, now, quiet_until)
        if vector["schedule"][0] != machine.PASS:
            if vector["schedule"][1] == "waiting_reset" and (row.get("next_retry_at") or 0) <= now:
                # A usage reset still ahead is a wait with a reason, never a record that is
                # due every poll and silently refused.
                self._wait(row, "waiting_reset", "waiting_reset",
                           row["reset_at"] + self.options["reset_grace_seconds"] - now, vector)
            elif vector["schedule"][1] == machine.POSTPONED and (row.get("next_retry_at") or 0) <= now:
                self._wait(row, row["state"], row.get("last_error"), row["not_before"] - now, vector)
            elif vector["schedule"][1] == machine.QUIET_HOURS:
                self._quiet(row, vector, quiet_until - now)
            return
        # P7: due by core's schedule, and the plug may say not yet - asked already if it looked early,
        # or if a person's Send now passed it; SEND_NOW here passes the spacing and the attempt budget.
        if not (early or forced) and vector["consent"][0] == machine.PASS:
            said = self.plug.schedule(row, machine.eligible_at(row))
            forced = said is Alternative.SEND_NOW
            if self._held("schedule", row, vector, said):
                return
        if row["state"] in ("waiting_reset", "waiting_poll"):
            self.log(row["thread_id"], "checking_eligibility", None)
        compatibility = self.engine_state()
        vector["engine_compatible"] = (
            machine.gate(machine.PASS) if compatibility in ("verified", "checked", "structurally_compatible")
            else machine.gate(machine.BLOCK, "engine_incompatible") if compatibility in ("incompatible", "failed_here")
            else machine.gate(machine.UNKNOWN, "engine_unknown"))
        vector["single_owner"] = (machine.gate(machine.PASS) if self.home_lock()
                                  else machine.gate(machine.BLOCK, "home_lock_unavailable"))
        others = self.store.others_in_flight(row["thread_id"], row["interruption_id"])
        vector["submission_safe"] = machine.gate_submission_safe(row, others)
        if vector["engine_compatible"][0] != machine.PASS:
            self._wait(row, "waiting_for_app", vector["engine_compatible"][1], poll, vector)
            return
        if vector["single_owner"][0] != machine.PASS:
            self._wait(row, "waiting_for_app", "home_lock_unavailable", poll, vector)
            return
        if vector["submission_safe"][0] != machine.PASS:
            self._wait(row, "waiting_retry", "other_recovery_in_flight", poll, vector)
            return
        if self._plugged("submission_safe", row, vector):
            return
        if not self.valid_interruption(row):
            self.transition(row, *self.supersede_reason(row))
            return
        # Even a brief lag can hide a newer user turn. The grace period is useful
        # when watching an already queued item, but never authorizes a new send.
        fresh = self._projection_now(row["thread_id"])
        if fresh is None:
            vector["engine_compatible"] = machine.gate(machine.BLOCK, "projection_table_missing")
            self._wait(row, "waiting_for_app", "projection_table_missing", poll, vector)
            return
        vector["identity"] = (machine.gate(machine.PASS) if fresh
                              else machine.gate(machine.UNKNOWN, "projection_stale"))
        if not fresh:
            self._wait(row, "waiting_for_loaded_thread", "projection_stale", poll, vector)
            return
        relaxed = self._known_failure(row, vector, now)
        if relaxed is False:
            return
        # CAPACITY counts against core's capacity bounds: budgets, its day and its spacing (ladder.py).
        capacity = relaxed == "capacity"
        limits = self.capacity_limits() if capacity else self.limits()
        vector.update(machine.gate_budgets(row, limits, row["category"] == failures.USAGE_LIMIT))
        if forced:
            self._own_budget(row, vector)
        for name in ("chain_budget", "attempt_budget", "no_progress_budget"):
            if vector[name][0] != machine.PASS:
                self.store.record_gates(row["interruption_id"], vector, now)
                self._stop_for_budget(row, name, vector[name][1])
                return
        # The attempt budget is put to the plug with the pacing below, which is recorded under
        # the same gate, so the plug hears each gate once.
        for name in ("chain_budget", "no_progress_budget"):
            if self._plugged(name, row, vector):
                return
        app = self.backend.app_identity()
        if not app:
            vector["thread_available"] = machine.gate(machine.WAIT, "desktop_app_unavailable")
            self._wait(row, "waiting_for_app", "desktop_app_unavailable", poll, vector)
            return
        loaded = self.backend.loaded(row["thread_id"], app)
        # P16: a conversation the app does not hold waits for it to be opened (A11), unless the
        # plug names a route that continues it otherwise, which core carries out (engine/delivery.py).
        route = self._unloaded(row, loaded, vector)
        if route is None and loaded != "loaded":
            reason = "notLoaded" if loaded == "notLoaded" else "loaded_state_unknown"
            vector["thread_available"] = machine.gate(
                machine.WAIT if loaded == "notLoaded" else machine.UNKNOWN, reason)
            self._wait(row, "waiting_for_loaded_thread", reason, poll, vector)
            return
        if route is None:
            vector["thread_available"] = machine.gate(machine.PASS)
            if self._plugged("thread_available", row, vector):
                return
            if row["state"] != "waiting_for_usage":
                self.log(row["thread_id"], "loaded", None)
        if self.source.foreign_queued(row["thread_id"], row["marker"]):
            # Somebody already queued something for this conversation. It goes first,
            # and it may well make our continuation unnecessary.
            vector["no_newer_user_work"] = machine.gate(machine.WAIT, "user_input_queued")
            self._wait(row, "waiting_retry", "user_input_queued", poll, vector)
            return
        vector["no_newer_user_work"] = machine.gate(machine.PASS)
        recent = self.store.recent_claims(row["thread_id"], now - 86400)
        per_day = ladder.CAPACITY_PER_DAY if capacity else self.options["max_submissions_per_thread_per_day"]
        if self.store.recent_claim_count(row["thread_id"], now - 86400) >= per_day:
            # Defer until the oldest claim rolls out of the 24h window rather than
            # permanently abandoning a still-valid interruption. Bounded to N/day per thread.
            vector["attempt_budget"] = machine.gate(machine.WAIT, "daily_submission_cap")
            self._wait(row, "waiting_retry", "daily_submission_cap",
                       max(60, min(recent) + 86400 - now + 5), vector)
            return
        cooldown = ladder.CAPACITY_SPACING if capacity else self.options["thread_cooldown_seconds"]
        if recent and now - max(recent) < cooldown and not forced:
            vector["attempt_budget"] = machine.gate(machine.WAIT, "thread_submission_cooldown")
            self._wait(row, "waiting_retry", "thread_submission_cooldown", cooldown, vector)
            return
        if self._plugged("attempt_budget", row, vector) or self._offline(row, vector, now):  # v0.6.11
            return
        usage = self.usage()
        if usage.get("available") is not True:
            vector["usage"] = machine.gate(
                machine.WAIT if usage.get("available") is False else machine.UNKNOWN,
                "usage_unavailable" if usage.get("available") is False else "usage_unknown")
            self.store.record_gates(row["interruption_id"], vector, now)
            if not early:                                   # a look early that finds none changes nothing
                self._usage_wait(row, usage, now)
            return
        vector["usage"] = machine.gate(machine.PASS)
        if self._plugged("usage", row, vector):
            return
        if vector["consent"][0] != machine.PASS:
            return self._would_send(row, vector, now)       # observe only: every other gate passed
        # v0.6.11: the task-changed guard, which reads nothing at the defaults (engine/guard.py).
        if self._guarded(row, vector, now) or (not forced and self._objection(row, vector, now)):
            return
        self.dispatch(row, app, vector, limits, route, relaxed=relaxed or ("early" if early else None),
                      forced=forced)

    def _plugged(self, name, row, vector) -> bool:
        """P3: gate `name`, which core has just passed, put to the plug. True if it held. Never asked
        of a record only observed: the plug is asked after consent, and observe only refused it."""
        if vector["consent"][0] != machine.PASS:
            return False
        return self._held(name, row, vector, self.plug.gate(name, row, dict(vector)))

    def _held(self, name, row, vector, answer) -> bool:
        """Whether the plug's answer at gate `name` holds this record, which core would let go.

        HOLD only restricts: the gate is recorded as waiting, and the record keeps its state and
        its reason for one more poll, as on any wait of core's own. Every other answer lets core go
        on as it would have with no plug at all - known_failure's words aside (_known_failure)."""
        if answer is not Alternative.HOLD:
            return False
        vector[name] = machine.gate(machine.WAIT, machine.HELD)
        self._wait(row, row["state"], row.get("last_error"), self.options["state_poll_seconds"],
                   vector)
        return True

    def dispatch(self, row, app, vector, limits, route=None, relaxed=None, resend=False, forced=False):
        """Claim, re-check, send. The only method that sends: to core's backend, or to the
        channel the plug names at P5, and either way through the one call below. With a `route`
        (P16) there is no send: the conversation is still one the app does not hold, and the
        route is carried out in its place (engine/delivery.py). `relaxed` is a gate the plug
        relaxed for this record (_known_failure), which its ledger pays for at the claim. With
        `resend`, an uncertain submission is sent once more (engine/resend.py): every re-check
        that fails leaves it as it was, since no move takes one back to waiting. `forced` is a
        person's Send now (SEND_NOW), which the claim re-checks and the plug's ledger pays for."""
        key = row["interruption_id"]
        with self.dispatch_lock():
            current = self.store.get(key)
            if not current or not self.allowed(current) or not (
                    self._resendable(current, self.clock()) if resend else current["state"] in UNSENT):
                return
            if not self.valid_interruption(current):
                if not resend:
                    self.transition(current, *self.supersede_reason(current))
                return
            # A fresh process identity prevents a prior app's status authorizing a new app. A
            # route is for a conversation the app does not hold, and only while it still does not.
            if (self.backend.app_identity() != app
                    or self.backend.loaded(current["thread_id"], app) != (
                        "loaded" if route is None else "notLoaded")):
                if not resend and not self._parked(current, vector):
                    self.transition(current, "waiting_for_loaded_thread", "loaded_recheck_failed", delay=60)
                return
            if self.usage().get("available") is not True:
                if not resend and not self._parked(current, vector):
                    self.transition(current, "waiting_for_usage", "usage_recheck_failed", delay=900)
                return
            if route is not None:
                self._resume_unloaded(current, vector, limits, route, app, relaxed=relaxed, forced=forced)
                return
            # The text is decided before the claim, not after it. Building it reads catalogs
            # and settings; if either were ever broken, the failure has to happen while the
            # record is still merely waiting. After the claim, any exception is treated as a
            # send that may have happened - which is the right rule for a send and the wrong
            # one for a sentence that was never finished.
            #
            # Nothing about the text can change what is allowed. Every gate above has
            # already passed; the style and the Custom message decide words, and the words
            # are only ever built for a category the classifier has proven recoverable.
            try:
                message = _message.for_settings(current["category"], self.policy_values,
                                                row=current, limits=limits)
            except Exception:
                self.log(current["thread_id"], "continuation_text_fallback", None)
                message = _message.build(current["category"], locale=l10n.DEFAULT)
            message, worded = self._plugged_text(current, message, limits)
            # P5, decided before the claim like the words: core's own backend, unless the plug
            # names a channel. The one binding of the one sender; whichever it is gets the one
            # send below, after the claim and the pre-send look, inside the launch guard.
            sender = self.plug.sender(current, self.backend)
            # P15, decided like them before the claim, and written into the record before it - for a
            # resend, the proof its first send carried, or nothing is sent (engine/delivery.py).
            client = self._delivery(current, sender, resend=resend)
            if client is False:
                return
            # P11 is asked inside the claim, once every check the store makes there has passed.
            # The claim is told which of the plug's answers the send carries - its words, its
            # channel, its way of carrying them - as decided here, where words that fill in to
            # nothing were dropped: those are paid for in its ledger, so a ledger that breaks holds
            # the claim instead of letting them go out unpaid, and nothing core dropped is paid
            # for or held.
            carried = frozenset(point for point, taken in ((Point.TEXT, worded),
                                                           (Point.SENDER, sender is not self.backend),
                                                           (Point.DELIVERY, client is not None))
                                if taken) | self.relaxed_points("resend" if resend else relaxed)
            carried |= self.relaxed_points("forced" if forced else None)
            at = self.clock()
            claimed, gate, reason = self.store.reserve_detailed(
                key, at, limits=self.forced_limits(limits) if forced else limits, gates=vector,
                ledger=self.plug, carried=carried, quiet_until=self.quiet_until(at), relaxed=relaxed,
                resend=self.resend_window() if resend else None, forced=forced)
            if not claimed:
                if not resend:                          # a resend refused stays as it was
                    self._refused(current, gate, reason)
                return
            self.moved(current, "submitting")
            claim = self.store.get(key)
            problem = self.presend_problem(claim, forced=True) if forced else self.presend_problem(claim)
            if problem is None and client is not None and self.proof(claim) != client:
                # Never sent under an id the watch would not look for (engine/delivery.py).
                problem = ("waiting_retry", "released_before_send", self.options["state_poll_seconds"])
            if problem is not None:
                target, why, delay = problem
                if resend:          # never given back to a wait: its first send is still uncertain
                    target, why = "submission_unknown", "released_before_send"
                    self.transition(claim, target, why, delay=1)
                else:
                    self._release(key, claim, target, why, delay)
                self.log(current["thread_id"], target, why)
                return
            self.log(current["thread_id"], "queue_submission_started", None)
            # Reservation is durable before any external process can accept the message.
            # The conversation and the marker are the claimed row's, read back from the store
            # after the claim - the row the pre-send look and the launch guard judged - and not
            # the dict the plug's points were asked about before it. With no marker (P15), the
            # client id that row holds goes with the words instead (engine/delivery.py).
            words, carrying = ((message, {"client_id": client}) if client is not None
                               else (message + "\n\n" + claim["marker"], {}))
            try:
                response = sender.send(claim["thread_id"], words,
                                       launch_guard=self.store.submission_guard(key), **carrying)
            except Exception:
                response = {"outcome": "unknown"}
            if not isinstance(response, dict):
                response = {"outcome": "unknown"}
            try:
                self._after_send(current, response, resend)
            except Exception:
                # The send happened or may have; the record stays claimed and the watch
                # resolves it. Never logged as "no submission".
                self.log(current["thread_id"], "post_send_bookkeeping_failed", None)
