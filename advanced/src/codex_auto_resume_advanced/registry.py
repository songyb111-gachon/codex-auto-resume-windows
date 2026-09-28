# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""The capability registry: every capability this edition can offer, and what each one is.

A capability is a definition here plus its code. The definition says everything a person is
asked to agree to and everything the plug holds it to:

* `id` - its closed name, the one every table, surface and journal line uses;
* `points` - the plug points its code answers at (domain/plug.py), and no others;
* `revision` - the revision of its statement: the five fields in `statement.py`'s catalogs, in
  every language the product has a catalog for. Arming names the revision the person read, and a new revision turns the
  capability off until they have read that one (a tripwire, arming.py);
* `departs_from` - the standards it breaks (standards.py). Never empty: a capability that keeps
  every standard belongs in the standard edition, so the rule for which edition a capability is
  in is this field;
* `compat` - the Compatibility Registry capability it stands on. Its grade here is shown in the
  statement - FAILED_HERE, INCOMPATIBLE or UNKNOWN as a warning the person confirms - and a
  failure the person did not confirm turns it off (arming.py);
* `measurements` - the measurements its route rests on (measure.py), if any. One that failed, or
  has no pass for the Codex in force (measured.py), is a warning in its statement, never a
  reason to withhold it;
* `ceilings` - how many sends it may make in a day, overall and in one conversation. Beside them
  stands one global ceiling for every capability together, GLOBAL_HOURLY an hour, which a person
  may lower and never raise (state.AdvancedState.set_global_hourly);
* `journal_prefix` and `codes` - the words its own journal lines are written in, `<prefix>.<code>`,
  closed like every other word the edition stores;
* `make` - the factory for its code: given the installation's paths, it returns an object whose
  methods are the plug's hooks for its points, each answering as a plug would.

The edition ships three capabilities now: start-with-Codex, at P9 (control/codexstart.py); the
goal continuation, at P16, P3 and P5 (engine/goal.py); and the marker-free continuation, at P5 and
P15 (engine/markerfree.py). The tests define one of their own to hold every rule here.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Callable

from codex_auto_resume.domain.plug import Point

from .control.codexstart import make as make_start_with_codex
from .engine.goal import make as make_goal_continuation
from .engine.markerfree import make as make_marker_free
from .standards import STANDARDS
from .vocabulary import Measurement

# The one ceiling over every capability together: advanced sends an hour. It is also the highest
# value a person may set it to - it can be lowered and never raised.
GLOBAL_HOURLY = 12
# Core's own caps on one conversation (engine/options.py): claims in 24 hours, and the spacing
# between them. The claim ledger counts advanced records against the same numbers (ledger.py), so
# no capability's own ceiling for one conversation can usefully be above the first.
CORE_DAILY_CAP = 5
CORE_COOLDOWN_SECONDS = 900

# Points a capability's code may answer at. The claim ledger (P11) and the surfaces (P10) are the
# plug's own: a capability is counted there, and shown there, but never handed core's connection
# or a surface to write into. So are the moves core tells of (P14), which the tripwires read
# (arming.py): what turns a capability off is never the capability's to hear first.
CAPABILITY_POINTS = frozenset(Point) - {Point.CLAIM_LEDGER, Point.SURFACES, Point.MOVED}

ID_SHAPE = re.compile(r"[a-z][a-z0-9_]{2,47}")
PREFIX_SHAPE = re.compile(r"[a-z]{2,8}")
CODE_SHAPE = re.compile(r"[a-z][a-z0-9_]{0,31}")


class RegistryError(ValueError):
    """A definition that breaks a rule of the registry. Raised when the registry is made, which
    is when the package is imported: a capability that cannot be described is never offered."""


@dataclass(frozen=True)
class Ceilings:
    per_day: int               # this capability's sends in 24 hours, every conversation together
    per_conversation: int      # its sends in 24 hours in any one conversation


@dataclass(frozen=True)
class CapabilityDef:
    id: str
    points: frozenset
    revision: int
    departs_from: tuple
    compat: str
    ceilings: Ceilings
    journal_prefix: str
    make: Callable
    codes: tuple = ()
    measurements: tuple = ()

    def code(self, word) -> str | None:
        """`word` as this capability's journal writes it, or None if it is not one of its own."""
        return "%s.%s" % (self.journal_prefix, word) if word in self.codes else None


def _count(value) -> bool:
    return type(value) is int and value >= 1


def problems(definition) -> list:
    """Every rule `definition` breaks, each named in a few words. Empty when it keeps them all."""
    if not isinstance(definition, CapabilityDef):
        return ["not a definition"]
    found = []
    if not isinstance(definition.id, str) or not ID_SHAPE.fullmatch(definition.id):
        found.append("id")
    points = definition.points
    if (not isinstance(points, frozenset) or not points
            or not all(isinstance(point, Point) for point in points)):
        found.append("points")
    elif not points <= CAPABILITY_POINTS:
        found.append("points the plug keeps for itself")
    if not _count(definition.revision):
        found.append("revision")
    departs = definition.departs_from
    if not isinstance(departs, tuple) or not departs:
        found.append("departs_from is empty: it keeps every standard, so it is standard")
    elif (not all(isinstance(standard, str) for standard in departs)
          or len(set(departs)) != len(departs) or not set(departs) <= set(STANDARDS)):
        found.append("departs_from names a standard the standards file does not hold")
    if not isinstance(definition.compat, str) or not ID_SHAPE.fullmatch(definition.compat):
        found.append("compat")
    ceilings = definition.ceilings
    if (not isinstance(ceilings, Ceilings) or not _count(ceilings.per_day)
            or not _count(ceilings.per_conversation)
            or ceilings.per_conversation > min(ceilings.per_day, CORE_DAILY_CAP)
            or ceilings.per_day > GLOBAL_HOURLY * 24):
        found.append("ceilings")
    if not isinstance(definition.journal_prefix, str) or not PREFIX_SHAPE.fullmatch(definition.journal_prefix):
        found.append("journal_prefix")
    codes = definition.codes
    if (not isinstance(codes, tuple)
            or not all(isinstance(code, str) and CODE_SHAPE.fullmatch(code) for code in codes)
            or len(set(codes)) != len(codes)):
        found.append("codes")
    if not callable(definition.make):
        found.append("make")
    measurements = definition.measurements
    if (not isinstance(measurements, tuple)
            or not all(isinstance(measurement, Measurement) for measurement in measurements)
            or len(set(measurements)) != len(measurements)):
        found.append("measurements")
    return found


class Registry:
    """A closed set of capabilities: the ids it was made with, and no others, ever.

    Anything a table or a surface holds under an id the registry does not know - a capability a
    newer version offered, a hand-edited row - is not one of these, and is never evaluated."""

    def __init__(self, definitions=()):
        definitions = tuple(definitions)
        for definition in definitions:
            found = problems(definition)
            if found:
                raise RegistryError("%s: %s" % (getattr(definition, "id", definition), "; ".join(found)))
        for attribute in ("id", "journal_prefix"):
            values = [getattr(definition, attribute) for definition in definitions]
            if len(set(values)) != len(values):
                raise RegistryError("two capabilities share one %s" % attribute)
        self.definitions = definitions
        self._by_id = {definition.id: definition for definition in definitions}

    @property
    def ids(self) -> tuple:
        return tuple(self._by_id)

    def get(self, capability) -> CapabilityDef | None:
        return self._by_id.get(capability) if isinstance(capability, str) else None

    def at(self, point) -> tuple:
        """The capabilities whose code answers at `point`, in the registry's order."""
        return tuple(definition for definition in self.definitions if point in definition.points)

    def __iter__(self):
        return iter(self.definitions)

    def __len__(self):
        return len(self.definitions)


# The capabilities this edition ships.
#
# start-with-Codex (decision C9): the one route out of Codex's kill-on-close job, at P9. It sends
# nothing and claims nothing - it starts the watcher - so it answers at START_ROUTE alone, no
# point it answers at is a sending point, and its ceilings never bind: a surface that shows them
# says so (arming.listing marks a non-sending capability). Its journal is the runtime's own -
# WOULD_HAVE where it is watched, ACTED where core takes its route - so it declares no codes of
# its own: nothing here would ever write one. It departs from C4 (nothing at start) and F6 (a
# process-creation route beyond the listed ones), rests on engine_present (the installed Codex is
# the one we start a watcher for, with local checks), and on measurement MW (the WMI escape still
# leaves a process outside the job); a version of Codex MW has not passed for is a warning in its
# statement, never a reason to withhold it. The ceilings are the schema's floor - the smallest a
# definition may name - because for a capability that never spends they are nominal.
START_WITH_CODEX = CapabilityDef(
    id="start_with_codex",
    points=frozenset({Point.START_ROUTE}),
    revision=1,
    departs_from=("C4", "F6"),
    compat="engine_present",
    ceilings=Ceilings(per_day=1, per_conversation=1),
    journal_prefix="swc",
    make=make_start_with_codex,
    measurements=(Measurement.MW,),
)

# The marker-free continuation (v0.6.11 stage 3a, the owner's request of 2026-09-26): each
# continuation goes with no marker, queued through the app server's thread/queue/add under the
# client id core derives from the interruption, and core proves delivery by that id alone
# (domain/plug.py, P15). It is the channel at P5 and answers CLIENT_ID at P15, so it pays one unit
# at the claim of each send it carries, and past its ceilings core sends with the marker as the
# standard edition does. It departs from A2 (one channel only: `codex queue`), A4 (the marker
# proves delivery), B3 (Codex's state changes only through `codex queue`, thread/queue/delete and
# the plugin command) and B4 (the app server is asked only initialize, account/rateLimits/read and
# thread/queue/delete) - the last two because its session calls thread/queue/add, as the goal
# continuation's does (codex/protocol.CAPABILITY_METHODS); revision 2 names them, where revision 1
# named A2 and A4 alone. It stands on recovery_turn_tracking - the history and queue tables the
# proof is read from, with local checks - and on measurement M7, where thread/queue/add with a
# clientUserMessageId was accepted and delivered as plain text. A send it cannot prove is held as
# core holds any uncertain one, and the tripwire for a paid send gone submission_unknown turns it
# off. Its ceilings: core's own five a conversation a day, and two dozen a day in all.
MARKER_FREE = CapabilityDef(
    id="marker_free_continuation",
    points=frozenset({Point.SENDER, Point.DELIVERY}),
    revision=2,
    departs_from=("A2", "A4", "B3", "B4"),
    compat="recovery_turn_tracking",
    ceilings=Ceilings(per_day=24, per_conversation=CORE_DAILY_CAP),
    journal_prefix="mfc",
    make=make_marker_free,
    measurements=(Measurement.M7,),
)

# The goal continuation (v0.6.11 stage 3b, the owner's request of 2026-09-26): for a usage limit in
# a conversation the app does not hold, it is the route core carries out at P16 - the conversation's
# goal, paused by the limit, set active again through the app server's thread/goal/set, an existing
# goal only and never its words - so Codex carries the goal on when the app next opens it (M2: a goal
# set so is not seen while the app holds the conversation, and is live once it loads it again). At
# P3 it holds the standard continuation back while that goal is active, so the two never both run;
# at P5, only where M2b passed for the Codex in force, it is the channel that sets the goal active
# before the continuation it queues. Anywhere else the standard queue route stands.
#
# It departs from 0.5 (goal-state manipulation is rejected from the product), A2 (one channel only),
# A11 (nothing is done for a conversation the app does not hold), B3 (Codex's state changes only
# through the queue and the plugin command) and B4 (the app server's three methods). It stands on
# loaded_state_detection - whether the app holds the conversation, with local checks, which is what
# decides its route - and reads the goals table's columns itself at every use, doing what the
# standard edition does where they are not there. Core's own goal_continuation entry in the
# Compatibility Registry has no local check and stays 'unsupported' (G12), as the standard
# edition's. Its route rests on M2, which failed for a conversation the app holds - a warning in its
# statement the person confirms; M2b only widens where it acts, and is read where it is used.
# Ceilings: three a conversation a day - a usage limit resets a few times a day at most - and a dozen
# a day in all. It comes before the marker-free continuation, so where both are on and the goal
# applies its channel carries the send, under the client id P15 gives it.
GOAL_CONTINUATION = CapabilityDef(
    id="goal_continuation",
    points=frozenset({Point.UNLOADED, Point.GATES, Point.SENDER}),
    revision=1,
    departs_from=("0.5", "A2", "A11", "B3", "B4"),
    compat="loaded_state_detection",
    ceilings=Ceilings(per_day=12, per_conversation=3),
    journal_prefix="goal",
    make=make_goal_continuation,
    measurements=(Measurement.M2,),
)

DEFINITIONS = (START_WITH_CODEX, GOAL_CONTINUATION, MARKER_FREE)
REGISTRY = Registry(DEFINITIONS)
