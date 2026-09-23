"""What the engine was given, and the policy it was last told.

The collaborators it holds - a store, a reader of Codex, a backend - and the settings a person
chose, which are re-read at the moment of sending rather than at the moment of failing, so a
style or a language changed while a recovery waits applies to that recovery.
"""
from __future__ import annotations

from contextlib import nullcontext
import time
from .. import settings as policy


# Bounded exponential backoff for proven "queue process never started" failures.
BACKOFF_LADDER = (30, 60, 120, 300)

# A transient failure waits on a bounded ladder, never on a usage reset. The two
# policies stay separate on purpose: a usage limit has a real reset timestamp to
# wait for, a dropped connection has nothing but elapsed time.
TRANSIENT_BACKOFF = (5, 15, 30, 60, 120)


def backoff_delay(retry: int) -> int:
    """retry is 1-based: 30s, 1m, 2m, 5m, then 5m forever (bounded by retry cap)."""
    index = max(0, min(int(retry) - 1, len(BACKOFF_LADDER) - 1))
    return BACKOFF_LADDER[index]


def transient_delay(attempt: int) -> int:
    """attempt is 1-based; the ladder is bounded and never grows without limit."""
    index = max(0, min(int(attempt) - 1, len(TRANSIENT_BACKOFF) - 1))
    return TRANSIENT_BACKOFF[index]


class OptionsMixin:
    def __init__(self, store, source, backend, *, dispatch_lock=nullcontext,
                 clock=time.time, log=None, options=None, notify=None, language=None,
                 home_lock=None, engine_state=None):
        self.store, self.source, self.backend = store, source, backend
        self.dispatch_lock, self.clock = dispatch_lock, clock
        self.log = log or (lambda *args: None)
        self.notify = notify or (lambda *args: None)
        self.language = language or "en"
        # The user's policy as last adopted. The continuation text is built from it at
        # the moment of sending, so a style or language changed while a recovery waits
        # applies to that recovery rather than to the next one.
        self.policy_values = policy.defaults()
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
        self.policy_values = values
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

    def allowed(self, row):
        return (self.store.settings()["enabled"] and self.store.thread_enabled(row["thread_id"])
                and not row.get("cancel_requested"))
