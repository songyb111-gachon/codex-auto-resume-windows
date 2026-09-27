"""Needs-you notices (v0.6.11), as the engine raises them: once, and never as a recovery.

A failure this product will not resume (needsyou.KINDS), and a turn that has recorded nothing new for
a time a person chose, are told through the one notification path there is (engine/announce.py) - one
event, NEEDS_YOU - and kept in the notices table so each is told once, restarts included. Nothing
here registers a record, claims one or sends anything, and nothing that decides a send reads what it
keeps. At the defaults it reads nothing and writes nothing: notices are off, and so is the stall.
"""
from __future__ import annotations

from .. import needsyou
from ..domain import ids


class NoticeMixin:
    def tell_needs_you(self, failures, since):
        """Raise each notice not raised before, from what detection read this tick (`failures`: the
        latest failures, with those that need a person among them) and, while a stall time is chosen,
        from the turns that stopped moving. A notice that cannot be raised costs its notice: detection
        and recovery go on as they would have."""
        if not needsyou.told(self.policy_values):
            return
        now = self.clock()
        try:
            kinds = needsyou.kinds(self.policy_values)
            for failure in failures:
                done = failure.get("completed_at")
                if (failure.get("category") in kinds and done is not None
                        and now - done <= needsyou.WINDOW_SECONDS
                        and self.store.thread_enabled(failure["thread_id"])):
                    self._notice(failure["interruption_id"], failure["thread_id"], failure["category"], now)
            quiet = needsyou.stall_seconds(self.policy_values)
            if quiet is None:
                return
            start = max(since, now - needsyou.WINDOW_SECONDS)
            for turn in self.source.stalled_turns(start, quiet, now):
                if self.store.thread_enabled(turn["thread_id"]):
                    self._notice(ids.stalled_id(turn["thread_id"], turn["turn_id"]), turn["thread_id"],
                                 needsyou.STALLED, now, minutes=needsyou.minutes(quiet))
        except Exception:
            self.log(None, "needs_you_unavailable", None)

    def _notice(self, key, thread_id, kind, now, **detail):
        """One notice: kept, and told, the first time only (store.raise_notice)."""
        if not self.store.raise_notice(key, thread_id, kind, now):
            return
        self.log(thread_id, "needs_you_notice", key)
        self.announce(needsyou.EVENT, {"interruption_id": key, "thread_id": thread_id, "category": kind},
                      **detail)
