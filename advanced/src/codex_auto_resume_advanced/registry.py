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
and one waiting recovery a person asks to send now (control/sendnow.py); and, at no point, two actions: longer
reset messages, and the compatibility report (report/). The tests define one of their own to hold every
rule here.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Callable

from codex_auto_resume.domain.plug import Point

from .control.codexstart import make as make_start_with_codex
from .control.sendnow import make as make_send_now
from .engine.admitted import (ATTEMPTS, DEFAULT_ATTEMPTS, make_codex_gave_up, make_sign_in_retry,
                              make_structured_rules, make_unknown_failure_budget)
from .engine.capacity import CEILING_HOURS, DEFAULT_HOURS, make as make_capacity_retry
from .engine.credits import make as make_reset_credit
from .engine.resetmessage import make as make_reset_message, make_long as make_long_messages
from .engine.earlyreset import make as make_early_reset
from .engine.goal import make as make_goal_continuation
from .engine.markerfree import make as make_marker_free
from .engine.oncemore import make as make_once_more
from .report import make as make_compat_report
from .standards import DEPARTABLE
from .vocabulary import CapabilityKind, Measurement, OptionKey

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
    kind: CapabilityKind = CapabilityKind.ROUTE

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
            or not _count(option.default) or option.default not in option.choices)


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
    revision=1,
    departs_from=("0.5", "A2", "A11", "B3", "B4"),
    compat="loaded_state_detection",
    ceilings=Ceilings(per_day=12, per_conversation=3),
    journal_prefix="goal",
    make=make_goal_continuation,
    measurements=(Measurement.M2,),
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
# reads Codex's error code, not only a kind). It stands on transient_classification, the history
# table the failure's kind and code are read from, and rests on no measurement: core sends what it
# always sends. Its ceilings are core's capacity day, 48 in one conversation and in all, which only
# A20's departure allows.
CAPACITY_RETRY = CapabilityDef(
    id="capacity_retry",
    points=frozenset({Point.ADMISSION, Point.GATES}),
    revision=1,
    departs_from=("A20", "A21", "A22", "B9"),
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
# (only classified kinds), A26 (continuation text for a recovered kind) and B9 (it reads Codex's code),
# and stands on transient_classification. Its hits are counted (`matched`) the first time core goes on
# with what a rule took up. Ceilings: five a conversation, two dozen a day.
STRUCTURED_RULES = CapabilityDef(
    id="structured_rules",
    points=frozenset({Point.ADMISSION, Point.GATES}),
    revision=1,
    departs_from=("0.5", "A13", "A14", "A26", "B9"),
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
# A26 and B9 as the rules do, and from D2 too: a sample keeps a code Codex chose. Ceilings: three a
# conversation, a dozen a day.
UNKNOWN_FAILURE_BUDGET = CapabilityDef(
    id="unknown_failure_budget",
    points=frozenset({Point.ADMISSION, Point.GATES}),
    revision=1,
    departs_from=("0.5", "A13", "A14", "A26", "B9", "D2"),
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
    revision=1,
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

# Longer reset messages (v0.6.14, the owner's answer of 2026-10-08): a message sent at a reset may be up to what one
# continuation carries (continuation.PROMPT_LIMIT, 8,154 characters) instead of A27's 2,000 - a separate opt-in, off
# until a person turns it on after its statement, which names A27. An action: it answers at no point and sends
# nothing; reset_message reads whether it stands on, and when it does not, a waiting message over 2,000 is cancelled.
LONG_RESET_MESSAGE = CapabilityDef(
    id="long_reset_message",
    kind=CapabilityKind.ACTION,
    points=frozenset(),
    revision=1,
    departs_from=("A27",),
    compat=None,
    ceilings=None,
    journal_prefix="longmsg",
    make=make_long_messages,
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
DEFINITIONS = (START_WITH_CODEX, GOAL_CONTINUATION, MARKER_FREE, CAPACITY_RETRY, STRUCTURED_RULES,
               UNKNOWN_FAILURE_BUDGET, CODEX_GAVE_UP, SIGN_IN_RETRY, RESET_CREDIT, RESET_MESSAGE, EARLY_RESET,
               ONCE_MORE, SEND_NOW, LONG_RESET_MESSAGE, COMPAT_REPORT)
REGISTRY = Registry(DEFINITIONS)
