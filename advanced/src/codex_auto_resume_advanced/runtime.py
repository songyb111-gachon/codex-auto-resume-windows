# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""The registry's capabilities, asked at the plug's points, each in the state a person put it in.

At every point the plug is asked at, each capability whose code answers there is taken in the
registry's order, and what it may do depends only on where it stands (arming.py):

* off: it is not asked at all;
* watched (shadow): it is asked, and whatever it answers is written to the journal as what it
  would have done - never taken, never spent, never a reason to move it anywhere;
* on (armed): its answer is taken. A restriction - HOLD - is taken at once, from any of them.
  Anything else is taken from the first that gives one, and where it leads to a send of the
  record it was given, only while its ceilings have a unit left; the unit itself is spent at the
  claim, before the claim is granted (ledger.py).

Only an answer core would take counts at all. Core checks every answer as it checks its own
(domain/plug.py's consult and Guarded, and the Custom message's validator for words), and the
same checks are made here first, so a capability is never journalled, counted or paid for an
answer core would not carry out; anything else is DEFER, as it is to core. Words that pass the
validator and still fill in to nothing for a record are the one answer core can drop after this -
it sends the person's own style instead - so what is paid for at the claim is what core says
there the send carries (P11's `carried`), never this runtime's own list of what it answered:
dropped words are journalled as taken, and cost nothing.

A hook that raises trips its own capability and costs its own answer, nothing more.

With no capability at a point, nothing is read and nothing is written: the answer is NULL's.
"""
from __future__ import annotations

import time

from codex_auto_resume import continuation
from codex_auto_resume.domain.plug import (ALTERNATIVES, ANSWERS, DEFER, HOOKS, NULL, RESTRICTIONS,
                                           Alternative, Point)

from .arming import Arming
from .ledger import ClaimLedger, ceiling_reached
from .registry import REGISTRY
from .state import AdvancedState, StateError
from .vocabulary import ArmingState, JournalCode, OffReason

# How long what every capability stands at is taken as read, between ticks. A tick reads it
# again; a process that has no ticks - the bridge, the MCP server - reads it at most this often.
REFRESH_SECONDS = 5.0
# The points whose answer, if it is not a restriction, leads to a send of the record it was
# given - so the capability pays a unit for it at that record's claim. Which argument the record
# is, at each.
SENDING = {Point.GATES: 1, Point.TEXT: 0, Point.SENDER: 0, Point.SCHEDULE: 0, Point.OUTCOME: 0}
# Journal lines written once per capability, point, answer and record in a process, not once a
# poll; forgotten, all at once, past this many.
NOTED_LIMIT = 4096


def _taken(point, answer) -> bool:
    """Whether core would take `answer` at `point`, by the checks core makes itself."""
    try:
        if point in ALTERNATIVES:
            return answer in ALTERNATIVES[point]
        if point == Point.TEXT:
            continuation.validate_custom(answer)
            return True
        if point == Point.SENDER:
            return callable(getattr(answer, "send", None))
    except Exception:                              # unhashable, refused, a `send` that raises
        return False
    return True                                    # the tick's answer is not read


def _restricts(answer) -> bool:
    try:
        return answer in RESTRICTIONS
    except TypeError:
        return False


def _word(answer, point):
    """What the journal may say an answer was: its word, if it is one of the alternatives, else
    the point it was given at. Never the answer itself - words a capability would have sent, or
    a channel, are not the journal's to keep."""
    try:
        return answer if answer in ANSWERS else point
    except TypeError:
        return point


class Runtime:
    def __init__(self, paths, *, registry=REGISTRY, clock=time.time,
                 measure_session_factory=None, measure_launcher=None, measure_backend=None,
                 evidence_dir=None, **arming):
        self.paths = paths
        self.registry = registry
        self.clock = clock
        self.state = AdvancedState(paths, registry=registry, clock=clock)
        self.arming = Arming(self.state, clock=clock, **arming)
        self.ledger = ClaimLedger(self.state)
        self._states, self._at = {}, None
        self._code = {}
        self._acted = {}
        self._noted = set()
        # The measurement harness's seams (measure.py). A person runs a measurement; production
        # opens a real one-turn session against the installed Codex and records to the source
        # tree, and a test gives a fake session and a temporary directory, so no test opens a
        # real Codex or writes into the repository.
        self._measure_session_factory = measure_session_factory
        self._measure_launcher = measure_launcher
        self._measure_backend = measure_backend
        self._evidence_dir = evidence_dir

    # ------------------------------------------------------------------ standing
    def states(self, *, fresh=False) -> dict:
        now = self.clock()
        if fresh or self._at is None or not 0 <= now - self._at < REFRESH_SECONDS:
            self._states, self._at = self.arming.current(), now
        return self._states

    def _code_of(self, definition):
        if definition.id not in self._code:
            self._code[definition.id] = definition.make(self.paths)
        return self._code[definition.id]

    def _tripped(self, definition) -> None:
        self.arming.trip(definition.id, OffReason.HOOK_EXCEPTION)
        self._states[definition.id] = ArmingState.OFF

    # ------------------------------------------------------------------ asking
    def ask(self, point, *arguments):
        """The answer at `point`: an armed capability's, or NULL's."""
        definitions = self.registry.at(point)
        if not definitions:
            return getattr(NULL, HOOKS[point])(*arguments)
        states = self.states()
        record = arguments[SENDING[point]] if point in SENDING else None
        chosen = chooser = None
        for definition in definitions:
            state = states.get(definition.id, ArmingState.OFF)
            if state == ArmingState.OFF:
                continue
            try:
                answer = getattr(self._code_of(definition), HOOKS[point])(*arguments)
            except Exception:
                self._tripped(definition)
                continue
            if (answer is DEFER or (point == Point.SENDER and answer is arguments[-1])
                    or not _taken(point, answer)):
                continue
            if state == ArmingState.SHADOW:
                self._once(JournalCode.WOULD_HAVE, definition, point, answer, record)
                continue
            if _restricts(answer):
                self._once(JournalCode.ACTED, definition, point, answer, record)
                return answer
            if chooser is not None:
                continue
            if point in SENDING:
                if not isinstance(record, dict) or self._ceiling(definition, record) is not None:
                    self._once(JournalCode.CEILING, definition, point, answer, record)
                    continue
            chosen, chooser = answer, definition
        if chooser is None:
            return getattr(NULL, HOOKS[point])(*arguments)
        if point in SENDING:
            self._acted.setdefault(record.get("interruption_id"), set()).add((point, chooser.id))
        self._once(JournalCode.ACTED, chooser, point, chosen, record)
        return chosen

    def _ceiling(self, definition, record):
        """The ceiling that leaves `definition` nothing to spend on `record` now, looked at
        before the claim; the claim looks again, under its lock, before it spends."""
        try:
            counts = self.state.spent(definition.id, record.get("thread_id"))
            return ceiling_reached(counts, definition, self.state.meta()["global_hourly"])
        except StateError:
            return True                          # nothing can be paid for, so nothing is taken

    def _once(self, code, definition, point, answer, record) -> None:
        key = (code, definition.id, point, _word(answer, point),
               record.get("interruption_id") if isinstance(record, dict) else None)
        if key in self._noted:
            return
        if len(self._noted) >= NOTED_LIMIT:
            self._noted.clear()
        self._noted.add(key)
        try:
            self.state.note(code, capability=definition.id, point=point, answer=_word(answer, point),
                            at=self.clock())
        except StateError:
            pass

    # ------------------------------------------------------------------ the tick and the claim
    def tick(self, view):
        """P8: every trip and reset there is to find, what every capability stands at read
        afresh, then the capabilities that answer once a tick."""
        self._acted.clear()
        if not len(self.registry):
            return DEFER
        self.arming.sweep(view)
        self.states(fresh=True)
        return self.ask(Point.TICK, view)

    def moved(self, record, state):
        """P14: core has moved `record` to `state`. Its one use is a tripwire's (arming.py): a
        capability that tripped is off from here on, not from the next tick."""
        if not len(self.registry):
            return DEFER
        if self.arming.moved(record, state):
            self.states(fresh=True)
        return DEFER

    def claim(self, connection, record, now, carried):
        """P11: the ledger, told which capabilities' answers this claim carries.

        Those are the capabilities that answered at a point in `carried` - the points whose
        answers core says the send carries - and no other: words core dropped for filling in to
        nothing were answered here and never sent, so they are neither paid for nor a reason to
        hold a claim of core's own words.

        A ledger that breaks is two different things. On a claim of core's own it costs its
        answer, as any hook's failure does, and core claims as it would with no plug. On a claim
        that carries a capability's answer, that answer could not be paid for, so the claim is
        held and nothing of it is sent; core takes back whatever the ledger had written."""
        key = record.get("interruption_id") if isinstance(record, dict) else None
        acted = {capability for point, capability in self._acted.pop(key, ()) if point in carried}
        try:
            return self.ledger.claim(connection, record, now, acted)
        except Exception:
            if acted:
                return Alternative.HOLD
            raise

    # ------------------------------------------------------------------ the measurement harness
    def run_measurement(self, measurement, thread=None):
        """Run one measurement the person asked for, and record what it found (measure.py).

        The session and the launcher are the runtime's own seams: production opens a real
        one-turn session against the installed Codex and writes to the source tree's evidence
        directory, and a test gives fakes and a temporary directory. Nothing here runs unless a
        surface was asked for it by a person.

        `thread` is an optional real throwaway conversation the owner points a measurement at,
        validated as a Codex thread id and used in the calls the probe makes, never written into
        the record.

        The backend is the one the session opens, so the record says which Codex it measured:
        without it every record said "unknown", and a measurement decides per Codex version. The
        launcher is MW's real WMI chain when a test wired none; only MW ever calls it, so it is
        built lazily and never touched by the other measurements."""
        from . import measure
        session_factory, backend = self._measure_session_factory, self._measure_backend
        if session_factory is None:
            backend = backend if backend is not None else measure.live_backend()
            session_factory = measure.live_session_factory(self.paths, backend)
        launcher = self._measure_launcher
        if launcher is None:
            launcher = measure.live_launcher(self.paths)
        return measure.run(measurement, session_factory=session_factory,
                           launcher=launcher, backend=backend, thread=thread,
                           directory=self._evidence_dir, clock=self.clock)

    def complete_measurement(self, measurement, verdict, note):
        """Record a person's completion of a blocked measurement (measure-verdict, measure.py).

        The backend is the one whose Codex version the record was measured on, so a completion
        only ever lands on a record of the same Codex; a run that cannot say which Codex it is on
        completes nothing. Nothing here opens a session or starts a process: the person has
        already done the step in the Codex app, and this only writes what they saw."""
        from . import measure
        backend = self._measure_backend
        if backend is None and self._measure_session_factory is None:
            backend = measure.live_backend()
        return measure.complete(measurement, verdict, note, backend=backend,
                                directory=self._evidence_dir, clock=self.clock)
