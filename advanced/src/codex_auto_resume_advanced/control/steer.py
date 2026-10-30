# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""The Dashboard's steer (v0.6.20, issue #50 item 2 - steer_send): one line asked to be added to the turn running in a
conversation, and the steers shown in History.

`request` (the bridge's advanced-steer, the Dashboard's alone - surfaces.py; no MCP tool reaches it) sends nothing: it
writes one row `requested` (state/steers.py) and wakes the watcher, whose errand alone writes it (engine/steer.py). It is
taken only while steer_send stands on - not watched: a steer is for the turn running now, and nothing watched would ever
send it - for a conversation switched on, with words core's check of a person's message passes
(continuation.validate_prompt: no empty text, no marker, no shipped template) within the prompt queue's bound, one steer
still waiting in that conversation at most, at most 30 in one conversation and 60 in all in 24 hours - and refused at
once where Codex's history says that conversation's latest turn is not running (no_turn_running), so the person is told
before anything waits.

`rows` is what History lists (control/prompts.view carries it): every steer of the last 30 days, its words - the
person's own, kept so they can see exactly what went in, since the Codex app does not show a steered line - when it was
asked and when it settled, and its outcome: accepted, unconfirmed (may have been delivered) or refused with why. Never
"seen in the conversation": that cannot be observed (MSTEER2).
"""
from __future__ import annotations

import uuid

from codex_auto_resume import continuation
from codex_auto_resume.domain import ids

from ..engine.steer import CAPABILITY, DAY, PER_CONVERSATION, PER_DAY, RUNNING, latest_status
from ..state.steers import WAITING
from ..vocabulary import Refusal
from .resets import _on, _refused, _stale, switched_off

SHOWN = ("steer_id", "thread_id", "words", "state", "reason", "created_at", "finished_at")
# How long History shows a steer: as long as the state keeps it (state/journal.py).
KEPT = 30 * DAY


def rows(runtime) -> list:
    """Every steer of the last 30 days, newest first, as History shows it; empty where none is or none can be read."""
    try:
        found = runtime.state.steers(max(0.0, runtime.clock() - KEPT))
    except Exception:
        return []
    shown = [{name: row.get(name) for name in SHOWN} for row in found]
    shown.sort(key=lambda row: (row["created_at"], row["steer_id"]), reverse=True)
    return shown


def waiting(runtime) -> int:
    """How many steers wait for the watcher: a count, for P10's status - which tells the page to read History again."""
    try:
        return sum(row["state"] in WAITING for row in runtime.state.waiting_steers())
    except Exception:
        return 0


def request(runtime, argument) -> dict:
    """advanced-steer: `words` asked to be added to the turn running in `thread_id`, against the generation the page read
    (control/prompts.view's answer, with `steer` the new row's id)."""
    from . import prompts
    if _stale(runtime, argument.get("generation")):
        return _refused(Refusal.STALE_GENERATION, runtime)
    thread, words = argument.get("thread_id"), argument.get("words")
    if not ids.is_uuid(thread):
        return _refused(Refusal.INVALID_REQUEST, runtime)
    if not _on(runtime, CAPABILITY):
        return _refused(Refusal.NOT_ON, runtime)
    if switched_off(runtime, thread):
        return _refused(Refusal.CONVERSATION_OFF, runtime)
    try:
        continuation.validate_prompt(words)
    except Exception:
        return _refused(Refusal.PROMPT_REFUSED, runtime)
    if len(words) > prompts.words_limit(runtime):
        return _refused(Refusal.PROMPT_REFUSED, runtime)
    now = runtime.clock()
    try:
        recent = runtime.state.steers(max(0.0, now - DAY))
    except Exception:
        return _refused(Refusal.STATE_UNAVAILABLE, runtime)
    if any(row["thread_id"] == thread and row["state"] in WAITING for row in recent):
        return _refused(Refusal.BEING_SENT, runtime)
    if (len(recent) >= PER_DAY
            or sum(row["thread_id"] == thread for row in recent) >= PER_CONVERSATION):
        return _refused(Refusal.QUEUE_FULL, runtime)
    from ..codex import inuse
    if latest_status(inuse.home(runtime.paths), thread) != RUNNING:
        return _refused(Refusal.NO_TURN_RUNNING, runtime)
    try:
        steer = runtime.state.add_steer(thread, words, str(uuid.uuid4()), at=now)
    except Exception:
        return _refused(Refusal.STATE_UNAVAILABLE, runtime)
    try:
        from .sendnow import wake
        wake(runtime.paths)
    except Exception:
        pass                                         # the next tick takes it
    return dict(prompts.view(runtime), done=True, steer=steer)
