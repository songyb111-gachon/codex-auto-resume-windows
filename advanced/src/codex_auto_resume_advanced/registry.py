# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""The capability registry: every capability this edition can offer, and what each one is.

A capability is a definition here plus its code. The definition says everything a person is
asked to agree to and everything the plug holds it to:

* `id` - its closed name, the one every table, surface and journal line uses;
* `points` - the plug points its code answers at (domain/plug.py), and no others;
* `revision` - the revision of its statement: the five fields in `statement.py`'s catalogs, in
  all nine languages. Arming names the revision the person read, and a new revision turns the
  capability off until they have read that one (a tripwire, arming.py);
* `departs_from` - the standards it breaks (standards.py). Never empty: a capability that keeps
  every standard belongs in the standard edition, so the rule for which edition a capability is
  in is this field;
* `compat` - the Compatibility Registry capability it stands on, which `compat.permits` is asked
  about at the experimental tier before it may act (arming.py);
* `ceilings` - how many sends it may make in a day, overall and in one conversation. Beside them
  stands one global ceiling for every capability together, GLOBAL_HOURLY an hour, which a person
  may lower and never raise (state.AdvancedState.set_global_hourly);
* `journal_prefix` and `codes` - the words its own journal lines are written in, `<prefix>.<code>`,
  closed like every other word the edition stores;
* `make` - the factory for its code: given the installation's paths, it returns an object whose
  methods are the plug's hooks for its points, each answering as a plug would.

There is no capability yet. DEFINITIONS is empty, so the registry the edition ships offers
nothing and its plug answers everywhere as the standard edition's does; the tests define one of
their own to hold every rule here.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Callable

from codex_auto_resume.domain.plug import Point

from .standards import STANDARDS

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


# The capabilities this edition ships. None yet.
DEFINITIONS = ()
REGISTRY = Registry(DEFINITIONS)
