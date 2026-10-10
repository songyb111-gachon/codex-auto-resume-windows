# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""Short retries when Codex is at capacity: the advanced edition's answer at P17 and P3 (v0.6.14).

When a turn fails because Codex says it is at capacity - its own code `serverOverloaded`, a server
error core recovers already - the standard edition waits its retry timing, at most five continuations
a conversation a day, fifteen minutes apart, and stops the task after four attempts. This answers
CAPACITY instead, at P17 as the failure is detected and again at known_failure as its record falls
due, and core carries it out within bounds of its own a capability cannot widen (core's ladder.py):
a minute, then two, four and five, each lengthened by up to a fifth, a minute apart, 48 a day, for
twelve hours on the clock from the task's first failure at most - and the claim pays a unit of this
capability's for each.

What this decides is only for how long, of those twelve hours, it keeps answering: the person's
choice of one to twelve (`ceiling_hours`, two by default), counted on the clock from the first
failure of the task - core's `chain_started_at` - whatever the task waited for meanwhile. Past it, it
answers DEFER, and the standard edition's waits and budgets hold the record again, which may end the
task. Any other server error, and every other kind, it leaves alone; core offers CAPACITY for nothing
else (failures.admits).
"""
from __future__ import annotations

import time

from codex_auto_resume.domain.plug import DEFER, Alternative

from ..vocabulary import OptionKey

CAPABILITY = "capacity_retry"
CODE = "serverOverloaded"
KIND = "server_5xx"
CEILING_HOURS = (1, 2, 3, 4, 6, 8, 12)
DEFAULT_HOURS = 2
HOUR = 3600


def _time(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


class CapacityRetry:
    """The capability's code: its hooks at P17 and P3. `bind` gives it its own choices and the
    runtime's clock (state.Scoped)."""
    __slots__ = ("paths", "_scoped")

    def __init__(self, paths):
        self.paths = paths
        self._scoped = None

    def bind(self, scoped):
        self._scoped = scoped

    def _now(self) -> float:
        return self._scoped.now() if self._scoped is not None else time.time()

    def _within(self, started) -> bool:
        """Whether a task that first failed at `started` is still inside the time the person chose."""
        hours = DEFAULT_HOURS
        if self._scoped is not None:
            hours = self._scoped.options().get(OptionKey.CEILING_HOURS, DEFAULT_HOURS)
        return _time(started) and self._now() - started < hours * HOUR

    def admission(self, failure):
        """P17: CAPACITY for Codex at capacity, while its task is inside the time chosen - a first
        failure always is; DEFER for anything else."""
        if failure.get("category") != KIND or failure.get("code") != CODE:
            return DEFER
        chain = failure.get("chain")
        if chain is None:
            return Alternative.CAPACITY
        started = chain.get("chain_started_at") if isinstance(chain, dict) else None
        return Alternative.CAPACITY if self._within(started) else DEFER

    def gate(self, name, record, facts):
        """P3: at known_failure, CAPACITY again for a record it took up (the runtime holds it to its
        own), while its task is inside the time chosen. Every other gate is core's."""
        if name != "known_failure" or record.get("category") != KIND:
            return DEFER
        return Alternative.CAPACITY if self._within(record.get("chain_started_at")) else DEFER


def make(paths) -> CapacityRetry:
    """The capability's factory (registry.CapabilityDef.make): its code for one installation."""
    return CapacityRetry(paths)
