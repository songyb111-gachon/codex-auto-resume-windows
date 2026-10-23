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

Two capabilities' answers for one record that cannot both be carried (v0.6.17, issue #42). CONFLICTS lists each such
pair of answers: one taken at an earlier point for a record this tick, and one at a later point for the same record
that core could not carry with it. There is one way to settle them, SPLIT: the later answer is not taken. Its
capability stands aside for that record, and the journal says so - an `overruled` line on it whose answer names the
capability it stood aside for, and whose reason says why, where its code said (`carries`). Each goes on serving its
own cases; nothing is shown on the Dashboard for a split. Only an armed answer is overruled: a watched capability's
answer is a would-have, as always.

The earlier answer is never the one dropped: core has already taken it when the later point is asked (P16's route is
handed to the dispatch that then asks P5 and P15), so dropping it here would leave core carrying an answer nobody pays
for. A line that settles any other way is refused where CONFLICTS is made (`_conflicts`), and is settled as a split
if one is ever put there afterwards.

A capability whose code has `carries(word)` is asked first whether it can carry its answer together with the earlier
one, the word that was: True, and there is no conflict - both are taken and paid for; anything else, and it stands
aside, with that answer as the reason where it is one of the statement's warning words.

Core carries P16's TO_SESSION only through its own backend, with its marker, and QUEUE_FOR_OPEN that way or through
a channel the plug named under a client id it named (core's engine/foropen._not_for_open): anything else for that
same send left the record waiting - notLoaded, held_by_other_session - with nothing sent and the P16 answer journalled
as acted. That pair is a split: the goal continuation's channel stands aside for such a send, and so does marker-free
continuation - except for QUEUE_FOR_OPEN where MQO passed, which it carries with no marker (engine/markerfree.carries);
both serve every send of a conversation the app holds as before.

Two answers at one point that serve different sends (v0.6.17, #47 P-6). Core asks P15 for a route that takes words
with the record saying `route` (core's engine/routes._silent), and takes only SILENT there; so here too only SILENT is
an answer at such an ask (`_takes`), and marker-free continuation's CLIENT_ID - an answer only a channel's send carries
- is passed over there as DEFER would be: never journalled as acted, never paid. Continue with no words serves the
routes, marker-free continuation every channel send that carries words; a silent turn carries no words, so no marker.

Several conversations at once beside a channel (v0.6.17, #47 P-7). Core pools a channel's send only where the channel
says it may wait beside others (its `pools()`, core's domain/plug.Guarded.sender): marker-free continuation says so
where MQP passed on the Codex in force. Where a channel cannot, its send goes inline, one at a time, and
parallel_dispatch is journalled as overruled for that record, naming the channel's capability and why (`_alone`).
parallel_dispatch is journalled as acted for a record only once a claim that pooled it committed (`moved`), never for
a tick that pooled nothing.

Taking failures up (v0.6.14, stage 3b). At P17 an answer is taken only if core offered it - one of
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

from codex_auto_resume import continuation, failures, machine
from codex_auto_resume.domain.plug import (ALTERNATIVES, ANSWERS, DEFER, HOOKS, NULL, QUEUED, RECORD_MOVES,
                                           RESTRICTIONS, TAKE_UP, Alternative, Point, RecordMove)
from codex_auto_resume.domain.plughands import RECORDS_LIMIT, kinds_of, widening_of, workers

from .arming import Arming
from .codex import headless
from .engine import chat, foropen, sessions, silent
from .ledger import ClaimLedger, ceiling_reached
from .registry import REGISTRY
from .state import AdvancedState, StateError
from .state.schema import HEADLESS_CAPABILITIES
from .vocabulary import (TRIPWIRES, ArmingState, ArmingWarning, CapabilityKind, ContinuationReason, JournalCode,
                         KeepReason, OffReason, OverrideKind, PromptReason)

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
# Core's word for a queued item it took back, and (v0.6.15-beta) the reason one queued for opening was taken back
# because Codex did not run it when the conversation was opened (core's engine/foropen.py).
WITHDRAWN_UNCONFIRMED = "withdrawn_unconfirmed"
NOT_DELIVERED_ON_OPEN = "not_delivered_on_open"
# Keep going's capability, whose continuations are counted as used at SENT.
KEEP_GOING = "keep_going"
# The reasons a start route was not named that nothing else in the journal says (v0.6.16-beta.3): a
# turn off has its own line, a watched answer its would-have; held back by Codex or a policy has none.
HELD_WORDS = frozenset({"compat_unknown", "engine_unknown", "policy", "refused", "off"})
# How two answers of CONFLICTS are settled (v0.6.17): the later stands aside - the one way there is.
SPLIT = "split"
# The state a claimed record moves to first (core's machine), where a pooled claim is known to have committed.
SUBMITTING = "submitting"


def _route_ask(record) -> bool:
    """Whether P15 is asked for a route that takes words (core's engine/routes._silent, v0.6.17): the record says
    `route`, True itself. There core takes SILENT alone."""
    return isinstance(record, dict) and record.get("route") is True


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
            # A route core resumes the conversation with, or (v0.6.15-beta) QUEUE_FOR_OPEN: core's own send left in
            # Codex's queue for when the conversation is opened - or (v0.6.16-beta.4) TO_SESSION, for another Codex
            # session holding it to take.
            if isinstance(answer, str):
                return answer in (Alternative.QUEUE_FOR_OPEN, Alternative.TO_SESSION)
            return callable(getattr(answer, "resume", None))
    except Exception:                              # unhashable, refused, a `send` that raises
        return False
    return True                                    # the tick's answer is not read


# The points core never asks a record of this edition's own at (v0.6.14): its words, its channel, how it is
# carried and a route for it are core's alone - the person's words, sent as they are, by `codex queue`.
OWN_RECORD_POINTS = frozenset({Point.TEXT, Point.SENDER, Point.DELIVERY, Point.UNLOADED})
# What each move of one is counted as, in its capability's own words (registry.RESET_MESSAGE.codes).
MOVE_CODES = {RecordMove.SENT: "sent", RecordMove.DELIVERED: "delivered", RecordMove.UNPROVEN: "unknown",
              RecordMove.NOT_STARTED: "not_started"}


def _own_record(record) -> bool:
    """Whether `record` is one of this edition's own records (P2) rather than one of core's."""
    return isinstance(record, dict) and "record_id" in record and "interruption_id" not in record


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


def _not_ordinary(point, answer) -> bool:
    """Whether `answer` at `point` keeps a send from going core's ordinary way - its own backend, its marker: any
    channel at P5 (core's own backend is never taken as an answer) and a client id at P15. Words for no marker through
    core's backend (P15's SILENT) core already sends with its marker, and are left as they are."""
    if point == Point.SENDER:
        return True
    try:
        return point == Point.DELIVERY and answer == Alternative.CLIENT_ID
    except Exception:
        return False


def _conflicts(lines) -> tuple:
    """`lines` as CONFLICTS holds them, each checked: an earlier point, the words its answer may be, the later points -
    every one asked after it - which of their answers core could not carry with it, and SPLIT. Anything else is
    refused (ValueError): an earlier answer core has already taken cannot be voided by a later one."""
    checked = []
    for line in lines:
        first, words, later, refuses, settled = line
        if settled != SPLIT:
            raise ValueError("a later answer cannot void one core has already taken: settle the pair as SPLIT")
        if first in later or not callable(refuses) or not words:
            raise ValueError("not a pair of an earlier and a later answer")
        checked.append((first, frozenset(words), frozenset(later), refuses, SPLIT))
    return tuple(checked)


# v0.6.17 (issue #42): the answers that cannot both be carried for one record - (the point an earlier answer was taken
# at, the words it may be, the later points, which of their answers core could not carry with it, SPLIT). P16's
# QUEUE_FOR_OPEN and TO_SESSION go only core's ordinary way (core's engine/foropen._not_for_open); P16 is asked before
# the dispatch asks P5 and P15.
CONFLICTS = _conflicts(((Point.UNLOADED, QUEUED, frozenset({Point.SENDER, Point.DELIVERY}), _not_ordinary, SPLIT),))


def _conflict(earlier, point, answer, carries=None):
    """The first of `earlier` (Runtime._earlier) that `answer` at `point` cannot be carried with - (entry, why: one of
    the statement's warning words or None) - or None. `carries` is the capability's own `carries(word)`, where its code
    has one: True, and that earlier answer is no conflict. Every conflict is settled as a split, whatever a line
    says."""
    for entry, (_first, _words, _later, refuses, _settled) in earlier:
        if not refuses(point, answer):
            continue
        why = None
        if carries is not None:
            try:
                why = carries(entry[2])
            except Exception:
                why = None
            if why is True:
                continue
        return entry, (why if isinstance(why, str) and why in tuple(ArmingWarning) else None)
    return None


def _restricts(answer) -> bool:
    try:
        return answer in RESTRICTIONS
    except TypeError:
        return False


def _preferred(point, chosen, answer, record, now) -> bool:
    """Whether `answer` is taken at `point` although an earlier capability's `chosen` was taken first (v0.6.17).

    A point is first wins, and this is its one exception: at P7, a person's Send now over an early look - where
    core would carry the Send now out, and only there. The person asked for the record to go as soon as it can.
    Core makes no early look at a postponement, which only Send now passes, so there EARLY taken first would
    send nobody and the request would stand unanswered until it lapsed. But core never carries a Send now out
    before a usage reset (domain/gates.py, gate_schedule), the very wait an early look exists for: there EARLY
    is what sends it soonest, and SEND_NOW taken in its place would hold it for the whole early window. So the
    record is put to core's own schedule gate for a Send now (quiet hours aside, which hold an early look too)."""
    return (point == Point.SCHEDULE and chosen is Alternative.EARLY and answer is Alternative.SEND_NOW
            and isinstance(record, dict) and machine.gate_schedule(record, now, forced=True)[0] == machine.PASS)


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
                 measure_cli=None, measure_ipc=None, measure_hands=None, evidence_dir=None, **arming):
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
        # {record: (capability, ...)}: the capabilities at P12 a claim that pooled the record paid, journalled as
        # acted once that claim is known to have committed (`moved`, v0.6.17).
        self._pooled = {}
        # v0.6.18: the capabilities whose words (P4) a committed claim carries, told once core moves it on (`moved`).
        self._texted = {}
        self._noted = set()
        # (capability, record) a kept-on capability's hook raised for: passed over for it (K8).
        self._skipped = set()
        self._records_turn = 0
        # Why the last start route asked (P9) named none, where a capability there was stored on or
        # watched (`start_held`); None where nothing was.
        self._start_held = None
        # The measurement harness's seams (measure.py). A person runs a measurement; production
        # opens a real one-turn session against the installed Codex and records to the source
        # tree, and a test gives a fake session and a temporary directory, so no test opens a
        # real Codex or writes into the repository.
        self._measure_session_factory = measure_session_factory
        self._measure_launcher = measure_launcher
        self._measure_backend = measure_backend
        self._measure_cli = measure_cli
        self._measure_ipc = measure_ipc
        self._measure_hands = measure_hands
        self._evidence_dir = evidence_dir

    # ------------------------------------------------------------------ standing
    def states(self, *, fresh=False, live=()) -> dict:
        now = self.clock()
        if fresh or self._at is None or not 0 <= now - self._at < REFRESH_SECONDS:
            self._states, self._since, self._unreadable = self.arming.read(live=live)
            self._at = now
            if not self._unreadable:
                for capability in self._since:
                    if self._states.get(capability, ArmingState.OFF) != ArmingState.ARMED:
                        self._down_at[capability] = now
                self._rearmed_silent()
        return self._states

    def _rearmed_silent(self) -> None:
        """v0.6.18: silent_continuation turned on again after REFUSED_BY_CODEX turned it off - a person's choice made
        since - is asked again: the process's refusal is forgotten, so it is not shown on while it answers DEFER until
        the watcher restarts. A refusal met again trips it again."""
        tripped = self.__dict__.get("_refused_tripped")
        since = self._since.get(silent.CAPABILITY)
        if (type(tripped) is float and self._states.get(silent.CAPABILITY) == ArmingState.ARMED
                and isinstance(since, (int, float)) and since >= tripped):
            headless.EMPTY_REFUSED = False
            self._refused_tripped = None

    def _code_of(self, definition):
        """A capability's code, made once. One that reads the state is given its own view of it
        (state.Scoped), through an optional `bind`: its choices, its rules, its admission rows, and
        one write - its own words counted, only while this runtime has it on."""
        if definition.id not in self._code:
            code = definition.make(self.paths)
            bind = _own(code, "bind")
            if bind is not None:
                capability = definition.id
                bind(self.state.scoped(capability, on=lambda: self._states.get(capability) == ArmingState.ARMED,
                                       verdict=self.arming.verdict,
                                       armed=lambda other: self._states.get(other) == ArmingState.ARMED))
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

    def start_route(self, request):
        """P9, asked where Codex has just started this plugin's MCP server (core's control/codexstart.py).

        v0.6.16-beta.3 (issue #31). What every capability here stands at is read afresh, and - for one
        stored on or watched - with a fresh check of Codex where the watcher's report cannot be used
        (Arming.read's `live`): that report is written only by a running watcher, and the watcher not
        running is the one case this point is for. Where none names a route, why is kept for core's
        line (`start_held`) and, where nothing else in the journal says it, written there as the
        capability's own `held`: a held-back start is a decision too."""
        definitions = self.registry.at(Point.START_ROUTE)
        self._start_held = None
        if not definitions:
            return NULL.start_route(request)
        self.states(fresh=True, live=frozenset(definition.id for definition in definitions))
        answer = self.ask(Point.START_ROUTE, request)
        if answer is DEFER:
            self._start_held = self._held_start(definitions)
        return answer

    def start_held(self):
        """Why the last start route asked named none, or None (core's Plug.start_held)."""
        return self._start_held

    def supervise(self, facts):
        """P13, asked by the launcher before it runs the watcher and once a watcher it ran has ended (v0.6.19,
        crash_restart). As at P9, what every capability here stands at is read afresh, with a fresh check of Codex
        where the watcher's report cannot be used - at sign-in no watcher has run for a while, and the watcher not
        running is the one case the start question is asked in (Arming.read's `live`)."""
        definitions = self.registry.at(Point.SUPERVISION)
        if not definitions:
            return NULL.supervise(facts)
        self.states(fresh=True, live=frozenset(definition.id for definition in definitions))
        return self.ask(Point.SUPERVISION, facts)

    def _held_start(self, definitions):
        """Why no capability at P9 named a route, as one word, for the first stored on or watched at
        the read; None where every one was stored off. A capability turned off on the way - at the
        read, or by a hook that raised as it was asked - already has its turn off journalled, and a
        watched one its would-have; one only held back - by what Codex is, or by a policy - or one on
        that named nothing core could carry out gets its `held` line here."""
        if self._unreadable:
            return "unreadable"
        for definition in definitions:
            word = self.arming.why.get(definition.id)
            if word is None:
                if definition.id not in self._since:
                    continue                                  # stored off: nothing of it was on
                if self._states.get(definition.id) == ArmingState.ARMED:
                    word = "refused"                          # asked, and named nothing core can carry out
                else:
                    word = OffReason.HOOK_EXCEPTION.value     # tripped off as it was asked
            if word in HELD_WORDS:
                try:
                    self.state.counted(definition.id, "held", at=self.clock())
                except StateError:
                    pass
            return word
        return None

    def ask(self, point, *arguments):
        """The answer at `point`: an armed capability's, or NULL's. A record of this edition's own (P2) is asked
        nothing at P4, P5, P15 or P16: its words are the person's, and core sends it as it is (v0.6.14).

        The first capability to answer is the one taken, in registry order, with one exception (`_preferred`):
        a person's Send now is preferred to an early look at P7 where core would carry it out (v0.6.17)."""
        definitions = self.registry.at(point)
        if point in OWN_RECORD_POINTS and _own_record(arguments[0]):
            return self._own_record_answer(point, arguments)
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
        # P16 in the watch (v0.6.15-beta): whether a continuation queued for opening stays queued. It was paid for at
        # its claim; nothing is spent or carried again, so neither a ceiling nor the claim is asked.
        kept = point == Point.UNLOADED and foropen.watching(record)
        # v0.6.17 (issue #42): what was taken earlier for this record that an answer here may not be carried with.
        earlier = self._earlier(key, point)
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
            conflict = _conflict(earlier, point, answer,
                                 _own(self._code_of(definition), "carries") if earlier else None)
            if conflict is not None:
                # Taken, core could carry neither: it stands aside for this record, and says for whom and why. Armed
                # answers only - a watched one is a would-have above, as always.
                self._paired(JournalCode.OVERRULED, definition, point, conflict[0][1], record, reason=conflict[1])
                continue
            if _restricts(answer):
                self._once(JournalCode.ACTED, definition, point, answer, record)
                return answer
            if chooser is not None and not _preferred(point, chosen, answer, record, self.clock()):
                continue
            if point in SENDING and not kept:
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
        if point == Point.SCHEDULE:
            self._not_taken(definitions, chooser, record, states)
        if point == Point.ADMISSION and not self._remember(chooser, record, chosen):
            return getattr(NULL, HOOKS[point])(*arguments)
        if relaxing and _relaxes(chosen) and not self._first(chooser, chosen, arguments, admission):
            return getattr(NULL, HOOKS[point])(*arguments)
        if point in SENDING and not kept:
            self._acted.setdefault(record.get("interruption_id"), set()).add(
                (point, chooser.id, _word(chosen, point)))
        if point == Point.SENDER:
            self._alone(chooser, chosen, record)
        self._once(JournalCode.ACTED, chooser, point, chosen, record)
        return chosen

    def _alone(self, chooser, channel, record) -> None:
        """v0.6.17 (#47 P-7): where P12 answered for `record` this tick and the channel `chooser` named for its send
        cannot wait beside others - its `pools()` answers anything but True, or it has none - core sends it inline,
        one at a time: the capability that answered P12 stood aside for this record, and the journal says for whom
        and why (an `overruled` line, the channel's warning word as the reason; no `pools` at all: no measurement
        covers its send at once, UNMEASURED). A resend is never pooled, so nothing is said of one."""
        entries = self._acted.get(record.get("interruption_id"), ())
        pooled = [capability for point, capability, _w in entries if point == Point.CONCURRENCY]
        if not pooled or any(point == Point.SCHEDULE and word == Alternative.RESEND for point, _c, word in entries):
            return
        try:
            pools = getattr(channel, "pools", None)
            why = pools() if callable(pools) else ArmingWarning.UNMEASURED
        except Exception:
            why = None
        if why is True:
            return
        reason = why if isinstance(why, str) and why in tuple(ArmingWarning) else None
        for capability in pooled:
            definition = self.registry.get(capability)
            if definition is not None:
                self._paired(JournalCode.OVERRULED, definition, Point.CONCURRENCY, chooser.id, record, reason=reason)

    def _earlier(self, key, point) -> tuple:
        """((entry, line), ...): each answer taken this tick for the record `key` - an `_acted` entry, (point,
        capability, word) - that a line of CONFLICTS says an answer at `point` may not be carried with. The tick
        forgets every answer taken (`tick`), and the claim pays for what is left (`claim`)."""
        found = []
        for line in CONFLICTS:
            first, words, later = line[:3]
            if point not in later:
                continue
            for entry in self._acted.get(key, ()):
                try:
                    if entry[0] == first and entry[2] in words:
                        found.append((entry, line))
                except TypeError:
                    continue
        return tuple(found)

    def _paired(self, code, definition, point, other, record, reason=None) -> None:
        """One journal line, once per record in a process, about `definition` and the capability `other`, which its
        answer names: `overruled` - it stood aside for that one, for `reason` where one is known."""
        key = (code, definition.id, point, other, record.get("interruption_id") if isinstance(record, dict) else None)
        if key in self._noted:
            return
        if len(self._noted) >= NOTED_LIMIT:
            self._noted.clear()
        self._noted.add(key)
        try:
            self.state.note(code, capability=definition.id, point=point, answer=other, reason=reason,
                            at=self.clock())
        except StateError:
            pass

    def _not_taken(self, definitions, chooser, record, states) -> None:
        """At P7, every capability on that has a `not_taken` and whose answer was not the one taken is told so
        (v0.6.14): early_reset lets go of a record another capability's EARLY looked at, so it does not hold it at
        its first yes (engine/earlyreset.py)."""
        for definition in definitions:
            if definition is chooser or states.get(definition.id, ArmingState.OFF) != ArmingState.ARMED:
                continue
            told = _own(self._code_of(definition), "not_taken")
            if told is None:
                continue
            try:
                told(record)
            except Exception:
                self._tripped(definition, record)

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
        if point == Point.DELIVERY and _route_ask(arguments[0]):
            # v0.6.17 (#47 P-6): a route's P15 takes SILENT alone; anything else is not an answer there.
            return answer is Alternative.SILENT
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
        afresh, then the capabilities that answer once a tick - each one that is on with an errand of
        its own, joined in the registry's order into the one errand core runs last in the tick
        (`_Errands`, v0.6.14); a watched one's is only journalled, never run."""
        self._acted.clear()
        self._pooled.clear()
        self._texted.clear()
        if not len(self.registry):
            return DEFER
        self.arming.sweep(view)
        states = self.states(fresh=True)
        errands = []
        for definition in self.registry.at(Point.TICK):
            state = states.get(definition.id, ArmingState.OFF)
            tend = (_own(self._code_of(definition), "tend")
                    if state != ArmingState.ARMED and definition.id in HEADLESS_CAPABILITIES else None)
            if tend is not None:
                # v0.6.18: what a run kind turned off or watched still owes what it started - a live run's Stop
                # handed on and its end written, a model put back (engine/headless.follow_up, engine/fallback.py):
                # its clean-up alone, never a turn of its own, whatever it stands at.
                try:
                    answer = tend(view)
                    run = None if answer is DEFER else getattr(answer, "run", None)
                except Exception:
                    continue                             # already off or watched; the next tick tends it again
                if callable(run):
                    errands.append((definition, answer))
                continue
            if state == ArmingState.OFF:
                continue
            try:
                answer = self._code_of(definition).tick(view)
                run = None if answer is DEFER else getattr(answer, "run", None)
            except Exception:
                self._tripped(definition)
                continue
            if not callable(run):
                continue
            if state == ArmingState.SHADOW:
                self._once(JournalCode.WOULD_HAVE, definition, Point.TICK, Point.TICK, None)
                continue
            self._once(JournalCode.ACTED, definition, Point.TICK, Point.TICK, None)
            errands.append((definition, answer))
        return _Errands(self, errands) if errands else DEFER

    def records(self, view):
        """P2: the records of this edition's own that core is to try, or to watch (v0.6.14): every message in
        flight, whatever its capability stands at now - core watches each to its end - but one claimed whose launch
        never began, which is handed back, and what each capability that is on answers. Core checks what it is handed (domain/plughands.records_of) and carries each out
        itself. A watched capability is not asked: it holds no message (arming.py, sweep)."""
        from .engine import continued, promptqueue
        from .engine.resetmessage import handed
        from .state.resets import UNLAUNCHED_AFTER
        found, seen = [], set()
        try:
            # A claim whose launch never began is handed back first (state/resets.release_unlaunched).
            self.state.release_unlaunched(at=self.clock())
            self.state.release_unlaunched_continuations(UNLAUNCHED_AFTER, at=self.clock())
            self.state.release_unlaunched_prompts(UNLAUNCHED_AFTER, at=self.clock())
            self.state.release_unlaunched_chats(UNLAUNCHED_AFTER, at=self.clock())
        except StateError:
            pass                                         # tried again at the next P2
        try:
            flying = [handed(rule) for rule in self.state.messages_in_flight()]
            flying += [continued.handed(row) for row in self.state.continuations_in_flight()]
            flying += [promptqueue.handed(row) for row in self.state.prompts_in_flight()]
            # v0.6.19: and the chat's messages in flight, each taken back once three minutes pass untaken.
            flying += [chat.watched(row, self.clock()) for row in self.state.chats_in_flight()]
        except StateError:
            flying = []
        # P2's eight (v0.6.15-beta): those in flight first, the longest in flight first, from a place that moves on
        # each tick when there are more than core takes; then one due of each capability in the registry's order, then
        # the rest - so none waits behind another for more than a tick.
        flying = sorted((record for record in flying if record is not None), key=lambda record: record["sent_at"] or 0)
        if len(flying) > RECORDS_LIMIT:
            start = (self._records_turn * RECORDS_LIMIT) % len(flying)
            flying = flying[start:] + flying[:start]
        self._records_turn += 1
        states = self.states()
        answers = [flying]
        for definition in self.registry.at(Point.RECORDS):
            if states.get(definition.id, ArmingState.OFF) == ArmingState.SHADOW:
                self._watched_records(definition, view)
                continue
            if states.get(definition.id, ArmingState.OFF) != ArmingState.ARMED:
                continue
            try:
                answer = self._code_of(definition).records(view)
            except Exception:
                self._tripped(definition)
                continue
            if isinstance(answer, (list, tuple)):
                answers.append(list(answer))
        due = answers[1:]
        answers = [flying, [answer[0] for answer in due if answer], [record for answer in due for record in answer[1:]]]
        held = self._holders(states)
        for answer in answers:
            for record in answer:
                key = record.get("record_id") if isinstance(record, dict) else None
                if key is not None and any(holds(record) for holds in held):
                    continue                                 # held back this tick (usage_pause's `holds`)
                if key is not None and key not in seen:
                    seen.add(key)
                    found.append(record)
        return found or DEFER

    def _holders(self, states) -> list:
        """The `holds` of every capability on that has one (v0.6.16-beta.3, usage_pause): each says whether a record
        of the edition's own waiting is held back from core this tick. One that raises holds nothing."""
        found = []
        for definition in self.registry:
            if states.get(definition.id, ArmingState.OFF) != ArmingState.ARMED:
                continue
            holds = _own(self._code_of(definition), "holds")
            if holds is not None:
                def guarded(record, holds=holds):
                    try:
                        return holds(dict(record)) is True
                    except Exception:
                        return False
                found.append(guarded)
        return found

    def eligibility(self):
        """P19 (v0.6.16-beta.3): the Widening words every capability on at ELIGIBILITY names, together - or NULL's DEFER.
        A watched one is only journalled, once: what it would have widened is never taken. Nothing is read with none
        registered there."""
        definitions = self.registry.at(Point.ELIGIBILITY)
        if not definitions:
            return DEFER
        states = self.states()
        found = set()
        for definition in definitions:
            state = states.get(definition.id, ArmingState.OFF)
            if state == ArmingState.OFF:
                continue
            try:
                answer = widening_of(self._code_of(definition).eligibility())
            except Exception:
                self._tripped(definition)
                continue
            if not answer:
                continue
            if state == ArmingState.SHADOW:
                self._once(JournalCode.WOULD_HAVE, definition, Point.ELIGIBILITY, Point.ELIGIBILITY, None)
                continue
            self._once(JournalCode.ACTED, definition, Point.ELIGIBILITY, Point.ELIGIBILITY, None)
            found |= answer
        return frozenset(found) if found else DEFER

    def sessions(self):
        """P18 (v0.6.16-beta.4): the SessionKind words every capability on at SESSIONS names, together - or NULL's
        DEFER. A watched one is only journalled, once: the conversations it would have watched are never read."""
        definitions = self.registry.at(Point.SESSIONS)
        if not definitions:
            return DEFER
        states = self.states()
        found = set()
        for definition in definitions:
            state = states.get(definition.id, ArmingState.OFF)
            if state == ArmingState.OFF:
                continue
            try:
                answer = kinds_of(self._code_of(definition).sessions())
            except Exception:
                self._tripped(definition)
                continue
            if not answer:
                continue
            if state == ArmingState.SHADOW:
                self._once(JournalCode.WOULD_HAVE, definition, Point.SESSIONS, Point.SESSIONS, None)
                continue
            self._once(JournalCode.ACTED, definition, Point.SESSIONS, Point.SESSIONS, None)
            found |= answer
        return frozenset(found) if found else DEFER

    def _watched_records(self, definition, view) -> None:
        """P2 for a watched capability (v0.6.16-beta.3): each of its rows a person set up that would be handed core now -
        as its code decides it from the stored state, writing nothing (`watched_due`) - journalled once as what it would
        have sent, with the time; never handed, never sent, and nothing spent or read for it."""
        would = getattr(self._code_of(definition), "watched_due", None)
        if not callable(would):
            return
        try:
            keys = would(view)
        except Exception:
            return                                        # a watched one's look costs nothing, and trips nothing
        for key in keys or ():
            if isinstance(key, str):
                self._once(JournalCode.WOULD_HAVE, definition, Point.RECORDS, Point.RECORDS, {"interruption_id": key})

    def conversation_off(self, thread_id) -> None:
        """A person switched `thread_id` off, in the Dashboard, a model's tool or the command line (core's
        Plug.conversation_off): every message waiting for it ends cancelled, its words with it, at once - so
        switching it on again, paused or between two ticks, revives none (H5). One being sent is its watch's to
        end. What cannot be written now, P2 cancels when it finds the conversation off."""
        try:
            self.state.end_messages_in(thread_id, at=self.clock())
            # v0.6.15-beta: and every continuation of the edition's own still waiting there, and keep going for it.
            self.state.end_continuations(ContinuationReason.CONVERSATION_OFF, thread_id=thread_id, at=self.clock())
            self.state.stop_keep_going(KeepReason.CONVERSATION_OFF, thread_id=thread_id, at=self.clock())
            self.state.end_prompts(PromptReason.CONVERSATION_OFF, thread_id=thread_id, at=self.clock())
        except StateError:
            pass

    def moved(self, record, state):
        """P14: core has moved `record` to `state`. Its one use is a tripwire's (arming.py): a
        capability that tripped is off from here on, not from the next tick."""
        if not len(self.registry):
            return DEFER
        if _own_record(record) and state in RECORD_MOVES:
            return self._record_moved(record, RecordMove(state))
        if state == SUBMITTING and isinstance(record, dict):
            self._pooled_acted(record)
            self._words_sent(record)
        if (self._not_delivered_on_open(record, state) or self._not_dispatched_by_session(record, state)
                or self._refused_by_codex()):
            self.states(fresh=True)
        if self.arming.moved(record, state):
            self.states(fresh=True)
        return DEFER

    def _words_sent(self, record) -> None:
        """v0.6.18: a claim that carried a capability's words (P4) committed - core moved it to submitting - so the
        capability is told, through its optional `words_sent`, what it may now take as said (subagent_parent's lines:
        told once only when they go, never when a claim held after P4 sent core's own words instead)."""
        for capability in self._texted.pop(record.get("interruption_id"), ()):
            definition = self.registry.get(capability)
            if definition is None:
                continue
            told = _own(self._code_of(definition), "words_sent")
            if told is not None:
                try:
                    told(record)
                except Exception:
                    pass                                 # nothing kept: the lines are told again at the next send

    def _pooled_acted(self, record) -> None:
        """v0.6.17 (#47 P-7): a claim that pooled `record` committed - core moved it to submitting - so the
        capability at P12 that it paid acted for it, and the journal says so: once per record, never for a tick."""
        for capability in self._pooled.pop(record.get("interruption_id"), ()):
            definition = self.registry.get(capability)
            if definition is not None:
                self._once(JournalCode.ACTED, definition, Point.CONCURRENCY, None, record)

    def _not_delivered_on_open(self, record, state) -> bool:
        """The tripwire NOT_DELIVERED_ON_OPEN (v0.6.15-beta): core took back a continuation queued for opening because
        the conversation was opened and Codex did not run it - the capability whose override queued it turns off, or,
        kept on, notes it (K8). Whether it was turned off."""
        if (state != WITHDRAWN_UNCONFIRMED or not isinstance(record, dict)
                or record.get("withdraw_reason") != NOT_DELIVERED_ON_OPEN):
            return False
        key = record.get("interruption_id")
        try:
            found = self.state.override(key, foropen.CAPABILITY)
        except StateError:
            return False
        if found is None or found.get("kind") != OverrideKind.QUEUE_FOR_OPEN:
            return False
        return self.arming.trip(foropen.CAPABILITY, OffReason.NOT_DELIVERED_ON_OPEN)

    def _own_record_answer(self, point, arguments):
        """P5 and P15 for a record of this edition's own (v0.6.19): a chat message goes through chat's own
        channel with no marker while chat is on (engine/chat.py), and one in flight is proven by its client id whatever
        chat stands at now - it was sent with no marker; everything else of the edition's own is asked nothing there,
        as before - NULL's answer."""
        record = arguments[0]
        armed = self.states().get(chat.CAPABILITY) == ArmingState.ARMED
        if point == Point.DELIVERY or (point == Point.SENDER and armed):
            definition = self.registry.get(chat.CAPABILITY)
            try:
                owned = definition is not None and self.state.chat_by_record(record.get("record_id")) is not None
            except Exception:
                owned = False
            if owned:
                code = self._code_of(definition)
                return code.sender(record, arguments[-1]) if point == Point.SENDER else code.delivery(record)
        return getattr(NULL, HOOKS[point])(*arguments)

    def _not_dispatched_by_session(self, record, state) -> bool:
        """The tripwire NOT_DISPATCHED_BY_SESSION (v0.6.16-beta.4): core took back a continuation sent to a
        conversation another Codex session held (its gate vector's `session` pass, core's own column) because that
        session did not take it within the delivery window - stored as not_delivered_on_open, the word every schema-5
        reader knows (core's engine/tosession.py). other_sessions, whose answer sent it, turns off, or - never kept
        on (keepable) - would note it. Whether it was turned off."""
        if (state != WITHDRAWN_UNCONFIRMED or not isinstance(record, dict)
                or record.get("withdraw_reason") != NOT_DELIVERED_ON_OPEN):
            return False
        try:
            gate = machine.decode_gates(record.get("gate_eval")).get("thread_available")
        except Exception:
            return False
        if gate != (machine.PASS, machine.SESSION):
            return False
        return self.arming.trip(sessions.CAPABILITY, OffReason.NOT_DISPATCHED_BY_SESSION)

    def _refused_by_codex(self) -> bool:
        """The tripwire REFUSED_BY_CODEX (v0.6.16-beta.4): a route met Codex refusing a turn with no input
        (codex/headless.EMPTY_REFUSED) - silent_continuation turns off, once, where it is registered and on. Whether it
        was turned off."""
        if not headless.EMPTY_REFUSED or self.__dict__.get("_refused_tripped") or self.registry.get(
                silent.CAPABILITY) is None:
            return False
        self._refused_tripped = float(self.clock())
        return self.arming.trip(silent.CAPABILITY, OffReason.REFUSED_BY_CODEX)

    def _record_moved(self, record, move):
        """P14 for a record of this edition's own (v0.6.14): its rule and its record as core says they are now,
        counted in its capability's words, and - unproven a day after it was sent - its capability turned off,
        as a send it paid for gone submission_unknown does (K7)."""
        try:
            moved = self.state.record_moved(record.get("record_id"), move, gate=record.get("gate"),
                                            reason=record.get("reason"), at=self.clock(),
                                            queue_id=record.get("queue_id"))
            if moved is None:
                # v0.6.15-beta: one of the edition's own continuations (state/continuations.py).
                moved = self.state.continuation_moved(record.get("record_id"), move, at=self.clock(),
                                                      queue_id=record.get("queue_id"))
            if moved is None:
                # or a queued prompt's occurrence (state/prompts.py).
                moved = self.state.prompt_moved(record.get("record_id"), move, at=self.clock(),
                                                queue_id=record.get("queue_id"))
            if moved is None:
                # or (v0.6.19) a chat message (state/chat.py).
                moved = self.state.chat_moved(record.get("record_id"), move, reason=record.get("reason"),
                                              at=self.clock())
        except StateError:
            return DEFER                                 # repaired from the next P2 (resetmessage.records)
        if moved is None:
            return DEFER
        if move == RecordMove.SENT and moved["capability"] == KEEP_GOING:
            try:
                # Keep going counts a continuation as used at its send's start (engine/keepgoing.py).
                self.state.keep_going_used(record.get("thread_id"), at=self.clock())
            except StateError:
                pass
        code = MOVE_CODES.get(move)
        if code is not None:
            try:
                self.state.counted(moved["capability"], code, at=self.clock())
            except StateError:
                pass
        if moved["trip"]:
            self.arming.trip(moved["capability"], OffReason.SUBMISSION_UNKNOWN)
            self.states(fresh=True)
        return DEFER

    def partition(self, records):
        """P12 (v0.6.15-beta): how many sends may wait for their receipts at once - an armed capability's whole
        number, which core holds to 2 to 4 (domain/plughands.workers), or NULL's. Each due record its ceilings leave a
        unit for is remembered as acted at CONCURRENCY, so the claim of a pooled send pays exactly one (`claim`).
        The journal says it acted only for a record whose pooled claim committed (`moved`, v0.6.17): an answer here
        pools nothing by itself."""
        definitions = self.registry.at(Point.CONCURRENCY)
        if not definitions or not isinstance(records, list):
            return DEFER
        states = self.states()
        for definition in definitions:
            state = states.get(definition.id, ArmingState.OFF)
            if state == ArmingState.OFF:
                continue
            try:
                answer = self._code_of(definition).partition(records)
            except Exception:
                self._tripped(definition)
                continue
            if workers(answer) == 1:
                continue
            if state == ArmingState.SHADOW:
                self._once(JournalCode.WOULD_HAVE, definition, Point.CONCURRENCY, answer, None)
                continue
            paid = [record for record in records if isinstance(record, dict)
                    and (definition.id, record.get("interruption_id")) not in self._skipped
                    and self._ceiling(definition, record) is None]
            if not paid:
                self._once(JournalCode.CEILING, definition, Point.CONCURRENCY, answer, None)
                continue
            for record in paid:
                self._acted.setdefault(record.get("interruption_id"), set()).add(
                    (Point.CONCURRENCY, definition.id, None))
            return answer
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
        if _own_record(record) and isinstance(record, dict) and "phase" in record:
            try:
                return self.ledger.record(connection, record, now)
            except Exception:
                return Alternative.HOLD                  # a record that cannot be paid for is not sent
        key = record.get("interruption_id") if isinstance(record, dict) else None
        acted = {}
        entries = self._acted.pop(key, ())
        if Point.CONCURRENCY in carried and not any(point == Point.CONCURRENCY for point, _c, _w in entries):
            return Alternative.HOLD                      # pooled, and nothing left to pay for it: one poll
        for point, capability, word in entries:
            if point in carried:
                words = acted.setdefault(capability, set())
                if word in ANSWERS:
                    words.add(Alternative(word))
        try:
            answer = self.ledger.claim(connection, record, now, acted)
        except Exception:
            if acted:
                return Alternative.HOLD
            raise
        if Point.TEXT in carried and answer is not Alternative.HOLD:
            self._texted[key] = tuple(capability for point, capability, _w in entries if point == Point.TEXT)
        if Point.CONCURRENCY in carried and answer is not Alternative.HOLD:
            # Journalled once the claim committed (`moved`): this runs inside its transaction.
            self._pooled[key] = tuple(capability for point, capability, _w in entries if point == Point.CONCURRENCY)
        return answer

    # ------------------------------------------------------------------ the measurement harness
    def run_measurement(self, measurement, thread=None, may_spend=False):
        """Run one measurement the person asked for, and record what it found (measure.py).

        The session and the launcher are the runtime's own seams: production opens a real
        one-turn session against the installed Codex and writes to the source tree's evidence
        directory, and a test gives fakes and a temporary directory. Nothing here runs unless a
        surface was asked for it by a person.

        `thread` is an optional real throwaway conversation the owner points a measurement at,
        validated as a Codex thread id and used in the calls the probe makes, never written into
        the record. `may_spend` is the person's second yes that MR may spend one real reset credit.

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
        # v0.6.16-beta.3: the read-only probes' seams - the engine's own CLI help (MAWS/MCLOUD) and the
        # Desktop's IPC pipe (MIPC). Built from the same backend, so they are of the Codex the record names.
        cli = self._measure_cli if self._measure_cli is not None else measure.live_cli(backend, self.paths)
        ipc = self._measure_ipc if self._measure_ipc is not None else measure.live_ipc()
        # v0.6.19: the groundwork's probes' hands (measure.live_hands), of the same backend.
        hands = (self._measure_hands if self._measure_hands is not None
                 else measure.live_hands(backend, self.paths))
        return measure.run(measurement, session_factory=session_factory,
                           launcher=launcher, backend=backend, thread=thread, may_spend=may_spend,
                           directory=self._evidence_dir, clock=self.clock, cli=cli, ipc=ipc, hands=hands)

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


class _Errands:
    """The errands of every capability on at P8, joined: core runs this once, last in the tick, with its guards
    (domain/plughands.Errand), and each errand is run in the registry's order. One that raises trips its own
    capability alone; one that asks for a tripwire - a spend whose result cannot be known (engine/credits.py) - has
    its capability turned off, or, kept on, noted (K7, K8)."""
    __slots__ = ("runtime", "errands")

    def __init__(self, runtime, errands):
        self.runtime, self.errands = runtime, list(errands)

    def run(self, guard):
        runtime = self.runtime
        for definition, errand in self.errands:
            try:
                asked = errand.run(guard)
            except Exception:
                runtime._tripped(definition)
                continue
            reason = asked.get("trip") if isinstance(asked, dict) else None
            if reason in TRIPWIRES:
                runtime.arming.trip(definition.id, reason)
                runtime.states(fresh=True)
        return None
