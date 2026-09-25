"""The plug: the one way an edition's own code reaches core, and what core does with none.

The advanced edition is the standard edition plus one package. Core never imports that
package. It asks a plug, at a fixed list of points, and in the standard edition the plug is
NULL, which answers every question the way core answers it alone. So the standard edition does
not depend on a setting that switches advanced code off - it holds no advanced code to switch -
and an advanced edition with nothing turned on answers exactly as NULL does.

Three rules make an answer safe to take:

* Only core acts. A hook answers; it never sends, claims or starts anything. At a decision
  point it answers DEFER or a member of that point's closed set in ALTERNATIVES, and core
  carries the member out itself, through its one claim, its pre-send look and its launch guard.
* A hook may always restrict, and may relax only as its point's set allows. There is no
  relaxation yet: one joins a set in the commit that teaches core to carry it out.
* A hook that fails costs its own answer and nothing else: `consult` puts NULL's answer in its
  place.

`edition.py` finds the package and makes a plug of it. This module is pure: the interface and
its version, NULL, the plug of an advanced installation whose package could not be loaded, and
the four closed vocabularies they speak in. Those are `StrEnum`s held to every rule
`domain/vocabulary.py`'s are (tests/test_vocabulary.py), and they live here, beside the one
interface that uses them, as the interface's own words.
"""
from __future__ import annotations

from enum import StrEnum

# The interface's version. The advanced package writes out the number it was written for, and
# edition.py takes its plug only when the two agree: otherwise a hook renamed, or given another
# argument, would be called the old way or not at all, and nothing would say so.
PLUG_API = 1


class Edition(StrEnum):
    """Which edition an installation is (edition.EDITIONS). Nothing is stamped anywhere to say
    which: the advanced package beside core is the whole difference."""
    STANDARD = "standard"
    ADVANCED = "advanced"


class PlugFailure(StrEnum):
    """Why an advanced installation's package was not loaded (edition.PLUG_FAILURES). Each one
    leaves the installation doing exactly what the standard edition does, and saying so."""
    SHADOWED = "shadowed"                    # Python would import another copy first
    IMPORT_FAILED = "import_failed"          # its plug module raised while it was imported
    API_MISMATCH = "api_mismatch"            # it was written for another PLUG_API
    FACTORY_FAILED = "factory_failed"        # its factory raised, or made no plug


class Point(StrEnum):
    """Where core asks the plug (POINTS), numbered P2-P13 as the v0.6.11 plan numbers them.

    There is no P1. Classifying a turn into a core category would write a category that does
    not describe it, so an advanced record stays in the advanced store and reaches core through
    RECORDS instead."""
    RECORDS = "records"                      # P2  records of the advanced store, due now
    GATES = "gates"                          # P3  the gates a record passes before it is sent
    TEXT = "text"                            # P4  what the continuation says
    SENDER = "sender"                        # P5  what the one send is handed to
    OUTCOME = "outcome"                      # P6  what follows a turn that ended
    SCHEDULE = "schedule"                    # P7  when a record is looked at next
    TICK = "tick"                            # P8  once a tick, after everything is observed
    START_ROUTE = "start_route"              # P9  how the watcher is started for Codex
    SURFACES = "surfaces"                    # P10 what the status, the bridge and the panel show
    CLAIM_LEDGER = "claim_ledger"            # P11 the caps counted inside the one claim
    CONCURRENCY = "concurrency"              # P12 how due records are divided for dispatch
    SUPERVISION = "supervision"              # P13 how the launcher keeps the watcher running


class Alternative(StrEnum):
    """What a plug may answer at a decision point instead of DEFER (ANSWERS). Core carries out
    every one of them itself."""
    HOLD = "hold"                            # not now: the record keeps waiting, as on a WAIT


POINTS = tuple(Point)


class _Defer:
    """The answer that means "core decides, as if there were no plug"."""
    __slots__ = ()

    def __repr__(self):
        return "DEFER"


# An object rather than a word, so that no string a hook returns - "defer" included - can be
# mistaken for it.
DEFER = _Defer()


class Plug:
    """Every hook core calls, each answering as core would with no plug at all.

    NULL is this class and nothing more. An edition's plug subclasses it and overrides only the
    hooks its capabilities use, so a hook it leaves alone keeps NULL's answer. Each hook is given
    what core holds at its point, and NULL reads none of it.
    """
    __slots__ = ()
    edition = Edition.STANDARD
    badge = "Standard"

    def records(self, view):                          # P2
        """Records of the advanced store that are due now, to be tried like core's own."""
        return DEFER

    def gate(self, name, record, facts):              # P3
        """A gate's answer for one record, after the consent gate has passed."""
        return DEFER

    def text(self, record, text):                     # P4
        """What the continuation says, decided before the claim."""
        return DEFER

    def sender(self, record, backend):                # P5
        """What the one send is handed to: core's own backend, unless a channel says otherwise."""
        return backend

    def outcome(self, record, outcome):               # P6
        """What follows a turn that has ended."""
        return DEFER

    def schedule(self, record, due):                  # P7
        """When a record is looked at next."""
        return DEFER

    def tick(self, view):                             # P8
        """Once a tick, after everything has been observed. Its answer is not read."""
        return DEFER

    def start_route(self, request):                   # P9
        """How the watcher is started for Codex. DEFER keeps core's own answer."""
        return DEFER

    def surface(self, name, facts):                   # P10
        """What one surface shows beyond core's own fields."""
        return DEFER

    def claim_ledger(self, record):                   # P11
        """What the one claim counts beside core's own rows."""
        return DEFER

    def partition(self, records):                     # P12
        """How the due records are divided for dispatch."""
        return DEFER

    def supervise(self, facts):                       # P13
        """What the launcher does about a watcher that is not running."""
        return DEFER

    def edition_changed(self, previous):
        """The installer has just replaced an installation of edition `previous` with this one.

        Not a point: it is called once, by `install --edition-from`, never during a tick."""
        return None


# Which hook each point calls.
HOOKS = {
    Point.RECORDS: "records", Point.GATES: "gate", Point.TEXT: "text", Point.SENDER: "sender",
    Point.OUTCOME: "outcome", Point.SCHEDULE: "schedule", Point.TICK: "tick",
    Point.START_ROUTE: "start_route", Point.SURFACES: "surface",
    Point.CLAIM_LEDGER: "claim_ledger", Point.CONCURRENCY: "partition",
    Point.SUPERVISION: "supervise",
}

# A hook may always restrict. HOLD keeps a record waiting, exactly as a gate that says WAIT
# does, so every point that decides whether or when a record goes accepts it.
RESTRICTIONS = frozenset({Alternative.HOLD})

# The decision points, and what each accepts besides DEFER; anything else a hook answers at one
# of them is DEFER. At every other point a hook answers with a value - records, text, a sender,
# fields - and core checks it where it takes it, as it checks its own.
ALTERNATIVES = {
    Point.GATES: RESTRICTIONS,
    Point.SCHEDULE: RESTRICTIONS,
    Point.START_ROUTE: frozenset(),
    Point.SUPERVISION: frozenset(),
}

# Every alternative some point accepts. The vocabulary is exactly these
# (tests/test_vocabulary.py), so no word waits in it for a point that does not take it.
ANSWERS = frozenset().union(*ALTERNATIVES.values())

NULL = Plug()


class DamagedPlug(Plug):
    """An advanced installation whose package could not be loaded.

    It does everything NULL does and nothing else - a package half loaded is worse than one not
    loaded at all - and says so: its badge reads "Advanced - not loaded", and `reason` is why.
    """
    __slots__ = ("reason",)
    edition = Edition.ADVANCED
    badge = "Advanced - not loaded"

    def __init__(self, reason):
        self.reason = PlugFailure(reason)


def consult(plug, point, *arguments):
    """Ask `plug` at `point`, the one way core asks.

    A hook that raises gets NULL's answer in its place, so a broken capability costs its own
    answer and nothing more. At a decision point, an answer outside the point's closed set is
    DEFER: an unknown word, another point's word, or something that is not a word at all.
    """
    point = Point(point)
    hook = HOOKS[point]
    try:
        answer = getattr(plug, hook)(*arguments)
    except Exception:
        return getattr(NULL, hook)(*arguments)
    if point not in ALTERNATIVES or answer is DEFER:
        return answer
    try:
        accepted = answer in ALTERNATIVES[point]
    except TypeError:                                  # unhashable, so no word
        return DEFER
    return Alternative(answer) if accepted else DEFER
