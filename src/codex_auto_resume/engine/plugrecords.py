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
  - and a channel the plug names for one of these is never used: it waits instead (from v0.6.19 but for a
  person's MESSAGE the plug carries marker-free, engine/recordchannel.py). The claim is the
  store's own transaction (store/claims.py, reserve_record), which asks again for consent and quiet
  hours, and nothing of core's in flight, and then the plug's ledger; the pre-send look follows; and the
  one send carries the words, a blank line and the marker, inside a launch guard that asks consent and
  the ledger once more (record_guard).
* in flight: its marker found in Codex's history is delivered; none a day after it was sent is unproven,
  and never sent again (A6).

From v0.6.15-beta a record says what its words are (plughands.RecordPurpose): a person's MESSAGE, or a
CONTINUATION in the edition's own catalog words (continuation.validate_continuation). Either goes only to a
person's own desktop conversation - one `LocalSource.latest` reads: not archived, not a subagent's, the
predicate detection uses (A15) - else it waits (identity, not_user_conversation); nothing is ever written
into a child. A CONTINUATION goes only while the turn it follows is still the conversation's latest, final
and with nothing after it; else it is SUPERSEDED, told once and never sent (A17 for it). Both are asked
again in the last look. In flight, a queue item Codex said it took that a person edited is HANDED_OVER -
theirs, never deleted and never unproven - and one a person cancelled, or every one while recovery is
paused or its conversation off, is taken back out of Codex's queue (WITHDRAWN), as core takes its own back
(H4, H6); one Codex will not give back is WITHDRAW_REFUSED, left there and watched, and never sent twice.

Every move is told at P14 (RecordMove), and every wait with its gate and the gate's reason: the plug
keeps its own record, and learns what became of it from core, as it learns of core's own records.
The standard edition's plug hands over none, so none of this runs there.
"""
from __future__ import annotations

from .. import continuation, machine, power
from ..domain.plug import RecordMove
from ..domain.plughands import RecordPurpose

# The two states a record the plug hands over is in (Guarded.records).
WAITING_RECORD, IN_FLIGHT_RECORD = "waiting", "in_flight"
# How many records a would-send line is remembered for, in a process, before all are forgotten.
NOTED_LIMIT = 512
COMPATIBLE = ("verified", "checked", "structurally_compatible")
# The log's fixed line for what came of a send (logbook.py).
SENT_LINES = {RecordMove.RELEASED: "plug_record_released", RecordMove.NOT_STARTED: "plug_record_not_started"}
# A turn whose ending is known, which a continuation may follow (codex/values.py KNOWN_STATUSES less inProgress).
FINAL = frozenset({"completed", "failed", "interrupted"})
# The moves after which a record is no longer core's to watch.
ENDED = frozenset({RecordMove.DELIVERED, RecordMove.UNPROVEN, RecordMove.HANDED_OVER, RecordMove.WITHDRAWN,
                   RecordMove.SUPERSEDED})


class PlugRecordsMixin:
    def plug_records(self, view):
        """P2: every record the plug hands over, each tried, sent or watched once (above). One that
        raises costs only itself."""
        for record in self.plug.records(view):
            try:
                if record["state"] == IN_FLIGHT_RECORD:
                    record = self._record_carried(self._record_queued(record))   # v0.6.19 (recordchannel.py)
                    self._flying()[record["record_id"]] = record
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
            if record["purpose"] in (RecordPurpose.CONTINUATION, RecordPurpose.WRAP_UP):
                continuation.validate_continuation(record["words"])
            else:
                continuation.validate_prompt(record["words"])
        except (continuation.PromptError, TypeError, KeyError):
            return False
        return True

    def _not_ones_own(self, record):
        """(move, gate, reason) for a record that may not go to its conversation now, or None (v0.6.15-beta): not a
        person's own desktop conversation - archived, a subagent's, nothing the history reader takes - waits; a
        CONTINUATION whose turn is no longer the latest, not ended, or has anything after it is SUPERSEDED."""
        thread = record["thread_id"]
        latest = self.source.latest(thread)
        if latest is None:
            return RecordMove.WAITING, "identity", "not_user_conversation"
        if record["purpose"] == RecordPurpose.WRAP_UP:
            # v0.6.16-beta.3: a wrap-up goes only into the very turn it was made for, while it still runs.
            if latest.get("ordinal") != record["ordinal"] or latest.get("status") != "inProgress":
                return RecordMove.SUPERSEDED, "identity", "latest_turn_changed"
            return None
        if record["purpose"] != RecordPurpose.CONTINUATION:
            return None
        if (latest.get("ordinal") != record["ordinal"] or latest.get("status") not in FINAL
                or self.source.later_turns(thread, record["ordinal"], record["marker"])):
            return RecordMove.SUPERSEDED, "identity", "latest_turn_changed"
        return None

    def _record_told(self, record, move, gate=None, reason=None):
        """P14 for a record of the plug's: `move` (RecordMove), with the gate and the reason of a wait."""
        told = dict(record) if gate is None else dict(record, gate=gate, reason=reason)
        if move in ENDED:
            self._flying().pop(record["record_id"], None)
        self.plug.moved(told, move)

    def _wrap_up_markers(self) -> dict:
        """The markers of the wrap-ups delivered in each conversation in this process (v0.6.16-beta.3), by thread."""
        found = self.__dict__.setdefault("_wrap_ups", {})
        if len(found) > NOTED_LIMIT:
            found.clear()
        return found

    def persons_turns(self, thread, turns) -> list:
        """`turns` (later_turns') less those a wrap-up of this product's started (v0.6.16-beta.3, usage_wrap_up): its
        message is the product's own, so the turn it starts is never the person's work (A17) and never supersedes a
        recovery as theirs. Known for the wrap-ups delivered while this process ran; a turn that cannot be looked at
        is the person's, as before."""
        markers = sorted(self._wrap_up_markers().get(thread, ()))
        if not markers:
            return list(turns)
        kept = []
        for turn in turns:
            try:
                ours = turn.get("turn_id") is not None and bool(self.source.turn_markers(thread, turn["turn_id"],
                                                                                          markers))
            except Exception:
                ours = False
            if not ours:
                kept.append(turn)
        return kept

    def _flying(self) -> dict:
        """The plug's records this engine watched in flight (v0.6.15-beta), by id, until each ends: what a Pause
        takes back out of Codex's queue while the plug is asked nothing (`paused_records`)."""
        found = self.__dict__.setdefault("_records_flying", {})
        if len(found) > NOTED_LIMIT:
            found.clear()
        return found

    def paused_records(self):
        """While recovery is paused, the plug's records core watched in flight, each looked at as its watch looks -
        delivered, handed over, or taken back out of Codex's queue (H4) - with the plug asked nothing (K5) and told
        each move (P14). One that raises costs only itself."""
        for record in list(self._flying().values()):
            try:
                self._watch_record(record)
            except Exception:
                self.log(record["thread_id"], "plug_record_check_failed", None)

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
        found = self._not_ones_own(record)
        if found is not None:
            move, gate, reason = found
            return self._record_told(record, move, gate, reason)
        app = self.backend.app_identity()
        if not app:
            return self._record_waits(record, "thread_available", "desktop_app_unavailable")
        loaded = self.backend.loaded(thread, app)
        if loaded != "loaded":
            return self._record_waits(record, "thread_available",
                                      "notLoaded" if loaded == "notLoaded" else "loaded_state_unknown")
        if self.source.foreign_queued(thread, self._record_proof(record)):
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
        if (sender is self.backend) != (self._record_client(record) is None):
            # A channel the plug named is used only for a person's message it carries marker-free, and that message
            # only through it (engine/recordchannel.py): core's backend or nothing.
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
        return (record["thread_id"], self._record_words(record),
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
        found = self._not_ones_own(record)
        if found is not None:
            move, gate, reason = found
            return (RecordMove.RELEASED if move == RecordMove.WAITING else move), gate, reason
        if self.source.foreign_queued(thread, self._record_proof(record)):
            return RecordMove.RELEASED, "no_newer_user_work", "user_input_queued"
        presence = self.source.marker_presence(thread, self._record_proof(record))
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
        queue_id = response.get("queue_id") if move == RecordMove.SENT else None
        sent = dict(record, queue_id=queue_id if isinstance(queue_id, str) else None)
        self._record_told(sent, move)
        if move == RecordMove.SENT:
            # Remembered from its send, so a Pause before the next tick that watches it takes it back too (H4).
            self._flying()[record["record_id"]] = dict(sent, state="in_flight", words=None, sent_at=self.clock(),
                                                       withdraw=False)
        self.log(record["thread_id"], SENT_LINES.get(move, "plug_record_sent"), None)

    def _watch_record(self, record) -> None:
        """A record of the plug's in flight: delivered once its marker is in Codex's history; unproven
        a day after it was sent with none there - and never sent again."""
        thread = record["thread_id"]
        if self.source.marker_rows(thread, self._record_proof(record)):
            if record.get("purpose") == RecordPurpose.WRAP_UP:
                # v0.6.16-beta.3: the turn it started is this product's own, never the person's work (persons_turns).
                self._wrap_up_markers().setdefault(thread, set()).add(record["marker"])
            self._record_told(record, RecordMove.DELIVERED)
            return
        queued = record["queue_id"] is not None and self.source.queue_row(thread, record["queue_id"],
                                                                          self._record_proof(record))
        if queued and queued["exists"] and not queued["has_marker"]:
            # Somebody edited it in Codex's queue: it is theirs now. Never deleted, never unproven, no trip.
            self._record_told(record, RecordMove.HANDED_OVER)
            return
        if queued and queued["exists"] and self._take_back(record):
            return
        sent = record["sent_at"]
        if sent is not None and self.clock() - sent >= self.options["unknown_reconcile_window_seconds"]:
            self._record_told(record, RecordMove.UNPROVEN)

    def _take_back(self, record) -> bool:
        """A record still in Codex's queue a person cancelled - or any while recovery is paused or its conversation off
        (the owner's answer of 2026-10-09) - taken back out of the queue, as core takes back its own (H4, H6): told
        WITHDRAWN once Codex says it deleted it and its marker is nowhere in the history; told WITHDRAW_REFUSED where
        Codex would not, and left there - never sent a second time. True where it was asked for back."""
        thread = record["thread_id"]
        settings = self.store.settings()
        paused = not settings["enabled"] or bool(self.managed.disable_auto_resume)
        if not (record["withdraw"] or paused or not self.store.thread_enabled(thread)):
            return False
        refused = self.__dict__.setdefault("_back_refused", set())
        if record["record_id"] in refused:
            return False                     # asked once and refused: watched as it is, never asked every tick
        deleted = self.backend.delete_queue(thread, record["queue_id"])
        if deleted is True and not self.source.marker_rows(thread, self._record_proof(record)):
            self._record_told(record, RecordMove.WITHDRAWN, "consent", "paused" if paused else "user_cancelled")
            self.log(thread, "plug_record_withdrawn", None)
        else:
            if len(refused) >= NOTED_LIMIT:
                refused.clear()
            refused.add(record["record_id"])
            self._record_told(record, RecordMove.WITHDRAW_REFUSED, "consent", "withdraw_unconfirmed")
            self.log(thread, "plug_record_withdraw_refused", None)
        return True
