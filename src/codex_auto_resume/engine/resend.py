"""An uncertain continuation sent once more (v0.6.14 stage 3b), where the edition's plug asks and core
proves it may.

Core never sends a continuation again once it may have been delivered (standards 0.2, A6): an
uncertain submission is followed for a day in case it arrives, and otherwise left as uncertain. The
edition's plug may answer RESEND at P7 (domain/plug.py) for one a look of the watch has just found no
trace of - its proof neither in Codex's history nor in its queue - and core carries it out itself,
through its one dispatch, once, only where it proves all of this, and otherwise writes nothing, so
the record stays the uncertain submission the watch goes on following:

* its send's answer was unknown or no receipt came, between 15 minutes and 6 hours ago; Codex was
  never seen holding it in its queue - not moved to `queued`, not found there by any look of this
  watcher's (`_sighted`), and holding no client id of Codex's own; never resent; not cancelled, held
  or carried by a route the plug named (domain/gates.py, resend_candidate);
* consent, the schedule, a compatible engine, the home's lock, nothing else in flight on the
  conversation and the failure still its latest turn - and the plug asked at every gate core passes,
  as a send's are (`_holds`), where HOLD stops it and writes nothing;
* Codex's history current at every look since the send, which a watcher started after it cannot
  say; neither its marker nor its proof in the history or the queue, no later turn and nothing
  queued by anyone; a kind core recovers and has left on, every budget as core computes it, the
  app holding the conversation, the day's five and the spacing, usage, the task-changed guard.

Its words are built again by the same rules, and it carries the same proof: the marker for a send
that had it, the derived client id through a channel for one that had none (engine/delivery.py). Its
claim charges no attempt and no link of the chain - the first paid them - and its vector, with
submission_safe passed as a resend, is what marks it resent for good: a resent record never waits
again (store/records.py, store/claims.py), so nothing rewrites it. Whatever comes of the send - not
started, refused at the last look, unknown - it is an uncertain submission again, never a wait, and
never resent. One that ran and whose proof is then found twice is written so (`watch_resent`), for
the edition to turn off what resent it.

The standard edition's plug never answers RESEND, and nothing here runs for it.
"""
from __future__ import annotations

from .. import failures, machine
from ..domain.plug import Alternative
from ..machine import OBSERVING, OUTCOMES

# How many records the memory of sightings in Codex's queue - and of looks that found no trace -
# holds before it is emptied; once sightings are, nothing sent before then is resent.
REMEMBERED = 4096
# How often a resent record that ran is looked at for a second copy of its proof, at most.
DUPLICATE_LOOK_SECONDS = 60
# The engine states a send may go on in, as `attempt` reads engine_compatible.
COMPATIBLE = ("verified", "checked", "structurally_compatible")
BUDGETS = ("chain_budget", "attempt_budget", "no_progress_budget")


class ResendMixin:
    def resend_window(self) -> tuple:
        """(after, until): how long after its send an uncertain submission may be resent."""
        return self.options["resend_after_seconds"], self.options["resend_until_seconds"]

    def _sighted(self, key):
        """A record's proof was seen in Codex's queue: it is never resent after. Remembered only
        where a plug may ask for a resend, and from the watcher's start - a send from before it is
        never resent, so nothing seen before could matter."""
        if self.plug.null:
            return
        if len(self._seen_queued) >= REMEMBERED:
            self._seen_queued.clear()
            self._seen_queued_cleared_at = self.clock()
        self._seen_queued.add(key)

    def _traceless(self, row, now):
        """The watch looked at an uncertain submission with no queue row of its own and found its
        proof nowhere: it is handed to `resend_uncertain`, at the tick's end."""
        if self.plug.null or row["queue_id"] is not None:
            return
        if len(self._no_trace) >= REMEMBERED:
            self._no_trace.clear()
        self._no_trace[row["interruption_id"]] = now

    def _resendable(self, row, now) -> bool:
        """resend_candidate, and never seen in Codex's queue by this watcher since it was sent."""
        return (machine.resend_candidate(row, now, self.resend_window())
                and row["interruption_id"] not in self._seen_queued
                and self._seen_queued_cleared_at < row["submitted_at"])

    def _holds(self, name, row, vector) -> bool:
        """P3 at gate `name`, for a resend: True if the plug holds it. Nothing is written for it -
        a wait's would rewrite an uncertain submission's next look."""
        return self.plug.gate(name, row, dict(vector)) is Alternative.HOLD

    def resend_uncertain(self):
        """Once a tick, after the due records, only for a plug that may ask: each uncertain
        submission a look of the watch found no trace of since the last tick, considered once."""
        found, self._no_trace = self._no_trace, {}
        now = self.clock()
        for key, looked in found.items():
            if now - looked > self.options["conservative_poll_seconds"]:
                continue
            try:
                self._resend(key, now)
            except Exception:
                self.log(None, "eligibility_check_failed_no_submission", None)

    def _resend(self, key, now):
        """Every condition the module names, in order; the first that fails returns, writing nothing."""
        row = self.store.get(key)
        if row is None or not self._resendable(row, now):
            return
        thread, sent = row["thread_id"], row["submitted_at"]
        settings = self.store.settings()
        vector = {"consent": machine.gate_consent(
            settings["enabled"], self.store.thread_enabled(thread), row["cancel_requested"],
            observe_only=self.observing(settings), hold=row["hold"])}
        if vector["consent"][0] != machine.PASS:
            return
        # P7, before anything of Codex's is read: the standard edition's plug, and one that defers,
        # cost nothing past this.
        if self.plug.schedule(row, sent) is not Alternative.RESEND:
            return
        vector["schedule"] = machine.gate_schedule(dict(row, next_retry_at=None), now,
                                                   quiet_until=self.quiet_until(now))
        if (vector["schedule"][0] != machine.PASS or self.engine_state() not in COMPATIBLE
                or not self.home_lock() or self.store.others_in_flight(thread, key)):
            return
        vector.update(engine_compatible=machine.gate(machine.PASS), single_owner=machine.gate(machine.PASS),
                      submission_safe=machine.gate(machine.PASS, machine.RESEND))
        if self._holds("submission_safe", row, vector) or not self.valid_interruption(row):
            return
        # Fresh throughout, from before the send: a watcher started since cannot say so.
        if not (self._watching_since < sent and self._stale_cleared_at < sent
                and self.fresh_throughout(thread, sent)):
            return
        proof = self.proof(row)
        for token in dict.fromkeys((proof, row["marker"])):
            presence = self.source.marker_presence(thread, token)
            if presence.get("history") or presence.get("queue"):
                return
        if self.source.later_turns(thread, row["ordinal"], proof) or self.source.foreign_queued(thread, proof):
            return
        category = row["category"]
        if not (failures.is_recoverable(category) and self.recovers(category)):
            return
        limits = self.limits()
        vector.update(identity=machine.gate(machine.PASS), known_failure=machine.gate(machine.PASS),
                      **machine.gate_budgets(row, limits, category == failures.USAGE_LIMIT))
        if (any(vector[name][0] != machine.PASS for name in BUDGETS)
                or self._holds("chain_budget", row, vector) or self._holds("no_progress_budget", row, vector)):
            return
        app = self.backend.app_identity()
        if not app or self.backend.loaded(thread, app) != "loaded":
            return
        vector["thread_available"] = machine.gate(machine.PASS)
        if self._holds("thread_available", row, vector):
            return
        vector["no_newer_user_work"] = machine.gate(machine.PASS)
        recent = self.store.recent_claims(thread, now - 86400)
        if (self.store.recent_claim_count(thread, now - 86400) >= self.options["max_submissions_per_thread_per_day"]
                or (recent and now - max(recent) < self.options["thread_cooldown_seconds"])
                or self._holds("attempt_budget", row, vector) or self.offline()
                or self.usage().get("available") is not True):
            return
        vector["usage"] = machine.gate(machine.PASS)
        if self._holds("usage", row, vector) or self._guarded(row, vector, now):
            return
        self.dispatch(row, app, vector, limits, resend=True)

    def _after_resend(self, reserved, outcome):
        """What came of a resend's send that was not accepted: an uncertain submission again, never a
        wait - not started, the conversation's consent refused at the launch guard, or unknown."""
        if outcome == "not_started":
            self.transition(reserved, "submission_unknown", "queue_process_not_started", delay=1)
        else:
            self.transition(reserved, "submission_unknown", "queue_result_unknown_do_not_resend", delay=1)

    def watch_resent(self):
        """Once a tick, paused or not, only for a plug that may ask, at most once a minute: a resent
        continuation that ran, sent in the last day, whose proof Codex's history now holds twice - the
        first copy arrived after all. Following its turn, it ends outcome_unverified; ended already,
        its reason is rewritten in place. Either way it says duplicate_marker, which the edition reads."""
        if self.plug.null:
            return
        now = self.clock()
        if self._resent_looked_at is not None and 0 <= now - self._resent_looked_at < DUPLICATE_LOOK_SECONDS:
            return
        self._resent_looked_at = now
        window = self.options["unknown_reconcile_window_seconds"]
        for row in self.store.records_in(OBSERVING | OUTCOMES):
            if (not machine.was_resent(row) or row["last_error"] == "duplicate_marker"
                    or now - (row["last_claim_at"] or 0) > window):
                continue
            try:
                if len(self.source.marker_rows(row["thread_id"], self.proof(row))) <= 1:
                    continue
                if row["state"] in OBSERVING:
                    self.transition(row, "outcome_unverified", "duplicate_marker")
                else:
                    self.store.update(row["interruption_id"], at=now, last_error="duplicate_marker")
            except Exception:
                self.log(row["thread_id"], "reconciliation_unavailable", None)
