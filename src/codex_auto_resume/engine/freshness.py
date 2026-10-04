"""Whether Codex is in a state worth reading: the app, the usage, the projection.

A projection that has fallen behind its rollout is the one that matters most - reading a turn
from a history that has not caught up is reading a past that is already wrong.

v0.6.11 adds two things that say whether a reading may be trusted at all, both off by default
(power.py): a PC that has just woken, whose last readings of the app and of usage are forgotten -
and, after a sleep longer than Settings allow, whose recoveries that fell due meanwhile wait for a
person - and a PC Windows reports without internet, for which usage is not read.
"""
from __future__ import annotations

from .. import machine, power
from ..domain import usage as readings
from ..machine import WAITING, WATCHED


class FreshnessMixin:
    def usage(self):
        now = self.clock()
        if self._usage_cache is None or now - self._usage_cache[0] > 30:
            self._usage_cache = (now, self.backend.usage())
        return self._usage_cache[1]

    def last_usage(self):
        """The last usage reading this engine made that had windows, as (time, windows) - None until it
        has made one (v0.6.11). What the watcher's heartbeat keeps (domain/usage.py). It reads nothing:
        usage is still read only when a recovery is due, and a reading reused for 30 seconds is the
        same reading (C4, C9)."""
        cached = self._usage_cache
        if cached is None:
            return None
        windows = readings.windows_of(cached[1])
        return None if windows is None else (cached[0], windows)

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

    def activity(self, threads=()) -> dict:
        """What may still run in Codex, for the power action (v0.6.12; LocalSource.activity): whether its
        history has caught up - every conversation written in the last hour, and each of `threads`, the
        batch's own - and then how many turns run and how many items are queued. Read only when the
        power action has passed every check of its own, and never at the defaults. Anything the source
        cannot say, or a source that cannot be asked, is None: the power action then waits (E1)."""
        try:
            found = self.source.activity(tuple(threads), self.clock())
        except Exception:
            found = None
        if not isinstance(found, dict):
            return {"history": None, "running": None, "queued": None}
        return {name: found.get(name) for name in ("history", "running", "queued")}

    def observe_projections(self):
        """Look at the history of every thread with something pending, so a lag that
        starts long before a record is due is already known when it becomes due."""
        threads = {row["thread_id"] for row in self.store.records_in(WAITING | WATCHED)}
        for thread in threads:
            self._projection_now(thread)

    # ------------------------------------------------------------ sleep and the network (v0.6.11)
    def offline(self) -> bool:
        """Whether Windows reports no internet: asked only while Wait for an internet connection is on,
        and never at the defaults, where usage is read as in v0.6.10. A question that could not be asked
        or was not answered is no answer - usage is then read, and decides, as without it (E1)."""
        if not power.waits_for_network(self.policy_values):
            return False
        try:
            return self.connectivity() is False
        except Exception:
            return False

    def _offline(self, row, vector, now) -> bool:
        """Just before usage would be read for a due record: True if it waits because Windows reports no
        internet. Usage is then not read - no App Server is started for it - and the record waits a poll
        with the usage gate's reason `offline`, the time counting toward nothing, as quiet time does not
        (engine/announce.py). False, and nothing asked, at the defaults."""
        if not self.offline():
            return False
        vector["usage"] = machine.gate(machine.WAIT, power.OFFLINE)
        if not self._parked(row, vector):
            self.store.record_gates(row["interruption_id"], vector, now)
            self.transition(row, "waiting_for_usage", power.OFFLINE,
                            delay=self.options["state_poll_seconds"], usage_probe_at=None)
        return True

    def after_sleep(self, since, slept) -> int:
        """This PC has woken (v0.6.11): the watcher heard it, or its clocks say it slept `slept`
        seconds since its look at `since`. What was read of the app and of usage before is forgotten,
        so nothing from before the sleep decides after it. With Ask after a long sleep on and a sleep
        at least that long, each waiting recovery that fell due while it slept - after `since`, and by
        now - waits for a person (power.HOLD): only one that still waits unsent, with no hold and no
        cancel, in one transaction (store.hold_waiting), and one notice says how long it slept and how
        many wait. Nothing is sent or made sooner. Asked only while the watcher listens, which it never
        does at the defaults. Returns how many were held."""
        self._usage_cache = None
        self._loaded_cache.clear()
        threshold = power.sleep_threshold(self.policy_values)
        if threshold is None or not slept or slept < threshold:
            return 0
        now = self.clock()
        due = [row["interruption_id"] for row in self.store.records_in(WAITING)
               if power.fell_due(row, since, now)]
        held = self.store.hold_waiting(due, power.HOLD, now, actor="engine") if due else 0
        if held:
            self.log(None, "held_after_sleep", held)
            try:
                self.notify("after_sleep", {"slept": float(slept), "count": held})
            except Exception:
                self.log(None, "notification_failed", "after_sleep")
        return held
