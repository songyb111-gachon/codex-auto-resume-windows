"""Records of the edition's own, tried like core's (v0.6.14: P2 carried out).

Once a tick, after core's own due records, the edition's plug hands core the records of its own store
that are due now, and those of them in flight (domain/plug.py, Guarded.records: eight at most, each a
64-hex id, a canonical conversation id, the marker core would give that id, waiting with words or in
flight with none). What a record waiting says is a person's own message, written in the Dashboard for
a time they chose; core checks the words again here (continuation.validate_prompt) and drops a record
whose words fail, so text that is empty, holds a marker or is one of the product's own continuations
is never sent.

Core carries each out as it carries out its own, and nothing of it is the plug's to do:

* waiting: core's gates in A8's order, where one applies to words that are not a continuation -
  consent (recovery on, not only observed, the conversation on, no administrator's DisableAutoResume),
  the schedule (quiet hours; when it is due is the plug's), engine_compatible, single_owner,
  submission_safe (nothing of core's that may be queued in the conversation), identity (the projection
  current), thread_available (the app holds it; never a route, P16), no_newer_user_work (nothing of
  someone else's queued), Wait for an internet connection, and usage. The budgets, the chain and
  known_failure are a recovery's, and this is no recovery: the plug's ledger counts its claims against
  core's, the day's five and the fifteen minutes in one conversation across both stores.
* the send: the one dispatch (engine/dispatch.py), which binds the one sender as it does for every send
  - and a channel the plug names for one of these is never used: it waits instead. The claim is the
  store's own transaction (store/claims.py, reserve_record), which asks again for consent and quiet
  hours, and nothing of core's in flight, and then the plug's ledger; the pre-send look follows; and the
  one send carries the words, a blank line and the marker, inside a launch guard that asks consent and
  the ledger once more (record_guard).
* in flight: its marker found in Codex's history is delivered; none a day after it was sent is unproven,
  and never sent again (A6).

Every move is told at P14 (RecordMove), and every wait with its gate and the gate's reason: the plug
keeps its own record, and learns what became of it from core, as it learns of core's own records.
The standard edition's plug hands over none, so none of this runs there.
"""
from __future__ import annotations

from .. import continuation, machine, power
from ..domain.plug import RecordMove

# The two states a record the plug hands over is in (Guarded.records).
WAITING_RECORD, IN_FLIGHT_RECORD = "waiting", "in_flight"
# How many records a would-send line is remembered for, in a process, before all are forgotten.
NOTED_LIMIT = 512
COMPATIBLE = ("verified", "checked", "structurally_compatible")
# The log's fixed line for what came of a send (logbook.py).
SENT_LINES = {RecordMove.RELEASED: "plug_record_released", RecordMove.NOT_STARTED: "plug_record_not_started"}


class PlugRecordsMixin:
    def plug_records(self, view):
        """P2: every record the plug hands over, each tried, sent or watched once (above). One that
        raises costs only itself."""
        for record in self.plug.records(view):
            try:
                if record["state"] == IN_FLIGHT_RECORD:
                    self._watch_record(record)
                elif self._worded(record):
                    self._try_record(record)
            except Exception:
                self.log(record["thread_id"], "plug_record_check_failed", None)

    @staticmethod
    def _worded(record) -> bool:
        """Whether a waiting record's words are a person's own that may be sent (A26, A27 as P2 keeps
        them): checked here again, whatever the plug checked, and a record whose words fail is dropped."""
        try:
            continuation.validate_prompt(record["words"])
        except (continuation.PromptError, TypeError):
            return False
        return True

    def _record_told(self, record, move, gate=None, reason=None):
        """P14 for a record of the plug's: `move` (RecordMove), with the gate and the reason of a wait."""
        told = dict(record) if gate is None else dict(record, gate=gate, reason=reason)
        self.plug.moved(told, move)

    def _record_waits(self, record, gate, reason) -> None:
        self._record_told(record, RecordMove.WAITING, gate, reason)

    def _try_record(self, record):
        """The gates for one waiting record, and the one dispatch where every one passes."""
        thread, now = record["thread_id"], self.clock()
        settings = self.store.settings()
        if not settings["enabled"] or self.managed.disable_auto_resume:
            return self._record_waits(record, "consent", "paused")
        if not self.store.thread_enabled(thread):
            return self._record_waits(record, "consent", "thread_disabled")
        if self.observing(settings):
            self._record_would_send(record)
            return self._record_waits(record, "consent", machine.OBSERVE_ONLY)
        if self.quiet_until(now) is not None:
            return self._record_waits(record, "schedule", machine.QUIET_HOURS)
        compatibility = self.engine_state()
        if compatibility not in COMPATIBLE:
            return self._record_waits(record, "engine_compatible", "engine_incompatible"
                                      if compatibility in ("incompatible", "failed_here") else "engine_unknown")
        if not self.home_lock():
            return self._record_waits(record, "single_owner", "home_lock_unavailable")
        if self.store.others_in_flight(thread, record["record_id"]):
            return self._record_waits(record, "submission_safe", "other_recovery_in_flight")
        fresh = self._projection_now(thread)
        if fresh is not True:
            return self._record_waits(record, "identity", "projection_stale" if fresh is False
                                      else "projection_table_missing")
        app = self.backend.app_identity()
        if not app:
            return self._record_waits(record, "thread_available", "desktop_app_unavailable")
        loaded = self.backend.loaded(thread, app)
        if loaded != "loaded":
            return self._record_waits(record, "thread_available",
                                      "notLoaded" if loaded == "notLoaded" else "loaded_state_unknown")
        if self.source.foreign_queued(thread, record["marker"]):
            return self._record_waits(record, "no_newer_user_work", "user_input_queued")
        if self.offline():
            return self._record_waits(record, "usage", power.OFFLINE)
        usage = self.usage()
        if usage.get("available") is not True:
            return self._record_waits(record, "usage", "usage_unavailable" if usage.get("available") is False
                                      else "usage_unknown")
        self.dispatch(record, app, None, None, record=True)

    def _record_would_send(self, record) -> None:
        """Observe only: every gate a record of the plug's would meet is not asked, and the line that
        says one would have been sent now is written once for it in a process."""
        noted = self._records_noted
        if record["record_id"] in noted:
            return
        if len(noted) >= NOTED_LIMIT:
            noted.clear()
        noted.add(record["record_id"])
        self.log(record["thread_id"], "plug_record_would_send", None)

    def _record_claim(self, record, sender, app):
        """The claim and the pre-send look for a record of the plug's: (conversation, words, launch
        guard) for the one send, or None where it waits, or was handed back, or was sent already."""
        if sender is not self.backend:
            # A channel the plug named is never used for one of these: core's backend or nothing.
            self._record_waits(record, "submission_safe", machine.HELD)
            return None
        now = self.clock()
        claimed, gate, reason = self.store.reserve_record(record, now, ledger=self.plug,
                                                          quiet_until=self.quiet_until(now))
        if not claimed:
            self._record_waits(record, gate, reason)
            return None
        try:
            problem = self._record_problem(record, app)
        except Exception:
            # A look that could not be made is one that failed: the claim is handed back, never kept
            # in flight with nothing launched - which would hold the conversation for good.
            problem = RecordMove.RELEASED, "submission_safe", "released_before_send"
        if problem is not None:
            move, gate, reason = problem
            self._record_told(record, move, gate, reason)
            self.log(record["thread_id"], "plug_record_released", None)
            return None
        self.log(record["thread_id"], "plug_record_send_started", None)
        return (record["thread_id"], record["words"] + "\n\n" + record["marker"],
                self.store.record_guard(record, self.plug, self.clock()))

    def _record_problem(self, record, app):
        """The last look before the one send of a record of the plug's: (move, gate, reason) to tell, or
        None to send. Anything that changed since its gates - a Pause, the conversation switched off,
        quiet hours, the app or its hold on the conversation, usage, a newer queued message - hands the
        claim back (RELEASED), and so does a look that raises (`_record_claim`); a copy of its marker
        already in Codex is the message sent already (SENT), never a second one."""
        thread, now = record["thread_id"], self.clock()
        settings = self.store.settings()
        if (not settings["enabled"] or self.managed.disable_auto_resume or self.observing(settings)
                or not self.store.thread_enabled(thread) or self.quiet_until(now) is not None):
            return RecordMove.RELEASED, "consent", "released_before_send"
        if self.backend.app_identity() != app or self.backend.loaded(thread, app) != "loaded":
            return RecordMove.RELEASED, "thread_available", "loaded_recheck_failed"
        if self.usage().get("available") is not True:
            return RecordMove.RELEASED, "usage", "usage_recheck_failed"
        if self._projection_now(thread) is not True:
            return RecordMove.RELEASED, "identity", "projection_stale"
        if self.source.foreign_queued(thread, record["marker"]):
            return RecordMove.RELEASED, "no_newer_user_work", "user_input_queued"
        presence = self.source.marker_presence(thread, record["marker"])
        if presence.get("history") or presence.get("queue"):
            return RecordMove.SENT, "submission_safe", "duplicate_owner"
        if not self.home_lock():
            return RecordMove.RELEASED, "single_owner", "home_lock_unavailable"
        return None

    def _record_sent(self, record, response) -> None:
        """What came of the one send of a record of the plug's: a launch the guard refused hands it
        back (RELEASED), a process that never started waits again with its words (NOT_STARTED), and
        anything else - accepted, or nothing that says - is sent (SENT), never sent again (A6)."""
        outcome = response.get("outcome")
        if outcome == "not_started":
            move = (RecordMove.RELEASED if response.get("error_code") == "queue_consent_refused"
                    else RecordMove.NOT_STARTED)
        else:
            move = RecordMove.SENT
        self._record_told(record, move)
        self.log(record["thread_id"], SENT_LINES.get(move, "plug_record_sent"), None)

    def _watch_record(self, record) -> None:
        """A record of the plug's in flight: delivered once its marker is in Codex's history; unproven
        a day after it was sent with none there - and never sent again."""
        if self.source.marker_rows(record["thread_id"], record["marker"]):
            self._record_told(record, RecordMove.DELIVERED)
            return
        sent = record["sent_at"]
        if sent is not None and self.clock() - sent >= self.options["unknown_reconcile_window_seconds"]:
            self._record_told(record, RecordMove.UNPROVEN)
