"""The watcher's memory: its peak, always shown, and a guard that is off by default (v0.6.11).

Every tick the watcher asks Windows how much private memory its own process has committed, and what
the most was (win/ownprocess.py). The peak goes into the heartbeat, and so into Diagnostics and
get_status, as a number and nothing else. That much happens at every setting, and asks Windows about
this process alone; nothing about Codex, and nothing about recovery, depends on it.

The guard is a setting, `memory_guard`, off unless a person turns it on:

    off     nothing more happens - v0.6.10's watcher, which had no guard
    warn    the first time the watcher is over the limit, one notification says so; it goes on
    stop    the same, and the watcher then stops, between two ticks, the way a Stop stops it

`memory_guard_limit` is the limit, 256 MiB to 2 GiB - or, with Custom..., from 128 MiB to 16 GiB in
whole MiB (ownvalues.py) - read only while the guard is on. A stop happens
only after a tick has ended - never inside one, so never while a continuation is being sent - and the
watcher leaves with its own exit code (runtime/loop.py, EXIT_MEMORY_GUARD), which the launcher does
not start again (scripts/watcher_launcher.py). Nothing is lost: every claim is durable before a send
(A5), and the next watcher reconciles before it sends anything. No other process watches this one;
the standard edition has no supervisor (F8).

Pure: settings and numbers in, answers out.
"""
from __future__ import annotations

from . import ownvalues
from .domain.vocabulary import MemoryGuard, MemoryLimit

GUARD_FIELD, LIMIT_FIELD = "memory_guard", "memory_guard_limit"
MODES, LIMITS = tuple(MemoryGuard), tuple(MemoryLimit)
DEFAULT_MODE, DEFAULT_LIMIT = MemoryGuard.OFF.value, MemoryLimit.MB1024.value
MIB = 1024 * 1024
# What the guard answers after a tick: nothing to do, say so once, or stop.
OK, WARN, STOP = "ok", "warn", "stop"
OWN = {LIMIT_FIELD: ownvalues.Own(ownvalues.COUNT, 128, 16 * 1024, ("",), prefix="mb", amount="own.mb")}


def _values(values) -> dict:
    return values if isinstance(values, dict) else {}


def mode(values) -> str:
    """off, warn or stop - off for anything the settings layer would not store."""
    chosen = _values(values).get(GUARD_FIELD)
    return chosen if chosen in MODES else DEFAULT_MODE


def limit_mib(values) -> int:
    """The limit, in MiB."""
    own = ownvalues.amount(OWN[LIMIT_FIELD], _values(values).get(LIMIT_FIELD))
    return own if own is not None else ownvalues.amount(OWN[LIMIT_FIELD], DEFAULT_LIMIT)


def mib(count) -> int | None:
    """A number of bytes as whole MiB, rounded up so a little over a limit never reads as the limit;
    None for anything that is not a count of bytes."""
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        return None
    return -(-count // MIB)


def verdict(values, private, warned) -> str:
    """After a tick: OK, WARN (the first time over the limit, with warn) or STOP (over it, with stop).

    `private` is the private memory the watcher has committed now, in bytes - None when Windows could
    not say, which is never over anything. `warned` is whether this watcher has said so already."""
    chosen = mode(values)
    if chosen == MemoryGuard.OFF or isinstance(private, bool) or not isinstance(private, int):
        return OK
    if private <= limit_mib(values) * MIB:
        return OK
    if chosen == MemoryGuard.STOP:
        return STOP
    return OK if warned else WARN
