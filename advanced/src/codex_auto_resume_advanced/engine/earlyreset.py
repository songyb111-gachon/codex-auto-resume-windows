# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""Notice a usage limit that lifts early: the advanced edition's answer at P7 and P3 (v0.6.14).

A conversation that waits for a usage limit to reset waits, in the standard edition, until the time
Codex gave, and usage is read only when a recovery is due (A12, C9). This looks earlier: at P7, asked
by core before such a record's time (EARLY, engine/relaxed.py), it answers EARLY once a probe - one
every five minutes, for every waiting conversation together, as core's own early window is - so core
reads usage once for them all. At P3 `usage`, which core reaches only when that reading said usage is
available, it holds the record the first time, and lets core go on - DEFER - only when a reading at
least five minutes after a first one says so again. Every wait a record meets in a look like this is
its gate vector alone (core's EARLY): it keeps its state, its reason and its next look.

Its memory is the process's, and only this: when the current probe began, whether that probe reached
the usage gate, when a probe first found usage available, and which records it released into the
probe. A probe that never reached the usage gate - an unavailable or failed reading, a spend block, a
gate before it - forgets the first yes, so two answers in a row, five minutes apart, are what lift a
limit early. It counts its own two words, once a probe: `probed` for a first early yes, `lifted` for
the second. It sends nothing but the continuation core sends, and never a turn to start a usage
window or keep one open (the plan's exclusion).
"""
from __future__ import annotations

import time

from codex_auto_resume import failures, machine
from codex_auto_resume.domain.plug import DEFER, Alternative

# The waits a record may be looked at early in: a usage limit's, as core's own (engine/relaxed.py).
EARLY_STATES = ("waiting_reset", "waiting_poll")
# Five minutes between two probes, and at least as much between the two answers that lift a limit.
SPACING = 300
# A probe's first seconds, in which every waiting record is looked at with it.
WINDOW = 30
USAGE = "usage"
# The schedule gate of a record looked at early (core's EARLY: passed, by the plug).
LOOKED_EARLY = machine.gate(machine.PASS, machine.PLUGGED)


def _time(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


class EarlyReset:
    """The capability's code: its hooks at P7 and P3. `bind` gives it the runtime's clock and the
    count of its own two words (state.Scoped)."""
    __slots__ = ("paths", "_scoped", "probe_at", "reached", "first_available_at", "lifted_at", "released")

    def __init__(self, paths):
        self.paths = paths
        self._scoped = None
        self.probe_at = None
        self.reached = False
        self.first_available_at = None
        self.lifted_at = None
        self.released = set()

    def bind(self, scoped):
        self._scoped = scoped

    def _now(self) -> float:
        return self._scoped.now() if self._scoped is not None else time.time()

    def _count(self, code) -> None:
        if self._scoped is not None:
            try:
                self._scoped.count(code)
            except Exception:
                pass                                 # a count that cannot be written changes nothing

    def schedule(self, record, eligible_at):
        """P7, asked early by core for a record that waits for a usage limit to reset: EARLY while a
        probe is open - one begins five minutes after the last - and DEFER for anything else, a record
        that is due among them."""
        now = self._now()
        if (not isinstance(record, dict) or record.get("category") != failures.USAGE_LIMIT
                or record.get("state") not in EARLY_STATES or not _time(eligible_at) or eligible_at <= now
                or (_time(record.get("not_before")) and record["not_before"] > now)):
            # A postponed record is never looked at early (core's EARLY), though P7 is asked about it
            # for a person's Send now: no probe is opened for it.
            return DEFER
        opened = self.probe_at
        if opened is None or not 0 <= now - opened < WINDOW:
            if opened is not None and 0 <= now - opened < SPACING:
                return DEFER
            if not self.reached:
                self.first_available_at = None       # the last probe found no yes: start again
            self.probe_at, self.reached, self.released = now, False, set()
        self.released.add(record.get("interruption_id"))
        return Alternative.EARLY

    def not_taken(self, record) -> None:
        """P7's answer of another capability was the one taken for `record` (runtime.py, v0.6.14): a reset credit's
        EARLY after its own reset, say. The record is not one released into this probe, so its first yes holds it
        not: what lifted the limit early was the credit."""
        if isinstance(record, dict):
            self.released.discard(record.get("interruption_id"))

    def gate(self, name, record, facts):
        """P3 `usage` for a record it released into this probe, which core reaches only once the
        reading said usage is available: HOLD on a first yes, DEFER - core goes on - on a second at
        least five minutes after it. Every other gate, and every record looked at in its own time,
        is core's alone."""
        if (name != USAGE or not isinstance(record, dict) or not isinstance(facts, dict)
                or record.get("interruption_id") not in self.released
                or tuple(facts.get("schedule") or ()) != LOOKED_EARLY):
            return DEFER
        self.reached = True
        if self.first_available_at is None:
            self.first_available_at = self.probe_at
            self._count("probed")
            return Alternative.HOLD
        if self.probe_at - self.first_available_at < SPACING:
            return Alternative.HOLD
        if self.lifted_at != self.probe_at:
            self.lifted_at = self.probe_at
            self._count("lifted")
        return DEFER


def make(paths) -> EarlyReset:
    """The capability's factory (registry.CapabilityDef.make): its code for one installation."""
    return EarlyReset(paths)
