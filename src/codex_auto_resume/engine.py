"""Fail-closed scheduler. Codex history stays read-only; transport is injected."""
from contextlib import nullcontext
import time

from .source import detect

CONTINUATION = (
    "사용량 제한으로 중단된 이전 작업을 계속 진행해. 먼저 현재 스레드 컨텍스트와 "
    "실제 저장소/파일 상태를 확인하고, 이미 완료된 작업은 반복하지 말고 원래 목표를 "
    "계속 수행해. 기존 Goal이 있다면 그 상태와 목표를 유지해."
)
UNSENT = {"waiting_reset", "waiting_poll", "waiting_for_app", "waiting_for_loaded_thread",
          "waiting_for_usage", "waiting_retry"}
IN_FLIGHT = {"submitting", "queued", "submission_unknown"}


class Engine:
    def __init__(self, store, source, backend, *, dispatch_lock=nullcontext,
                 clock=time.time, log=None, options=None):
        self.store, self.source, self.backend = store, source, backend
        self.dispatch_lock, self.clock = dispatch_lock, clock
        self.log = log or (lambda *args: None)
        self.options = {"reset_grace_seconds": 60, "conservative_poll_seconds": 900,
                        "state_poll_seconds": 60, "delivery_timeout_seconds": 120,
                        "max_queue_retries": 5, "max_submissions_per_thread_per_day": 5,
                        **(options or {})}
        self._usage_cache = None

    def transition(self, row, state, reason=None, delay=None, **extra):
        values = {"state": state, "last_error": reason, **extra}
        if delay is not None:
            values["next_retry_at"] = self.clock() + delay
        self.store.update(row["interruption_id"], **values)
        if row.get("state") != state or row.get("last_error") != reason:
            self.log(row["thread_id"], state, reason)

    def valid_interruption(self, row):
        latest = self.source.latest(row["thread_id"])
        found = detect(latest) if latest else None
        return found is not None and found["interruption_id"] == row["interruption_id"]

    def allowed(self, row):
        return (self.store.settings()["enabled"] and self.store.thread_enabled(row["thread_id"])
                and not row.get("cancel_requested"))

    def usage(self):
        now = self.clock()
        if self._usage_cache is None or now - self._usage_cache[0] > 30:
            self._usage_cache = (now, self.backend.usage())
        return self._usage_cache[1]

    def reconcile(self, row):
        """Resolve previous submissions without resending an uncertain attempt."""
        receipt = self.source.delivery(row["thread_id"], row["marker"])
        if receipt["delivered"]:
            self.transition(row, "resumed", None, resumed_at=self.clock(), next_retry_at=None)
            return
        queued = receipt.get("queued_ids", [])
        if len(queued) > 1:
            self.transition(row, "submission_unknown", "multiple_matching_queue_items")
            return
        if queued:
            queue_id = queued[0]
            app = self.backend.app_identity()
            loaded = self.backend.loaded(row["thread_id"], app) if app else "notLoaded"
            expired = self.clock() - (row.get("submitted_at") or self.clock()) >= self.options["delivery_timeout_seconds"]
            invalid = not self.valid_interruption(row)
            if not self.allowed(row) or invalid or loaded != "loaded" or expired:
                # Delete only an item found using this record's unique marker in this exact thread.
                if self.backend.delete_queue(row["thread_id"], queue_id):
                    target = "cancelled" if not self.allowed(row) else ("superseded" if invalid else "failed")
                    self.transition(row, target, "owned_queue_removed", queue_id=queue_id)
                else:
                    self.transition(row, "submission_unknown", "queue_cleanup_unconfirmed", queue_id=queue_id)
                return
            self.transition(row, "queued", None, delay=5, queue_id=queue_id)
            return
        # Submission may be in the brief dequeue-to-history persistence gap.
        age = self.clock() - (row.get("submitted_at") or self.clock())
        if row["state"] != "submission_unknown" and age < self.options["delivery_timeout_seconds"]:
            self.transition(row, "submitting", "awaiting_delivery_receipt", delay=5)
        else:
            self.transition(row, "submission_unknown", "no_receipt_do_not_resend", delay=900)

    def collect(self):
        settings = self.store.settings()
        if not settings["enabled"]:
            return
        for raw in self.source.latest_failures(settings["armed_at"]):
            record = detect(raw)
            if record is None or not self.store.thread_enabled(record["thread_id"]):
                continue
            if self.store.get(record["interruption_id"]) is not None:
                continue
            hint = self.source.reset_hint(record["thread_id"], record["turn_id"])
            record.update(hint)
            now = self.clock()
            if self.store.register(record, now):
                reset = record.get("reset_at")
                when = max(now + 30, reset + self.options["reset_grace_seconds"]) if reset else now + self.options["conservative_poll_seconds"]
                self.store.update(record["interruption_id"], state="waiting_reset" if reset else "waiting_poll", next_retry_at=when)
                self.log(record["thread_id"], "usageLimitExceeded_detected", record["interruption_id"])
                if reset:
                    self.log(record["thread_id"], "reset_expected", str(int(reset)))
                if record.get("uncertain"):
                    self.log(record["thread_id"], "blocking_limit_uncertain", None)

    def attempt(self, row):
        if not self.allowed(row):
            return
        now = self.clock()
        if row.get("next_retry_at") and now < row["next_retry_at"]:
            return
        if not self.valid_interruption(row):
            self.transition(row, "superseded", "latest_turn_changed")
            return
        app = self.backend.app_identity()
        if not app:
            self.transition(row, "waiting_for_app", "desktop_app_unavailable", delay=self.options["state_poll_seconds"])
            return
        loaded = self.backend.loaded(row["thread_id"], app)
        if loaded != "loaded":
            self.transition(row, "waiting_for_loaded_thread", "notLoaded" if loaded == "notLoaded" else "loaded_state_unknown", delay=self.options["state_poll_seconds"])
            return
        limits = self.usage()
        if limits.get("available") is not True:
            reset = limits.get("reset_at")
            wait = max(60, reset + self.options["reset_grace_seconds"] - now) if reset else self.options["conservative_poll_seconds"]
            self.transition(row, "waiting_for_usage", "usage_unavailable" if limits.get("available") is False else "usage_unknown", delay=wait)
            return
        recent = [x for x in self.store.all_records() if x["thread_id"] == row["thread_id"]
                  and x.get("submitted_at") and x["submitted_at"] > now - 86400]
        if len(recent) >= self.options["max_submissions_per_thread_per_day"]:
            self.transition(row, "failed", "daily_submission_cap")
            return
        if recent and now - max(x["submitted_at"] for x in recent) < 900:
            self.transition(row, "waiting_retry", "thread_submission_cooldown", delay=900)
            return
        with self.dispatch_lock():
            current = self.store.get(row["interruption_id"])
            if not current or current["state"] not in UNSENT or not self.allowed(current):
                return
            if not self.valid_interruption(current):
                self.transition(current, "superseded", "latest_turn_changed")
                return
            # A fresh process identity prevents a prior app's status authorizing a new app.
            if self.backend.app_identity() != app or self.backend.loaded(row["thread_id"], app) != "loaded":
                self.transition(current, "waiting_for_loaded_thread", "loaded_recheck_failed", delay=60)
                return
            if self.usage().get("available") is not True:
                self.transition(current, "waiting_for_usage", "usage_recheck_failed", delay=900)
                return
            if not self.store.reserve(row["interruption_id"], self.clock()):
                return
            self.log(row["thread_id"], "queue_submission_started", None)
            # Reservation is durable before any external process can accept the message.
            try:
                response = self.backend.send(row["thread_id"], CONTINUATION + "\n\n" + row["marker"])
            except Exception:
                response = {"outcome": "unknown"}
            reserved = self.store.get(row["interruption_id"])
            if response.get("outcome") == "accepted":
                self.transition(reserved, "queued", None, delay=5, queue_id=response.get("queue_id"))
                self.log(row["thread_id"], "queue_accepted_waiting_for_receipt", None)
            elif response.get("outcome") == "not_started":
                retry = row["retry_count"] + 1
                if retry >= self.options["max_queue_retries"]:
                    self.transition(reserved, "failed", "queue_launch_retry_limit", retry_count=retry, submitted_at=None)
                else:
                    self.transition(reserved, "waiting_retry", "queue_process_not_started", retry_count=retry,
                                    submitted_at=None, delay=min(300, 30 * 2 ** (retry - 1)))
            else:
                self.transition(reserved, "submission_unknown", "queue_result_unknown_do_not_resend", delay=900)

    def tick(self):
        # Reconciliation/owned-queue cleanup continues when globally disabled.
        for row in self.store.all_records():
            if row["state"] in IN_FLIGHT:
                if row["state"] == "submission_unknown" and self.allowed(row) and (row.get("next_retry_at") or 0) > self.clock():
                    continue
                try:
                    with self.dispatch_lock():
                        self.reconcile(row)
                except Exception:
                    self.log(row["thread_id"], "reconciliation_unavailable", None)
        if not self.store.settings()["enabled"]:
            return
        try:
            self.collect()
        except Exception:
            self.log(None, "detection_unavailable_no_submission", None)
            return
        for row in self.store.pending():
            if row["state"] not in UNSENT:
                continue
            try:
                self.attempt(row)
            except Exception:
                self.log(row["thread_id"], "eligibility_check_failed_no_submission", None)

