"""What became of a continuation that was sent.

The watch loop, the marker that says a message of ours is in Codex's queue, taking one back,
and matching a turn that started to the record that asked for it. This is where a send that
may have happened is settled one way or the other - never guessed at.
"""
from __future__ import annotations

import time
from .. import failures, machine
from ..machine import OBSERVING, TERMINAL, WAITING, WATCHED


UNSENT = WAITING

# What an owned queue item becomes when it was taken back and nothing ran.
SETTLED = {
    "cancel": "cancelled", "thread_disabled": "cancelled",
    "superseded_by_user": "superseded_by_user", "user_queued_input": "superseded_by_user",
    "superseded": "superseded", "duplicate_owner": "superseded",
    "not_loaded": "failed", "expired": "failed",
    # Withdrawn by a Pause, but it was already an uncertain submission: final, never
    # released back to waiting.
    "paused_unknown": "failed",
}

_UNDETERMINED = object()


class ReconcileMixin:
    # --------------------------------------------------------------- the watch
    def watch_needed(self) -> bool:
        """Whether anything may be sitting in Codex's queue right now.

        While that is true the watcher looks every second instead of every poll: the
        window in which a person can start work ahead of our queued item is seconds long.
        """
        return any(machine.may_be_queued(row["state"], row["queue_id"])
                   for row in self.store.records_in(WATCHED))

    def watch(self):
        """One pass over everything that may be in Codex's queue. Runs paused or not.

        A record that owns a row in Codex's queue is looked at on every pass, whatever
        its schedule says: that row can be dispatched the moment the conversation's
        current turn ends. Everything else that is unresolved is looked at when due.
        The pass has a time budget, and starts one record further on each time, so one
        slow delete cannot keep the others waiting pass after pass.
        """
        now = self.clock()
        rows = self.store.records_in(WATCHED)
        if rows:
            start = self._watch_offset % len(rows)
            rows = rows[start:] + rows[:start]
            self._watch_offset += 1
        deadline = time.monotonic() + self.options["watch_budget_seconds"]
        for row in rows:
            if time.monotonic() > deadline:
                break
            if row["state"] == "submission_unknown" and row["queue_id"] is None:
                if (row.get("next_retry_at") or 0) > now:
                    continue
                submitted = row.get("submitted_at") or row.get("detected_at") or now
                if now - submitted > self.options["unknown_reconcile_window_seconds"]:
                    continue
            try:
                with self.dispatch_lock():
                    current = self.store.get(row["interruption_id"])
                    if current is not None and current["state"] in WATCHED:
                        self.watch_record(current)
            except Exception:
                self.log(row["thread_id"], "reconciliation_unavailable", None)

    def watch_record(self, row):
        """Follow one continuation that may be in Codex. Never sends anything."""
        now = self.clock()
        thread, marker = row["thread_id"], row["marker"]
        found = self.source.marker_rows(thread, marker)
        if len(found) > 1:
            # Our unique marker in two places cannot be explained by one send, so no
            # turn is picked. Anything still queued is still taken back.
            if row["state"] != "submission_unknown" or row["last_error"] != "duplicate_marker":
                self.transition(row, "submission_unknown", "duplicate_marker", delay=60)
            for item in self.source.queued_rows(thread, marker):
                self._delete(thread, item["id"])
            return
        if found:
            self.correlate(row, found[0])
            return
        if row["state"] == "withdrawn_unconfirmed":
            self.settle(row)
            return
        if row["queue_id"]:
            known = self.source.queue_row(thread, row["queue_id"], marker)
            if known["exists"] and not known["has_marker"]:
                # Somebody edited our queued message in Codex. It is theirs now: nothing
                # is deleted and nothing more is sent.
                self.transition(row, "handed_over", "queued_item_edited")
                return
        queued = self.source.queued_rows(thread, marker)
        if queued:
            self.guard_queued(row, queued)
            return
        if row["state"] == "submission_unknown":
            extra = {"queue_id": None} if row["queue_id"] else {}
            self.transition(row, "submission_unknown", row["last_error"] or "no_receipt_do_not_resend",
                            delay=self.options["conservative_poll_seconds"], **extra)
            return
        age = now - (row.get("submitted_at") or now)
        if age < self.options["delivery_timeout_seconds"]:
            # Between leaving the queue and appearing in history. Waiting is safe.
            self.transition(row, row["state"], "awaiting_delivery_receipt", delay=1)
        else:
            self.transition(row, "submission_unknown", "no_receipt_do_not_resend",
                            delay=self.options["conservative_poll_seconds"])

    def guard_queued(self, row, queued):
        """Our item is in Codex's queue. Leave it there only while it is still right."""
        reason = "duplicate_owner" if len(queued) > 1 else self.withdraw_reason(row)
        if reason is _UNDETERMINED:
            return
        if reason is None:
            item = queued[0]
            changes = {}
            if row["queue_id"] != item["id"]:
                changes["queue_id"] = item["id"]
            if row["recovery_client_id"] is None and item.get("client_id"):
                changes["recovery_client_id"] = item["client_id"]
            if row["state"] == "submitting":
                changes["first_queued_at"] = row["first_queued_at"] or self.clock()
                self.transition(row, "queued", None, delay=1, event="submitted", **changes)
            elif changes:
                self.store.update(row["interruption_id"], at=self.clock(), **changes)
            return
        if row["withdraw_failures"] and (row.get("next_retry_at") or 0) > self.clock():
            return                      # the last delete failed; the next one is paced
        self.withdraw(row, [item["id"] for item in queued], reason)

    def withdraw_reason(self, row):
        """Why our queued item must be taken back now, or None to leave it queued.

        Cancel and a disabled thread withdraw it at once; so does any sign that the
        failure it answers is no longer the thread's latest state, and then Pause. A
        turn that is running but has not yet recorded who started it is no evidence
        about who is ahead, so it holds back only the decisions that depend on that -
        the supersede and expiry withdrawals. It never holds back a cancel or a Pause:
        Codex starts the head of the queue the moment a turn ends, so waiting for that
        turn would deliver the very message the person just asked not to send.

        A submission already known to be uncertain is still withdrawn by a Pause, but
        under its own reason: a paused withdrawal can be released back to waiting, and
        an uncertain submission is never sent again, so this one settles as final.
        """
        now = self.clock()
        thread, marker = row["thread_id"], row["marker"]
        if row["cancel_requested"]:
            return "cancel"
        if not self.store.thread_enabled(thread):
            return "thread_disabled"
        turns = self.source.later_turns(thread, row["ordinal"], marker)
        undetermined = any(turn["kind"] == "undetermined" for turn in turns)
        if any(turn["kind"] == "foreign" for turn in turns):
            return "superseded_by_user"
        if self.source.foreign_queued(thread, marker):
            return "user_queued_input"
        if not turns and not self.valid_interruption(row):
            return "superseded"
        if not self.store.settings()["enabled"]:
            return "paused_unknown" if row["state"] == "submission_unknown" else "paused"
        if self.loaded(thread) == "notLoaded":
            return "not_loaded"
        if now - (row.get("submitted_at") or now) >= self.options["delivery_timeout_seconds"]:
            return _UNDETERMINED if undetermined else "expired"
        if self.projection_fresh(thread) is False:
            return "projection_stale"
        return _UNDETERMINED if undetermined else None

    def _delete(self, thread, queue_id):
        try:
            return self.backend.delete_queue(thread, queue_id) is True
        except Exception:
            return False

    def withdraw(self, row, queue_ids, reason):
        """Delete our queued item. A successful delete is not proof that it never ran:
        Codex can report the delete after the turn has already started. The settle
        that follows decides."""
        now = self.clock()
        thread, marker = row["thread_id"], row["marker"]
        results = [self._delete(thread, queue_id) for queue_id in queue_ids]
        if results and all(results):
            self.store.update(row["interruption_id"], at=now, event="withdraw",
                              flags=machine.FLAG_WITHDRAW_DELETED,
                              state="withdrawn_unconfirmed", withdraw_reason=reason,
                              withdrawn_at=now, withdraw_deleted=True, queue_id=queue_ids[0],
                              last_error=reason, next_retry_at=now + 1)
            self.log(thread, "withdrawn_unconfirmed", reason)
            return
        remaining = self.source.queued_rows(thread, marker)
        if remaining:
            attempts = row["withdraw_failures"] + 1
            pace = self.options["delete_retry_seconds"]
            if attempts >= self.options["max_withdraw_attempts"] and row["state"] != "submission_unknown":
                # Still watched on every pass while the row exists; only the deletes
                # are paced.
                self.transition(row, "submission_unknown", "queue_cleanup_unconfirmed", delay=pace,
                                withdraw_failures=attempts, queue_id=remaining[0]["id"])
            else:
                self.store.update(row["interruption_id"], at=now, withdraw_failures=attempts,
                                  next_retry_at=now + pace)
            return
        # Gone, but not by our hand: dispatched, or removed in Codex.
        self.store.update(row["interruption_id"], at=now, event="withdraw",
                          state="withdrawn_unconfirmed", withdraw_reason=reason, withdrawn_at=now,
                          withdraw_deleted=False, last_error=reason, next_retry_at=now + 1)
        self.log(thread, "withdrawn_unconfirmed", reason)

    def settle(self, row):
        """Decide what a withdrawn item became, once it can be decided.

        For the delivery window after the withdrawal the watch keeps looking for our
        marker. If it appears, the continuation ran after all and is followed like any
        other. If it never appears and Codex's history is known to be current, nothing
        ran. If the history cannot be trusted, the record stays unknown - never resent.
        """
        now = self.clock()
        thread, marker = row["thread_id"], row["marker"]
        queued = self.source.queued_rows(thread, marker)
        if queued:
            # Back in the queue, or never really gone: take it back again.
            for item in queued:
                self._delete(thread, item["id"])
            return
        # Looked at on every pass of the window, so a lag anywhere in it is known.
        self._projection_now(thread)
        if now - row["withdrawn_at"] < self.options["delivery_timeout_seconds"]:
            return
        fresh = self.fresh_throughout(thread, row["withdrawn_at"])
        reason = row["withdraw_reason"]
        if not fresh or reason == "projection_stale":
            self.transition(row, "submission_unknown", "withdraw_unconfirmed",
                            delay=self.options["conservative_poll_seconds"])
            return
        if reason == "paused":
            later = bool(self.source.later_turns(thread, row["ordinal"], marker))
            if self.store.release_withdrawn(
                    row["interruption_id"], now, window=self.options["delivery_timeout_seconds"],
                    later_turn=later, marker_rows=0, row_present=False, fresh=fresh,
                    target=self.waiting_state(row), next_retry_at=now):
                self.log(thread, "released_after_withdrawal", "paused")
                return
            self.transition(row, "submission_unknown", "withdraw_unconfirmed",
                            delay=self.options["conservative_poll_seconds"])
            return
        target = SETTLED.get(reason, "submission_unknown")
        self.transition(row, target, "duplicate_owner" if reason == "duplicate_owner"
                        else "owned_queue_removed")

    def correlate(self, row, found):
        """Our marker is in history: record the exact turn it started.

        That turn is the turn of the row holding the marker - never the thread's latest
        turn, which may already be somebody else's.
        """
        now = self.clock()
        if found["ordinal"] is not None and found["ordinal"] <= row["ordinal"]:
            self.transition(row, "submission_unknown", "ambiguous_receipt", delay=900)
            return
        if (row["recovery_client_id"] and found["client_id"]
                and row["recovery_client_id"] != found["client_id"]):
            self.transition(row, "submission_unknown", "ambiguous_receipt", delay=900)
            return
        if found["first_unset"] or found["turn_id"] is None:
            # Codex has not yet recorded who started that turn. Wait - bounded.
            submitted = row.get("submitted_at") or now
            if now - submitted > self.options["unknown_reconcile_window_seconds"]:
                self.transition(row, "submission_unknown", "ambiguous_receipt", delay=900)
            return
        client = found["client_id"] or row["recovery_client_id"]
        if not found["starts_turn"]:
            # Our text landed inside a turn somebody else started. That turn is theirs.
            if self.store.correlate(row["interruption_id"], found["turn_id"], now, client_id=client,
                                    status=found["status"], state="handed_over",
                                    reason="marker_not_turn_initiator", user_joined=True):
                self.log(row["thread_id"], "handed_over", "marker_not_turn_initiator")
            else:
                self.transition(row, "submission_unknown", "ambiguous_receipt", delay=900)
            return
        turns = self.source.later_turns(row["thread_id"], row["ordinal"], row["marker"])
        before_ours = any(turn["kind"] == "foreign" and turn["ordinal"] < found["ordinal"]
                          for turn in turns)
        withdrawn = row["state"] == "withdrawn_unconfirmed"
        after_user = before_ours or row["withdraw_reason"] in machine.SUPERSEDE_WITHDRAWALS
        extra = None
        if withdrawn and row["withdraw_reason"] == "paused":
            extra = "dispatched_while_paused"
        elif withdrawn and row["withdraw_deleted"]:
            extra = "dispatched_despite_delete"
        elif before_ours:
            extra = "continuation_after_user_turn"
        if not self.store.correlate(row["interruption_id"], found["turn_id"], now, client_id=client,
                                    status=found["status"], after_user_work=after_user,
                                    extra_event=extra):
            self.transition(row, "submission_unknown", "ambiguous_receipt", delay=900)
            return
        self.log(row["thread_id"], "turn_started", extra)
        self.announce("result", row, state="turn_started", reason=None)
