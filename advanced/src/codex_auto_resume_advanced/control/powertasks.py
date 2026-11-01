# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""The power action after tasks a person picked, on the Dashboard (power_after_tasks, v0.6.21, Discussion #57).

`advanced-power-tasks` reads what the card shows: the person's own conversations whose latest turn runs now, with their
names (codex/turns.running, codex/threads.own - never a word a conversation says, none the person switched off), and,
while core's power action is armed for tasks, each task and how it stands. `advanced-power-tasks-arm` arms core's own
power action for the conversations a person picked - once, with the action and the warning they chose - and writes the
list the capability answers from (engine/powertasks.py). Both the Dashboard's alone (surfaces.py); no MCP tool arms
anything. Turning it off is core's, from anywhere (`power-disarm`, the icon, a notice): it only does less.

Refused unless the capability is on (a watched one is never asked at P21, so an arming for it would only wait), a
conversation is not one offered now, or core refuses the arming (DisablePowerAction, an older watcher, an action Windows
will not do here). Nothing is sent to Codex.
"""
from __future__ import annotations

from codex_auto_resume.domain import ids

from ..engine import powertasks
from ..vocabulary import Refusal
from .resets import _on, _refused, _stale

LIMIT = 200
ACTIONS = ("sleep", "hibernate", "shut_down")
GRACE_MINUTES = (2, 5, 10, 15, 30)


def _offered(runtime):
    """[(thread id, name)] of the person's own conversations whose latest turn runs now, newest first."""
    from codex_auto_resume.store import Store
    from ..codex import inuse
    from ..codex.threads import Threads
    from ..codex.turns import Turns
    with Store(runtime.paths.state_dir) as store:
        off = store.disabled_threads()
    home = inuse.home(runtime.paths)
    running = set(Turns(home).running())
    return [(thread, name) for thread, name in Threads(home).own(LIMIT, off) if thread in running]


def _control(runtime):
    from codex_auto_resume.control import Control
    return Control(runtime.paths)


def _armed(runtime):
    """Core's arming when it is one for tasks, with its nonce, else None."""
    from codex_auto_resume import poweraction
    why, document = _control(runtime).read_power_action()
    armed = (document or {}).get("armed") if why == poweraction.READ_OK else None
    return armed if poweraction.for_tasks(armed) else None


def view(runtime, code=None) -> dict:
    """advanced-power-tasks: {"running": [{thread_id, name}], "armed": None or {action, grace_seconds, failed,
    interrupted, tasks: [{thread_id, end}]}}."""
    try:
        offered = _offered(runtime)
        armed = _armed(runtime)
    except Exception:
        return _refused(Refusal.STATE_UNAVAILABLE, runtime)
    shown = None
    if armed is not None:
        document = powertasks.read(runtime.paths)
        if document is not None and document["nonce"] == armed["nonce"]:
            code = code or powertasks.make(runtime.paths)
            shown = {"action": armed["action"], "grace_seconds": armed["grace_seconds"],
                     "failed": document["failed"], "interrupted": document["interrupted"],
                     "tasks": [{"thread_id": task["thread_id"], "end": end} for task, end in code.stand(document)]}
    found = {"done": True, "refusal": None, "running": [{"thread_id": thread, "name": name} for thread, name in offered],
             "armed": shown}
    try:
        found["generation"] = runtime.state.meta()["generation"]
    except Exception:
        pass
    return found


def arm(runtime, threads, action, grace_minutes, failed, interrupted, generation, turns=None) -> dict:
    """advanced-power-tasks-arm: core's power action armed, once, for `threads` (each running now), and the list
    written with that arming's nonce. A list that cannot be written turns the arming off again."""
    from codex_auto_resume.control import ControlError
    if (not isinstance(threads, list) or not 1 <= len(threads) <= powertasks.MOST
            or not all(type(thread) is str and ids.is_uuid(thread) for thread in threads)
            or len(set(threads)) != len(threads) or action not in ACTIONS
            or type(grace_minutes) is not int or grace_minutes not in GRACE_MINUTES
            or type(failed) is not bool or type(interrupted) is not bool):
        return _refused(Refusal.INVALID_REQUEST, runtime)
    if _stale(runtime, generation):
        return _refused(Refusal.STALE_GENERATION, runtime)
    if not _on(runtime, powertasks.CAPABILITY):
        return _refused(Refusal.NOT_ON, runtime)
    try:
        offered = {thread for thread, _name in _offered(runtime)}
        reader = turns
        if reader is None:
            from ..codex import inuse
            from ..codex.turns import Turns
            reader = Turns(inuse.home(runtime.paths))
        tasks = []
        for thread in threads:
            latest = reader.latest(thread) if thread in offered else None
            if latest is None or latest.status != "inProgress":
                return _refused(Refusal.NO_TURN_RUNNING, runtime)
            tasks.append({"thread_id": thread, "turn_id": latest.turn_id})
    except Exception:
        return _refused(Refusal.STATE_UNAVAILABLE, runtime)
    from codex_auto_resume.control import Control
    layer = Control(runtime.paths, plug=_plug_of(runtime))
    choice = {"action": action, "after": "any_end", "repeat": "once", "grace_minutes": grace_minutes}
    try:
        layer.arm_power_action(choice, actor="dashboard", tasks=True)
    except ControlError as error:
        found = _refused(Refusal.POWER_REFUSED, runtime)
        found["reason"] = getattr(error, "code", None)
        return found
    armed = _armed(runtime)
    document = {"format": powertasks.FORMAT, "nonce": armed["nonce"] if armed else "", "armed_at": armed["armed_at"]
                if armed else 0, "failed": failed, "interrupted": interrupted, "tasks": tasks}
    if armed is None or not powertasks.write(runtime.paths, document):
        try:
            layer.disarm_power_action("dashboard")
        except ControlError:
            pass
        return _refused(Refusal.STATE_UNAVAILABLE, runtime)
    return view(runtime)


def _plug_of(runtime):
    """This edition's plug as the arming is asked through: one whose runtime is this one, so core's check that a plug
    answers for tasks (P21's `wants`) reads the capability's state as this request does."""
    from ..plug import AdvancedPlug
    made = AdvancedPlug(runtime.paths)
    made._runtime = runtime
    return made


def follow(paths, armed) -> None:
    """The capability's stored state moved (arming.py): while it is not on, core's power action armed for tasks is
    turned off and the list goes, so nothing waits for an answer that never comes. Never raises."""
    if armed:
        return
    try:
        from codex_auto_resume import poweraction
        from codex_auto_resume.control import Control
        layer = Control(paths)
        why, document = layer.read_power_action()
        if why == poweraction.READ_OK and poweraction.for_tasks((document or {}).get("armed")):
            layer.disarm_power_action("dashboard")
        powertasks.remove(paths)
    except Exception:
        pass
