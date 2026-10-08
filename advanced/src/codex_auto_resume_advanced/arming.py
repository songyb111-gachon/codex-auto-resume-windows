# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""Who may turn a capability on, who may turn it off, and what turns it off by itself.

Every capability starts off, and stays off until a person turns it on, one at a time, in the
Dashboard, after its statement. So `arm` - which also moves one to "Watch first" - takes an actor
and refuses every actor but the Dashboard, and it needs what only the Dashboard has just shown
the person, each of which must still hold when the request arrives:

* the statement revision they read;
* the generation the Dashboard read the list at, so that anything turned off anywhere since - by
  a person, a tripwire or a policy - is never undone by a window that had not seen it yet;
* the statement's warnings (`warnings_for`), exactly as they hold now: a measurement its route
  rests on that failed or was never made for this Codex, a compatibility grade of FAILED_HERE,
  INCOMPATIBLE or UNKNOWN, no Codex version known. A warning never refuses. Turning the
  capability on, or watching it, is the person's confirmation of every warning shown, and the
  set they confirmed is stored with the state;
* for "on", the Codex version the Dashboard showed, which is the one in force - or none, where
  none is known, which is itself a warning.

That replaced decision C7 (the owner, 2026-09-26). A failed measurement or a low grade used to be
a refusal - compat.permits at the experimental tier - and is now a warning the person confirms.
What still refuses a capability is an administrator's policy (policy.py): ForbidAdvanced,
AllowedCapabilities, and ForceShadow for "on". Every other refusal says only that the request
was not the person's own, current confirmation, which the Dashboard can ask for again at once.

Turning off is the other way round. `disarm` and `all_off` take any actor that is a surface -
the Dashboard, MCP, the icon, a card - and need nothing: turning something off only ever does
less, like a Pause. MCP can turn things off and nothing else (surfaces.py).

Shadow ("Watch first") never promotes itself: nothing here, or anywhere, moves a capability
from watched to on except a person arming it.

What a capability is at this moment (`standing`) is its stored state as seen through what has
happened since, and a few of those things are carried out, because each means the person's
agreement no longer covers what the capability would do:

* the tripwires turn it off: its statement changed (a new revision the person has not read); a
  warning they did not confirm appeared that says what it stands on went wrong - its
  compatibility FAILED_HERE or INCOMPATIBLE here, or a measurement its route rests on failed; a
  hook of its raised; or a send it paid for became submission_unknown - that send, claimed when
  it paid, and not a later one core made of the same record alone. A warning they confirmed never
  trips it: it was so when they turned it on;
* a new Codex version turns an armed capability off: the acknowledgement was for another one;
* a policy (policy.py) only reads it down - off, or watched - and changes nothing stored; so,
  for one that is on, does a compatibility or a Codex version that cannot be read now, where the
  person did not confirm that.

Re-arming is always possible: whatever turned a capability off - a person, a tripwire, a new
Codex - the Dashboard can turn it on again, with its statement as it reads then.

Keep on (v0.6.14, the owner's K8, amending K7): a person may keep a capability that is on or watched
from turning itself off, in the Dashboard, after its warning. Kept on, each tripwire and a new Codex
version are noted instead, the most serious kept until the person arms it again; a hook that raises
costs only the record it raised for (runtime.py); what cannot be read still holds it back (E1); and the
policy reads it down first, so the administrator wins. Any move to off - the person's, from any
surface - takes it away.

Send again (v0.6.14), only with Keep on: a continuation the kept-on capability paid for that cannot be
proven to have arrived is sent once more, under the once-more capability's rules (`resender`), and only
where the policy admits that capability as well - Send again does what it does, so it departs from what
it departs from too (`departs`). A continuation sent once more and then found twice turns off what sent
it again (`sweep`): the once-more capability itself, whether or not it is kept on, or Send again alone,
the capability staying on with that noted.
"""
from __future__ import annotations

import math
import time

from codex_auto_resume.compat.model import FAILED_HERE, INCOMPATIBLE, STATES, UNKNOWN

from . import policy as _policy
from .measured import MEASURED
from .registry import GLOBAL_HOURLY, ONCE_MORE
from .state import Refused, StaleGeneration, StateError
from .state.spend import CHANNELS
from .state.choices import DAY, RECENT_DAYS, RULES_LIMIT, aggregated, tag_problem
from .statement import CATALOGS
from .vocabulary import (KEPT_NOTICES, TRIPWIRES, Actor, ArmingState, ArmingWarning, CapabilityKind,
                         KeepOn, OffReason, OverrideKind, Refusal, Verdict)

# The actors a person turns a capability off through.
SURFACES = frozenset({Actor.DASHBOARD, Actor.MCP, Actor.TRAY, Actor.CARD})
# What the state of a capability in core's store is when a send it paid for may or may not have
# reached Codex (engine/dispatch.py).
SUBMISSION_UNKNOWN = "submission_unknown"
# How far apart a unit's time and a claim's may be and still be the one claim. The ledger spends a
# unit at the very time the claim writes (ledger.py, store/claims.py), so they are equal; this only
# absorbs a float's round trip. Two claims of one record are never this close.
SAME_CLAIM = 0.001
# What core writes into a record it sent once more whose proof is then found twice (core's
# engine/resend.py, watch_resent; and engine/reconcile.py while it follows the turn).
DUPLICATE = "duplicate_marker"
# How long a resend is watched for a second copy: core's own window for an uncertain one.
RESEND_WATCH = 86400
# The warnings that, appearing where the person did not confirm them, say that what a capability
# stands on went wrong: each is a tripwire, with its own reason. The first found trips it.
TRIPPING = {ArmingWarning.FAILED_HERE: OffReason.FAILED_HERE,
            ArmingWarning.LOCAL_CHECK_FAILED: OffReason.LOCAL_CHECK_FAILED,
            ArmingWarning.INCOMPATIBLE: OffReason.INCOMPATIBLE,
            ArmingWarning.MEASUREMENT_FAILED: OffReason.MEASUREMENT_FAILED}


def engine_version(view):
    engine = view.get("engine") if isinstance(view, dict) else None
    version = engine.get("version") if isinstance(engine, dict) else None
    return version if isinstance(version, str) else None


def compat_warning(view, definition):
    """The warning the Compatibility Registry's view gives for what `definition` stands on, or
    None for a grade of COMPATIBLE or better. A view that cannot be read is UNKNOWN. An action
    stands on nothing of Codex's, so it has none: a failing Codex is no reason to withhold it."""
    if definition.compat is None:
        return None
    capabilities = view.get("capabilities") if isinstance(view, dict) else None
    entry = capabilities.get(definition.compat) if isinstance(capabilities, dict) else None
    state = entry.get("state") if isinstance(entry, dict) else UNKNOWN
    if state == FAILED_HERE:
        return ArmingWarning.FAILED_HERE
    if state == INCOMPATIBLE:
        return (ArmingWarning.LOCAL_CHECK_FAILED if entry.get("reason") == "local_check_failed"
                else ArmingWarning.INCOMPATIBLE)
    if state == UNKNOWN or state not in STATES:
        return ArmingWarning.COMPAT_UNKNOWN
    return None


def warnings_for(definition, view, measured=MEASURED) -> tuple:
    """Every warning `definition`'s statement shows now, in the vocabulary's order. Pure.

    A measurement its route rests on that failed is MEASUREMENT_FAILED, whichever Codex it failed
    on; one with no verdict, or a pass on another Codex than the one in force, is UNMEASURED - a
    pass counts only for the version it was made on. Then the compatibility grade of what it
    stands on (`compat_warning`), and ENGINE_UNKNOWN where no Codex version is known."""
    version = engine_version(view)
    found = set()
    for measurement in definition.measurements:
        entry = measured.get(measurement) if isinstance(measured, dict) else None
        verdict, measured_on = entry if isinstance(entry, tuple) and len(entry) == 2 else (None, None)
        if verdict == Verdict.FAIL:
            found.add(ArmingWarning.MEASUREMENT_FAILED)
        elif verdict != Verdict.PASS or version is None or measured_on != version:
            found.add(ArmingWarning.UNMEASURED)
    compat = compat_warning(view, definition)
    if compat is not None:
        found.add(compat)
    if version is None:
        found.add(ArmingWarning.ENGINE_UNKNOWN)
    return tuple(warning for warning in ArmingWarning if warning in found)


def standing(definition, row, policy, view, measured=MEASURED) -> tuple:
    """(state now, what must be done to the stored state or None, the unconfirmed warning that
    holds it back without changing anything stored, or None, what a kept-on capability notes in
    place of a turn off, or None).

    Pure. The order is the order of what overrides what: a changed statement, and a warning the
    person did not confirm that says what it stands on went wrong, turn it off whatever else
    holds; a policy reads it down; and "on" is on only for the Codex version the person
    acknowledged, with a new one turning it off, and one that cannot be read - or a grade nobody
    knows, where the person did not confirm that - holding it back.

    Kept on (K8), the policy comes first, so it reads one down whatever is noted; then a changed
    statement, an unconfirmed tripping warning and a new Codex version are each a notice - the first
    found - and it stays where it stands; what cannot be read still holds it back, noting nothing."""
    stored = row["state"] if row else ArmingState.OFF
    if stored == ArmingState.OFF:
        return ArmingState.OFF, None, None, None
    kept = bool(row.get("keep_on"))
    notice = None
    if not kept or policy.admits(definition.id):
        if row.get("statement_revision") != definition.revision:
            notice = OffReason.STATEMENT_CHANGED
    unconfirmed = set(warnings_for(definition, view, measured)) - set(row.get("warnings") or ())
    if notice is None:
        notice = next((reason for warning, reason in TRIPPING.items() if warning in unconfirmed), None)
    if notice is not None and not kept:
        return ArmingState.OFF, notice, None, None
    if not policy.admits(definition.id):
        return ArmingState.OFF, None, None, None
    if stored == ArmingState.ARMED and policy.force_shadow:
        return ArmingState.SHADOW, None, None, None
    if stored == ArmingState.ARMED:
        version, acknowledged = engine_version(view), row.get("engine_version")
        if version != acknowledged:
            if version is None:
                return ArmingState.OFF, None, ArmingWarning.ENGINE_UNKNOWN, None
            if not kept:
                return ArmingState.OFF, OffReason.ENGINE_CHANGED, None, None
            notice = notice or OffReason.ENGINE_CHANGED
        if ArmingWarning.COMPAT_UNKNOWN in unconfirmed:
            return ArmingState.OFF, None, ArmingWarning.COMPAT_UNKNOWN, None
    return stored, None, None, notice


def departs(definition, row) -> list:
    """The standards `definition` departs from as a surface lists them: its own, joined - for one kept
    on with Send again (v0.6.14) - by the once-more capability's, since Send again does what it does."""
    found = list(definition.departs_from)
    if (row or {}).get("send_again"):
        found += [standard for standard in ONCE_MORE.departs_from if standard not in found]
    return found


def kept_words(keep_on, send_again) -> list:
    """The words a person confirms to keep a capability on: ["keep_on"], with "send_again" after it."""
    return [str(word) for word in KeepOn
            if (word == KeepOn.KEEP_ON and keep_on) or (word == KeepOn.SEND_AGAIN and send_again)]


def _rises(held, notice) -> bool:
    """Whether `notice` is more serious than the notice a kept-on row holds (KEPT_NOTICES), so worth
    writing: only a rise is written, never the same one again on every tick."""
    return held not in KEPT_NOTICES or KEPT_NOTICES.index(notice) < KEPT_NOTICES.index(held)


def _confirmed(warnings):
    """The warnings a request says the person confirmed, as a set of the vocabulary's words, or
    None for a request that does not say it in those words. Saying nothing is confirming none."""
    if warnings is None:
        return frozenset()
    if not isinstance(warnings, (list, tuple)) or not all(isinstance(word, str) for word in warnings):
        return None
    try:
        return frozenset(ArmingWarning(word) for word in warnings)
    except ValueError:
        return None


def _claimed_at(record):
    """When the send of `record` that core holds now was claimed - its `last_claim_at` - or None
    where that cannot be read."""
    at = record.get("last_claim_at") if isinstance(record, dict) else None
    if isinstance(at, bool) or not isinstance(at, (int, float)) or not math.isfinite(at):
        return None
    return at


def _carried(spent, key, claimed_at) -> bool:
    """Whether the send of record `key` claimed at `claimed_at` is one a capability paid for, by
    `spent` - its units, {record: their times} (state.spends_since).

    A unit is spent inside the claim it pays for, at the claim's own time, so a later send of the
    same record that core made alone - once the capability's own was settled, a goal set active or
    a message that arrived - carried nothing of the capability's, and its going unknown is not
    the capability's doing. Where the claim's time cannot be read, any unit on the record is taken
    for that send: the side that turns the capability off."""
    times = spent.get(key)
    if not times:
        return False
    if claimed_at is None:
        return True
    return any(abs(at - claimed_at) <= SAME_CLAIM for at in times)


def _unknown_claim(core_view, key):
    """(whether core holds record `key` as submission_unknown now, when the send it holds so was
    claimed). A view that cannot answer says nothing either way."""
    try:
        record = core_view.get(key)
    except Exception:
        return False, None
    if not (isinstance(record, dict) and record.get("state") == SUBMISSION_UNKNOWN):
        return False, None
    return True, _claimed_at(record)


def _view_of(paths):
    """The Compatibility Registry's view, as the watcher last wrote it, bound to the engine the
    settings name - what every front end shows."""
    from codex_auto_resume import compatio, settings
    return compatio.reader_view(paths, settings=settings.load(paths.settings_file))


class Arming:
    def __init__(self, state, *, catalogs=CATALOGS, policy=None, view=None, measured=None,
                 clock=time.time):
        self.state = state
        self.registry = state.registry
        self.catalogs = catalogs
        self._policy = policy or _policy.read
        self._view = view or (lambda: _view_of(state.paths))
        self._measured = measured or (lambda: MEASURED)
        self.clock = clock
        # {record: (when core told of its move into submission_unknown, when the send that went
        # unknown was claimed)} for each such move whose trips are not all written yet: core tells
        # a move once, so one whose trip could not be written then - the state locked past its
        # timeout, or not to be opened - is tried again at every sweep until it is, though the
        # record has settled by then (`_settle`).
        self._owed = {}

    def policy(self):
        try:
            found = self._policy()
        except Exception:
            return _policy.STRICTEST
        return found if isinstance(found, _policy.Policy) else _policy.STRICTEST

    def view(self) -> dict:
        """The Compatibility Registry's view; one that cannot be read is UNKNOWN for everything,
        and no Codex version - both warnings, never permission for anything unconfirmed."""
        try:
            found = self._view()
        except Exception:
            return {}
        return found if isinstance(found, dict) else {}

    def measured(self) -> dict:
        """What the measurements found, as this build ships them (measured.py). A table that
        cannot be read is no measurement at all: every route unmeasured, which is a warning."""
        try:
            found = self._measured()
        except Exception:
            return {}
        return found if isinstance(found, dict) else {}

    def warnings(self, definition, view=None) -> tuple:
        """The warnings `definition`'s statement shows now."""
        return warnings_for(definition, self.view() if view is None else view, self.measured())

    # ------------------------------------------------------------------ now
    def current(self, *, view=None, policy=None) -> dict:
        """{id: state now} for every capability of the registry, carrying out every trip and
        reset `standing` finds. With no capability, nothing is read; and with nothing stored on,
        nothing else is read either - no policy, no compatibility view, no measurement - so an
        installation that never turned a capability on is the standard edition, down to what it
        reads. A capability that is off is off whatever any of those say."""
        return self.read(view=view, policy=policy)[0]

    def read(self, *, view=None, policy=None) -> tuple:
        """`current`, with what the runtime needs beside it (v0.6.14): ({id: state now}, {id: since
        when its stored state has stood, for one that is not off}, whether the state could not be
        read). A state that cannot be read has every capability off; the third says it was not read
        as off, which is not the same thing for a record a capability took up (runtime.py)."""
        if not len(self.registry):
            return {}, {}, False
        try:
            rows, failed = self.state.arming(), False
        except StateError:
            rows, failed = {}, True
        since = {capability: row.get("since") for capability, row in rows.items()
                 if (row or {}).get("state", ArmingState.OFF) != ArmingState.OFF}
        if not since:
            return {definition.id: ArmingState.OFF for definition in self.registry}, {}, failed
        view = self.view() if view is None else view
        policy = self.policy() if policy is None else policy
        measured = self.measured()
        states = {}
        for definition in self.registry:
            state, change, _held, notice = standing(definition, rows.get(definition.id), policy, view,
                                                    measured)
            if change is not None:
                self._off(definition.id, change)
            elif notice is not None and _rises((rows.get(definition.id) or {}).get("reason"), notice):
                self._keep(definition.id, notice)
            states[definition.id] = state
        return states, since, failed

    def _off(self, capability, reason) -> bool:
        try:
            return self._write_off(capability, reason)
        except StateError:
            return False                   # it reads as off either way

    def _write_off(self, capability, reason) -> bool:
        """`capability` off, with why; StateError where that cannot be written."""
        actor = Actor.TRIPWIRE if reason in TRIPWIRES else Actor.ENGINE_CHANGE
        return self.state.move(capability, ArmingState.OFF, actor=actor, reason=reason,
                               at=self.clock())[0]

    def trip(self, capability, reason) -> bool:
        """A tripwire: `capability` off, with why - or, kept on, noted (K8). Only a tripwire's
        reason is one. Whether it was turned off."""
        if OffReason(reason) not in TRIPWIRES:
            raise ValueError("not a tripwire")
        try:
            return self._trip_or_keep(capability, reason)
        except StateError:
            return False                   # it reads as off either way, or stays kept on

    def _keep(self, capability, reason) -> bool:
        try:
            return self.state.note_kept(capability, reason, at=self.clock())
        except StateError:
            return False

    def _trip_or_keep(self, capability, reason, row=None) -> bool:
        """A tripwire's `reason` carried out: off, or, for one kept on, its notice (state.note_kept) -
        written only where it rises above the one the row holds. Whether it was turned off;
        StateError where nothing could be written or read."""
        row = self.state.arming().get(capability) if row is None else row
        if (row or {}).get("keep_on"):
            if _rises(row.get("reason"), reason):
                self.state.note_kept(capability, reason, at=self.clock())
            return False
        return self._write_off(capability, reason)

    def kept(self, capability) -> bool:
        """Whether `capability` is kept on now (K8); not, where the state cannot be read."""
        try:
            return bool((self.state.arming().get(capability) or {}).get("keep_on"))
        except StateError:
            return False

    def _paid(self):
        """{capability: (since when it is on, {record: when it paid a send of it} since then, its
        row)} for each capability that is on, or None where the state cannot be read."""
        try:
            rows = self.state.arming()
            return {capability: (row["since"], self.state.spends_since(capability, row["since"]), row)
                    for capability, row in rows.items()
                    if row["state"] == ArmingState.ARMED and row["since"] is not None}
        except StateError:
            return None

    def _settle(self, core_view=None) -> bool:
        """Turn off every capability that is on and paid for the very send core told this plug
        went into submission_unknown while it was on - and, with `core_view`, for one core holds
        so now (`_carried`). Whether any was turned off.

        What was told stays owed until a pass has read the state and written every trip it
        called for: a trip whose write failed is not lost with the one telling of it, and a
        capability turned on again since is not turned off by a move from before."""
        paid = self._paid()
        if paid is None:
            return False
        tripped = failed = False
        for capability, (since, spent, row) in paid.items():
            owed = any(told >= since and _carried(spent, key, claimed)
                       for key, (told, claimed) in self._owed.items())
            held = core_view is not None and any(
                unknown and _carried(spent, key, claimed)
                for key in spent for unknown, claimed in (_unknown_claim(core_view, key),))
            if not (owed or held):
                continue
            try:
                tripped = self._trip_or_keep(capability, OffReason.SUBMISSION_UNKNOWN, row) or tripped
            except StateError:
                failed = True
        if not failed:
            self._owed.clear()
        return tripped

    def sweep(self, core_view) -> None:
        """Once a tick: every trip and reset `standing` finds, and a send a capability paid for,
        since it was last turned on, that core holds as submission_unknown now - one that was
        so before this plug was told of any move, say, the watcher having started again since.
        A send of the same record core made later, alone, is not one it paid for (`_carried`).

        A send that became unknown while this plug was loaded has tripped its capability
        already, as core wrote the move (`moved`): by P8 the watch that runs before it may have
        settled a late delivery, and the record's state now would say nothing. Where that trip
        could not be written, it is written here.

        And (v0.6.14) every continuation this edition sent once more that core found twice since
        (`_duplicates`), and every person's request a capability that does not stand on can no longer
        use (`_void_requests`)."""
        states = self.current()
        if not len(self.registry):
            return
        self._settle(core_view)
        self._duplicates(core_view)
        self._void_requests(states)

    def _void_requests(self, states) -> None:
        """Every unused FORCE_ONCE - a person's Send now - of a capability that does not stand on now,
        closed: watched, off, or read down by a policy, a request is never held for later."""
        try:
            opened = self.state.open_overrides(OverrideKind.FORCE_ONCE)
        except StateError:
            return
        for override in opened:
            if states.get(override["capability"], ArmingState.OFF) != ArmingState.ARMED:
                self._close(override["interruption_id"], override["capability"])

    def _duplicates(self, core_view) -> None:
        """Each resend still watched (an open RESEND_ONCE) whose record core says was found twice:
        what sent it again is turned off - the once-more capability itself, kept on or not, or the
        payer's Send again alone, the payer staying on with it noted (DUPLICATE_SEEN) - where it has
        stood where it stands since the resend. The watch on it closes then, when core no longer holds
        the record, and a day after the resend; a write that failed is tried again at the next sweep."""
        try:
            watched = self.state.open_overrides(OverrideKind.RESEND_ONCE)
        except StateError:
            return
        if not watched:
            return
        try:
            rows = self.state.arming()
        except StateError:
            return
        now = self.clock()
        for override in watched:
            key, capability = override["interruption_id"], override["capability"]
            try:
                record = core_view.get(key)
            except Exception:
                continue                             # a view that cannot answer says nothing
            if not (isinstance(record, dict) and record.get("last_error") == DUPLICATE):
                if not isinstance(record, dict) or now - override["created_at"] > RESEND_WATCH:
                    self._close(key, capability)
                continue
            row, definition = rows.get(capability), self.registry.get(capability)
            try:
                if (row is not None and row["state"] != ArmingState.OFF and row["since"] is not None
                        and override["created_at"] >= row["since"]):
                    if definition.resends:
                        self._write_off(capability, OffReason.DUPLICATE_SEEN)
                    elif row.get("send_again"):
                        self.state.send_again_off(capability, reason=OffReason.DUPLICATE_SEEN, at=now)
            except StateError:
                continue
            self._close(key, capability)

    def _close(self, key, capability) -> None:
        try:
            self.state.use_override(key, capability, at=self.clock())
        except StateError:
            pass

    def resender(self, record, states):
        """(the capability, where it stands) whose Keep on's Send again sends `record` once more
        (v0.6.14), or None: the first, in the registry's order, that stands on or watched in `states`,
        is kept on with Send again, paid for this very send since it last stood where it stands, and is
        not the once-more capability - only where the policy admits the once-more capability too, where
        this edition never resent the record and where no other capability that is a channel or a route
        paid for that send, the once-more capability's own restriction (engine/oncemore.py). A state
        that cannot be read sends nothing again."""
        key = record.get("interruption_id") if isinstance(record, dict) else None
        if not isinstance(key, str) or record.get("state") != SUBMISSION_UNKNOWN:
            return None
        if not self.policy().admits(ONCE_MORE.id):
            return None
        try:
            rows = self.state.arming()
            if not any(row.get("send_again") for row in rows.values()) or self.state.resent(key):
                return None
            payers = self.state.payers(key, _claimed_at(record))
        except StateError:
            return None
        for definition in self.registry:
            row = rows.get(definition.id) or {}
            state = states.get(definition.id, ArmingState.OFF)
            if (definition.resends or state == ArmingState.OFF or not row.get("send_again")
                    or row.get("since") is None
                    or not any(at >= row["since"] for at in payers.get(definition.id, ()))):
                continue
            if any(self.registry.get(other).points & CHANNELS for other in payers if other != definition.id):
                return None
            return definition, state
        return None

    def moved(self, record, state) -> bool:
        """P14: core has just moved `record` to `state`. Into submission_unknown, every capability
        that paid for that send - the one claimed at the record's `last_claim_at` - since it was
        last turned on is turned off: the tripwire's word for "it may be in Codex, and nothing
        proves where". Whether any was.

        Told by core as it writes the move, so nothing that settles the record afterwards - in
        the same watch or the same tick - can hide it, and nothing is read back from core's
        journal, which no decision reads. Told once: what cannot be written now is owed, and
        every sweep tries it again (`_settle`)."""
        key = record.get("interruption_id") if isinstance(record, dict) else None
        if state != SUBMISSION_UNKNOWN or not isinstance(key, str) or not len(self.registry):
            return False
        self._owed[key] = (self.clock(), _claimed_at(record))
        return self._settle()

    # ------------------------------------------------------------------ on
    def arm(self, capability, *, state, revision, generation, acknowledged_version=None,
            warnings=None, actor) -> dict:
        """Move `capability` to watched (SHADOW) or on (ARMED), for a person in the Dashboard.

        `warnings` are the words of the statement's warnings the person confirmed (none, when
        not given), and `acknowledged_version` the Codex version the Dashboard showed them, for
        "on". Neither may be what refuses it: when they are not what holds now, the request is
        refused as a stale confirmation, and the warnings that hold now go back with it for the
        Dashboard to show.

        {"done": bool, "refusal": Refusal or None, "warnings": the warnings that hold now, once
        read, "generation": the generation after}."""
        shown = ()

        def refused(why):
            return {"done": False, "refusal": why, "warnings": [str(word) for word in shown],
                    "generation": self._generation()}

        if actor != Actor.DASHBOARD:
            return refused(Refusal.NOT_THE_DASHBOARD)
        definition = self.registry.get(capability)
        if definition is None:
            return refused(Refusal.UNKNOWN_CAPABILITY)
        confirmed = _confirmed(warnings)
        if (state not in (ArmingState.SHADOW, ArmingState.ARMED) or type(revision) is not int
                or type(generation) is not int or confirmed is None
                or not (acknowledged_version is None or isinstance(acknowledged_version, str))):
            return refused(Refusal.INVALID_REQUEST)
        # The administrator's word, and the only thing that refuses a capability itself.
        policy = self.policy()
        if policy.forbid:
            return refused(Refusal.FORBIDDEN_BY_POLICY)
        if not policy.admits(definition.id):
            return refused(Refusal.NOT_ALLOWED_BY_POLICY)
        if state == ArmingState.ARMED and policy.force_shadow:
            return refused(Refusal.SHADOW_FORCED_BY_POLICY)
        # What the person read and confirmed has to be what holds now.
        if revision != definition.revision:
            return refused(Refusal.STALE_REVISION)
        if not self.catalogs.complete_in(definition, "en"):
            return refused(Refusal.STATEMENT_INCOMPLETE)
        view = self.view()
        shown = self.warnings(definition, view)
        if confirmed != frozenset(shown) or (state == ArmingState.ARMED
                                             and acknowledged_version != engine_version(view)):
            return refused(Refusal.STALE_CONFIRMATION)
        try:
            _moved, after = self.state.move(
                capability, state, actor=actor, revision=revision,
                engine_version=acknowledged_version if state == ArmingState.ARMED else None,
                warnings=shown, generation=generation, at=self.clock())
        except StaleGeneration:
            return refused(Refusal.STALE_GENERATION)
        except StateError:
            return refused(Refusal.STATE_UNAVAILABLE)
        return {"done": True, "refusal": None, "warnings": [str(word) for word in shown],
                "generation": after}

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

    # ------------------------------------------------------------------ kept on
    def set_keep_on(self, capability, keep_on, *, send_again=False, generation, confirmed=None,
                    actor) -> dict:
        """Keep `capability` on (K8) - with Send again (v0.6.14) or without - or let it turn itself off
        again, for a person in the Dashboard.

        Turning anything on: the policy's refusals first, as an arm meets them - for Send again, the
        once-more capability's too, since Send again does what it does; then it must be on or watched
        (NOT_ON); then `confirmed` must be the words of the warnings the Dashboard showed, ["keep_on"] or
        ["keep_on", "send_again"] (STALE_CONFIRMATION); then the generation. Send again is only with Keep
        on, and never for a capability that resends itself, nor for an action, which sends no continuation
        to send again (INVALID_REQUEST). Letting either go needs only the capability. {"done", "refusal",
        "generation"}."""
        def refused(why):
            return {"done": False, "refusal": why, "generation": self._generation()}

        if actor != Actor.DASHBOARD:
            return refused(Refusal.NOT_THE_DASHBOARD)
        definition = self.registry.get(capability)
        if definition is None:
            return refused(Refusal.UNKNOWN_CAPABILITY)
        if (type(keep_on) is not bool or type(send_again) is not bool
                or not (generation is None or type(generation) is int)
                or (send_again and (not keep_on or definition.resends
                                    or definition.kind == CapabilityKind.ACTION))):
            return refused(Refusal.INVALID_REQUEST)
        try:
            row = self.state.arming().get(definition.id) or {}
        except StateError:
            return refused(Refusal.STATE_UNAVAILABLE)
        wanted = kept_words(keep_on, send_again)
        if not set(wanted) <= set(kept_words(row.get("keep_on"), row.get("send_again"))):
            policy = self.policy()
            if policy.forbid:
                return refused(Refusal.FORBIDDEN_BY_POLICY)
            if not policy.admits(definition.id) or (send_again and not policy.admits(ONCE_MORE.id)):
                return refused(Refusal.NOT_ALLOWED_BY_POLICY)
            if policy.force_shadow and row.get("state") == ArmingState.ARMED:
                return refused(Refusal.SHADOW_FORCED_BY_POLICY)
            if self.current(policy=policy).get(definition.id, ArmingState.OFF) == ArmingState.OFF:
                return refused(Refusal.NOT_ON)
            if confirmed != wanted:
                return refused(Refusal.STALE_CONFIRMATION)
            if generation is None:
                return refused(Refusal.INVALID_REQUEST)
        else:
            generation = None                    # letting go never waits on a generation
        try:
            after = self.state.set_keep_on(capability, keep_on, send_again=send_again, actor=actor,
                                           generation=generation, at=self.clock())
        except Refused as refusal:
            return refused(refusal.refusal)
        except StaleGeneration:
            return refused(Refusal.STALE_GENERATION)
        except StateError:
            return refused(Refusal.STATE_UNAVAILABLE)
        return {"done": True, "refusal": None, "generation": after}

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

    # ------------------------------------------------------------------ choices and rules
    def _chosen(self, write):
        """A person's choice or rule written as `write` does it: {"done", "refusal", and what it
        gave}. Allowed in any state a capability is in - it changes no state - and refused by no
        policy: a choice only narrows what a capability that is on may do, and arming it is what
        the policy refuses."""
        try:
            return dict(write(), done=True, refusal=None)
        except Refused as refused:
            return {"done": False, "refusal": refused.refusal, "generation": self._generation()}
        except StaleGeneration:
            return {"done": False, "refusal": Refusal.STALE_GENERATION, "generation": self._generation()}
        except StateError:
            return {"done": False, "refusal": Refusal.STATE_UNAVAILABLE, "generation": self._generation()}

    def set_option(self, capability, key, value, *, generation, actor) -> dict:
        """One of a capability's own choices (registry.Option), in the Dashboard, against the
        generation it read - which the write moves on, so a page showing the old choice cannot arm
        against the new one."""
        if actor != Actor.DASHBOARD:
            return {"done": False, "refusal": Refusal.NOT_THE_DASHBOARD}
        if self.registry.get(capability) is None:
            return {"done": False, "refusal": Refusal.UNKNOWN_CAPABILITY}
        return self._chosen(lambda: {"generation": self.state.set_option(
            capability, key, value, generation=generation, actor=actor, at=self.clock())})

    def add_rule(self, tag, status_from, status_to, category, *, generation, actor) -> dict:
        """A rule for one of Codex's error codes, in the Dashboard (state/choices.rule_problem)."""
        if actor != Actor.DASHBOARD:
            return {"done": False, "refusal": Refusal.NOT_THE_DASHBOARD}

        def write():
            rule, after = self.state.add_rule(tag, status_from, status_to, category,
                                              generation=generation, actor=actor, at=self.clock())
            return {"rule": rule, "generation": after}
        return self._chosen(write)

    def remove_rule(self, rule, *, generation, actor) -> dict:
        """A rule removed, in the Dashboard. What it took up and has not sent ends unsent: its
        capability no longer takes it up again (engine/admitted.py)."""
        if actor != Actor.DASHBOARD:
            return {"done": False, "refusal": Refusal.NOT_THE_DASHBOARD}
        return self._chosen(lambda: {"generation": self.state.remove_rule(
            rule, generation=generation, actor=actor, at=self.clock())})

    def _options(self, definition) -> list:
        """A capability's choices as a surface shows them: the defaults where the state cannot be read."""
        if not definition.options:
            return []
        try:
            values = self.state.options(definition.id)
        except StateError:
            values = {}
        return [{"key": str(option.key), "choices": list(option.choices),
                 "value": values.get(option.key, option.default), "default": option.default}
                for option in definition.options]

    def rules_view(self) -> dict:
        """The rules as the Dashboard's editor shows them, oldest first: each one's id, code, status
        numbers and kind, whether the product has come to know its code since (it never matches then),
        and how many failures it took up in the last 30 days; the generation a change is made against;
        how many rules there may be; and the codes the samples of the last 30 days saw that a rule may
        name. Codes and numbers only."""
        since = self.clock() - RECENT_DAYS * DAY
        try:
            rules, hits = self.state.rules(), self.state.rule_hits(since)
            samples, meta = self.state.failure_samples(since), self.state.meta()
        except StateError:
            return {"done": False, "refusal": Refusal.STATE_UNAVAILABLE}
        return {"done": True, "generation": meta["generation"], "limit": RULES_LIMIT,
                "rules": [{"rule": rule["rule_id"], "tag": rule["tag"], "status_from": rule["status_from"],
                           "status_to": rule["status_to"], "category": rule["category"],
                           "known": rule["known"], "hits": hits.get(rule["rule_id"], 0)} for rule in rules],
                "tags": sorted({sample["tag"] for sample in samples
                                if sample["tag"] is not None and tag_problem(sample["tag"]) is None})}

    def samples_view(self) -> dict:
        """The samples of the last 30 days, as the Dashboard and a diagnostics export show them: each
        code, status number and form, how many times and the last day (choices.aggregated)."""
        try:
            samples = self.state.failure_samples(self.clock() - RECENT_DAYS * DAY)
        except StateError:
            return {"done": False, "refusal": Refusal.STATE_UNAVAILABLE}
        return {"done": True, "samples": aggregated(samples)}

    # ------------------------------------------------------------------ shown
    def statement(self, definition, locale=None) -> dict:
        """What the Dashboard shows before the choice: the five fields, and above them the
        warnings that hold now, with the Codex version an "on" acknowledges. The Dashboard
        sends back the warnings' words and that version as the person's confirmation (`arm`)."""
        view = self.view()
        return dict(self.catalogs.statement(definition, locale, warnings=self.warnings(definition, view)),
                    engine_version=engine_version(view))

    def listing(self) -> dict:
        """Every capability as a surface shows it: where it is stored, what it is now, since
        when and by whom, what a person would be agreeing to, what its statement warns of now
        and what they confirmed when they last turned it on or watched it."""
        from .runtime import SENDING              # lazily: runtime imports this module
        SENDING_POINTS = frozenset(SENDING)
        view, policy = self.view(), self.policy()
        states = self.current(view=view, policy=policy)
        try:
            rows, meta = self.state.arming(), self.state.meta()
        except StateError:
            rows, meta = {}, {"generation": 0, "global_hourly": GLOBAL_HOURLY}
        shown = []
        for definition in self.registry:
            row = rows.get(definition.id) or {}
            off = row.get("state", ArmingState.OFF) == ArmingState.OFF
            shown.append({
                "id": definition.id, "stored": str(row.get("state", ArmingState.OFF)),
                "state": str(states.get(definition.id, ArmingState.OFF)),
                "since": row.get("since"), "by": row.get("actor"), "reason": row.get("reason") if off else None,
                # Keep on (K8), its Send again (v0.6.14), and what a kept-on capability noted in place of
                # turning itself off; and whether it sends an uncertain continuation once more itself, and
                # so is never given Send again.
                "keep_on": bool(row.get("keep_on")), "send_again": bool(row.get("send_again")),
                "notice": None if off else row.get("reason"), "resends": definition.resends,
                "revision": definition.revision, "read_revision": row.get("statement_revision"),
                "acknowledged_version": row.get("engine_version"),
                "warnings": [str(word) for word in self.warnings(definition, view)],
                "confirmed_warnings": [str(word) for word in row.get("warnings") or ()],
                "kind": str(definition.kind),
                "departs_from": departs(definition, row), "compat": definition.compat,
                "measurements": [str(measurement) for measurement in definition.measurements],
                "points": sorted(str(point) for point in definition.points),
                # Whether any point it answers at leads to a send, and so whether its ceilings can
                # ever bind. A capability that only starts, or only shadows, spends no unit; a
                # surface shows its ceilings as nominal rather than as a limit that will be met.
                "sends": bool(definition.points & SENDING_POINTS),
                # An action has none: it sends nothing to Codex, so there is no limit to show.
                "ceilings": None if definition.ceilings is None else
                {"per_day": definition.ceilings.per_day,
                 "per_conversation": definition.ceilings.per_conversation},
                # Its own choices, each with what it offers, what it is now and its default; and whether
                # the page shows it the rules editor and the samples, which are read on their own
                # (rules_view, samples_view) - never in this list, which MCP reads too.
                "options": self._options(definition),
                "rules_editor": definition.rules_editor, "samples": definition.samples})
        return {"generation": meta["generation"], "global_hourly": meta["global_hourly"],
                "global_hourly_default": GLOBAL_HOURLY, "engine_version": engine_version(view),
                "policy": policy.as_json(), "on": sum(item["state"] == ArmingState.ARMED for item in shown),
                "capabilities": shown}
