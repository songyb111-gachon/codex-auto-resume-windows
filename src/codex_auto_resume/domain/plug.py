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
* A hook may always restrict, and may relax only as its point's set allows. A relaxation joins
  a set in the commit that teaches core to carry it out, and core holds each to bounds of its
  own a plug cannot widen (failures.admits, ladder.py).
* A hook that fails costs its own answer and nothing else: `consult` puts NULL's answer in its
  place.
* A hook is handed copies. What core reads again after asking - the record it sends, the due
  records it goes on to try, the facts a surface shows - is never the object a hook was given, so
  a hook that changes what it was handed and answers DEFER has changed nothing of core's.

These rules are kept against a plug's mistakes, not against its intent. The plug is the
advanced edition's package - this product's own code, from the same archive - running in core's
process, where closures, frames and the garbage collector reach every object core has and the
state is a file on the same disk. So what is handed over - copies, a view with no writes, a
connection that writes only the plug's own database, a name for the backend - removes the plain
way to a side effect a hook did not mean; no guard here is a sandbox or claims to be.

Core holds a plug only as `Guarded`, which asks every hook through `consult` and checks every
value a hook hands back before core takes it. The engine, the store's claim, the control layer
and every surface hold one; none of them calls a hook of a plug itself.

`edition.py` finds the package and makes a plug of it. This module is pure: the interface and
its version, NULL, the plug of an advanced installation whose package could not be loaded, the
guard core holds a plug in, and the six closed vocabularies they speak in - and what core holds of
a channel, a route or an errand a plug names is beside it, in domain/plughands.py. Those are `StrEnum`s
held to every rule `domain/vocabulary.py`'s are (tests/test_vocabulary.py), and they live here,
beside the one interface that uses them, as the interface's own words.
"""
from __future__ import annotations

from contextlib import nullcontext
import copy
from enum import StrEnum
import json

from .plughands import Channel, Errand, Route, records_of

# The interface's version. The advanced package writes out the number it was written for, and
# edition.py takes its plug only when the two agree: otherwise a hook renamed, or given another
# argument, would be called the old way or not at all, and nothing would say so. 2: P17 and `wants`.
# 3 (v0.6.14): P8's errand, and P2's records carried out.
PLUG_API = 3


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
    """Where core asks the plug (POINTS), numbered P2-P13 as the v0.6.11 plan numbers them, and
    P14 and P15, which the plan did not have.

    There is no P1. Classifying a turn into a core category would write a category that does
    not describe it, so an advanced record stays in the advanced store and reaches core through
    RECORDS instead, which core carries out from v0.6.14 (engine/plugrecords.py): each record is
    tried through core's gates, its one claim and its one send, and its moves are told at P14 in
    RecordMove's words.

    P14 is not a question: the engine tells the plug a record core holds has moved, as it writes
    the move. A person's own moves - a cancel, or the attempts given back (store/actions.py, and
    an older watcher's cancel, store/legacy.py) - are not told: what the person acted through
    wrote them, most often in a process that holds no engine. None moves a record into or out of
    submission_unknown, and a plug finds where they left it at its next P2 or P8. Read back out of
    the journal instead, a move would be a second source of truth a pruned entry changes; and at
    P8 the record's state alone has already moved on when the watch before it settled it.

    P15 (v0.6.11 stage 3) is how a continuation is carried and how its arrival is proven. Core
    has always ended the words with the record's marker and proven delivery by finding it in
    Codex's history (A4); a plug may answer CLIENT_ID instead, and core sends the words with no
    marker, under a client id it derives from the interruption, and proves delivery by that id.

    P16 (v0.6.11 stage 3a) is what continues a record whose conversation the app does not hold.
    Core has always waited for the app to open it (A11); a plug may name a route instead - an
    object with a `resume` - and core carries it out itself, as it carries out the send: its one
    claim, its pre-send look and its launch guard, the route called once, and what came of it
    settled by core's own rules (engine/delivery.py).

    P17 (v0.6.14 stage 3b) is whether a failure core never recovers alone is taken up, asked with
    the answers core would carry out for it (failures.takes): taken, it is a core record of its true
    category, which core follows as its own and known_failure (P3) puts to the plug again."""
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
    MOVED = "moved"                          # P14 a record core holds moved to another state
    DELIVERY = "delivery"                    # P15 how a continuation is carried and proven
    UNLOADED = "unloaded"                    # P16 what continues one the app does not hold
    ADMISSION = "admission"                  # P17 a failure core never recovers alone, taken up


class Alternative(StrEnum):
    """What a plug may answer at a decision point instead of DEFER (ANSWERS). Core carries out
    every one of them itself."""
    HOLD = "hold"                            # not now: the record keeps waiting, as on a WAIT
    # P15: no marker; queued under the client id core derives from the interruption
    # (ids.continuation_client_id), which is what proves it arrived.
    CLIENT_ID = "client_id"
    # P17, and P3 at known_failure: take a failure up, waiting as core waits for an admitted one
    # (ladder.ADMITTED_WAITS), or as a temporary failure of the kind named (PACED_AS).
    ADMIT = "admit"
    AS_NETWORK_TRANSIENT = "as_network_transient"
    AS_TIMEOUT = "as_timeout"
    AS_RATE_LIMIT_TRANSIENT = "as_rate_limit_transient"
    AS_SERVER_5XX = "as_server_5xx"
    AS_STREAM_INTERRUPTED = "as_stream_interrupted"
    CAPACITY = "capacity"                    # and a capacity error retried sooner, in core's limits
    EARLY = "early"                          # P7: a usage-limited record looked at before its time
    RESEND = "resend"                        # P7: an uncertain submission sent once more, if core may
    SEND_NOW = "send_now"                    # P7: a waiting record sent now, as a person asked


class FailureForm(StrEnum):
    """What form a failure's structured error took (failures.shape), as P17 is told it."""
    TAGGED = "tagged"                        # a code of Codex's, known or of the shape of one
    STATUS_ONLY = "status_only"              # a status number and no code
    UNRECOGNISED = "unrecognised"            # something, and neither
    MESSAGE_ONLY = "message_only"            # no structured error, only a message
    ABSENT = "absent"                        # nothing at all


class RecordMove(StrEnum):
    """What core did with a record of the plug's own (P2, v0.6.14), as P14 tells it (RECORD_MOVES): it
    waits, at a gate and for a reason core names; it was handed back before its send, or its process
    never started, and waits again with its words; it was sent - its words gone from the plug's state -
    and is watched; its marker was found in Codex's history; or none was a day after it was sent, and
    it is never sent again."""
    WAITING = "waiting"
    RELEASED = "released"
    NOT_STARTED = "not_started"
    SENT = "sent"
    DELIVERED = "delivered"
    UNPROVEN = "unproven"


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
RECORD_MOVES = tuple(RecordMove)
FAILURE_FORMS = tuple(FailureForm)
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
        """Records of the advanced store that are due now, to be tried like core's own, and those in
        flight, to be watched: asked once a tick, after core's own due records, with the engine's view
        of its store, and held to plughands.records_of (Guarded.records)."""
        return DEFER

    def gate(self, name, record, facts):              # P3
        """A gate's answer for one record, asked once core's own evaluation of that gate has
        passed - which is always after the consent gate. `facts` is the gate vector so far. One
        gate core refuses is asked too: known_failure, for a record P17 took up, whose category
        core never recovers alone - and DEFER, or a hook that fails, then ends it unsent."""
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
        the moment core's schedule made it so. From v0.6.14 also before then, for a record that waits
        for a usage limit to reset (or for usage), while core's early window is open: EARLY looks now. And
        for an uncertain submission a look of the watch found no trace of (`due` its send): RESEND
        sends it once more, where core proves it may (engine/resend.py). And for a waiting record its
        retry's wait or a postponement holds: SEND_NOW, a person's request, passes those, its spacing
        and its own attempt budget for this one look (engine/relaxed.py), and nothing else."""
        return DEFER

    def tick(self, view):                             # P8
        """Once a tick, after everything has been observed. From v0.6.14 it may answer an errand -
        something with a callable `run` - which core runs once, last in the tick, with guards of its own
        (Guarded.tick); any other answer is not read."""
        return DEFER

    def start_route(self, request):                   # P9
        """How the watcher is started for Codex. DEFER keeps core's own answer."""
        return DEFER

    def surface(self, name, facts):                   # P10
        """What one surface shows beyond core's own fields: a JSON object, or DEFER."""
        return DEFER

    def claim_ledger(self, connection, record, now, carried):  # P11
        """What the one claim counts beside core's own rows. Asked inside the claim's own
        transaction, on its connection, once every check core makes there has passed; what the
        hook writes on that connection is committed with the claim and with nothing else.
        `carried` is the points whose answers the send this claim leads to carries, as core
        decided them - TEXT for the plug's words, SENDER for its channel: what a ledger pays
        for, and all it pays for."""
        return DEFER

    def partition(self, records):                     # P12
        """How the due records are divided for dispatch."""
        return DEFER

    def supervise(self, facts):                       # P13
        """What the launcher does about a watcher that is not running."""
        return DEFER

    def moved(self, record, state):                   # P14
        """A record core holds has just moved to `state`: told once the move is written, with
        the record as core held it before - so its `state` is the one it left. Every move the
        engine writes is told, a Pause's included, because this decides nothing: it is how a
        plug learns what the engine did, as it happened. A person's own moves - a cancel, the
        attempts given back - are not told (Point, P14). Its answer is not read."""
        return DEFER

    def delivery(self, record):                       # P15
        """How a continuation of `record` is carried and how its arrival is proven, asked once
        a dispatch has its words and its sender, before the claim. DEFER is core's own way: the
        record's marker at the end of the words, found in Codex's history. CLIENT_ID is no
        marker: core queues the words through the channel the plug named at P5, under the client
        id it derives from the interruption, and proves delivery by that id alone - so without a
        channel, core's own backend being unable to name one, it is DEFER."""
        return DEFER

    def unloaded(self, record):                       # P16
        """What continues `record` while the app does not hold its conversation, asked once
        every gate before that one has passed, its consent included, and the app has said the
        conversation is notLoaded - never when it could not say. DEFER is core's own way: the
        record waits for the app to open it (A11). A route - an object with a callable `resume`
        - is carried out by core instead: the gates that follow, its one claim, the pre-send look,
        and the route called once inside the launch guard (engine/delivery.py)."""
        return DEFER

    def admission(self, failure):                     # P17
        """Whether core takes up a failure it would not recover alone, or relaxes one it would: `failure` is its
        facts - its kind, Codex's code and status and the error's form, never a word of the message - with
        `takes`, the answers core would carry out for it now, and `chain`, the record whose continuation started
        the turn that failed, or None (from v0.6.14 with `categories`, every kind its task has had, or None). An
        answer outside `takes` is DEFER. Asked only while `wants(ADMISSION)` says so."""
        return DEFER

    def wants(self, point):
        """Whether a capability may answer at `point` now. Not a point: it decides nothing, and
        core makes the reads a point needs only when it is True, so a plug with nothing on costs
        the standard edition's reads exactly. NULL wants nothing."""
        return False

    def edition_changed(self, previous):
        """The installer has just replaced an installation of edition `previous` with this one.

        Not a point: it is called once, by `install --edition-from`, never during a tick."""
        return None

    def codex(self, codex_exe, codex_home):
        """The Codex this process drives: the codex.exe the watcher found and checked - its
        `--codex-exe`, the `codex_exe` setting, or the one discovery chose - and the Codex home it
        runs it with, `--codex-home` or CODEX_HOME's. A plug whose own session with Codex has to
        be that very Codex, and whose reads have to be of that home, is told them here, once the
        watcher has built its backend (runtime/app.py), rather than finding a Codex of its own.

        Not a point: nothing is decided by it and its answer is not read. NULL keeps nothing."""
        return None


# Which hook each point calls.
HOOKS = {
    Point.RECORDS: "records", Point.GATES: "gate", Point.TEXT: "text", Point.SENDER: "sender",
    Point.OUTCOME: "outcome", Point.SCHEDULE: "schedule", Point.TICK: "tick",
    Point.START_ROUTE: "start_route", Point.SURFACES: "surface",
    Point.CLAIM_LEDGER: "claim_ledger", Point.CONCURRENCY: "partition",
    Point.SUPERVISION: "supervise", Point.MOVED: "moved", Point.DELIVERY: "delivery",
    Point.UNLOADED: "unloaded", Point.ADMISSION: "admission",
}

# A hook may always restrict. HOLD keeps a record waiting, exactly as a gate that says WAIT
# does, so every point that decides whether or when a record goes accepts it.
RESTRICTIONS = frozenset({Alternative.HOLD})

# The decision points, and what each accepts besides DEFER; anything else a hook answers at one
# of them is DEFER. At every other point a hook answers with a value - text, a sender, fields -
# and core checks it where it takes it, as it checks its own.
#
# An empty set is a point core asks and carries nothing out at yet. Something that follows a
# finished turn, a division of the due records and a restart each relax what core does alone, so
# each waits for the commit that teaches core to carry it out - and then joins its point's set, or
# leaves this table for a value core checks, as RECORDS (P2) did in v0.6.14: the records a plug
# hands over, each checked (plughands.records_of) and carried out by core (engine/plugrecords.py).
#
# START_ROUTE (v0.6.11 stage 3) and UNLOADED (P16, stage 3a) have left this table for values core
# checks: the plug names a route - an object with a `start`, or a `resume` - and core carries it
# out itself (Guarded.start_route; Guarded.unloaded, through its claim, engine/delivery.py).
#
# DELIVERY (P15) takes CLIENT_ID, which core learned to carry out in the same commit: the words
# with no marker, the one send made through the plug's channel with the client id core derived,
# and every look that proves or disproves delivery made for that id (engine/delivery.py). It
# relaxes no gate - every one of them has passed before it is asked - so it is not a restriction.
#
# ADMISSION (P17, v0.6.14 stage 3b) takes a failure up, or relaxes a capacity error's retries, and
# GATES the same words, which core takes only at known_failure and only for the kind each is for
# (failures.admits, failures.readmits) - CAPACITY within core's own bounds (ladder.py). SCHEDULE
# (P7) takes EARLY, RESEND and SEND_NOW, each carried out by core in its own (relaxed.py, resend.py).
TAKE_UP = frozenset({Alternative.ADMIT, Alternative.AS_NETWORK_TRANSIENT, Alternative.AS_TIMEOUT,
                     Alternative.AS_RATE_LIMIT_TRANSIENT, Alternative.AS_SERVER_5XX,
                     Alternative.AS_STREAM_INTERRUPTED, Alternative.CAPACITY})
ALTERNATIVES = {
    Point.GATES: RESTRICTIONS | TAKE_UP,
    Point.OUTCOME: frozenset(),
    Point.SCHEDULE: RESTRICTIONS | {Alternative.EARLY, Alternative.RESEND, Alternative.SEND_NOW},
    Point.CLAIM_LEDGER: RESTRICTIONS,
    Point.CONCURRENCY: frozenset(),
    Point.SUPERVISION: frozenset(),
    Point.DELIVERY: frozenset({Alternative.CLIENT_ID}),
    Point.ADMISSION: TAKE_UP,
}
# The temporary kind each AS_ word waits, counts and is switched off as (failures.TRANSIENT).
PACED_AS = {Alternative.AS_NETWORK_TRANSIENT: "network_transient", Alternative.AS_TIMEOUT: "timeout",
            Alternative.AS_RATE_LIMIT_TRANSIENT: "rate_limit_transient",
            Alternative.AS_SERVER_5XX: "server_5xx", Alternative.AS_STREAM_INTERRUPTED: "stream_interrupted"}

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


class Guarded:
    """A plug as core holds it: every hook asked through `consult`, every value checked before
    core takes it.

    It has a method for each of the plug's hooks, with the same arguments. A decision point
    answers DEFER or a member of its set; a value point answers DEFER or a value core can use,
    and anything else is DEFER - except at the sender, where it is core's own backend, because
    there is always a send to hand the one message to. Nothing a hook does reaches past this:
    it is handed copies (`consult`) and a stand-in for the backend (BACKEND), and a channel it
    names is held to the launch guard, as an errand is to guards of its own. `failures` counts the
    hooks that raised, over every caller on every thread; the claim asks through `claim_ledger_checked`, which says whether
    that one call raised (store/ledger.py)."""
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
        """P2: the records the plug hands over that core can carry out (plughands.records_of): a tuple,
        empty for anything else."""
        return records_of(self._ask(Point.RECORDS, view))

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
        return Channel(send) if callable(send) else backend

    def outcome(self, record, outcome):
        return self._ask(Point.OUTCOME, record, outcome)

    def schedule(self, record, due):
        return self._ask(Point.SCHEDULE, record, due)

    def tick(self, view):
        """P8: the errand the plug answered, held so that core runs it once with guards of its own
        (plughands.Errand) - or DEFER, for anything without a callable `run`."""
        answer = self._ask(Point.TICK, view)
        if answer is DEFER:
            return DEFER
        try:
            run = getattr(answer, "run", None)
        except Exception:                              # a `run` that raises when it is looked up
            return DEFER
        return Errand(run) if callable(run) else DEFER

    def start_route(self, request):
        """A route to start the watcher outside Codex's job, or DEFER.

        DEFER keeps core's own answer, which is today's refusal. Anything else is a route only
        if it has a callable `start`, which core calls with the command line it built itself; a
        word, a number, or an object without one is DEFER, so a hook that answers with something
        core cannot call changes nothing. The route is the plug's own code, held to the launch
        the way the sender's channel is: core decides when to call it, and with what."""
        answer = self._ask(Point.START_ROUTE, request)
        if answer is DEFER:
            return DEFER
        try:
            start = getattr(answer, "start", None)
        except Exception:                              # a `start` that raises when it is looked up
            return DEFER
        return answer if callable(start) else DEFER

    def surface(self, name, facts):
        """Fields for surface `name` (a Surface), or DEFER."""
        return fields(self._ask(Point.SURFACES, Surface(name), facts))

    def claim_ledger(self, connection, record, now, carried):
        return self.claim_ledger_checked(connection, record, now, carried)[0]

    def claim_ledger_checked(self, connection, record, now, carried):
        """P11 as the claim asks it: the answer, and whether this very call raised.

        Not `failures` read before and after: that counter is shared by every thread that holds
        this plug - the engine's, the icon's, a card's - and a surface failing on one of them
        while the ledger answered would have looked like the ledger breaking."""
        broke = []
        answer = self._ask(Point.CLAIM_LEDGER, connection, record, now, carried,
                           failed=broke.append)
        return answer, bool(broke)

    def partition(self, records):
        return self._ask(Point.CONCURRENCY, records)

    def supervise(self, facts):
        return self._ask(Point.SUPERVISION, facts)

    def moved(self, record, state):
        """P14. The record goes as a copy (`consult`), and the answer is not read."""
        self._ask(Point.MOVED, record, state)

    def delivery(self, record):
        """P15: CLIENT_ID, or DEFER - which is the marker, as core has always carried it. Core
        takes CLIENT_ID only for a send it hands to a channel (engine/dispatch.py)."""
        return self._ask(Point.DELIVERY, record)

    def unloaded(self, record):
        """P16: the route the plug names for a record whose conversation the app does not hold,
        held to the launch guard (plughands.Route), or DEFER - which is core's own wait (A11).

        A route is something with a callable `resume`; a word, a number, or an object without one
        is DEFER, so a hook that answers with something core cannot call changes nothing. Core
        calls it once, after its claim and its pre-send look (engine/delivery.py)."""
        answer = self._ask(Point.UNLOADED, record)
        if answer is DEFER:
            return DEFER
        try:
            resume = getattr(answer, "resume", None)
        except Exception:                              # a `resume` that raises when it is looked up
            return DEFER
        return Route(resume) if callable(resume) else DEFER

    def admission(self, failure):
        """P17: an answer of TAKE_UP, or DEFER. Core takes one only if failures.takes offered it."""
        return self._ask(Point.ADMISSION, failure)

    def wants(self, point) -> bool:
        """Plug.wants, True only if it says True: not a point, so NULL and a raise want nothing."""
        if self.plug is NULL:
            return False
        try:
            return self.plug.wants(Point(point)) is True
        except Exception:
            self.failures += 1
            return False

    def codex(self, codex_exe, codex_home):
        """Tell the plug which Codex this process drives (Plug.codex). Not a point, so not asked
        through `consult`: NULL is told nothing, and a plug that raises is counted in `failures`
        and has changed nothing of core's."""
        if self.plug is NULL:
            return
        try:
            self.plug.codex(codex_exe, codex_home)
        except Exception:
            self.failures += 1


def guard(plug) -> Guarded:
    """`plug` as core holds it. NULL for None or for anything that is not a plug, and a plug
    already guarded as it is."""
    return plug if isinstance(plug, Guarded) else Guarded(plug)
