# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""Who may turn a capability on, who may turn it off, and what turns it off by itself.

Every capability starts off, and stays off until a person turns it on, one at a time, in the
Dashboard, after its statement. So `arm` - which also moves one to "Watch first" - takes an actor
and refuses every actor but the Dashboard, and it needs three things only the Dashboard has just
shown the person:

* the statement revision they read, which must be the current one;
* the generation the Dashboard read the list at, which must still be the current one, so that
  anything turned off anywhere since - by a person, a tripwire or a policy - is never undone by a
  window that had not seen it yet;
* for "on", the Codex version the person acknowledged, which `compat.permits` must accept at the
  experimental tier: the capability's local checks passed, the registry says nothing against it,
  and the acknowledgement is for this exact engine. UNKNOWN is never enough.

Turning off is the other way round. `disarm` and `all_off` take any actor that is a surface -
the Dashboard, MCP, the icon, a card - and need nothing: turning something off only ever does
less, like a Pause.

Shadow ("Watch first") never promotes itself: nothing here, or anywhere, moves a capability
from watched to on except a person arming it.

What a capability is at this moment (`standing`) is its stored state as seen through what has
happened since, and a few of those things are carried out, because each means the person's
agreement no longer covers what the capability would do:

* the tripwires turn it off: its statement changed (a new revision the person has not read), the
  capability it stands on failed a local check here, FAILED_HERE or INCOMPATIBLE, a hook of its
  raised, or a send it paid for became submission_unknown;
* a new Codex version turns an armed capability off: the acknowledgement was for another one;
* a policy (policy.py) only reads it down - off, or watched - and changes nothing stored.
"""
from __future__ import annotations

import time

from codex_auto_resume.compat import permits
from codex_auto_resume.compat.model import FAILED_HERE, INCOMPATIBLE

from . import policy as _policy
from .registry import GLOBAL_HOURLY
from .state import StaleGeneration, StateError
from .statement import CATALOGS
from .vocabulary import TRIPWIRES, Actor, ArmingState, OffReason, Refusal

TIER = "experimental"
# The actors a person turns a capability off through.
SURFACES = frozenset({Actor.DASHBOARD, Actor.MCP, Actor.TRAY, Actor.CARD})
# What the state of a capability in core's store is when a send it paid for may or may not have
# reached Codex (engine/dispatch.py).
SUBMISSION_UNKNOWN = "submission_unknown"


def compat_trip(view, definition):
    """The tripwire the Compatibility Registry trips for `definition`, or None."""
    capabilities = view.get("capabilities") if isinstance(view, dict) else None
    entry = capabilities.get(definition.compat) if isinstance(capabilities, dict) else None
    state = entry.get("state") if isinstance(entry, dict) else None
    if state == FAILED_HERE:
        return OffReason.FAILED_HERE
    if state == INCOMPATIBLE:
        return (OffReason.LOCAL_CHECK_FAILED if entry.get("reason") == "local_check_failed"
                else OffReason.INCOMPATIBLE)
    return None


def engine_version(view):
    engine = view.get("engine") if isinstance(view, dict) else None
    version = engine.get("version") if isinstance(engine, dict) else None
    return version if isinstance(version, str) else None


def standing(definition, row, policy, view) -> tuple:
    """(state now, what must be done to the stored state or None, permits' reason or None).

    Pure. The order is the order of what overrides what: a changed statement and a failed
    compatibility turn it off whatever else holds; a policy reads it down; and "on" is on only
    while `permits` agrees, with a new Codex version turning it off."""
    stored = row["state"] if row else ArmingState.OFF
    if stored == ArmingState.OFF:
        return ArmingState.OFF, None, None
    if row.get("statement_revision") != definition.revision:
        return ArmingState.OFF, OffReason.STATEMENT_CHANGED, None
    tripped = compat_trip(view, definition)
    if tripped is not None:
        return ArmingState.OFF, tripped, None
    if not policy.admits(definition.id):
        return ArmingState.OFF, None, None
    if stored == ArmingState.ARMED and policy.force_shadow:
        return ArmingState.SHADOW, None, None
    if stored == ArmingState.ARMED:
        allowed, reason = permits(view, definition.compat, tier=TIER, opt_in=True,
                                  engine_version=engine_version(view),
                                  acknowledged_version=row.get("engine_version"))
        if not allowed:
            return (ArmingState.OFF,
                    OffReason.ENGINE_CHANGED if reason == "not_acknowledged_for_this_engine" else None,
                    reason)
    return stored, None, None


def _was_unknown(core_view, key, since) -> bool:
    """Whether core holds record `key` as submission_unknown, or moved it there at or after
    `since`. A view that cannot answer says nothing either way."""
    try:
        record = core_view.get(key)
    except Exception:
        record = None
    if isinstance(record, dict) and record.get("state") == SUBMISSION_UNKNOWN:
        return True
    try:
        history = core_view.events(key)
    except Exception:
        return False
    return any(isinstance(event, dict) and event.get("to_state") == SUBMISSION_UNKNOWN
               and isinstance(event.get("at"), (int, float)) and event["at"] >= since
               for event in history or ())


def _view_of(paths):
    """The Compatibility Registry's view, as the watcher last wrote it, bound to the engine the
    settings name - what every front end shows."""
    from codex_auto_resume import compatio, settings
    return compatio.reader_view(paths, settings=settings.load(paths.settings_file))


class Arming:
    def __init__(self, state, *, catalogs=CATALOGS, policy=None, view=None, clock=time.time):
        self.state = state
        self.registry = state.registry
        self.catalogs = catalogs
        self._policy = policy or _policy.read
        self._view = view or (lambda: _view_of(state.paths))
        self.clock = clock

    def policy(self):
        try:
            found = self._policy()
        except Exception:
            return _policy.STRICTEST
        return found if isinstance(found, _policy.Policy) else _policy.STRICTEST

    def view(self) -> dict:
        """The Compatibility Registry's view; one that cannot be read is UNKNOWN for everything,
        which permits nothing."""
        try:
            found = self._view()
        except Exception:
            return {}
        return found if isinstance(found, dict) else {}

    # ------------------------------------------------------------------ now
    def current(self, *, view=None, policy=None) -> dict:
        """{id: state now} for every capability of the registry, carrying out every trip and
        reset `standing` finds. With no capability, nothing is read."""
        if not len(self.registry):
            return {}
        view = self.view() if view is None else view
        policy = self.policy() if policy is None else policy
        try:
            rows = self.state.arming()
        except StateError:
            rows = {}
        states = {}
        for definition in self.registry:
            state, change, _reason = standing(definition, rows.get(definition.id), policy, view)
            if change is not None:
                self._off(definition.id, change)
            states[definition.id] = state
        return states

    def _off(self, capability, reason) -> bool:
        actor = Actor.TRIPWIRE if reason in TRIPWIRES else Actor.ENGINE_CHANGE
        try:
            return self.state.move(capability, ArmingState.OFF, actor=actor, reason=reason,
                                   at=self.clock())[0]
        except StateError:
            return False                   # it reads as off either way

    def trip(self, capability, reason) -> bool:
        """A tripwire: `capability` off, with why. Only a tripwire's reason is one."""
        if OffReason(reason) not in TRIPWIRES:
            raise ValueError("not a tripwire")
        return self._off(capability, reason)

    def sweep(self, core_view) -> None:
        """Once a tick: every trip and reset `standing` finds, and the one it cannot find alone -
        a send a capability paid for, since it was last turned on, that core holds or held as
        submission_unknown.

        Held, not only holds: the tick observes before it asks P8, and core's own late-delivery
        case - the queue's answer unknown, the item in Codex's queue all the same - moves the
        record on in that same watch. Its state now would say nothing, so its journal is read
        (engine/options.py, VIEW_READS)."""
        self.current()
        if not len(self.registry):
            return
        try:
            rows = self.state.arming()
        except StateError:
            return
        for capability, row in rows.items():
            if row["state"] != ArmingState.ARMED or row["since"] is None:
                continue
            try:
                spent_on = self.state.spends_since(capability, row["since"])
            except StateError:
                return
            for key in spent_on:
                if _was_unknown(core_view, key, row["since"]):
                    self.trip(capability, OffReason.SUBMISSION_UNKNOWN)
                    break

    # ------------------------------------------------------------------ on
    def arm(self, capability, *, state, revision, generation, acknowledged_version=None,
            actor) -> dict:
        """Move `capability` to watched (SHADOW) or on (ARMED), for a person in the Dashboard.

        {"done": bool, "refusal": Refusal or None, "permit": permits' reason or None,
        "generation": the generation after}."""
        def refused(why, permit=None):
            return {"done": False, "refusal": why, "permit": permit,
                    "generation": self._generation()}

        if actor != Actor.DASHBOARD:
            return refused(Refusal.NOT_THE_DASHBOARD)
        definition = self.registry.get(capability)
        if definition is None:
            return refused(Refusal.UNKNOWN_CAPABILITY)
        if (state not in (ArmingState.SHADOW, ArmingState.ARMED) or type(revision) is not int
                or type(generation) is not int
                or (state == ArmingState.ARMED and not isinstance(acknowledged_version, str))):
            return refused(Refusal.INVALID_REQUEST)
        policy = self.policy()
        if policy.forbid:
            return refused(Refusal.FORBIDDEN_BY_POLICY)
        if not policy.admits(definition.id):
            return refused(Refusal.NOT_ALLOWED_BY_POLICY)
        if state == ArmingState.ARMED and policy.force_shadow:
            return refused(Refusal.SHADOW_FORCED_BY_POLICY)
        if revision != definition.revision:
            return refused(Refusal.STALE_REVISION)
        if not self.catalogs.complete_in(definition, "en"):
            return refused(Refusal.STATEMENT_INCOMPLETE)
        view = self.view()
        tripped = compat_trip(view, definition)
        if tripped is not None:
            return refused(Refusal.NOT_PERMITTED, "incompatible")
        version = None
        if state == ArmingState.ARMED:
            allowed, reason = permits(view, definition.compat, tier=TIER, opt_in=True,
                                      engine_version=engine_version(view),
                                      acknowledged_version=acknowledged_version)
            if not allowed:
                return refused(Refusal.NOT_PERMITTED, reason)
            version = acknowledged_version
        try:
            _moved, after = self.state.move(capability, state, actor=actor, revision=revision,
                                            engine_version=version, generation=generation,
                                            at=self.clock())
        except StaleGeneration:
            return refused(Refusal.STALE_GENERATION)
        except StateError:
            return refused(Refusal.STATE_UNAVAILABLE)
        return {"done": True, "refusal": None, "permit": None, "generation": after}

    def _generation(self) -> int:
        try:
            return self.state.meta()["generation"]
        except StateError:
            return 0

    # ------------------------------------------------------------------ off
    def disarm(self, capability, *, actor) -> dict:
        """One capability off, from any surface. Needs nothing, and always wins."""
        if actor not in SURFACES:
            return {"done": False, "refusal": Refusal.INVALID_REQUEST, "changed": False}
        if self.registry.get(capability) is None:
            return {"done": False, "refusal": Refusal.UNKNOWN_CAPABILITY, "changed": False}
        try:
            changed, _after = self.state.move(capability, ArmingState.OFF, actor=actor,
                                              reason=OffReason.DISARMED, at=self.clock())
        except StateError:
            return {"done": False, "refusal": Refusal.STATE_UNAVAILABLE, "changed": False}
        return {"done": True, "refusal": None, "changed": changed}

    def all_off(self, *, actor) -> dict:
        """"All advanced features off": every capability, at once, from any surface."""
        if actor not in SURFACES:
            return {"done": False, "refusal": Refusal.INVALID_REQUEST, "count": 0}
        try:
            count, _after = self.state.all_off(actor=actor, reason=OffReason.ALL_OFF, at=self.clock())
        except StateError:
            return {"done": False, "refusal": Refusal.STATE_UNAVAILABLE, "count": 0}
        return {"done": True, "refusal": None, "count": count}

    def edition_entered(self) -> int:
        """The installer has just entered this edition: every capability off, whatever an
        earlier advanced installation of this home left on. Writes nothing where there is no
        advanced state, since then nothing can be on."""
        return self.state.all_off(actor=Actor.EDITION_ENTRY, reason=OffReason.EDITION_ENTERED,
                                  at=self.clock())[0]

    # ------------------------------------------------------------------ ceiling
    def set_global_hourly(self, value, *, generation, actor) -> dict:
        """Lower the one ceiling over every capability together, in the Dashboard. It can be
        set anywhere from 1 to GLOBAL_HOURLY, and never above."""
        if actor != Actor.DASHBOARD:
            return {"done": False, "refusal": Refusal.NOT_THE_DASHBOARD}
        if (type(value) is not int or not 1 <= value <= GLOBAL_HOURLY
                or type(generation) is not int):
            return {"done": False, "refusal": Refusal.INVALID_REQUEST}
        try:
            after = self.state.set_global_hourly(value, generation=generation, actor=actor,
                                                 at=self.clock())
        except StaleGeneration:
            return {"done": False, "refusal": Refusal.STALE_GENERATION}
        except StateError:
            return {"done": False, "refusal": Refusal.STATE_UNAVAILABLE}
        return {"done": True, "refusal": None, "generation": after}

    # ------------------------------------------------------------------ shown
    def listing(self) -> dict:
        """Every capability as a surface shows it: where it is stored, what it is now, since
        when and by whom, and what a person would be agreeing to."""
        view, policy = self.view(), self.policy()
        states = self.current(view=view, policy=policy)
        try:
            rows, meta = self.state.arming(), self.state.meta()
        except StateError:
            rows, meta = {}, {"generation": 0, "global_hourly": GLOBAL_HOURLY}
        shown = []
        for definition in self.registry:
            row = rows.get(definition.id) or {}
            shown.append({
                "id": definition.id, "stored": str(row.get("state", ArmingState.OFF)),
                "state": str(states.get(definition.id, ArmingState.OFF)),
                "since": row.get("since"), "by": row.get("actor"), "reason": row.get("reason"),
                "revision": definition.revision, "read_revision": row.get("statement_revision"),
                "acknowledged_version": row.get("engine_version"),
                "departs_from": list(definition.departs_from), "compat": definition.compat,
                "points": sorted(str(point) for point in definition.points),
                "ceilings": {"per_day": definition.ceilings.per_day,
                             "per_conversation": definition.ceilings.per_conversation}})
        return {"generation": meta["generation"], "global_hourly": meta["global_hourly"],
                "global_hourly_default": GLOBAL_HOURLY, "engine_version": engine_version(view),
                "policy": policy.as_json(), "on": sum(item["state"] == ArmingState.ARMED for item in shown),
                "capabilities": shown}
