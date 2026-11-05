# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""Parallel dispatch: the advanced edition's answer at P12, how many sends may wait for their receipts at once
(v0.6.15-beta).

The standard edition sends one continuation after another on one thread, each waiting up to 45 seconds for Codex's
receipt before the next is looked at (A19: in sequence, under one lock). With this on, core lets two to eight of them
wait at once - each in a conversation of its own, the claim refusing a second in one (core's I4) - while every gate,
every claim and every look stays on the tick, as before (core's engine/launches.py). What it answers is a number of
workers and nothing else: the person's Workers option, 2 by default - and 2 at most until MQ passes on the Codex in
force. The runtime pays one unit for each pooled claim (`acted` at CONCURRENCY), so a send of it whose fate cannot be
known turns it off like any paid send (K7).

It holds no memory of its own: what it reads is the state's, through its view (state.Scoped).
"""
from __future__ import annotations

from codex_auto_resume.domain.plug import DEFER

from ..vocabulary import Measurement, OptionKey

CAPABILITY = "parallel_dispatch"
WORKERS = (2, 3, 4, 5, 6, 7, 8)
DEFAULT_WORKERS = 2
# Until MQ - two to four throwaway conversations sent to at once, each receipt matched and each marker found once -
# passes for the Codex in force, no more than this many at once (the narrowed route; never a refusal, K6).
UNMEASURED_WORKERS = 2


class ParallelDispatch:
    """The capability's code: its hook at P12. `bind` gives it its view of the state (state.Scoped)."""
    __slots__ = ("paths", "_scoped")

    def __init__(self, paths):
        self.paths = paths
        self._scoped = None

    def bind(self, scoped):
        self._scoped = scoped

    def partition(self, records):
        """P12: how many sends may wait for their receipts at once - the Workers option, held to 2 until MQ passed
        for the Codex in force; DEFER with nothing due, or a state that cannot be read."""
        scoped = self._scoped
        if scoped is None or not isinstance(records, list) or len(records) < 2:
            return DEFER
        try:
            chosen = scoped.options().get(OptionKey.WORKERS, DEFAULT_WORKERS)
            measured = scoped.passed(Measurement.MQ)
        except Exception:
            return DEFER
        chosen = chosen if chosen in WORKERS else DEFAULT_WORKERS
        return chosen if measured else min(chosen, UNMEASURED_WORKERS)


def make(paths) -> ParallelDispatch:
    """The capability's factory (registry.CapabilityDef.make): its code for one installation."""
    return ParallelDispatch(paths)
