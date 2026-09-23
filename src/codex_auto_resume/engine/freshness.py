"""Whether Codex is in a state worth reading: the app, the usage, the projection.

A projection that has fallen behind its rollout is the one that matters most - reading a turn
from a history that has not caught up is reading a past that is already wrong.
"""
from __future__ import annotations

from .. import machine
from ..machine import WAITING, WATCHED


class FreshnessMixin:
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
