"""What the engine was given, and the policy it was last told.

The collaborators it holds - a store, a reader of Codex, a backend - and the settings a person
chose, which are re-read at the moment of sending rather than at the moment of failing, so a
style or a language changed while a recovery waits applies to that recovery.
"""
from __future__ import annotations

from contextlib import nullcontext
import random
import time
from .. import ladder, machine, managed as admin, projects, quiet, settings as policy
from ..domain.plug import guard
from ..domain.vocabulary import ImportanceTier, NewConversationPolicy


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


# What a plug is shown of the store, at P2 and P8: the reads the engine itself makes, and none
# of its writes. Not the journal, which no decision reads (tests/test_surface_properties.py): a
# plug learns what became of a record from the moves core tells it of as it writes them (P14,
# engine/announce.py), not from a history a pruned entry or a retention bound would change.
VIEW_READS = frozenset({"get", "records_in", "settings", "thread_enabled", "others_in_flight",
                        "recent_claims", "recent_claim_count", "claimed_on_thread"})


class StoreView:
    """The engine's store as a plug sees it, and the moment it was shown.

    The reads, and nothing that writes: a plug is told what core holds and decides nothing by
    changing it. Each read is the store's own, looked up when it is used, so a view costs
    nothing until a plug reads through it.

    The store is kept in a closure, not on an attribute, and a read is handed over as a function
    of its own rather than the store's bound method: `view._store`, or a read's `__self__`, would
    have been every write the store has.

    That keeps a plug from writing by accident, and it is all this can do. The plug is this
    product's own advanced package, running in core's process, and Python keeps nothing there
    from code that means to find it: a closure's cells, a frame's locals, the garbage collector
    and the store's file on disk all lead to the store. What is taken away is the plain way to
    a write a hook did not mean to make, not every way.
    """
    __slots__ = ("now", "_reads")

    def __init__(self, store, now):
        self.now = now
        # Written out one by one rather than looked up by name, so that each read names the
        # store call it makes and tests/test_ports.py sees every one of them: a call built at
        # run time is one no table can hold.
        reads = {
            "get": lambda *a, **k: store.get(*a, **k),
            "records_in": lambda *a, **k: store.records_in(*a, **k),
            "settings": lambda *a, **k: store.settings(*a, **k),
            "thread_enabled": lambda *a, **k: store.thread_enabled(*a, **k),
            "others_in_flight": lambda *a, **k: store.others_in_flight(*a, **k),
            "recent_claims": lambda *a, **k: store.recent_claims(*a, **k),
            "recent_claim_count": lambda *a, **k: store.recent_claim_count(*a, **k),
            "claimed_on_thread": lambda *a, **k: store.claimed_on_thread(*a, **k),
        }
        for name, call in reads.items():
            call.__name__ = call.__qualname__ = name
        self._reads = reads

    def __getattr__(self, name):
        if name in VIEW_READS and name in self._reads:
            return self._reads[name]
        raise AttributeError(name)


class OptionsMixin:
    def __init__(self, store, source, backend, *, dispatch_lock=nullcontext,
                 clock=time.time, log=None, options=None, notify=None, language=None,
                 home_lock=None, engine_state=None, plug=None, connectivity=None):
        self.store, self.source, self.backend = store, source, backend
        # The edition's plug, as core holds one (domain/plug.py): NULL, the standard edition's,
        # unless the watcher was given another. Every point is asked through this and nothing
        # else, and it is fixed for the engine's life, so no edition changes under a tick.
        self.plug = guard(plug)
        self.dispatch_lock, self.clock = dispatch_lock, clock
        self.log = log or (lambda *args: None)
        self.notify = notify or (lambda *args: None)
        self.language = language or "en"
        # The user's policy as last adopted. The continuation text is built from it at
        # the moment of sending, so a style or language changed while a recovery waits
        # applies to that recovery rather than to the next one.
        self.policy_values = policy.defaults()
        # v0.6.11: an administrator's policy keys, as last adopted (managed.py) - none until told -
        # and the windows quiet hours are asked of besides the settings': each administrator's, and
        # a person's own that the first of those stands in for in the settings. None at all unless
        # a key sets quiet hours.
        self.managed = admin.NONE
        self._more_quiet = ()
        # Whether this watcher holds the lock on its Codex home, and what the Codex
        # engine compatibility check concluded. Both are owned by the process.
        self.home_lock = home_lock or (lambda: True)
        self.engine_state = engine_state or (lambda: "verified")
        # v0.6.11: whether Windows reports this PC on the internet (win/network.py) - True, False or
        # None, asked only while Wait for an internet connection is on (engine/freshness.py).
        self.connectivity = connectivity or (lambda: None)
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
                        # v0.6.14: how long after its send an uncertain submission may be sent
                        # once more, where the edition's plug asks (engine/resend.py).
                        "resend_after_seconds": 900, "resend_until_seconds": 6 * 3600,
                        **(options or {})}
        self._usage_cache = None
        # v0.6.11: records whose task changed under the task-changed guard's Tell, said on their
        # continuation's notice (engine/guard.py); and jitter's draw, asked only while it is on.
        self._told = set()
        self._random = random.Random()
        self._declined = set()
        # v0.6.14: when each failure the edition's plug did not take up was last put to it (P17), the
        # record looked at early now and when the last early window opened (EARLY, engine/relaxed.py).
        self._unadmitted = {}
        self._early_look = self._early_at = None
        # and what P7 said of the record looked at now, where it was asked at a refused schedule.
        self._schedule_said = None
        self._announced = set()
        self._stale_since = {}
        self._stale_seen = {}
        # v0.6.14 (engine/resend.py): since when this engine watches, and since when it no longer
        # knows the lags it saw; uncertain submissions a look found no trace of, those seen in
        # Codex's queue, since when sightings are known, and the last look for a resend found twice.
        self._watching_since, self._stale_cleared_at = self.clock(), float("-inf")
        self._no_trace, self._seen_queued, self._seen_queued_cleared_at = {}, set(), float("-inf")
        self._resent_looked_at = None
        self._loaded_cache = {}
        self._watch_offset = 0

    # ------------------------------------------------------------------ policy
    def apply_policy(self, values, managed=None) -> None:
        """Adopt the user's configurable policy.

        Policy only. Nothing here can widen what the classifier treats as recoverable,
        shorten a revalidation, resend an uncertain submission or lift any other safety
        gate - those are properties of the engine, not preferences. The worst a bad
        settings file can do through this method is make recovery more conservative,
        because every value it reads has already been coerced to a sane default.

        v0.6.11: `managed` is what an administrator's policy keys hold (managed.py), applied after
        the coercion, so it can only hold back; with none, the values are the ones adopted.
        """
        own = policy.coerce(values)
        self.managed = managed if isinstance(managed, admin.Managed) else admin.NONE
        values = admin.clamp(own, self.managed)
        self.policy_values = values
        self._more_quiet = admin.quiet_sources(own, self.managed) if self.managed.quiet_hours else ()
        self.options["max_recovery_attempts"] = values["max_recovery_attempts"]
        self.options["max_no_progress"] = values["max_no_progress"]
        self.options["max_chain_continuations"] = values["max_chain_continuations"]
        self.options["retry_ladder"] = policy.timing_ladder(values)
        self.options["detection_lookback_seconds"] = float(values["detection_lookback_hours"]) * 3600.0
        self.options["recoverable_categories"] = frozenset(
            category for category in policy.CONFIGURABLE_CATEGORIES
            if policy.category_enabled(values, category))
        # v0.6.11: how long a task may keep failing with a temporary error; None, the default, is no
        # ceiling, and then the budgets are exactly the three there were.
        self.options["max_chain_seconds"] = ladder.ceiling(values)

    def limits(self) -> dict:
        found = {name: self.options[name] for name in
                 ("max_recovery_attempts", "max_no_progress", "max_chain_continuations")}
        if self.options.get("max_chain_seconds") is not None:
            found["max_chain_seconds"] = self.options["max_chain_seconds"]
        return found

    def capacity_limits(self) -> dict:
        """The budgets of a capacity error the plug vouches for (CAPACITY, v0.6.14): core's own capacity
        bounds (ladder.py), and the person's own time ceiling when one is set, which only restricts.
        v0.6.14: and an administrator's MaxRecoveryAttempts, which holds a capacity retry back as it
        holds every other (managed.clamp): CAPACITY passes the person's budgets, never the key's."""
        found = {name: ladder.CAPACITY_PER_DAY for name in
                 ("max_recovery_attempts", "max_no_progress", "max_chain_continuations")}
        ceiling = self.managed.max_recovery_attempts
        if ceiling is not None:
            found["max_recovery_attempts"] = min(found["max_recovery_attempts"], ceiling)
        if self.options.get("max_chain_seconds") is not None:
            found["max_chain_seconds"] = self.options["max_chain_seconds"]
        return found

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

    def quiet_until(self, now):
        """The end of the quiet hours `now` falls in, or None (quiet.py). Asked of the settings
        alone, so with none set - the default - nothing is read and nothing ever waits; and, from
        v0.6.11, of each window an administrator set too, a person's own still among them, the
        latest end of any being when a recovery may go."""
        if not self._more_quiet:
            return quiet.quiet_until(now, self.policy_values)
        ends = [end for end in (quiet.quiet_until(now, source)
                                for source in (self.policy_values,) + self._more_quiet) if end is not None]
        return max(ends) if ends else None

    def tier(self, thread_id) -> str:
        """The tier a conversation has: its own, or the default's (settings.tier_of)."""
        return policy.tier_of(self.policy_values, self.store.thread_tier(thread_id))

    def allowed(self, row):
        """Consent: recovery on, the conversation on, no cancel - and, from schema 4, not only
        observed and not held for a person, both of which are off at the defaults. What the
        last look before a send asks again (presend_problem), with a postponement beside it."""
        settings = self.store.settings()
        return (settings["enabled"] and self.store.thread_enabled(row["thread_id"])
                and not row.get("cancel_requested") and not self.observing(settings)
                and row.get("hold") is None)

    def observing(self, settings) -> bool:
        """Observe only (v0.6.11): the state's switch, or the setting it is written from - either is
        enough, so a switch not yet written, or a setting not yet read, still sends nothing."""
        return bool(settings["observe_only"] or self.policy_values.get("observe_only"))

    @staticmethod
    def observes(row, vector) -> bool:
        """Whether a record whose consent was refused is only observed: every other condition of consent
        held, so the rest of the gates are asked to learn whether it would have been sent."""
        return vector["consent"][1] == machine.OBSERVE_ONLY and row.get("hold") is None

    def admission(self, thread_id, now):
        """The hold an interruption of this conversation is detected with (v0.6.11), or None - at the
        defaults, always None, and nothing is read or written for it. A conversation this state has
        never seen may first be given Only notify me as its own tier (new_conversation_policy); then
        its tier's hold, and failing that its project's (projects.py): one the policy does not allow,
        or one that cannot be read under either list policy, waits for a person (notify_only)."""
        values = self.policy_values
        if values.get("new_conversation_policy") == NewConversationPolicy.NOTIFY_ONLY:
            self.store.enrol_conversation(thread_id, ImportanceTier.NOTIFY_ONLY.value, now)
        hold = machine.hold_for_tier(self.tier(thread_id))
        if hold is not None or not projects.asks(values):
            return hold
        try:
            key = self.source.project_key(thread_id)
        except Exception:
            key = None
        return projects.hold_for(values, key)
