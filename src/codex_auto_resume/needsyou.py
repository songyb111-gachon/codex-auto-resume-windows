"""Needs-you notices (v0.6.11): a conversation that needs a person, said once.

Two kinds of thing need a person and are never resumed by this product:

* a failure the classifier knows and will not retry (failures.TERMINAL) - the request was refused
  or the conversation is too long (terminal_invalid), a content policy stopped it
  (terminal_policy), Codex is signed out (terminal_auth), or Codex itself gave up
  (terminal_failure). Never terminal_user: a person who stopped a turn knows it;
* a turn that has recorded nothing new for a while - read from lifecycle columns and item counts
  only, so it says that nothing moved and never why: no signal says an approval is pending (J6).

Each is told once, through the notification the watcher already raises (engine/announce.py), with
one next step from the catalog and one button, Open Dashboard, which opens Settings: that is where
a kind is switched off (C14). Nothing here sends, registers a recovery or decides one - a notice is
kept in its own table, which nothing that decides a send reads (store/columns.py).

Off by default, as v0.6.10 was: `notify_needs_you` is the one notification event that starts off,
and the turn that stops moving is never looked for until a time is chosen. Pure: settings in,
words out.
"""
from __future__ import annotations

from .domain.vocabulary import StallWait

# The failures that need a person, each with the setting that switches it and its next step.
KINDS = ("terminal_invalid", "terminal_policy", "terminal_auth", "terminal_failure")
KIND_FIELDS = {kind: "notify_needs_you_" + kind[len("terminal_"):] for kind in KINDS}
# A turn that stopped moving, as a notice's kind: no failure category, and none of the ones above.
STALLED = "stalled_turn"
NOTICE_KINDS = frozenset(KINDS) | {STALLED}
# The catalog sentence each kind is told with: what to do next, in Codex.
NEXT_STEPS = {kind: "msg.needs_you_" + kind[len("terminal_"):] for kind in KINDS}
NEXT_STEPS[STALLED] = "msg.needs_you_stalled"
# The one notification event every kind is raised under, and the setting that turns it on.
EVENT = "needs_you"
EVENT_FIELD = "notify_" + EVENT
SOUND_FIELD = "needs_you_sound"
STALL_FIELD = "stall_after"

STALL_WAITS = tuple(StallWait)
DEFAULT_STALL = StallWait.OFF.value
STALL_SECONDS = {StallWait.M10: 600, StallWait.M15: 900, StallWait.M30: 1800,
                 StallWait.H1: 3600, StallWait.H2: 7200}
# A failure or a stopped turn older than this is never told: the longest look-back detection has
# (A16) - and a notice kept past a day more than it may be let go, since nothing older is looked at.
WINDOW_SECONDS = 7 * 86400
KEEP_SECONDS = WINDOW_SECONDS + 86400


def _on(values, name) -> bool:
    return isinstance(values, dict) and values.get(name) is True


def told(values) -> bool:
    """Whether needs-you notices are raised at all: notifications on, and this one of them."""
    return _on(values, "notifications") and _on(values, EVENT_FIELD)


def kinds(values) -> frozenset:
    """The failure categories a notice is raised for now - none at the defaults."""
    if not told(values):
        return frozenset()
    return frozenset(kind for kind in KINDS if _on(values, KIND_FIELDS[kind]))


def stall_seconds(values):
    """How long a turn may record nothing new before it is told, or None - never, at the defaults."""
    if not told(values):
        return None
    chosen = values.get(STALL_FIELD)
    return STALL_SECONDS.get(chosen) if chosen in STALL_WAITS else None


def minutes(seconds) -> int:
    """A stall's length in whole minutes, as the notice says it."""
    return max(1, int(seconds) // 60)
