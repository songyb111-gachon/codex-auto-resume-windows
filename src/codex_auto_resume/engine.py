"""Fail-closed scheduler. Codex history stays read-only; transport is injected.

Every decision that can lead to ``backend.send`` is re-checked inside the dispatch
lock, then again by the store inside the claim, and then once more immediately before
the queue process starts. The only retryable send failure is a proven "process never
started"; any other uncertainty ends in ``submission_unknown`` and is never resent.

After a send the engine follows *its own* continuation, not the thread. The turn it
started is the turn of the history row that holds its marker; what that turn did is
read from that turn alone; and while the item still sits in Codex's queue, the engine
takes it back the moment anything makes it the wrong thing to run.
"""
from contextlib import nullcontext
import time

from . import failures, machine, messages, settings as policy
from .machine import OBSERVING, TERMINAL, WAITING
from .source import detect

# Sent into the exact conversation that stopped. One text per kind of stop, in the
# language the Codex app itself is using.
CONTINUATIONS = {
    ("ko", "usage"): (
        "사용량 제한으로 중단된 이전 작업을 계속 진행해. 먼저 현재 스레드 컨텍스트와 "
        "실제 저장소/파일 상태를 확인하고, 이미 완료된 작업은 반복하지 말고 원래 목표를 "
        "계속 수행해. 기존 Goal이 있다면 그 상태와 목표를 유지해."),
    ("ko", "transient"): (
        "일시적인 연결 또는 서비스 오류로 중단된 이전 작업을 계속 진행해. 먼저 현재 스레드 "
        "컨텍스트와 실제 저장소/파일 상태를 확인하고, 이미 완료된 작업은 반복하지 말고 원래 "
        "목표를 계속 수행해. 기존 Goal이 있다면 그 상태와 목표를 유지해."),
    ("en", "usage"): (
        "Continue the previous task, which stopped because of a usage limit. First check the "
        "current thread context and the actual repository and file state, do not repeat work "
        "that is already done, and keep working toward the original goal. If there is an "
        "existing Goal, keep its status and objective."),
    ("en", "transient"): (
        "Continue the previous task, which stopped because of a temporary connection or service "
        "error. First check the current thread context and the actual repository and file state, "
        "do not repeat work that is already done, and keep working toward the original goal. If "
        "there is an existing Goal, keep its status and objective."),
}
CONTINUATION = CONTINUATIONS[("ko", "usage")]


def continuation(category, language="en") -> str:
    kind = "usage" if category == failures.USAGE_LIMIT else "transient"
    return CONTINUATIONS[(language if language in messages.SUPPORTED else "en", kind)]


UNSENT = WAITING
# Everything that may be sitting in Codex's queue, or may have just left it.
WATCHED = frozenset({"submitting", "queued", "withdrawn_unconfirmed", "submission_unknown"})
# A transient failure waits on a bounded ladder, never on a usage reset. The two
# policies stay separate on purpose: a usage limit has a real reset timestamp to
# wait for, a dropped connection has nothing but elapsed time.
TRANSIENT_BACKOFF = (5, 15, 30, 60, 120)
# States worth telling a person about, and which notification setting governs each.
# Only outcomes appear here: the waiting states change constantly and announcing them
# would turn a useful signal into noise nobody reads.
NOTIFY_ON_STATE = {
    "turn_started": "result",
    "failed": "result",
    "submission_unknown": "result",
    "retry_budget_exhausted": "stopped",
    "no_progress_exhausted": "stopped",
    "terminal_failure": "stopped",
}
# Bounded exponential backoff for proven "queue process never started" failures.
BACKOFF_LADDER = (30, 60, 120, 300)
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


def backoff_delay(retry: int) -> int:
    """retry is 1-based: 30s, 1m, 2m, 5m, then 5m forever (bounded by retry cap)."""
    index = max(0, min(int(retry) - 1, len(BACKOFF_LADDER) - 1))
    return BACKOFF_LADDER[index]


def transient_delay(attempt: int) -> int:
    """attempt is 1-based; the ladder is bounded and never grows without limit."""
    index = max(0, min(int(attempt) - 1, len(TRANSIENT_BACKOFF) - 1))
    return TRANSIENT_BACKOFF[index]


class Engine:
    def __init__(self, store, source, backend, *, dispatch_lock=nullcontext,
                 clock=time.time, log=None, options=None, notify=None, language=None,
                 home_lock=None, engine_state=None):
        self.store, self.source, self.backend = store, source, backend
        self.dispatch_lock, self.clock = dispatch_lock, clock
        self.log = log or (lambda *args: None)
        self.notify = notify or (lambda *args: None)
        self.language = language or "en"
        # Whether this watcher holds the lock on its Codex home, and what the Codex
        # engine compatibility check concluded. Both are owned by the process.
        self.home_lock = home_lock or (lambda: True)
        self.engine_state = engine_state or (lambda: "verified")
        self.options = {"reset_grace_seconds": 60, "conservative_poll_seconds": 900,
                        "state_poll_seconds": 60, "delivery_timeout_seconds": 180,
                        "max_queue_retries": 5, "max_submissions_per_thread_per_day": 5,
                        "thread_cooldown_seconds": 900,
                        # Failures that completed up to this long before `enable` are
                        # still eligible, as long as they remain the thread's latest turn.
                        "detection_lookback_seconds": 6 * 3600,
                        # An unresolved submission, or a recovery turn that never
                        # finishes, is followed for this long and then left as unknown.
                        "unknown_reconcile_window_seconds": 24 * 3600,
                        # General transient recovery is strictly bounded: a chain that
                        # keeps failing, or keeps producing nothing, is abandoned.
                        "max_recovery_attempts": 4,
                        "max_no_progress": 3,
                        # How many continuations one task may receive in total, whatever
                        # each individual failure was.
                        "max_chain_continuations": 6,
                        # A finished turn is judged this long after it finished, so items
                        # Codex is still writing are counted.
                        "settle_seconds": 10,
                        # How long Codex's history may lag its own file before nothing
                        # is decided from it.
                        "projection_grace_seconds": 120,
                        # A usage limit that never lifts is eventually given up on.
                        "usage_never_available_seconds": 7 * 86400,
                        "usage_after_reset_seconds": 24 * 3600,
                        "loaded_check_seconds": 5,
                        "max_withdraw_attempts": 5,
                        # A delete that failed is tried again at most this often: each
                        # one starts a Codex process.
                        "delete_retry_seconds": 10,
                        # How long one watch pass may take before the rest waits.
                        "watch_budget_seconds": 5,
                        # The ladder a transient failure waits on, and the categories the
                        # user has left switched on. None means "every category the
                        # classifier can produce" - the shipped behaviour.
                        "retry_ladder": TRANSIENT_BACKOFF,
                        "recoverable_categories": None,
                        **(options or {})}
        self._usage_cache = None
        self._declined = set()
        self._announced = set()
        self._stale_since = {}
        self._stale_seen = {}
        self._loaded_cache = {}
        self._watch_offset = 0

    # ------------------------------------------------------------------ policy
    def apply_policy(self, values) -> None:
        """Adopt the user's configurable policy.

        Policy only. Nothing here can widen what the classifier treats as recoverable,
        shorten a revalidation, resend an uncertain submission or lift any other safety
        gate - those are properties of the engine, not preferences. The worst a bad
        settings file can do through this method is make recovery more conservative,
        because every value it reads has already been coerced to a sane default.
        """
        values = policy.coerce(values)
        self.options["max_recovery_attempts"] = values["max_recovery_attempts"]
        self.options["max_no_progress"] = values["max_no_progress"]
        self.options["max_chain_continuations"] = values["max_chain_continuations"]
        self.options["retry_ladder"] = policy.timing_ladder(values)
        self.options["detection_lookback_seconds"] = float(values["detection_lookback_hours"]) * 3600.0
        self.options["recoverable_categories"] = frozenset(
            category for category in policy.CONFIGURABLE_CATEGORIES
            if policy.category_enabled(values, category))

    def limits(self) -> dict:
        return {name: self.options[name] for name in
                ("max_recovery_attempts", "max_no_progress", "max_chain_continuations")}

    def recovers(self, category) -> bool:
        """Whether the user has left this category of failure switched on.

        A category with no switch is recovered: the classifier already decided it is
        safe, and the absence of a toggle is not an instruction to stop.
        """
        allowed = self.options.get("recoverable_categories")
        if allowed is None or category not in policy.CONFIGURABLE_CATEGORIES:
            return True
        return category in allowed

    def delay_for(self, attempt: int) -> int:
        """The configured wait before the next attempt at a transient failure."""
        ladder = self.options.get("retry_ladder") or TRANSIENT_BACKOFF
        return ladder[max(0, min(int(attempt) - 1, len(ladder) - 1))]

    def first_delay(self, category) -> int:
        # Codex already retried a rate limit several times before giving up, so the
        # first wait is never shorter than a minute.
        if category == "rate_limit_transient":
            return max(60, self.delay_for(1))
        return self.delay_for(1)

    # ----------------------------------------------------------------- helpers
    def transition(self, row, state, reason=None, delay=None, event=None, **extra):
        values = {"state": state, "last_error": reason, **extra}
        if delay is not None:
            values["next_retry_at"] = self.clock() + delay
        if state in TERMINAL and state != row.get("state") and "outcome_at" not in extra:
            values["outcome_at"] = self.clock()
        self.store.update(row["interruption_id"], at=self.clock(), event=event, **values)
        changed = row.get("state") != state
        if changed or row.get("last_error") != reason:
            self.log(row["thread_id"], state, reason)
        # Announced from the transition itself, so the notification and the recorded
        # state can never disagree, and only on a real change - a record that keeps
        # re-entering the same state says nothing new.
        if changed and state in NOTIFY_ON_STATE:
            self.announce(NOTIFY_ON_STATE[state], row, state=state, reason=reason)

    def announce(self, event, row, **detail):
        """Tell the user something happened. Never affects what happens.

        Deduplicated per interruption, event and state: a late delivery after an
        unknown result is still announced, but nothing is announced twice. Any failure
        inside the notifier is swallowed here, because a toast that cannot be drawn must
        never decide whether a task is recovered.
        """
        key = (row.get("interruption_id"), event, detail.get("state"))
        if key in self._announced:
            return
        if len(self._announced) > 4096:
            self._announced.clear()
        self._announced.add(key)
        try:
            self.notify(event, {"thread_id": row.get("thread_id"),
                                "interruption_id": row.get("interruption_id"),
                                "category": row.get("category"),
                                "reset_at": row.get("reset_at"), **detail})
        except Exception:
            self.log(row.get("thread_id"), "notification_failed", event)

    def waiting_state(self, row) -> str:
        """The wait a record returns to when it goes back to waiting."""
        if row["category"] == failures.USAGE_LIMIT:
            reset = row.get("reset_at")
            return "waiting_reset" if reset is not None and reset > self.clock() else "waiting_poll"
        return "waiting_backoff"

    def valid_interruption(self, row):
        latest = self.source.latest(row["thread_id"])
        found = detect(latest) if latest else None
        return found is not None and found["interruption_id"] == row["interruption_id"]

    def supersede_reason(self, row):
        """Why this interruption is no longer the one to recover.

        A later turn on the exact thread means work continued without us - by the user,
        or by Codex itself - so the old failure must not be resumed on top of it.
        """
        try:
            progress = self.source.progress(row["thread_id"], row["ordinal"])
        except Exception:
            progress = {}
        if progress.get("later_turn"):
            return "superseded_by_user", "later_turn_exists"
        return "superseded", "latest_turn_changed"

    def allowed(self, row):
        return (self.store.settings()["enabled"] and self.store.thread_enabled(row["thread_id"])
                and not row.get("cancel_requested"))

    def usage(self):
        now = self.clock()
        if self._usage_cache is None or now - self._usage_cache[0] > 30:
            self._usage_cache = (now, self.backend.usage())
        return self._usage_cache[1]

    def loaded(self, thread_id):
        """The loaded state of one thread, re-read at most every few seconds."""
        now = self.clock()
        cached = self._loaded_cache.get(thread_id)
        if cached and now - cached[0] < self.options["loaded_check_seconds"]:
            return cached[1]
        app = self.backend.app_identity()
        value = self.backend.loaded(thread_id, app) if app else "unknown"
        if len(self._loaded_cache) > 512:
            self._loaded_cache.clear()
        self._loaded_cache[thread_id] = (now, value)
        return value

    def _projection_now(self, thread_id):
        """Exactly current right now: True, False (behind, or not knowable), or None
        when the projection table itself is missing. Also records what was seen, so a
        lag is measured from when it began, not from when a decision first looked."""
        try:
            found = self.source.projection(thread_id)
        except Exception:
            found = {"table": None, "fresh": None}
        if found.get("table") is False:
            return None
        now = self.clock()
        if found.get("fresh") is True:
            self._stale_since.pop(thread_id, None)
            return True
        if len(self._stale_since) > 512:
            self._stale_since.clear()
            self._stale_seen.clear()
        self._stale_since.setdefault(thread_id, now)
        self._stale_seen[thread_id] = now
        return False

    def projection_fresh(self, thread_id):
        """True when Codex's history is current enough to decide from, False when it
        has lagged for longer than the grace period, None when that cannot be told
        because the projection table itself is missing.

        A short lag passes: Codex writes the file and then the tables, so a lag of a
        moment is normal. The grace is measured from the first time any pass saw the
        lag, and the watcher looks at every thread with a pending record every tick."""
        current = self._projection_now(thread_id)
        if current is not False:
            return current
        return self.clock() - self._stale_since[thread_id] < self.options["projection_grace_seconds"]

    def fresh_throughout(self, thread_id, since: float) -> bool:
        """Exactly current now, and not seen behind at any point since `since`.

        What a settle needs before concluding that nothing ran: a lag anywhere in the
        window could be hiding the very turn our item started. After a restart only the
        present can be checked, which is still the strict half of the rule."""
        if self._projection_now(thread_id) is not True:
            return False
        return self._stale_seen.get(thread_id, float("-inf")) < since

    def observe_projections(self):
        """Look at the history of every thread with something pending, so a lag that
        starts long before a record is due is already known when it becomes due."""
        threads = {row["thread_id"] for row in self.store.records_in(WAITING | WATCHED)}
        for thread in threads:
            self._projection_now(thread)

    # --------------------------------------------------------------- the watch
    def watch_needed(self) -> bool:
        """Whether anything may be sitting in Codex's queue right now.

        While that is true the watcher looks every second instead of every poll: the
        window in which a person can start work ahead of our queued item is seconds long.
        """
        return any(row["state"] != "submission_unknown" or row["queue_id"] is not None
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

    # ----------------------------------------------------------- the outcome
    def observe(self, row):
        """Follow our own recovery turn to its end, reading that turn only."""
        now = self.clock()
        try:
            seen = self.source.turn_observation(row["thread_id"], row["recovery_turn_id"], row["marker"])
        except Exception:
            seen = None
        deadline = (row["turn_started_at"] or now) + self.options["unknown_reconcile_window_seconds"]
        if not seen or not seen.get("found"):
            # Unreadable is unknown, never "no progress". It is retried until the deadline.
            if now >= deadline:
                self.transition(row, "outcome_unverified", "outcome_deadline")
            return
        status = seen["status"]
        if seen["foreign_user_messages"] > 0:
            self.transition(row, "handed_over", "user_joined", user_joined=True,
                            recovery_turn_status=status)
        elif status == "other":
            self.transition(row, "outcome_unverified", "unknown_turn_status", recovery_turn_status="other")
        elif status == "inProgress":
            if seen["later_terminal"]:
                # The row can never finish: Codex only updates a turn row while it is
                # the one in progress, so a later finished turn means this one is stale.
                self.transition(row, "outcome_unverified", "stale_turn_row")
            elif now >= deadline:
                self.transition(row, "outcome_unverified", "outcome_deadline")
            elif row["recovery_turn_status"] != "inProgress":
                self.store.update(row["interruption_id"], at=now, recovery_turn_status="inProgress")
        elif row["state"] == "turn_started":
            self.transition(row, "turn_completed", None, recovery_turn_status=status)
        else:
            completed = seen["completed_at"] or row["turn_started_at"] or now
            if now < completed + self.options["settle_seconds"]:
                return
            if status == "completed":
                if seen["progress"]:
                    self.transition(row, "recovered", "progress_observed", recovery_turn_status=status)
                else:
                    self.transition(row, "completed_no_progress", "no_progress_observed",
                                    recovery_turn_status=status)
            elif status == "failed":
                # The failure itself is registered by detection, as this record's child.
                self.transition(row, "recovery_turn_failed", "turn_failed", recovery_turn_status=status)
            elif status == "interrupted":
                self.transition(row, "stopped_by_user", "turn_interrupted", recovery_turn_status=status)

    def observe_all(self):
        for row in self.store.records_in(OBSERVING):
            try:
                self.observe(row)
            except Exception:
                self.log(row["thread_id"], "outcome_check_unavailable", None)

    # --------------------------------------------------------------- collect
    def _owner(self, thread_id, turn_id):
        """Which of our records put its continuation into this turn, if any."""
        candidates = [row for row in self.store.claimed_on_thread(thread_id)
                      if row["recovery_turn_id"] is None]
        if not candidates:
            return None
        try:
            present = set(self.source.turn_markers(thread_id, turn_id, [row["marker"] for row in candidates]))
        except Exception:
            return None
        for row in candidates:
            if row["marker"] in present:
                return row["interruption_id"]
        return None

    def _legacy_carry(self, detection):
        """The v0.5 no-progress carry, for a predecessor recorded before chains existed.

        When the previous delivered interruption on this thread produced no completed
        turn and no assistant reply, the count carries forward; visible progress resets
        it. Only lifecycle booleans are consulted - no message text.
        """
        previous = [row for row in self.store.claimed_on_thread(detection["thread_id"])
                    if row["state"] == "resumed" and row["interruption_id"] != detection["interruption_id"]]
        if not previous:
            return None
        last = max(previous, key=lambda row: row["ordinal"])
        try:
            progress = self.source.progress(detection["thread_id"], last["ordinal"])
        except Exception:
            return None                     # unreadable progress is not evidence of failure
        if progress.get("assistant_reply") or progress.get("later_completed"):
            return None                     # something happened; the chain starts over
        return last["no_progress_count"] + 1

    def collect(self):
        settings = self.store.settings()
        if not settings["enabled"]:
            return
        since = max(0.0, settings["armed_at"] - self.options["detection_lookback_seconds"])
        for raw in self.source.latest_failures(since):
            record = detect(raw)
            if record is None or not self.store.thread_enabled(record["thread_id"]):
                continue
            if self.store.get(record["interruption_id"]) is not None:
                continue
            category = record["category"]
            if not self.recovers(category):
                # Logged once per interruption: the user switched this off deliberately,
                # so it is a fact worth being able to find, not a repeating complaint.
                if record["interruption_id"] not in self._declined:
                    if len(self._declined) > 512:
                        self._declined.clear()
                    self._declined.add(record["interruption_id"])
                    self.log(record["thread_id"], "category_recovery_disabled", category)
                continue
            usage = category == failures.USAGE_LIMIT
            # A reset timestamp only exists for a usage limit; a transient failure has
            # nothing to wait for but time, so the two schedules are computed separately.
            hint = (self.source.reset_hint(record["thread_id"], record["turn_id"]) if usage
                    else {"reset_at": None, "limit_type": category, "uncertain": False})
            # store.register accepts only these exact detection fields; detect() also
            # returns status/category which must not be forwarded as-is.
            detection = {
                "thread_id": record["thread_id"], "turn_id": record["turn_id"],
                "completed_at": record["completed_at"], "started_at": record["started_at"],
                "ordinal": record["ordinal"], "interruption_id": record["interruption_id"],
                "reset_at": hint["reset_at"], "limit_type": hint["limit_type"],
                "uncertain": bool(hint["uncertain"]), "category": category,
            }
            now = self.clock()
            reset = detection["reset_at"]
            if usage:
                state = "waiting_reset" if reset else "waiting_poll"
                when = (max(now + 30, reset + self.options["reset_grace_seconds"]) if reset
                        else now + self.options["conservative_poll_seconds"])
            else:
                state = "waiting_backoff"
                when = now + self.first_delay(category)
            owner = self._owner(detection["thread_id"], detection["turn_id"])
            progress = self.source.turn_progress(detection["thread_id"], detection["turn_id"])
            carry = None if owner else self._legacy_carry(detection)
            # One transaction: the record can never exist without its real schedule and
            # the counters of the task it continues.
            if not self.store.register(detection, now, state=state, next_retry_at=when,
                                       owner_id=owner, failed_turn_progress=progress,
                                       legacy_carry=carry, limits=self.limits()):
                continue
            registered = self.store.get(detection["interruption_id"])
            self.log(detection["thread_id"],
                     "usageLimitExceeded_detected" if usage else "transient_failure_detected",
                     detection["interruption_id"] if usage else category)
            if registered["state"] in TERMINAL:
                # Created already stopped: the task it continues was cancelled, taken
                # over, or is out of budget. Said once, and never as "will resume".
                self.log(detection["thread_id"], registered["state"], registered["last_error"])
                self.announce("stopped", registered, state=registered["state"],
                              reason=registered["last_error"])
                continue
            if usage and reset:
                self.log(detection["thread_id"], "reset_expected", str(int(reset)))
            elif usage:
                self.log(detection["thread_id"], "reset_unknown_conservative_poll",
                         str(int(self.options["conservative_poll_seconds"])))
            if detection["uncertain"]:
                self.log(detection["thread_id"], "blocking_limit_uncertain", None)
            # The only moment a control can be offered at the time it matters: the
            # Codex turn has already failed, so nothing can be added to the app's
            # own notice, but the watcher is running right now.
            self.announce("interruption", registered)

    # --------------------------------------------------------------- attempt
    def _stop_for_budget(self, row, gate, reason):
        state = "no_progress_exhausted" if gate == "no_progress_budget" else "retry_budget_exhausted"
        self.transition(row, state, reason)

    def _usage_wait(self, row, limits, now):
        """Wait for usage, and give up on a limit that is never going to lift.

        Only time between two probes that both said "unavailable, no reset known" is
        counted, capped per interval, so time the app was closed, the watcher was not
        running or the probe itself failed never counts.
        """
        available = limits.get("available")
        probe_reset = limits.get("reset_at")
        reset = max([value for value in (row.get("reset_at"), probe_reset) if value], default=None)
        extra = {}
        if available is False and reset is None:
            gap = 0.0
            if row.get("usage_probe_at"):
                gap = min(max(0.0, now - row["usage_probe_at"]),
                          1.5 * self.options["conservative_poll_seconds"])
            total = row["usage_unavailable_seconds"] + gap
            if total >= self.options["usage_never_available_seconds"]:
                self.transition(row, "terminal_failure", "usage_never_available",
                                usage_unavailable_seconds=total, usage_probe_at=None)
                return
            extra = {"usage_unavailable_seconds": total, "usage_probe_at": now}
        else:
            extra = {"usage_probe_at": None} if row.get("usage_probe_at") else {}
            if (available is False and reset is not None
                    and now >= reset + self.options["usage_after_reset_seconds"]):
                self.transition(row, "terminal_failure", "usage_not_restored_after_reset", **extra)
                return
        wait = (max(60, probe_reset + self.options["reset_grace_seconds"] - now) if probe_reset
                else self.options["conservative_poll_seconds"])
        self.transition(row, "waiting_for_usage",
                        "usage_unavailable" if available is False else "usage_unknown",
                        delay=wait, **extra)

    def _wait(self, row, state, reason, delay, vector):
        """Park a record that was due but is not claimable, with the reason recorded."""
        self.store.record_gates(row["interruption_id"], vector, self.clock())
        extra = ({"usage_probe_at": None}
                 if row.get("usage_probe_at") and state != "waiting_for_usage" else {})
        self.transition(row, state, reason, delay=delay, **extra)

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
        if row["state"] in ("waiting_reset", "waiting_poll"):
            self.log(row["thread_id"], "checking_eligibility", None)
        compatibility = self.engine_state()
        vector["engine_compatible"] = (
            machine.gate(machine.PASS) if compatibility in ("verified", "structurally_compatible")
            else machine.gate(machine.BLOCK, "engine_incompatible") if compatibility == "incompatible"
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
        if not self.valid_interruption(row):
            self.transition(row, *self.supersede_reason(row))
            return
        fresh = self.projection_fresh(row["thread_id"])
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
        if len(recent) >= self.options["max_submissions_per_thread_per_day"]:
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
        usage = self.usage()
        if usage.get("available") is not True:
            vector["usage"] = machine.gate(
                machine.WAIT if usage.get("available") is False else machine.UNKNOWN,
                "usage_unavailable" if usage.get("available") is False else "usage_unknown")
            self.store.record_gates(row["interruption_id"], vector, now)
            self._usage_wait(row, usage, now)
            return
        vector["usage"] = machine.gate(machine.PASS)
        self.dispatch(row, app, vector, limits)

    def dispatch(self, row, app, vector, limits):
        """Claim, re-check, send. The only method that can call `backend.send`."""
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
            claimed, gate, reason = self.store.reserve_detailed(key, self.clock(), limits=limits,
                                                                gates=vector)
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
                response = self.backend.send(current["thread_id"],
                                             continuation(current["category"], self.language)
                                             + "\n\n" + current["marker"])
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
        if self.projection_fresh(claim["thread_id"]) is not True:
            return "waiting_for_loaded_thread", "projection_stale", poll
        if self.source.foreign_queued(claim["thread_id"], claim["marker"]):
            return "waiting_retry", "user_input_queued", poll
        presence = self.source.marker_presence(claim["thread_id"], claim["marker"])
        if presence.get("history") or presence.get("queue"):
            return "superseded", "duplicate_owner", 0
        if not self.home_lock():
            return "waiting_for_app", "home_lock_unavailable", poll
        return None

    # ------------------------------------------------------------------ tick
    def tick(self):
        # The watch and outcome observation continue when recovery is paused: taking
        # back a queued continuation is exactly what a Pause asks for.
        try:
            self.observe_projections()
        except Exception:
            self.log(None, "projection_check_unavailable", None)
        self.watch()
        self.observe_all()
        if not self.store.settings()["enabled"]:
            return
        try:
            self.collect()
        except Exception:
            self.log(None, "detection_unavailable_no_submission", None)
            return
        for row in self.store.records_in(UNSENT):
            try:
                self.attempt(row)
            except Exception:
                self.log(row["thread_id"], "eligibility_check_failed_no_submission", None)
