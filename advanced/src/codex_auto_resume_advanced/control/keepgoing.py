# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""The Dashboard's keep going (v0.6.15-beta): the conversations kept going read, one picked with a count, one stopped.

Each is the long-lived bridge's, the Dashboard's alone (surfaces.py), against the generation the page read: a page
that had not seen something turned off is refused, as an arm is. No MCP tool reaches any of them. A conversation is
picked only while keep_going stands on and the conversation is switched on, with a count of 1 to 10 - of which no
more than engine/keepgoing.UNMEASURED_COUNT are sent until MK passes on the Codex in force (`count_capped`).
"""
from __future__ import annotations

from codex_auto_resume.domain import ids

from ..engine.keepgoing import CAPABILITY, UNMEASURED_COUNT, allowed
from ..state.continuations import KEEP_COUNTS
from ..vocabulary import KeepReason, KeepState, Measurement, Refusal
from .resets import _refused, _stale, _standing, switched_off

SHOWN = ("thread_id", "count", "used", "armed_at", "state", "reason", "finished_at")


def _measured(runtime) -> bool:
    try:
        return runtime.arming.verdict(Measurement.MK) == "pass"
    except Exception:
        return False


def _failed(runtime) -> bool:
    """Whether MK failed (arming.verdict): the card says the count is held because the measurement failed."""
    try:
        return runtime.arming.verdict(Measurement.MK) == "fail"
    except Exception:
        return False


def view(runtime) -> dict:
    """advanced-keep-going: every conversation kept going or stopped, what it may have now, whether the count is
    held to UNMEASURED_COUNT on this Codex (`count_capped`) and whether that is because MK failed (`count_failed`)."""
    try:
        rows = runtime.state.keep_going()
        generation = runtime.state.meta()["generation"]
    except Exception:
        return _refused(Refusal.STATE_UNAVAILABLE)
    measured = _measured(runtime)
    shown = [dict({name: row.get(name) for name in SHOWN}, allowed=allowed(row["count"], measured)) for row in rows]
    return {"done": True, "refusal": None, "generation": generation, "rows": shown,
            "count_capped": not measured, "count_failed": _failed(runtime), "limits": {"count": max(KEEP_COUNTS), "unmeasured": UNMEASURED_COUNT}}


def set_one(runtime, argument) -> dict:
    """advanced-keep-going-set: `thread_id` kept going for `count` continuations, made again where it was."""
    if _stale(runtime, argument.get("generation")):
        return _refused(Refusal.STALE_GENERATION, runtime)
    thread, count = argument.get("thread_id"), argument.get("count")
    if not ids.is_uuid(thread):
        return _refused(Refusal.INVALID_REQUEST, runtime)
    if type(count) is not int or count not in KEEP_COUNTS:
        return _refused(Refusal.KEEP_COUNT_INVALID, runtime)
    if not _standing(runtime, CAPABILITY):
        return _refused(Refusal.NOT_ON, runtime)
    if switched_off(runtime, thread):
        return _refused(Refusal.CONVERSATION_OFF, runtime)
    try:
        runtime.state.set_keep_going(thread, count, at=runtime.clock())
    except Exception:
        return _refused(Refusal.STATE_UNAVAILABLE, runtime)
    return dict(view(runtime), done=True)


def stop(runtime, argument) -> dict:
    """advanced-keep-going-stop: `thread_id` kept going no more (by_person)."""
    if _stale(runtime, argument.get("generation")):
        return _refused(Refusal.STALE_GENERATION, runtime)
    thread = argument.get("thread_id")
    if not ids.is_uuid(thread):
        return _refused(Refusal.INVALID_REQUEST, runtime)
    try:
        row = runtime.state.keep_going(thread)
        if row is None or row["state"] != KeepState.ON:
            return _refused(Refusal.INVALID_REQUEST, runtime)
        runtime.state.stop_keep_going(KeepReason.BY_PERSON, thread_id=thread, at=runtime.clock())
    except Exception:
        return _refused(Refusal.STATE_UNAVAILABLE, runtime)
    return dict(view(runtime), done=True)
