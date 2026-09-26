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
* A hook is handed copies. What core reads again after asking - the record it sends, the due
  records it goes on to try, the facts a surface shows - is never the object a hook was given, so
  a hook that changes what it was handed and answers DEFER has changed nothing of core's.

Core holds a plug only as `Guarded`, which asks every hook through `consult` and checks every
value a hook hands back before core takes it. The engine, the store's claim, the control layer
and every surface hold one; none of them calls a hook of a plug itself.

`edition.py` finds the package and makes a plug of it. This module is pure: the interface and
its version, NULL, the plug of an advanced installation whose package could not be loaded, the
guard core holds a plug in, and the five closed vocabularies they speak in. Those are `StrEnum`s
held to every rule `domain/vocabulary.py`'s are (tests/test_vocabulary.py), and they live here,
beside the one interface that uses them, as the interface's own words.
"""
from __future__ import annotations

from contextlib import nullcontext
import copy
from enum import StrEnum
import json

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


class Surface(StrEnum):
    """What a plug may add to at P10 (SURFACES). What it adds sits under the one key EXTRA,
    beside everything core shows there and never in place of any of it."""
    STATUS = "status"                        # the status the Dashboard, the panel and get_status show
    BRIDGE = "bridge"                        # a bridge command core has none of its own for
    DIAGNOSTICS = "diagnostics"              # the diagnostics export
    TRAY = "tray"                            # what the icon draws from
    MCP = "mcp"                              # tools after core's own, and a call to one of them


POINTS = tuple(Point)
SURFACES = tuple(Surface)
# The key a surface puts a plug's fields under. NULL never adds any, so no standard surface
# carries it.
EXTRA = "advanced"


class _Defer:
    """The answer that means "core decides, as if there were no plug"."""
    __slots__ = ()

    def __repr__(self):
        return "DEFER"


# An object rather than a word, so that no string a hook returns - "defer" included - can be
# mistaken for it.
DEFER = _Defer()


class _Backend:
    """What a hook is handed at P5 where core's backend would be: a name for it, and nothing
    more."""
    __slots__ = ()

    def __repr__(self):
        return "BACKEND"


# Core's own backend, as P5 names it to a hook. Answered back - or DEFER - it keeps the backend.
# The backend itself is never handed over: a hook holding it could rebind its `send` and answer
# DEFER, and the one send went through the rebound method, outside the launch guard, with the
# claim told it carried nothing of the plug's.
BACKEND = _Backend()


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
        """Records of the advanced store that are due now, to be tried like core's own. Asked
        once a tick, after core's own due records, with the engine's view of its store."""
        return DEFER

    def gate(self, name, record, facts):              # P3
        """A gate's answer for one record, asked once core's own evaluation of that gate has
        passed - which is always after the consent gate. `facts` is the gate vector so far."""
        return DEFER

    def text(self, record, text):                     # P4
        """What the continuation says, decided before the claim. `text` is core's own."""
        return DEFER

    def sender(self, record, backend):                # P5
        """What the one send is handed to: core's own backend, unless a channel says otherwise.
        `backend` is BACKEND, which stands for core's backend and is not it."""
        return backend

    def outcome(self, record, outcome):               # P6
        """What follows a turn that has ended: asked as a record moves from following its
        recovery turn to `outcome`, one of the outcome states."""
        return DEFER

    def schedule(self, record, due):                  # P7
        """When a record is looked at next, asked when core's schedule says it is due; `due` is
        the moment core's schedule made it so."""
        return DEFER

    def tick(self, view):                             # P8
        """Once a tick, after everything has been observed. Its answer is not read."""
        return DEFER

    def start_route(self, request):                   # P9
        """How the watcher is started for Codex. DEFER keeps core's own answer."""
        return DEFER

    def surface(self, name, facts):                   # P10
        """What one surface shows beyond core's own fields: a JSON object, or DEFER."""
        return DEFER

    def claim_ledger(self, connection, record, now):  # P11
        """What the one claim counts beside core's own rows. Asked inside the claim's own
        transaction, on its connection, once every check core makes there has passed; what the
        hook writes on that connection is committed with the claim and with nothing else."""
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
# of them is DEFER. At every other point a hook answers with a value - text, a sender, fields -
# and core checks it where it takes it, as it checks its own.
#
# An empty set is a point core asks and carries nothing out at yet. An advanced record tried
# like core's own, something that follows a finished turn, another way to start the watcher, a
# division of the due records and a restart each relax what core does alone, so each waits for
# the commit that teaches core to carry it out - and then joins its point's set, or leaves this
# table for a value core checks.
ALTERNATIVES = {
    Point.RECORDS: frozenset(),
    Point.GATES: RESTRICTIONS,
    Point.OUTCOME: frozenset(),
    Point.SCHEDULE: RESTRICTIONS,
    Point.START_ROUTE: frozenset(),
    Point.CLAIM_LEDGER: RESTRICTIONS,
    Point.CONCURRENCY: frozenset(),
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


def _handed(argument):
    """What a hook is given of `argument`: a copy of core's own records and facts, and anything
    else - a view, a connection, BACKEND - as it is, each being what its point hands over."""
    if isinstance(argument, (dict, list)):
        return copy.deepcopy(argument)
    return argument


def consult(plug, point, *arguments, failed=None):
    """Ask `plug` at `point`, the one way core asks.

    A hook that raises gets NULL's answer in its place, so a broken capability costs its own
    answer and nothing more; `failed`, if given, is told the point it happened at. At a decision
    point, an answer outside the point's closed set is DEFER: an unknown word, another point's
    word, or something that is not a word at all - and one whose hashing or comparison raises is
    a hook that failed, since that is the plug's own code running.

    Every record and every fact goes to the hook as a copy (`_handed`). The row whose thread and
    marker the send takes, the due list the tick goes on to try, the status a surface returns:
    a hook that rewrote any of them and answered DEFER would have relaxed what core does through
    a side effect, where DEFER says it changed nothing. NULL reads nothing, so it is given
    core's own and nothing is copied for the standard edition.
    """
    point = Point(point)
    hook = HOOKS[point]
    if plug is NULL:
        return getattr(NULL, hook)(*arguments)
    try:
        answer = getattr(plug, hook)(*(_handed(argument) for argument in arguments))
    except Exception:
        if failed is not None:
            failed(point)
        return getattr(NULL, hook)(*arguments)
    if point not in ALTERNATIVES or answer is DEFER:
        return answer
    try:
        accepted = answer in ALTERNATIVES[point]
    except TypeError:                                  # unhashable, so no word
        return DEFER
    except Exception:                                  # a __hash__ or __eq__ of the plug's raised
        if failed is not None:
            failed(point)
        return DEFER
    return Alternative(answer) if accepted else DEFER


def fields(answer):
    """What a surface takes from a plug: a JSON object, copied, or DEFER.

    Words for keys, and nothing JSON cannot write strictly - no NaN, no infinity, no object of
    some other kind - so what a plug adds reaches a front end through the same writer as every
    reply (controlcli.encode) and cannot break it. It is copied through that writer's own form,
    so nothing the plug keeps a reference to changes a reply after it was made.

    A dict with str keys exactly, not a subclass of either: a subclass brings its own iteration,
    items and hashing, which are the plug's code running here, outside `consult`. Anything at all
    that goes wrong while it is copied is DEFER - a surface is the status, get_status and the
    Dashboard, which a strange answer must never break."""
    try:
        if type(answer) is not dict or not all(type(key) is str for key in answer):
            return DEFER
        return json.loads(json.dumps(answer, allow_nan=False))
    except Exception:
        return DEFER


class _Channel:
    """A channel a plug named at P5, held to the launch guard rather than asked to enter it.

    Core's backend enters the guard it is handed around the one moment it launches the queue
    process, so a Pause, a cancel or a conversation switched off that committed after the claim
    stops the send there. A channel is the plug's code, and nothing made it enter the guard it
    was handed, so this enters the guard for it: consent is read under the store's write lock,
    and the channel is called only if it held, with a guard already decided.

    The lock is let go before the channel is called, as core's backend lets it go once the
    queue process is launched: calling the channel is this send's launch. It is never held
    across the channel's send. That is a transport core cannot see into, and the lock is the
    advanced state's too once the claim has attached it, so a Pause from the settings window,
    a disarm on another thread and the channel's own write to the advanced state all waited
    for it - and failed, past SQLite's ten seconds. A Pause that commits once consent was read
    finds a send started, as it finds one of the backend's after its launch."""
    __slots__ = ("_send",)

    def __init__(self, send):
        self._send = send

    def send(self, thread_id, prompt, *, launch_guard=None):
        with launch_guard if launch_guard is not None else nullcontext(True) as permitted:
            pass
        if permitted is not True:
            return {"outcome": "not_started", "error_code": "queue_consent_refused"}
        return self._send(thread_id, prompt, launch_guard=nullcontext(True))


class Guarded:
    """A plug as core holds it: every hook asked through `consult`, every value checked before
    core takes it.

    It has a method for each of the plug's hooks, with the same arguments. A decision point
    answers DEFER or a member of its set; a value point answers DEFER or a value core can use,
    and anything else is DEFER - except at the sender, where it is core's own backend, because
    there is always a send to hand the one message to. Nothing a hook does reaches past this:
    it is handed copies (`consult`) and a stand-in for the backend (BACKEND), and a channel it
    names is held to the launch guard.
    `failures` counts the hooks that raised, over every caller of this plug on every thread; the
    claim asks through `claim_ledger_checked` instead, which says whether that one call raised
    (store/claims.py).
    """
    __slots__ = ("plug", "failures")

    def __init__(self, plug):
        self.plug = plug if isinstance(plug, Plug) else NULL
        self.failures = 0

    @property
    def null(self) -> bool:
        """Whether this is the standard edition's plug, where core does exactly what it does
        with no plug at all - down to the statements it runs."""
        return self.plug is NULL

    @property
    def edition(self) -> Edition:
        return self.plug.edition

    @property
    def badge(self) -> str:
        return self.plug.badge

    def _failed(self, _point):
        self.failures += 1

    def _ask(self, point, *arguments, failed=None):
        def told(where):
            self._failed(where)
            if failed is not None:
                failed(where)
        return consult(self.plug, point, *arguments, failed=told)

    def records(self, view):
        return self._ask(Point.RECORDS, view)

    def gate(self, name, record, facts):
        return self._ask(Point.GATES, name, record, facts)

    def text(self, record, text):
        """Words, or DEFER. Core still checks them as it checks a person's Custom message."""
        answer = self._ask(Point.TEXT, record, text)
        return answer if isinstance(answer, str) else DEFER

    def sender(self, record, backend):
        """`backend` itself, or the channel the plug named, held to the launch guard (`_Channel`).

        The plug is asked with BACKEND in the backend's place, and that answer or DEFER is the
        backend. Anything else with a `send` is a channel, core's own backend included, should
        a plug have found it some other way: held to the guard, and paid for as the plug's."""
        answer = self._ask(Point.SENDER, record, BACKEND)
        if answer is BACKEND or answer is DEFER:
            return backend
        try:
            send = getattr(answer, "send", None)
        except Exception:                              # a `send` that raises when it is looked up
            return backend
        return _Channel(send) if callable(send) else backend

    def outcome(self, record, outcome):
        return self._ask(Point.OUTCOME, record, outcome)

    def schedule(self, record, due):
        return self._ask(Point.SCHEDULE, record, due)

    def tick(self, view):
        self._ask(Point.TICK, view)

    def start_route(self, request):
        return self._ask(Point.START_ROUTE, request)

    def surface(self, name, facts):
        """Fields for surface `name` (a Surface), or DEFER."""
        return fields(self._ask(Point.SURFACES, Surface(name), facts))

    def claim_ledger(self, connection, record, now):
        return self.claim_ledger_checked(connection, record, now)[0]

    def claim_ledger_checked(self, connection, record, now):
        """P11 as the claim asks it: the answer, and whether this very call raised.

        Not `failures` read before and after: that counter is shared by every thread that holds
        this plug - the engine's, the icon's, a card's - and a surface failing on one of them
        while the ledger answered would have looked like the ledger breaking."""
        broke = []
        answer = self._ask(Point.CLAIM_LEDGER, connection, record, now, failed=broke.append)
        return answer, bool(broke)

    def partition(self, records):
        return self._ask(Point.CONCURRENCY, records)

    def supervise(self, facts):
        return self._ask(Point.SUPERVISION, facts)


def guard(plug) -> Guarded:
    """`plug` as core holds it. NULL for None or for anything that is not a plug, and a plug
    already guarded as it is."""
    return plug if isinstance(plug, Guarded) else Guarded(plug)
