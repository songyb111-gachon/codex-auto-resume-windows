# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""The capability registry: every capability this edition can offer, and what each one is.

A capability is a definition here plus its code. The definition says everything a person is
asked to agree to and everything the plug holds it to:

* `id` - its closed name, the one every table, surface and journal line uses;
* `kind` - a ROUTE, which answers at plug points, or an ACTION, which answers at none: core never
  asks an action, it sends nothing to Codex and spends nothing, so it has no points, stands on no
  compatibility capability, rests on no measurement and has no ceilings - its own bounds are its
  code's, and a person in the Dashboard starts each thing it does (vocabulary.CapabilityKind);
* `points` - the plug points its code answers at (domain/plug.py), and no others;
* `revision` - the revision of its statement: the five fields in `statement.py`'s catalogs, in
  every language the product has a catalog for. Arming names the revision the person read, and a new revision turns the
  capability off until they have read that one (a tripwire, arming.py);
* `departs_from` - the standards it breaks (standards.py). Never empty: a capability that keeps
  every standard belongs in the standard edition, so the rule for which edition a capability is
  in is this field. Only the standard edition's standards may be named (standards.DEPARTABLE):
  family K is the advanced edition's own rules, which every capability keeps;
* `compat` - the Compatibility Registry capability it stands on. Its grade here is shown in the
  statement - FAILED_HERE, INCOMPATIBLE or UNKNOWN as a warning the person confirms - and a
  failure the person did not confirm turns it off (arming.py);
* `measurements` - the measurements its route rests on (measure.py), if any. One that failed, or
  has no pass for the Codex in force (measured.py), is a warning in its statement, never a
  reason to withhold it;
* `ceilings` - how many sends it may make in a day, overall and in one conversation. Beside them
  stands one global ceiling for every capability together, GLOBAL_HOURLY an hour, which a person
  may lower and never raise (state.AdvancedState.set_global_hourly). One conversation's ceiling is
  never above core's own five a day (CORE_DAILY_CAP) unless the capability says it departs from
  A20, the standard that sets them;
* `options` - the choices it offers a person in the Dashboard (`Option`): a key, the values it may
  take, smallest first, and the one it has until a person picks another. Stored in the state's
  `options` table, read by the capability's own code (state.Scoped);
* `rules_editor` and `samples` - whether the Dashboard shows it the rules a person writes for
  Codex's error codes, and whether it keeps samples of the failures it takes up (state/choices.py);
* `journal_prefix` and `codes` - the words its own journal lines are written in, `<prefix>.<code>`,
  closed like every other word the edition stores;
* `resends` - whether what it does is send an uncertain continuation once more (v0.6.14): such a
  capability answers at P7, is turned off by a resend of its found twice whether or not it is kept on,
  and is never given Keep on's Send again, which would be itself (arming.py);
* `requires` - the ids of other capabilities this one needs on (v0.6.16-beta.3, the owner's rule: a
  capability that needs another, or that makes another turn on, turns both on). Turning this one on
  turns on what it requires in the same confirmation (one yes, both statements), and turning a required
  one off turns off what requires it; a required one an administrator's policy forbids, or whose
  compatibility is Failed here, keeps the dependent off, with that reason (arming.py). Never names
  itself, and the registry is acyclic (Registry rejects a cycle when it is made);
* `keepable` - whether a person may keep it on (K8; v0.6.16-beta.4): False for one whose tripwire is what stops it
  doing harm, which Keep on would turn into a note (arming.py refuses it);
* `make` - the factory for its code: given the installation's paths, it returns an object whose
  methods are the plug's hooks for its points, each answering as a plug would.

The edition ships these capabilities now: start-with-Codex, at P9 (control/codexstart.py); the
goal continuation, at P16, P3 and P5 (engine/goal.py); the marker-free continuation, at P5 and
P15 (engine/markerfree.py); and, from v0.6.14 (stage 3b), those that take up failures at P17 and
relax their records at P3: the short retries when Codex is at capacity (engine/capacity.py), the
rules for Codex's error codes, the retries of failures nothing classified, of Codex giving up and
of a sign-in failure (engine/admitted.py); at P8 and P7, a reset credit used at the limit a person picked
(engine/credits.py), and at P8, P2 and P3 a message of a person's own sent when the window they picked resets
(engine/resetmessage.py); and, at P7 and P3, the notice of a usage limit that lifts early (engine/earlyreset.py); at P7, an uncertain continuation sent once more (engine/oncemore.py),
and one waiting recovery a person asks to send now (control/sendnow.py); at P12, several conversations at once
(engine/parallel.py); at P16, a conversation queued in Codex for when it is opened (engine/foropen.py); from v0.6.18,
at P8, the weekly update check while idle (engine/updatecheck.py); and, at no point, three actions: longer
reset messages, Open Codex on a notice (control/opencodex.py), and the compatibility report (report/). The tests define
one of their own to hold every rule here.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Callable

from codex_auto_resume.domain.plug import Point

from .control.codexstart import make as make_start_with_codex
from .control.opencodex import make as make_open_codex_button
from .control.sendnow import make as make_send_now
from .engine.admitted import (ATTEMPTS, DEFAULT_ATTEMPTS, make_codex_gave_up, make_sign_in_retry,
                              make_structured_rules, make_unknown_failure_budget)
from .engine.capacity import CEILING_HOURS, DEFAULT_HOURS, make as make_capacity_retry
from .engine.compact import make as make_compact_continue
from .engine.credits import make as make_reset_credit
from .engine.resetmessage import make as make_reset_message, make_long as make_long_messages
from .engine.earlyreset import make as make_early_reset
from .engine.emptyreply import make as make_empty_response
from .engine.everyconversation import make as make_every_conversation
from .engine.subagent import make as make_subagent_parent
from .engine.keepgoing import make as make_keep_going
from .engine.promptqueue import make as make_prompt_queue
from .engine.foropen import CODES as FOROPEN_CODES, DAYS, DEFAULT_DAYS, make as make_queue_for_open
from .engine.fallback import (ATTEMPTS as FALLBACK_ATTEMPTS, DEFAULT_ATTEMPTS as FALLBACK_DEFAULT_ATTEMPTS,
                              NOT_RESTORED, make as make_model_fallback)
from .engine.goal import make as make_goal_continuation
from .engine.headless import DEFAULT_HOURS as HEADLESS_DEFAULT_HOURS, HOURS as HEADLESS_HOURS, make as make_headless_run
from .engine.markerfree import make as make_marker_free
from .engine.hookclaims import make as make_stop_hook
from .engine.retries import (ATTEMPTS as RETRY_ATTEMPTS, DEFAULT_ATTEMPTS as RETRY_DEFAULT_ATTEMPTS,
                             make as make_retry_settings)
from .engine.sessions import make as make_other_sessions
from .engine.silent import make as make_silent_continuation
from .engine.oncemore import make as make_once_more
from .engine.parallel import DEFAULT_WORKERS, WORKERS, make as make_parallel
from .engine.updatecheck import make as make_idle_update_check
from .engine.usage import (DEFAULT_PAUSE, DEFAULT_POLL, DEFAULT_STOP_WORDS, DEFAULT_STYLE, DEFAULT_WARN,
                           DEFAULT_WRAP, ON, PERCENT_RANGE, PERCENTS, POLL_RANGE, SWITCH,
                           POLL_CHOICES, STYLES, make_meter, make_pause, make_wrap_up)
from .report import make as make_compat_report
from .standards import DEPARTABLE
from .vocabulary import CapabilityKind, Measurement, OptionKey, RunEnd, Verdict, WordingKey

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
class Option:
    key: OptionKey             # what the choice is
    choices: tuple             # the values it may take: whole numbers from 1, smallest first
    default: int               # the one it has until a person picks another; one of the choices
    # v0.6.16-beta.4 (item (f), "이런 수치들은 직접 입력도 가능해야 한다니까"): (lowest, highest) a person may type in
    # beside the choices - any whole number in it - or None where only the choices are taken.
    custom: tuple | None = None

    def takes(self, value) -> bool:
        """Whether `value` is one this choice takes: one of its choices, or a whole number in its custom range."""
        if type(value) is not int:
            return False
        return value in self.choices or (self.custom is not None and self.custom[0] <= value <= self.custom[1])


@dataclass(frozen=True)
class CapabilityDef:
    id: str
    points: frozenset
    revision: int
    departs_from: tuple
    compat: str | None                   # None for an action, which stands on none
    ceilings: Ceilings | None            # None for an action, which spends nothing
    journal_prefix: str
    make: Callable
    codes: tuple = ()
    measurements: tuple = ()
    options: tuple = ()
    rules_editor: bool = False
    samples: bool = False
    resends: bool = False
    requires: tuple = ()
    kind: CapabilityKind = CapabilityKind.ROUTE
    # v0.6.16-beta.4: the WordingKeys of a person's own text it keeps (state `wordings`): the wrap-up's Custom text.
    wordings: tuple = ()
    keepable: bool = True

    def option(self, key) -> Option | None:
        """The choice of `key` this capability offers, or None."""
        return next((option for option in self.options if option.key == key), None)

    def code(self, word) -> str | None:
        """`word` as this capability's journal writes it, or None if it is not one of its own."""
        return "%s.%s" % (self.journal_prefix, word) if word in self.codes else None


def _count(value) -> bool:
    return type(value) is int and value >= 1


def _option_problem(option) -> bool:
    return (not isinstance(option, Option) or option.key not in tuple(OptionKey)
            or not isinstance(option.choices, tuple) or not option.choices
            or not all(_count(value) for value in option.choices)
            or list(option.choices) != sorted(set(option.choices))
            or not _count(option.default) or option.default not in option.choices
            or not (option.custom is None or (isinstance(option.custom, tuple) and len(option.custom) == 2
                                              and all(_count(end) for end in option.custom)
                                              and option.custom[0] <= option.choices[0]
                                              and option.choices[-1] <= option.custom[1])))


def problems(definition) -> list:
    """Every rule `definition` breaks, each named in a few words. Empty when it keeps them all."""
    if not isinstance(definition, CapabilityDef):
        return ["not a definition"]
    found = []
    if not isinstance(definition.id, str) or not ID_SHAPE.fullmatch(definition.id):
        found.append("id")
    if not isinstance(definition.kind, CapabilityKind):
        found.append("kind")
    action = definition.kind == CapabilityKind.ACTION
    points = definition.points
    if action:
        if points != frozenset():
            found.append("an action answers at no point")
        if definition.compat is not None:
            found.append("an action stands on no compatibility capability")
        if definition.ceilings is not None:
            found.append("an action has no ceilings: it spends nothing")
        if definition.measurements != ():
            found.append("an action rests on no measurement")
    elif (not isinstance(points, frozenset) or not points
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
          or len(set(departs)) != len(departs) or not set(departs) <= set(DEPARTABLE)):
        found.append("departs_from names a standard the standard edition does not keep")
    if not action:
        if not isinstance(definition.compat, str) or not ID_SHAPE.fullmatch(definition.compat):
            found.append("compat")
        ceilings = definition.ceilings
        if (not isinstance(ceilings, Ceilings) or not _count(ceilings.per_day)
                or not _count(ceilings.per_conversation)
                or ceilings.per_conversation > ceilings.per_day
                or (ceilings.per_conversation > CORE_DAILY_CAP
                    and "A20" not in (departs if isinstance(departs, tuple) else ()))
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
    options = definition.options
    if (not isinstance(options, tuple) or any(_option_problem(option) for option in options)
            or len({option.key for option in options}) != len(options)):
        found.append("options")
    if type(definition.rules_editor) is not bool or type(definition.samples) is not bool:
        found.append("rules_editor or samples")
    if type(definition.resends) is not bool or (
            definition.resends is True and Point.SCHEDULE not in (points if isinstance(points, frozenset) else ())):
        found.append("resends")
    if type(definition.keepable) is not bool:
        found.append("keepable")
    requires = definition.requires
    if (not isinstance(requires, tuple)
            or not all(isinstance(other, str) for other in requires)
            or len(set(requires)) != len(requires)
            or definition.id in requires):
        found.append("requires")
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
        self._check_requirements()

    def _check_requirements(self) -> None:
        """Every required id is a capability of this registry, and the requirement graph has no cycle:
        a capability that cannot have every requirement turned on, or that would require itself round a
        loop, is never offered."""
        for definition in self.definitions:
            for other in definition.requires:
                if other not in self._by_id:
                    raise RegistryError("%s requires an unknown capability %s" % (definition.id, other))
        colour = {}                              # 0 visiting, 1 done

        def visit(capability):
            if colour.get(capability) == 1:
                return
            if colour.get(capability) == 0:
                raise RegistryError("the requirements of %s form a cycle" % capability)
            colour[capability] = 0
            for other in self._by_id[capability].requires:
                visit(other)
            colour[capability] = 1

        for definition in self.definitions:
            visit(definition.id)

    def requires(self, capability) -> tuple:
        """The ids `capability` needs on, transitively, in a stable order (each required capability's own
        requirements before it); empty for one that needs none or is not of this registry."""
        found, seen = [], set()

        def visit(current):
            definition = self._by_id.get(current)
            for other in definition.requires if definition is not None else ():
                if other not in seen:
                    seen.add(other)
                    visit(other)
                    found.append(other)
        visit(capability)
        return tuple(found)

    def required_by(self, capability) -> tuple:
        """The ids that need `capability` on, transitively, in the registry's order: what turning it off
        turns off too (arming.disarm)."""
        return tuple(definition.id for definition in self.definitions
                     if capability in self.requires(definition.id))

    @property
    def ids(self) -> tuple:
        return tuple(self._by_id)

    def get(self, capability) -> CapabilityDef | None:
        return self._by_id.get(capability) if isinstance(capability, str) else None

    def at(self, point) -> tuple:
        """The capabilities whose code answers at `point`, in the registry's order. Never an action,
        which answers at none: core never asks it anything."""
        return tuple(definition for definition in self.definitions
                     if definition.kind == CapabilityKind.ROUTE and point in definition.points)

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
# WOULD_HAVE where it is watched, ACTED where it names a route - and, from v0.6.16-beta.3 (issue
# #31), what core made of that route, in its own codes (core's control/codexstart.OUTCOMES, told to
# the route), and `held` where it was on and named none: held back by what Codex is, or by a policy,
# so a start that did not happen is in the journal as one that did is. It departs from C4 (nothing at start) and F6 (a
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
    codes=("held", "started", "running", "uncertain", "paused", "unasked", "installing", "not_installed",
           "refused", "failed", "ended"),
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

# The goal continuation (v0.6.11 stage 3a, the owner's request of 2026-09-26): for a usage limit in
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
    # Revision 2 (v0.6.15-beta): its risks say it acts on a conversation the app holds where M2b passed.
    revision=2,
    departs_from=("0.5", "A2", "A11", "B3", "B4"),
    compat="loaded_state_detection",
    ceilings=Ceilings(per_day=12, per_conversation=3),
    journal_prefix="goal",
    make=make_goal_continuation,
    measurements=(Measurement.M2,),
)

# Queue for opening (v0.6.15-beta; the plan's item 4: an unloaded conversation through the deferred queue). At P16,
# for a usage-limited conversation the Codex app does not hold (notLoaded, never unknown), it answers QUEUE_FOR_OPEN:
# core sends its own words with its marker through its own backend, under the one claim - which writes this
# capability's override, one per interruption (ledger.py) - and leaves the item in Codex's queue for when the
# conversation is opened. In the watch it keeps the item queued while the override is within the person's Days (3 to
# 7, 3 by default); core takes it back at seven days and an hour whatever it answers, and at once when it is turned
# off. Opened and not delivered within core's 180 seconds, the item is taken back, given back to waiting and sent the
# ordinary way, and this turns off (NOT_DELIVERED_ON_OPEN). It departs from A11 (nothing is queued on the off chance)
# and keeps A17, H4 and H6 - every withdrawal still fires at once - and stands on loaded_state_detection, what decides
# that a conversation is not held. Its route rests on M1, passed on codex-cli 0.158 and a warning on any other.
# Ceilings: three a conversation a day, a dozen a day in all. After the goal continuation, whose route comes first
# where both are on and a goal applies - and (v0.6.17, #47) which, while MQG has no pass on the Codex in force, it leaves
# a conversation whose goal is active to: one continuation, its codes saying why (engine/foropen.py).
QUEUE_FOR_OPEN = CapabilityDef(
    id="queue_for_open",
    points=frozenset({Point.UNLOADED}),
    revision=1,
    departs_from=("A11",),
    compat="loaded_state_detection",
    ceilings=Ceilings(per_day=12, per_conversation=3),
    journal_prefix="qfo",
    make=make_queue_for_open,
    codes=FOROPEN_CODES,
    options=(Option(OptionKey.DAYS, DAYS, DEFAULT_DAYS),),
    measurements=(Measurement.M1,),
)

# Run a conversation here while Codex is closed (v0.6.16-beta.4, stage 4; the plan's "unloaded conversation: recover
# it here, headless"). At P16, asked by core where the Codex app is not running and nothing holds the conversation's
# writer lock (`holder="none", app=False`, for the default home), it is the route: core decides the words - with its
# marker - claims, this paying one unit, and calls it inside its launch guard; the route runs that one turn on our own
# app server on the settings Codex saved for the conversation, declines every approval, refuses full access, an
# outside sandbox and another reviewer before anything starts, and lets go (codex/headless.py). One run at a time; the
# person's Hours (1 to 6, 1 by default) cap it; a Stop on Pending's row, and the Codex app starting (Q3, at once),
# interrupt it. At P8 it writes the live run's row, hands a Stop on and journals how each run ended. It departs from
# 0.5 (it wakes a conversation through thread/resume), A2 (a channel beside codex queue), A11 (nothing is done for a
# conversation the app does not hold), B3 and B4 (four more app-server methods), E8 and F8 (a Codex helper that lives
# for the turn, ended by us), and keeps A4. It stands on loaded_state_detection and rests on M6 and M6B. A full
# context window is compact_continue's, never this one's. Ceilings: three a conversation, a dozen a day.
HEADLESS_RUN = CapabilityDef(
    id="headless_run",
    points=frozenset({Point.UNLOADED, Point.TICK}),
    revision=1,
    departs_from=("0.5", "A2", "A11", "B3", "B4", "E8", "F8"),
    compat="loaded_state_detection",
    ceilings=Ceilings(per_day=12, per_conversation=3),
    journal_prefix="head",
    make=make_headless_run,
    codes=tuple(str(word) for word in RunEnd),
    options=(Option(OptionKey.CEILING_HOURS, HEADLESS_HOURS, HEADLESS_DEFAULT_HOURS),),
    measurements=(Measurement.M6, Measurement.M6B),
)

# Recover the conversations of a terminal's Codex TUI and of VS Code (v0.6.16-beta.4, stage 4; one capability for
# both, Q10). At P18 it names both other kinds, `cli` and `ide`, and core watches their conversations as the app's:
# detected, and every check of their records made with them (core's codex/eligibility.py); turned off, core cancels
# their waiting records (session_kind_off) and follows what it sent to its end. At P16, for a conversation another
# Codex session holds (`holder="session"`), it answers TO_SESSION: core's ordinary send through `codex queue`, with
# its marker, for that session to take (M5) - taken back when that session lets go of it, and given back to waiting;
# taken back because the session did not take it within core's delivery window, it turns off
# (NOT_DISPATCHED_BY_SESSION), and so it may not be kept on (keepable). It departs from A15 (only the app's
# conversations are detected), A11 (sent while a session other than the app holds the conversation) and B6 (the
# version skew guard reads which Codex wrote such a conversation off its file's first line, core's engine/kinds.py,
# and waits while that is newer than the engine), keeps A2, A3,
# A4, A17, H4 and H6, stands on thread_eligibility and rests on M5 and MO - the words that tell these conversations
# apart, a warning until MO passes for the Codex in force. Ceilings: three a conversation, two dozen a day.
OTHER_SESSIONS = CapabilityDef(
    id="other_sessions",
    points=frozenset({Point.SESSIONS, Point.UNLOADED}),
    revision=1,
    departs_from=("A11", "A15", "B6"),
    compat="thread_eligibility",
    ceilings=Ceilings(per_day=24, per_conversation=3),
    journal_prefix="sess",
    make=make_other_sessions,
    measurements=(Measurement.M5, Measurement.MO),
    keepable=False,
)

# Compact a full conversation, then continue (v0.6.16-beta.4, stage 4). At P17 it takes up Codex's own
# contextWindowExceeded alone (core offers a terminal_invalid failure for that one code, failures.admits); at P3 it
# admits it again while it is worth going on - less than a day since, and no compaction after it failed - and, where
# the app holds the conversation, HOLDs until a compaction turn is the latest: Pending asks the person to run /compact
# in Codex (MXA), and core's ordinary continuation follows, which a compaction turn does not supersede (core's
# engine/detect.py). Where nothing holds it and Codex is closed it compacts it here at P16 on the headless route
# (thread/compact/start, MX), then continues it the same way, and at P8 journals each run. It departs from 0.5, A2,
# A11, B3, B4, E8 and F8 (as headless_run), A13 and A14 (a context-length failure is taken up), A16 (the continuation
# follows the compaction turn), A17 (a compaction turn supersedes nothing of its record) and A26 (the continuation's
# words for a failure the standard edition does not recover). It stands on transient_classification and rests on M7,
# MX and MXA. Ceilings: two a conversation - the compaction's claim and its continuation's - and six a day. Before
# headless_run in DEFINITIONS, so its own record is its route's at P16.
COMPACT_CONTINUE = CapabilityDef(
    id="compact_continue",
    points=frozenset({Point.ADMISSION, Point.GATES, Point.UNLOADED, Point.TICK}),
    revision=1,
    departs_from=("0.5", "A2", "A11", "A13", "A14", "A16", "A17", "A26", "B3", "B4", "E8", "F8"),
    compat="transient_classification",
    ceilings=Ceilings(per_day=6, per_conversation=2),
    journal_prefix="compact",
    make=make_compact_continue,
    codes=tuple(str(word) for word in RunEnd),
    measurements=(Measurement.M7, Measurement.MX, Measurement.MXA),
)

# Another model when one is at capacity (v0.6.16-beta.4, stage 4; headless only). At P16, for a server error Codex
# coded serverOverloaded whose task has had the person's Attempts (1 to 3, 2 by default) of continuations, and only
# where nothing holds the conversation while Codex is closed, it is the headless route in fallback mode: one turn on
# Codex's own default model where the conversation is on another, the conversation's own model put back before it
# lets go (codex/headless.py), on every path; at P8 it journals each run, and a model Codex would not put back
# (model_not_restored) - and, where one is still owed (stored before the turn/start: a watcher stopped mid-turn), puts
# it back as its errand, with no run live, Codex closed and nothing holding the conversation.
# It departs from 0.5 (it changes and replays a model setting), A2, A11, B3, B4, E8 and F8 (as headless_run) and B9
# (it reads Codex's error code), stands on transient_classification and rests on MF. Ceilings: two a conversation,
# six a day. Before headless_run in DEFINITIONS, so its own case is its route's at P16.
MODEL_FALLBACK = CapabilityDef(
    id="model_fallback",
    points=frozenset({Point.UNLOADED, Point.TICK}),
    revision=1,
    departs_from=("0.5", "A2", "A11", "B3", "B4", "B9", "E8", "F8"),
    compat="transient_classification",
    ceilings=Ceilings(per_day=6, per_conversation=2),
    journal_prefix="model",
    make=make_model_fallback,
    codes=tuple(str(word) for word in RunEnd) + (NOT_RESTORED,),
    options=(Option(OptionKey.ATTEMPTS, FALLBACK_ATTEMPTS, FALLBACK_DEFAULT_ATTEMPTS),),
    measurements=(Measurement.MF,),
)

# Continue with no words (v0.6.16-beta.4, stage 4; headless only). At P15 it answers SILENT, which core carries out
# only through a route that takes words - headless_run's turn, compact_continue's continuation - calling it with no
# words at all under the client id it derives, its proof (core's engine/routes.py); through codex queue or a channel
# core ignores it (M3: Codex refuses an empty queue item). It continues nothing by itself. Where Codex refuses a turn
# with no input it answers DEFER from then on in this process, so the next attempt carries words, and it turns off
# (REFUSED_BY_CODEX) - so it may not be kept on (keepable). It departs from A4 (no marker) and A26 (no words), stands
# on recovery_turn_tracking and rests on M3B. Ceilings: five a conversation, two dozen a day.
SILENT_CONTINUATION = CapabilityDef(
    id="silent_continuation",
    points=frozenset({Point.DELIVERY}),
    revision=1,
    departs_from=("A4", "A26"),
    compat="recovery_turn_tracking",
    ceilings=Ceilings(per_day=24, per_conversation=5),
    journal_prefix="silent",
    make=make_silent_continuation,
    measurements=(Measurement.M3B,),
    keepable=False,
)

# Short retries when Codex is at capacity (v0.6.14 stage 3b; the plan's row: serverOverloaded alone,
# 60 seconds to 5 minutes apart with jitter, a 60-second cooldown, 48 in 24 hours, 1 to 12 hours in
# all). At P17 it takes up Codex's own
# `serverOverloaded` with CAPACITY, and at P3 known_failure it answers CAPACITY again for a record it
# took up, while the task is inside the hours the person chose (one to twelve, two by default), on the
# clock from its first failure. Core carries CAPACITY out within its own bounds - a minute, two, four
# and five, lengthened by up to a fifth, a minute apart, 48 a day, twelve hours on the clock
# (ladder.py) - so it departs from A20 (five a conversation a day, fifteen minutes apart), A21 (the
# attempt, no-progress and continuation budgets), A22 (waits only from the retry timing) and B9 (it
# reads Codex's error code, not only a kind), and from H2 (nothing can move an engine constant: A20's
# caps are the engine's, and a person's choice moves them here). It stands on transient_classification,
# the history table the failure's kind and code are read from, and rests on no measurement: core sends
# what it always sends. Its ceilings are core's capacity day, 48 in one conversation and in all, which
# only A20's departure allows. Revision 2 (v0.6.15-beta) names H2, where revision 1 did not.
CAPACITY_RETRY = CapabilityDef(
    id="capacity_retry",
    points=frozenset({Point.ADMISSION, Point.GATES}),
    revision=2,
    departs_from=("A20", "A21", "A22", "B9", "H2"),
    compat="transient_classification",
    ceilings=Ceilings(per_day=48, per_conversation=48),
    journal_prefix="cap",
    make=make_capacity_retry,
    options=(Option(OptionKey.CEILING_HOURS, CEILING_HOURS, DEFAULT_HOURS),),
)

# Rules for Codex's error codes (v0.6.14 stage 3b; the plan's row: an error code, and if wished a
# range of status numbers, mapped to a kind of temporary failure; ten at most; only where the kind is
# unknown; never a terminal code, never a usage limit; the Dashboard only). A person writes up to ten
# rules (state/choices.py); a failure nothing classified, with a code core offers (a tagged code of
# Codex's naming no decision, failures.admits), is taken up at P17 as the kind the lowest-numbered
# matching rule names (AS_*), and at known_failure the same word again while that rule is there - its
# removal ends what it took up. Core paces it as that kind, counts it against that kind's budget and
# follows that kind's switch. It departs from 0.5 (unknown failures are never retried), A13 and A14
# (only classified kinds), A26 (continuation text for a recovered kind), B9 (it reads Codex's code) and
# H2 (nothing can retry an unknown failure: a rule is a person's setting, and it retries only what
# nothing classified), and stands on transient_classification. Its hits are counted (`matched`) the
# first time core goes on with what a rule took up. Ceilings: five a conversation, two dozen a day.
# Revision 2 (v0.6.15-beta) names H2, where revision 1 did not.
STRUCTURED_RULES = CapabilityDef(
    id="structured_rules",
    points=frozenset({Point.ADMISSION, Point.GATES}),
    revision=2,
    departs_from=("0.5", "A13", "A14", "A26", "B9", "H2"),
    compat="transient_classification",
    ceilings=Ceilings(per_day=24, per_conversation=5),
    journal_prefix="rule",
    make=make_structured_rules,
    codes=("matched",),
    rules_editor=True,
)

# Retry failures it cannot name (v0.6.14 stage 3b; the plan's row: a failure nothing classified
# retried on its own budget, one to three times, three a conversation in 24 hours, with a sample of
# no words - Codex's code, the status number, item counts and times only). At P17 it takes up with
# ADMIT a failure nothing classified - core offers it only for a code of Codex's that names no
# decision - while its task has tries left (Option attempts, one by default), after the rules, which
# come first; at known_failure ADMIT again. Core waits ten minutes, then 15 and 30
# (ladder.ADMITTED_WAITS), and its own no-progress and chain budgets still bind. The first time core
# goes on with one it keeps a sample (state/choices.py; `sampled`). It departs from 0.5, A13, A14,
# A26, B9 and H2 as the rules do, and from D2 too: a sample keeps a code Codex chose. Ceilings: three
# a conversation, a dozen a day. Revision 2 (v0.6.15-beta) names H2, where revision 1 did not.
UNKNOWN_FAILURE_BUDGET = CapabilityDef(
    id="unknown_failure_budget",
    points=frozenset({Point.ADMISSION, Point.GATES}),
    revision=2,
    departs_from=("0.5", "A13", "A14", "A26", "B9", "D2", "H2"),
    compat="transient_classification",
    ceilings=Ceilings(per_day=12, per_conversation=3),
    journal_prefix="unk",
    make=make_unknown_failure_budget,
    codes=("sampled",),
    options=(Option(OptionKey.ATTEMPTS, ATTEMPTS, DEFAULT_ATTEMPTS),),
    samples=True,
)

# Retry when Codex gave up (v0.6.14 stage 3b; the plan's row: responseTooManyFailedAttempts with a
# 5xx or no status, retried with a first wait of five minutes or more, twice at most). At P17 it takes
# up with ADMIT what core offers - Codex's responseTooManyFailedAttempts on a server error or none, a
# 429 being a rate limit core recovers already - while the task it continues has had fewer than two
# continuations, and at known_failure ADMIT again. Core waits ten minutes, then 15 (ladder.py). It
# departs from A14 (Codex giving up without a 429 is never retried), A26 and B9 (it reads Codex's code
# and status), and stands on transient_classification. Ceilings: two a conversation, a dozen a day.
CODEX_GAVE_UP = CapabilityDef(
    id="codex_gave_up",
    points=frozenset({Point.ADMISSION, Point.GATES}),
    revision=1,
    departs_from=("A14", "A26", "B9"),
    compat="transient_classification",
    ceilings=Ceilings(per_day=12, per_conversation=2),
    journal_prefix="gup",
    make=make_codex_gave_up,
)

# Retry a sign-in failure after proof (v0.6.14 stage 3b; the plan's row: retried once when a usage read
# succeeds; once a failure, twice in 24 hours, stopping at the second failure; auth.json and the way of
# signing in never touched). At P17 it takes up with ADMIT what core offers - Codex's unauthorized with
# no status or a 401, never a 403 (permission is on the plan's exclusions) - unless the task it
# continues is one whose continuation failed at sign-in already, and at known_failure ADMIT again. The
# proof is core's own: the usage read every continuation waits for works only while Codex is signed
# in, and core ends the record unsent a day on the clock after the failure (ladder.py). It departs
# from 0.5 (sign-in failures are never retried), A14 (401 and 403 are never retried) and A26, and
# stands on usage_probe - the usage read is its proof. Ceilings: two a conversation and two a day.
SIGN_IN_RETRY = CapabilityDef(
    id="sign_in_retry",
    points=frozenset({Point.ADMISSION, Point.GATES}),
    revision=1,
    departs_from=("0.5", "A14", "A26"),
    compat="usage_probe",
    ceilings=Ceilings(per_day=2, per_conversation=2),
    journal_prefix="sgn",
    make=make_sign_in_retry,
)

# Use a reset credit when the limit a person picked is reached (v0.6.14, the owner's request of 2026-10-05; the
# plan's row "reset credits"): a person picks an occasion - the next 5-hour limit, a later one, the weekly one - and
# when that window fills while a recovery waits for usage, the errand at P8 spends one reset credit of theirs: only
# with the window still full, the count and the soonest expiry both readable, one for each filling, two a day and
# seven a week at most, inside core's errand guard, and on its own only where MR passed and the person did not ask to
# be asked first (until then, the Dashboard's Use a reset credit now). For fifteen minutes after its credit reset a
# window, it answers EARLY at P7 for the recoveries that wait, so they go at core's next early window. It departs
# from A12 (a look before the reset time), B3 and B4 (account/rateLimitResetCredit/consume changes the account),
# B10 (it keeps the count and the soonest expiry), C4 (it reads and spends on its own) and C9 (it reads usage when no
# recovery is due); it stands on usage_probe and rests on MU, MN and MR. A spend whose result cannot be known turns
# it off, as a send it paid for gone submission_unknown does (K7). Ceilings: the early looks it causes, three a
# conversation, a dozen a day. It comes before early_reset, whose hold lets go of a look it made (not_taken).
RESET_CREDIT = CapabilityDef(
    id="reset_credit",
    points=frozenset({Point.TICK, Point.SCHEDULE}),
    revision=1,
    departs_from=("A12", "B3", "B4", "B10", "C4", "C9"),
    compat="usage_probe",
    ceilings=Ceilings(per_day=12, per_conversation=3),
    journal_prefix="credit",
    make=make_reset_credit,
    codes=("hit", "spent", "nothing", "no_credit", "asked", "lapsed", "unknown", "gap", "gone"),
    measurements=(Measurement.MU, Measurement.MN, Measurement.MR),
)

# A message of a person's own when the window they picked resets (v0.6.14, the owner's request of 2026-10-06; the
# plan's row "at the next reset", pulled forward from 3c): a person writes it in the Dashboard for one conversation
# that is switched on and picks an occasion, and when that window resets core sends it - its gates, its one claim,
# its one send - as a record of this edition's own (P2), at most 2,000 characters unless Longer reset messages is on
# (A27 kept). At P8 it counts the windows (engine/resetwatch.py); at P2 it hands core the messages due and in flight,
# cancelling one whose conversation was switched off (H5) and ending one that waited too long; at P3 `usage` it holds
# a core record of the same conversation while a message there is due or in flight, or counts for the very reset
# that record waits for, so the message goes in its place (the owner's answer). It departs from A8 (a recovery's
# budgets and failure checks are not run), A17 (a turn after it does not take it back), A26 (the words are the
# person's), C4 (it sends at a time chosen), C9 (it reads usage when no recovery is due), D2 (the words kept until
# sent), H4 (a Pause does not take back one already queued) and H6 (Cancel no longer reaches one being sent); its
# reads are core's own method, so not B4. It stands on exact_thread_recovery and rests on MU. One that cannot be
# proven to have arrived a day after it was sent turns it off (K7). Ceilings: two a conversation, ten a day.
RESET_MESSAGE = CapabilityDef(
    id="reset_message",
    points=frozenset({Point.TICK, Point.RECORDS, Point.GATES}),
    # Revision 2 (v0.6.15-beta): a Pause takes back a message Codex already holds and cancels it (core's
    # engine/plugrecords.py), which its statement's H4 now says.
    revision=2,
    departs_from=("A8", "A17", "A26", "C4", "C9", "D2", "H4", "H6"),
    compat="exact_thread_recovery",
    ceilings=Ceilings(per_day=10, per_conversation=2),
    journal_prefix="resetmsg",
    make=make_reset_message,
    codes=("due", "sent", "delivered", "unknown", "expired", "not_started", "gap", "gone"),
    measurements=(Measurement.MU,),
)

# Notice a usage limit that lifts early (v0.6.14 stage 3b; the plan's row: continue at once when usage
# frees up before the time given; two checks at least five minutes apart; only while a record waits for
# a usage limit). At P7, asked by core before such a record's time (EARLY), it answers EARLY once a
# probe - one every five minutes for every waiting record together, as core's own early window is - so
# core reads usage once for them all; at P3 `usage`, which core reaches only when that reading found
# usage, it holds a record on a first yes and lets core go on at a second at least five minutes after.
# Core keeps every other gate, a postponement and quiet hours included, and a look that meets a wait
# leaves the record as it was. It departs from A12 (never before the real reset time) and C9 (usage is
# read only when a recovery is due), and stands on usage_probe. Its words: `probed` for a first early
# yes, `lifted` for the second. Ceilings: three a conversation, a dozen a day.
EARLY_RESET = CapabilityDef(
    id="early_reset",
    points=frozenset({Point.SCHEDULE, Point.GATES}),
    revision=1,
    departs_from=("A12", "C9"),
    compat="usage_probe",
    ceilings=Ceilings(per_day=12, per_conversation=3),
    journal_prefix="erl",
    make=make_early_reset,
    codes=("probed", "lifted"),
)

# Once more when unsure (v0.6.14 stage 3b; the plan's row: when a delivery is uncertain, send it once
# more with the same words and the same marker - no marker in the history or the queue, no wait, a
# fresh reading, no later turn; off by itself where a duplicate is seen). At P7, asked by core for an
# uncertain submission a look of its watch has just found no trace of (core's engine/resend.py), it
# answers RESEND once, for one this edition never resent and no channel or route paid for; core proves
# every other condition - 15 minutes to 6 hours after the send, Codex never seen holding it, its history
# current at every look since, neither the marker nor the client id it went under anywhere, no later
# turn and nothing queued, every gate a send passes with every budget - and charges no attempt. It
# departs from 0.2 (never again when the first may have been delivered), A6 (an uncertain delivery is
# never resent), E2 (better to miss a resume than resume twice) and H2 (nothing can resend an uncertain
# submission), and stands on recovery_turn_tracking - the history, queue and projection tables its
# proof reads. A resend of its found twice turns it off, kept on or not. Ceilings: two a conversation,
# six a day.
ONCE_MORE = CapabilityDef(
    id="once_more_when_unsure",
    points=frozenset({Point.SCHEDULE}),
    revision=1,
    departs_from=("0.2", "A6", "E2", "H2"),
    compat="recovery_turn_tracking",
    ceilings=Ceilings(per_day=6, per_conversation=2),
    journal_prefix="oncemore",
    make=make_once_more,
    resends=True,
)

# Send now (v0.6.14 stage 3b; the plan's row: skip the schedule, the cooldown and the attempt budget and
# go at once; the Dashboard's alone; consent, compatibility, ownership, identity, the daily cap, loading,
# new work and the live usage check stay). A person asks for one waiting recovery in the Dashboard
# (advanced-send-now) while it is on, and at P7 it answers SEND_NOW for that record, once, within fifteen
# minutes: core then passes the retry's wait, a postponement, the objection window, the fifteen minutes
# between two continuations and an attempt budget of the person's own - never an administrator's - and
# every other gate holds, a reset still ahead and quiet hours among them. It departs from A8 (the claim's
# re-check passes nothing), A20 (fifteen minutes between two continuations), A21 (the attempt budget
# stops a recovery) and H2 (nothing can force a send), and stands on exact_thread_recovery - the official
# Codex and its queue flags every send rests on. Its word: `requested`, a person's request. Ceilings: core's
# five a conversation a day, two dozen a day in all.
SEND_NOW = CapabilityDef(
    id="send_now",
    points=frozenset({Point.SCHEDULE}),
    revision=1,
    departs_from=("A8", "A20", "A21", "H2"),
    compat="exact_thread_recovery",
    ceilings=Ceilings(per_day=24, per_conversation=CORE_DAILY_CAP),
    journal_prefix="sendnow",
    make=make_send_now,
    codes=("requested",),
)

# Several conversations at once (v0.6.15-beta; the plan's row: parallel processing across conversations). At P12 it
# answers how many sends may wait for their receipts at once - the Workers option, 2 by default, 2 at most until MQ
# passes on the Codex in force - and core lets that many wait on workers, one in each conversation, while every gate,
# claim and look stays on the tick (core's engine/launches.py). Each pooled claim pays one unit, so a pooled send whose
# fate cannot be known turns it off (K7). It departs from 0.5 (one recovery dispatched at a time) and A19 (in sequence,
# under one lock) - and keeps A19's one continuation in flight per conversation - and stands on exact_thread_recovery.
# Ceilings: core's five a conversation a day, 48 a day in all.
PARALLEL_DISPATCH = CapabilityDef(
    id="parallel_dispatch",
    points=frozenset({Point.CONCURRENCY}),
    revision=1,
    departs_from=("0.5", "A19"),
    compat="exact_thread_recovery",
    ceilings=Ceilings(per_day=48, per_conversation=CORE_DAILY_CAP),
    journal_prefix="par",
    make=make_parallel,
    options=(Option(OptionKey.WORKERS, WORKERS, DEFAULT_WORKERS),),
    measurements=(Measurement.MQ,),
)

# The prompt queue (v0.6.15-beta; the plan's item 7, on reset_message's way). A person queues messages of their own
# for one conversation in the Dashboard - after the turn now running, at a time, or every day or week from a time, 30
# times and 30 days at most - and at P2 each conversation's first one still to go is made due and handed core with its
# words, a P2 MESSAGE core sends exactly as typed: in order, each once, one waiting for the one before it to arrive
# where asked, paced like every recovery (A20 kept, the owner's answer). Cancel and a Pause take back one Codex already
# holds (the owner's answer of 2026-10-09). It departs from A8, A17, A26, A27, C4, D2, H4 and H6 as its statement says,
# and stands on exact_thread_recovery. Its after_turn route rests on MT. Ceilings: core's five a conversation, thirty a
# day. Before the edition's own continuations, so a person's message is handed first (P2's eight).
PROMPT_QUEUE = CapabilityDef(
    id="prompt_queue",
    points=frozenset({Point.RECORDS}),
    revision=1,
    departs_from=("A8", "A17", "A26", "A27", "C4", "D2", "H4", "H6"),
    compat="exact_thread_recovery",
    ceilings=Ceilings(per_day=30, per_conversation=CORE_DAILY_CAP),
    journal_prefix="queue",
    make=make_prompt_queue,
    codes=("due", "sent", "delivered", "unknown", "expired", "missed", "held", "superseded"),
    measurements=(Measurement.MT,),
)

# Empty-response recovery (v0.6.15-beta; the plan's item 3). At P8, at most once a minute, it looks at the
# conversations with a turn completed in the last hour: one switched on whose latest turn Codex completed with no
# error, no final agent item and only a message of the person's and Codex's reasoning in it - judged by kinds alone
# (codex/turns.py) - seen so twice, thirty seconds apart and ten after it ended, is continued once in the edition's
# own words, its turn's record a P2 CONTINUATION that core sends only while that turn is the latest. A goal Codex
# keeps going or stopped (active, blocked) is left alone; goals unreadable, nothing. Twice a chain at most. It departs
# from 0.5 (a completed turn is no failure), A13 (only classified failures) and A26 (words of its own), and stands on
# outcome_observation, the history its kinds are read from. Its route rests on ME. Ceilings: two a conversation, a
# dozen a day.
EMPTY_RESPONSE = CapabilityDef(
    id="empty_response",
    points=frozenset({Point.TICK, Point.RECORDS}),
    revision=1,
    departs_from=("0.5", "A13", "A26"),
    compat="outcome_observation",
    ceilings=Ceilings(per_day=12, per_conversation=2),
    journal_prefix="empty",
    make=make_empty_response,
    codes=("found", "goal_left", "chain_spent", "sent", "delivered", "unknown", "superseded"),
    measurements=(Measurement.ME,),
)

# Subagent recovery through the parent (v0.6.15-beta; the plan's item 5). At P4, for a core continuation of a parent
# whose subagents stopped on a failure, it adds one line a subagent, at most five, in fixed words with only the
# subagent's id and a closed kind word varying (5a); at P8 and P2, once MS passes on the Codex in force, one
# continuation of its own to a parent that finished normally after a subagent stopped (5b). Every record is the
# parent's: nothing is ever sent to a subagent. It departs from 0.5 (only failed turns are recovered), A15 (subagents
# are never detected or recovered) and A26 (words of its own), and stands on thread_eligibility, which conversations
# are a person's own. Its route rests on MS. Ceilings: three a conversation, a dozen a day.
SUBAGENT_PARENT = CapabilityDef(
    id="subagent_parent",
    points=frozenset({Point.TEXT, Point.TICK, Point.RECORDS}),
    revision=1,
    departs_from=("0.5", "A15", "A26"),
    compat="thread_eligibility",
    ceilings=Ceilings(per_day=12, per_conversation=3),
    journal_prefix="sub",
    make=make_subagent_parent,
    codes=("told", "followed_up", "sent", "delivered", "unknown", "superseded"),
    measurements=(Measurement.MS,),
)

# Keep going (v0.6.15-beta; the plan's item 6). A person picks conversations in the Dashboard, each with a count of 1
# to 10; at P8, at most once a minute, a picked conversation whose latest turn ended well and that has been idle a
# minute is sent one continuation of the edition's own words, a P2 CONTINUATION core sends only while that turn is the
# latest. It stops on no progress, a finished plan (its steps' statuses alone), an unreadable plan, the count used, an
# active goal, a failed or interrupted turn, and the conversation switched off. Until MK passes on the Codex in force,
# three at most are sent. It departs from A13 (only failures are recovered), A26 (words of its own) and B9 (a plan's
# step statuses are read from an item's content), and stands on outcome_observation. Ceilings: core's five a
# conversation, two dozen a day.
KEEP_GOING = CapabilityDef(
    id="keep_going",
    points=frozenset({Point.TICK, Point.RECORDS}),
    revision=1,
    departs_from=("A13", "A26", "B9"),
    compat="outcome_observation",
    ceilings=Ceilings(per_day=24, per_conversation=CORE_DAILY_CAP),
    journal_prefix="keep",
    make=make_keep_going,
    codes=("found", "stopped", "sent", "delivered", "unknown", "superseded"),
    measurements=(Measurement.MK,),
)

# Recover every conversation but Codex's own (v0.6.16-beta.3; users asked, the owner's plan of 2026-10-13). At P19 it
# answers EVERY_DESKTOP, and core takes up every desktop conversation of the app but the kinds Codex makes for itself
# (core's codex/values.INTERNAL_THREAD_SOURCES: subagent, guardian_review, memory_consolidation, agent_created_thread)
# - every other check of a conversation, and every gate of a recovery, standing. It departs from A15 (only the desktop
# app's own user conversations are detected), stands on thread_eligibility - the state row and the rollout's first
# line it is judged by - and rests on no measurement. It sends nothing itself: what it takes up is core's recovery, under
# core's own limits, so its ceilings are the schema's floor and never bind.
EVERY_CONVERSATION = CapabilityDef(
    id="every_conversation",
    points=frozenset({Point.ELIGIBILITY}),
    revision=1,
    departs_from=("A15",),
    compat="thread_eligibility",
    ceilings=Ceilings(per_day=1, per_conversation=1),
    journal_prefix="every",
    make=make_every_conversation,
)

# The usage meter (v0.6.16-beta.3, issue #29; the v0.6.11 design's "Live usage meter"). At P8, while the Codex app
# runs, it reads usage on its own every POLL_MINUTES (5 to 60, 15 by default) through one finite session that asks
# account/rateLimits/read alone (codex/protocol.CAPABILITY_METHODS), keeps the windows as core keeps a reading
# (state/meter.py), shows them in the icon's tooltip and the popup (surfaces.meter_view), and at the person's
# warning percentage of the five-hour or the weekly window (85 by default, each its own) shows a notice once for that
# window. It never satisfies core's usage gate. It departs from C4 (it reads on a schedule, on its own) and C9 (usage
# read when no recovery is due), stands on usage_probe and rests on MU. It sends nothing: its ceilings are the
# schema's floor and never bind, as start_with_codex's. Wrap up near a limit and Pause near a limit require it.
# Its two window switches decide only its warnings (v0.6.16 final): each of the other two has a pair of its own.
USAGE_METER = CapabilityDef(
    id="usage_meter",
    points=frozenset({Point.TICK}),
    revision=2,
    departs_from=("C4", "C9"),
    compat="usage_probe",
    ceilings=Ceilings(per_day=1, per_conversation=1),
    journal_prefix="meter",
    make=make_meter,
    codes=("read", "unreadable", "warned"),
    measurements=(Measurement.MU,),
    options=(Option(OptionKey.POLL_MINUTES, POLL_CHOICES, DEFAULT_POLL, custom=POLL_RANGE),
             Option(OptionKey.WARN_FIVE_HOUR, PERCENTS, DEFAULT_WARN, custom=PERCENT_RANGE),
             Option(OptionKey.WARN_WEEKLY, PERCENTS, DEFAULT_WARN, custom=PERCENT_RANGE),
             Option(OptionKey.WINDOW_FIVE_HOUR, SWITCH, ON),
             Option(OptionKey.WINDOW_WEEKLY, SWITCH, ON)),
)

# Wrap up near a limit (v0.6.16-beta.3, issue #29; the v0.6.11 design's "Near-limit wrap-up nudge"). At P8, when the
# meter's reading of the five-hour or the weekly window is at the person's wrap-up percentage (90 by default, each its
# own), each conversation switched on whose latest turn is running is given one message of the edition's own - short,
# standard or detailed, as the person chose - once for that window (its key the conversation, the window and its
# reset); at P2 each waiting one is handed core as a WRAP_UP record, which core queues through `codex queue` only
# while that turn is still the latest and still running, so Codex delivers it when the turn ends. It departs from
# A13 (no failure is recovered) and A26 (words of its own), stands on exact_thread_recovery, the queue every send
# rests on, and rests on MT (a message queued while a turn runs is delivered after it). It requires the meter.
# Ceilings: two a conversation (both windows), a dozen a day.
USAGE_WRAP_UP = CapabilityDef(
    id="usage_wrap_up",
    points=frozenset({Point.TICK, Point.RECORDS}),
    revision=2,
    departs_from=("A13", "A26"),
    compat="exact_thread_recovery",
    ceilings=Ceilings(per_day=12, per_conversation=2),
    journal_prefix="wrap",
    make=make_wrap_up,
    codes=("found", "sent", "delivered", "unknown", "superseded", "continued"),
    measurements=(Measurement.MT,),
    options=(Option(OptionKey.WRAP_FIVE_HOUR, PERCENTS, DEFAULT_WRAP, custom=PERCENT_RANGE),
             Option(OptionKey.WRAP_WEEKLY, PERCENTS, DEFAULT_WRAP, custom=PERCENT_RANGE),
             Option(OptionKey.STOP_WORDS_FIVE_HOUR, PERCENTS, DEFAULT_STOP_WORDS, custom=PERCENT_RANGE),
             Option(OptionKey.STOP_WORDS_WEEKLY, PERCENTS, DEFAULT_STOP_WORDS, custom=PERCENT_RANGE),
             Option(OptionKey.WRAP_STYLE, STYLES, DEFAULT_STYLE),
             Option(OptionKey.WRAP_RESET_TIME, SWITCH, ON),
             Option(OptionKey.WRAP_AFTER_RESET, SWITCH, ON),
             # v0.6.16 final: the windows it acts on, its own pair (the meter's pair decided for all three before).
             Option(OptionKey.WINDOW_FIVE_HOUR, SWITCH, ON),
             Option(OptionKey.WINDOW_WEEKLY, SWITCH, ON)),
    wordings=(WordingKey.WRAP_CUSTOM_FIVE_HOUR, WordingKey.WRAP_CUSTOM_WEEKLY),
    requires=("usage_meter",),
)

# Stop near a limit (v0.6.16-beta.4, item (h); Pause near a limit in v0.6.16-beta.3). At P8, when the meter's reading of
# a window switched on is at the person's stop percentage (97 by default, each its own), the window is marked held until
# its reset (state/meter.py) - at P3 HOLD for every record of core's, and the edition's own continuations waiting not
# handed to core (`holds`) - and each conversation switched on whose turn runs is stopped through the Codex app's own
# IPC channel (engine/usagestop.py, codex/ipc.py; measurement MIPC), falling back to the hold alone, with a notice, where
# it cannot; after the reset a conversation it stopped is continued once by a turn the app starts (Continue after the
# reset). A person's own messages, a wrap-up and anything typed in Codex are untouched. It departs from A2 (a turn
# started through the app's channel, not `codex queue`), B3 (Codex's state changed through that channel), C9 (it acts
# on the meter's reading) and H6 (a running turn is stopped), stands on usage_probe and rests on MU. Its ceilings are
# the schema's floor - one stop and one continuation a conversation a window. It requires the meter.
USAGE_PAUSE = CapabilityDef(
    id="usage_pause",
    points=frozenset({Point.GATES, Point.TICK}),
    revision=2,
    departs_from=("A2", "B3", "C9", "H6"),
    compat="usage_probe",
    ceilings=Ceilings(per_day=1, per_conversation=1),
    journal_prefix="pause",
    make=make_pause,
    codes=("paused", "resumed", "stopped", "not_stopped", "stop_unconfirmed", "held", "resume_unproven", "continued",
           "not_continued"),
    measurements=(Measurement.MU, Measurement.MIPC),
    options=(Option(OptionKey.PAUSE_FIVE_HOUR, PERCENTS, DEFAULT_PAUSE, custom=PERCENT_RANGE),
             Option(OptionKey.PAUSE_WEEKLY, PERCENTS, DEFAULT_PAUSE, custom=PERCENT_RANGE),
             # v0.6.16 final: the windows it acts on, its own pair, as the wrap-up's.
             Option(OptionKey.WINDOW_FIVE_HOUR, SWITCH, ON),
             Option(OptionKey.WINDOW_WEEKLY, SWITCH, ON)),
    requires=("usage_meter",),
)

# A weekly update check while idle (v0.6.18, the owner's list of 2026-10-21). At P8, at most once in seven days and only
# while core holds no recovery waiting, being sent or watched, it starts the very check the Dashboard's Check for updates
# runs - this installation's scripts/bootstrap.ps1 -CheckOnly, by Windows PowerShell's full path, CREATE_NO_WINDOW, the
# window's 120 s, never killed - on a thread of its own (engine/updatecheck.py); what that check offers, read as the
# window reads it (a newer release, or the pre-release a pressed check would offer), is one notice of its own kind whose
# button opens Diagnostics, where an update is installed. It downloads and installs nothing. An administrator's
# DisableUpdateCheck holds it. The time of the last check is a stamp in `options` (state/choices.py), kept before the
# check starts, so a failed or refused one waits a week too. It departs from C4 (it acts on a schedule, on its own), C5
# (the update check without a button pressed) and C7 (the compatibility data, which the check refreshes, refreshed
# from the watcher). It sends nothing to Codex and reads nothing of it; it stands on engine_present, the installation
# every recovery stands on, so a Codex the product cannot find holds it with them. Its ceilings are the schema's
# floor and never bind.
IDLE_UPDATE_CHECK = CapabilityDef(
    id="idle_update_check",
    points=frozenset({Point.TICK}),
    revision=1,
    departs_from=("C4", "C5", "C7"),
    compat="engine_present",
    ceilings=Ceilings(per_day=1, per_conversation=1),
    journal_prefix="update",
    make=make_idle_update_check,
    codes=("checked", "offered", "unanswered"),
)

# Longer reset messages (v0.6.14, the owner's answer of 2026-10-08): a message sent at a reset may be up to what one
# continuation carries (continuation.PROMPT_LIMIT, 8,154 characters) instead of A27's 2,000 - a separate opt-in, off
# until a person turns it on after its statement, which names A27. An action: it answers at no point and sends
# nothing; reset_message reads whether it stands on, and when it does not, a waiting message over 2,000 is cancelled.
# It requires nothing (v0.6.16-beta.3's audit of the registry for `requires`): it lengthens what reset_message and
# prompt_queue send, either one, so neither is a requirement - requiring one would turn on a feature a person who wants
# longer queued prompts never asked for. No capability of the registry before v0.6.16-beta.3 needs another; the pairs
# are new: the usage meter, which Wrap up near a limit and Pause near a limit require.
LONG_RESET_MESSAGE = CapabilityDef(
    id="long_reset_message",
    kind=CapabilityKind.ACTION,
    points=frozenset(),
    # Revision 2 (v0.6.15-beta): "Longer messages" - a queued prompt's too (engine/promptqueue.py).
    revision=2,
    departs_from=("A27",),
    compat=None,
    ceilings=None,
    journal_prefix="longmsg",
    make=make_long_messages,
)

# Open Codex on a notice (v0.6.18, the owner's list of 2026-10-21): while it stands on, a notice about one conversation
# offers Open Codex beside Open Dashboard, the Codex app's own link to that conversation (core's notify.codex_thread_uri,
# measured on Codex app 26.1007), opened by the card through notify.open_in_codex and by Windows' toast through the
# handler registered for `codex:` - and only where one is (control/opencodex.py reads Software\Classes\codex, never
# writes it). An action: core never asks it; the icon's surface says whether the button is offered, and core's
# notifier adds it. It departs from A28 (a button cancels one interruption or opens one page of the Dashboard), B16
# (Windows is asked only the listed content-free questions: the `codex:` key is read too) and F6 (explorer.exe, which
# opens the link, is not a listed process). The link only shows a conversation; nothing is sent (A1 kept).
OPEN_CODEX_BUTTON = CapabilityDef(
    id="open_codex_button",
    kind=CapabilityKind.ACTION,
    points=frozenset(),
    revision=1,
    departs_from=("A28", "B16", "F6"),
    compat=None,
    ceilings=None,
    journal_prefix="opencdx",
    make=make_open_codex_button,
)

# The compatibility report (v0.6.14 stage 3b, the plan's in-app report): this PC's own records written
# up as codex-compat-reporter writes them (report/records.py, evidence.py, document.py), shown whole in
# the Dashboard, saved where the person chooses, and sent to the project as a public pull request -
# through gh, the GitHub CLI the person installed, signed in as them - only after they type send. An
# action: it answers at no point, so core never asks it, nothing goes to Codex and no unit is spent; it
# stands on no compatibility capability, since a failing Codex is when a report matters most, and has no
# ceilings: one check or send at a time per home, and each send its own typed word for exactly the file
# and the writes shown, are its bounds (report/flow.py). It departs from B11 (gh reads the person's GitHub
# sign-in on the product's behalf), C1 and C2 (network work, by delegation, from a second shipped file),
# C3 (GitHub addresses beyond the two lists of releases), C8 (the person's GitHub identity and gh's own
# User-Agent), D1 (the report's counts go to the project), E8 (a hung gh, and one still running when the
# Dashboard's service ends, is ended), F3 (the file saved where the person chooses) and F6 (gh is not a
# listed process). It keeps G13 - a report grants nothing - and K5: a pause stops checking and sending.
COMPAT_REPORT = CapabilityDef(
    id="compat_report",
    kind=CapabilityKind.ACTION,
    points=frozenset(),
    revision=1,
    departs_from=("B11", "C1", "C2", "C3", "C8", "D1", "E8", "F3", "F6"),
    compat=None,
    ceilings=None,
    journal_prefix="rpt",
    make=make_compat_report,
    codes=("built", "saved", "checked", "sent", "partial", "refused", "lost"),
)

# In this order, which is also which answers first where two answer at one point; the action, which
# answers at none, last.
DEFINITIONS = (START_WITH_CODEX, GOAL_CONTINUATION, QUEUE_FOR_OPEN, COMPACT_CONTINUE, MODEL_FALLBACK, HEADLESS_RUN, OTHER_SESSIONS, MARKER_FREE, CAPACITY_RETRY, STRUCTURED_RULES,
               UNKNOWN_FAILURE_BUDGET, CODEX_GAVE_UP, SIGN_IN_RETRY, RESET_CREDIT, RESET_MESSAGE, EARLY_RESET,
               ONCE_MORE, SEND_NOW, PARALLEL_DISPATCH, PROMPT_QUEUE, EMPTY_RESPONSE, SUBAGENT_PARENT, KEEP_GOING,
               USAGE_METER, USAGE_WRAP_UP, USAGE_PAUSE, EVERY_CONVERSATION, SILENT_CONTINUATION, IDLE_UPDATE_CHECK,
               OPEN_CODEX_BUTTON, LONG_RESET_MESSAGE,
               COMPAT_REPORT)
# Codex's own retry settings (stage 4's item 6): Attempts (6, 8, 10 or 12; 8 by default) for both of its built-in
# provider's retry keys, written at P8 and put back (engine/retries.py). MB failed on codex-cli 0.162.0-alpha.17.2 -
# Codex refuses any write under model_providers.openai - so it waits in WAITING: hidden, its statement unwritten.
CODEX_RETRY_SETTINGS = CapabilityDef(
    id="codex_retry_settings",
    points=frozenset({Point.TICK}),
    revision=1,
    departs_from=("B3", "B4"),
    compat="engine_present",
    ceilings=Ceilings(per_day=1, per_conversation=1),
    journal_prefix="retry",
    make=make_retry_settings,
    options=(Option(OptionKey.ATTEMPTS, RETRY_ATTEMPTS, RETRY_DEFAULT_ATTEMPTS),),
    measurements=(Measurement.MB,),
)

# Continue inside the turn (v0.6.19, plans/v0619-design/D-stop-hook.md): a continuation of a short temporary failure
# carried inside the turn that failed, by this edition's Stop hook - a program Codex starts as the turn stops
# (gui/HookLauncher.cs, hook/handler.py) - in place of the watcher's queued message after the wait. The hook claims in
# core's file under core's claim's lock (engine/hookclaims.py): the watcher first, the hook passes; the hook first,
# core is held at P3 and at P11 (ledger.py) from a second continuation of the same interruption, and its units count
# in the caps on one conversation. Its declaration is written into this product's plugin copy only while it is on
# (control/hookplugin.py). It departs from A2 (a second channel: Codex's own hook answer, not `codex queue`), A5 (the
# claim is made by the hook's process, in the same transaction core's claim takes, not by core's claim), A26 (the
# continuation is carried as the hook's reason, not a queued message), B3 (Codex's state changes through the hook's
# declaration in the plugin copy) and F6 (Codex starts the hook's program, which is not a listed process). It stands on
# recovery_turn_tracking - the history it reads the failed turn from - and rests on M4 (a plugin's Stop hook runs after
# a failed turn, its row already written), M4B (Codex carries out the block: the turn goes on, without a console window)
# and MHK (the declaration's format on the engine in force). Hidden in WAITING until M4 and M4B both pass. Ceilings:
# core's own five a conversation a day, and two dozen a day in all.
STOP_HOOK = CapabilityDef(
    id="stop_hook_continuation",
    points=frozenset({Point.GATES}),
    revision=1,
    departs_from=("A2", "A5", "A26", "B3", "F6"),
    compat="recovery_turn_tracking",
    ceilings=Ceilings(per_day=24, per_conversation=CORE_DAILY_CAP),
    journal_prefix="shk",
    make=make_stop_hook,
    measurements=(Measurement.M4, Measurement.M4B, Measurement.MHK),
)

# The one gate for a capability that cannot work on any Codex measured so far (the owner's rule of 2026-10-16): each
# here, with the measurement that must pass first, is hidden - not in the registry this edition runs, so no row, no
# statement and no switch anywhere - until that measurement passes (measured.MEASURED), and then offered after
# DEFINITIONS. Its code and its probe stay in the tree. v0.6.19: a tuple of measurements is several, every one of which
# must pass (Continue inside the turn: M4 and M4B).
WAITING = ((CODEX_RETRY_SETTINGS, Measurement.MB),
           (STOP_HOOK, (Measurement.M4, Measurement.M4B)))


def offered(measured) -> tuple:
    """The waiting capabilities `measured` (measured.MEASURED's shape) lets out: those whose measurements all passed."""
    def passed(measurement):
        return (measured.get(measurement) or (None,))[0] == Verdict.PASS
    return tuple(definition for definition, measurement in WAITING
                 if all(passed(each) for each in (measurement if isinstance(measurement, tuple) else (measurement,))))


def _registry():
    from .measured import MEASURED
    return Registry(DEFINITIONS + offered(MEASURED))


REGISTRY = _registry()

# The order a person sees them in - the Dashboard's Advanced features page and every list arming.listing
# answers - which is not the order above: that one decides which answers first, and this one only what is
# read first. The owner's order, 2026-10-10 ("고급 기능 순서를 중요하고 많이 쓸만한거 순서대로 해줘. 그리고
# 호환성 보고서를 제일 위로 해줘"): the compatibility report at the top, then 1) what gets work going again
# after a usage limit with no hands, 2) what saves the person work, 3) the other common failures, 4) rare
# cases and expert settings. A measurement's warning never pushes a capability down. Every capability of
# DEFINITIONS appears here exactly once (test_advanced_registry holds it).
SHOWN_ORDER = ("compat_report", "start_with_codex",
               # v0.6.16-beta.3: which conversations are recovered at all, beside what starts the recovering.
               "every_conversation", "queue_for_open",
               # v0.6.16-beta.4: what gets a conversation going when nothing holds it, beside queue for opening (Q12).
               "headless_run", "other_sessions", "marker_free_continuation",
               # v0.6.16-beta.4: how a turn run here starts, beside the other continuation that goes without a marker
               # (DECISIONS Q12).
               "silent_continuation", "reset_credit",
               "early_reset", "parallel_dispatch", "reset_message", "long_reset_message",
               # v0.6.16-beta.3 (issue #29): the usage meter and what it serves, beside the other usage-limit features.
               "usage_meter", "usage_wrap_up", "usage_pause", "keep_going",
               "prompt_queue", "empty_response", "once_more_when_unsure", "send_now",
               # v0.6.18: Open Codex on a notice, beside Send now - both what a person does about one conversation.
               "open_codex_button", "capacity_retry",
               # v0.6.16-beta.4: what a failure of Codex's own is taken up with, beside the capacity retry (Q12).
               "compact_continue", "model_fallback",
               "codex_gave_up", "goal_continuation", "subagent_parent", "sign_in_retry", "unknown_failure_budget",
               # v0.6.18: the weekly update check, which recovers nothing, among the expert settings.
               "idle_update_check",
               "structured_rules")


# v0.6.19: where a capability that waits in WAITING is shown once it is offered - right after the one named, in the
# owner's order of 2026-10-22 - and until then in no list a person sees.
WAITING_PLACES = (("stop_hook_continuation", "marker_free_continuation"),)


def _placed(order, registry) -> tuple:
    """`order` with every capability of WAITING_PLACES that `registry` offers put in its place."""
    placed = list(order)
    for capability, after in WAITING_PLACES:
        if registry.get(capability) is not None and capability not in placed and after in placed:
            placed.insert(placed.index(after) + 1, capability)
    return tuple(placed)


SHOWN_ORDER = _placed(SHOWN_ORDER, REGISTRY)


def shown(registry) -> tuple:
    """`registry`'s capabilities in SHOWN_ORDER; any it does not name (a registry a test made) after
    them, in the registry's own order."""
    place = {capability: index for index, capability in enumerate(SHOWN_ORDER)}
    definitions = tuple(registry)
    return tuple(sorted(definitions, key=lambda definition: (place.get(definition.id, len(place)),
                                                             definitions.index(definition))))
