"""Sending one continuation, and everything checked at the last moment.

`attempt` gathers the facts and evaluates the gates, `dispatch` claims the right to send and
starts the queue process, and `presend_problem` is the look taken after the claim and before
the process - the only moment where giving the claim back is still provably safe.

The edition's plug is asked here at five points, every one of them after the consent gate: the
schedule (P7) and the gates (P3) once core's own evaluation has passed, where the one thing it
can answer yet is HOLD; the words (P4) and what the send is handed to (P5) before the claim;
and its ledger (P11) inside the claim. Whatever it answers, the send is still this module's
one call, made after the one claim, the pre-send look and inside the launch guard.
"""
from __future__ import annotations

from .. import continuation as _message, failures, l10n, machine
from ..domain.plug import DEFER, Alternative
from ..machine import OBSERVING, TERMINAL, WAITING, WATCHED
from .options import backoff_delay
from .reconcile import UNSENT


class DispatchMixin:
    def attempt(self, row):
        now = self.clock()
        poll = self.options["state_poll_seconds"]
        settings = self.store.settings()
        vector = {"consent": machine.gate_consent(settings["enabled"],
                                                  self.store.thread_enabled(row["thread_id"]),
                                                  row.get("cancel_requested"))}
        if vector["consent"][0] != machine.PASS:
            # No transition - the overlays already say why it waits - but a due record
            # still records the refusing gate, once, so every interface can show it.
            recorded = machine.decode_gates(row.get("gate_eval")).get("consent")
            if (row.get("next_retry_at") or 0) <= now and recorded != vector["consent"]:
                self.store.record_gates(row["interruption_id"], vector, now)
            return
        vector["schedule"] = machine.gate_schedule(row, now)
        if vector["schedule"][0] != machine.PASS:
            if vector["schedule"][1] == "waiting_reset" and (row.get("next_retry_at") or 0) <= now:
                # A usage reset still ahead is a wait with a reason, never a record that is
                # due every poll and silently refused.
                self._wait(row, "waiting_reset", "waiting_reset",
                           row["reset_at"] + self.options["reset_grace_seconds"] - now, vector)
            return
        # P7: due by core's schedule, and the plug may say not yet.
        if self._held("schedule", row, vector, self.plug.schedule(row, machine.eligible_at(row))):
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
        vector["known_failure"] = (machine.gate(machine.PASS) if self.recovers(row["category"])
                                   else machine.gate(machine.BLOCK, "category_disabled"))
        if vector["known_failure"][0] != machine.PASS:
            self._wait(row, row["state"], "category_disabled",
                       self.options["conservative_poll_seconds"], vector)
            return
        limits = self.limits()
        vector.update(machine.gate_budgets(row, limits, row["category"] == failures.USAGE_LIMIT))
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
        if loaded != "loaded":
            reason = "notLoaded" if loaded == "notLoaded" else "loaded_state_unknown"
            vector["thread_available"] = machine.gate(
                machine.WAIT if loaded == "notLoaded" else machine.UNKNOWN, reason)
            self._wait(row, "waiting_for_loaded_thread", reason, poll, vector)
            return
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
        if self.store.recent_claim_count(row["thread_id"], now - 86400) >= self.options["max_submissions_per_thread_per_day"]:
            # Defer until the oldest claim rolls out of the 24h window rather than
            # permanently abandoning a still-valid interruption. Bounded to N/day per thread.
            vector["attempt_budget"] = machine.gate(machine.WAIT, "daily_submission_cap")
            self._wait(row, "waiting_retry", "daily_submission_cap",
                       max(60, min(recent) + 86400 - now + 5), vector)
            return
        cooldown = self.options["thread_cooldown_seconds"]
        if recent and now - max(recent) < cooldown:
            vector["attempt_budget"] = machine.gate(machine.WAIT, "thread_submission_cooldown")
            self._wait(row, "waiting_retry", "thread_submission_cooldown", cooldown, vector)
            return
        if self._plugged("attempt_budget", row, vector):
            return
        usage = self.usage()
        if usage.get("available") is not True:
            vector["usage"] = machine.gate(
                machine.WAIT if usage.get("available") is False else machine.UNKNOWN,
                "usage_unavailable" if usage.get("available") is False else "usage_unknown")
            self.store.record_gates(row["interruption_id"], vector, now)
            self._usage_wait(row, usage, now)
            return
        vector["usage"] = machine.gate(machine.PASS)
        if self._plugged("usage", row, vector):
            return
        self.dispatch(row, app, vector, limits)

    def _plugged(self, name, row, vector) -> bool:
        """P3: gate `name`, which core has just passed, put to the plug. True if it held."""
        return self._held(name, row, vector, self.plug.gate(name, row, dict(vector)))

    def _held(self, name, row, vector, answer) -> bool:
        """Whether the plug's answer at gate `name` holds this record, which core would let go.

        HOLD is the one answer a plug can give at a gate yet, and it only restricts: the gate
        is recorded as waiting, and the record keeps its state and its reason for one more
        poll, as on any wait of core's own. Every other answer lets core go on as it would
        have with no plug at all."""
        if answer is not Alternative.HOLD:
            return False
        vector[name] = machine.gate(machine.WAIT, machine.HELD)
        self._wait(row, row["state"], row.get("last_error"), self.options["state_poll_seconds"],
                   vector)
        return True

    def _plugged_text(self, row, message, limits) -> str:
        """P4: the plug's words for this continuation, or core's own `message`.

        Taken only as a person's Custom message is: they pass the same validator and are filled
        in the same way, for the same record, so they can say nothing a person could not have
        written in the Dashboard. Words that fail the validator, or fill in to nothing, are not
        sent, and core's are - the person's own style, not the Standard text a Custom message
        falls back to."""
        words = self.plug.text(row, message)
        if words is DEFER:
            return message
        try:
            _message.validate_custom(words)
            values = dict(self.policy_values, continuation_style="custom",
                          custom_message_mode="global", custom_message=words)
            if _message.source_for(row["category"], values, row=row, limits=limits) != "global":
                return message
            return _message.for_settings(row["category"], values, row=row, limits=limits)
        except Exception:
            return message

    def dispatch(self, row, app, vector, limits):
        """Claim, re-check, send. The only method that sends: to core's backend, or to the
        channel the plug names at P5, and either way through the one call below."""
        key = row["interruption_id"]
        with self.dispatch_lock():
            current = self.store.get(key)
            if not current or current["state"] not in UNSENT or not self.allowed(current):
                return
            if not self.valid_interruption(current):
                self.transition(current, *self.supersede_reason(current))
                return
            # A fresh process identity prevents a prior app's status authorizing a new app.
            if (self.backend.app_identity() != app
                    or self.backend.loaded(current["thread_id"], app) != "loaded"):
                self.transition(current, "waiting_for_loaded_thread", "loaded_recheck_failed", delay=60)
                return
            if self.usage().get("available") is not True:
                self.transition(current, "waiting_for_usage", "usage_recheck_failed", delay=900)
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
            message = self._plugged_text(current, message, limits)
            # P5, decided before the claim like the words: core's own backend, unless the plug
            # names a channel. The one binding of the one sender; whichever it is gets the one
            # send below, after the claim and the pre-send look, inside the launch guard.
            sender = self.plug.sender(current, self.backend)
            # P11 is asked inside the claim, once every check the store makes there has passed.
            claimed, gate, reason = self.store.reserve_detailed(key, self.clock(), limits=limits,
                                                                gates=vector, ledger=self.plug)
            if not claimed:
                self._refused(current, gate, reason)
                return
            problem = self.presend_problem(self.store.get(key))
            if problem is not None:
                target, why, delay = problem
                self.store.release_claim(key, target, why, self.clock(),
                                         next_retry_at=self.clock() + delay)
                self.log(current["thread_id"], target, why)
                return
            self.log(current["thread_id"], "queue_submission_started", None)
            # Reservation is durable before any external process can accept the message.
            try:
                response = sender.send(current["thread_id"],
                                       message + "\n\n" + current["marker"],
                                       launch_guard=self.store.submission_guard(key))
            except Exception:
                response = {"outcome": "unknown"}
            if not isinstance(response, dict):
                response = {"outcome": "unknown"}
            try:
                self._after_send(current, response)
            except Exception:
                # The send happened or may have; the record stays claimed and the watch
                # resolves it. Never logged as "no submission".
                self.log(current["thread_id"], "post_send_bookkeeping_failed", None)

    def _after_send(self, row, response):
        reserved = self.store.get(row["interruption_id"])
        outcome = response.get("outcome")
        if outcome == "accepted":
            now = self.clock()
            self.transition(reserved, "queued", None, delay=1, event="submitted",
                            queue_id=response.get("queue_id"),
                            first_queued_at=reserved["first_queued_at"] or now)
            self.log(row["thread_id"], "continuation_submitted", None)
            self.announce("starting", reserved)
        elif outcome == "not_started":
            if response.get("error_code") == "queue_consent_refused":
                target = "cancelled" if reserved["cancel_requested"] else self.waiting_state(reserved)
                reason = "user_cancelled" if reserved["cancel_requested"] else "released_before_send"
                self.store.release_claim(row["interruption_id"], target, reason, self.clock(),
                                         next_retry_at=self.clock() + self.options["state_poll_seconds"])
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
            self.transition(reserved, "submission_unknown", "queue_result_unknown_do_not_resend", delay=1)

    def _refused(self, row, gate, reason):
        """A claim the store refused. Recorded as a wait or a stop, never silently."""
        if gate in ("chain_budget", "attempt_budget", "no_progress_budget"):
            self._stop_for_budget(row, gate, reason)
        elif gate == "schedule" and reason == "waiting_reset" and row.get("reset_at"):
            self.transition(row, "waiting_reset", "waiting_reset",
                            delay=max(30, row["reset_at"] + self.options["reset_grace_seconds"] - self.clock()))
        elif gate == "submission_safe" and reason == "other_recovery_in_flight":
            self.transition(row, "waiting_retry", "other_recovery_in_flight",
                            delay=self.options["state_poll_seconds"])
        elif gate == "submission_safe" and reason == machine.HELD:
            # The plug's ledger held the claim (P11): the record keeps its state and its reason
            # for one more poll, as a gate the plug holds does.
            self.transition(row, row["state"], row.get("last_error"),
                            delay=self.options["state_poll_seconds"])

    def presend_problem(self, claim):
        """The last look before the queue process starts. Returns (target, reason,
        delay) to give the claim back, or None to send.

        Anything that changed since the gates ran - a cancel, a Pause, a disabled
        thread, a newer turn, somebody else's queued message, another copy of our
        marker - is caught here, where giving the claim back is still proven safe.
        """
        poll = self.options["state_poll_seconds"]
        if claim is None or claim["state"] != "submitting" or claim["queue_id"] is not None:
            return "waiting_retry", "released_before_send", poll
        if claim["cancel_requested"]:
            return "cancelled", "user_cancelled", 0
        waiting = self.waiting_state(claim)
        if not self.store.settings()["enabled"] or not self.store.thread_enabled(claim["thread_id"]):
            return waiting, "released_before_send", poll
        if not self.valid_interruption(claim):
            state, reason = self.supersede_reason(claim)
            return state, reason, 0
        if self._projection_now(claim["thread_id"]) is not True:
            return "waiting_for_loaded_thread", "projection_stale", poll
        if self.source.foreign_queued(claim["thread_id"], claim["marker"]):
            return "waiting_retry", "user_input_queued", poll
        presence = self.source.marker_presence(claim["thread_id"], claim["marker"])
        if presence.get("history") or presence.get("queue"):
            return "superseded", "duplicate_owner", 0
        if not self.home_lock():
            return "waiting_for_app", "home_lock_unavailable", poll
        return None
