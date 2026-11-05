# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""See your other PCs, on the Dashboard (fleet_view, v0.6.22).

`advanced-fleet` reads what the Overview's Other PCs list and the capability's card show: this PC's alias and folder, how
the folder stands, and each other PC as its file says - read-only, checked and bounded (engine/fleet.py). Off or watched the
folder is not touched: the answer is what the state holds. `advanced-fleet-save` keeps the alias and the folder chosen in a
dialog of the window, each checked here; both the Dashboard's alone (surfaces.py): no MCP tool reaches them, and nothing
here acts on a peer. A rename takes this PC's file under its old name with it, where it says it is that one's.
"""
from __future__ import annotations

from ..engine import fleet
from ..vocabulary import ArmingState, OptionKey, Refusal, WordingKey
from .resets import _refused, _stale, _standing


def view(runtime, *, now=None) -> dict:
    """advanced-fleet: {"state", "alias", "folder", "stand", "peers": [...], "ignored", "generation"}."""
    try:
        state = runtime.states(fresh=True).get(fleet.CAPABILITY, ArmingState.OFF)
        words = runtime.state.wordings(fleet.CAPABILITY)
        alias, folder = words.get(WordingKey.FLEET_ALIAS), words.get(WordingKey.FLEET_FOLDER)
        found = {"done": True, "refusal": None, "state": str(state), "alias": alias, "folder": folder, "stand": fleet.UNSET,
                 "peers": [], "ignored": 0, "generation": runtime.state.meta()["generation"]}
    except Exception:
        return _refused(Refusal.STATE_UNAVAILABLE, runtime)
    if state != ArmingState.ARMED or not fleet.alias_valid(alias) or not folder:
        return found
    problem = fleet.folder_problem(folder, runtime.paths)
    if problem is not None:
        found["stand"] = problem
        return found
    try:
        kept, ignored, held = fleet.read_peers(folder, alias)
    except OSError:
        found["stand"] = fleet.MISSING
        return found
    now = runtime.state.clock() if now is None else now
    waiting = fleet.waiting_word(runtime.state.stamped(fleet.CAPABILITY, OptionKey.FLEET_WAITING))
    found.update(stand=fleet.HELD if held else waiting or fleet.OK, ignored=ignored,
                 peers=[fleet.shown(each, now) for each in kept])
    return found


def save(runtime, alias, folder, generation) -> dict:
    """advanced-fleet-save: the alias and the folder kept, each as they must be: WORDING_INVALID with the `problem` word
    otherwise. The watcher is asked to write afresh at its next tick, and a rename takes the old file with it."""
    if _stale(runtime, generation):
        return _refused(Refusal.STALE_GENERATION, runtime)
    if not _standing(runtime, fleet.CAPABILITY):
        return _refused(Refusal.NOT_ON, runtime)
    problem = "alias" if not fleet.alias_valid(alias) else fleet.folder_problem(folder, runtime.paths)
    if problem is not None:
        found = _refused(Refusal.WORDING_INVALID, runtime)
        found["problem"] = problem
        return found
    from ..state import StateError
    try:
        words = runtime.state.wordings(fleet.CAPABILITY)
        was_alias, was_folder = words.get(WordingKey.FLEET_ALIAS), words.get(WordingKey.FLEET_FOLDER)
        generation = runtime.state.set_wording(fleet.CAPABILITY, WordingKey.FLEET_ALIAS, alias, generation=generation,
                                               actor="dashboard")
        runtime.state.set_wording(fleet.CAPABILITY, WordingKey.FLEET_FOLDER, folder, generation=generation,
                                  actor="dashboard")
        runtime.state.unstamp(fleet.CAPABILITY, OptionKey.LAST_FLEET_WRITE)
        runtime.state.unstamp(fleet.CAPABILITY, OptionKey.FLEET_WAITING)
        runtime.state.unstamp(fleet.CAPABILITY, OptionKey.FLEET_WROTE_AT)
    except StateError:
        return _refused(Refusal.STATE_UNAVAILABLE, runtime)
    if was_alias and was_alias != alias and was_folder == folder and fleet.alias_valid(was_alias):
        fleet.remove_old_name(folder, was_alias)
    return view(runtime)
