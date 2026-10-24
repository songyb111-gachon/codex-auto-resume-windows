# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""early_reset on Pending (v0.6.19, issue #50): the line that says what it last did, and its Check now.

While early_reset stands on, Pending shows one compact line: when it last read usage early, what that reading found,
and whether anything was continued - counts and times only, never a word of a conversation. `view` makes it from the
capability's own times (engine/earlyreset.py: CHECKED_AT, AVAILABLE_AT, LIFTED_AT, CHECK_ASKED) and from the usage gate
each waiting record's look at that probe wrote in core's state: found (passed, or held for the second reading), still
limited, or nothing could be told - or not read at all, where an earlier gate (the conversation not open in the app,
say) held the record first.

`check` is Check now (the bridge's advanced-early-check): one fresh reading at once, for every waiting conversation
together, without choosing a row. Taken only while early_reset stands on (watched, off or read down by a policy, it is
refused) and while a record waits for a usage reset. It writes the request for both sides of the look - core's
(store.ask_early_check, so its early window opens before its five minutes are up) and the capability's own
(CHECK_ASKED) - and wakes the watcher as Retry now does. Every click before the probe begins is the one request, and a
click within one reading's life of the last probe asks nothing more: that reading is the one it would get. With no
watcher running the request is taken back and the answer says so. It never sends: the probe it opens is one of the two
readings - which still have to be at least five minutes apart - and every gate runs.
"""
from __future__ import annotations

from contextlib import nullcontext

from codex_auto_resume import failures, machine

from ..engine.earlyreset import EARLY_STATES, SPACING, WINDOW
from ..vocabulary import ArmingState, OptionKey, Refusal

CAPABILITY = "early_reset"
# What the last probe read, as the line says it.
READ_AVAILABLE, READ_LIMITED, READ_UNKNOWN, READ_NONE = "available", "still_limited", "unknown", "not_read"
# What a Check now did: asked, coalesced into a reading just made or already asked for, or taken back with no watcher.
ASKED, COALESCED, NOT_RUNNING, NOTHING_WAITS = "asked", "coalesced", "not_running", "nothing_waits"


def _time(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _on(runtime) -> bool:
    return runtime.states(fresh=True).get(CAPABILITY, ArmingState.OFF) == ArmingState.ARMED


def _core(runtime, store):
    """Core's state: the one the caller holds (a test's), or the Dashboard's own, opened for this read."""
    if store is not None:
        return nullcontext(store)
    from codex_auto_resume.store import Store
    return Store(runtime.paths.state_dir)


def _waiting(store) -> list:
    """Core's records that wait for a usage limit to reset - the ones an early look is for."""
    return [row for row in store.pending() if row.get("category") == failures.USAGE_LIMIT
            and row.get("state") in EARLY_STATES and not row.get("cancel_requested")]


def _read(rows, checked_at) -> str:
    """What the probe begun at `checked_at` read, from the usage gate each waiting record's look at it wrote."""
    found = set()
    for row in rows:
        at = row.get("gate_eval_at")
        if not _time(at) or at < checked_at or not row.get("gate_eval"):
            continue
        try:
            gate = tuple(machine.decode_gates(row["gate_eval"]).get("usage") or ())
        except Exception:
            continue
        if len(gate) != 2 or gate[1] == machine.NOT_CHECKED:
            continue                                 # a gate before usage held it: not read
        if gate[0] == machine.PASS or gate == (machine.WAIT, machine.HELD):
            found.add(READ_AVAILABLE)
        elif gate == (machine.WAIT, "usage_unavailable"):
            found.add(READ_LIMITED)
        else:
            found.add(READ_UNKNOWN)
    return next((word for word in (READ_AVAILABLE, READ_LIMITED, READ_UNKNOWN) if word in found), READ_NONE)


def view(runtime, store=None) -> dict:
    """{"early_check": {...}} while early_reset stands on, else {}: when it last read (`checked_at`, None before it has),
    what it read (`read`), the first yes of the count running (`available_at`) and when the second reading may come
    (`confirm_at`), when two readings last lifted a limit (`lifted_at`) and whether that was this probe (`lifted`),
    how many records wait for a usage reset (`waiting`), and whether a Check now stands (`asked`)."""
    try:
        if not _on(runtime):
            return {}
        state, now = runtime.state, runtime.clock()
        times = {key: state.stamped(CAPABILITY, key) for key in (OptionKey.CHECKED_AT, OptionKey.AVAILABLE_AT,
                                                                  OptionKey.LIFTED_AT, OptionKey.CHECK_ASKED)}
    except Exception:
        return {}
    try:
        with _core(runtime, store) as core:
            rows = _waiting(core)
    except Exception:
        rows = []
    checked, available = times[OptionKey.CHECKED_AT], times[OptionKey.AVAILABLE_AT]
    lifted, asked = times[OptionKey.LIFTED_AT], times[OptionKey.CHECK_ASKED]
    shown = {"checked_at": checked, "read": _read(rows, checked) if checked else None,
             "available_at": available, "confirm_at": available + SPACING if available else None,
             "lifted_at": lifted, "lifted": bool(checked and lifted == checked), "waiting": len(rows),
             "asked": bool(_time(asked) and 0 <= now - asked < SPACING + 1 and (not checked or asked > checked))}
    return {"early_check": shown}


def check(runtime, store=None) -> dict:
    """advanced-early-check: a person's Check now. {"done", "refusal", "check"}: ASKED, COALESCED (a reading made within
    the last WINDOW seconds, or a request already standing), NOT_RUNNING (no watcher to read: nothing stays asked) or
    NOTHING_WAITS. Refused (NOT_ON) unless early_reset stands on; STATE_UNAVAILABLE where a request cannot be written."""
    if runtime.registry.get(CAPABILITY) is None:
        return {"done": False, "refusal": Refusal.UNKNOWN_CAPABILITY}
    if not _on(runtime):
        return {"done": False, "refusal": Refusal.NOT_ON}
    state, now = runtime.state, runtime.clock()
    try:
        with _core(runtime, store) as core:
            if not _waiting(core):
                return {"done": True, "refusal": None, "check": NOTHING_WAITS}
            checked = state.stamped(CAPABILITY, OptionKey.CHECKED_AT)
            asked = state.stamped(CAPABILITY, OptionKey.CHECK_ASKED)
            if ((_time(checked) and 0 <= now - checked < WINDOW)
                    or (_time(asked) and 0 <= now - asked < SPACING + 1 and (not checked or asked > checked)
                        and core.early_check_asked(now))):
                return {"done": True, "refusal": None, "check": COALESCED}
            if not (state.stamp(CAPABILITY, OptionKey.CHECK_ASKED, max(1, int(now)))
                    and core.ask_early_check(now)):
                state.unstamp(CAPABILITY, OptionKey.CHECK_ASKED)
                return {"done": False, "refusal": Refusal.STATE_UNAVAILABLE}
            from .sendnow import wake
            try:
                running = wake(runtime.paths)
            except Exception:
                running = False
            if not running:
                core.early_check_taken()
                state.unstamp(CAPABILITY, OptionKey.CHECK_ASKED)
                return {"done": True, "refusal": None, "check": NOT_RUNNING}
            return {"done": True, "refusal": None, "check": ASKED}
    except Exception:
        return {"done": False, "refusal": Refusal.STATE_UNAVAILABLE}
