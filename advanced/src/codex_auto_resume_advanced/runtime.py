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

A hook that raises trips its own capability and costs its own answer, nothing more - or, for one kept
on (K8, arming.py), stays on and skips that one recovery: it is passed over for that record from then
on, and core goes its own way with it.

Keep on's Send again (v0.6.14): at P7, for an uncertain submission, the capability that paid for its
send and is kept on with Send again answers RESEND before any capability's own hook is asked
(arming.Arming.resender) - one answer like any other, journalled, under its ceilings, and paid for at
the claim, which reads Send again's words once more (ledger.py). What each answer was is kept with it
until the claim, so the ledger pays for a resend, or a person's Send now, only where it was that.

With no capability at a point, nothing is read and nothing is written: the answer is NULL's.

Taking failures up (v0.6.13, stage 3b). At P17 an answer is taken only if core offered it - one of
the `takes` core hands over (failures.takes) - and only for a failure that completed after the
capability was last turned on or watched: arming never reaches back. A capability that takes one up
is remembered as the one that did, with its word (state/choices.py, admissions). At P3 such a word
is taken only at known_failure, and only from that capability with that very word, so none relaxes a
record it did not take up, or at another gate. A record core never recovers alone that it took up
waits, where the state cannot be read or its capability has no unit left, and ends only where a read
that worked found nothing holding it; a capacity error is never parked so - the standard edition's
handling is what it falls back to. From v0.6.14 a record is relaxed only while its capability has
stood on ever since it took the record up: turned off, watched or read down by the policy in between,
however briefly, the record ends unsent at its next look, though the capability stands on again then.
The first time core goes on with a record a capability took up, the capability is told (`taken`) and
what it keeps of it - a sample, a rule's hit - is written with the mark that it was told, in one
transaction, once.
"""
from __future__ import annotations

from inspect import getattr_static
import time

from codex_auto_resume import continuation, failures
from codex_auto_resume.domain.plug import (ALTERNATIVES, ANSWERS, DEFER, HOOKS, NULL, RESTRICTIONS,
                                           TAKE_UP, Alternative, Point)

from .arming import Arming
from .ledger import ClaimLedger, ceiling_reached
from .registry import REGISTRY
from .state import AdvancedState, StateError
from .vocabulary import ArmingState, CapabilityKind, JournalCode, OffReason

# How long what every capability stands at is taken as read, between ticks. A tick reads it
# again; a process that has no ticks - the bridge, the MCP server - reads it at most this often.
REFRESH_SECONDS = 5.0
# The points whose answer, if it is not a restriction, leads to a send of the record it was
# given - so the capability pays a unit for it at that record's claim. Which argument the record
# is, at each.
# P17 is one of them for the look before the claim alone: a failure is taken up only while the
# capability has a unit left, and no claim carries P17, so it is never paid for there.
SENDING = {Point.GATES: 1, Point.TEXT: 0, Point.SENDER: 0, Point.SCHEDULE: 0, Point.OUTCOME: 0,
           Point.DELIVERY: 0, Point.UNLOADED: 0, Point.ADMISSION: 0}
# The gate a record taken up at P17 is put to the plug again at (core's engine/relaxed.py).
KNOWN_FAILURE = "known_failure"
# The words that take a failure up at P17 and relax its record at known_failure.
RELAXING = TAKE_UP
# Those a capability with no unit left holds its record on, rather than letting it end: all but
# CAPACITY, whose record the standard edition goes on with as it always did.
HELD_AT_CEILING = TAKE_UP - {Alternative.CAPACITY}
# Journal lines written once per capability, point, answer and record in a process, not once a
# poll; forgotten, all at once, past this many.
NOTED_LIMIT = 4096
# The state core holds a record in whose send may or may not have reached Codex.
SUBMISSION_UNKNOWN = "submission_unknown"


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
        if point == Point.UNLOADED:
            return callable(getattr(answer, "resume", None))
    except Exception:                              # unhashable, refused, a `send` that raises
        return False
    return True                                    # the tick's answer is not read


def _own(code, name):
    """`code`'s own method `name`, if its class defines one, else None - an optional hook a
    capability has only where it means to (`bind`, `rule_for`, `taken`)."""
    if getattr_static(code, name, None) is None:
        return None
    found = getattr(code, name, None)
    return found if callable(found) else None


def _known_failure(name) -> bool:
    return isinstance(name, str) and name == KNOWN_FAILURE


def _relaxes(answer) -> bool:
    try:
        return answer in RELAXING
    except TypeError:
        return False


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
        # Since when each capability that is not off has stood where it stands, and whether the
        # last read of the arming table failed (Arming.read).
        self._since, self._unreadable = {}, False
        # v0.6.14: when a read that worked last found each capability stored on or watched standing
        # weaker than that - watched, read down by the policy, or held back - which nothing stored says.
        self._down_at = {}
        self._code = {}
        # {record: {(point, capability, word)}}: the answers taken this tick that lead to a send, with
        # the word each was where it was one (an Alternative), for the claim to pay (`claim`).
        self._acted = {}
        self._noted = set()
        # (capability, record) a kept-on capability's hook raised for: passed over for it (K8).
        self._skipped = set()
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
            self._states, self._since, self._unreadable = self.arming.read()
            self._at = now
            if not self._unreadable:
                for capability in self._since:
                    if self._states.get(capability, ArmingState.OFF) != ArmingState.ARMED:
                        self._down_at[capability] = now
        return self._states

    def _code_of(self, definition):
        """A capability's code, made once. One that reads the state is given its own view of it
        (state.Scoped), through an optional `bind`: its choices, its rules, its admission rows, and
        one write - its own words counted, only while this runtime has it on."""
        if definition.id not in self._code:
            code = definition.make(self.paths)
            bind = _own(code, "bind")
            if bind is not None:
                capability = definition.id
                bind(self.state.scoped(capability, on=lambda: self._states.get(capability) == ArmingState.ARMED))
            self._code[definition.id] = code
        return self._code[definition.id]

    def action(self, definition):
        """The code of `definition`, an action, made once for this process: for the surface a person
        starts what it does from. Core never asks an action (`ask` reaches routes alone)."""
        if definition.kind != CapabilityKind.ACTION or self.registry.get(definition.id) is not definition:
            raise ValueError("not an action of this registry")
        return self._code_of(definition)

    def _tripped(self, definition, record=None) -> None:
        """A hook of `definition`'s raised: off from here on - or, kept on (K8), noted, and passed
        over for `record` alone; a point with no record skips only the call it raised in."""
        if self.arming.trip(definition.id, OffReason.HOOK_EXCEPTION) or not self.arming.kept(definition.id):
            self._states[definition.id] = ArmingState.OFF
            return
        key = record.get("interruption_id") if isinstance(record, dict) else None
        if isinstance(key, str):
            if len(self._skipped) >= NOTED_LIMIT:
                self._skipped.clear()
            self._skipped.add((definition.id, key))

    # ------------------------------------------------------------------ asking
    def wants(self, point) -> bool:
        """Whether a capability registered at `point` is on or watched now (core's Plug.wants). With
        none there, nothing is read; a state that cannot be read has every capability off
        (arming.py), so nothing is wanted."""
        definitions = self.registry.at(point)
        if not definitions:
            return False
        states = self.states()
        return any(states.get(definition.id, ArmingState.OFF) != ArmingState.OFF
                   for definition in definitions)

    def ask(self, point, *arguments):
        """The answer at `point`: an armed capability's, or NULL's."""
        definitions = self.registry.at(point)
        if not definitions:
            return getattr(NULL, HOOKS[point])(*arguments)
        states = self.states()
        record = arguments[SENDING[point]] if point in SENDING else None
        if point == Point.SCHEDULE and isinstance(record, dict) and record.get("state") == SUBMISSION_UNKNOWN:
            again = self._send_again(record, states)
            if again is not None:
                return again
        relaxing = point == Point.GATES and _known_failure(arguments[0]) and isinstance(record, dict)
        admission = self._admission_of(record) if relaxing else None
        key = record.get("interruption_id") if isinstance(record, dict) else None
        chosen = chooser = None
        for definition in definitions:
            state = states.get(definition.id, ArmingState.OFF)
            if state == ArmingState.OFF or (definition.id, key) in self._skipped:
                continue
            try:
                answer = getattr(self._code_of(definition), HOOKS[point])(*arguments)
            except Exception:
                self._tripped(definition, record)
                continue
            if (answer is DEFER or (point == Point.SENDER and answer is arguments[-1])
                    or not self._takes(definition, point, answer, arguments, admission)):
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
                    if relaxing and answer in HELD_AT_CEILING:
                        return Alternative.HOLD          # it waits for a unit, and does not end
                    continue
            chosen, chooser = answer, definition
        if chooser is None:
            if relaxing and self._unsure(record, admission):
                return Alternative.HOLD
            return getattr(NULL, HOOKS[point])(*arguments)
        if point == Point.ADMISSION and not self._remember(chooser, record, chosen):
            return getattr(NULL, HOOKS[point])(*arguments)
        if relaxing and _relaxes(chosen) and not self._first(chooser, chosen, arguments, admission):
            return getattr(NULL, HOOKS[point])(*arguments)
        if point in SENDING:
            self._acted.setdefault(record.get("interruption_id"), set()).add(
                (point, chooser.id, _word(chosen, point)))
        self._once(JournalCode.ACTED, chooser, point, chosen, record)
        return chosen

    def _send_again(self, record, states):
        """Keep on's Send again at P7 (v0.6.14): RESEND for an uncertain submission, from the kept-on
        capability that paid for its send (arming.Arming.resender), where it stands on and has a unit
        left; watched, only journalled. None where none answers: the capabilities' own hooks are asked."""
        try:
            found = self.arming.resender(record, states)
        except Exception:
            return None
        if found is None:
            return None
        definition, state = found
        key = record.get("interruption_id")
        if (definition.id, key) in self._skipped:
            return None
        if state == ArmingState.SHADOW:
            self._once(JournalCode.WOULD_HAVE, definition, Point.SCHEDULE, Alternative.RESEND, record)
            return None
        if self._ceiling(definition, record) is not None:
            self._once(JournalCode.CEILING, definition, Point.SCHEDULE, Alternative.RESEND, record)
            return None
        self._acted.setdefault(key, set()).add((Point.SCHEDULE, definition.id, Alternative.RESEND))
        self._once(JournalCode.ACTED, definition, Point.SCHEDULE, Alternative.RESEND, record)
        return Alternative.RESEND

    # ------------------------------------------------------------------ taking failures up
    def _takes(self, definition, point, answer, arguments, admission) -> bool:
        """Whether `definition`'s `answer` is one to take at all: one core would carry out
        (`_taken`); at P17, one core offered, for a failure from after the capability was turned on
        or watched; at P3, a word that relaxes only at known_failure, and only from the capability
        that took the record up with that very word."""
        if not _taken(point, answer):
            return False
        if point == Point.ADMISSION:
            facts = arguments[0]
            try:
                offered = answer in facts["takes"]
            except Exception:                        # no `takes` core handed over: nothing offered
                return False
            return offered is True and self._since_armed(definition, facts)
        if point == Point.GATES and _relaxes(answer):
            if admission is None:
                return False
            row, _failed = admission()
            return (row is not None and row["capability"] == definition.id and row["answer"] == answer
                    and self._on_since_taken(definition, row))
        return True

    def _since_armed(self, definition, facts) -> bool:
        """Whether the failure `facts` describe completed once `definition` stood where it stands
        now: turning a capability on, or watching it, never reaches back to failures from before."""
        since = self._since.get(definition.id)
        completed = facts.get("completed_at") if isinstance(facts, dict) else None
        numbers = all(isinstance(value, (int, float)) and not isinstance(value, bool)
                      for value in (since, completed))
        return numbers and completed >= since

    def _on_since_taken(self, definition, row) -> bool:
        """Whether `definition` has stood on ever since it took up the failure `row` remembers
        (v0.6.14): not moved since - turned off, watched or turned on again, which its stored `since`
        says - and not read by this runtime as standing weaker since, as the policy's ForceShadow or
        AllowedCapabilities reads it, which nothing stored says. Otherwise what it took up ends unsent
        at its next look, however briefly it stood so and whether or not that look fell inside it."""
        since, taken = self._since.get(definition.id), row.get("created_at")
        numbers = all(isinstance(value, (int, float)) and not isinstance(value, bool)
                      for value in (since, taken))
        return numbers and taken >= since and taken >= self._down_at.get(definition.id, float("-inf"))

    def _admission_of(self, record):
        """The admission row of `record`, read once and only if something asks: (row or None,
        whether the read failed)."""
        memo = []

        def admission():
            if not memo:
                try:
                    memo.append((self.state.admission(record.get("interruption_id")), False))
                except StateError:
                    memo.append((None, True))
            return memo[0]
        return admission

    def _unsure(self, record, admission) -> bool:
        """Whether a record core never recovers alone that nothing took up again is one this runtime
        could not look at: the arming read or its admission read failed. It waits then, bounded by
        core's day on the clock (ladder.ADMITTED_MAX_SECONDS); only reads that worked end it."""
        if record.get("category") not in failures.ADMISSIBLE:
            return False
        return self._unreadable or admission()[1]

    def _remember(self, definition, facts, answer) -> bool:
        """P17's answer taken: which capability took the failure up, with which word - and the rule
        it rests on, or the failure's shape for one that samples. A write that fails takes nothing
        up: NULL's answer."""
        code = self._code_of(definition)
        rule = None
        rule_for = _own(code, "rule_for")
        if rule_for is not None:
            try:
                found = rule_for(facts, answer)
            except Exception:
                self._tripped(definition, facts)
                return False
            rule = found if type(found) is int else None
        shape = ({name: facts.get(name) for name in ("code", "status", "form", "has_message")}
                 if definition.samples else None)
        try:
            return self.state.admit(facts.get("interruption_id"), definition.id, answer, rule_id=rule,
                                    shape=shape, at=self.clock())
        except StateError:
            return False

    def _first(self, definition, answer, arguments, admission) -> bool:
        """The first time core goes on with a record `definition` took up: its code's `taken`, if it
        has one, and what it keeps of it written with the mark, once. False where `taken` raised:
        that trips it, and costs its answer."""
        row, _failed = admission()
        taken = _own(self._code_of(definition), "taken")
        if row is None or row["sampled"] or taken is None:
            return True
        try:
            kept = taken(Point.GATES, answer, *arguments)
        except Exception:
            self._tripped(definition, arguments[1] if len(arguments) > 1 else None)
            return False
        kept = kept if isinstance(kept, dict) else {}
        try:
            self.state.taken(row["interruption_id"], definition.id, kept.get("code"),
                             sample=kept.get("sample"), at=self.clock())
        except StateError:
            pass                                     # kept the next time core goes on with it
        return True

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
        hold a claim of core's own words. Each is handed over with the words it answered there
        (v0.6.14), for the ledger to check what only a resend or a Send now needs.

        A ledger that breaks is two different things. On a claim of core's own it costs its
        answer, as any hook's failure does, and core claims as it would with no plug. On a claim
        that carries a capability's answer, that answer could not be paid for, so the claim is
        held and nothing of it is sent; core takes back whatever the ledger had written."""
        key = record.get("interruption_id") if isinstance(record, dict) else None
        acted = {}
        for point, capability, word in self._acted.pop(key, ()):
            if point in carried:
                words = acted.setdefault(capability, set())
                if word in ANSWERS:
                    words.add(Alternative(word))
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
            backend = backend if backend is not None else measure.live_backend(self.paths)
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
            backend = measure.live_backend(self.paths)
        return measure.complete(measurement, verdict, note, backend=backend,
                                directory=self._evidence_dir, clock=self.clock)
