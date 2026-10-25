# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""Continue with no words (v0.6.16-beta.4, P15; headless only).

The standard edition always ends a continuation's words with its marker and proves delivery by finding it (A4), and
its words are always a shipped template's or the Custom message (A26). With this on, P15 answers SILENT: core carries
it out only through a route that takes words - a turn run here (codex/headless.py) - which it then calls with no
words at all, under the client id it derives from the interruption, and proves delivery by that id (P15's own
machinery: nothing new is stored). Through `codex queue`, or any channel, core ignores it and sends the words with
the marker: M3 found Codex refuses an empty queue item, so that route is not offered.

It continues nothing by itself: it changes only how headless_run's turn, or compact_continue's continuation, starts.
It never silences words that are not core's own template: where the continuation carries another capability's words
(P4) or the person's words for this time, core does not ask P15 at all and those words go with the marker (v0.6.17).
Until M3B - a turn started with no input, proven by its id - passes for the Codex in force, its statement carries the
UNMEASURED warning. Where Codex refuses a turn with no input, the route answers "not started" with Codex's refusal,
and from then on this answers DEFER for that Codex in this process - so the next attempt carries words (the review's
finding: a kept-on capability is not turned off by a trip) - and it trips (REFUSED_BY_CODEX): off, or, kept on (K8,
since v0.6.19-beta.3), a note while it goes on answering DEFER.
"""
from __future__ import annotations

from codex_auto_resume.domain.plug import DEFER, Alternative

from ..codex import headless

CAPABILITY = "silent_continuation"


class SilentContinuation:
    """The capability's code: its hook at P15. It reads one flag of the process's: whether a route met Codex
    refusing a turn with no input (codex/headless.EMPTY_REFUSED)."""
    __slots__ = ("paths",)

    def __init__(self, paths):
        self.paths = paths

    def delivery(self, record):
        """P15: SILENT, unless Codex has refused a turn with no input in this process."""
        return DEFER if headless.EMPTY_REFUSED else Alternative.SILENT


def make(paths) -> SilentContinuation:
    """The capability's factory (registry.CapabilityDef.make): its code for one installation."""
    return SilentContinuation(paths)
